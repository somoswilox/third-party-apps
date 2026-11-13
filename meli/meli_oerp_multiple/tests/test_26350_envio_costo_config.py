# -*- coding: utf-8 -*-
"""26.350 (#caso-K64 cliente K caso-K28): la configuracion de la cuenta trae el control
`mercadolibre_shipping_cost_as_purchase_price` (default True = comportamiento historico) y el
helper de meli_oerp lo lee de la config real (mercadolibre.configuration)."""
from odoo.addons.meli_oerp.models.versions import meli_shipping_cost_as_purchase_price
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

FIELD = 'mercadolibre_shipping_cost_as_purchase_price'


@tagged('post_install', '-at_install', 'meli_26350_envio_costo')
class TestMeli26350EnvioCostoConfig(TransactionCase):

    def test_campo_existe_con_default_true(self):
        Cfg = self.env['mercadolibre.configuration']
        self.assertIn(FIELD, Cfg._fields, "el campo vuelve con el MISMO nombre (la columna existente manda)")
        self.assertTrue(Cfg.default_get([FIELD]).get(FIELD), "default True: no cambia nada a otros clientes")

    def test_helper_lee_la_config(self):
        Cfg = self.env['mercadolibre.configuration']
        self.assertTrue(meli_shipping_cost_as_purchase_price(Cfg.new({FIELD: True})))
        self.assertFalse(meli_shipping_cost_as_purchase_price(Cfg.new({FIELD: False})))

    def test_campo_en_la_vista(self):
        views = self.env['ir.ui.view'].search([('model', '=', 'mercadolibre.configuration'), ('type', '=', 'form')])
        self.assertTrue(any(FIELD in (v.arch_db or '') for v in views), "el control se ve en la configuracion")
