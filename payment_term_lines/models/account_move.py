from dateutil.relativedelta import relativedelta
from odoo.tools import format_date, frozendict

from odoo import api, fields, models


class AccountAccountType(models.Model):
    _inherit = "account.account"

    related_user_account_name = fields.Selection(
        name='Related user account name',
        related='account_type'
    )


class AccountPaymentTermLine(models.Model):
    _inherit = "account.payment.term.line"

    delay_type = fields.Selection(
        selection_add=[('days_after_accounting_date', 'Días después de la fecha contable')],
        ondelete={'days_after_accounting_date': 'set default'}
    )

    l10n_pe_is_detraction_retention = fields.Boolean(string='¿Es un descuento?')

    def _get_data_from_line_ids(self, date_ref, accounting_date_ref=None, **kwargs):
        """Get term data from payment term line.

        Args:
            date_ref: Reference date (invoice date)
            accounting_date_ref: Accounting date (optional)
            **kwargs: Additional arguments for compatibility with POS and other contexts
        """
        term_date = self._get_due_date(date_ref, accounting_date_ref)
        tmp_date_maturity = term_date
        if self.nb_days == 0 and self.l10n_pe_is_detraction_retention == True:
            # Se fuerza el cambio de fecha por un dia inferior para evitar agrupar cuando es de tipo Saldo y no hay diferencia de dias
            tmp_date_maturity += relativedelta(days=-1)
        return {
            'date': term_date,
            'tmp_date_maturity': tmp_date_maturity,
            'l10n_pe_is_detraction_retention': self.l10n_pe_is_detraction_retention,
            'company_amount': 0,
            'foreign_amount': 0,
        }

    def _get_due_date(self, date_ref, accounting_date_ref=None):
        """Override to add support for accounting date calculation"""
        self.ensure_one()

        # If delay_type is days_after_accounting_date, use accounting_date_ref
        if self.delay_type == 'days_after_accounting_date':
            if accounting_date_ref:
                due_date = fields.Date.from_string(accounting_date_ref) or fields.Date.today()
            else:
                # Fallback to date_ref if accounting_date_ref is not provided
                due_date = fields.Date.from_string(date_ref) or fields.Date.today()
            return due_date + relativedelta(days=self.nb_days)

        # For all other delay types, use the standard calculation
        return super()._get_due_date(date_ref)


class AccountPaymentTerm(models.Model):
    _inherit = "account.payment.term"

    def _compute_terms_line_by_type(self, is_last_line, line, term_vals, residual_amount,
        residual_amount_currency, sign, company_currency, rate, currency, total_amount, total_amount_currency):
        if is_last_line:
            term_vals['company_amount'] = residual_amount
            term_vals['foreign_amount'] = residual_amount_currency
        elif line.value == 'fixed':
            # Fixed amounts
            term_vals['company_amount'] = sign * company_currency.round(line.value_amount / rate) if rate else 0.0
            term_vals['foreign_amount'] = sign * currency.round(line.value_amount)
        else:
            # Percentage amounts
            line_amount = company_currency.round(total_amount * (line.value_amount / 100.0))
            line_amount_currency = currency.round(total_amount_currency * (line.value_amount / 100.0))
            term_vals['company_amount'] = line_amount
            term_vals['foreign_amount'] = line_amount_currency
        
    
    def _compute_terms(self, date_ref, currency, company, tax_amount, tax_amount_currency, sign, untaxed_amount, untaxed_amount_currency, accounting_date_ref=None):

        """  Complete overwrite of compute method for adding method _get_data_from_line_ids. """
        self.ensure_one()
        company_currency = company.currency_id
        total_amount = tax_amount + untaxed_amount
        total_amount_currency = tax_amount_currency + untaxed_amount_currency

        pay_term = {
            'total_amount': total_amount,
            'discount_percentage': self.discount_percentage if self.early_discount else 0.0,
            'discount_date': date_ref + relativedelta(days=(self.discount_days or 0)) if self.early_discount else False,
            'discount_balance': 0,
            'line_ids': [],
        }

        if self.early_discount:
            # Early discount is only available on single line, 100% payment terms.
            discount_percentage = self.discount_percentage / 100.0
            if self.early_pay_discount_computation in ('excluded', 'mixed'):
                pay_term['discount_balance'] = company_currency.round(total_amount - untaxed_amount * discount_percentage)
                pay_term['discount_amount_currency'] = currency.round(total_amount_currency - untaxed_amount_currency * discount_percentage)
            else:
                pay_term['discount_balance'] = company_currency.round(total_amount * (1 - discount_percentage))
                pay_term['discount_amount_currency'] = currency.round(total_amount_currency * (1 - discount_percentage))

        rate = abs(total_amount_currency / total_amount) if total_amount else 0.0
        residual_amount = total_amount
        residual_amount_currency = total_amount_currency

        for i, line in enumerate(self.line_ids):
            # Determinamos si esta línea es la última
            is_last_line = i == len(self.line_ids) - 1

            # Obtenemos los datos iniciales de la línea
            term_vals = line._get_data_from_line_ids(date_ref, accounting_date_ref)

            self._compute_terms_line_by_type(
                is_last_line=is_last_line,
                line=line,
                term_vals=term_vals,
                residual_amount=residual_amount,
                residual_amount_currency=residual_amount_currency,
                sign=sign,
                company_currency=company_currency,
                rate=rate,
                currency=currency,
                total_amount=total_amount,
                total_amount_currency=total_amount_currency
            )

            # Actualizamos los montos residuales
            residual_amount -= term_vals['company_amount']
            residual_amount_currency -= term_vals['foreign_amount']

            # Añadimos la línea al término de pago
            pay_term['line_ids'].append(term_vals)

        return pay_term
        

    @api.model
    def _get_amount_by_date(self, terms):
        """
            Se sobreescribe para que divida en lineas diferentes y no agrupe por fecha en el ejemplo visual en las lineas de pago
        """
        terms = sorted(terms["line_ids"], key=lambda t: t.get('date'))
        amount_by_date = {}
        for term in terms:
            key = frozendict({
                'date': term['date'],
                # Parametro para evitar que se agrupe
                'tmp_date_maturity': term['tmp_date_maturity'],
            })
            results = amount_by_date.setdefault(key, {
                'tmp_date_maturity': format_date(self.env, term['tmp_date_maturity']),
                'date': format_date(self.env, term['date']),
                'amount': 0.0,
            })
            results['amount'] += term['foreign_amount']
        return amount_by_date

