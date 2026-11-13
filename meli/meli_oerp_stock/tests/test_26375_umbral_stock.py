# -*- coding: utf-8 -*-
"""26.375 — caso-K10 cliente G (#caso-K69): modo «umbral» en las reglas de stock.

Regla type='stock' con meli_stock_rule_mode='umbral' y "Quantity Stock" = K: si el disponible es menor que K se
publica 0 (ML pausa por falta de stock); si no, el disponible entero. 'resguardo' (default) = comportamiento de
siempre (max(0, disponible - N)). Cada modo resuelve su precedencia por separado (SKU exacto > '*', la mayor) y
se combinan: primero el umbral sobre el disponible, después el resguardo.

    odoo-bin -d <db> -u meli_oerp_stock --test-enable --test-tags meli_26375 --stop-after-init
"""
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'meli_oerp_stock', 'meli_26375')
class TestUmbralStock26375(TransactionCase):

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
        cls.p_a = cls._storable('UMB-A', 4.0)
        cls.p_b = cls._storable('UMB-B', 12.0)

    @classmethod
    def _storable(cls, sku, qty):
        Product = cls.env['product.product']
        vals = {'name': 'Umbral %s' % sku, 'default_code': sku, 'type': 'consu'}
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
        self.assertIn('meli_stock_rule_mode', Rule._fields, "falta el modo de regla (fix 26.375)")
        recs = Rule
        for i, spec in enumerate(specs):
            vals = {'name': 'Umbral test %s %s' % (i, spec.get('sku')), 'type': 'stock'}
            vals.update(spec)
            recs |= Rule.create(vals)
        self.company.mercadolibre_stock_sku_mapping = [(6, 0, recs.ids)]
        return recs

    def _qty(self, product):
        return product._meli_available_quantity(config=self.company)

    def test_00_default_es_resguardo(self):
        rule = self._rules({'sku': '*', 'security_quantity_stock_to_pause': 5})
        self.assertEqual(rule.meli_stock_rule_mode, 'resguardo')
        self.assertEqual(self._qty(self.p_a), 0.0)   # 4 - 5 -> 0
        self.assertEqual(self._qty(self.p_b), 7.0)   # 12 - 5

    def test_01_umbral_debajo_cero_arriba_todo(self):
        self._rules({'sku': '*', 'meli_stock_rule_mode': 'umbral', 'security_quantity_stock_to_pause': 5})
        self.assertEqual(self._qty(self.p_a), 0.0, "4 < 5 => 0")
        self.assertEqual(self._qty(self.p_b), 12.0, "12 >= 5 => el disponible ENTERO (no resta)")

    def test_02_umbral_igual_a_k_publica(self):
        self._rules({'sku': '*', 'meli_stock_rule_mode': 'umbral', 'security_quantity_stock_to_pause': 4})
        self.assertEqual(self._qty(self.p_a), 4.0, "4 no es menor que 4")

    def test_03_umbral_sku_exacto_gana_a_estrella(self):
        self._rules({'sku': '*', 'meli_stock_rule_mode': 'umbral', 'security_quantity_stock_to_pause': 20},
                    {'sku': 'UMB-B', 'meli_stock_rule_mode': 'umbral', 'security_quantity_stock_to_pause': 10})
        self.assertEqual(self._qty(self.p_b), 12.0, "UMB-B usa K=10 (exacto), no K=20 ('*')")
        self.assertEqual(self._qty(self.p_a), 0.0)

    def test_04_umbral_y_resguardo_se_combinan(self):
        self._rules({'sku': '*', 'meli_stock_rule_mode': 'umbral', 'security_quantity_stock_to_pause': 5},
                    {'sku': '*', 'security_quantity_stock_to_pause': 2})
        self.assertEqual(self._qty(self.p_a), 0.0, "umbral: 4 < 5")
        self.assertEqual(self._qty(self.p_b), 10.0, "umbral pasa (12 >= 5), resguardo 2 => 10")

    def test_05_diagnostico_resguardo_no_cuenta_umbral(self):
        """El N que ve el diagnóstico de meli_oerp es sólo el de resguardo: un umbral no se resta."""
        self._rules({'sku': '*', 'meli_stock_rule_mode': 'umbral', 'security_quantity_stock_to_pause': 50},
                    {'sku': 'UMB-A', 'security_quantity_stock_to_pause': 3})
        Rule = self.env['meli_oerp.sku.rule']
        self.assertEqual(Rule._meli_stock_safety_qty_from_config(self.company, 'UMB-A'), 3.0)
        self.assertEqual(Rule._meli_stock_safety_qty_from_config(self.company, 'UMB-B'), 0.0)
