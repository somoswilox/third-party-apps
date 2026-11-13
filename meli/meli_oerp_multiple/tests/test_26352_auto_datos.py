# -*- coding: utf-8 -*-
"""26.352 (caso-K21 C, pedido FCA 2-nov-2026): datos automáticos al publicar.
- IVA [meli] vacío => sale del impuesto de VENTA del producto ('21 %', '10.5 %', '0 %'; formato de ML
  verificado contra /categories/MLA40513/attributes). Antes: '21 %' fijo para todos (el asistente) y el
  camino multi-cuenta no mandaba el IVA.
- Impuesto interno vacío => '0 %' siempre en MLA (también fuera del asistente).
- Marca vacía => la marca del producto (product_brand_id) si el módulo está.
- Fabricante => proveedor principal sin sufijo societario (o la Marca, según la cuenta).
Control (origin 26.349): no existen los helpers ni el auto-fill => ERROR/FAIL.
Sin red: meli.util.get_new_instance queda parcheado.
Correr: odoo-bin ... -i meli_oerp_multiple --test-enable --test-tags meli_cK21 --stop-after-init
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from .test_26339_wizard_menos_clics import TestWizardMenosClics

_N = [0]


@tagged('post_install', '-at_install', 'meli_cK21')
class TestAutoDatos(TransactionCase):

    _crear_minimo = TestWizardMenosClics._crear_minimo

    def setUp(self):
        super().setUp()
        p = patch.object(type(self.env['meli.util']), 'get_new_instance',
                         side_effect=AssertionError("llamada a ML"))
        p.start()
        self.addCleanup(p.stop)
        p2 = patch.object(type(self.env['product.template']), '_get_meli_category_from_predictor',
                          return_value=([], {}), create=True)
        p2.start()
        self.addCleanup(p2.stop)
        self.company = self.env.company
        self.company.country_id = self.env.ref('base.ar')
        self.Tmpl = self.env['product.template']
        try:
            self.account = self.env['mercadolibre.account'].search([], limit=1) \
                or self._crear_minimo('mercadolibre.account')
            self.account.write({'company_id': self.company.id, 'meli_user_site_id': 'MLA'})
            otra = self.env['res.company'].create({'name': 'CK21 otra'})
            (self.company.mercadolibre_connections - self.account).write({'company_id': otra.id})
        except Exception as e:  # pragma: no cover
            self.account = self.env['mercadolibre.account']
            self._account_error = repr(e)

    def _tax(self, amount, name=None):
        _N[0] += 1
        name = '%s #%s' % (name or ('IVA %s%% CK21' % amount), _N[0])
        try:
            return self.env['account.tax'].create({
                'name': name, 'amount': amount, 'amount_type': 'percent',
                'type_tax_use': 'sale', 'company_id': self.company.id,
                'country_id': self.company.account_fiscal_country_id.id or self.env.ref('base.ar').id,
            })
        except Exception as e:  # pragma: no cover
            self.skipTest("no se pudo crear account.tax: %s" % e)

    def _prod(self, taxes=None, seller=None, **vals):
        v = {'name': vals.pop('name', 'CK21 prod'), 'taxes_id': [(6, 0, (taxes or self.env['account.tax']).ids)]}
        v.update(vals)
        tmpl = self.Tmpl.create(v)
        if seller:
            partner = self.env['res.partner'].create({'name': seller, 'is_company': True})
            self.env['product.supplierinfo'].create({'partner_id': partner.id, 'product_tmpl_id': tmpl.id,
                                                     'company_id': self.company.id})
        return tmpl

    # ---------------------------------------------------------------- C1 IVA
    def test_c1_iva_desde_impuesto_de_venta(self):
        self.assertEqual(self._prod(self._tax(21.0))._meli_vat_from_taxes(), '21 %')
        self.assertEqual(self._prod(self._tax(10.5))._meli_vat_from_taxes(), '10.5 %')
        self.assertEqual(self._prod(self._tax(0.0))._meli_vat_from_taxes(), '0 %')
        self.assertFalse(self._prod(self._tax(3.0, 'Percepcion IIBB CK21'))._meli_vat_from_taxes())
        self.assertFalse(self._prod()._meli_vat_from_taxes())
        # percepción + IVA => el IVA
        both = self._tax(3.0, 'Perc CK21') | self._tax(10.5)
        self.assertEqual(self._prod(both)._meli_vat_from_taxes(), '10.5 %')

    # ---------------------------------------------------------------- C4 Fabricante
    def test_c4_sufijo_societario(self):
        f = self.Tmpl._meli_strip_society_suffix
        for raw, clean in [('ACMEX S.R.L.', 'ACMEX'), ('WINNIE S. A', 'WINNIE'), ('CRESKO S.A.', 'CRESKO'),
                           ('CHIMOLA SA', 'CHIMOLA'), ('FOO S.A.C.I.F.', 'FOO'), ('BAR SAS', 'BAR'),
                           ('ACME, S.A.', 'ACME'), ('MESA', 'MESA'), ('Juan Pérez', 'Juan Pérez')]:
            self.assertEqual(f(raw), clean, raw)

    def test_c4_fabricante_proveedor_o_marca(self):
        tmpl = self._prod(seller='ACMEX S.R.L.', meli_brand='ACMEX MARCA')
        self.assertEqual(tmpl._meli_manufacturer_auto(), 'ACMEX')
        conf = self.company
        conf.mercadolibre_manufacturer_source = 'brand'
        self.assertEqual(tmpl._meli_manufacturer_auto(config=conf), 'ACMEX MARCA')
        conf.mercadolibre_manufacturer_source = 'supplier'
        sin_prov = self._prod(meli_brand='FW')
        self.assertEqual(sin_prov._meli_manufacturer_auto(config=conf), 'FW')   # sin proveedor => Marca

    # ---------------------------------------------------------------- C3 Marca
    def test_c3_marca_desde_product_brand(self):
        if 'product_brand_id' not in self.Tmpl._fields:
            tmpl = self._prod(meli_brand='X')
            self.assertEqual(tmpl._meli_brand_auto(), 'X')
            self.assertFalse(self._prod()._meli_brand_auto())
            return
        brand = self.env[self.Tmpl._fields['product_brand_id'].comodel_name].create({'name': 'ACMEX'})
        tmpl = self._prod(product_brand_id=brand.id)
        self.assertEqual(tmpl._meli_brand_auto(), 'ACMEX')

    # ---------------------------------------------------------------- C1+C2+C4 en el armado
    def test_auto_fill_mla(self):
        tmpl = self._prod(self._tax(10.5), seller='WINNIE S. A', meli_brand='FW')
        variant = tmpl.product_variant_ids[:1]
        attrs, ids = [], {}
        variant._meli_attr_auto_fill(attrs, ids, config=self.company)
        self.assertEqual(ids.get('BRAND'), 'FW')
        self.assertEqual(ids.get('VALUE_ADDED_TAX'), '10.5 %')
        self.assertEqual(ids.get('IMPORT_DUTY'), '0 %')
        self.assertEqual(ids.get('MANUFACTURER'), 'WINNIE')
        self.assertEqual(len(attrs), 4)

    def test_auto_fill_no_pisa(self):
        tmpl = self._prod(self._tax(21.0), seller='WINNIE S. A', meli_brand='FW', meli_vat='27 %',
                          meli_import_duty='4 %')
        variant = tmpl.product_variant_ids[:1]
        attrs = [{'id': 'MANUFACTURER', 'value_name': 'Hecho a mano'}]
        ids = {'MANUFACTURER': 'Hecho a mano'}
        variant._meli_attr_auto_fill(attrs, ids, config=self.company)
        self.assertEqual(ids['VALUE_ADDED_TAX'], '27 %')
        self.assertEqual(ids['IMPORT_DUTY'], '4 %')
        self.assertEqual(ids['MANUFACTURER'], 'Hecho a mano')
        self.assertEqual(len([a for a in attrs if a['id'] == 'MANUFACTURER']), 1)

    def test_auto_fill_sin_impuesto_usa_default_del_sitio(self):
        variant = self._prod(meli_brand='FW').product_variant_ids[:1]
        attrs, ids = [], {}
        variant._meli_attr_auto_fill(attrs, ids, config=self.company)
        self.assertEqual(ids.get('VALUE_ADDED_TAX'), '21 %')
        self.assertEqual(ids.get('IMPORT_DUTY'), '0 %')

    def test_auto_fill_fuera_de_mla_no_manda_impuestos(self):
        self.company.country_id = self.env.ref('base.mx')
        variant = self._prod(self._tax(16.0), meli_brand='FW').product_variant_ids[:1]
        attrs, ids = [], {}
        variant._meli_attr_auto_fill(attrs, ids, config=self.company)
        self.assertNotIn('VALUE_ADDED_TAX', ids)
        self.assertNotIn('IMPORT_DUTY', ids)
        self.assertEqual(ids.get('MANUFACTURER'), 'FW')

    def test_camino_multiple_manda_iva_y_fabricante(self):
        """El armado multi-cuenta (_product_post_set_attributes) lleva IVA/imp. interno/Fabricante."""
        if not self.account:
            self.skipTest("sin mercadolibre.account en la base de test: %s" % getattr(self, "_account_error", ""))
        tmpl = self._prod(self._tax(10.5), seller='ACMEX S.R.L.', meli_brand='ACMEX')
        variant = tmpl.product_variant_ids[:1]
        attrs = variant._product_post_set_attributes(product_tmpl=tmpl, product=variant, meli=None,
                                                     config=self.account.configuration)
        ids = {a['id']: a['value_name'] for a in attrs}
        self.assertEqual(ids.get('VALUE_ADDED_TAX'), '10.5 %')
        self.assertEqual(ids.get('IMPORT_DUTY'), '0 %')
        self.assertEqual(ids.get('MANUFACTURER'), 'ACMEX')
        self.assertEqual(ids.get('BRAND'), 'ACMEX')

    # ---------------------------------------------------------------- asistente
    def test_asistente_por_fila(self):
        if not self.account:
            self.skipTest("sin mercadolibre.account en la base de test: %s" % getattr(self, "_account_error", ""))
        self.account.write({'meli_user_site_id': 'MLA'})
        t105 = self._prod(self._tax(10.5), seller='WINNIE S. A', meli_brand='FW', name='CK21 FW')
        t0 = self._prod(self._tax(0.0), seller='CRESKO S.A.', meli_brand='CK', name='CK21 cero')
        Wiz = self.env['mercadolibre.product.template.post'].with_context(
            active_model='product.template', active_ids=[t105.id, t0.id])
        with patch.object(type(Wiz), '_p_suggest_category', return_value=self.env['mercadolibre.category']):
            wiz = Wiz.create({'connectors': self.account.id})
        by = {l.product_tmpl_id: l for l in wiz.p_line_ids}
        self.assertEqual(by[t105].p_vat, '10.5 %')
        self.assertEqual(by[t0].p_vat, '0 %')
        self.assertEqual(by[t105].p_manufacturer, 'WINNIE')
        wiz._w_prepare_template(t105)
        wiz._w_prepare_template(t0)
        self.assertEqual(t105.meli_vat, '10.5 %')   # antes: '21 %' fijo
        self.assertEqual(t0.meli_vat, '0 %')
        self.assertEqual(t0.meli_import_duty, '0 %')
