from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    term_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Parametro temporal para tener calculado cuenta de la linea del término de pago',
    )

    def _set_payment_terms_account(self, payment_terms_lines):
        for line in payment_terms_lines:
            if line.term_account_id:
                line.account_id = line.term_account_id

    def _compute_account_id(self):
        super()._compute_account_id()
        term_lines = self.filtered(lambda line: line.display_type == 'payment_term')
        if term_lines:
            self._set_payment_terms_account(term_lines)