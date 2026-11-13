# -*- coding: utf-8 -*-
"""26.345 (caso-K21 cliente F FASE 2, 30-oct-2026): asistente Publicar con MENOS PASOS.
P1 sin confirmación en el botón de la pestaña · P2 grilla editable por producto (se guarda en la plantilla,
categoría pre-sugerida) · P3 contadores · P4 «qué hacer» en un radio · P5 «Revisar en ML (sin publicar)»:
body real contra POST /items/validate, con todo otro POST/PUT/DELETE bloqueado y rollback.
Control (código anterior): no existen p_line_ids / p_operation / action_p_validate => todo ROJO.
Sin red: get_new_instance y el predictor quedan parcheados.
Correr: odoo-bin ... --test-enable --test-tags meli_p345 --stop-after-init
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo import fields


class _Resp(object):
    def __init__(self, j):
        self.rjson = j
        self.response = j

    def json(self):
        return self.rjson


class _FakeMeli(object):
    """Cliente ML de mentira: registra las llamadas; /items/validate responde lo que se le diga."""

    def __init__(self, validate_json=None):
        self.calls = []
        self.validate_json = validate_json if validate_json is not None else {}
        self.access_token = 'TEST'

    def need_login(self):
        return False

    def get(self, path, *a, **k):
        self.calls.append(('GET', path))
        return _Resp({})

    def post(self, path, body=None, params=None, *a, **k):
        self.calls.append(('POST', path))
        if path == '/items/validate':
            return _Resp(self.validate_json)
        if str(path).startswith('/pictures'):
            return _Resp({'id': 'PIC1'})
        raise AssertionError("POST real a ML en un test: %s" % path)

    def put(self, path, *a, **k):
        raise AssertionError("PUT real a ML en un test: %s" % path)

    put_mini = put

    def delete(self, path, *a, **k):
        raise AssertionError("DELETE real a ML en un test: %s" % path)


@tagged('post_install', '-at_install', 'meli_p345')
class TestPublicarMenosPasos(TransactionCase):

    def _crear_minimo(self, model, _visitados=None):
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
                    rec = self._crear_minimo(f.comodel_name, _visitados)
                vals[name] = rec.id if rec else False
        return Model.create(vals)

    def setUp(self):
        super().setUp()
        self.Wiz = self.env['mercadolibre.product.template.post']
        self.Cat = self.env['mercadolibre.category']
        self.categ = self.Cat.create({'name': 'Cat P345', 'meli_category_id': 'MLA0345'})
        Tmpl = type(self.env['product.template'])
        p = patch.object(Tmpl, '_get_meli_category_from_predictor', lambda s: (self.categ, []))
        p.start()
        self.addCleanup(p.stop)
        try:
            self.account = self.env['mercadolibre.account'].search([], limit=1) \
                or self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("no se pudo obtener una mercadolibre.account: %s" % e)
        self.account.company_id = self.env.user.company_id
        self.inc = self.env['product.template'].create({'name': 'P345 incompleto'})
        self.full = self.env['product.template'].create({
            'name': 'P345 completo', 'meli_category': self.categ.id, 'meli_brand': 'Marca', 'meli_model': 'M1',
            'meli_seller_package_height': '10 cm', 'meli_seller_package_width': '10 cm',
            'meli_seller_package_length': '10 cm', 'meli_seller_package_weight': '100 g',
            'meli_description': 'desc', 'image_1920': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='})

    def _wiz(self, tmpls, **vals):
        if self.account:
            vals.setdefault('connectors', self.account.id)
        W = self.Wiz.with_context(active_model='product.template', active_ids=tmpls.ids)
        defaults = W.default_get(list(W._fields))
        defaults.update(vals)
        return W.create(defaults)

    def test_p2_grilla_una_fila_por_producto_con_categoria_sugerida(self):
        wiz = self._wiz(self.inc | self.full)
        self.assertEqual(len(wiz.p_line_ids), 2)
        li = wiz.p_line_ids.filtered(lambda l: l.product_tmpl_id == self.inc)
        lf = wiz.p_line_ids.filtered(lambda l: l.product_tmpl_id == self.full)
        self.assertEqual(li.meli_category, self.categ)        # sugerida por ML
        self.assertTrue(li.category_suggested)
        self.assertEqual(li.p_state, 'missing')
        self.assertIn('marca', li.p_missing)
        self.assertEqual(lf.p_state, 'ready')
        self.assertFalse(self.inc.meli_category)               # la sugerencia NO escribe hasta revisar/publicar
        self.assertEqual((wiz.p_count_missing, wiz.p_count_ready), (1, 1))  # P3

    def test_p2_lo_cargado_en_la_grilla_va_a_la_plantilla_sin_borrar(self):
        self.inc.meli_model = 'YA CARGADO'
        wiz = self._wiz(self.inc)
        line = wiz.p_line_ids
        line.write({'meli_brand': 'cliente F', 'meli_model': False, 'meli_seller_package_weight': '300 g'})
        self.assertEqual(line.p_state, 'missing')
        wiz._p_apply_lines()
        self.assertEqual(self.inc.meli_brand, 'cliente F')
        self.assertEqual(self.inc.meli_seller_package_weight, '300 g')
        self.assertEqual(self.inc.meli_model, 'YA CARGADO')    # vacío en la grilla no borra
        self.assertEqual(self.inc.meli_category, self.categ)   # la sugerida se guarda al aplicar

    def test_p4_radio_que_hacer(self):
        wiz = self._wiz(self.full)
        wiz.p_operation = 'stock'
        wiz._onchange_p_operation()
        self.assertTrue(wiz.post_stock)
        self.assertFalse(wiz.post_price)
        wiz.p_operation = 'pause'
        wiz._onchange_p_operation()
        self.assertTrue(wiz.action_pause)
        self.assertFalse(wiz.force_meli_active)
        self.assertFalse(wiz.post_stock)
        wiz.p_operation = 'full'
        wiz._onchange_p_operation()
        self.assertFalse(wiz.action_pause)
        self.assertTrue(wiz.force_meli_active)

    def test_p5_cliente_seco_redirige_y_bloquea(self):
        from odoo.addons.meli_oerp_multiple.models.wizards import MeliDryValidateClient, MeliDryStop
        inner = _FakeMeli({'status': 400, 'error': 'validation_error', 'cause': [
            {'type': 'error', 'code': 'item.attribute.missing_required', 'message': 'Falta GTIN'},
            {'type': 'warning', 'code': 'shipping', 'message': 'envío gratis obligatorio'}]})
        dry = MeliDryValidateClient(inner)
        self.assertEqual(dry.access_token, 'TEST')
        dry.post('/pictures/items/upload', {})                 # subir imagen pasa
        with self.assertRaises(MeliDryStop):
            dry.put_mini('/items/MLA1', {'price': 1})
        with self.assertRaises(MeliDryStop):
            dry.post('/items', {'title': 'x'}, {'access_token': 'TEST'})
        self.assertIn(('POST', '/items/validate'), inner.calls)
        self.assertNotIn(('POST', '/items'), inner.calls)
        state, msg = dry.summary()
        self.assertEqual(state, 'error')
        self.assertIn('Falta GTIN', msg)
        self.assertIn('envío gratis', msg)
        self.assertEqual(dry.blocked, ['PUT /items/MLA1'])

    def test_p5_400_solo_avisos_es_ok_y_204_es_ok(self):
        from odoo.addons.meli_oerp_multiple.models.wizards import MeliDryValidateClient
        d = MeliDryValidateClient(_FakeMeli())
        d.result = {'status': 400, 'json': {'status': 400, 'error': 'validation_error',
                                             'cause': [{'type': 'warning', 'message': 'aviso'}]}}
        self.assertEqual(d.summary()[0], 'warn')
        d.result = {'status': None, 'json': {}}
        self.assertEqual(d.summary()[0], 'ok')

    def test_p5_revisar_en_ml_no_deja_rastros(self):
        if not self.account:
            self.skipTest("sin mercadolibre.account")
        inner = _FakeMeli({'status': 400, 'error': 'validation_error',
                           'cause': [{'type': 'error', 'code': 'x', 'message': 'Falta family_name'}]})
        Tmpl = type(self.env['product.template'])

        def fake_post(tmpl, context=None, meli_id=None, meli=None, account=None):
            tmpl.meli_title = 'ESCRITO EN EL ARMADO'          # lo que el armado escribe se deshace
            meli.post('/items', {'title': tmpl.name}, {'access_token': meli.access_token})
            return {}

        wiz = self._wiz(self.inc)
        wiz.p_line_ids.meli_brand = 'cliente F'
        with patch.object(type(self.env['meli.util']), 'get_new_instance', lambda *a, **k: inner), \
             patch.object(Tmpl, 'product_template_post', fake_post):
            wiz.action_p_validate()
        line = wiz.p_line_ids
        self.assertEqual(line.ml_check_state, 'error')
        self.assertIn('family_name', line.ml_check_msg)
        self.assertFalse(self.inc.meli_title)                  # rollback del armado
        self.assertEqual(self.inc.meli_brand, 'cliente F')          # lo cargado en la grilla sí queda
        self.assertEqual(wiz.p_count_check_error, 1)

    def test_p1_boton_publicar_sin_confirmacion(self):
        arch = self.env.ref('meli_oerp.product_tpl_ml_form_view').arch_db or ''
        i = arch.find('title="Publicar/Actualizar en ML')
        self.assertGreater(i, 0, "no está el botón Publicar de la pestaña")
        boton = arch[arch.rfind('<button', 0, i):arch.find('/>', i)]
        self.assertIn('Publicar', boton)
        self.assertNotIn('confirm=', boton)

    def test_p2_precio_por_fila_hook(self):
        """Hook para extensiones (campaign: margen): cada fila trae lista, precio y vinculación."""
        self.full.list_price = 1234.0
        pl = self.env['product.pricelist'].create({'name': 'PL P345', 'item_ids': [(0, 0, {
            'applied_on': '3_global', 'compute_price': 'percentage', 'percent_price': 10.0})]})
        wiz = self._wiz(self.full, force_meli_new_pricelist=pl.id)
        line = wiz.p_line_ids
        self.assertEqual(line.p_pricelist_id, pl)
        self.assertAlmostEqual(line.p_price, 1110.6, places=2)
        self.assertFalse(line.p_binding_id)                    # sin vinculación con la cuenta
        self.assertTrue(hasattr(type(line), '_compute_p_price'))

    def test_p2_grilla_guarda_producto_desde_la_ui(self):
        """El cliente web no manda los campos readonly al guardar: los que la fila necesita persistir
        (producto, sugerida, publicado) llevan force_save, o la fila se crea sin producto (visto en banco UI)."""
        from lxml import etree
        arch = self.env['mercadolibre.product.template.post'].get_view(
            self.env.ref('meli_oerp.view_product_template_post').id, 'form')['arch']
        doc = etree.fromstring(arch)
        for name in ('product_tmpl_id', 'category_suggested', 'p_published'):
            node = doc.xpath("//field[@name='p_line_ids']/*[self::list or self::tree]/field[@name='%s']" % name)
            self.assertTrue(node, name)
            self.assertTrue(node[0].get('force_save') in ('1', 'True', 'true') or not node[0].get('readonly'),
                            "%s readonly sin force_save: la fila se guarda sin ese dato" % name)

    def test_w5_fabricante_desde_marca_en_camino_multicuenta(self):
        """El armado multi-cuenta (el de cliente F) también completa MANUFACTURER con la Marca: si no, el
        pre-flight corta con «faltan atributos obligatorios: Fabricante» aunque la marca esté cargada."""
        prod = self.full.product_variant_id
        atts = prod._product_post_set_attributes(product_tmpl=self.full, product=prod, meli=_FakeMeli(),
                                                 config=self.account.configuration or self.env.company)
        ids = {a.get('id'): a.get('value_name') for a in (atts or []) if isinstance(a, dict)}
        self.assertEqual(ids.get('MANUFACTURER'), 'Marca')
