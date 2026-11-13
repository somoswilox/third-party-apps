# -*- coding: utf-8 -*-
"""#caso-K36-caso-K37 (cliente P, 22-oct-2026): al publicar en MLM3390 (Cartas Coleccionables T.C.G) el atributo
obligatorio «Tipo de producto» (PRODUCT_TYPE, tipo LISTA con 9 valores) llegaba con el nombre del set
("Hyperia City") y ML rechazaba: "Attribute [PRODUCT_TYPE] is not valid, item values [(null:Hyperia City)]".

El pre-flight #caso-K40 sólo miraba que el atributo ESTUVIERA. Ahora, para los obligatorios de tipo lista,
el valor tiene que ser uno de la lista (por id o por nombre, sin importar mayúsculas ni acentos);
si no, aviso en castellano con los valores válidos y NO se llama a ML.

Sin red: ML es un objeto falso y los pasos de armado del body/imágenes quedan parcheados.
"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

NEW = 'MLM9037919853'
LISTA = ['Sobre de cartas', 'Caja de sobres', 'Booster bundle', 'Blíster', 'Caja de entrenador élite',
         'Lata', 'Mazo', 'Caja de colección', 'Carta suelta']
CAT_ATTS = [
    {'id': 'BRAND', 'name': 'Marca', 'value_type': 'string', 'tags': {'required': True}},
    {'id': 'PRODUCT_TYPE', 'name': 'Tipo de producto', 'value_type': 'list',
     'tags': {'catalog_required': True, 'required': True},
     'values': [{'id': str(1000 + i), 'name': n} for i, n in enumerate(LISTA)]},
    {'id': 'LANGUAGE', 'name': 'Idioma', 'value_type': 'list', 'tags': {},
     'values': [{'id': '7001', 'name': 'Español'}, {'id': '7002', 'name': 'Inglés'}]},
]


class _Resp(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli(object):
    access_token = 'x'

    def __init__(self):
        self.gets, self.puts, self.posts = [], [], []

    def get(self, path, *a, **k):
        self.gets.append(path)
        return _Resp({})

    def put(self, path, body, *a, **k):
        self.puts.append((path, body))
        return _Resp({'id': NEW})

    def post(self, path, body, *a, **k):
        self.posts.append((path, body))
        return _Resp({'id': NEW, 'status': 'active'})


@tagged('post_install', '-at_install', 'meli_K36_K37')
class TestAtributoListaK36(TransactionCase):

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
        self.atts = []
        PP = type(self.env['product.product'])
        mod = 'odoo.addons.meli_oerp_multiple.models.product'
        spy = self
        patches = [
            patch.object(PP, '_product_post_set_basic_configuration', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_template_configuration', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_title', lambda *a, **k: None),
            patch.object(PP, 'set_meli_price', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_price', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_attributes', lambda *a, **k: [dict(x) for x in spy.atts]),
            patch.object(PP, '_product_post_set_category', lambda *a, **k: None),
            patch.object(PP, '_meli_get_category_attributes', lambda *a, **k: CAT_ATTS),
            patch.object(PP, '_product_post_set_quantity', lambda *a, **k: None),
            patch.object(PP, 'product_meli_upload_image', lambda *a, **k: {}),
            patch.object(PP, 'product_meli_upload_multi_images', lambda *a, **k: {}),
            patch.object(PP, '_product_post_set_body', lambda *a, **k: ({'title': 'T', 'pictures': []}, {})),
            patch.object(PP, '_product_set_variations', lambda this, body=None, **k: body),
            patch(mod + '.get_first_image_to_publish', lambda *a, **k: 'img'),
            patch(mod + '.variant_image_ids', lambda *a, **k: []),
            patch(mod + '.template_image_ids', lambda *a, **k: []),
            patch.object(type(self.env['mercadolibre.account']), 'fetch_meli_product',
                         lambda this, meli_id=None, meli=None: {'id': meli_id, 'status': 'active'}),
            patch.object(type(self.env['mercadolibre.product_template']), 'copy_from_rjson', lambda *a, **k: None),
            # el aviso del pre-flight hace cr.rollback(): en el test se neutraliza para no perder el setUp
            patch.object(self.env.cr, 'rollback', lambda *a, **k: None),
        ]
        if hasattr(PP, '_meli_family_selector_attributes'):
            patches.append(patch.object(PP, '_meli_family_selector_attributes', lambda *a, **k: []))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        try:
            categ = self._crear_minimo('mercadolibre.category', {
                'name': 'Cartas Coleccionables T.C.G', 'meli_category_id': 'MLM3390'})
        except Exception as e:
            self.skipTest("No se pudo crear la categoria ML en esta base: %s" % e)
        self.tmpl = self.env['product.template'].create({'name': 'Carta Pokemon (test K36)'})
        self.prod = self.tmpl.product_variant_ids[:1]
        self.tmpl.write({'meli_category': categ.id, 'meli_pub': True})
        self.prod.write({'meli_category': categ.id, 'meli_pub': True})

    def _post(self, atts):
        self.atts = atts
        meli = _FakeMeli()
        res = self.prod._product_post(meli=meli, config=self.env.company)
        w = self.env['meli.warning'].search([], order='id desc', limit=1)
        return meli, w

    def test_valor_fuera_de_lista_no_publica_y_explica(self):
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, w = self._post([{'id': 'BRAND', 'value_name': 'Pokemon'},
                                  {'id': 'PRODUCT_TYPE', 'value_name': 'Hyperia City'}])
        self.assertFalse(meli.posts, "con un valor fuera de la lista no debe llamar a ML")
        msg = w.message or ''
        self.assertIn('Tipo de producto', msg)
        self.assertIn('Hyperia City', msg)
        self.assertIn('Carta suelta', msg)
        self.assertIn('Mercado Libre sólo acepta', msg)

    def test_valor_de_lista_sin_acentos_ni_mayusculas_publica(self):
        # Control positivo: "blister" == "Blíster" (pasa con y sin el fix).
        meli, w = self._post([{'id': 'BRAND', 'value_name': 'Pokemon'},
                              {'id': 'PRODUCT_TYPE', 'value_name': 'blister'}])
        self.assertEqual(len(meli.posts), 1)

    def test_valor_por_id_publica(self):
        meli, w = self._post([{'id': 'BRAND', 'value_name': 'Pokemon'},
                              {'id': 'PRODUCT_TYPE', 'value_id': '1008'}])
        self.assertEqual(len(meli.posts), 1)

    def test_lista_no_obligatoria_no_bloquea(self):
        # Atributo de lista NO obligatorio con valor libre: no lo frena el pre-flight (lo decide ML).
        meli, w = self._post([{'id': 'BRAND', 'value_name': 'Pokemon'},
                              {'id': 'PRODUCT_TYPE', 'value_name': 'Carta suelta'},
                              {'id': 'LANGUAGE', 'value_name': 'Japonés'}])
        self.assertEqual(len(meli.posts), 1)

    def test_faltante_orienta_al_mapeo_si_existe(self):
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, w = self._post([{'id': 'BRAND', 'value_name': 'Pokemon'}])
        self.assertFalse(meli.posts)
        msg = w.message or ''
        self.assertIn('Tipo de producto', msg)
        if 'meli_oerp.attribute.mapping' in self.env:
            self.assertIn('Mapeo de Atributos', msg)
