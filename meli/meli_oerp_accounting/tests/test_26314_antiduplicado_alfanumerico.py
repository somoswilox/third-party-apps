# -*- coding: utf-8 -*-
"""Brasil D (26.314): anti-duplicado de pagos ML con payment_id ALFANUMERICO.

payments.py create_payment y order.py _cleanup_duplicate_customer_payments ordenaban los pagos por
int(payment_id) dentro de un try: con un ID alfanumerico (Mercado Livre Brasil) el anti-duplicado se
apagaba en silencio y se registraban los DOS pagos. Ahora: todos numericos => mismo criterio de
siempre (int); alguno alfanumerico => date_created, desempate por el ID como texto.

(a) IDs numericos: mismo resultado que origin (incluye el caso ML 2000962033503295 de #caso-K15 y fechas
    a proposito invertidas: con IDs numericos manda el ID, no la fecha).
(b) IDs alfanumericos: el duplicado se detecta (create_payment crea uno solo, el mas reciente por
    fecha) y la limpieza cancela el mas viejo. Control contra origin: (b) falla, (a) pasa.
"""
from unittest.mock import patch

from odoo import fields, release
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18
OLD = '2026-10-20 10:00:00'
NEW = '2026-10-20 11:00:00'


@tagged('post_install', '-at_install', 'meli', 'meli_26314')
class TestAntiDuplicadoAlfanumerico26314(TransactionCase):

    def _crear_minimo(self, model, extra=None, _visitados=None):
        _visitados = _visitados or set()
        Model = self.env[model]
        vals = {}
        for name, f in Model._fields.items():
            if not f.required or f.compute or f.related or f.readonly:
                continue
            if f.type in ('char', 'text', 'html'):
                vals[name] = 'TEST'
            elif f.type == 'integer':
                vals[name] = 1
            elif f.type in ('float', 'monetary'):
                vals[name] = 1.0
            elif f.type == 'boolean':
                vals[name] = False
            elif f.type == 'date':
                vals[name] = fields.Date.today()
            elif f.type == 'datetime':
                vals[name] = fields.Datetime.now()
            elif f.type == 'selection':
                sel = f.selection(Model) if callable(f.selection) else f.selection
                vals[name] = sel[0][0] if sel else False
            elif f.type == 'many2one':
                rec = self.env[f.comodel_name].search([], limit=1)
                if not rec and f.comodel_name not in _visitados:
                    _visitados.add(f.comodel_name)
                    rec = self._crear_minimo(f.comodel_name, None, _visitados)
                vals[name] = rec.id if rec else False
        vals.update(extra or {})
        return Model.create(vals)

    def setUp(self):
        super().setUp()
        self.co = self.env.company
        if not self.env['account.account'].search([('account_type', '=', 'asset_receivable')], limit=1):
            self.skipTest("sin plan de cuentas en esta base")
        acc_vals = {'name': 'Cobros ML pendientes K15', 'code': '1526001',
                    'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in self.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            acc_vals['company_id'] = self.co.id
        cuenta = self.env['account.account'].create(acc_vals)
        manual = self.env.ref('account.account_payment_method_manual_in')
        self.journal = self.env['account.journal'].create({
            'name': 'MercadoPago K15', 'code': 'MK15', 'type': 'bank', 'company_id': self.co.id})
        self.journal.inbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'Pago manual', 'payment_method_id': manual.id, 'payment_account_id': cuenta.id})]
        self.co.mercadolibre_process_payments_journal = self.journal
        for f, v in (('mercadolibre_payment_receipt_validation', 'validate'),
                     ('mercadolibre_notification_mode', 'internal_note'),
                     ('mercadolibre_order_total_config', 'paid_amount'),
                     ('mercadolibre_including_shipping_cost', 'always'),
                     ('mercadolibre_rounding_tolerance', 1.0),
                     ('mercadolibre_round_to_integer', False)):
            if f in self.co._fields:
                self.co[f] = v
        self.partner = self.env['res.partner'].create({'name': 'Comprador ML K15'})
        self.product = self.env['product.product'].create({
            'name': 'Cortina K15', 'type': 'service', 'taxes_id': [(5, 0, 0)]})
        self.tax_field = 'tax_ids' if 'tax_ids' in self.env['sale.order.line']._fields else 'tax_id'
        self.n = 0
        if V18:
            Move = type(self.env['account.move'])
            p = patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'in_payment', create=False)
            p.start()
            self.addCleanup(p.stop)

    def _venta(self, precios, coupon=0.0, pagos=()):
        """precios = lineas de la venta (sin impuestos); pagos = dicts de mercadolibre.payments."""
        self.n += 1
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1.0,
                                   'price_unit': p, self.tax_field: [(5, 0, 0)]}) for p in precios],
        })
        if 'meli_coupon_amount' in so._fields:
            so.meli_coupon_amount = coupon
        ml_id = '20004006633262%02d' % self.n
        try:
            mo = self._crear_minimo('mercadolibre.orders', {
                'order_id': ml_id, 'name': ml_id, 'sale_order': so.id,
                'paid_amount': sum(p['transaction_amount'] for p in pagos)})
            mps = self.env['mercadolibre.payments']
            for i, vals in enumerate(pagos):
                v = {'order_id': mo.id, 'payment_id': vals.get('pid', '5260%02d%02d' % (self.n, i)),
                     'status': 'approved', 'currency_id': self.co.currency_id.name}
                v.update({k: x for k, x in vals.items() if k != 'pid' and k in mps._fields})
                mps |= self._crear_minimo('mercadolibre.payments', v)
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        return so, mps

    def _cobrar(self, mps):
        for mp in mps:
            mp.create_payment(config=self.co)
        return mps.mapped('account_payment_id')

    # ------------------------------------------------------------ (a) numericos
    def test_a1_clave_numerica_es_el_int_de_siempre(self):
        so, mps = self._venta([100.0], pagos=(
            {'pid': '1000000002', 'transaction_amount': 100.0, 'date_created': OLD},
            {'pid': '1000000001', 'transaction_amount': 100.0, 'date_created': NEW},
        ))
        key = self.env['mercadolibre.payments']._meli_payment_recency_key(mps)
        self.assertEqual([key(p) for p in mps], [1000000002, 1000000001])

    def test_a2_numerico_duplicado_conserva_el_mayor_id_aunque_sea_mas_viejo(self):
        so, mps = self._venta([100.0], pagos=(
            {'pid': '1000000001', 'transaction_amount': 100.0, 'total_paid_amount': 100.0, 'date_created': NEW},
            {'pid': '1000000002', 'transaction_amount': 100.0, 'total_paid_amount': 100.0, 'date_created': OLD},
        ))
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 1)
        self.assertTrue(mps.filtered(lambda p: p.payment_id == '1000000002').account_payment_id)
        self.assertFalse(mps.filtered(lambda p: p.payment_id == '1000000001').account_payment_id)

    def test_a3_caso_K15_dos_adiciones_que_ml_cuenta(self):
        # ML 2000962033503295: 77.675 + 8.000 + 8.000 = 93.675 (no es duplicado)
        so, mps = self._venta([77675.0, 16000.0], pagos=(
            {'pid': '180818701979', 'transaction_amount': 77675.0, 'total_paid_amount': 77675.0},
            {'pid': '182481184994', 'transaction_amount': 8000.0, 'total_paid_amount': 8000.0},
            {'pid': '181598918485', 'transaction_amount': 8000.0, 'total_paid_amount': 8000.0},
        ))
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 3)
        self.assertAlmostEqual(sum(pays.mapped('amount')), 93675.0, places=2)

    # --------------------------------------------------------- (b) alfanumericos
    def test_b1_alfanumerico_duplicado_se_detecta(self):
        # el ID "mas grande" como texto es el mas VIEJO: manda la fecha
        so, mps = self._venta([100.0], pagos=(
            {'pid': 'MLBzz-0001', 'transaction_amount': 100.0, 'total_paid_amount': 100.0, 'date_created': OLD},
            {'pid': 'MLBaa-0002', 'transaction_amount': 100.0, 'total_paid_amount': 100.0, 'date_created': NEW},
        ))
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 1, "dos pagos alfanumericos iguales que la venta no espera: uno solo")
        self.assertTrue(mps.filtered(lambda p: p.payment_id == 'MLBaa-0002').account_payment_id)

    def test_b2_alfanumerico_pagos_parciales_distintos_se_crean_los_dos(self):
        so, mps = self._venta([150.0], pagos=(
            {'pid': 'MLBpay-A', 'transaction_amount': 100.0, 'total_paid_amount': 100.0, 'date_created': OLD},
            {'pid': 'MLBpay-B', 'transaction_amount': 50.0, 'total_paid_amount': 50.0, 'date_created': NEW},
        ))
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 2)

    def _cleanup(self, pagos):
        so, mps = self._venta([100.0], pagos=pagos)
        for mp in mps:
            mp.account_payment_id = self.env['account.payment'].create({
                'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': self.partner.id,
                'amount': 100.0, 'journal_id': self.journal.id})
        cancelados = []
        Pay = type(self.env['mercadolibre.payments'])
        with patch.object(Pay, 'cancel_payments', lambda rec, config=None: cancelados.append(rec.payment_id), create=False):
            so._cleanup_duplicate_customer_payments(mps[:1].order_id, config=self.co)
        return cancelados

    def test_b3_limpieza_alfanumerica_cancela_el_mas_viejo(self):
        cancelados = self._cleanup((
            {'pid': 'MLBzz-0001', 'transaction_amount': 100.0, 'date_created': OLD},
            {'pid': 'MLBaa-0002', 'transaction_amount': 100.0, 'date_created': NEW},
        ))
        self.assertEqual(cancelados, ['MLBzz-0001'])

    def test_a4_limpieza_numerica_igual_que_siempre(self):
        cancelados = self._cleanup((
            {'pid': '1000000001', 'transaction_amount': 100.0, 'date_created': NEW},
            {'pid': '1000000002', 'transaction_amount': 100.0, 'date_created': OLD},
        ))
        self.assertEqual(cancelados, ['1000000001'])
