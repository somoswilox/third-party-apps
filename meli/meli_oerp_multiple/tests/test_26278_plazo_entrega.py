# -*- coding: utf-8 -*-
"""26.278 (#caso-K31): boton "Publicar Plazo" -- publica SOLO el sale_term MANUFACTURING_TIME.

Sin red: ML es un objeto falso que registra los GET/PUT. Se mide: que el PUT lleve SOLO
`sale_terms` (nada de titulo ni ficha), que la garantia vigente se reenvie intacta, que el plazo
salga del binding (o de la plantilla / el producto), y que sin plazo no se mande nada.
"""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.meli_oerp_multiple.models import connection_binding as CB

ITEM = "MLM831960444"
TERMS = [
    {"id": "WARRANTY_TYPE", "name": "Tipo de garantía", "value_id": "2230280", "value_name": "Garantía del vendedor"},
    {"id": "WARRANTY_TIME", "name": "Tiempo de garantía", "value_id": None, "value_name": "90 días",
     "value_struct": {"number": 90, "unit": "días"}},
    {"id": "MANUFACTURING_TIME", "value_id": None, "value_name": "5 días"},
]


class _Resp(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli(object):
    access_token = "x"

    def __init__(self, put_answer=None):
        self.gets, self.puts = [], []
        self.put_answer = put_answer or {"id": ITEM}

    def need_login(self):
        return False

    def get(self, path, *a, **k):
        self.gets.append(path)
        return _Resp({"id": ITEM, "title": "T" * 72, "sale_terms": [dict(t) for t in TERMS]})

    def put_mini(self, path, body, *a, **k):
        self.puts.append((path, body))
        return _Resp(dict(self.put_answer))


@tagged("post_install", "-at_install", "meli_26278")
class TestPlazoEntrega609(TransactionCase):

    def _crear_minimo(self, model, extra=None, _visitados=None):
        _visitados = _visitados or set()
        Model = self.env[model]
        vals = {}
        for name, f in Model._fields.items():
            if not f.required or f.compute or f.related or f.readonly:
                continue
            if f.type in ('char', 'text', 'html'):
                vals[name] = 'TEST'
            elif f.type == 'integer':
                vals[name] = 1
            elif f.type in ('float', 'monetary'):
                vals[name] = 1.0
            elif f.type == 'boolean':
                vals[name] = False
            elif f.type == 'date':
                vals[name] = fields.Date.today()
            elif f.type == 'datetime':
                vals[name] = fields.Datetime.now()
            elif f.type == 'selection':
                sel = f.selection(Model) if callable(f.selection) else f.selection
                vals[name] = sel[0][0] if sel else False
            elif f.type == 'many2one':
                rec = self.env[f.comodel_name].search([], limit=1)
                if not rec and f.comodel_name not in _visitados:
                    _visitados.add(f.comodel_name)
                    rec = self._crear_minimo(f.comodel_name, None, _visitados)
                vals[name] = rec.id if rec else False
        vals.update(extra or {})
        return Model.create(vals)

    def setUp(self):
        super().setUp()
        p = patch.object(type(self.env["mercadolibre.account"]), "_meli_instance_or_mine",
                         lambda this, meli=None: meli)
        p.start()
        self.addCleanup(p.stop)
        self.tmpl = self.env["product.template"].create({"name": "Cuerdas 609"})
        self.prod = self.tmpl.product_variant_ids[:1]
        try:
            self.bT = self._crear_minimo("mercadolibre.product_template", {
                "name": "Cuerdas 609", "product_tmpl_id": self.tmpl.id, "conn_id": ITEM})
            self.bV = self._crear_minimo("mercadolibre.product", {
                "name": "Cuerdas 609", "product_id": self.prod.id, "product_tmpl_id": self.tmpl.id,
                "binding_product_tmpl_id": self.bT.id, "conn_id": ITEM})
        except Exception as e:
            self.skipTest("No se pudieron crear las vinculaciones en esta base: %s" % e)

    def test_pura_reemplaza_el_plazo_y_conserva_la_garantia(self):
        out = CB.meli_sale_terms_with_manufacturing_time(TERMS, "2 días")
        self.assertEqual(out, [{"id": "WARRANTY_TYPE", "value_id": "2230280"},
                               {"id": "WARRANTY_TIME", "value_name": "90 días"},
                               {"id": "MANUFACTURING_TIME", "value_name": "2 días"}])
        self.assertEqual(CB.meli_sale_terms_with_manufacturing_time(None, "3 días"),
                         [{"id": "MANUFACTURING_TIME", "value_name": "3 días"}])

    def test_publica_solo_sale_terms(self):
        self.bV.meli_manufacturing_time = "2 días"
        meli = _FakeMeli()
        self.assertEqual(self.bV.product_post_manufacturing_time(meli=meli), {})
        self.assertEqual(len(meli.puts), 1)
        path, body = meli.puts[0]
        self.assertEqual(path, "/items/" + ITEM)
        self.assertEqual(list(body.keys()), ["sale_terms"], "solo sale_terms: ni titulo ni ficha")
        mt = [t for t in body["sale_terms"] if t["id"] == "MANUFACTURING_TIME"]
        self.assertEqual(mt, [{"id": "MANUFACTURING_TIME", "value_name": "2 días"}])
        self.assertIn({"id": "WARRANTY_TIME", "value_name": "90 días"}, body["sale_terms"])

    def test_plazo_de_la_plantilla(self):
        self.bV.meli_manufacturing_time = False
        self.bT.meli_manufacturing_time = "4 días"
        meli = _FakeMeli()
        self.assertEqual(self.bT.product_template_post_manufacturing_time(meli=meli), {})
        self.assertIn({"id": "MANUFACTURING_TIME", "value_name": "4 días"}, meli.puts[0][1]["sale_terms"])
        meli2 = _FakeMeli()
        self.assertEqual(self.bV.product_post_manufacturing_time(meli=meli2), {})
        self.assertIn({"id": "MANUFACTURING_TIME", "value_name": "4 días"}, meli2.puts[0][1]["sale_terms"])

    def test_sin_plazo_no_manda_nada(self):
        self.bV.meli_manufacturing_time = False
        self.bT.meli_manufacturing_time = False
        if "meli_manufacturing_time" in self.prod._fields:
            self.prod.meli_manufacturing_time = False
        meli = _FakeMeli()
        res = self.bV.product_post_manufacturing_time(meli=meli)
        self.assertEqual(res.get("error"), "sin_plazo")
        self.assertEqual(meli.puts, [])
        self.assertEqual(meli.gets, [])

    def test_rechazo_de_ml_se_muestra(self):
        self.bV.meli_manufacturing_time = "2 días"
        meli = _FakeMeli(put_answer={"error": "validation_error", "message": "invalid sale_terms"})
        with self.assertLogs("odoo.addons.meli_oerp_multiple.models.connection_binding", level="ERROR"):
            res = self.bV.product_post_manufacturing_time(meli=meli)
        self.assertEqual(res.get("error"), "validation_error")
        with patch.object(type(self.bV), "product_post_manufacturing_time", lambda this, **k: res):
            with self.assertRaises(UserError):
                self.bV.action_meli_post_manufacturing_time()
