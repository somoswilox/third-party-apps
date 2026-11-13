# -*- coding: utf-8 -*-
"""26.337 — port 16-20 del fix caso-K51 (13.0.26.336): cron Post Stock publica en UNA variacion.

Caso real caso-K51 (29-oct-2026), MLA1430074051 Pijama Nicolle Naira 701: Talle 1 y Talle 2 con el MISMO SKU
NICNAIK05ROSCHI1 en Odoo y en ML. x_product_post_stock recorria TODAS las variaciones de ML y hacia PUT a cada
una que matcheaba por barcode/SKU/combinacion, sin dar prioridad a la variacion vinculada:
  - con el binding exacto, la otra variacion con el mismo SKU disparaba "Changing binding variant" y el
    preflight de conflicto devolvia SIN publicar (el talle nunca recibia su stock), o publicaba en las dos;
  - sin variacion vinculada, el stock de un talle salia a las dos variaciones.
En el cron, la fila que fallaba se deshacia (savepoint P6) pero quedaba NULL: encabezaba la cola cada ciclo.

Sin red: meli falso (registra los PUT), fetch_meli_product y _meli_available_quantity parcheados, y
requests/urllib3 bloqueados (cualquier llamada real hace fallar el test).
    odoo-bin -d <db> -u meli_oerp_multiple --test-enable --test-tags meli_K51_stock_dup --stop-after-init
"""
from datetime import timedelta
from unittest.mock import patch

import requests
import urllib3

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

SKU = "NICNAIK05ROSCHI1"
MID = "MLA1430074051"
V1, V2 = 192080759249, 192080759251
MUTE = ('odoo.sql_db', 'odoo.addons.meli_oerp_multiple.models.product',
        'odoo.addons.meli_oerp_multiple.models.connection_binding',
        'odoo.addons.meli_oerp_multiple.models.connection_account')


