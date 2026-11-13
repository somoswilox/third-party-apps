# -*- coding: utf-8 -*-
"""26.229 -- dedupe de notificaciones y pestaña 'Ventas incompletas'.

Montos de casos reales de produccion. Sin red: ML se simula.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_binder_wizard import TestBinderWizard


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli:
    access_token = 'TEST'

    def __init__(self, data=None, exc=None):
        self.data, self.exc, self.calls = data, exc, []

    def get(self, path, params=None):
        self.calls.append(path)
        if self.exc:
            raise self.exc
        return _Resp(self.data)


@tagged('post_install', '-at_install', 'meli', 'meli_26229')
class TestVentasMLDedupeIncompletas(TransactionCase):

    _crear_minimo = TestBinderWizard._crear_minimo
    _cuenta = TestBinderWizard._cuenta

    def _sale(self, price, paid):
        partner = self.env['res.partner'].create({'name': 'comprador'})
        product = self.env['product.product'].create({'name': 'ref', 'taxes_id': [(5, 0, 0)]})
        tax_field = 'tax_ids' if 'tax_ids' in self.env['sale.order.line']._fields else 'tax_id'
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1, 'price_unit': price,
                                   tax_field: [(5, 0, 0)]})],
        })
        so.write({'meli_paid_amount': paid, 'meli_total_amount': price, 'meli_status': 'paid'})
        return so

    # ------------------------------------------- 2. dedupe vs cambio de estado
    def _noti_and_order(self, ml_status_saved='paid', so_meli_status='paid'):
        so = self._sale(100.0, 100.0)
        so.meli_status = so_meli_status
        mo = self.env['mercadolibre.orders'].create({'order_id': '2000461625671435', 'name': 'x',
                                                      'status': ml_status_saved, 'sale_order': so.id})
        noti = self.env['mercadolibre.notification'].create({'resource': '/orders/2000461625671435', 'notification_id': 'T-NOTI',
                                                             'topic': 'orders_v2'})
        return noti, mo, so

    def test_2_cancel_after_recent_success_is_processed(self):
        noti, mo, so = self._noti_and_order('paid')
        meli = _FakeMeli({'id': 2000461625671435, 'status': 'cancelled'})
        self.assertTrue(noti._meli_dedupe_state_changed(meli=meli))
        self.assertEqual(meli.calls, ['/orders/2000461625671435'])

    def test_2_same_status_is_still_skipped(self):
        noti, mo, so = self._noti_and_order('paid')
        self.assertFalse(noti._meli_dedupe_state_changed(meli=_FakeMeli({'id': 2000461625671435, 'status': 'paid'})))

    def test_2_order_cancelled_but_sale_not(self):
        noti, mo, so = self._noti_and_order('cancelled', so_meli_status='paid')
        self.assertTrue(noti._meli_dedupe_state_changed(meli=_FakeMeli({'id': 2000461625671435, 'status': 'cancelled'})))

    def test_2_api_error_keeps_old_behaviour(self):
        noti, mo, so = self._noti_and_order('paid')
        self.assertFalse(noti._meli_dedupe_state_changed(meli=_FakeMeli(exc=Exception('timeout'))))
        self.assertFalse(noti._meli_dedupe_state_changed(meli=_FakeMeli({'error': 'not_found', 'status': 404})))

    # ------------------------------------------- 5. ventas incompletas
    def test_5_confirmed_sales_not_listed(self):
        account = self._cuenta()
        now = fields.Datetime.now()
        # las dos NO cuadran (237 pagado contra 152, sin envio registrado en ningun lado)
        so_draft = self._sale(152.0, 237.0)
        so_conf = self._sale(152.0, 237.0)
        so_conf.action_confirm()
        self.assertEqual(so_conf.state, 'sale')
        for oid, so in (('T-DRAFT', so_draft), ('2000733445471610', so_conf)):
            mo = self.env['mercadolibre.orders'].create({
                'order_id': oid, 'name': oid, 'status': 'paid', 'sale_order': so.id,
                'connection_account': account.id, 'date_closed': now,
            })
            so.meli_orders = [(4, mo.id)]
        wiz = self.env['mercadolibre.orders.import'].create({
            'order_date_from': fields.Datetime.subtract(now, days=1),
            'order_date_to': fields.Datetime.add(now, days=1),
        })
        wiz._scan_incomplete_sales(target=wiz, context={'active_ids': [account.id]})
        listed = set(wiz.import_lines.mapped('order_id'))
        self.assertIn('T-DRAFT', listed)
        self.assertNotIn('2000733445471610', listed)
