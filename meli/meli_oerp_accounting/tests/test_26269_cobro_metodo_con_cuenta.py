# -*- coding: utf-8 -*-
"""26.269 (#caso-K15/#caso-K49, 22-oct-2026): cobro ML con linea de metodo EXPLICITA.

create_payment no fijaba payment_method_line_id: Odoo tomaba la primera linea entrante del
diario. La "Cuenta de pagos pendientes" del cobro sale de esa linea; en 18/19 no hay default de
compania, asi que si la primera es "Online" sin cuenta el cobro queda SIN ASIENTO.

Ahora: si la linea por defecto es valida se usa esa (sin cambio); si no, la primera con cuenta;
si ninguna, no se crea el cobro y queda el motivo en el chatter de la venta.

En 18/19 se simula contabilidad completa (account_accountant, como en Odoo.sh): sin ella Odoo
Community le pone al pago la cuenta pendiente del plan y el problema no aparece.
test_default_respetado mide que ese default (y el de compania en 16/17) se sigue usando.

Control: test_control_mecanismo_sin_linea_explicita reproduce el alta VIEJA (sin linea) y mide
que en 18/19 queda sin asiento. Ademas, corrido contra origin (sin el fix),
test_online_sin_cuenta_primero_usa_la_manual falla.
"""
from unittest.mock import patch

from odoo import fields, release
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18


