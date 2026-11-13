# -*- coding: utf-8 -*-
"""26.384 (#caso-K21 cliente F, 8-nov-2026) — el push de stock de una vinculacion hermana NO activa el item legacy.

Caso real: producto SKU 1418165 con DOS publicaciones. product.meli_id (campo legacy de meli_oerp) =
MLA2613019228, cuya vinculacion de plantilla estaba bloqueada (meli_update_stock_blocked) y pausada por el
vendedor. El cron Post Stock empujo la hermana MLA2722407127 y x_product_post_stock, despues del PUT de stock,
hacia `if product.meli_status == "paused": product.product_meli_status_active()` sobre el item LEGACY:
PUT /items/MLA2613019228 {status: active} sin mirar ningun bloqueo.

Sin red: meli falso (registra los PUT), fetch_meli_product y _meli_available_quantity parcheados, y
requests/urllib3 bloqueados (cualquier llamada real hace fallar el test).
    odoo-bin -d <db> -u meli_oerp_multiple --test-enable --test-tags meli_26384 --stop-after-init
"""
from unittest.mock import patch

import requests
import urllib3

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

SKU = "1418165"
LEGACY = "MLA2613019228"   # bloqueada + paused_by_seller
SISTER = "MLA2722407127"   # hermana activa, otro user_product
MUTE = ('odoo.sql_db', 'odoo.addons.meli_oerp_multiple.models.product',
        'odoo.addons.meli_oerp_multiple.models.connection_binding',
        'odoo.addons.meli_oerp_multiple.models.connection_account',
        'odoo.addons.meli_oerp.models.product')


