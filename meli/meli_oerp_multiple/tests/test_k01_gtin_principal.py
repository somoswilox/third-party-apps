# -*- coding: utf-8 -*-
"""#caso-K35 (cliente B caso-K01, 21-oct-2026): PMG4200_14 / PMG10845_W (plantilla con variantes, "publicar como
variantes", variante principal definida, barcode valido en cada variante) no publicaban:
ML respondia item.attribute.missing_conditional_required [GTIN].

Medido EN SECO en la base de cliente B (26.134): con "User Product Seller" el body sale con family_name
y SIN variations[] (_product_post las borra), y _product_post_set_attributes salteaba
SELLER_SKU/GTIN de item "porque van por variacion" => el GTIN no viajaba por ningun lado.
Con el gate corregido el mismo body lleva SELLER_SKU + GTIN y /items/validate ya no lo pide.

Sin red: get_new_instance queda parcheado para fallar si se intenta.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_K01')
class TestGtinUps577(TransactionCase):

    def setUp(self):
        super().setUp()
        p = patch.object(type(self.env['meli.util']), 'get_new_instance',
                         side_effect=AssertionError("llamada a ML"))
        p.start()
        self.addCleanup(p.stop)
        self.company = self.env.company
        need = ('mercadolibre_user_product_seller', 'mercadolibre_post_barcode', 'mercadolibre_post_default_code')
        if any(f not in self.company._fields for f in need):
            self.skipTest("config sin los campos de publicacion")
        attr = self.env['product.attribute'].create({'name': 'Color 577', 'create_variant': 'always'})
        v_b = self.env['product.attribute.value'].create({'name': 'Negro', 'attribute_id': attr.id})
        v_w = self.env['product.attribute.value'].create({'name': 'Blanco', 'attribute_id': attr.id})
        self.tmpl = self.env['product.template'].create({
            'name': 'Arturia Keylab Essential 49 (test 577)',
            'attribute_line_ids': [(0, 0, {'attribute_id': attr.id, 'value_ids': [(6, 0, [v_b.id, v_w.id])]})],
        })
        variants = self.tmpl.product_variant_ids
        self.assertEqual(len(variants), 2)
        self.var_b, self.var_w = variants[0], variants[1]
        self.var_b.write({'default_code': 'PMG10845_B', 'barcode': '3760033531922'})
        self.var_w.write({'default_code': 'PMG10845_W', 'barcode': '3760033531823'})
        self.tmpl.write({'meli_pub_as_variant': True, 'meli_pub_principal_variant': self.var_w.id})
        self.company.write({'mercadolibre_post_barcode': True, 'mercadolibre_post_default_code': True})

    def _attrs(self, product, ups):
        self.company.write({'mercadolibre_user_product_seller': ups})
        res = self.env['product.product']._product_post_set_attributes(
            product_tmpl=self.tmpl, product=product, meli=None, config=self.company)
        return dict((a.get('id'), a.get('value_name')) for a in (res or []) if isinstance(a, dict))

    def test_ups_principal_lleva_gtin_y_sku(self):
        a = self._attrs(self.var_w, True)
        self.assertEqual(a.get('GTIN'), '3760033531823')
        self.assertEqual(a.get('SELLER_SKU'), 'PMG10845_W')

    def test_ups_otra_variante_lleva_gtin_y_sku(self):
        # En cliente B el primer post toma la PRIMERA variante (PMG10845_B) como principal.
        a = self._attrs(self.var_b, True)
        self.assertEqual(a.get('GTIN'), '3760033531922')
        self.assertEqual(a.get('SELLER_SKU'), 'PMG10845_B')

    def test_control_sin_ups_gtin_va_por_variacion(self):
        # Control: sin User Product Seller el body lleva variations[] y el GTIN viaja en cada
        # variacion (_update_sku_attribute): a nivel item NO se agrega (igual que antes del fix).
        a = self._attrs(self.var_w, False)
        self.assertNotIn('GTIN', a)
