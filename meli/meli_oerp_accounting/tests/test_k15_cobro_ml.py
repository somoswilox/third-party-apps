# -*- coding: utf-8 -*-
"""26.305 (#caso-K15 cliente E, 25-oct-2026): monto del cobro de cada pago ML relativo a la venta.

Casos con los montos reales de produccion (sin red):
  A. cupon financiado por ML + segundo pago (payment_addition del envio): la venta/factura va por
     lo cobrado en ML (transaction_amount, con cupon). Antes: 227.200 + 6.000 = 233.200 contra
     258.200 => factura con saldo = cupon (25.000) y el cobro se deshacia.
  B. dos payment_addition del MISMO monto que ML cuenta a los dos: antes el anti-duplicado
     descartaba uno (77.675 + 8.000 contra 93.675 => saldo 8.000).
  C. pago unico muy distinto de la venta (precio pisado a $1,21 contra $171.925 cobrados): antes
     se "cobraba" $1,21 y la factura quedaba pagada escondiendo el error. Ahora se registra lo
     cobrado y queda el aviso en la venta.
  Regresion (iguales antes y despues): pago unico con cupon (56.520), redondeo (<= tolerancia),
  duplicado REAL (dos pagos iguales que la venta no espera: se crea uno solo).

Control: corrido contra origin (sin el fix) A, B y C fallan.
"""
from unittest.mock import patch

from odoo import fields, release
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18


@tagged('post_install', '-at_install', 'meli_K15_cobro')
class TestCobroMLK15(TransactionCase):

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

    # ---------------------------------------------------------------- A
    def test_A_multi_pago_cupon_financiado_por_ml(self):
        so, mps = self._venta([252200.0, 6000.0], coupon=25000.0, pagos=(
            {'pid': '182983040227', 'transaction_amount': 252200.0, 'total_paid_amount': 227200.0, 'coupon_amount': 25000.0},
            {'pid': '182983825807', 'transaction_amount': 6000.0, 'total_paid_amount': 6000.0},
        ))
        self.assertAlmostEqual(so.amount_total, 258200.0, places=2)
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 2)
        self.assertAlmostEqual(sum(pays.mapped('amount')), 258200.0, places=2,
                               msg="los cobros tienen que sumar la venta (antes 233.200: saldo = cupon)")

    # ---------------------------------------------------------------- B
    def test_B_dos_adiciones_mismo_monto_no_son_duplicado(self):
        so, mps = self._venta([77675.0, 16000.0], pagos=(
            {'pid': '180818701979', 'transaction_amount': 77675.0, 'total_paid_amount': 77675.0},
            {'pid': '182481184994', 'transaction_amount': 8000.0, 'total_paid_amount': 8000.0},
            {'pid': '181598918485', 'transaction_amount': 8000.0, 'total_paid_amount': 8000.0},
        ))
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 3, "ML cuenta los dos 8.000: no es un duplicado")
        self.assertAlmostEqual(sum(pays.mapped('amount')), 93675.0, places=2)

    # ---------------------------------------------------------------- C
    def test_C_pago_unico_no_se_fuerza_a_una_venta_mal_cotizada(self):
        so, mps = self._venta([1.21], pagos=(
            {'pid': '180827887318', 'transaction_amount': 171925.0, 'total_paid_amount': 171925.0},))
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 1)
        self.assertAlmostEqual(pays.amount, 171925.0, places=2,
                               msg="se registra lo cobrado en ML, no el total de la venta ($1,21)")
        body = " || ".join(str(m.body) for m in so.message_ids if m.body)
        self.assertIn('no coincide con el total de la venta', body)

    # ------------------------------------------------------- regresion
    def test_R1_pago_unico_con_cupon_igual_que_antes(self):
        so, mps = self._venta([56520.0], coupon=9000.0, pagos=(
            {'transaction_amount': 56520.0, 'total_paid_amount': 47520.0, 'coupon_amount': 9000.0},))
        pays = self._cobrar(mps)
        self.assertAlmostEqual(pays.amount, 56520.0, places=2)

    def test_R2_pago_unico_cupon_descontado_en_la_venta(self):
        # modo viejo (product_discount): la venta = total - cupon = lo que puso el comprador
        so, mps = self._venta([47520.0], coupon=9000.0, pagos=(
            {'transaction_amount': 56520.0, 'total_paid_amount': 47520.0, 'coupon_amount': 9000.0},))
        pays = self._cobrar(mps)
        self.assertAlmostEqual(pays.amount, 47520.0, places=2)

    def test_R3_redondeo_se_ajusta(self):
        so, mps = self._venta([100.4], pagos=({'transaction_amount': 100.0, 'total_paid_amount': 100.0},))
        pays = self._cobrar(mps)
        self.assertAlmostEqual(pays.amount, 100.4, places=2)

    def test_R4_duplicado_real_sigue_descartado(self):
        so, mps = self._venta([100.0], pagos=(
            {'pid': '1000000001', 'transaction_amount': 100.0, 'total_paid_amount': 100.0},
            {'pid': '1000000002', 'transaction_amount': 100.0, 'total_paid_amount': 100.0},
        ))
        pays = self._cobrar(mps)
        self.assertEqual(len(pays), 1, "dos pagos iguales que la venta NO espera: se crea uno solo")
        self.assertAlmostEqual(pays.amount, 100.0, places=2)
