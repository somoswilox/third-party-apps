# -*- coding: utf-8 -*-
"""26.375 — caso-K10 cliente G: «Stock por depósito: Odoo vs Mercado Libre» + reglas de stock por depósito (#739).

(1) Vista: el asistente lee GET /user-products/{id}/stock UNA vez (al abrir / releer), compara cada depósito ML con
    la ubicación Odoo mapeada (mismo cálculo que publica 26.363) y guarda el estado en la vinculación
    (badge, columna, filtro). Al publicar por depósito el estado se actualiza SIN otra llamada a ML.
(2) Reglas de stock con «Depósitos ML»: con el flag de la cuenta, la regla de un depósito gana a la general, y el
    modo «umbral» publica 0 en ese depósito si hay menos de K. Sin flag, sólo cuentan las reglas sin depósitos.

Sin red: meli falso, requests/urllib3 bloqueados.
    odoo-bin -d <db> -u meli_oerp_multiple --test-enable --test-tags meli_26375 --stop-after-init
"""
from unittest.mock import patch

import requests
import urllib3

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

MID = "MLA1211320822"
UPID = "MLAU505336"
MUTE = ('odoo.sql_db', 'odoo.addons.meli_oerp_multiple.models.product',
        'odoo.addons.meli_oerp_multiple.models.connection_binding',
        'odoo.addons.meli_oerp_multiple.models.connection_account',
        'odoo.addons.meli_oerp_multiple.models.meli_wh_stock',
        'odoo.addons.meli_oerp_stock.models.product')


