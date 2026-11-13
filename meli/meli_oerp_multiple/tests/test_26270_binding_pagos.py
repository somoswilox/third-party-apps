# -*- coding: utf-8 -*-
"""26.270: pagos de mercadolibre.payment (binding de meli_oerp_multiple).

Hoy _get_ml_journal/_get_ml_partner devuelven None (circuito apagado), pero el codigo de alta
pasaba 'communication' (no existe en account.payment desde Odoo 14) y no fijaba la linea de metodo.
El test fuerza diario/partner con patch y mide: alta sin error, referencia en memo/ref, linea con
cuenta, y sin linea valida no se crea. Control (origin 26.269): el alta revienta por 'communication'.
"""
from unittest.mock import patch

from odoo import fields, release
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18


@tagged('post_install', '-at_install', 'meli_26270')
class TestBindingPagos26270(TransactionCase):

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
        acc_vals = {'name': 'Pagos ML binding 26270', 'code': '1270002',
                    'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in self.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            acc_vals['company_id'] = self.co.id
        self.cuenta = self.env['account.account'].create(acc_vals)
        self.journal = self.env['account.journal'].create({
            'name': 'MP binding 26270', 'code': 'B270', 'type': 'bank', 'company_id': self.co.id})
        for f in ('account_journal_payment_debit_account_id', 'account_journal_payment_credit_account_id'):
            if f in self.co._fields:
                self.co[f] = False
        if 'mercadolibre_notification_mode' in self.co._fields:
            self.co.mercadolibre_notification_mode = 'none'
        self.ml = self.env['res.partner'].create({'name': 'MercadoLibre binding 26270'})
        self.buyer = self.env['res.partner'].create({'name': 'Comprador binding 26270'})
        Pay = type(self.env['mercadolibre.payment'])
        for name, val in (('_get_ml_journal', self.journal), ('_get_ml_partner', self.ml)):
            p = patch.object(Pay, name, lambda self, *a, _v=val, **k: _v)
            p.start()
            self.addCleanup(p.stop)
        if V18:
            Move = type(self.env['account.move'])
            p = patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'in_payment')
            p.start()
            self.addCleanup(p.stop)
        self.so = self.env['sale.order'].create({'partner_id': self.buyer.id})
        try:
            mo = self._crear_minimo('mercadolibre.sale_order', {'name': '2000270999', 'sale_order': self.so.id,
                                                                'shipping_seller_cost': 15.0})
            self.mp = self._crear_minimo('mercadolibre.payment', {
                'order_id': mo.id, 'payment_id': '2709', 'status': 'approved',
                'currency_id': self.co.currency_id.name, 'total_paid_amount': 100.0, 'fee_amount': 10.0})
        except Exception as e:
            self.skipTest("no se pudo crear el binding de pago en esta base: %s" % e)

    def _lineas(self, tipo, *specs):
        method = self.env.ref('account.account_payment_method_manual_%s' % ('out' if tipo == 'outbound' else 'in'))
        cmds = [(5, 0, 0)] + [(0, 0, {'name': n, 'payment_method_id': method.id, 'sequence': i + 1,
                                     'payment_account_id': self.cuenta.id if c else False})
                              for i, (n, c) in enumerate(specs)]
        self.journal['%s_payment_method_line_ids' % tipo] = cmds
        return self.journal._get_available_payment_method_lines(tipo)

    def _ref(self, pay):
        return pay.memo if 'memo' in pay._fields else pay.ref

    def test_comision_binding_crea_con_linea_y_referencia(self):
        lines = self._lineas('outbound', ('Online', False), ('Pago manual', True))
        self.mp.create_supplier_payment()
        pay = self.mp.account_supplier_payment_id
        self.assertTrue(pay)
        self.assertEqual(pay.payment_method_line_id, lines[1])
        self.assertIn('OP 2709 FEE', self._ref(pay) or '')
        self.assertTrue(pay.move_id)

    def test_envio_binding_crea_con_linea(self):
        lines = self._lineas('outbound', ('Online', False), ('Pago manual', True))
        self.mp.create_supplier_payment_shipment()
        pay = self.mp.account_supplier_payment_shipment_id
        self.assertTrue(pay)
        self.assertEqual(pay.payment_method_line_id, lines[1])

    def test_cobro_binding_crea_con_linea(self):
        lines = self._lineas('inbound', ('Online', False), ('Pago manual', True))
        self.mp.create_payment()
        pay = self.mp.account_payment_id
        self.assertTrue(pay)
        self.assertEqual(pay.payment_method_line_id, lines[1])

    def test_binding_sin_linea_no_crea_y_avisa_en_modo_none(self):
        self._lineas('outbound', ('Online', False))
        with self.assertLogs('odoo.addons.meli_oerp.models.versions', level='WARNING'):
            self.mp.create_supplier_payment()
        self.assertFalse(self.mp.account_supplier_payment_id)
        body = " || ".join(str(m.body) for m in self.so.message_ids if m.body)
        self.assertIn("No se registro el pago de comision", body)
