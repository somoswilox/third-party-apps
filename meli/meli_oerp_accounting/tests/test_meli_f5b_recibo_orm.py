# -*- coding: utf-8 -*-
"""[#caso-K60 F5b, un cliente] Recibo del ULTIMO pago de un carrito: create_payment real (tag `meli_f5b`).

Carrito de 2 sub-ordenes, cada pago trae SOLO su producto; el envio lo paga el comprador y no
viene en ningun pago. Antes el ultimo recibo quedaba corto por el envio (factura "cancelada
parcialmente", el cliente lo corregia a mano). Ahora cierra al total del pedido, nunca lo pasa.
Sin red: create_payment(meli=None) no llama a ML.
"""
from odoo.tests import common, tagged


@tagged('post_install', '-at_install', 'meli', 'meli_f5b')
class TestMeliF5bReciboCarrito(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # [26.369] diario con metodo entrante y cuenta de pagos pendientes (sin ella create_payment
        # no registra nada desde 26.3xx y el test daria rojo por otro motivo).
        acc_vals = {'name': 'Cobros ML F5b', 'code': '1526369', 'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in cls.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [cls.company.id])]
        else:
            acc_vals['company_id'] = cls.company.id
        cuenta = cls.env['account.account'].create(acc_vals)
        manual = cls.env.ref('account.account_payment_method_manual_in')
        cls.journal = cls.env['account.journal'].create({'name': 'MercadoPago F5b', 'code': 'MF5B', 'type': 'bank',
                                                         'company_id': cls.company.id})
        cls.journal.inbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'Pago manual', 'payment_method_id': manual.id, 'payment_account_id': cuenta.id})]
        cls.company.mercadolibre_process_payments_journal = cls.journal.id
        rec_vals = {'name': 'Deudores ML F5b', 'code': '1136369', 'account_type': 'asset_receivable', 'reconcile': True}
        if 'company_ids' in cls.env['account.account']._fields:
            rec_vals['company_ids'] = [(6, 0, [cls.company.id])]
        else:
            rec_vals['company_id'] = cls.company.id
        cls.receivable = cls.env['account.account'].create(rec_vals)
        cls.partner = cls.env['res.partner'].create({'name': 'Comprador carrito F5b',
                                                     'property_account_receivable_id': cls.receivable.id})
        P = cls.env['product.product']
        cls.p1 = P.create({'name': 'F5b rec 1', 'type': 'consu', 'taxes_id': [(6, 0, [])]})
        cls.p2 = P.create({'name': 'F5b rec 2', 'type': 'consu', 'taxes_id': [(6, 0, [])]})
        cls.ship = P.create({'name': 'Envio F5b', 'type': 'service', 'taxes_id': [(6, 0, [])]})

    @property
    def _tax_f(self):
        # sale.order.line: 'tax_id' hasta 18, 'tax_ids' desde 19
        return 'tax_ids' if 'tax_ids' in self.env['sale.order.line']._fields else 'tax_id'

    def _carrito(self, tag, shipping, items=(12012.00, 30901.20)):
        lines = [(self.p1, items[0]), (self.p2, items[1])] + ([(self.ship, shipping)] if shipping else [])
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'company_id': self.company.id,
            'meli_shipping_amount': shipping,
            'order_line': [(0, 0, {'product_id': p.id, 'product_uom_qty': 1, 'price_unit': pu,
                                   self._tax_f: [(6, 0, [])]}) for p, pu in lines]})
        pays = self.env['mercadolibre.payments']
        for i, amount in enumerate(items, 1):
            mo = self.env['mercadolibre.orders'].create({'order_id': '%s-%d' % (tag, i), 'sale_order': so.id})
            so.meli_orders = [(4, mo.id)]
            pays |= self.env['mercadolibre.payments'].create({
                'order_id': mo.id, 'payment_id': '%s%d' % ({'F5BR': 7001, 'F5BX': 7002, 'F5BS': 7003}[tag], i), 'status': 'approved',
                'transaction_amount': amount, 'total_paid_amount': amount, 'shipping_amount': 0.0,
                'currency_id': self.company.currency_id.name})
        return so, pays

    def _recibos(self, pays):
        for p in pays:
            p.create_payment(meli=None, config=self.company)
        self.assertTrue(all(p.account_payment_id for p in pays), "se crean los dos recibos")
        return [p.account_payment_id.amount for p in pays]

    def test_envio_pagado_por_el_comprador_cierra_el_ultimo_recibo(self):
        so, pays = self._carrito('F5BR', 1500.00)
        self.assertAlmostEqual(so.amount_total, 44413.20, places=2)
        amounts = self._recibos(pays)
        self.assertAlmostEqual(amounts[0], 12012.00, places=2, msg="el primero queda crudo")
        self.assertAlmostEqual(amounts[1], 32401.20, places=2, msg="el ultimo absorbe el envio")
        self.assertAlmostEqual(sum(amounts), so.amount_total, places=2, msg="recibos == factura")

    def test_diferencia_que_el_envio_no_explica_queda_cruda(self):
        """Mismo carrito sin envio, pero el pedido tiene 1.500 de mas (linea de otro origen): el
        ajuste NO inventa plata; el ultimo recibo queda con su monto crudo."""
        so, pays = self._carrito('F5BX', 0.0)
        so.order_line = [(0, 0, {'product_id': self.ship.id, 'product_uom_qty': 1, 'price_unit': 1500.0,
                                 self._tax_f: [(6, 0, [])]})]
        amounts = self._recibos(pays)
        self.assertAlmostEqual(amounts[1], 30901.20, places=2)
        self.assertLess(sum(amounts), so.amount_total)

    def test_caso_real_carrito_con_flete_en_pago_aparte(self):
        """[26.369] Caso real (28-oct-2026): carrito de 2 ordenes (29.999 + 5.670,10); el
        comprador pago el flete 9.149,78 en un pago MP aparte (marketplace_shipment) que no es de
        ninguna orden. Los recibos tienen que sumar la factura (44.818,88), no dejar saldo = flete."""
        so, pays = self._carrito('F5BS', 9149.78, items=(29999.00, 5670.10))
        self.assertAlmostEqual(so.amount_total, 44818.88, places=2)
        amounts = self._recibos(pays)
        self.assertAlmostEqual(sum(amounts), so.amount_total, places=2, msg="recibos == factura (sin saldo = flete)")
