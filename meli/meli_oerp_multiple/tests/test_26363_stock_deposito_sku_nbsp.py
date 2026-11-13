# -*- coding: utf-8 -*-
"""26.363 — caso-K10 cliente G: (1) stock por depósito ML desde el mapeo «Depósitos ML»; (2) SKU con U+00A0.

(1) Cuenta multi-depósito (seller_warehouse, 12 depósitos ML): x_product_post_stock publicaba el libre TOTAL de
todas las ubicaciones y lo repartía en proporción a lo que ML ya tenía por store_id; el mapeo store_id →
ubicación Odoo sólo se usaba para las ventas. Con `meli_stock_by_location_mapping` cada depósito recibe el stock
de SU ubicación; un depósito sin ubicación mapeada no se toca (se reenvía lo que ML ya tenía).
(2) MLA2330354629: SKU en ML 'PKPSR014-PK RUBICAT CLASSIC X 5K\\xa0X\\xa02U' (espacios no separables) contra la
Referencia interna con espacios comunes ⇒ search_meli_product no matcheaba y el wizard dejaba la pub MISSING.

Sin red: meli falso (registra PUT y responde el GET /stock), requests/urllib3 bloqueados.
    odoo-bin -d <db> -u meli_oerp_multiple --test-enable --test-tags meli_26363 --stop-after-init
"""
from unittest.mock import patch

import requests
import urllib3

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

try:
    from odoo.addons.meli_oerp_multiple.models.meli_util import meli_norm_sku
except ImportError:  # control sobre un origin sin el fix: el test de la funcion falla, los demas corren
    meli_norm_sku = None

