from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    voucher_payment_date = fields.Date(
        related='move_id.voucher_payment_date',
        string='Fecha pago',
        store=True
    )
    voucher_number = fields.Char(
        related='move_id.voucher_number',
        string='Número recibo',
        store=True
    )