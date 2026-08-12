from odoo import fields, models, api

import logging
_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.onchange('invoice_payment_term_id', 'currency_id','journal_id')
    def _onchange_account_id(self):
        self.ensure_one()

        payment_lines = self.line_ids.filtered(lambda l: l.display_type == "payment_term")
        if not payment_lines:
            return

        for line in payment_lines:
            account = line.term_account_id
            if not account:
                account = self._get_payment_terms_account()

            if account and line.account_id != account:
                line.account_id = account
                _logger.info("cuenta contable aplicada a linea de pago: %s", account.display_name)

    def write(self, vals):
        res = super().write(vals)
        fields_to_track = ['currency_id', 'invoice_payment_term_id']
        if any(field in vals for field in fields_to_track):
            for move in self:
                move.with_context(tracking_disable=True)._onchange_account_id()
        return res

    def _get_payment_terms_account(self):
        """
        Get the account from invoice that will be set as receivable / payable account.
        :return:                        An account.account record.
        """
        if 'account.change.by.type' in self.env and self.journal_id:
            Change = self.env['account.change.by.type']
            rec = Change.search([
                ('company_id', '=', self.company_id.id),
                ('journal_id', '=', self.journal_id.id),
                ('currency_id', '=', self.currency_id.id),
            ], limit=1)
            if rec:
                return rec.sale_account_id if self.move_type in ('out_invoice','out_refund','out_receipt') else rec.purchase_account_id

        if self.partner_id:
            condition = self.is_sale_document(include_receipts=True)
            partner = self.partner_id
            account_id = partner.with_company(self.company_id).property_account_receivable_id if condition else partner.with_company(self.company_id).property_account_payable_id
            if account_id:
                return account_id

        domain = [
            ('company_ids', 'in', [self.company_id.id]),
            ('account_type', '=', 'asset_receivable' if self.move_type in ('out_invoice', 'out_refund', 'out_receipt') else 'liability_payable'),
            ('deprecated', '=', False),
        ]
        return self.env['account.account'].search(domain, limit=1)

    def _get_data_from_account_payment_term_lines(self, term, invoice_payment_terms):
        res = super(AccountMove, self)._get_data_from_account_payment_term_lines(term, invoice_payment_terms)
        new_account = self._get_payment_terms_account()

        ext_lines = term.get('term_extension', self.env['account.payment.term.line.extension'])

        ext = ext_lines.search([
            ('id', 'in', ext_lines.ids),
            '|', ('currency', '=', self.currency_id.id), ('currency', '=', False),
        ], limit=1)

        #candidate es variable temporal pra almacenar la cuenta que debe asignarse
        candidate = False
        if ext:
            if self.move_type in ('out_invoice', 'out_refund', 'out_receipt'):
                candidate = ext.ledger_account_custom
            else:
                candidate = ext.ledger_account_payable_custom

        if not candidate:
            ledger = term.get('ledger_account_custom')
            ledger_pay = term.get('ledger_account_payable_custom')

            if self.move_type in ('out_invoice', 'out_refund', 'out_receipt') and ledger:
                candidate = ledger
            elif self.move_type in ('in_invoice', 'in_refund', 'in_receipt') and ledger_pay:
                candidate = ledger_pay

        if candidate:
            new_account = candidate

        res['term_account_id'] = new_account.id if new_account else False
        return res


