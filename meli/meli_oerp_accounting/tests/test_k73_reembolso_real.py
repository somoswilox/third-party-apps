# -*- coding: utf-8 -*-
"""#718 punto 6 (v2) -- devolucion FEE/SHP por el CAMINO REAL.

Revision del cliente sobre 624389a (4-nov): (1) si un reintegro pasa de parcial a total puede quedar
registrado solo el primer importe; (2) si falla la publicacion del cobro reverso queda en borrador sin
reintento. Los dos eran reales:
  (1) con el FEE-REV ya publicado, el total solo dejaba un warning;
  (2) versions.payment_post traga toda excepcion: el REV quedaba borrador + vinculado, sin aviso, y la
      pasada siguiente lo devolvia tal cual.
LECCION (#707): el banco con datos armados a mano no vio un fallo que aparecio en prod. Aca NADA se escribe
a mano: alta desde el order_json de ML con el JSON de MercadoPago bajado por requests.get (simulado), FEE y
SHP originales creados por confirm_ml, y cada reintegro entra por la re-sincronizacion real
mercadolibre.orders.orders_update_order (meli_oerp_multiple, cuenta enlazada). POST/PUT a ML prohibidos.
Importes de la OP 173823500930 (prod): comision 20.206,41, envio 24.750.

Casos:
  P. aprobado -> reintegro parcial (re-sync) -> reintegro total (re-sync, orden cancelada) -> 3.a re-sync
     => FEE-REV = 20.206,41 y SHP-REV = 24.750 (= original), publicados, sin duplicar.
  F. post del FEE-REV forzado a fallar => borrador + aviso UNA vez en la venta, el SHP-REV se publica igual;
     la re-sync siguiente lo publica.
  X. aprobado -> reintegro total con la orden CANCELADA en UNA re-sync => FEE-REV/SHP-REV publicados en esa
     misma pasada (la cancelacion entra por meli_cancel_with_detail sin config: los REV nacian en borrador).
  C. FEE-REV anulado a mano (18: state 'canceled') => no cuenta como registrado: la re-sync lo vuelve a registrar.
"""
import copy
import logging
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

_logger = logging.getLogger(__name__)

FEE, SHP, TAX = 20206.41, 24750.0, 830.07
TOTAL = 138344.31


class _Resp:
    status_code = 200
    ok = True

    def __init__(self, data):
        self._data = data

    def json(self):
        return copy.deepcopy(self._data)

    def __bool__(self):
        return True


class _Meli:
    access_token = 'TEST'

    def __init__(self, order_json):
        self.oj = order_json

    def get(self, path, params=None, **kwargs):
        oid = str(self.oj['id'])
        if path.startswith('/orders/%s/' % oid):
            return _Resp({})
        if path.startswith('/orders/%s' % oid):
            return _Resp(self.oj)
        if path.startswith('/items/'):
            return _Resp({'id': 'MLA420718', 'attributes': []})
        return _Resp({})

    def post(self, *a, **k):
        raise AssertionError("POST a ML en un test: %s" % (a,))

    put = post

    def need_login(self):
        return False


def _mp_json(pay_id, status, fee_ref=0.0, shp_ref=0.0):
    return {
        'id': pay_id, 'status': status, 'status_detail': 'accredited' if status == 'approved' else status,
        'currency_id': 'ARS', 'transaction_amount': TOTAL, 'shipping_amount': 0, 'taxes_amount': 0,
        'coupon_amount': 0, 'installments': 1, 'payment_method_id': 'account_money',
        'payment_type_id': 'account_money', 'operation_type': 'regular_payment',
        'date_approved': '2026-08-20T10:00:01.000-03:00',
        'transaction_amount_refunded': (TOTAL if status == 'refunded' else 0.0),
        'transaction_details': {'total_paid_amount': TOTAL, 'net_received_amount': TOTAL - FEE - SHP - TAX},
        'fee_details': [],
        'charges_details': [
            {'id': '%s-fee' % pay_id, 'name': 'meli_percentage_fee', 'type': 'fee',
             'accounts': {'from': 'collector', 'to': 'ml'}, 'amounts': {'original': FEE, 'refunded': fee_ref}},
            {'id': '%s-shp' % pay_id, 'name': 'shp_cross_docking', 'type': 'shipping',
             'accounts': {'from': 'collector', 'to': 'ml'}, 'amounts': {'original': SHP, 'refunded': shp_ref}},
            {'id': '%s-tax' % pay_id, 'name': 'tax_withholding-iibb', 'type': 'tax',
             'accounts': {'from': 'collector', 'to': 'mp'}, 'amounts': {'original': TAX, 'refunded': 0}},
        ],
    }


