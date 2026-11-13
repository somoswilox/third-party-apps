# -*- coding: utf-8 -*-
"""26.270: pagos SALIENTES de ML (comision y envio) con linea de metodo EXPLICITA, y el aviso de
dinero sin registrar SIEMPRE en el chatter (aunque el modo de notificaciones sea 'none').

Mismo criterio que el cobro (26.269): linea por defecto si tiene "Cuenta de pagos pendientes"; si
no, la primera que la tenga; respeta el default de compania (16/17) y el de Community (18/19). Sin
linea valida: no se crea el pago y queda el motivo en la venta.
En 18/19 se simula contabilidad completa (account_accountant, como Odoo.sh).
Control: corrido contra origin (26.269) los tests de linea y de aviso fallan;
test_control_mecanismo_saliente mide el alta vieja (sin linea) en cada version.
"""
from unittest.mock import patch

from odoo import fields, release
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18


@tagged('post_install', '-at_install', 'meli_26270')
class TestPagosSalientes26270(TransactionCase):

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
        acc_vals = {'name': 'Pagos ML pendientes 26270', 'code': '1270001',
                    'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in self.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            acc_vals['company_id'] = self.co.id
        self.cuenta = self.env['account.account'].create(acc_vals)
        self.manual_in = self.env.ref('account.account_payment_method_manual_in')
        self.manual_out = self.env.ref('account.account_payment_method_manual_out')
        self.journal = self.env['account.journal'].create({
            'name': 'MercadoPago 26270', 'code': 'M270', 'type': 'bank', 'company_id': self.co.id})
        for f in ('account_journal_payment_debit_account_id', 'account_journal_payment_credit_account_id'):
            if f in self.co._fields:
                self.co[f] = False
        self.ml = self.env['res.partner'].create({'name': 'MercadoLibre SRL 26270'})
        self.co.mercadolibre_process_payments_journal = self.journal
        self.co.mercadolibre_process_payments_res_partner = self.ml
        for f, v in (('mercadolibre_process_payments_journal_shp', self.journal),
                     ('mercadolibre_process_payments_res_partner_shp', self.ml),
                     ('mercadolibre_payment_receipt_validation', 'validate'),
                     ('mercadolibre_notification_mode', 'internal_note'),
                     ('mercadolibre_order_total_config', False)):
            if f in self.co._fields:
                self.co[f] = v
        self.buyer = self.env['res.partner'].create({'name': 'Comprador ML 26270'})
        self.n = 0
        if V18:
            Move = type(self.env['account.move'])
            p = patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'in_payment')
            p.start()
            self.addCleanup(p.stop)

    def _lineas(self, tipo, *specs):
        cmds = [(5, 0, 0)]
        method = self.manual_out if tipo == 'outbound' else self.manual_in
        for i, (name, con_cuenta) in enumerate(specs):
            cmds.append((0, 0, {'name': name, 'payment_method_id': method.id, 'sequence': i + 1,
                                'payment_account_id': self.cuenta.id if con_cuenta else False}))
        self.journal['%s_payment_method_line_ids' % tipo] = cmds
        return self.journal._get_available_payment_method_lines(tipo)

    def _pago_ml(self, envio=0.0):
        self.n += 1
        so = self.env['sale.order'].create({'partner_id': self.buyer.id})
        ml_id = '20006030021436%02d' % self.n
        try:
            mo = self._crear_minimo('mercadolibre.orders', {'order_id': ml_id, 'name': ml_id, 'sale_order': so.id})
            pay = self._crear_minimo('mercadolibre.payments', {
                'order_id': mo.id, 'payment_id': '27000%02d' % self.n, 'status': 'approved',
                'currency_id': self.co.currency_id.name, 'transaction_amount': 100.0,
                'total_paid_amount': 100.0, 'fee_amount': 10.0})
            if 'company_id' in mo._fields:
                mo.company_id = self.co   # la config de la orden = la compania (como en la ingesta)
            if envio:
                mo.shipping_seller_cost = envio
                if 'meli_shipping_seller_cost' in so._fields:
                    so.meli_shipping_seller_cost = envio
                if 'shipping_amount' in pay._fields:
                    pay.shipping_amount = envio
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        return so, pay

    def _chatter(self, so):
        return " || ".join(str(m.body) for m in so.message_ids if m.body)

    # ------------------------------------------------------------------ comision
    def test_comision_online_sin_cuenta_primero_usa_la_manual(self):
        lines = self._lineas('outbound', ('Online', False), ('Pago manual', True))
        so, mp = self._pago_ml()
        mp.create_supplier_payment(config=self.co)
        pay = mp.account_supplier_payment_id
        self.assertTrue(pay, "tiene que crear el pago de comision")
        self.assertEqual(pay.payment_method_line_id, lines[1])
        self.assertTrue(pay.move_id, "el pago de comision tiene asiento")

    def test_comision_primera_valida_no_cambia(self):
        lines = self._lineas('outbound', ('Pago manual', True), ('Online', False))
        so, mp = self._pago_ml()
        mp.create_supplier_payment(config=self.co)
        self.assertEqual(mp.account_supplier_payment_id.payment_method_line_id, lines[0])

    def test_comision_ninguna_valida_no_crea_y_avisa_aun_en_modo_none(self):
        self._lineas('outbound', ('Online', False), ('Pago manual', False))
        if 'mercadolibre_notification_mode' in self.co._fields:
            self.co.mercadolibre_notification_mode = 'none'
        so, mp = self._pago_ml()
        with self.assertLogs('odoo.addons.meli_oerp.models.versions', level='WARNING'):
            mp.create_supplier_payment(config=self.co)
        self.assertFalse(mp.account_supplier_payment_id)
        self.assertIn("No se registro el pago de comision", self._chatter(so),
                      "dinero sin registrar: el aviso va al chatter aunque el modo sea 'none'")
        n = len(so.message_ids)
        with self.assertLogs('odoo.addons.meli_oerp.models.versions', level='WARNING'):
            mp.create_supplier_payment(config=self.co)
        self.assertEqual(len(so.message_ids), n, "una sola vez por pago")

    # ------------------------------------------------------------------ envio
    def test_envio_online_sin_cuenta_primero_usa_la_manual(self):
        lines = self._lineas('outbound', ('Online', False), ('Pago manual', True))
        so, mp = self._pago_ml(envio=15.0)
        mp.create_supplier_payment_shipment(config=self.co)
        pay = mp.account_supplier_payment_shipment_id
        self.assertTrue(pay, "tiene que crear el pago de envio")
        self.assertEqual(pay.payment_method_line_id, lines[1])
        self.assertTrue(pay.move_id)

    def test_envio_ninguna_valida_no_crea_y_avisa(self):
        self._lineas('outbound', ('Online', False), ('Pago manual', False))
        so, mp = self._pago_ml(envio=15.0)
        with self.assertLogs('odoo.addons.meli_oerp.models.versions', level='WARNING'):
            mp.create_supplier_payment_shipment(config=self.co)
        self.assertFalse(mp.account_supplier_payment_shipment_id)
        self.assertIn("No se registro el pago de envio", self._chatter(so))

    # ------------------------------------------------------------------ cobro en modo none
    def test_cobro_sin_linea_en_modo_none_avisa_en_chatter(self):
        self._lineas('inbound', ('Online', False))
        if 'mercadolibre_notification_mode' not in self.co._fields:
            self.skipTest("sin modo de notificaciones")
        self.co.mercadolibre_notification_mode = 'none'
        so, mp = self._pago_ml()
        with self.assertLogs('odoo.addons.meli_oerp_accounting.models.payments', level='WARNING'), self.assertLogs('odoo.addons.meli_oerp.models.versions', level='WARNING'):
            mp.create_payment(config=self.co)
        self.assertFalse(mp.account_payment_id)
        self.assertIn("No se registro el cobro de MercadoLibre", self._chatter(so))

    # ------------------------------------------------------------------ defaults / control
    def test_default_respetado_saliente(self):
        lines = self._lineas('outbound', ('Online', False), ('Pago manual', False))
        if V18:
            Move = type(self.env['account.move'])
            with patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'paid'):
                so, mp = self._pago_ml()
                mp.create_supplier_payment(config=self.co)
        else:
            self.co.account_journal_payment_credit_account_id = self.cuenta
            so, mp = self._pago_ml()
            mp.create_supplier_payment(config=self.co)
        pay = mp.account_supplier_payment_id
        self.assertTrue(pay, "con default de la version el pago se crea")
        self.assertEqual(pay.payment_method_line_id, lines[0])
        self.assertTrue(pay.move_id)

    def test_control_mecanismo_saliente(self):
        """Alta VIEJA (sin linea): 18/19 Enterprise sin asiento; 16/17 sin default revienta."""
        lines = self._lineas('outbound', ('Online', False), ('Pago manual', True))
        vals = {'company_id': self.co.id, 'partner_id': self.ml.id, 'payment_type': 'outbound',
                'partner_type': 'supplier', 'journal_id': self.journal.id, 'amount': 10.0}
        if V18:
            pay = self.env['account.payment'].create(vals)
            pay.action_post()
            self.assertEqual(pay.payment_method_line_id, lines[0])
            self.assertFalse(pay.move_id)
        else:
            with self.assertRaises(UserError):
                self.env['account.payment'].create(vals)
