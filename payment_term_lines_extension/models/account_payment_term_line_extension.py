from odoo import fields, models


class PaymentTermLineExtension(models.Model):
    _name = 'account.payment.term.line.extension'
    _description = 'Payment lines extension'

    payment_term_line_id = fields.Many2one(
        comodel_name='account.payment.term.line'
    )
    currency = fields.Many2one(
        comodel_name='res.currency',
        string='Moneda',
        required=False
    )
    ledger_account_custom = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta contable por cobrar',
        default=False,
        help="Al colocar una cuenta contable, el plazo de pago se generará en esa cuenta contable.",
        required=False,
        company_dependent=True
    )
    ledger_account_payable_custom = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta contable por pagar',
        default=False,
        required=False,
        company_dependent=True
    )



