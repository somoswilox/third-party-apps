from odoo import fields
from odoo.tests.common import TransactionCase
from datetime import datetime
from odoo.tools import float_compare


class TestPaymentTermExtension(TransactionCase):
    def setUp(self):
        super(TestPaymentTermExtension, self).setUp()
        
        self.partner= self.env['res.partner'].search([])
        self.journal= self.env['account.journal'].search([])
        self.currency= self.env['res.currency'].search([])
        
        self.product= self.env['product.product'].search([])
        self.account= self.env['account.account'].search([])
        self.payment_term = self.env['account.payment.term'].create({
            'name': 'Detraccion Payment Term',
            'example_date':fields.Date.today(),
            'line_ids': [
                (0, 0, {'value':'percent','value_amount':'12','nb_days':'0'}),
                (0, 0, {'value':'percent','value_amount':'88','nb_days':'30'})
            ]
        })
         
    def test_default_line_ids(self):
       
        self.assertEqual(self.payment_term.line_ids[0].value, 'percent')
        self.assertEqual(self.payment_term.line_ids[0].value_amount, 12)
        self.assertEqual(self.payment_term.line_ids[0].nb_days, 0)
        self.assertEqual(self.payment_term.example_date, fields.Date.today())
    
    def test_create_account_move(self):
        account_move = self.env['account.move'].create({
            'partner_id': self.partner[0].id,
            'partner_shipping_id': self.partner[0].id,
            'invoice_payment_term_id': self.payment_term.id,
            'journal_id': self.journal[0].id,
            'currency_id': self.currency[0].id,
            'line_ids': [
                (0, 0, {
                    'product_id': self.product[0].id,
                    'account_id': self.account[0].id,
                    'quantity': 5,
                    'price_unit': 12.50,
                })
            ],
        })

        self.assertEqual(account_move.partner_id, self.partner[0])
        self.assertEqual(account_move.partner_shipping_id, self.partner[0])
        self.assertEqual(account_move.invoice_payment_term_id, self.payment_term)
        self.assertEqual(account_move.journal_id, self.journal[0])
        self.assertEqual(account_move.currency_id, self.currency[0])
        self.assertEqual(account_move.line_ids.product_id, self.product[0])
        self.assertEqual(account_move.line_ids.account_id, self.account[0])
        self.assertEqual(account_move.line_ids.quantity, 5)
        self.assertEqual(account_move.line_ids.price_unit, 12.50)

    
     