@tagged('post_install', '-at_install', 'meli_26269')
class TestCobroMetodoConCuenta26269(TransactionCase):

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
        acc_vals = {'name': 'Cobros ML pendientes 26269', 'code': '1269001',
                    'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in self.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            acc_vals['company_id'] = self.co.id
        self.cuenta = self.env['account.account'].create(acc_vals)
        self.manual = self.env.ref('account.account_payment_method_manual_in')
        self.journal = self.env['account.journal'].create({
            'name': 'MercadoPago 26269', 'code': 'M269', 'type': 'bank', 'company_id': self.co.id})
        # 16/17: sin default de compania, para que "sin cuenta" sea sin cuenta de verdad.
        for f in ('account_journal_payment_debit_account_id',):
            if f in self.co._fields:
                self.co[f] = False
        self.co.mercadolibre_process_payments_journal = self.journal
        if 'mercadolibre_payment_receipt_validation' in self.co._fields:
            self.co.mercadolibre_payment_receipt_validation = 'validate'
        if 'mercadolibre_notification_mode' in self.co._fields:
            self.co.mercadolibre_notification_mode = 'internal_note'
        if 'mercadolibre_order_total_config' in self.co._fields:
            self.co.mercadolibre_order_total_config = False
        self.partner = self.env['res.partner'].create({'name': 'Comprador ML 26269'})
        self.n = 0
        if V18:
            Move = type(self.env['account.move'])
            p = patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'in_payment', create=False)
            p.start()
            self.addCleanup(p.stop)

    def _lineas(self, *specs):
        """specs = (nombre, con_cuenta) en el orden del diario."""
        cmds = [(5, 0, 0)]
        for i, (name, con_cuenta) in enumerate(specs):
            cmds.append((0, 0, {'name': name, 'payment_method_id': self.manual.id, 'sequence': i + 1,
                                'payment_account_id': self.cuenta.id if con_cuenta else False}))
        self.journal.inbound_payment_method_line_ids = cmds
        return self.journal._get_available_payment_method_lines('inbound')

    def _pago_ml(self):
        self.n += 1
        so = self.env['sale.order'].create({'partner_id': self.partner.id})
        ml_id = '20009035072066%02d' % self.n
        try:
            mo = self._crear_minimo('mercadolibre.orders', {'order_id': ml_id, 'name': ml_id, 'sale_order': so.id})
            pay = self._crear_minimo('mercadolibre.payments', {
                'order_id': mo.id, 'payment_id': '26900%02d' % self.n, 'status': 'approved',
                'currency_id': self.co.currency_id.name, 'transaction_amount': 100.0, 'total_paid_amount': 100.0})
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        return so, pay

    def _chatter(self, so):
        return " || ".join(str(m.body) for m in so.message_ids if m.body)

    def test_online_sin_cuenta_primero_usa_la_manual(self):
        lines = self._lineas(('Online', False), ('Pago manual', True))
        so, mp = self._pago_ml()
        mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertTrue(pay, "tiene que crear el cobro")
        self.assertEqual(pay.payment_method_line_id, lines[1], "usa la linea CON cuenta, no la primera")
        self.assertEqual(pay.outstanding_account_id, self.cuenta)
        self.assertTrue(pay.move_id, "el cobro tiene asiento")
        self.assertNotEqual(pay.state, 'draft')

    def test_primera_valida_no_cambia(self):
        lines = self._lineas(('Pago manual', True), ('Online', False))
        so, mp = self._pago_ml()
        mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertEqual(pay.payment_method_line_id, lines[0], "con la primera valida, la misma que elegia Odoo")
        self.assertTrue(pay.move_id)

    def test_ninguna_con_cuenta_no_crea_y_avisa_en_la_venta(self):
        self._lineas(('Online', False), ('Pago manual', False))
        so, mp = self._pago_ml()
        # dinero sin registrar: el WARNING es parte del contrato (aviso al operador)
        with self.assertLogs('odoo.addons.meli_oerp_accounting.models.payments', level='WARNING'), self.assertLogs('odoo.addons.meli_oerp.models.versions', level='WARNING'):
            mp.create_payment(config=self.co)
        self.assertFalse(mp.account_payment_id, "sin linea valida no se crea un cobro sin asiento")
        self.assertIn("No se registro el cobro de MercadoLibre %s" % mp.payment_id, self._chatter(so))
        self.assertIn("Cuenta de pagos pendientes", self._chatter(so))
        # once_key: un reintento del cron no repite el aviso
        n = len(so.message_ids)
        with self.assertLogs('odoo.addons.meli_oerp_accounting.models.payments', level='WARNING'), self.assertLogs('odoo.addons.meli_oerp.models.versions', level='WARNING'):
            mp.create_payment(config=self.co)
        self.assertEqual(len(so.message_ids), n)

    def test_control_mecanismo_sin_linea_explicita(self):
        """Alta VIEJA (sin payment_method_line_id): Odoo toma la primera linea.
        18/19 (con contabilidad completa): el cobro queda SIN ASIENTO.
        16/17 (sin default de compania): el alta revienta con UserError (el cobro no se registra)."""
        lines = self._lineas(('Online', False), ('Pago manual', True))
        vals = {'company_id': self.co.id, 'partner_id': self.partner.id, 'payment_type': 'inbound',
                'partner_type': 'customer', 'journal_id': self.journal.id, 'amount': 100.0}
        if V18:
            pay = self.env['account.payment'].create(vals)
            pay.action_post()
            self.assertEqual(pay.payment_method_line_id, lines[0])
            self.assertFalse(pay.move_id, "control: la primera linea sin cuenta deja el cobro sin asiento")
        else:
            with self.assertRaises(UserError):
                self.env['account.payment'].create(vals)

    def test_default_respetado(self):
        """Ninguna linea con cuenta, pero la version tiene default: se crea igual, como antes."""
        lines = self._lineas(('Online', False), ('Pago manual', False))
        if V18:
            Move = type(self.env['account.move'])
            with patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'paid'):
                so, mp = self._pago_ml()
                mp.create_payment(config=self.co)
        else:
            self.co.account_journal_payment_debit_account_id = self.cuenta
            so, mp = self._pago_ml()
            mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertTrue(pay, "con default de la version el cobro se crea")
        self.assertEqual(pay.payment_method_line_id, lines[0], "y con la linea que elegia Odoo")
        self.assertTrue(pay.move_id)
