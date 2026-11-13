# -*- coding: utf-8 -*-
"""26.371 (#462, B1 armonización 18.0 — pedido FCA 4-nov-2026).

Lo que corría SÓLO en un cliente entra al source detrás del botón «Publicar (nuevo)»; el «Publicar» de
siempre queda con el camino de origin/18.0. La publicación recuerda el camino (meli_post_mode del
binding) y los updates siguen ese camino sin saber de botones.

  T1  camino nuevo, cuenta clásica, 2 variantes sueltas ⇒ cada variante a SU publicación (antes: la 2ª
      levantaba ValidationError con la 1ª ya viva en ML, y todos los bindings quedaban con el id de la 1ª).
  T2  camino nuevo, cuenta user_product ⇒ 2 POST sin variations[], mismo family_name; el PUT sin
      family_name ni title.
  T6  KIT de ML (tag bundle) ⇒ no se publica stock, stock_error = bundle.
  T9  traza de alta sin `registry.in_test_mode` (core 19/20) ⇒ sin excepción en el log.
  T10 botón VIEJO = origin/18.0, también en cuenta user_product (el flag de la cuenta NO prende el
      modo familia). Verde en origin y en la rama: es el control de no-regresión.
  T11 binding 'family' ⇒ un update que llega sin contexto (cron) va por el camino familia.
  Td  mercadolibre_bind_to completa product.meli_id vacío (para todas las cuentas).
Control (origin/18.0 26.370) ⇒ T1/T2/T6/T9/T11/Td ROJO; T10 verde en las dos.
Sin red: ML es un objeto falso y requests queda bloqueado.
Correr: odoo-bin ... -i meli_oerp_multiple --test-enable --test-tags meli_b462 --stop-after-init
"""
import logging
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

_MOD = 'odoo.addons.meli_oerp_multiple.models.product'

CAT_ATTS_462 = [
    {'id': 'BRAND', 'name': 'Marca', 'value_type': 'string', 'tags': {}},
    {'id': 'COLOR', 'name': 'Color', 'value_type': 'list', 'tags': {'allow_variations': True},
     'values': [{'id': '52049', 'name': 'Rojo'}, {'id': '52028', 'name': 'Azul'}]},
]


class _Resp(object):
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeMeli462(object):
    """ML falso: cada POST /items da un id NUEVO (como ML). Registra todo lo que se escribe."""
    access_token = 'x'
    seller_id = '123456'

    def __init__(self):
        self.gets, self.puts, self.posts, self.deletes = [], [], [], []
        self._n = 0

    def need_login(self):
        return False

    def auth_url(self, *a, **k):
        return 'http://localhost/login'

    def get(self, path, *a, **k):
        self.gets.append(path)
        p = str(path)
        if p.startswith('/items/') and p.count('/') == 2:
            return _Resp({'id': p.split('/')[2], 'status': 'active'})
        return _Resp({})

    def post(self, path, body=None, *a, **k):
        self.posts.append((path, body))
        if str(path) == '/items':
            self._n += 1
            return _Resp({'id': 'MLA9462%04d' % self._n, 'status': 'active'})
        return _Resp({'id': 'X'})

    post_mini = post

    def put(self, path, body=None, *a, **k):
        self.puts.append((path, body))
        p = str(path)
        return _Resp({'id': p.split('/')[2] if p.startswith('/items/') else 'X', 'status': 'active'})

    put_mini = put

    def delete(self, path, *a, **k):
        self.deletes.append(path)
        return _Resp({})

    def item_posts(self):
        return [b for (p, b) in self.posts if str(p) == '/items']

    def item_puts(self):
        return [b for (p, b) in self.puts if str(p).startswith('/items/') and str(p).count('/') == 2]


