from odoo.tools.float_utils import float_round
from odoo import models


class AccountPaymentTerm(models.Model):
    _inherit = 'account.payment.term'

    def _compute_terms_line_by_type(self,is_last_line,line,term_vals,residual_amount,
        residual_amount_currency,sign,company_currency,rate,currency,total_amount,total_amount_currency):
        
        if is_last_line:
            # The last line is always the balance, no matter the type
            term_vals['company_amount'] = residual_amount
            term_vals['foreign_amount'] = residual_amount_currency
            
        elif line.value == 'fixed':
            # Fixed amounts
            if line.factor_round > 0.00:
                term_vals['company_amount'] = float_round(sign * company_currency.round(line.value_amount / rate) if rate else 0.0,
                                                          precision_rounding=line.factor_round)
                term_vals['foreign_amount'] = float_round(sign * currency.round(line.value_amount),
                                                          precision_rounding=line.factor_round)
            else:
                term_vals['company_amount'] = sign * company_currency.round(line.value_amount / rate) if rate else 0.0
                term_vals['foreign_amount'] = sign * currency.round(line.value_amount)
        else:
            # Percentage amounts
            if line.factor_round > 0.00:
                term_vals['company_amount'] = float_round(company_currency.round(total_amount * (line.value_amount / 100.0)),precision_rounding=line.factor_round)
                
                term_vals['foreign_amount'] = float_round(currency.round(total_amount_currency * (line.value_amount / 100.0)),
                    precision_rounding=line.factor_round)
            else:
                line_amount = company_currency.round(total_amount * (line.value_amount / 100.0))
                line_amount_currency = currency.round(total_amount_currency * (line.value_amount / 100.0))
                term_vals['company_amount'] = line_amount
                term_vals['foreign_amount'] = line_amount_currency
                
                