def _order_json(oid, pay_id, order_status, pay_status):
    return {
        'id': oid, 'status': order_status, 'status_detail': None, 'site_id': 'MLA',
        'date_created': '2026-08-20T10:00:00.000-03:00', 'date_closed': '2026-08-20T10:00:01.000-03:00',
        'total_amount': TOTAL, 'paid_amount': TOTAL, 'currency_id': 'ARS',
        'coupon': {'id': None, 'amount': 0},
        'order_items': [{'item': {'id': 'MLA420718', 'title': 'Prueba 718', 'variation_id': None,
                                  'seller_sku': 'SKU420718', 'category_id': 'MLA1'},
                         'quantity': 1, 'unit_price': TOTAL, 'full_unit_price': TOTAL, 'currency_id': 'ARS'}],
        'payments': [{'id': pay_id, 'transaction_amount': TOTAL, 'total_paid_amount': TOTAL,
                      'currency_id': 'ARS', 'status': pay_status, 'coupon_amount': 0, 'shipping_cost': 0,
                      'date_created': '2026-08-20T10:00:01.000-03:00',
                      'date_last_modified': '2026-11-04T10:00:00.000-03:00'}],
        'buyer': {'id': 420718001, 'nickname': 'COMPRADOR718', 'first_name': 'Comprador', 'last_name': 'Prueba',
                  'name': 'Comprador Prueba', 'email': 'c718@example.com',
                  'phone': {'area_code': '11', 'number': '45556666'}},
        'seller': {'id': 420999},
        'tags': ['paid'], 'context': {'channel': 'marketplace', 'site': 'MLA'},
        'shipping': {'id': None}, 'pack_id': None,
    }


