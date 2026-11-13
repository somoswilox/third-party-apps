# -*- coding: utf-8 -*-
"""#caso-K71 (cliente D caso-K07), port 26.386 de 7a911b9: el wizard "Forzar conciliacion" contaba INTENTOS.

`reconciled_count += 1` despues de llamar a meli_reconcile => "Se conciliaron 1 facturas" con la factura
todavia impaga. Ahora mide la factura antes/despues y separa conciliada / parcial / sin cambio.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_K71', 'meli_26386')
class TestK71ContadorConciliacion(TransactionCase):

    def _tax_field(self):
        return 'tax_ids' if 'tax_ids' in self.env['sale.order.line']._fields else 'tax_id'

    def setUp(self):
        super().setUp()
        self.journal = self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1)
        if not self.journal:
            self.skipTest("sin diario de banco en esta base")
        self.partner = self.env['res.partner'].create({'name': 'Comprador #caso-K71 wizard'})
        prod = self.env['product.product'].create({'name': 'Prod #caso-K71', 'type': 'service', 'invoice_policy': 'order',
                                                   'taxes_id': [(6, 0, [])]})
        self.so = self.env['sale.order'].create({'partner_id': self.partner.id, 'order_line': [
            (0, 0, {'product_id': prod.id, 'product_uom_qty': 1, 'price_unit': 100.0, self._tax_field(): [(6, 0, [])]})]})
        self.so.action_confirm()
        self.inv = self.so._create_invoices()
        self.inv.action_post()
        self.wiz = self.env['mercadolibre.orders.actions.wiz'].create({})

    def _mensaje(self, reconcile_side_effect):
        SO = type(self.env['sale.order'])
        with patch.object(SO, 'meli_reconcile', autospec=True, side_effect=reconcile_side_effect, create=True), \
                patch.object(type(self.wiz), '_get_sale_orders', autospec=True, return_value=self.so):
            res = self.wiz._action_force_reconcile()
        return self.env['meli.warning'].browse(res['res_id']).message or ''

    def test_meli_reconcile_que_no_aplica_nada_no_se_cuenta_como_conciliada(self):
        msg = self._mensaje(lambda so, invoice=None: None)
        self.assertNotIn("Se conciliaron 1 facturas", msg)
        self.assertIn("Se conciliaron 0 facturas de 1 intentadas", msg)
        self.assertIn("1 NO se pudieron conciliar", msg)

    def test_control_conciliacion_real_se_cuenta(self):
        def _pagar(so, invoice=None):
            pay = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids).create({'journal_id': self.journal.id})
            pay._create_payments()
        msg = self._mensaje(_pagar)
        self.assertIn("Se conciliaron 1 facturas", msg)
