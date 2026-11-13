# -*- coding: utf-8 -*-
"""#caso-K47 (caso-K48 cliente O, opcion A): el numero de la linea de retencion del pago es el ID de
operacion de MercadoPago (mercadolibre.payments.payment_id).

Antes la linea nacia sin numero; con l10n_account_withholding_tax, si el impuesto no tiene
secuencia de retenciones Odoo NO deja confirmar el pago ("Please enter the withholding
number") y habia que tipearlo a mano en cada uno. Si el impuesto SI tiene secuencia, numera
Odoo y no se le pisa.

16/17 no tienen el modulo de retenciones al pago: ahi corre solo el helper (sin red).
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MP_ID = '98765432101'


@tagged('post_install', '-at_install', 'meli', 'meli_26273')
class TestWithholdingNumberK47(TransactionCase):

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
        self.Tax = self.env['account.tax']
        self.has_wth = 'is_withholding_tax_on_payment' in self.Tax._fields
        self.mp = self._crear_minimo('mercadolibre.payments', {'payment_id': MP_ID})

    def _tax(self, **extra):
        vals = {'name': 'Ret K47 %s' % len(extra), 'amount': 1.0, 'amount_type': 'percent',
                'type_tax_use': 'sale', 'company_id': self.env.company.id}
        vals.update(extra)
        return self.Tax.create(vals)

    # --- helper: corre en 16/17/18/19 -----------------------------------------------------
    def test_number_is_mp_operation_id(self):
        self.assertEqual(self.mp._meli_withholding_number(self._tax()), MP_ID)

    def test_without_mp_id_no_number(self):
        mp = self._crear_minimo('mercadolibre.payments', {'payment_id': False})
        self.assertFalse(mp._meli_withholding_number(self._tax()))

    # --- con l10n_account_withholding_tax (19) --------------------------------------------
    def _wth_setup(self, with_sequence=False):
        if not self.has_wth or 'withholding_line_ids' not in self.env['account.payment']._fields:
            self.skipTest('sin l10n_account_withholding_tax')
        vals = {'is_withholding_tax_on_payment': True, 'amount': -1.0}
        if with_sequence:
            vals['withholding_sequence_id'] = self.env['ir.sequence'].create(
                {'name': 'Ret K47', 'prefix': 'RET/', 'padding': 4}).id
        tax = self._tax(**vals)
        rule = self.env['mercadolibre.tax'].create({
            'name': 'ISR K47', 'meli_charge_type': 'tax', 'account_tax_id': tax.id,
            'state': 'confirmed', 'company_id': self.env.company.id,
        }) if 'name' in self.env['mercadolibre.tax']._fields else self._crear_minimo(
            'mercadolibre.tax', {'meli_charge_type': 'tax', 'account_tax_id': tax.id, 'state': 'confirmed'})
        self.env['mercadolibre.payment.charge'].create({
            'payment_id': self.mp.id, 'name': 'tax_withholding-isr', 'charge_type': 'tax',
            'amount_original': 10.0, 'base_amount': 1000.0, 'meli_tax_id': rule.id,
        })
        acc = self.env['account.account'].search(
            [('account_type', 'in', ('liability_current', 'asset_current'))], limit=1)
        if not acc:
            self.skipTest('sin plan de cuentas')
        if 'withholding_tax_base_account_id' in self.env.company._fields:
            self.env.company.withholding_tax_base_account_id = acc
        return tax

    def test_prepared_line_carries_mp_id(self):
        self._wth_setup()
        lines = self.mp._prepare_withholding_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][2].get('name'), MP_ID)

    def test_tax_sequence_is_respected(self):
        self._wth_setup(with_sequence=True)
        lines = self.mp._prepare_withholding_lines()
        self.assertEqual(len(lines), 1)
        self.assertNotIn('name', lines[0][2], 'con secuencia propia numera Odoo')

    def test_payment_posts_without_typing_the_number(self):
        self._wth_setup()
        journal = self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1)
        partner = self.env['res.partner'].create({'name': 'Comprador K47'})
        if not journal:
            self.skipTest('sin diario de banco')
        pay = self.env['account.payment'].create({
            'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': partner.id,
            'amount': 990.0, 'journal_id': journal.id, 'should_withhold_tax': True,
            'withholding_line_ids': self.mp._prepare_withholding_lines(),
        })
        try:
            pay.action_post()
        except UserError as e:
            self.fail('el pago no se pudo confirmar: %s' % e)
        self.assertEqual(pay.withholding_line_ids.name, MP_ID)
