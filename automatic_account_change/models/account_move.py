from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    pay_sell_force_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Forzar cuenta por cobrar o pagar',
    )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        super(AccountMove, self)._onchange_partner_id()
        self._get_change_account()

    @api.onchange('currency_id') 
    def _onchange_currency_change_account(self):
        self._get_change_account()

    def _get_change_account(self):
        if not (self.journal_id and self.currency_id):
            return
        
        move_types_to_change = [
            'out_invoice', 'out_refund', # sale
            'in_invoice', 'in_refund', # purchase
        ]

        account_output = False

        if self.pay_sell_force_account_id:
            account_output = self.pay_sell_force_account_id if self.move_type in move_types_to_change else False
        else:
            account_change = self.env['account.change.by.type'].search([
                ('journal_id', '=', self.journal_id.id),
                ('currency_id', '=', self.currency_id.id)
            ], limit=1)

            if account_change:
                if self.move_type in move_types_to_change[:2]:
                    account_output = account_change.sale_account_id
                elif self.move_type in move_types_to_change[2:]:
                    account_output = account_change.purchase_account_id
                    

        if account_output:
            payment_term_lines = self.line_ids.filtered(lambda line: line.display_type == 'payment_term')
            payment_term_lines.write({'account_id': account_output.id})

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        for move in moves:
            move._get_change_account()
        return moves

    def write(self, vals):
        res = super().write(vals)
        fields_to_track = ['currency_id', 'pay_sell_force_account_id', 'journal_id']
        if any(field in vals for field in fields_to_track):
            for move in self:
                move.with_context(tracking_disable=True)._get_change_account()
        return res
