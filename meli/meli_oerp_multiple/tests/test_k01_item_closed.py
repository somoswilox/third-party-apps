# -*- coding: utf-8 -*-
"""#caso-K12 (cliente B caso-K01, 21-oct-2026): publicar un producto cuya publicacion vinculada esta CERRADA o
DADA DE BAJA en Mercado Libre hacia PUT /items/<id> y ML respondia 400 BODY_INVALID_FIELDS.

Caso real: PMG11527 -> MLM6993352331 (under_review / forbidden), plantilla simple, binding 3451.
  closed / deleted  => se publica NUEVA (POST) y se re-vincula todo lo que apuntaba al id viejo.
  forbidden         => no PUT, no POST: error claro; con force_meli_new_pub => POST.
  activa (control)  => PUT como siempre.

Sin red: ML es un objeto falso; los pasos de armado del body/imagenes quedan parcheados (lo que se
prueba es la DECISION PUT/POST y el re-vinculo).
"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

OLD = 'MLM6015410269'
NEW = 'MLM9054326430'


class _Resp(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli(object):
    access_token = 'x'

    def __init__(self, item):
        self.item = item
        self.gets, self.puts, self.posts = [], [], []

    def get(self, path, *a, **k):
        self.gets.append(path)
        return _Resp(dict(self.item))

    def put_mini(self, path, body, *a, **k):
        self.puts.append((path, body))
        return _Resp({'id': OLD})

    put = put_mini

    def post(self, path, body, *a, **k):
        self.posts.append((path, body))
        return _Resp({'id': NEW, 'status': 'active'})


@tagged('post_install', '-at_install', 'meli_K01')
class TestItemClosed611(TransactionCase):

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
        self.body_meli_id = []
        PP = type(self.env['product.product'])
        mod = 'odoo.addons.meli_oerp_multiple.models.product'
        spy = self

        def _body(this, product_tmpl=None, product=None, **kw):
            spy.body_meli_id.append(product.meli_id)
            return {'title': 'T', 'pictures': []}, {}

        patches = [
            patch.object(PP, '_product_post_set_basic_configuration', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_template_configuration', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_title', lambda *a, **k: None),
            patch.object(PP, 'set_meli_price', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_price', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_attributes', lambda *a, **k: []),
            patch.object(PP, '_product_post_set_category', lambda *a, **k: None),
            patch.object(PP, '_meli_preflight_missing_required_attributes', lambda *a, **k: []),
            patch.object(PP, '_product_post_set_quantity', lambda *a, **k: None),
            patch.object(PP, 'product_meli_upload_image', lambda *a, **k: {}),
            patch.object(PP, 'product_meli_upload_multi_images', lambda *a, **k: {}),
            patch.object(PP, '_product_post_set_body', _body),
            patch.object(PP, '_product_set_variations', lambda this, body=None, **k: body),
            patch(mod + '.get_first_image_to_publish', lambda *a, **k: 'img'),
            patch(mod + '.variant_image_ids', lambda *a, **k: []),
            patch(mod + '.template_image_ids', lambda *a, **k: []),
            patch.object(type(self.env['mercadolibre.account']), 'fetch_meli_product',
                         lambda this, meli_id=None, meli=None: {'id': meli_id, 'status': 'active'}),
            patch.object(type(self.env['mercadolibre.product_template']), 'copy_from_rjson', lambda *a, **k: None),
        ]
        if hasattr(PP, '_meli_family_selector_attributes'):
            patches.append(patch.object(PP, '_meli_family_selector_attributes', lambda *a, **k: []))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        try:
            categ = self._crear_minimo('mercadolibre.category', {'name': 'Afinadores', 'meli_category_id': 'MLM194198'})
        except Exception as e:
            self.skipTest("No se pudo crear la categoria ML en esta base: %s" % e)
        self.tmpl = self.env['product.template'].create({'name': 'Cordal 464 (test 611)'})
        self.prod = self.tmpl.product_variant_ids[:1]
        self.tmpl.write({'meli_category': categ.id, 'meli_pub': True})
        self.prod.write({'meli_category': categ.id, 'meli_pub': True, 'meli_id': OLD})
        try:
            self.bT = self._crear_minimo('mercadolibre.product_template', {
                'name': 'Cordal 464', 'product_tmpl_id': self.tmpl.id, 'conn_id': OLD})
            self.bV = self._crear_minimo('mercadolibre.product', {
                'name': 'Cordal 464', 'product_id': self.prod.id, 'product_tmpl_id': self.tmpl.id,
                'binding_product_tmpl_id': self.bT.id, 'conn_id': OLD, 'meli_id': OLD})
        except Exception as e:
            self.skipTest("No se pudieron crear las vinculaciones en esta base: %s" % e)
        self.tmpl.mercadolibre_bindings = [(4, self.bT.id)]

    def _post(self, item, **ctx):
        meli = _FakeMeli(item)
        res = self.prod.with_context(**ctx)._product_post(meli=meli, config=self.env.company)
        return meli, res

    def _assert_post_nuevo(self, meli):
        self.assertFalse(meli.puts, "no debe modificar (PUT) una publicacion cerrada/dada de baja")
        self.assertEqual(len(meli.posts), 1, "debe publicarla como NUEVA (POST /items)")
        self.assertEqual(self.body_meli_id, [False], "el body se arma como ALTA (sin el id viejo)")
        self.assertEqual(self.prod.meli_id, NEW)
        self.assertEqual(self.bT.conn_id, NEW)
        self.assertEqual((self.bV.conn_id, self.bV.meli_id), (NEW, NEW))

    def test_helper_estados(self):
        from odoo.addons.meli_oerp_multiple.models.product import _meli_item_unmodifiable as f
        self.assertEqual(f({'status': 'closed', 'sub_status': []}), 'closed')
        self.assertEqual(f({'status': 'paused', 'sub_status': ['deleted']}), 'deleted')
        self.assertEqual(f({'status': 'under_review', 'sub_status': ['forbidden']}), 'forbidden')
        self.assertEqual(f({'status': 'under_review', 'sub_status': ['waiting_for_patch']}), False)
        self.assertEqual(f({'status': 'paused', 'sub_status': ['out_of_stock']}), False)
        self.assertEqual(f({'error': 'not_found', 'status': 404}), False)
        self.assertEqual(f(None), False)

    def test_cerrada_publica_nueva(self):
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, res = self._post({'id': OLD, 'status': 'closed', 'sub_status': []})
        self._assert_post_nuevo(meli)

    def test_eliminada_publica_nueva(self):
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, res = self._post({'id': OLD, 'status': 'closed', 'sub_status': ['deleted']})
        self._assert_post_nuevo(meli)

    def test_baja_por_moderacion_error_claro(self):
        n0 = self.env['meli.warning'].search_count([])
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, res = self._post({'id': OLD, 'status': 'under_review', 'sub_status': ['forbidden']})
        self.assertFalse(meli.puts, "no debe hacer PUT sobre un item dado de baja por moderacion")
        self.assertFalse(meli.posts, "no debe republicar sola un item moderado")
        self.assertEqual(self.prod.meli_id, OLD)
        w = self.env['meli.warning'].search([], order='id desc', limit=1)
        self.assertGreater(self.env['meli.warning'].search_count([]), n0)
        self.assertIn(OLD, w.message or '')
        self.assertIn('Crear una nueva publicación', w.message or '')

    def test_baja_por_moderacion_forzada_publica_nueva(self):
        # republicar forzado recorre el alta completa con un ML de prueba: los avisos del
        # binder y la consulta de /sites (sin red en tests) no son lo que se mide aca.
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'), mute_logger('odoo.addons.meli_oerp.models.meli_util'):
            meli, res = self._post({'id': OLD, 'status': 'under_review', 'sub_status': ['forbidden']},
                                   force_meli_new_pub=True)
        self._assert_post_nuevo(meli)

    def test_control_activa_modifica(self):
        # Control: una publicacion viva se sigue modificando con PUT (pasa con y sin el fix).
        meli, res = self._post({'id': OLD, 'status': 'active', 'sub_status': []})
        self.assertEqual(len(meli.puts), 1)
        self.assertEqual(meli.puts[0][0], '/items/' + OLD)
        self.assertFalse(meli.posts)
        self.assertEqual(self.prod.meli_id, OLD)