class FakeResp(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeMeli(object):
    """Lo minimo de meli.util que usa el camino de stock 16-20. Registra los PUT."""

    def __init__(self, account):
        self.client_id = account.client_id
        self.seller_id = account.seller_id
        self.access_token = "TEST"
        self.puts = []

    def need_login(self):
        return False

    def put_mini(self, path, body=None, params=None, *a, **k):
        self.puts.append((path, dict(body or {})))
        return FakeResp({"id": path})

    put = put_mini

    def get(self, path, params=None, *a, **k):
        return FakeResp({"error": "not_found", "status": 404})

    def post(self, path, body=None, params=None, *a, **k):
        raise AssertionError("POST inesperado a ML: %s" % path)


def _sin_red(*args, **kwargs):
    raise AssertionError("llamada de red real en un test: %r" % (args[1:3],))


@tagged("post_install", "-at_install", "meli_K51_stock_dup")
class TestK51StockSkuDup(TransactionCase):

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

        def _meli_falso(*a, **k):
            # cualquier camino que pida una instancia (p.ej. el compute de meli_status) recibe el ML falso: la red
            # real sigue bloqueada (requests/urllib3) y todo PUT queda registrado y se compara exacto.
            return test.meli
        p = patch.object(type(env["meli.util"]), "get_new_instance", _meli_falso)
        p.start()
        self.addCleanup(p.stop)

        wh = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
        pricelist = env["product.pricelist"].search([], limit=1) or env["product.pricelist"].create({"name": "K51"})
        try:
            self.config = env["mercadolibre.configuration"].create({
                "name": "K51 test", "mode": "test", "company_id": env.company.id,
                "mercadolibre_cron_post_update_stock": True, "mercadolibre_pricelist": pricelist.id,
                "mercadolibre_buying_mode": "buy_it_now", "mercadolibre_currency": "ARS",
                "mercadolibre_stock_warehouse": wh.id, "mercadolibre_stock_warehouse_full": wh.id})
            self.account = env["mercadolibre.account"].create({
                "name": "K51 test", "type": "custom", "company_id": env.company.id,
                "country_id": env.ref("base.ar").id, "configuration": self.config.id,
                "meli_login_id": "K51TEST", "redirect_uri": "http://localhost/meli_login",
                "client_id": "K51TEST", "secret_key": "x", "seller_id": "K51"})
        except Exception as e:
            self.skipTest("no se pudo crear configuracion/cuenta ML en esta base: %s" % e)
        if "meli_cron_stock_minutes" in self.account._fields:
            self.account.meli_cron_stock_minutes = False
        self.meli = FakeMeli(self.account)

        talle = env["product.attribute"].create({"name": "Talle K51", "create_variant": "always"})
        t1 = env["product.attribute.value"].create({"name": "1", "attribute_id": talle.id})
        t2 = env["product.attribute.value"].create({"name": "2", "attribute_id": talle.id})
        self.tmpl = env["product.template"].create(dict(self._ptype(), **{
            "name": "Pijama Nicolle Naira 701",
            "attribute_line_ids": [(0, 0, {"attribute_id": talle.id, "value_ids": [(6, 0, [t1.id, t2.id])]})]}))
        self.tmpl.meli_pub_as_variant = True
        vs = self.tmpl.product_variant_ids
        self.p1 = vs.filtered(lambda p: t1 in p.product_template_attribute_value_ids.mapped("product_attribute_value_id"))
        self.p2 = vs.filtered(lambda p: t2 in p.product_template_attribute_value_ids.mapped("product_attribute_value_id"))
        # el dato del cliente: los DOS talles con el mismo SKU
        self.p1.default_code = SKU
        self.p2.default_code = SKU
        self.qty = {self.p1.id: 1.0, self.p2.id: 0.0}

        self.bindT = env["mercadolibre.product_template"].create({
            "name": "bindT", "connection_account": self.account.id, "conn_id": MID,
            "product_tmpl_id": self.tmpl.id})
        self.b1 = self._bind(self.p1, V1)
        self.b2 = self._bind(self.p2, V2)

        self.items = {MID: {"id": MID, "status": "active", "variations": [
            {"id": V1, "seller_custom_field": SKU, "price": 100, "available_quantity": 1,
             "attribute_combinations": [{"name": "Talle K51", "value_name": "1"}]},
            {"id": V2, "seller_custom_field": SKU, "price": 100, "available_quantity": 0,
             "attribute_combinations": [{"name": "Talle K51", "value_name": "2"}]},
        ]}}
        test = self

        def fetch(acc, meli_id=None, meli=None, **kw):
            return test.items.get(meli_id)

        def qty(prod, meli_id=None, meli=None, config=None, **kw):
            return test.qty.get(prod.id, 0.0)

        PB = type(env["mercadolibre.product"])
        patches = [
            (type(env["mercadolibre.account"]), "fetch_meli_product", fetch),
            (type(env["product.product"]), "_meli_available_quantity", qty),
            (type(env["product.product"]), "_meli_update_logistic_type", lambda *a, **k: False),
            (type(env["product.product"]), "product_meli_status_active", lambda *a, **k: {}),
            (PB, "product_meli_status_active", lambda *a, **k: {}),
        ]
        if hasattr(PB, "_fetch_meli_user_product_id"):
            patches.append((PB, "_fetch_meli_user_product_id", lambda *a, **k: False))
        for cls, attr, fn in patches:
            p = patch.object(cls, attr, fn)
            p.start()
            self.addCleanup(p.stop)

    def _bind(self, product, var_id, conn_id=MID, tmpl_bind=None, tmpl=None):
        return self.env["mercadolibre.product"].create({
            "name": product.display_name, "connection_account": self.account.id,
            "conn_id": conn_id, "meli_id": conn_id,
            "conn_variation_id": var_id and str(var_id), "meli_id_variation": var_id and str(var_id),
            "product_id": product.id, "product_tmpl_id": (tmpl or self.tmpl).id,
            "binding_product_tmpl_id": (tmpl_bind or self.bindT).id})

    def _puts(self):
        return [(p.rsplit("/", 1)[-1], b.get("available_quantity")) for p, b in self.meli.puts]

    # ---------- 1. SKU duplicado entre dos variantes ----------

    def test_binding_exacto_gana_sobre_sku_duplicado(self):
        """T2 (stock 0) vinculada a V2: un PUT, a V2, con 0. Nunca a V1; el binding no se toca."""
        with mute_logger(*MUTE):
            self.b2.product_post_stock(meli=self.meli)
        self.assertEqual(self._puts(), [(str(V2), 0)])
        self.assertEqual(self.b2.conn_variation_id, str(V2))
        self.meli.puts[:] = []
        with mute_logger(*MUTE):
            self.b1.product_post_stock(meli=self.meli)
        self.assertEqual(self._puts(), [(str(V1), 1)])
        self.assertEqual(self.b1.conn_variation_id, str(V1))

    def test_sku_ambiguo_sin_binding_no_publica(self):
        """Sin variacion vinculada y SKU en 2 variantes: 0 PUT, aviso, fila marcada revision_error."""
        self.b2.write({"conn_variation_id": False, "meli_id_variation": False})
        with mute_logger(*MUTE):
            res = self.b2.product_post_stock(meli=self.meli)
        self.assertEqual(self._puts(), [])
        self.assertTrue(res and "error" in res, res)
        self.assertIn("SKU ambiguo", str(res))
        self.assertEqual(self.b2.meli_stock_status, "revision_error")
        self.assertFalse(self.b2.conn_variation_id)

    def test_binding_inexistente_en_ml_y_sku_unico_revincula(self):
        """El binding apunta a una variacion que ML ya no tiene; el SKU es unico: re-vincula y publica 1 vez."""
        self.p2.default_code = SKU[:-1] + "2"
        self.items[MID]["variations"][1]["seller_custom_field"] = SKU[:-1] + "2"
        self.b2.write({"conn_variation_id": "999", "meli_id_variation": "999"})
        with mute_logger(*MUTE):
            self.b2.product_post_stock(meli=self.meli)
        self.assertEqual(self._puts(), [(str(V2), 0)])
        self.assertEqual(self.b2.conn_variation_id, str(V2))

    # ---------- 2. la cola: una fila que viola la unique no sale a ML y no encabeza la cola ----------

    def _cola(self):
        """3 filas NULL: la 1a re-vincularia a una variacion que YA tiene otro binding (unique); 2 sanas."""
        env = self.env
        color = env["product.attribute"].create({"name": "Color K51", "create_variant": "always"})
        ca = env["product.attribute.value"].create({"name": "Negro", "attribute_id": color.id})
        cb = env["product.attribute.value"].create({"name": "Blanco", "attribute_id": color.id})
        tb = env["product.template"].create(dict(self._ptype(), **{
            "name": "Corinto 2749",
            "attribute_line_ids": [(0, 0, {"attribute_id": color.id, "value_ids": [(6, 0, [ca.id, cb.id])]})]}))
        tb.meli_pub_as_variant = True
        va = tb.product_variant_ids.filtered(lambda p: ca in p.product_template_attribute_value_ids.mapped("product_attribute_value_id"))
        vb = tb.product_variant_ids - va
        va.default_code = "COR2749"
        vb.default_code = "COR2749-B"
        bT = env["mercadolibre.product_template"].create({
            "name": "bT", "connection_account": self.account.id, "conn_id": "MLA1467760482",
            "product_tmpl_id": tb.id})
        self.items["MLA1467760482"] = {"id": "MLA1467760482", "status": "active", "variations": [
            {"id": 1001, "seller_custom_field": "COR2749", "price": 1, "available_quantity": 1}]}
        self._bind(vb, 1001, conn_id="MLA1467760482", tmpl_bind=bT, tmpl=tb)        # ya tiene la 1001
        mala = self._bind(va, 999, conn_id="MLA1467760482", tmpl_bind=bT, tmpl=tb)  # 999 ya no existe en ML
        sanas = self.b1 | self.b2
        filas = mala | sanas
        env.flush_all()
        env.cr.execute("UPDATE mercadolibre_product SET meli_stock_status=NULL, stock_update=NULL, meli_last_status='active'"
                       " WHERE id IN %s", (tuple(filas.ids),))
        env.cr.execute("UPDATE mercadolibre_product SET meli_stock_status='updated' WHERE connection_account=%s"
                       " AND NOT id IN %s", (self.account.id, tuple(filas.ids)))
        env.invalidate_all()
        return mala, sanas

    def test_cola_fila_con_unique_no_sale_a_ml_ni_frena_el_lote(self):
        mala, sanas = self._cola()
        with mute_logger(*MUTE):
            self.account.meli_update_remote_stock(meli=self.meli)
        self.env.cr.execute("SELECT 1")          # el cursor sigue sano
        self.env.invalidate_all()
        # la fila mala: NINGUN PUT a su publicacion, binding intacto, marcada con error (va al fondo)
        self.assertFalse([p for p, b in self.meli.puts if "MLA1467760482" in p], self.meli.puts)
        self.assertEqual(mala.conn_variation_id, "999")
        self.assertEqual(mala.meli_stock_status, "revision_error", mala.stock_error)
        self.assertTrue(mala.stock_update)
        # las sanas se procesaron igual, cada una a SU variacion
        self.assertEqual(sorted(self._puts()), sorted([(str(V1), 1), (str(V2), 0)]))
        for b in sanas:
            self.assertNotIn(b.meli_stock_status, (False, None, "revision_error"), b.stock_error)

    def test_cola_excepcion_en_una_fila_se_aisla_y_se_marca(self):
        """Cualquier excepcion (incl. de DB al flush) en una fila: rollback SOLO de esa fila, queda marcada."""
        mala, sanas = self._cola()
        orig = type(self.env["mercadolibre.product"]).product_post_stock

        def post(binds, *a, **k):
            if binds.id == mala.id:
                # escritura local y despues una excepcion (en 16/17 la unique revienta en el flush; en 18 una base
                # nueva no tiene el indice unico): el savepoint de la fila tiene que deshacer la escritura.
                binds.write({"conn_variation_id": "1001"})
                binds.env.flush_all()
                raise RuntimeError("duplicate key value violates unique constraint (simulada)")
            return orig(binds, *a, **k)

        with patch.object(type(self.env["mercadolibre.product"]), "product_post_stock", post), mute_logger(*MUTE):
            self.account.meli_update_remote_stock(meli=self.meli)
        self.env.cr.execute("SELECT 1")
        self.env.invalidate_all()
        self.assertEqual(mala.conn_variation_id, "999")
        self.assertEqual(mala.meli_stock_status, "revision_error", mala.stock_error)
        self.assertTrue(mala.stock_update)
        self.assertEqual(sorted(self._puts()), sorted([(str(V1), 1), (str(V2), 0)]))

    def test_cola_revision_error_reciente_no_se_reintenta(self):
        """Reintento acotado: una fila en revision_error de hace < 6 h no vuelve a la cola, aunque
        el re-queue N1 la vea con movimientos posteriores al ultimo push."""
        mala, sanas = self._cola()
        with mute_logger(*MUTE):
            self.account.meli_update_remote_stock(meli=self.meli)
        self.env.invalidate_all()
        self.assertEqual(mala.meli_stock_status, "revision_error")
        if "meli_stock_moves_update" in mala._fields:
            mala.meli_stock_moves_update = fields.Datetime.now() + timedelta(minutes=1)
            self.env.flush_all()
        self.meli.puts[:] = []
        calls = []
        orig = type(self.env["mercadolibre.product"]).product_post_stock

        def post(binds, *a, **k):
            calls.append(binds.id)
            return orig(binds, *a, **k)

        with patch.object(type(self.env["mercadolibre.product"]), "product_post_stock", post), mute_logger(*MUTE):
            self.account.meli_update_remote_stock(meli=self.meli)
        self.assertNotIn(mala.id, calls)
