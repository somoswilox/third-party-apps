# -*- coding: utf-8 -*-
"""26.361 — caso-K39 cliente B1, OFF 720: pagos a proveedor de ML por 0.00 (comision) y envio.

Caso medido en la call del 2-nov-2026: venta ML 2000043159842268, pago MP 186552249020 (6 x 286 =
1716 MXN). MercadoPago informa la comision como cargo `meli_fee` 300.30 (deferred-charges/fees-api)
y fee_details application_fee 300.3; la ingesta dejaba fee_amount=0 (solo sumaba nombres conocidos)
y el pago de comision se creaba por 0.00 y quedaba Pagado. El envio (shp_cross_docking 234.00) es
un pago SALIENTE de 234: el -234.00 de la lista es el importe firmado de Odoo, no el monto.

Fixture: el JSON del pago reducido a los campos que lee el codigo (montos y nombres del caso real).
Control: contra origin 26.358 fallan los tests de comision, de cero, de borrador y de conciliado.
"""
import copy
from unittest.mock import patch

from odoo import fields, release
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18

MP_186552249020 = {
    "id": 186552249020,
    "status": "approved",
    "date_approved": "2026-10-28T15:02:35.000-04:00",
    "currency_id": "MXN",
    "transaction_amount": 1716,
    "shipping_amount": 0,
    "taxes_amount": 0,
    "transaction_details": {"total_paid_amount": 1716, "net_received_amount": 1026.38},
    "fee_details": [{"amount": 300.3, "type": "application_fee", "fee_payer": "collector"}],
    "charges_details": [
        {"id": "c-iva", "name": "tax_withholding-iva", "type": "tax", "base_amount": 1479.31, "rate": 8,
         "accounts": {"from": "collector", "to": "mp"}, "amounts": {"original": 118.34, "refunded": 0}},
        {"id": "c-isr", "name": "tax_withholding-isr", "type": "tax", "rate": 2.5,
         "accounts": {"from": "collector", "to": "mp"}, "amounts": {"original": 36.98, "refunded": 0}},
        {"id": "c-fee", "name": "meli_fee", "type": "fee", "date_created": "2026-10-28T15:02:37.000-04:00",
         "metadata": {"source": "deferred-charges/fees-api"},
         "accounts": {"from": "collector", "to": "ml"}, "amounts": {"original": 300.30, "refunded": 0}},
        {"id": "c-shp", "name": "shp_cross_docking", "type": "shipping",
         "date_created": "2026-10-28T15:02:42.000-04:00",
         "metadata": {"source": "deferred-charges/shipping-account-movements", "shipment_id": 44732689599},
         "accounts": {"from": "collector", "to": "ml"}, "amounts": {"original": 234.00, "refunded": 0}},
    ],
}