MID = "MLA2330354629"
UPID = "MLAU524314"
SKU_ML = "PKPSR014-PK RUBICAT CLASSIC X 5K\xa0X\xa02U"
SKU_ODOO = "PKPSR014-PK RUBICAT CLASSIC X 5K X 2U"
MUTE = ('odoo.sql_db', 'odoo.addons.meli_oerp_multiple.models.product',
        'odoo.addons.meli_oerp_multiple.models.connection_binding',
        'odoo.addons.meli_oerp_multiple.models.connection_account',
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

    def need_login(self):
        return False

    def get_user_product_stock_with_version(self, upid, token=None, *a, **k):
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


@tagged("post_install", "-at_install", "meli_26363")
class Test26363NormSku(TransactionCase):

    def test_norm_sku(self):
        self.assertIsNotNone(meli_norm_sku, "falta meli_norm_sku (fix 26.363)")
        self.assertEqual(meli_norm_sku(SKU_ML), SKU_ODOO)
        self.assertEqual(meli_norm_sku("​ AB C ﻿"), "AB C")
        self.assertEqual(meli_norm_sku([SKU_ML, "X"]), [SKU_ODOO, "X"])
        self.assertIsNone(meli_norm_sku(None))
        self.assertFalse(meli_norm_sku(False))


@tagged("post_install", "-at_install", "meli_26363")
class Test26363(TransactionCase):

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
                "name": "K10 test", "mode": "test", "company_id": env.company.id,
                "mercadolibre_cron_post_update_stock": True, "mercadolibre_pricelist": pricelist.id,
                "mercadolibre_buying_mode": "buy_it_now", "mercadolibre_currency": "ARS",
                "mercadolibre_stock_warehouse": self.wh.id, "mercadolibre_stock_warehouse_full": self.wh.id,
                "mercadolibre_stock_update_mode": "auto"})
            self.account = env["mercadolibre.account"].create({
                "name": "K10 test", "type": "custom", "company_id": env.company.id,
                "country_id": env.ref("base.ar").id, "configuration": self.config.id,
                "meli_login_id": "K10TEST", "redirect_uri": "http://localhost/meli_login",
                "client_id": "K10TEST", "secret_key": "x", "seller_id": "K10",
                "user_product_seller": True, "multiwarehouse": True})
        except Exception as e:
            self.skipTest("no se pudo crear configuracion/cuenta ML en esta base: %s" % e)
        if "meli_cron_stock_minutes" in self.account._fields:
            self.account.meli_cron_stock_minutes = False

        Loc = env["stock.location"]
        self.l1 = Loc.create({"name": "BocFl K10", "usage": "internal", "location_id": self.wh.lot_stock_id.id})
        self.l2 = Loc.create({"name": "Cba K10", "usage": "internal", "location_id": self.wh.lot_stock_id.id})
        self.product = env["product.product"].create(dict(self._ptype(), name="21345 MC LASER", default_code="21345"))
        Quant = env["stock.quant"]
        Quant._update_available_quantity(self.product, self.l1, 5)
        Quant._update_available_quantity(self.product, self.l2, 3)

        SL = env["mercadolibre.account.stock_location"]
        self.m1 = SL.create({"account_id": self.account.id, "meli_store_id": "S1", "network_node_id": "N1",
                             "name": "Boca Flex", "odoo_location_id": self.l1.id})
        self.m2 = SL.create({"account_id": self.account.id, "meli_store_id": "S2", "network_node_id": "N2",
                             "name": "Cordoba", "odoo_location_id": self.l2.id})
        self.m3 = SL.create({"account_id": self.account.id, "meli_store_id": "S3", "network_node_id": "N3",
                             "name": "Sin mapear"})
        # lo que ML ya tiene en cada depósito
        self.ml_locs = [
            {"type": "seller_warehouse", "store_id": "S1", "network_node_id": "N1", "quantity": 10},
            {"type": "seller_warehouse", "store_id": "S2", "network_node_id": "N2", "quantity": 0},
            {"type": "seller_warehouse", "store_id": "S3", "network_node_id": "N3", "quantity": 4},
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
        self.items = {MID: {"id": MID, "status": "active", "user_product_id": UPID, "available_quantity": 14,
                            "seller_sku": SKU_ML}}

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

    def _locs(self, existing=True):
        return [{"store_id": l["store_id"], "network_node_id": l["network_node_id"],
                 "existing_qty": l["quantity"] if existing else 0} for l in self.ml_locs]

    def _stock_puts(self):
        return [(p, b) for p, b in self.meli.puts if "/stock/type/seller_warehouse" in str(p)]

    # ---------- (1) stock por depósito: helper ----------

    def test_helper_flag_apagado_devuelve_none(self):
        self.assertIn("meli_stock_by_location_mapping", self.account._fields, "falta el flag (fix 26.363)")
        self.assertFalse(self.account.meli_stock_by_location_mapping)
        self.assertIsNone(self.product._meli_stock_locations_by_mapping(
            self.account, self._locs(), meli_id=MID, meli=self.meli, config=self.config))

    def test_helper_por_deposito_y_sin_mapeo_no_se_toca(self):
        self.account.meli_stock_by_location_mapping = True
        with mute_logger(*MUTE):
            out = self.product._meli_stock_locations_by_mapping(
                self.account, self._locs(), meli_id=MID, meli=self.meli, config=self.config)
        self.assertEqual(out, [
            {"quantity": 5, "store_id": "S1", "network_node_id": "N1"},   # stock de BocFl caso-K10
            {"quantity": 3, "store_id": "S2", "network_node_id": "N2"},   # stock de Cba caso-K10
            {"quantity": 4, "store_id": "S3", "network_node_id": "N3"},   # sin mapeo: lo que ML ya tenía
        ])

    def test_helper_mapea_por_nodo_si_no_hay_store(self):
        self.account.meli_stock_by_location_mapping = True
        locs = [{"store_id": None, "network_node_id": "N2", "existing_qty": 9}]
        with mute_logger(*MUTE):
            out = self.product._meli_stock_locations_by_mapping(
                self.account, locs, meli_id=MID, meli=self.meli, config=self.config)
        self.assertEqual(out, [{"quantity": 3, "network_node_id": "N2"}])

    def test_helper_nada_mapeado_cae_al_reparto(self):
        self.account.meli_stock_by_location_mapping = True
        (self.m1 | self.m2).write({"odoo_location_id": False})
        with mute_logger(*MUTE):
            self.assertIsNone(self.product._meli_stock_locations_by_mapping(
                self.account, self._locs(), meli_id=MID, meli=self.meli, config=self.config))

    def test_helper_no_negativos(self):
        self.account.meli_stock_by_location_mapping = True
        self.env["stock.quant"]._update_available_quantity(self.product, self.l2, -10)
        with mute_logger(*MUTE):
            out = self.product._meli_stock_locations_by_mapping(
                self.account, self._locs(), meli_id=MID, meli=self.meli, config=self.config)
        self.assertEqual(out[1]["quantity"], 0)

    # ---------- (1) stock por depósito: de punta a punta (PUT armado) ----------

    def test_post_stock_flag_apagado_reparto_proporcional_como_antes(self):
        """Control del comportamiento anterior: total 8 (5+3) repartido según 10/0/4 ⇒ 6/0/2."""
        with mute_logger(*MUTE):
            self.bind.product_post_stock(meli=self.meli)
        puts = self._stock_puts()
        self.assertTrue(puts, self.meli.puts)
        self.assertEqual([l["quantity"] for l in puts[0][1]["locations"]], [6, 0, 2])

    def test_post_stock_por_deposito(self):
        self.account.meli_stock_by_location_mapping = True
        with mute_logger(*MUTE):
            self.bind.product_post_stock(meli=self.meli)
        puts = self._stock_puts()
        self.assertTrue(puts, self.meli.puts)
        self.assertEqual(puts[0][0], "/user-products/%s/stock/type/seller_warehouse" % UPID)
        self.assertEqual(puts[0][1]["locations"], [
            {"quantity": 5, "store_id": "S1", "network_node_id": "N1"},
            {"quantity": 3, "store_id": "S2", "network_node_id": "N2"},
            {"quantity": 4, "store_id": "S3", "network_node_id": "N3"},
        ])

    # ---------- (2) SKU con U+00A0 ----------

    def test_fetch_meli_sku_normaliza(self):
        self.assertEqual(self.account.fetch_meli_sku(meli_id=MID, meli=self.meli, rjson=self.items[MID]), SKU_ODOO)

    def test_search_meli_product_encuentra_sku_con_nbsp(self):
        prod = self.env["product.product"].create(dict(self._ptype(), name="Rubicat x2", default_code=SKU_ODOO))
        with mute_logger(*MUTE):
            product_id, binding, status = self.account.search_meli_product(
                meli_id="MLA0000543", meli=self.meli, rjson={"id": "MLA0000543", "seller_sku": SKU_ML})
        self.assertEqual(product_id, prod)
        self.assertFalse(status["missing"])
        # y si el llamador pasa el SKU crudo (con U+00A0), también
        with mute_logger(*MUTE):
            product_id, binding, status = self.account.search_meli_product(
                meli_id="MLA0000543", seller_sku=SKU_ML, meli=self.meli, rjson={"id": "MLA0000543"})
        self.assertEqual(product_id, prod)
