# -*- coding: utf-8 -*-
"""26.372 — caso-K41 cliente R #caso-K73: financiacion separada (punto 4) y devolucion de FEE/SHP (punto 6).

Fixtures reducidos a los campos que lee el codigo, con los importes de los casos medidos en prod (3-nov):
  * OP 181190052053: meli_percentage_fee 55.208,76 + financing_add_on_fee 81.645,85 (= 136.854,61).
  * OP 173823500930: orden cancelada, pago refunded total; JSON fee 20.206,41 / envio 24.750 devueltos,
    y en Odoo `amount_refunded` = 0 porque el sync no actualizaba cargos existentes.
Control: contra origin 26.370 fallan todos (faltan campos/metodos o el refunded no se actualiza).
"""
import copy
from unittest.mock import patch

from odoo import fields, release
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18

MP_FIN = {
    "id": 181190052053, "status": "approved", "currency_id": "ARS",
    "charges_details": [
        {"id": "f-1", "name": "meli_percentage_fee", "type": "fee",
         "accounts": {"from": "collector", "to": "ml"}, "amounts": {"original": 55208.76, "refunded": 0}},
        {"id": "f-2", "name": "financing_add_on_fee", "type": "fee",
         "accounts": {"from": "collector", "to": "mp"}, "amounts": {"original": 81645.85, "refunded": 0}},
    ],
}

MP_REF_APPROVED = {
    "id": 173823500930, "status": "approved", "currency_id": "ARS",
    "charges_details": [
        {"id": "r-fee", "name": "meli_percentage_fee", "type": "fee",
         "accounts": {"from": "collector", "to": "ml"}, "amounts": {"original": 20206.41, "refunded": 0}},
        {"id": "r-shp", "name": "shp_cross_docking", "type": "shipping",
         "accounts": {"from": "collector", "to": "ml"}, "amounts": {"original": 24750.0, "refunded": 0}},
        {"id": "r-tax", "name": "tax_withholding-iibb", "type": "tax",
         "accounts": {"from": "collector", "to": "mp"}, "amounts": {"original": 830.07, "refunded": 0}},
    ],
}


def _refunded(fp=MP_REF_APPROVED, fee=None, shp=None):
    out = copy.deepcopy(fp)
    out["status"] = "refunded"
    for c in out["charges_details"]:
        c["amounts"]["refunded"] = c["amounts"]["original"]
        if fee is not None and c["type"] == "fee":
            c["amounts"]["refunded"] = fee
        if shp is not None and c["type"] == "shipping":
            c["amounts"]["refunded"] = shp
    return out


class Meli718Common(TransactionCase):

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
        acc_vals = {'name': 'Pagos ML 26372', 'code': '1372001', 'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in self.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            acc_vals['company_id'] = self.co.id
        self.cuenta = self.env['account.account'].create(acc_vals)
        self.journal = self.env['account.journal'].create({
            'name': 'Mercado Pago 26372', 'code': 'M372', 'type': 'bank', 'company_id': self.co.id})
        out = self.env.ref('account.account_payment_method_manual_out')
        inb = self.env.ref('account.account_payment_method_manual_in')
        self.journal.outbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'Pago manual', 'payment_method_id': out.id, 'payment_account_id': self.cuenta.id})]
        self.journal.inbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'Cobro manual', 'payment_method_id': inb.id, 'payment_account_id': self.cuenta.id})]
        self.ml = self.env['res.partner'].create({'name': 'MercadoLibre S.R.L. 26372'})
        self.log = self.env['res.partner'].create({'name': 'Meli Log 26372'})
        for f, v in (('mercadolibre_payment_receipt_validation', 'validate'),
                     ('mercadolibre_order_total_config', False)):
            if f in self.co._fields:
                self.co[f] = v
        self.co.meli_refund_revert_charges = True
        self.buyer = self.env['res.partner'].create({'name': 'Comprador ML 26372'})
        self.n = 0
        if V18:
            Move = type(self.env['account.move'])
            p = patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'in_payment')
            p.start()
            self.addCleanup(p.stop)

    def _pago_ml(self, full_payment, status='approved'):
        self.n += 1
        so = self.env['sale.order'].create({'partner_id': self.buyer.id})
        ml_id = '20008150551541%02d' % self.n
        try:
            mo = self._crear_minimo('mercadolibre.orders', {'order_id': ml_id, 'name': ml_id, 'sale_order': so.id})
            pay = self._crear_minimo('mercadolibre.payments', {
                'order_id': mo.id, 'payment_id': '1738235009%02d' % self.n, 'status': status,
                'currency_id': self.co.currency_id.name, 'transaction_amount': 138344.31,
                'total_paid_amount': 138344.31, 'fee_amount': 0.0,
                'full_payment': str(copy.deepcopy(full_payment))})
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        pay.sync_charges_from_json()
        return so, pay

    def _saliente(self, partner, amount, memo):
        vals = {'company_id': self.co.id, 'partner_id': partner.id, 'payment_type': 'outbound',
                'partner_type': 'supplier', 'journal_id': self.journal.id, 'amount': amount,
                'payment_method_line_id': self.journal.outbound_payment_method_line_ids[:1].id}
        ref = next((f for f in ('memo', 'ref') if f in self.env['account.payment']._fields), None)
        if ref:
            vals[ref] = memo
        p = self.env['account.payment'].create(vals)
        p.action_post()
        return p

    def _con_originales(self, fee=20206.41, shp=24750.0):
        so, mp = self._pago_ml(MP_REF_APPROVED)
        if fee:
            mp.account_supplier_payment_id = self._saliente(self.ml, fee, '%s OP %s FEE' % (so.name, mp.payment_id))
        if shp:
            mp.account_supplier_payment_shipment_id = self._saliente(self.log, shp, '%s OP %s SHP' % (so.name, mp.payment_id))
        return so, mp

    def _reembolsar(self, mp, fp=None, status='refunded'):
        mp.write({'status': status, 'full_payment': str(fp or _refunded())})
        mp.sync_charges_from_json()

    def _rev(self, mp):
        return self.env['account.payment'].search([('meli_payment_id', '=', mp.id), ('payment_type', '=', 'inbound')])



