from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo import fields

class TestAccountPaymentDetraction(TransactionCase):

    def setUp(self):
        super(TestAccountPaymentDetraction, self).setUp()

        self.partner = self.env['res.partner'].create({
            'name': 'Test Partner',
            'vat': '123456789',
        })
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'l10n_pe_withhold_percentage': 10,
            'l10n_pe_withhold_code': '001',
        })
        self.account_move = self.env['account.move'].create({
            'partner_id': self.partner.id,
            'move_type': 'out_invoice',
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100,
            })]
        })

        self.partner_id = self.env['res.partner'].create({
            'name': 'Test Partner',
            'company_type': 'company',
            'customer_rank': 1,
        })
        self.payment_method = self.env['account.payment.method'].create({
            'name': 'Manual',
            'payment_type': 'outbound',
            'code': 'MANUAL',
        })
        self.journal = self.env['account.journal'].create({
            'name': 'Bank Journal',
            'type': 'bank',
            'code': 'BNK',
        })
        bank_account = self.env['account.account'].search([
            ('account_type', '=', 'asset_cash')
        ], limit=1)

        if not bank_account:
            raise ValueError("No se encontró una cuenta bancaria válida.")

        self.journal.inbound_payment_method_line_ids = [(0, 0, {
            'payment_method_id': self.payment_method.id,
            'payment_account_id': bank_account.id,
        })]

        self.payment = self.env['account.payment'].create({
            'payment_type': 'outbound', 
            'payment_method_id': self.payment_method.id, 
            'amount': 100.0,
            'partner_id': self.partner_id.id,
            'partner_type': 'supplier',
            'journal_id': self.journal.id,
            'reference_invoice': False,
        })
    
        self.payment.action_post()

        self.batch_payment = self.env['account.batch.payment'].create({
            'lot_number': '001',
            'payment_ids': [(4, self.payment.id)],
            'journal_id': self.journal.id,
            'batch_type': 'outbound',
            'payment_method_id': self.payment.payment_method_id.id,  
        })

        print("---<<<SETUP>>>---")

    def test_calculate_detractions(self):
        self.payment.reference_invoice = self.account_move
        self.payment.calculate_detractions()
        expected_amount = round(self.account_move.amount_total * 0.10)  
        self.assertEqual(self.payment.amount, expected_amount, "Detraction amount should be 10 PEN")
        print("---<<<TEST 1>>>---")


    def test_generate_detraction(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100,
            })],
        })
        invoice.action_post()

        payment = self.env['account.payment'].create({
            'partner_id': self.partner.id,
            'amount': 100,
            'payment_type': 'outbound',
            'partner_type': 'customer',
            'journal_id': self.journal.id,
            'payment_method_id': self.env.ref('account.account_payment_method_manual_out').id,
            'currency_id': self.env.ref('base.USD').id,
        })
        payment.action_post()

        receivable_account_type_id = self.env['account.account'].search([('account_type', '=', 'asset')], limit=1).id

        move_line = self.env['account.move.line'].search([
            ('move_id', '=', payment.move_id.id),
            ('account_id.account_type', '=', receivable_account_type_id)
        ], limit=1)
        
        if move_line:
            invoice_line = self.env['account.move.line'].search([
                ('move_id', '=', invoice.id),
                ('account_id.account_type', '=', receivable_account_type_id)
            ], limit=1)
            
            if invoice_line:
                move_line.reconcile([invoice_line.id])

        self.batch_payment.payment_ids = [(6, 0, [payment.id])]
        
        self.batch_payment.generate_detraction()

        if not self.batch_payment.txt_binary:
            print("Contenido del archivo TXT:")
            print(self.batch_payment.txt_binary)

        print("<<<<<<< TEST 2 >>>>>>>>")