@tagged('post_install', '-at_install', 'meli', 'meli_718_real')
class TestMeli718ReembolsoReal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'mercadolibre.account' not in cls.env:
            raise cls.skipException("camino real con cuenta enlazada: requiere meli_oerp_multiple")
        co = cls.company = cls.env.company
        if not cls.env['account.account'].search([('account_type', '=', 'liability_payable')], limit=1):
            raise cls.skipException("sin plan de cuentas en esta base")
        co.meli_refund_revert_charges = True
        cls.env.ref('base.ARS').active = True  # en prod es la moneda de la compania
        pricelist = cls.env['product.pricelist'].search([], limit=1) or \
            cls.env['product.pricelist'].create({'name': 'Lista ML'})
        co.mercadolibre_pricelist = pricelist
        cls.product = cls.env['product.product'].create({
            'name': 'Prueba 718', 'taxes_id': [(5, 0, 0)], 'meli_id': 'MLA420718', 'default_code': 'SKU420718'})
        acc_vals = {'name': 'Mercado Pago 718', 'code': '1718001', 'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in cls.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [co.id])]
        else:
            acc_vals['company_id'] = co.id
        cuenta = cls.env['account.account'].create(acc_vals)
        cls.journal = cls.env['account.journal'].create({
            'name': 'Mercado Pago 718', 'code': 'M718', 'type': 'bank', 'company_id': co.id})
        Method = cls.env['account.payment.method']
        out = Method.search([('code', '=', 'outbound_online'), ('payment_type', '=', 'outbound')], limit=1)
        inb = Method.search([('code', '=', 'inbound_online'), ('payment_type', '=', 'inbound')], limit=1)
        if not out or not inb:
            raise cls.skipException("sin metodos de pago online en esta base")
        cls.journal.outbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'MP out', 'payment_method_id': out.id, 'payment_account_id': cuenta.id})]
        cls.journal.inbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'MP in', 'payment_method_id': inb.id, 'payment_account_id': cuenta.id})]
        cls.ml = cls.env['res.partner'].create({'name': 'MercadoLibre S.R.L. 718'})
        cls.log = cls.env['res.partner'].create({'name': 'Meli Logistica 718'})
        wh = cls.env['stock.warehouse'].search([('company_id', '=', co.id)], limit=1)
        cfg = {
            'name': 'Cliente Odoo Produccion 718', 'mode': 'production', 'company_id': co.id,
            'mercadolibre_pricelist': pricelist.id, 'mercadolibre_buying_mode': 'buy_it_now',
            'mercadolibre_currency': 'ARS', 'mercadolibre_stock_warehouse': wh.id,
            'mercadolibre_stock_warehouse_full': wh.id,
            'mercadolibre_order_confirmation': 'paid_confirm',
            'mercadolibre_process_payments_customer': False,
            'mercadolibre_process_payments_supplier_fea': True,
            'mercadolibre_process_payments_supplier_shipment': True,
            'mercadolibre_process_payments_journal': cls.journal.id,
            'mercadolibre_process_payments_journal_shp': cls.journal.id,
            'mercadolibre_process_payments_res_partner': cls.ml.id,
            'mercadolibre_process_payments_res_partner_shp': cls.log.id,
            'mercadolibre_payment_receipt_validation': 'validate',
            'mercadolibre_cron_get_orders_shipment_client': True,
        }
        Config = cls.env['mercadolibre.configuration']
        cls.config = Config.create({k: v for k, v in cfg.items() if k in Config._fields})
        cls.account = cls.env['mercadolibre.account'].create({
            'name': 'Meli Cliente Produccion 718', 'configuration': cls.config.id,
            'company_id': co.id, 'country_id': cls.env.ref('base.ar').id,
            'meli_login_id': 'cliente718', 'redirect_uri': 'https://cliente.example/meli_login/cliente718'})
        assert cls.config.accounts, "la configuracion no quedo con cuenta"

    # -- camino real -----------------------------------------------------------------------------
    def _sync(self, oid, pay_id, order_status, pay_status, fee_ref=0.0, shp_ref=0.0, first=False):
        oj = _order_json(oid, pay_id, order_status, pay_status)
        mp = _mp_json(pay_id, pay_status, fee_ref, shp_ref)
        seen = []

        def _get(url, *a, **k):
            seen.append(url)
            if 'api.mercadopago.com/v1/payments/%s' % pay_id in url:
                return _Resp(mp)
            raise requests.exceptions.ConnectionError('sin red: %s' % url)

        meli = _Meli(oj)
        with patch('odoo.addons.meli_oerp.models.orders.requests.get', side_effect=_get), \
                patch('requests.post', side_effect=AssertionError('POST de red en un test')), \
                patch('requests.put', side_effect=AssertionError('PUT de red en un test')):
            if first:
                res = self.env['mercadolibre.orders'].orders_update_order_json(
                    {'id': False, 'order_json': oj}, meli=meli, config=self.config)
                self.assertFalse(isinstance(res, dict) and res.get('error'), res)
            else:
                mo = self.env['mercadolibre.orders'].search([('order_id', '=', str(oid))], limit=1)
                mo.orders_update_order(meli=meli, config=self.config)
        self.assertTrue(seen, "no se consulto MercadoPago: el caso no recorre el camino real")
        so = self.env['sale.order'].search([('meli_order_id', '=', str(oid))], limit=1)
        self.assertTrue(so, "no se creo la venta %s" % oid)
        so.invalidate_recordset()
        pay = self.env['mercadolibre.payments'].search([('payment_id', '=', str(pay_id))], limit=1)
        self.assertTrue(pay, "no se creo el pago ML %s" % pay_id)
        pay.invalidate_recordset()
        return so, pay

    def _alta(self, oid, pay_id):
        so, pay = self._sync(oid, pay_id, 'paid', 'approved', first=True)
        self.assertTrue(pay.account_supplier_payment_id, "confirm_ml no creo el FEE original")
        self.assertTrue(pay.account_supplier_payment_shipment_id, "confirm_ml no creo el SHP original")
        self.assertAlmostEqual(pay.account_supplier_payment_id.amount, FEE, places=2)
        self.assertAlmostEqual(pay.account_supplier_payment_shipment_id.amount, SHP, places=2)
        return so, pay

    _DEAD = ('cancel', 'cancelled', 'canceled', 'rejected')

    def _revs(self, pay, kind):
        P = self.env['account.payment']
        ref = next(f for f in ('memo', 'ref') if f in P._fields)
        return P.search([('meli_payment_id', '=', pay.id), ('payment_type', '=', 'inbound'),
                         (ref, 'like', '%s-REV' % kind), ('state', 'not in', list(self._DEAD))])

    def _posted(self, revs):
        return all(r.state not in ('draft',) + self._DEAD for r in revs)

    # -- P ---------------------------------------------------------------------------------------
    def test_P_parcial_luego_total(self):
        oid, pid = 2000017382350001, 173823500931
        so, pay = self._alta(oid, pid)
        self.assertFalse(self._revs(pay, 'FEE') | self._revs(pay, 'SHP'), "aprobado: no hay devolucion")
        # reintegro PARCIAL: ML devuelve media comision, el envio no
        so, pay = self._sync(oid, pid, 'paid', 'partially_refunded', fee_ref=10103.20)
        fee = self._revs(pay, 'FEE')
        self.assertAlmostEqual(sum(fee.mapped('amount')), 10103.20, places=2)
        self.assertTrue(self._posted(fee), "el FEE-REV parcial no se publico")
        self.assertFalse(self._revs(pay, 'SHP'))
        # reintegro TOTAL, orden cancelada
        so, pay = self._sync(oid, pid, 'cancelled', 'refunded', fee_ref=FEE, shp_ref=SHP)
        fee, shp = self._revs(pay, 'FEE'), self._revs(pay, 'SHP')
        self.assertAlmostEqual(sum(fee.mapped('amount')), FEE, places=2,
                               msg="parcial->total: quedo registrado %.2f de %.2f" % (sum(fee.mapped('amount')), FEE))
        self.assertAlmostEqual(sum(shp.mapped('amount')), SHP, places=2)
        self.assertTrue(self._posted(fee | shp), [(r.id, r.state) for r in fee | shp])
        self.assertLessEqual(sum(fee.mapped('amount')), pay.account_supplier_payment_id.amount + 0.001)
        # tercera pasada: nada nuevo
        n = len(fee | shp)
        so, pay = self._sync(oid, pid, 'cancelled', 'refunded', fee_ref=FEE, shp_ref=SHP)
        self.assertEqual(len(self._revs(pay, 'FEE') | self._revs(pay, 'SHP')), n, "re-sync duplico la devolucion")
        self.assertAlmostEqual(sum(self._revs(pay, 'FEE').mapped('amount')), FEE, places=2)
        self.assertNotIn(pay.account_supplier_payment_id.state, ('draft',) + self._DEAD, "el FEE original no se toca")

    # -- F ---------------------------------------------------------------------------------------
    def test_F_fallo_de_publicacion_se_reintenta(self):
        oid, pid = 2000017382350002, 173823500932
        so, pay = self._alta(oid, pid)
        Pay = type(self.env['account.payment'])
        orig = Pay.action_post
        ref = next(f for f in ('memo', 'ref') if f in Pay._fields)

        def _boom(this):
            if any(p.payment_type == 'inbound' and 'FEE-REV' in (p[ref] or '') for p in this):
                raise UserError("falla forzada al publicar FEE-REV")
            return orig(this)

        with patch.object(Pay, 'action_post', _boom):
            so, pay = self._sync(oid, pid, 'cancelled', 'refunded', fee_ref=FEE, shp_ref=SHP)
        fee, shp = self._revs(pay, 'FEE'), self._revs(pay, 'SHP')
        self.assertEqual(len(fee), 1)
        self.assertEqual(fee.state, 'draft', "con el post fallando el FEE-REV queda en borrador")
        self.assertTrue(shp and self._posted(shp), "un fallo del FEE-REV no frena el SHP-REV")
        avisos = so.message_ids.filtered(lambda m: 'meli-718-rev-sin-publicar' in (m.body or ''))
        self.assertEqual(len(avisos), 1, "el borrador tiene que quedar avisado en la venta, una vez")
        # pasada siguiente sin falla: se reintenta y publica, sin crear otro
        so, pay = self._sync(oid, pid, 'cancelled', 'refunded', fee_ref=FEE, shp_ref=SHP)
        fee = self._revs(pay, 'FEE')
        self.assertEqual(len(fee), 1, "el reintento no debe crear otro FEE-REV")
        self.assertTrue(self._posted(fee), "el FEE-REV en borrador no se reintento: %s" % fee.state)
        self.assertAlmostEqual(fee.amount, FEE, places=2)

    # -- C ---------------------------------------------------------------------------------------
    def test_C_rev_anulado_a_mano_no_cuenta(self):
        oid, pid = 2000017382350003, 173823500933
        so, pay = self._alta(oid, pid)
        so, pay = self._sync(oid, pid, 'cancelled', 'refunded', fee_ref=FEE, shp_ref=SHP)
        fee = self._revs(pay, 'FEE')
        self.assertEqual(len(fee), 1)
        fee.action_draft()
        fee.action_cancel()
        self.assertIn(fee.state, self._DEAD)
        so, pay = self._sync(oid, pid, 'cancelled', 'refunded', fee_ref=FEE, shp_ref=SHP)
        again = self._revs(pay, 'FEE')
        self.assertEqual(len(again), 1, "anulado a mano: se vuelve a registrar una sola vez")
        self.assertNotEqual(again, fee)
        self.assertAlmostEqual(again.amount, FEE, places=2)
        self.assertEqual(pay.account_supplier_payment_rev_id, again, "el link tiene que apuntar al vigente")

    # -- X ---------------------------------------------------------------------------------------
    def test_X_orden_cancelada_publica_en_la_misma_pasada(self):
        oid, pid = 2000017382350004, 173823500934
        so, pay = self._alta(oid, pid)
        so, pay = self._sync(oid, pid, 'cancelled', 'refunded', fee_ref=FEE, shp_ref=SHP)
        revs = self._revs(pay, 'FEE') | self._revs(pay, 'SHP')
        self.assertEqual(len(revs), 2)
        self.assertTrue(self._posted(revs), [(r.id, r.state) for r in revs])
        self.assertAlmostEqual(sum(self._revs(pay, 'FEE').mapped('amount')), FEE, places=2)
        self.assertAlmostEqual(sum(self._revs(pay, 'SHP').mapped('amount')), SHP, places=2)