@tagged('post_install', '-at_install', 'meli_26372')
class TestMejoras718(Meli718Common):

    # ---------------------------------------------------------------- punto 4
    def test_4b_comision_excluye_financing_add_on_fee_por_defecto(self):
        if 'meli_supplier_fee_mode' not in self.co._fields:
            self.skipTest("modo charges_only (#caso-K76) solo en esta serie")
        self.co.meli_supplier_fee_mode = 'charges_only'
        so, mp = self._pago_ml(MP_FIN)
        self.assertAlmostEqual(mp._get_supplier_fee_amount(config=self.co), 55208.76, places=2)

    # ---------------------------------------------------------------- punto 6
    def test_6a_sync_actualiza_reintegro_de_cargos_existentes(self):
        so, mp = self._pago_ml(MP_REF_APPROVED)
        self.assertEqual(sum(mp.charge_ids.mapped('amount_refunded')), 0.0)
        n = len(mp.charge_ids)
        self._reembolsar(mp)
        self.assertEqual(len(mp.charge_ids), n, "no duplica cargos")
        fee = mp.charge_ids.filtered(lambda c: c.charge_type == 'fee')
        self.assertAlmostEqual(fee.amount_refunded, 20206.41, places=2,
                               msg="el reintegro informado DESPUES del alta tiene que llegar a Odoo")

    def test_6b_refunded_registra_fee_rev_y_shp_rev_idempotente(self):
        so, mp = self._con_originales()
        self._reembolsar(mp)
        so._meli_718_revert_refunds(config=self.co)
        fee_rev, shp_rev = mp.account_supplier_payment_rev_id, mp.account_supplier_payment_shipment_rev_id
        self.assertTrue(fee_rev and shp_rev)
        self.assertEqual(fee_rev.payment_type, 'inbound')
        self.assertEqual(fee_rev.partner_id, self.ml)
        self.assertEqual(shp_rev.partner_id, self.log)
        self.assertAlmostEqual(fee_rev.amount, 20206.41, places=2)
        self.assertAlmostEqual(shp_rev.amount, 24750.0, places=2)
        ref = next((f for f in ('memo', 'ref') if f in fee_rev._fields), None)
        self.assertTrue(str(fee_rev[ref]).endswith('FEE-REV'))
        self.assertTrue(str(shp_rev[ref]).endswith('SHP-REV'))
        # segunda y tercera pasada: no duplica
        so._meli_718_revert_refunds(config=self.co)
        so._meli_718_revert_refunds(config=self.co)
        self.assertEqual(len(self._rev(mp)), 2)
        # link perdido: se re-vincula por memo, no se crea otro
        mp.account_supplier_payment_rev_id = False
        so._meli_718_revert_refunds(config=self.co)
        self.assertEqual(mp.account_supplier_payment_rev_id, fee_rev)
        self.assertEqual(len(self._rev(mp)), 2)
        # el original no se toca
        self.assertNotIn(mp.account_supplier_payment_id.state, ('cancel', 'draft'))

    def test_6c_flag_apagado_no_hace_nada(self):
        self.co.meli_refund_revert_charges = False
        so, mp = self._con_originales()
        self._reembolsar(mp)
        so._meli_718_revert_refunds(config=self.co)
        self.assertFalse(self._rev(mp), "default apagado: comportamiento actual")

    def test_6d_sin_original_no_registra_y_tope_al_original(self):
        so, mp = self._con_originales(fee=20000.0, shp=0.0)
        self._reembolsar(mp)
        so._meli_718_revert_refunds(config=self.co)
        self.assertAlmostEqual(mp.account_supplier_payment_rev_id.amount, 20000.0, places=2,
                               msg="nunca se devuelve mas que el pago original")
        self.assertFalse(mp.account_supplier_payment_shipment_rev_id, "sin SHP original no hay SHP-REV")

    def test_6e_reintegro_cero_no_crea(self):
        so, mp = self._con_originales()
        self._reembolsar(mp, fp=_refunded(fee=0.0, shp=0.0))
        so._meli_718_revert_refunds(config=self.co)
        self.assertFalse(self._rev(mp))

    def test_6f_charged_back_tambien(self):
        so, mp = self._con_originales(shp=0.0)
        self._reembolsar(mp, status='charged_back')
        so._meli_718_revert_refunds(config=self.co)
        self.assertAlmostEqual(mp.account_supplier_payment_rev_id.amount, 20206.41, places=2)

    def test_6g_pack_partido_no_es_devolucion(self):
        so, mp = self._con_originales()
        if not hasattr(mp, '_meli_is_pack_splitted'):
            self.skipTest("sin deteccion de pack partido (#caso-K74) en esta serie")
        mp.order_id.status_detail = 'pack_splitted: Purchases has splitted the pack'
        self._reembolsar(mp)
        so._meli_718_revert_refunds(config=self.co)
        self.assertFalse(self._rev(mp))

    def test_6h_aprobado_no_revierte(self):
        so, mp = self._con_originales()
        so._meli_718_revert_refunds(config=self.co)
        self.assertFalse(self._rev(mp))

    def test_6i_financiacion_devuelta_no_entra_en_fee_rev(self):
        fp = copy.deepcopy(MP_FIN)
        so, mp = self._pago_ml(fp)
        mp.account_supplier_payment_id = self._saliente(self.ml, 55208.76, '%s OP %s FEE' % (so.name, mp.payment_id))
        self._reembolsar(mp, fp=_refunded(fp))
        so._meli_718_revert_refunds(config=self.co)
        self.assertAlmostEqual(mp.account_supplier_payment_rev_id.amount, 55208.76, places=2,
                               msg="la financiacion no fue parte del FEE: tampoco de su devolucion")