class _Pub462Base(TransactionCase):
    """Cuenta + configuración + plantilla con 2 variantes (Color Rojo/Azul), ML falso, red bloqueada."""

    USER_PRODUCT = False

    def _red(self, *a, **k):
        raise AssertionError("llamada de RED real a %s" % (a[1:2] or a,))

    def setUp(self):
        super().setUp()
        env = self.env
        PP = type(env['product.product'])
        spy = self
        self.meli = FakeMeli462()
        self.posted_contexts = []
        patches = [
            patch('requests.sessions.Session.request', self._red),
            patch.object(type(env['meli.util']), 'get_new_instance', lambda *a, **k: spy.meli),
            patch.object(type(env['mercadolibre.account']), '_meli_instance_or_mine',
                         lambda this, meli=None: meli or spy.meli, create=True),
            patch.object(PP, '_product_post_set_basic_configuration', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_template_configuration', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_title', lambda *a, **k: None),
            patch.object(PP, 'set_meli_price', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_price', lambda *a, **k: None),
            patch.object(PP, '_product_post_set_attributes', lambda *a, **k: []),
            patch.object(PP, '_product_post_set_category', lambda *a, **k: None),
            patch.object(PP, '_meli_get_category_attributes', lambda *a, **k: CAT_ATTS_462),
            patch.object(PP, '_product_post_set_quantity', lambda *a, **k: None),
            patch.object(PP, 'product_meli_upload_image', lambda *a, **k: {}),
            patch.object(PP, 'product_meli_upload_multi_images', lambda *a, **k: {}),
            patch(_MOD + '.get_first_image_to_publish', lambda *a, **k: 'img'),
            patch(_MOD + '.variant_image_ids', lambda *a, **k: []),
            patch(_MOD + '.template_image_ids', lambda *a, **k: []),
            patch.object(type(env['mercadolibre.account']), 'fetch_meli_product',
                         lambda this, meli_id=None, meli=None: {'id': meli_id, 'status': 'active'}),
            patch.object(type(env['mercadolibre.product_template']), 'copy_from_rjson', lambda *a, **k: None),
            patch.object(type(env['mercadolibre.product']), 'copy_from_rjson', lambda *a, **k: None),
            patch.object(env.cr, 'rollback', lambda *a, **k: None),
        ]
        if hasattr(PP, '_meli_family_selector_attributes'):
            patches.append(patch.object(PP, '_meli_family_selector_attributes', lambda *a, **k: []))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
        pl = env['product.pricelist'].search([], limit=1) or env['product.pricelist'].create({'name': 'B462'})
        self.config = env['mercadolibre.configuration'].create({
            'name': 'B462', 'mode': 'test', 'company_id': env.company.id, 'mercadolibre_pricelist': pl.id,
            'mercadolibre_buying_mode': 'buy_it_now', 'mercadolibre_currency': 'ARS',
            'mercadolibre_stock_warehouse': wh.id, 'mercadolibre_stock_warehouse_full': wh.id,
            'mercadolibre_listing_type': 'gold_special'})
        self.account = env['mercadolibre.account'].create({
            'name': 'B462', 'type': 'custom', 'company_id': env.company.id, 'configuration': self.config.id,
            'country_id': env.ref('base.ar').id, 'meli_login_id': 'B462', 'client_id': 'B462',
            'secret_key': 'x', 'seller_id': '123456', 'redirect_uri': 'http://localhost/meli_login',
            'user_product_seller': self.USER_PRODUCT})
        # mercadolibre_user_product_seller de la configuración es related a la cuenta
        self.assertEqual(bool(self.config.mercadolibre_user_product_seller), self.USER_PRODUCT)
        self.categ = env['mercadolibre.category'].create({'name': 'Agendas B462', 'meli_category_id': 'MLA4625'})
        att = env['product.attribute'].create({'name': 'Color B462', 'create_variant': 'always'})
        rojo = env['product.attribute.value'].create({'name': 'Rojo', 'attribute_id': att.id})
        azul = env['product.attribute.value'].create({'name': 'Azul', 'attribute_id': att.id})
        self.tmpl = env['product.template'].create({
            'name': 'Agenda B462', 'list_price': 1000.0, 'meli_pub': True, 'meli_category': self.categ.id,
            'meli_listing_type': 'gold_special', 'meli_title': 'Agenda B462',
            'attribute_line_ids': [(0, 0, {'attribute_id': att.id, 'value_ids': [(6, 0, [rojo.id, azul.id])]})]})
        self.v1, self.v2 = self.tmpl.product_variant_ids.sorted('id')[:2]
        for i, v in enumerate((self.v1, self.v2), 1):
            v.write({'meli_pub': True, 'default_code': 'B462-%d' % i, 'meli_category': self.categ.id})

    def _old_button_assert_origin(self, bindT, b1, b2):
        """Resultado de origin/18.0 con variantes sueltas: UNA alta en ML, la 2ª variante levanta
        ValidationError y la request se deshace entera (en Odoo no queda nada; en ML la 1ª queda viva).
        assertRaises de Odoo corre en un savepoint = el rollback de la request real."""
        with self.assertRaises(ValidationError):
            bindT.product_template_post(meli=self.meli)
        self.env.invalidate_all()
        self.assertEqual(len(self.meli.item_posts()), 1, "una sola alta llega a ML")
        self.assertFalse(bindT.conn_id or b1.conn_id or b2.conn_id or self.v1.meli_id or self.v2.meli_id)
        return self.meli.item_posts()[0]

    # bindings "a mano" (lo que deja un binder antes de publicar)
    def _bindings(self, conn_ids=(False, False), tpl_conn=False, mode=None):
        TB, VB = self.env['mercadolibre.product_template'], self.env['mercadolibre.product']
        vals = {'name': self.tmpl.name, 'connection_account': self.account.id, 'product_tmpl_id': self.tmpl.id,
                'conn_id': tpl_conn, 'meli_category': self.categ.id}
        if mode:
            vals['meli_post_mode'] = mode
        bindT = TB.create(vals)
        vbs = VB
        for v, cid in zip((self.v1, self.v2), conn_ids):
            vv = {'name': v.display_name, 'connection_account': self.account.id, 'product_id': v.id,
                  'product_tmpl_id': self.tmpl.id, 'binding_product_tmpl_id': bindT.id, 'conn_id': cid,
                  'meli_category': self.categ.id}
            if mode:
                vv['meli_post_mode'] = mode
            vbs |= VB.create(vv)
            if cid:
                v.meli_id = cid
        self.tmpl.mercadolibre_bindings = [(4, bindT.id)]
        return bindT, vbs


@tagged('post_install', '-at_install', 'meli_b462')
class TestPublicarNuevoClasica(_Pub462Base):

    def test_t1_nuevo_cuenta_clasica_cada_variante_su_publicacion(self):
        bindT, (b1, b2) = self._bindings()
        bindT.with_context(meli_post_mode='family').product_template_post(meli=self.meli)
        posts = self.meli.item_posts()
        self.assertEqual(len(posts), 2, "una publicación por variante")
        self.assertTrue(b1.conn_id and b2.conn_id)
        self.assertNotEqual(b1.conn_id, b2.conn_id, "cada binding de variante conserva SU publicación")
        self.assertEqual(b1.conn_id, self.v1.meli_id)
        self.assertEqual(b2.conn_id, self.v2.meli_id)
        self.assertEqual(bindT.conn_id, b1.conn_id, "la plantilla toma el 1er id")
        self.assertEqual(bindT.meli_post_mode, 'family', "la publicación recuerda el camino")
        self.assertEqual(set((b1 | b2).mapped('meli_post_mode')), {'family'})

    def test_t10_boton_viejo_igual_a_origin(self):
        """El «Publicar» de siempre: idéntico a origin/18.0, incluido su límite con variantes sueltas."""
        bindT, (b1, b2) = self._bindings()
        body = self._old_button_assert_origin(bindT, b1, b2)
        self.assertIn('title', body)
        self.assertNotIn('family_name', body)

    def test_td_bind_to_completa_meli_id_vacio(self):
        bindT, _vbs = self._bindings(tpl_conn='MLA7770001')
        self.assertFalse(self.v1.meli_id)
        self.v1.mercadolibre_bind_to(self.account, binding_product_tmpl_id=bindT, meli_id='MLA7770001',
                                     meli=self.meli, rjson={'id': 'MLA7770001', 'status': 'active'})
        self.assertEqual(self.v1.meli_id, 'MLA7770001', "vincular completa el meli_id vacío de la variante")
        # nunca pisa uno que apunta a OTRA publicación
        self.v2.meli_id = 'MLA7770009'
        self.v2.mercadolibre_bind_to(self.account, binding_product_tmpl_id=bindT, meli_id='MLA7770001',
                                     meli=self.meli, rjson={'id': 'MLA7770001', 'status': 'active'})
        self.assertEqual(self.v2.meli_id, 'MLA7770009')

    def test_t6_kit_bundle_no_publica_stock(self):
        _bindT, (b1, _b2) = self._bindings(conn_ids=('MLA4620001', 'MLA4620002'), tpl_conn='MLA4620001')
        Acc, PP, VB = type(self.env['mercadolibre.account']), type(self.env['product.product']), \
            type(self.env['mercadolibre.product'])
        kit = {'id': 'MLA4620001', 'status': 'active', 'tags': ['bundle'], 'available_quantity': 2}
        with patch.object(Acc, 'fetch_meli_product', lambda this, meli_id=None, meli=None: dict(kit)), \
                patch.object(VB, '_fetch_meli_user_product_id', lambda *a, **k: False, create=True), \
                patch.object(PP, '_meli_available_quantity', lambda *a, **k: 7):
            res = b1.product_post_stock(meli=self.meli)
        self.assertEqual((res or {}).get('error'), 'bundle', res)
        self.assertIn('bundle', b1.stock_error or '')
        self.assertFalse([p for p in self.meli.puts if 'MLA4620001' in str(p[0])], self.meli.puts)

    def test_t9_traza_de_alta_sin_in_test_mode(self):
        """Core 19.0 no tiene registry.in_test_mode(): la traza no puede romper (antes: excepción en
        cada alta y sin fila de rescate)."""
        reg_cls = type(self.env.registry)
        with patch.object(reg_cls, 'in_test_mode', None, create=True):
            self.assertTrue(self.v1._meli_in_test_mode(), "en tests, por el fallback")
            with self.assertNoLogs('odoo.addons.meli_oerp_multiple.models.meli_family_post', level='ERROR'):
                lst = []
                self.v1.with_context(meli_created_listings=lst)._meli_trace_created_listing('MLA4629999')
        self.assertEqual(lst, [(self.v1.id, 'MLA4629999')])


@tagged('post_install', '-at_install', 'meli_b462')
class TestPublicarNuevoUserProduct(_Pub462Base):

    USER_PRODUCT = True

    def test_t2_familia_dos_altas_sin_variations_y_put_sin_nombre(self):
        self.tmpl.with_context(meli_post_mode='family').product_template_post(account=self.account, meli=self.meli)
        posts = self.meli.item_posts()
        self.assertEqual(len(posts), 2, [p for p in self.meli.posts])
        for b in posts:
            self.assertNotIn('variations', b)
            self.assertNotIn('title', b)
        self.assertEqual({b.get('family_name') for b in posts}, {'Agenda B462'}, "mismo family_name, de la plantilla")
        colors = sorted(a.get('value_name') for b in posts for a in b.get('attributes', []) if a.get('id') == 'COLOR')
        self.assertEqual(colors, ['Azul', 'Rojo'], "cada alta lleva SU valor diferenciador")
        self.assertTrue(self.v1.meli_id and self.v2.meli_id and self.v1.meli_id != self.v2.meli_id)
        binds = self.env['mercadolibre.product'].search([('product_tmpl_id', '=', self.tmpl.id),
                                                         ('connection_account', '=', self.account.id)])
        self.assertEqual(set(binds.mapped('meli_post_mode')), {'family'})
        # segunda vuelta = actualización: PUT sin family_name ni title
        self.meli.posts.clear()
        self.tmpl.with_context(meli_post_mode='family').product_template_post(account=self.account, meli=self.meli)
        self.assertFalse(self.meli.item_posts(), "no da de alta otra vez")
        puts = self.meli.item_puts()
        self.assertEqual(len(puts), 2, self.meli.puts)
        for b in puts:
            self.assertNotIn('family_name', b)
            self.assertNotIn('title', b)

    def test_t10_boton_viejo_cuenta_user_product_no_prende_familia(self):
        """Cuenta user_product + «Publicar» de siempre ⇒ el camino de origin (el flag de la cuenta NO
        prende el modo familia): misma alta única con family_name del título y el mismo raise."""
        bindT, (b1, b2) = self._bindings()
        body = self._old_button_assert_origin(bindT, b1, b2)
        self.assertIn('family_name', body, "origin: cuenta user_product manda family_name (del título de la variante)")
        self.assertNotIn('title', body)

    def test_t11_binding_family_enruta_sin_boton(self):
        bindT, (b1, b2) = self._bindings(conn_ids=('MLA4621001', 'MLA4621002'), tpl_conn='MLA4621001', mode='family')
        # (a) el binding de plantilla (lo que corre un cron de update) sin contexto de botón
        bindT.product_template_post(meli=self.meli)
        self.assertFalse(self.meli.item_posts())
        puts = self.meli.item_puts()
        self.assertEqual(sorted(str(p).split('/')[2] for p, _b in self.meli.puts if str(p).count('/') == 2),
                         ['MLA4621001', 'MLA4621002'], "cada variante actualiza SU publicación")
        for b in puts:
            self.assertNotIn('family_name', b)
            self.assertNotIn('title', b)
            self.assertNotIn('variations', b)
        # (b) el binding de variante (asistente de bindings / cron por variante)
        self.meli.puts.clear()
        ret = b2.product_post(meli=self.meli)
        puts = self.meli.item_puts()
        self.assertEqual(len(puts), 1, (self.env['meli.warning'].search([], order='id desc', limit=1).read(['message', 'message_html']),
                                        self.meli.gets))
        self.assertNotIn('title', puts[0])
        self.assertNotIn('variations', puts[0])