@tagged('post_install', '-at_install', 'meli_26361')
class TestCargosML26361(TransactionCase):

    def _crear_minimo(self, model, extra=None, _visitados=None):
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
                    rec = self._crear_minimo(f.comodel_name, None, _visitados)
                vals[name] = rec.id if rec else False
        vals.update(extra or {})
        return Model.create(vals)

    def setUp(self):
        super().setUp()
        self.co = self.env.company
        if not self.env['account.account'].search([('account_type', '=', 'asset_receivable')], limit=1):
            self.skipTest("sin plan de cuentas en esta base")
        acc_vals = {'name': 'Pagos ML pendientes 26361', 'code': '1361001',
                    'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in self.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            acc_vals['company_id'] = self.co.id
        self.cuenta = self.env['account.account'].create(acc_vals)
        self.journal = self.env['account.journal'].create({
            'name': 'Mercado Libre 26361', 'code': 'MK28', 'type': 'bank', 'company_id': self.co.id})
        out = self.env.ref('account.account_payment_method_manual_out')
        self.journal.outbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'Pago manual', 'payment_method_id': out.id, 'payment_account_id': self.cuenta.id})]
        self.ml = self.env['res.partner'].create({'name': 'DEREMATE.COM DE MEXICO 26361'})
        self.co.mercadolibre_process_payments_journal = self.journal
        self.co.mercadolibre_process_payments_res_partner = self.ml
        for f, v in (('mercadolibre_process_payments_journal_shp', self.journal),
                     ('mercadolibre_process_payments_res_partner_shp', self.ml),
                     ('mercadolibre_payment_receipt_validation', 'validate'),
                     ('mercadolibre_notification_mode', 'internal_note'),
                     ('mercadolibre_order_total_config', False)):
            if f in self.co._fields:
                self.co[f] = v
        self.buyer = self.env['res.partner'].create({'name': 'Comprador ML 26361'})
        self.n = 0
        if V18:
            Move = type(self.env['account.move'])
            p = patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'in_payment')
            p.start()
            self.addCleanup(p.stop)

    def _pago_ml(self, fee=0.0, envio=0.0, full_payment=MP_186552249020):
        self.n += 1
        so = self.env['sale.order'].create({'partner_id': self.buyer.id})
        ml_id = '20000315616817%02d' % self.n
        try:
            mo = self._crear_minimo('mercadolibre.orders', {'order_id': ml_id, 'name': ml_id, 'sale_order': so.id})
            pay = self._crear_minimo('mercadolibre.payments', {
                'order_id': mo.id, 'payment_id': '1865522490%02d' % self.n, 'status': 'approved',
                'currency_id': self.co.currency_id.name, 'transaction_amount': 1716.0,
                'total_paid_amount': 1716.0, 'fee_amount': fee,
                'full_payment': str(copy.deepcopy(full_payment)) if full_payment else False})
            if 'company_id' in mo._fields:
                mo.company_id = self.co
            if envio:
                mo.shipping_seller_cost = envio
                if 'meli_shipping_seller_cost' in so._fields:
                    so.meli_shipping_seller_cost = envio
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        return so, pay

    def _chatter(self, so):
        return " || ".join(str(m.body) for m in so.message_ids if m.body)

    def _pago_proveedor(self, amount, ref='FEE'):
        return self.env['account.payment'].create({
            'company_id': self.co.id, 'partner_id': self.ml.id, 'payment_type': 'outbound',
            'partner_type': 'supplier', 'journal_id': self.journal.id, 'amount': amount,
            'payment_method_line_id': self.journal.outbound_payment_method_line_ids[:1].id})

    # ---------------------------------------------------------------- comision
    def test_1_comision_sale_del_json_si_fee_amount_quedo_en_0(self):
        """El pago ML quedo con fee_amount=0 (como en el cliente) y el JSON trae meli_fee 300.30."""
        so, mp = self._pago_ml(fee=0.0)
        mp.create_supplier_payment(config=self.co)
        pay = mp.account_supplier_payment_id
        self.assertTrue(pay, "tiene que crear el pago de comision")
        self.assertAlmostEqual(pay.amount, 300.30, places=2, msg="comision = 300.30, no 0.00")

    def test_2_sin_comision_no_crea_pago_de_cero_y_avisa(self):
        """JSON sin comision todavia (cargo diferido): no se crea un pago de 0.00; aviso una vez."""
        fp = copy.deepcopy(MP_186552249020)
        fp['fee_details'] = []
        fp['charges_details'] = [c for c in fp['charges_details'] if c['type'] == 'tax']
        so, mp = self._pago_ml(fee=0.0, full_payment=fp)
        mp.create_supplier_payment(config=self.co)
        self.assertFalse(mp.account_supplier_payment_id, "no se crea un pago de comision por 0.00")
        self.assertIn("todavia no informa", self._chatter(so))
        n = len(so.message_ids)
        mp.create_supplier_payment(config=self.co)
        self.assertEqual(len(so.message_ids), n, "el aviso va una sola vez")
        # llega el cargo diferido (re-import) => en la pasada siguiente se crea por el monto real
        mp.fee_amount = 300.30
        mp.create_supplier_payment(config=self.co)
        self.assertAlmostEqual(mp.account_supplier_payment_id.amount, 300.30, places=2)

    def test_3_borrador_con_monto_equivocado_se_corrige(self):
        so, mp = self._pago_ml(fee=0.0)
        pay = self._pago_proveedor(1.0)
        mp.account_supplier_payment_id = pay
        self.assertEqual(pay.state, 'draft')
        mp.check_supplier_payment(config=self.co)
        self.assertAlmostEqual(pay.amount, 300.30, places=2, msg="borrador: se corrige al monto de ML")

    def test_4_pagado_conciliado_no_se_toca_y_avisa(self):
        so, mp = self._pago_ml(fee=0.0)
        pay = self._pago_proveedor(1.0)
        pay.action_post()
        # simular conciliado/pagado (como en el cliente: "Pagado")
        self.env.flush_all()
        if V18:
            self.env.cr.execute("UPDATE account_payment SET state='paid' WHERE id=%s", (pay.id,))
        else:
            self.env.cr.execute("UPDATE account_payment SET is_matched=true WHERE id=%s", (pay.id,))
        pay.invalidate_recordset()
        mp.account_supplier_payment_id = pay
        try:
            mp.check_supplier_payment(config=self.co)
        except Exception as e:
            self.fail("corregir un pago conciliado no puede reventar ni tocarlo: %s" % e)
        pay.invalidate_recordset()
        self.assertAlmostEqual(pay.amount, 1.0, places=2, msg="lo conciliado NO se modifica automaticamente")
        self.assertIn("no se modifica automaticamente", self._chatter(so))

    # ---------------------------------------------------------------- envio
    def test_5_envio_es_saliente_positivo_y_la_lista_muestra_negativo(self):
        """Control del -234: el pago se crea por +234 saliente; Odoo lo lista firmado (-234)."""
        so, mp = self._pago_ml(fee=300.30, envio=234.0)
        mp.create_supplier_payment_shipment(config=self.co)
        pay = mp.account_supplier_payment_shipment_id
        self.assertTrue(pay)
        self.assertEqual(pay.payment_type, 'outbound')
        self.assertAlmostEqual(pay.amount, 234.0, places=2)
        signed = next((f for f in ('amount_company_currency_signed', 'amount_signed') if f in pay._fields), None)
        if signed:
            self.assertAlmostEqual(pay[signed], -234.0, places=2,
                                   msg="el -234.00 de la lista es el importe firmado de un pago saliente")

    def test_6_envio_negativo_no_crea_y_avisa(self):
        so, mp = self._pago_ml(fee=300.30, envio=41.0)
        so.meli_shipping_seller_cost = -41.0
        mp.create_supplier_payment_shipment(config=self.co)
        self.assertFalse(mp.account_supplier_payment_shipment_id, "un pago saliente de envio no es negativo")
        self.assertIn("negativo", self._chatter(so))

    def test_7_envio_borrador_con_monto_equivocado_se_corrige(self):
        so, mp = self._pago_ml(fee=300.30, envio=234.0)
        pay = self._pago_proveedor(1.0)
        mp.account_supplier_payment_shipment_id = pay
        if not hasattr(mp, 'check_supplier_payment_shipment'):
            self.fail("falta check_supplier_payment_shipment (el envio nunca se corregia)")
        mp.check_supplier_payment_shipment(config=self.co)
        self.assertAlmostEqual(pay.amount, 234.0, places=2)


