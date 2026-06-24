from odoo import models, fields, api, _
from odoo.exceptions import UserError

class PaymentDetractions(models.TransientModel):
    _name = 'payment.detractions'
    _description = 'Payment massive detractions'

    move_ids = fields.Many2many(
        comodel_name='account.move',
        string='account moves'
    )
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Diario',
        domain=[('type', '=', 'bank')]
    )
    other_lines = fields.One2many(
        related='journal_id.outbound_payment_method_line_ids'
    )
    outbound_payment_method_line_id = fields.Many2one(
        comodel_name='account.payment.method.line',
        string='Método de pago',
        domain="[('id', 'in', other_lines)]"
    )
    date = fields.Date(
        string='Fecha',
        required=True,
        default=fields.Date.context_today
    )
    memo = fields.Char(
        string='Memo'
    )
    account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta de destino'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lines = self.env['account.move'].browse(self._context.get('active_ids', []))
        res['move_ids'] = [(6, 0, lines.ids)]
        return res

    def create_payment_account_move(self):
        for move in self.move_ids:
            # Validar que la factura tenga productos con porcentaje de detracción
            amount = self.amount_total_json(move)
            if amount <= 0:
                raise UserError(
                    f"La factura {move.name} no tiene productos con porcentaje de detracción configurado "
                    f"o el monto calculado es 0. Por favor, configure el porcentaje de detracción en los productos."
                )
            payment = self.create_payment(move)
            payment_to_post = self.env['account.payment'].create(payment)
            payment_to_post.action_post()

    def create_payment(self, move):
        detraction_amount = self.amount_total_json(move)

        # Para facturas en moneda extranjera, calcular force_balance usando el TC
        # de la factura (línea de plazo de pago) para que el asiento refleje el
        # importe correcto en soles sin depender de módulos externos de TC.
        force_balance = None
        if move.currency_id != move.company_id.currency_id:
            payment_term_line = move.line_ids.filtered(
                lambda l: l.display_type == 'payment_term' and l.account_id.account_type in ('asset_receivable', 'liability_payable')
            )
            if payment_term_line:
                amount_currency_inv = abs(payment_term_line[0].amount_currency)
                amount_company_inv = abs(payment_term_line[0].debit or payment_term_line[0].credit)
                if amount_currency_inv > 0:
                    rate = amount_company_inv / amount_currency_inv
                    force_balance = detraction_amount * rate

        # Buscar cuenta de destino
        account_destination = False
        for line in move.line_ids:
            if hasattr(line, 'l10n_pe_is_detraction_retention') and line.l10n_pe_is_detraction_retention:
                account_destination = line.account_id.id
                break
        if not account_destination:
            account_destination = move.partner_id.property_account_receivable_id.id

        # Buscar banco
        bank_code = False
        if self.journal_id.bank_account_id:
            for bank in self.env.company.partner_id.bank_ids:
                if bank.acc_number == self.journal_id.bank_account_id.acc_number:
                    bank_code = bank
                    break

        payment_vals = {
            'payment_type': 'outbound',
            'partner_id': move.partner_id.id,
            'amount': detraction_amount,
            'destination_account_id': account_destination,
            'currency_id': move.currency_id.id,
            'date': self.date,
            'memo': self.memo or f"Pago detracción: {move.name}",
            'journal_id': self.journal_id.id,
            'partner_bank_id': bank_code.id if bank_code else False,
            'payment_method_line_id': self.outbound_payment_method_line_id.id,
            'reference_invoice': move.id,
        }
        if force_balance is not None:
            payment_vals['force_balance'] = force_balance
        return payment_vals

    def amount_total_json(self, move):
        amount = float(move.amount_total)
        for line in move.invoice_line_ids:
            if line.product_id.l10n_pe_withhold_percentage:
                amount = amount * float(line.product_id.l10n_pe_withhold_percentage) / 100
                if move.currency_id.name == 'PEN':
                    amount = round(amount)
                return amount
        return 0.0
