# -*- coding: utf-8 -*-
"""caso-K51 (13.0 -> 16-20, 26.368): columna «Sub Status» de la pestaña Variantes — cada variante con SU estado de ML.

Caso real caso-K51 (2-nov-2026), DIN122 Corpiño Malla Top: NEG4 y ROJ2 activas en ML mostraban «out_of_stock».
product_get_meli_update inicializaba status / sub_status / links UNA vez antes del `for product in self`:
una variante que no trae sub_status (o da error, o no tiene meli_id) mostraba el valor de la anterior.

Sin red: meli.util.get_new_instance devuelve un meli falso (GET /items/<id> desde un dict) y
requests/urllib3 quedan bloqueados.
    odoo-bin -d <db> -u meli_oerp_multiple --test-enable --test-tags meli_K51_substatus --stop-after-init
"""
from unittest.mock import patch

import requests
import urllib3

from odoo.tests.common import TransactionCase, tagged


class FakeResp(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeMeli(object):
    def __init__(self, items):
        self.items = items
        self.access_token = "TEST"
        self.gets = []

    def need_login(self):
        return False

    def get(self, path, params=None):
        self.gets.append(path)
        return FakeResp(self.items.get(path.rsplit("/", 1)[-1], {"error": "not_found", "status": 404}))

    def put(self, *a, **k):
        raise AssertionError("PUT inesperado a ML: %r" % (a,))

    def post(self, *a, **k):
        raise AssertionError("POST inesperado a ML: %r" % (a,))


def _sin_red(*args, **kwargs):
    raise AssertionError("llamada de red real en un test: %r" % (args[1:3],))


@tagged("post_install", "-at_install", "meli_K51_substatus")
class TestK51SubStatus(TransactionCase):

    def setUp(self):
        super().setUp()
        env = self.env
        for target, attr in ((requests.sessions.Session, "request"), (urllib3.PoolManager, "urlopen")):
            p = patch.object(target, attr, _sin_red)
            p.start()
            self.addCleanup(p.stop)

        wh = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
        pricelist = env["product.pricelist"].search([], limit=1) or env["product.pricelist"].create({"name": "K51"})
        try:
            config = env["mercadolibre.configuration"].create({
                "name": "K51 substatus", "mode": "test", "company_id": env.company.id,
                "mercadolibre_pricelist": pricelist.id,
                "mercadolibre_buying_mode": "buy_it_now", "mercadolibre_currency": "ARS",
                "mercadolibre_stock_warehouse": wh.id, "mercadolibre_stock_warehouse_full": wh.id})
            # 16+: company.mercadolibre_connections = One2many por company_id
            self.account = env["mercadolibre.account"].create({
                "name": "K51 substatus", "type": "custom", "company_id": env.company.id,
                "country_id": env.ref("base.ar").id, "configuration": config.id,
                "meli_login_id": "K51SUB", "redirect_uri": "http://localhost/meli_login",
                "client_id": "K51SUB", "secret_key": "x", "seller_id": "1"})
        except Exception as e:
            self.skipTest("no se pudo crear configuracion/cuenta ML en esta base: %s" % e)
        self.assertEqual(env.company.mercadolibre_connections[:1], self.account)

        P = env["product.product"]
        # orden del for = orden del recordset: la 1ª trae out_of_stock, las siguientes NO deben heredarlo
        self.p_oos = P.create({"name": "DIN122NEG2", "meli_id": "MLA2244220428"})
        self.p_act = P.create({"name": "DIN122NEG4", "meli_id": "MLA1265252494"})
        self.p_err = P.create({"name": "DIN122ROJ3", "meli_id": "MLA0443284201"})
        self.p_sin = P.create({"name": "DIN122ROJ4"})
        self.p_act2 = P.create({"name": "DIN122ROJ2", "meli_id": "MLA2033097023"})
        self.items = {
            "MLA2244220428": {"id": "MLA2244220428", "status": "paused", "sub_status": ["out_of_stock"],
                              "permalink": "https://articulo.mercadolibre.com.ar/MLA-2244220428"},
            "MLA1265252494": {"id": "MLA1265252494", "status": "active", "sub_status": [],
                              "permalink": "https://articulo.mercadolibre.com.ar/MLA-1265252494"},
            "MLA2033097023": {"id": "MLA2033097023", "status": "active",
                              "permalink": "https://articulo.mercadolibre.com.ar/MLA-2033097023"},
        }
        self.meli = FakeMeli(self.items)
        test = self

        def new_instance(util, *a, **k):
            return test.meli

        p = patch.object(type(env["meli.util"]), "get_new_instance", new_instance)
        p.start()
        self.addCleanup(p.stop)
        self.recs = self.p_oos | self.p_act | self.p_err | self.p_sin | self.p_act2

    def _leer(self):
        self.env.invalidate_all()
        return {r["id"]: r for r in self.recs.read(["meli_status", "meli_sub_status", "meli_permalink_api"])}

    def test_1_activa_no_hereda_out_of_stock(self):
        r = self._leer()
        self.assertEqual((r[self.p_oos.id]["meli_status"], r[self.p_oos.id]["meli_sub_status"]), ("paused", "out_of_stock"))
        self.assertEqual(r[self.p_act.id]["meli_status"], "active")
        self.assertFalse(r[self.p_act.id]["meli_sub_status"], "NEG4 activa heredó el sub_status de NEG2")
        self.assertFalse(r[self.p_act2.id]["meli_sub_status"], "ROJ2 activa heredó un sub_status ajeno")

    def test_2_error_y_sin_meli_id_no_heredan(self):
        r = self._leer()
        self.assertEqual(r[self.p_err.id]["meli_status"], "not_found")
        self.assertFalse(r[self.p_err.id]["meli_sub_status"])
        self.assertFalse(r[self.p_err.id]["meli_permalink_api"], "la que dio error heredó el link de otra")
        self.assertEqual(r[self.p_sin.id]["meli_status"], "unknown", "sin meli_id heredó el status de otra")
        self.assertFalse(r[self.p_sin.id]["meli_sub_status"])
        self.assertFalse(r[self.p_sin.id]["meli_permalink_api"])

    def test_3_links_son_de_su_propia_publicacion(self):
        r = self._leer()
        self.assertIn("MLA1265252494", r[self.p_act.id]["meli_permalink_api"])
        self.assertIn("MLA2033097023", r[self.p_act2.id]["meli_permalink_api"])
        # solo se consultan las publicaciones de las variantes con meli_id (guarda de no-regresion)
        self.assertEqual({g.rsplit("/", 1)[-1] for g in self.meli.gets if g.startswith("/items/")},
                         {"MLA2244220428", "MLA1265252494", "MLA0443284201", "MLA2033097023"})
