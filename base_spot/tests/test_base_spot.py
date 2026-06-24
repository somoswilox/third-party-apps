from odoo.tests import tagged
from odoo.tests.common import TransactionCase
import time

@tagged('-at_install', 'post_install')
class TestBaseSpot(TransactionCase):

    def test_set_base_spot(self):
        account_move_model = self.env['account.move']
        account_spot_detraction = self.env['account.spot.detraction'].search([])
        account_spot_retention = self.env['account.spot.retention']
        currency_id = self.env['res.currency'].search([])[0].id
        journal_id = self.env['account.journal'].search([])[0].id
        partners = self.env['res.partner'].search([])
        account_spot_retention_unit1 = account_spot_retention.create({
            'name': 'Retention 1',
        })
        account_spot_retention_unit2 = account_spot_retention.create({
            'name': 'Retention 2',
        })
        account_move_unit1 = account_move_model.create({
            'partner_id': partners[0].id,
            'currency_id': currency_id,
            'auto_post': 'no',
            'invoice_date': '2024-02-01',
            'extract_state': 'no_extract_requested',
            'move_type': 'in_invoice',
            'invoice_line_ids': [
                (0, 0, {'name': 'test', 'price_unit': 200})
            ],
        })
        account_move_unit2 = account_move_model.create({
            'partner_id': partners[0].id,
            'currency_id': currency_id,
            'auto_post': 'no',
            'date': '2024-02-01',
            'extract_state': 'no_extract_requested',
            'move_type': 'in_refund',
            'invoice_line_ids': [
                (0, 0, {'name': 'test', 'price_unit': 200})
            ],
        })
        account_move_unit1.write({
            'detraction_id': account_spot_detraction[0].id,
            'retention_id': account_spot_retention_unit1.id,
            'voucher_payment_date': '2024-02-01',
            'voucher_number': '1234567890',
            'operation_type_detraction': '01',
        })
        account_move_unit2.write({
            'detraction_id': account_spot_detraction[1].id,
            'retention_id': account_spot_retention_unit2.id,
            'voucher_payment_date': '2024-02-01',
            'voucher_number': '0987654321',
            'operation_type_detraction': '02',
        })

        vals = account_move_model.search([('move_type', 'in', ['in_invoice', 'in_refund'])])
        self.assertEqual(2, len(vals))
        self.assertEqual(account_move_unit1, vals[1])
        self.assertEqual(account_move_unit2, vals[0])
        vals = account_move_model.search([('detraction_id', 'in', [account_spot_detraction[0].id, account_spot_detraction[1].id])])
        self.assertEqual(2, len(vals))
        self.assertEqual(account_move_unit1, vals[1])
        self.assertEqual(account_move_unit2, vals[0])

        self.assertEqual(36, len(account_spot_detraction))

        account_spot_detraction.create({'name': 'producto prueba 1', 'code': '041', 'rate': 11.0,})
        account_spot_detraction.create({'name': 'producto prueba 2', 'code': '042', 'rate': 12.0,})
        account_spot_detraction.create({'name': 'producto prueba 3', 'code': '043', 'rate': 13.0,})
        vals = account_spot_detraction.search([])

        self.assertEqual(39, len(vals))
        self.assertEqual(vals[36].name, 'producto prueba 1')
        self.assertEqual(11.0, vals[36].rate)
        self.assertEqual(vals[37].name, 'producto prueba 2')
        self.assertEqual(12.0, vals[37].rate)
        self.assertEqual(vals[38].name, 'producto prueba 3')
        self.assertEqual(13.0, vals[38].rate)

        print('-------------TEST BASE_SPOT OK-------------')