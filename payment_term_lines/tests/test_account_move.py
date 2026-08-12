from odoo.tests.common import TransactionCase
from odoo import fields
from datetime import date
from dateutil.relativedelta import relativedelta

class TestAccountPaymentTerm(TransactionCase):

    def setUp(self):
        super(TestAccountPaymentTerm, self).setUp()
        self.payment_term = self.env['account.payment.term'].create({
            'name': 'Test Payment Term',
            'line_ids': [
                # Línea de tipo percent con el 100% para cumplir con la validación
                (0, 0, {'value': 'percent', 'value_amount': 100.0, 'nb_days': 0, 'l10n_pe_is_detraction_retention': True}),
            ]
        })
        self.company = self.env.user.company_id
        self.currency = self.company.currency_id
        print("<<<< SET UP >>>>")

    def test_compute_terms(self):
        # Define valores de prueba
        date_ref = date.today()
        sign = 1
        tax_amount = 100
        tax_amount_currency = 100
        untaxed_amount = 400
        untaxed_amount_currency = 400

        terms = self.payment_term._compute_terms(
            date_ref=date_ref,
            currency=self.currency,
            company=self.company,
            tax_amount=tax_amount,
            tax_amount_currency=tax_amount_currency,
            sign=sign,
            untaxed_amount=untaxed_amount,
            untaxed_amount_currency=untaxed_amount_currency
        )

        self.assertIn('line_ids', terms, "No se encuentran las líneas de términos.")
        self.assertEqual(len(terms['line_ids']), len(self.payment_term.line_ids), "El número de líneas de términos no coincide.")
        
        self.assertEqual(terms['line_ids'][0]['tmp_date_maturity'], date_ref + relativedelta(days=-1), "El campo tmp_date_maturity no coincide para el primer término de saldo.")
        print("<<<< TEST COMPUTE TERMS >>>>")

    def test_get_amount_by_date(self):
        term_data = {
            'line_ids': [
                {'date': date.today(), 'tmp_date_maturity': date.today() + relativedelta(days=-1), 'foreign_amount': 150.0},
                {'date': date.today() + relativedelta(days=30), 'tmp_date_maturity': date.today() + relativedelta(days=29), 'foreign_amount': 250.0},
            ]
        }
        
        amount_by_date = self.payment_term._get_amount_by_date(term_data)

        self.assertEqual(len(amount_by_date), len(term_data['line_ids']), "Las líneas de cantidad por fecha no están divididas correctamente.")
        for key, value in amount_by_date.items():
            self.assertIn('tmp_date_maturity', value, "El campo tmp_date_maturity debería estar en el diccionario.")
            self.assertGreater(value['amount'], 0.0, "El monto debería ser mayor a cero.")
        print("<<<< TEST GET AMOUNT BY DATE >>>>")

    def test_account_move_line(self):
        move = self.env['account.move'].create({
            'name': 'Test Move',
            'move_type': 'out_invoice',
            'journal_id': self.env['account.journal'].search([('type', '=', 'sale')], limit=1).id,
            'date': fields.Date.today(),
        })

        move_line = self.env['account.move.line'].create({
            'move_id': move.id,
            'date_maturity': fields.Date.today(),
            'tmp_date_maturity': fields.Date.today() + relativedelta(days=-1),
            'display_type': 'payment_term',
        })

        move_line._compute_term_key()
        self.assertTrue(move_line.term_key, "El campo term_key debería generarse correctamente.")
        self.assertEqual(move_line.term_key['tmp_date_maturity'], move_line.tmp_date_maturity, "tmp_date_maturity no coincide en term_key.")
        print("TEST ACCOUNT MOVE LINE >>>>")