@tagged('post_install', '-at_install', 'meli_26372')
class TestNCBorrador718(Meli718Common):
    """Decision del cliente (call 4-nov): la NC por reembolso se crea EN BORRADOR, nunca se postea sola."""

    def setUp(self):
        super().setUp()
        self.co.meli_refund_credit_note_draft = True
        self.prod = self.env['product.product'].create({
            'name': 'Producto ML 26372', 'type': 'service', 'list_price': 138344.31,
            'invoice_policy': 'order'})

    def _venta_facturada(self, status='refunded'):
        so, mp = self._pago_ml(MP_REF_APPROVED)
        so.write({'order_line': [(0, 0, {'product_id': self.prod.id, 'product_uom_qty': 1,
                                          'price_unit': 138344.31})]})
        try:
            so.action_confirm()
            inv = so._create_invoices()
            inv.action_post()
        except Exception as e:
            self.skipTest("no se pudo facturar la venta en esta base: %s" % e)
        self._reembolsar(mp, status=status)
        return so, mp, inv

    def _ncs(self, inv):
        return self.env['account.move'].search([('reversed_entry_id', '=', inv.id)])

    def test_nc_1_reembolso_total_crea_nc_en_borrador_una_vez(self):
        so, mp, inv = self._venta_facturada()
        so._meli_718_revert_refunds(config=self.co)
        ncs = self._ncs(inv)
        self.assertEqual(len(ncs), 1)
        self.assertEqual(ncs.state, 'draft', "la NC nunca se publica sola")
        so._meli_718_revert_refunds(config=self.co)
        so._meli_718_revert_refunds(config=self.co)
        self.assertEqual(len(self._ncs(inv)), 1, "una NC en borrador cuenta: no se crea otra")
        self.assertEqual(inv.state, 'posted', "la factura original no se toca")

    def test_nc_2_flag_apagado_no_crea(self):
        self.co.meli_refund_credit_note_draft = False
        so, mp, inv = self._venta_facturada()
        so._meli_718_revert_refunds(config=self.co)
        self.assertFalse(self._ncs(inv))

    def test_nc_3_reintegro_parcial_o_contracargo_no_crea(self):
        for st in ('partially_refunded', 'charged_back'):
            so, mp, inv = self._venta_facturada(status=st)
            so._meli_718_revert_refunds(config=self.co)
            self.assertFalse(self._ncs(inv), st)

    def test_nc_4_modo_cancelacion_credit_note_respeta_borrador(self):
        if 'mercadolibre_invoice_cancel_mode' not in self.co._fields:
            self.skipTest("sin modo de cancelacion de factura")
        self.co.meli_refund_credit_note_draft = True
        self.co.mercadolibre_invoice_cancel_mode = 'credit_note'
        so, mp, inv = self._venta_facturada(status='approved')
        so._meli_cancel_invoices(config=self.co)
        so._meli_cancel_invoices(config=self.co)
        ncs = self._ncs(inv)
        self.assertEqual(len(ncs), 1, "idempotente con NC en borrador")
        self.assertEqual(ncs.state, 'draft')