class FakeResp(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeMeli(object):
    def __init__(self, account, items):
        self.client_id = account.client_id
        self.seller_id = account.seller_id
        self.access_token = "TEST"
        self.items = items
        self.puts = []

    def need_login(self):
        return False

    def put_mini(self, path, body=None, params=None, *a, **k):
        self.puts.append((path, dict(body or {})))
        return FakeResp({"id": path})

    put = put_mini

    def get(self, path, params=None, *a, **k):
        mid = str(path).split("?")[0].rstrip("/").split("/")[-1]
        if str(path).startswith("/items/") and mid in self.items:
            return FakeResp(dict(self.items[mid]))
        return FakeResp({"error": "not_found", "status": 404})

    def post(self, path, body=None, params=None, *a, **k):
        raise AssertionError("POST inesperado a ML: %s" % path)


def _sin_red(*args, **kwargs):
    raise AssertionError("llamada de red real en un test: %r" % (args[1:3],))


@tagged("post_install", "-at_install", "meli_26384")
class Test26384ActivaLegacy(TransactionCase):

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

        wh = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
        pricelist = env["product.pricelist"].search([], limit=1) or env["product.pricelist"].create({"name": "K21"})
        try:
            self.config = env["mercadolibre.configuration"].create({
                "name": "K21 test", "mode": "test", "company_id": env.company.id,
                "mercadolibre_cron_post_update_stock": True, "mercadolibre_pricelist": pricelist.id,
                "mercadolibre_buying_mode": "buy_it_now", "mercadolibre_currency": "ARS",
                "mercadolibre_stock_warehouse": wh.id, "mercadolibre_stock_warehouse_full": wh.id})
            self.account = env["mercadolibre.account"].create({
                "name": "K21 test", "type": "custom", "company_id": env.company.id,
                "country_id": env.ref("base.ar").id, "configuration": self.config.id,
                "meli_login_id": "K21TEST", "redirect_uri": "http://localhost/meli_login",
                "client_id": "K21TEST", "secret_key": "x", "seller_id": "K21"})
        except Exception as e:
            self.skipTest("no se pudo crear configuracion/cuenta ML en esta base: %s" % e)
        if "meli_cron_stock_minutes" in self.account._fields:
            self.account.meli_cron_stock_minutes = False

        self.items = {
            LEGACY: {"id": LEGACY, "status": "paused", "sub_status": ["paused_by_seller"],
                     "available_quantity": 20, "variations": [], "seller_custom_field": SKU,
                     "shipping": {"logistic_type": "xd_drop_off"}},
            SISTER: {"id": SISTER, "status": "active", "sub_status": [],
                     "available_quantity": 20, "variations": [], "seller_custom_field": SKU,
                     "shipping": {"logistic_type": "xd_drop_off"}},
        }
        self.meli = FakeMeli(self.account, self.items)

        self.tmpl = env["product.template"].create(dict(self._ptype(), name="Cuaderno Modelo 2027 Diseño"))
        self.product = self.tmpl.product_variant_ids[:1]
        self.product.default_code = SKU
        self.product.meli_id = LEGACY

        self.bindT_legacy = env["mercadolibre.product_template"].create({
            "name": "bindT legacy", "connection_account": self.account.id, "conn_id": LEGACY,
            "product_tmpl_id": self.tmpl.id, "meli_update_stock_blocked": True})
        self.bindT_sister = env["mercadolibre.product_template"].create({
            "name": "bindT sister", "connection_account": self.account.id, "conn_id": SISTER,
            "product_tmpl_id": self.tmpl.id})
        self.b_legacy = self._bind(LEGACY, self.bindT_legacy)
        self.b_sister = self._bind(SISTER, self.bindT_sister)

        def fetch(acc, meli_id=None, meli=None, **kw):
            it = test.items.get(meli_id)
            return dict(it) if it else None

        PB = type(env["mercadolibre.product"])
        self.target_activations = []
        patches = [
            (type(env["mercadolibre.account"]), "fetch_meli_product", fetch),
            (type(env["product.product"]), "_meli_available_quantity", lambda *a, **k: 20.0),
            (type(env["product.product"]), "_meli_update_logistic_type", lambda *a, **k: False),
            (PB, "product_meli_status_active",
             lambda recs, *a, **k: test.target_activations.extend(recs.mapped("conn_id")) or {}),
        ]
        if hasattr(PB, "_fetch_meli_user_product_id"):
            patches.append((PB, "_fetch_meli_user_product_id", lambda *a, **k: False))
        for cls, attr, fn in patches:
            p = patch.object(cls, attr, fn)
            p.start()
            self.addCleanup(p.stop)

    def _bind(self, conn_id, bindT):
        return self.env["mercadolibre.product"].create({
            "name": self.product.display_name, "connection_account": self.account.id,
            "conn_id": conn_id, "meli_id": conn_id,
            "product_id": self.product.id, "product_tmpl_id": self.tmpl.id,
            "binding_product_tmpl_id": bindT.id})

    def _activaciones(self, mid):
        return [p for p, b in self.meli.puts if p.rstrip("/").endswith("/items/" + mid) and b.get("status") == "active"]

    def test_01_push_de_la_hermana_no_activa_el_legacy_bloqueado(self):
        """Caso caso-K21: empujar la hermana con stock NO manda PUT status=active al item legacy bloqueado."""
        with mute_logger(*MUTE):
            self.b_sister.product_post_stock(meli=self.meli)
        stock_puts = [p for p, b in self.meli.puts if SISTER in p and "available_quantity" in b]
        self.assertTrue(stock_puts, "control: el stock de la hermana se tiene que publicar (%r)" % self.meli.puts)
        self.assertEqual(self._activaciones(LEGACY), [], "se activo el item legacy bloqueado: %r" % self.meli.puts)

    def test_02_push_de_la_vinculacion_bloqueada_no_publica(self):
        """Control: la vinculacion bloqueada no publica ni activa (ya funcionaba)."""
        with mute_logger(*MUTE):
            res = self.b_legacy.product_post_stock(meli=self.meli)
        self.assertIn("blocked", str(res))
        self.assertEqual(self.meli.puts, [])

    def test_03_activacion_de_producto_respeta_el_bloqueo(self):
        """Defensa en profundidad: product_meli_status_active no activa un meli_id con vinculacion bloqueada."""
        with mute_logger(*MUTE):
            self.product.product_meli_status_active(meli=self.meli)
        self.assertEqual(self._activaciones(LEGACY), [])
        with mute_logger(*MUTE):
            self.product.with_context(meli_activate_force=True).product_meli_status_active(meli=self.meli)
        self.assertEqual(len(self._activaciones(LEGACY)), 1, "el bypass explicito tiene que activar")

    def test_04_sin_bloqueo_la_activacion_de_producto_sigue_andando(self):
        """Control: sin bloqueo, la activacion directa del producto sigue haciendo su PUT."""
        self.bindT_legacy.meli_update_stock_blocked = False
        with mute_logger(*MUTE):
            self.product.product_meli_status_active(meli=self.meli)
        self.assertEqual(len(self._activaciones(LEGACY)), 1)