class AccountMove(models.Model):
    _inherit = 'account.move'

    @staticmethod
    def _get_data_from_account_payment_term_lines(term,invoice_payment_terms):
        
        return {
            'balance': term['company_amount'],
            'amount_currency': term['foreign_amount'],
            'l10n_pe_is_detraction_retention': term['l10n_pe_is_detraction_retention'],
            'discount_date': invoice_payment_terms.get('discount_date'),
            'discount_balance': invoice_payment_terms.get('discount_balance') or 0.0,
            'discount_amount_currency': invoice_payment_terms.get('discount_amount_currency') or 0.0,
        }

    @api.depends('invoice_payment_term_id', 'invoice_date', 'currency_id', 'amount_total_in_currency_signed',
                 'invoice_date_due')
    def _compute_needed_terms(self):
        for invoice in self:
            is_draft = invoice.id != invoice._origin.id
            invoice.needed_terms = {}
            invoice.needed_terms_dirty = True
            sign = 1 if invoice.is_inbound(include_receipts=True) else -1
            if invoice.is_invoice(True) and invoice.invoice_line_ids:
                if invoice.invoice_payment_term_id:
                    if is_draft:
                        tax_amount_currency = 0.0
                        untaxed_amount_currency = 0.0
                        for line in invoice.invoice_line_ids:
                            # Usamos compute_all para calcular impuestos en la línea
                            tax_details = line.tax_ids.compute_all(
                                price_unit=line.price_unit,
                                currency=invoice.currency_id,
                                quantity=line.quantity,
                                product=line.product_id,
                                partner=invoice.partner_id
                            )
                            # Sumarizamos el subtotal y el monto de impuestos
                            untaxed_amount_currency += tax_details['total_excluded']
                            tax_amount_currency += tax_details['total_included'] - tax_details['total_excluded']
                        untaxed_amount = untaxed_amount_currency
                        tax_amount = tax_amount_currency
                    else:
                        tax_amount_currency = invoice.amount_tax * sign
                        tax_amount = invoice.amount_tax_signed
                        untaxed_amount_currency = invoice.amount_untaxed * sign
                        untaxed_amount = invoice.amount_untaxed_signed
                    invoice_payment_terms = invoice.invoice_payment_term_id._compute_terms(
                        date_ref=invoice.invoice_date or invoice.date or fields.Date.context_today(invoice),
                        currency=invoice.currency_id,
                        tax_amount_currency=tax_amount_currency,
                        tax_amount=tax_amount,
                        untaxed_amount_currency=untaxed_amount_currency,
                        untaxed_amount=untaxed_amount,
                        company=invoice.company_id,
                        sign=sign,
                        accounting_date_ref=invoice.date
                    )
                    for term in invoice_payment_terms['line_ids']:
                        
                        key = frozendict({
                            'move_id': invoice.id,
                            'date_maturity': fields.Date.to_date(term.get('date')),
                            'discount_date': invoice_payment_terms.get('discount_date'),
                            # Campo que permite evitar la agrupacion por fecha en los terminos de pago cuando calcula
                            'tmp_date_maturity': fields.Date.to_date(term.get('tmp_date_maturity')),
                            'l10n_pe_is_detraction_retention': term.get('l10n_pe_is_detraction_retention'),
                        })
                        values = invoice._get_data_from_account_payment_term_lines(term,invoice_payment_terms)
                        
                        if key not in invoice.needed_terms:
                            invoice.needed_terms[key] = values
                        else:
                            invoice.needed_terms[key]['balance'] += values['balance']
                            invoice.needed_terms[key]['amount_currency'] += values['amount_currency']
                else: 
                    invoice.needed_terms[frozendict({
                        'move_id': invoice.id,
                        'date_maturity': fields.Date.to_date(invoice.invoice_date_due),
                        'discount_date': False,
                        # Campo que permite evitar la agrupacion por fecha en los terminos de pago cuando calcula por defecto
                        'tmp_date_maturity': fields.Date.to_date(invoice.invoice_date_due),
                        'discount_balance': 0.0,
                        'discount_amount_currency': 0.0
                    })] = {
                        'balance': invoice.amount_total_signed,
                        'amount_currency': invoice.amount_total_in_currency_signed,
                    }


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    tmp_date_maturity = fields.Date(string='Parametro temporal para evitar que agrupe lineas de pagos por fecha')
    l10n_pe_is_detraction_retention = fields.Boolean(string='¿Es un descuento?')

    @api.depends('date_maturity', 'tmp_date_maturity')
    def _compute_term_key(self):
        for line in self:
            if line.display_type == 'payment_term':
                line.term_key = frozendict({
                    'move_id': line.move_id.id,
                    'date_maturity': fields.Date.to_date(line.date_maturity),
                    'discount_date': line.discount_date,
                    # Campo que permite evitar la agrupacion por fecha en los terminos de pago cuando se recalcula
                    'tmp_date_maturity': fields.Date.to_date(line.tmp_date_maturity)
                })
            else:
                line.term_key = False
    