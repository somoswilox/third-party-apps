# -*- coding: utf-8 -*-
"""un cliente (13-oct-2026) — stock de seguridad desde las REGLAS DE STOCK existentes.

Se publica en ML max(0, disponible - N), con N = `security_quantity_stock_to_pause`
("Quantity Stock") de las reglas `meli_oerp.sku.rule` type='stock' de la configuracion:
SKU exacto gana sobre '*', las formula='update_rt' se ignoran, en un kit cuenta la regla del
SKU del kit. El campo 26.208 `mercadolibre_stock_safety_qty` ya no se lee.

Sin red: `_meli_update_logistic_type` se parchea (sin meli_id no llama a ML igual, pero
`get_new_instance` no tiene por que correr en un test).
"""
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'meli_oerp_stock', 'meli_stock_safety')
class TestStockSafetySkuRule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.warehouse = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.company.write({
            'mercadolibre_stock_location_to_post': cls.stock_loc.id,
            'mercadolibre_stock_virtual_available': 'virtual',
            'mercadolibre_stock_sku_mapping': [(5, 0, 0)],
        })
        cls.p_a = cls._storable('SAFE-A', 25.0)
        cls.p_b = cls._storable('SAFE-B', 25.0)
        cls.p_low = cls._storable('SAFE-LOW', 6.0)

    @classmethod
    def _storable(cls, sku, qty):
        Product = cls.env['product.product']
        vals = {'name': 'Safety %s' % sku, 'default_code': sku, 'type': 'consu'}
        if 'is_storable' in Product._fields:
            vals['is_storable'] = True
        else:
            vals['type'] = 'product'
        p = Product.create(vals)
        if qty:
            cls.env['stock.quant']._update_available_quantity(p, cls.stock_loc, qty)
        return p

    def setUp(self):
        super().setUp()
        self.env['product.product']._clear_logistic_type_cache()
        patcher = patch.object(type(self.env['product.product']), '_meli_update_logistic_type',
                               lambda *a, **k: '')
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rules(self, *specs):
        Rule = self.env['meli_oerp.sku.rule']
        recs = Rule
        for i, spec in enumerate(specs):
            vals = {'name': 'Seguridad test %s %s' % (i, spec.get('sku')), 'type': 'stock'}
            vals.update(spec)
            recs |= Rule.create(vals)
        self.company.mercadolibre_stock_sku_mapping = [(6, 0, recs.ids)]
        return recs

    def _qty(self, product):
        return product._meli_available_quantity(config=self.company)

    # --- control negativo -------------------------------------------------
    def test_00_sin_reglas_igual_que_antes(self):
        self.assertEqual(self._qty(self.p_a), 25.0)
        self.assertEqual(self._qty(self.p_low), 6.0)

    def test_01_campo_26208_ya_no_se_lee(self):
        """Sin reglas, aunque el campo viejo tenga valor, no se descuenta nada (no hay doble descuento)."""
        if 'mercadolibre_stock_safety_qty' in self.company._fields:
            self.company.mercadolibre_stock_safety_qty = 7
        self.assertEqual(self._qty(self.p_a), 25.0)
        self._rules({'sku': '*', 'security_quantity_stock_to_pause': 10})
        self.assertEqual(self._qty(self.p_a), 15.0, "solo la regla (10), no regla + campo (17)")

    def test_02_regla_estrella_diez(self):
        self._rules({'sku': '*', 'security_quantity_stock_to_pause': 10})
        self.assertEqual(self._qty(self.p_a), 15.0)
        self.assertEqual(self._qty(self.p_b), 15.0)
        self.assertEqual(self._qty(self.p_low), 0.0, "disponible <= N => 0, nunca negativo")

    def test_03_sku_exacto_gana_a_estrella(self):
        self._rules({'sku': '*', 'security_quantity_stock_to_pause': 10},
                    {'sku': 'SAFE-A', 'security_quantity_stock_to_pause': 3})
        self.assertEqual(self._qty(self.p_a), 22.0, "SAFE-A usa su regla (3), no la '*' (10)")
        self.assertEqual(self._qty(self.p_b), 15.0, "SAFE-B cae en '*'")

    def test_04_solo_sku_exacto(self):
        self._rules({'sku': 'SAFE-B', 'security_quantity_stock_to_pause': 5})
        self.assertEqual(self._qty(self.p_a), 25.0)
        self.assertEqual(self._qty(self.p_b), 20.0)

    def test_05_update_rt_ignorada(self):
        self._rules({'sku': '*', 'formula': 'update_rt', 'security_quantity_stock_to_pause': 10,
                     'security_virtual_stock_to_pause': 5})
        self.assertEqual(self._qty(self.p_a), 25.0)

    def test_06_reglas_no_stock_o_en_cero_ignoradas(self):
        self._rules({'sku': '*', 'type': 'map', 'security_quantity_stock_to_pause': 10},
                    {'sku': 'SAFE-A', 'security_quantity_stock_to_pause': 0},
                    {'sku': '*', 'security_virtual_stock_to_pause': 9})
        self.assertEqual(self._qty(self.p_a), 25.0)

    def test_07_kit_usa_regla_del_kit_no_de_componentes(self):
        if 'mrp.bom' not in self.env:
            self.skipTest("mrp no instalado")
        comp = self._storable('SAFE-COMP', 30.0)
        kit = self._storable('SAFE-KIT', 0.0)
        self.env['mrp.bom'].create({
            'product_tmpl_id': kit.product_tmpl_id.id,
            'product_id': kit.id,
            'type': 'phantom',
            'bom_line_ids': [(0, 0, {'product_id': comp.id, 'product_qty': 2.0})],
        })
        self.env['product.product']._clear_logistic_type_cache()
        self.assertEqual(self._qty(kit), 15.0, "control: 30 / 2 = 15 kits sin reglas")
        self._rules({'sku': '*', 'security_quantity_stock_to_pause': 10},
                    {'sku': 'SAFE-COMP', 'security_quantity_stock_to_pause': 20})
        self.env['product.product']._clear_logistic_type_cache()
        # si se aplicara la regla del componente: (30-20)/2=5 -> 5-10 = 0
        self.assertEqual(self._qty(kit), 5.0, "kit: 15 - regla '*' (10); la del componente no entra")

    def test_08_diagnostico_mismo_n_que_el_envio(self):
        self._rules({'sku': '*', 'security_quantity_stock_to_pause': 10},
                    {'sku': 'SAFE-A', 'security_quantity_stock_to_pause': 3},
                    {'sku': '*', 'formula': 'update_rt', 'security_quantity_stock_to_pause': 50})
        resolve = self.company._meli_stock_safety_resolver()
        self.assertEqual(resolve('SAFE-A'), 3.0)
        self.assertEqual(resolve('SAFE-B'), 10.0)
        self.assertEqual(resolve(None), 10.0)
        self.assertEqual(self.company._meli_stock_safety_qty('SAFE-A'), 3.0)

    def test_09_diagnostico_sin_reglas_cero(self):
        if 'mercadolibre_stock_safety_qty' in self.company._fields:
            self.company.mercadolibre_stock_safety_qty = 7
        self.assertEqual(self.company._meli_stock_safety_resolver()('SAFE-A'), 0.0)