class FakeResp(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeMeli(object):
    def __init__(self, account, locations):
        self.client_id = account.client_id
        self.seller_id = account.seller_id
        self.access_token = "TEST"
        self.locations = locations
        self.puts = []
        self.gets = 0
        self.stock_error = None

    def need_login(self):
        return False

    def get_user_product_stock_with_version(self, upid, token=None, *a, **k):
        self.gets += 1
        if self.stock_error:
            return dict(self.stock_error), None
        return {"locations": [dict(l) for l in self.locations]}, "7"

    def put_mini(self, path, body=None, params=None, *a, **k):
        self.puts.append((path, body))
        return FakeResp({"id": path})

    put = put_mini

    def get(self, path, params=None, *a, **k):
        return FakeResp({"error": "not_found", "status": 404})

    def post(self, path, body=None, params=None, *a, **k):
        raise AssertionError("POST inesperado a ML: %s" % path)


def _sin_red(*args, **kwargs):
    raise AssertionError("llamada de red real en un test: %r" % (args[1:3],))


@tagged("post_install", "-at_install", "meli_26375")
class Test26375(TransactionCase):

    def _ptype(self):
        PT = self.env["product.template"]
        if "is_storable" in PT._fields:
            return {"type": "consu", "is_storable": True}
        return {"type": "product"}

    def setUp(self):
        super().setUp()
        env = self.env
        for target, attr in ((requests.sessions.Session, "request"), (urllib3.PoolManager, "urlopen")):
            p = patch.object(target, attr, _sin_red)
            p.start()
            self.addCleanup(p.stop)
        test = self
        p = patch.object(type(env["meli.util"]), "get_new_instance", lambda *a, **k: test.meli)
        p.start()
        self.addCleanup(p.stop)

        self.wh = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
        pricelist = env["product.pricelist"].search([], limit=1) or env["product.pricelist"].create({"name": "K10"})
        try:
            self.config = env["mercadolibre.configuration"].create({
                "name": "K10 test 375", "mode": "test", "company_id": env.company.id,
                "mercadolibre_cron_post_update_stock": True, "mercadolibre_pricelist": pricelist.id,
                "mercadolibre_buying_mode": "buy_it_now", "mercadolibre_currency": "ARS",
                "mercadolibre_stock_warehouse": self.wh.id, "mercadolibre_stock_warehouse_full": self.wh.id,
                "mercadolibre_stock_update_mode": "auto"})
            self.account = env["mercadolibre.account"].create({
                "name": "K10 test 375", "type": "custom", "company_id": env.company.id,
                "country_id": env.ref("base.ar").id, "configuration": self.config.id,
                "meli_login_id": "K10TEST375", "redirect_uri": "http://localhost/meli_login",
                "client_id": "K10TEST375", "secret_key": "x", "seller_id": "K10",
                "user_product_seller": True, "multiwarehouse": True})
        except Exception as e:
            self.skipTest("no se pudo crear configuracion/cuenta ML en esta base: %s" % e)
        if "meli_cron_stock_minutes" in self.account._fields:
            self.account.meli_cron_stock_minutes = False

        Loc = env["stock.location"]
        self.l1 = Loc.create({"name": "BocFl 375", "usage": "internal", "location_id": self.wh.lot_stock_id.id})
        self.l2 = Loc.create({"name": "Cba 375", "usage": "internal", "location_id": self.wh.lot_stock_id.id})
        self.l3 = Loc.create({"name": "MisPi 375", "usage": "internal", "location_id": self.wh.lot_stock_id.id})
        self.config.write({"publish_stock": True,
                           "publish_stock_locations": [(6, 0, (self.l1 | self.l2 | self.l3).ids)]})
        self.product = env["product.product"].create(dict(self._ptype(), name="21345 MC LASER", default_code="21345"))
        Quant = env["stock.quant"]
        Quant._update_available_quantity(self.product, self.l1, 5)
        Quant._update_available_quantity(self.product, self.l2, 3)
        Quant._update_available_quantity(self.product, self.l3, 2)

        SL = env["mercadolibre.account.stock_location"]
        self.m1 = SL.create({"account_id": self.account.id, "meli_store_id": "S1", "network_node_id": "N1",
                             "name": "Boca Flex", "odoo_location_id": self.l1.id,
                             "services_stock_location": "self_service"})
        self.m2 = SL.create({"account_id": self.account.id, "meli_store_id": "S2", "network_node_id": "N2",
                             "name": "Cordoba", "odoo_location_id": self.l2.id,
                             "services_stock_location": "xd_drop_off"})
        self.m3 = SL.create({"account_id": self.account.id, "meli_store_id": "S3", "network_node_id": "N3",
                             "name": "Sin mapear"})
        self.ml_locs = [
            {"type": "seller_warehouse", "store_id": "S1", "network_node_id": "N1", "quantity": 10},
            {"type": "seller_warehouse", "store_id": "S2", "network_node_id": "N2", "quantity": 0},
            {"type": "seller_warehouse", "store_id": "S3", "network_node_id": "N3", "quantity": 4},
            {"type": "meli_facility", "network_node_id": "ARFULL", "quantity": 7},
        ]
        self.meli = FakeMeli(self.account, self.ml_locs)

        self.bindT = env["mercadolibre.product_template"].create({
            "name": "bindT", "connection_account": self.account.id, "conn_id": MID,
            "product_tmpl_id": self.product.product_tmpl_id.id})
        self.bind = env["mercadolibre.product"].create({
            "name": self.product.display_name, "connection_account": self.account.id,
            "conn_id": MID, "meli_id": MID, "product_id": self.product.id,
            "product_tmpl_id": self.product.product_tmpl_id.id, "binding_product_tmpl_id": self.bindT.id,
            "meli_user_product_id": UPID})
        self.product.mercadolibre_bindings = [(4, self.bind.id)]
        self.items = {MID: {"id": MID, "status": "active", "user_product_id": UPID, "available_quantity": 14,
                            "seller_sku": "21345"}}

        def fetch(acc, meli_id=None, meli=None, **kw):
            return test.items.get(meli_id)

        PB = type(env["mercadolibre.product"])
        patches = [
            (type(env["mercadolibre.account"]), "fetch_meli_product", fetch),
            (type(env["product.product"]), "_meli_update_logistic_type", lambda *a, **k: False),
            (type(env["product.product"]), "product_meli_status_active", lambda *a, **k: {}),
            (PB, "product_meli_status_active", lambda *a, **k: {}),
        ]
        if hasattr(PB, "_fetch_meli_user_product_id"):
            patches.append((PB, "_fetch_meli_user_product_id", lambda *a, **k: UPID))
        for cls, attr, fn in patches:
            p = patch.object(cls, attr, fn)
            p.start()
            self.addCleanup(p.stop)

    def _open(self):
        self.assertTrue(hasattr(self.bind, "action_meli_wh_stock_open"), "falta la vista de depósitos (fix 26.375)")
        with mute_logger(*MUTE):
            action = self.bind.action_meli_wh_stock_open()
        self.assertEqual(action["res_model"], "mercadolibre.product.wh.stock")
        return self.env["mercadolibre.product.wh.stock"].browse(action["res_id"])

    def _by_name(self, wiz):
        return {l.name: l for l in wiz.line_ids}

    # ---------- (1) vista ----------

    def test_01_tabla_por_deposito(self):
        wiz = self._open()
        self.assertEqual(self.meli.gets, 1, "UNA lectura de ML por apertura")
        rows = self._by_name(wiz)
        self.assertEqual((rows["Boca Flex"].qty_odoo, rows["Boca Flex"].qty_ml, rows["Boca Flex"].state), (5, 10, "diff"))
        self.assertEqual(rows["Boca Flex"].logistic, "FLEX")
        self.assertEqual(rows["Boca Flex"].odoo_location_id, self.l1)
        self.assertIn("-5", rows["Boca Flex"].state_label)
        self.assertEqual((rows["Cordoba"].qty_odoo, rows["Cordoba"].qty_ml, rows["Cordoba"].state), (3, 0, "diff"))
        self.assertIn("en 0", rows["Cordoba"].state_label)
        self.assertEqual(rows["Sin mapear"].state, "unmapped_ml")
        self.assertFalse(rows["Sin mapear"].has_odoo)
        mispi = wiz.line_ids.filtered(lambda l: l.odoo_location_id == self.l3)
        self.assertEqual((mispi.state, mispi.qty_odoo, mispi.has_ml), ("unmapped_odoo", 2, False))
        full = wiz.line_ids.filtered(lambda l: l.loc_type == "meli_facility")
        self.assertEqual((full.state, full.qty_ml), ("ml_managed", 7))
        # Total: depósitos propios en ML (10+0+4) vs Odoo de los mapeados (5+3)
        self.assertEqual((wiz.total_ml, wiz.total_odoo), (14, 8))
        # estado guardado en la vinculación
        self.assertEqual(self.bind.meli_wh_state, "diff")
        self.assertEqual((self.bind.meli_wh_diff_count, self.bind.meli_wh_qty_ml, self.bind.meli_wh_qty_odoo), (2, 14, 8))
        self.assertTrue(self.bind.meli_wh_date)
        self.assertEqual(self.bind.meli_wh_badge, "Depósitos ML: 14 u.")
        self.assertIn(self.bind, self.env["mercadolibre.product"].search([("meli_wh_state", "=", "diff")]))

    def test_02_igual_salvo_deposito_sin_mapeo(self):
        self.ml_locs[0]["quantity"] = 5
        self.ml_locs[1]["quantity"] = 3
        self._open()
        self.assertEqual(self.bind.meli_wh_state, "unmapped")
        self.ml_locs.pop(2)
        self._open()
        self.assertEqual(self.bind.meli_wh_state, "ok")
        self.assertEqual(self.bind.meli_wh_qty_ml, 8)

    def test_03_deposito_mapeado_que_ml_no_lista(self):
        self.ml_locs[:] = [l for l in self.ml_locs if l.get("store_id") != "S2"]
        wiz = self._open()
        cba = self._by_name(wiz)["Cordoba"]
        self.assertEqual((cba.state, cba.qty_odoo, cba.has_ml), ("missing_ml", 3, False))

    def test_04_error_de_ml(self):
        self.meli.stock_error = {"error": "not_found", "status": 404, "message": "user product"}
        wiz = self._open()
        self.assertTrue(wiz.error)
        self.assertFalse(wiz.line_ids)
        self.assertEqual(self.bind.meli_wh_state, "error")

    def test_05_sin_user_product_no_llama_a_ml(self):
        self.bind.meli_user_product_id = False
        wiz = self._open()
        self.assertTrue(wiz.error)
        self.assertEqual(self.meli.gets, 0)

    def test_06_publicar_por_deposito_actualiza_sin_red_extra(self):
        self.account.meli_stock_by_location_mapping = True
        with mute_logger(*MUTE):
            self.bind.product_post_stock(meli=self.meli)
        self.assertEqual(self.meli.gets, 1, "sólo el GET que ya hacía la publicación")
        self.assertEqual(self.bind.meli_wh_state, "unmapped", "S3 sin mapeo: se reenvía lo que tenía")
        self.assertEqual((self.bind.meli_wh_qty_ml, self.bind.meli_wh_qty_odoo), (12, 8))  # 5+3+4 / 5+3

    def test_07_publicar_total_invalida_la_comparacion(self):
        self._open()
        self.assertEqual(self.bind.meli_wh_state, "diff")
        with mute_logger(*MUTE):
            self.bind.product_post_stock(meli=self.meli)
        self.assertEqual(self.bind.meli_wh_state, "none")

    def test_08_botones_del_asistente(self):
        self.account.meli_stock_by_location_mapping = True
        wiz = self._open()
        with mute_logger(*MUTE):
            action = wiz.action_publish()
        self.assertTrue([p for p, b in self.meli.puts if "/stock/type/seller_warehouse" in str(p)])
        self.assertEqual(action["res_model"], "mercadolibre.product.wh.stock")
        self.assertEqual(self.meli.gets, 3, "abrir + publicar + releer")
        edit = wiz.action_edit_mapping()
        self.assertEqual(edit["res_model"], "mercadolibre.account.stock_location")
        self.assertEqual(edit["domain"], [("account_id", "=", self.account.id)])
        self.assertEqual(wiz.action_reload()["res_model"], "mercadolibre.product.wh.stock")

    def test_09_ficha_de_producto(self):
        self.assertEqual(self.product.meli_wh_state, "none")
        self.assertEqual(self.product.meli_wh_badge, "Depósitos ML: comparar")
        self.assertEqual(self.product.meli_wh_binding_count, 1)
        action = self.product.action_meli_wh_stock_open()
        self.assertEqual(action["res_model"], "mercadolibre.product.wh.stock")
        self.product.invalidate_recordset()
        self.assertEqual(self.product.meli_wh_state, "diff")
        self.assertEqual(self.product.product_tmpl_id.meli_wh_qty_ml, 14)

    # ---------- (2) reglas de stock por depósito (#caso-K69) ----------

    def _rule(self, **vals):
        Rule = self.env["meli_oerp.sku.rule"]
        self.assertIn("meli_stock_location_ids", Rule._fields, "falta el alcance por depósito (fix 26.375)")
        n = len(self.config.mercadolibre_stock_sku_mapping)
        return Rule.create(dict({"name": "r375 %s" % n, "type": "stock", "configuration_id": self.config.id}, **vals))

    def _post_body(self):
        self.meli.puts[:] = []
        with mute_logger(*MUTE):
            self.bind.product_post_stock(meli=self.meli)
        puts = [(p, b) for p, b in self.meli.puts if "/stock/type/seller_warehouse" in str(p)]
        self.assertTrue(puts, self.meli.puts)
        return {l["store_id"]: l["quantity"] for l in puts[0][1]["locations"]}

    def test_10_umbral_en_un_deposito(self):
        self.account.meli_stock_by_location_mapping = True
        self._rule(sku="*", meli_stock_rule_mode="umbral", security_quantity_stock_to_pause=4,
                   meli_stock_location_ids=[(6, 0, self.m2.ids)])
        self.assertEqual(self._post_body(), {"S1": 5, "S2": 0, "S3": 4}, "Cordoba 3 < 4 => 0; Boca Flex sin regla")

    def test_11_deposito_especifico_gana_a_todos(self):
        self.account.meli_stock_by_location_mapping = True
        self._rule(sku="*", security_quantity_stock_to_pause=1)                       # resguardo 1, todos
        self._rule(sku="*", security_quantity_stock_to_pause=4,                       # resguardo 4, Boca Flex
                   meli_stock_location_ids=[(6, 0, self.m1.ids)])
        self.assertEqual(self._post_body(), {"S1": 1, "S2": 2, "S3": 4})

    def test_12_sin_flag_solo_reglas_sin_deposito(self):
        self._rule(sku="*", meli_stock_rule_mode="umbral", security_quantity_stock_to_pause=100,
                   meli_stock_location_ids=[(6, 0, self.m1.ids)])
        q = self.product._meli_available_quantity(meli_id=MID, config=self.config)
        self.assertEqual(q, 10, "la regla del depósito no cuenta sin el flag (5+3+2 publicables)")
        self._rule(sku="21345", meli_stock_rule_mode="umbral", security_quantity_stock_to_pause=100)
        self.assertEqual(self.product._meli_available_quantity(meli_id=MID, config=self.config), 0)

    def test_13_vista_usa_las_reglas_del_deposito(self):
        self.account.meli_stock_by_location_mapping = True
        self._rule(sku="*", meli_stock_rule_mode="umbral", security_quantity_stock_to_pause=4,
                   meli_stock_location_ids=[(6, 0, self.m2.ids)])
        self.ml_locs[0]["quantity"] = 5
        rows = self._by_name(self._open())
        self.assertEqual((rows["Cordoba"].qty_odoo, rows["Cordoba"].state), (0, "ok"),
                         "Odoo publicaría 0 en Cordoba (umbral) y ML tiene 0")
