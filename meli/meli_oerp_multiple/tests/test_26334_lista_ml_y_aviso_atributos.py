# -*- coding: utf-8 -*-
"""26.334 (caso-26334, 28-oct-2026), dos defectos del alta de publicaciones:

1) «Nueva Lista de Precios» del asistente: con la lista «Mercado Libre» elegida, el body salía con el
   precio de la lista de la CUENTA (LP 1) y no con el de la regla de la lista elegida. El binding sí la
   usaba ⇒ el asistente mostraba un precio y se publicaba otro. Causa: `_product_post` llamaba a
   `set_meli_price(config)` sin la lista, y en `set_meli_price` un `plist` explícito iba ÚLTIMO.

2) El aviso de atributos obligatorios faltantes decía «pestaña MercadoLibre» para todos; atributos como
   Fabricante (MANUFACTURER) se cargan como línea en «Atributos y variantes». Ahora dice dónde va cada uno.

Sin red: ML es un objeto falso y el armado del body queda parcheado (mismo arnés que K36).
"""
from unittest.mock import patch

from odoo.tests import tagged

from .test_k36_k37_atributo_lista import TestAtributoListaK36

CAT_ATTS_26334 = [
    {'id': 'BRAND', 'name': 'Marca', 'value_type': 'string', 'tags': {'required': True}},
    {'id': 'MANUFACTURER', 'name': 'Fabricante', 'value_type': 'string', 'tags': {'required': True}},
    {'id': 'MODEL', 'name': 'Modelo', 'value_type': 'string', 'tags': {'required': True}},
]


@tagged('post_install', '-at_install', 'meli_26334')
class TestListaMLyAviso26334(TestAtributoListaK36):
    # se reusa el arnés de K36; sus tests no se repiten acá
    test_valor_fuera_de_lista_no_publica_y_explica = None
    test_valor_de_lista_sin_acentos_ni_mayusculas_publica = None
    test_valor_por_id_publica = None
    test_lista_no_obligatoria_no_bloquea = None
    test_faltante_orienta_al_mapeo_si_existe = None

    def setUp(self):
        super().setUp()
        PP = type(self.env['product.product'])
        p = patch.object(PP, '_meli_get_category_attributes', lambda *a, **k: CAT_ATTS_26334)
        p.start()
        self.addCleanup(p.stop)

    # ---------------- 2) aviso: dónde se carga cada atributo ----------------
    def test_fabricante_va_en_atributos_y_variantes(self):
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, w = self._post([{'id': 'BRAND', 'value_name': 'MarcaX'},
                                  {'id': 'MODEL', 'value_name': 'AGENDA'}])
        self.assertFalse(meli.posts)
        msg = w.message or ''
        self.assertIn('Fabricante', msg)
        self.assertIn('Atributos y variantes', msg)
        self.assertNotIn('pestaña MercadoLibre', msg,
                         "Fabricante no tiene campo en la pestaña MercadoLibre: el aviso no debe mandar ahí")

    def test_marca_va_en_pestana_mercadolibre(self):
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, w = self._post([{'id': 'MANUFACTURER', 'value_name': 'MarcaX'},
                                  {'id': 'MODEL', 'value_name': 'AGENDA'}])
        msg = w.message or ''
        self.assertIn('Marca: completalo en la pestaña MercadoLibre', msg)
        self.assertNotIn('Atributos y variantes', msg)

    def test_mixto_separa_cada_uno(self):
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='WARNING'):
            meli, w = self._post([{'id': 'BRAND', 'value_name': 'MarcaX'}])
        msg = w.message or ''
        self.assertIn('Fabricante: agregalo en la pestaña «Atributos y variantes»', msg)
        self.assertIn('Modelo: completalo en la pestaña MercadoLibre', msg)

    # ---------------- 1) precio: la lista elegida llega al body ----------------
    def _lista_ml(self, product, factor=2.2):
        return self.env['product.pricelist'].create({
            'name': 'Mercado Libre (test 26334)',
            'item_ids': [(0, 0, {'applied_on': '1_product', 'product_tmpl_id': product.product_tmpl_id.id,
                                 'compute_price': 'formula', 'base': 'standard_price',
                                 'price_discount': -(factor - 1.0) * 100.0})],
        })

    def test_post_pasa_la_nueva_lista_a_set_meli_price(self):
        PP = type(self.env['product.product'])
        vistos = []

        def spy(this, meli=None, config=None, plist=None):
            vistos.append(plist)

        pl = self._lista_ml(self.prod)
        with patch.object(PP, 'set_meli_price', spy):
            self._post_ctx(force_meli_new_pricelist=pl)
        self.assertTrue(vistos)
        self.assertEqual(vistos[0], pl, "la «Nueva Lista de Precios» tiene que llegar a set_meli_price")
        # y por id (contexto/RPC) también
        vistos.clear()
        with patch.object(PP, 'set_meli_price', spy):
            self._post_ctx(force_meli_new_pricelist=pl.id)
        self.assertEqual(vistos[0], pl)

    def _post_ctx(self, **ctx):
        from .test_k36_k37_atributo_lista import _FakeMeli
        return self.prod.with_context(force_meli_new_pub=True, **ctx)._product_post(
            meli=_FakeMeli(), config=self.env.company)

    def _set_meli_price_real(self, prod, **kw):
        # el arnés K36 parchea set_meli_price en la clase del registro: se usa la definición real
        PP = type(self.env['product.product'])
        for klass in PP.__mro__[1:]:
            if 'set_meli_price' in klass.__dict__:
                return klass.__dict__['set_meli_price'](prod, **kw)
        raise AssertionError('set_meli_price no encontrado')

    def test_set_meli_price_lista_explicita_gana_a_la_de_la_cuenta(self):
        lp1 = self.env['product.pricelist'].create({'name': 'LP 1 (test 26334)'})
        prod = self.env['product.product'].create({
            'name': 'Agenda (test 26334)', 'list_price': 52925.0, 'standard_price': 26460.0, 'taxes_id': [(5, 0, 0)]})
        pl = self._lista_ml(prod)
        company = self.env.company
        company.mercadolibre_pricelist = lp1
        # sin lista explícita: la de la cuenta (precio de venta)
        self.assertAlmostEqual(float(self._set_meli_price_real(prod, config=company)), 52925.0, places=2)
        # con la lista ML: la regla (costo x 2,2)
        self.assertAlmostEqual(float(self._set_meli_price_real(prod, config=company, plist=pl)), 26460.0 * 2.2, places=2)
        self.assertAlmostEqual(float(prod.meli_price), 26460.0 * 2.2, places=2)