@tagged('post_install', '-at_install', 'meli_26361')
class TestComisionDesdeJson26361(TransactionCase):
    """La funcion de meli_oerp que usa la ingesta cuando ningun cargo tiene nombre conocido."""

    def _f(self):
        try:
            from odoo.addons.meli_oerp.models.versions import meli_payment_commission_from_json
        except ImportError:
            self.fail("falta meli_payment_commission_from_json en meli_oerp (la ingesta deja la comision en 0)")
        return meli_payment_commission_from_json

    def test_fee_details(self):
        self.assertAlmostEqual(self._f()(MP_186552249020), 300.30, places=2)

    def test_solo_cargos_meli_fee(self):
        fp = copy.deepcopy(MP_186552249020)
        fp['fee_details'] = []
        self.assertAlmostEqual(self._f()(fp), 300.30, places=2)

    def test_sin_comision_y_financing_fee_no_cuenta(self):
        fp = copy.deepcopy(MP_186552249020)
        fp['fee_details'] = [{"amount": 15.0, "type": "financing_fee", "fee_payer": "payer"}]
        fp['charges_details'] = [c for c in fp['charges_details'] if c['type'] != 'fee'] + [
            {"name": "financing_fee", "type": "fee", "accounts": {"from": "collector"}, "amounts": {"original": 15.0}}]
        self.assertEqual(self._f()(fp), 0.0)
        self.assertEqual(self._f()(None), 0.0)
