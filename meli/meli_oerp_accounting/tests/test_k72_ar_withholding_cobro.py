# -*- coding: utf-8 -*-
"""#caso-K72 (caso-K21 cliente F, 2025-10-14 / 2026-10-23): retenciones de MercadoPago registradas en el cobro
con l10n_ar_withholding (Odoo 17/18/19, Argentina).

El cobro ML trae en charges_details las retenciones que MP aplico (Impuesto a los Debitos y
Creditos 0,6 %, SIRTAC 3 %...). Con l10n_account_withholding_tax (19) ya se registraban; con
l10n_ar_withholding (lo que tiene el cliente, y el unico disponible en 17/18) NUNCA: el pago
quedaba por el bruto y las retenciones solo como dato.

Ahora (opt-in `mercadolibre_ar_withholding_on_payment`): pago por el NETO + una linea de retencion
por cargo (impuesto l10n_ar_withholding_payment_type='customer', monto = el que retuvo MP) + par de
base, como el wizard "Registrar pago" de Odoo. La cuenta a cobrar salda el bruto.

Payload: el JSON real del pago que el cliente adjunto en el ticket #caso-K72 (9-nov-2025), ANONIMIZADO
(ids de pago, orden, pagador, vendedor, envio, cargos e IP cambiados; montos y nombres de cargo
originales).

Control: sobre origin/<v> (sin el cambio) test_retenciones_en_el_cobro y
test_borrador_sin_autovalidacion FALLAN (el cobro sale por el bruto y sin lineas de retencion).
"""
import json
from unittest.mock import patch

from odoo import fields, release
from odoo.tests import TransactionCase, tagged

V18 = release.version_info[0] >= 18

MP_ID = '900000000239'
PAYLOAD = {
    "id": int(MP_ID),
    "status": "approved",
    "status_detail": "accredited",
    "currency_id": "ARS",
    "collector_id": 100000462,
    "external_reference": "2000345532630504",
    "order": {"id": "2000345532630504", "type": "mercadolibre"},
    "operation_type": "regular_payment",
    "payment_method_id": "account_money",
    "payment_type_id": "account_money",
    "installments": 1,
    "shipping_amount": 0,
    "taxes_amount": 0,
    "coupon_amount": 0,
    "fee_details": [],
    "transaction_amount": 58564.44,
    "transaction_amount_refunded": 0,
    "transaction_details": {"net_received_amount": 40771.81, "total_paid_amount": 58564.44,
                            "installment_amount": 0, "overpaid_amount": 0},
    "payer": {"id": "100000001", "type": "registered"},
    "charges_details": [
        {"accounts": {"from": "collector", "to": "mp"},
         "amounts": {"original": 351.39, "refunded": 0},
         "base_amount": 58564.44, "client_id": 0,
         "date_created": "2025-11-09T20:30:40.000-04:00",
         "id": MP_ID + "-001",
         "metadata": {"mov_detail": "tax_withholding_collector", "mov_financial_entity": "debitos_creditos",
                      "mov_type": "expense", "source": "taxes", "source_detail": "",
                      "tax_id": 100000000001, "tax_status": "applied", "user_id": 100000462},
         "name": "tax_withholding_collector-debitos_creditos", "rate": 0.6,
         "refund_charges": [], "reserve_id": None, "type": "tax"},
        {"accounts": {"from": "collector", "to": "mp"},
         "amounts": {"original": 1756.93, "refunded": 0},
         "base_amount": 58564.44, "client_id": 0,
         "date_created": "2025-11-09T20:30:40.000-04:00",
         "id": MP_ID + "-002",
         "metadata": {"mov_detail": "tax_withholding_sirtac", "mov_financial_entity": "buenos_aires",
                      "mov_type": "expense", "source": "taxes", "source_detail": "",
                      "tax_id": 100000000002, "tax_status": "applied", "user_id": 100000462},
         "name": "tax_withholding_sirtac-buenos_aires", "rate": 3,
         "refund_charges": [], "reserve_id": None, "type": "tax"},
        {"accounts": {"from": "collector", "to": "100000003"},
         "amounts": {"original": 6560.49, "refunded": 0},
         "client_id": 1, "date_created": "2025-11-09T20:30:45.000-04:00",
         "id": MP_ID + "-003",
         "metadata": {"shipment_id": 100000000003, "source": "deferred-charges",
                      "source_detail": "shipping-account-movements"},
         "name": "shp_fulfillment", "refund_charges": [], "reserve_id": None, "type": "shipping"},
        {"accounts": {"from": "collector", "to": "ml"},
         "amounts": {"original": 9123.82, "refunded": 0},
         "client_id": 2, "date_created": "2025-11-09T20:30:48.000-04:00",
         "id": MP_ID + "-004",
         "metadata": {"source": "deferred-charges", "source_detail": "fees-api"},
         "name": "meli_percentage_fee", "refund_charges": [], "reserve_id": None, "type": "fee"},
    ],
}
BRUTO = 58564.44
RET_DC = 351.39
RET_SIRTAC = 1756.93
NETO = round(BRUTO - RET_DC - RET_SIRTAC, 2)   # 56456.12


@tagged('post_install', '-at_install', 'meli_K72')
class TestArWithholdingCobro239(TransactionCase):

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

    def _cuenta(self, code, name, account_type, reconcile=False):
        vals = {'name': name, 'code': code, 'account_type': account_type, 'reconcile': reconcile}
        if 'company_ids' in self.env['account.account']._fields:
            vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            vals['company_id'] = self.co.id
        return self.env['account.account'].create(vals)

    def _impuesto_ret(self, name, amount, payment_type='customer'):
        vals = {'name': name, 'amount': amount, 'amount_type': 'percent',
                'type_tax_use': 'none', 'company_id': self.co.id,
                'l10n_ar_withholding_payment_type': payment_type}
        if self.ar:
            vals['country_id'] = self.ar.id
        vals['tax_group_id'] = self.grupo.id
        tax = self.env['account.tax'].create(vals)
        tax.invoice_repartition_line_ids.filtered(lambda l: l.repartition_type == 'tax').account_id = self.cta_ret
        return tax

    def _regla(self, charge_name, entity, tax):
        return self.env['mercadolibre.tax'].create({
            'name': entity.upper(), 'meli_charge_type': 'tax', 'meli_charge_name': charge_name,
            'meli_financial_entity': entity, 'company_id': self.co.id, 'state': 'confirmed',
            'account_tax_id': tax.id})

    def setUp(self):
        super().setUp()
        if 'l10n_ar_withholding_payment_type' not in self.env['account.tax']._fields:
            self.skipTest("sin l10n_ar_withholding")
        self.co = self.env.company
        if not self.env['account.account'].search([('account_type', '=', 'asset_receivable')], limit=1):
            self.skipTest("sin plan de cuentas en esta base")
        self.ar = self.env.ref('base.ar', raise_if_not_found=False)
        if self.ar and 'account_fiscal_country_id' in self.co._fields:
            # El caso es AR (cliente F): las retenciones l10n_ar exigen pais fiscal AR.
            self.co.account_fiscal_country_id = self.ar
        self.cta_pend = self._cuenta('1239001', 'Cobros ML pendientes 239', 'asset_current', True)
        self.cta_ret = self._cuenta('1239002', 'Retenciones sufridas 239', 'asset_current')
        self.cta_base = self._cuenta('1239003', 'Base retenciones 239', 'asset_current')
        self.co.l10n_ar_tax_base_account_id = self.cta_base
        gvals = {'name': 'Retenciones 239'}
        if self.ar and 'country_id' in self.env['account.tax.group']._fields:
            gvals['country_id'] = self.ar.id
        self.grupo = self.env['account.tax.group'].create(gvals)
        manual = self.env.ref('account.account_payment_method_manual_in')
        self.journal = self.env['account.journal'].create({
            'name': 'MercadoPago 239', 'code': 'MK72', 'type': 'bank', 'company_id': self.co.id})
        self.journal.inbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'Transferencia', 'payment_method_id': manual.id, 'payment_account_id': self.cta_pend.id})]
        self.co.mercadolibre_process_payments_journal = self.journal
        self.co.mercadolibre_payment_receipt_validation = 'validate'
        if 'mercadolibre_notification_mode' in self.co._fields:
            self.co.mercadolibre_notification_mode = 'internal_note'
        if 'mercadolibre_order_total_config' in self.co._fields:
            self.co.mercadolibre_order_total_config = False
        # Sobre origin el campo no existe: el test corre igual y falla por la aserción.
        if 'mercadolibre_ar_withholding_on_payment' in self.co._fields:
            self.co.mercadolibre_ar_withholding_on_payment = True
        self.tax_dc = self._impuesto_ret('Ret. Imp. Deb/Cred 239', 0.6)
        self.tax_sirtac = self._impuesto_ret('Ret. IIBB SIRTAC 239', 3.0)
        self._regla('tax_withholding_collector-debitos_creditos', 'debitos_creditos', self.tax_dc)
        self._regla('tax_withholding_sirtac-buenos_aires', 'buenos_aires', self.tax_sirtac)
        self.partner = self.env['res.partner'].create({'name': 'Comprador ML 239'})
        if V18:
            Move = type(self.env['account.move'])
            p = patch.object(Move, '_get_invoice_in_payment_state', lambda self: 'in_payment', create=False)
            p.start()
            self.addCleanup(p.stop)

    def _pago_ml(self):
        so = self.env['sale.order'].create({'partner_id': self.partner.id})
        ml_id = PAYLOAD['order']['id']
        try:
            mo = self._crear_minimo('mercadolibre.orders', {'order_id': ml_id, 'name': ml_id, 'sale_order': so.id})
            mp = self._crear_minimo('mercadolibre.payments', {
                'order_id': mo.id, 'payment_id': MP_ID, 'status': 'approved',
                'currency_id': self.co.currency_id.name, 'transaction_amount': BRUTO,
                'total_paid_amount': BRUTO, 'full_payment': json.dumps(PAYLOAD)})
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        mp.sync_charges_from_json()   # lo que hace confirm_ml antes de crear el cobro
        return so, mp

    def _chatter(self, so):
        return " || ".join(str(m.body) for m in so.message_ids if m.body)

    def _lineas(self, pay):
        lines = pay.move_id.line_ids
        wth = lines.filtered(lambda l: l.tax_line_id and l.tax_line_id.l10n_ar_withholding_payment_type == 'customer')
        liq = lines.filtered(lambda l: l.account_id == self.cta_pend)
        rec = lines.filtered(lambda l: l.account_id == pay.destination_account_id)
        base = lines.filtered(lambda l: l.account_id == self.cta_base)
        return wth, liq, rec, base

    def test_retenciones_en_el_cobro(self):
        so, mp = self._pago_ml()
        self.assertEqual(len(mp.charge_ids.filtered(lambda c: c.charge_type == 'tax')), 2)
        mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertTrue(pay and pay.move_id, "crea el cobro con asiento")
        self.assertAlmostEqual(pay.amount, NETO, places=2, msg="el cobro va por el NETO")
        wth, liq, rec, base = self._lineas(pay)
        self.assertEqual(len(wth), 2, "una linea de retencion por cargo tax de MP")
        self.assertEqual(sorted(round(l.balance, 2) for l in wth), [RET_DC, RET_SIRTAC],
                         "monto = el que retuvo MP")
        self.assertEqual(wth.tax_line_id, self.tax_dc | self.tax_sirtac)
        self.assertEqual(set(wth.mapped('name')), {MP_ID + '-001', MP_ID + '-002'},
                         "numero de retencion = id del cargo de MP")
        self.assertAlmostEqual(sum(liq.mapped('balance')), NETO, places=2, msg="liquidez = neto")
        self.assertAlmostEqual(sum(rec.mapped('balance')), -BRUTO, places=2, msg="a cobrar salda el BRUTO")
        self.assertEqual(len(base), 2, "par de base +/-")
        self.assertAlmostEqual(sum(base.mapped('balance')), 0.0, places=2)
        self.assertAlmostEqual(max(base.mapped('balance')), BRUTO, places=2)
        self.assertEqual(pay.move_id.state, 'posted')
        if 'l10n_ar_withholding_ids' in pay._fields:
            self.assertEqual(len(pay.l10n_ar_withholding_ids), 2, "visible como retenciones del pago")
        self.assertAlmostEqual(mp._meli_account_payment_gross(), BRUTO, places=2,
                               msg="multi-pago suma el bruto, no el neto")

    def test_borrador_sin_autovalidacion(self):
        self.co.mercadolibre_payment_receipt_validation = 'draft'
        so, mp = self._pago_ml()
        mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertTrue(pay)
        self.assertEqual(pay.state, 'draft', "sin autovalidacion queda en borrador, como cualquier cobro")
        self.assertAlmostEqual(pay.amount, NETO, places=2)
        pay.action_post()
        wth, liq, rec, base = self._lineas(pay)
        self.assertEqual(pay.move_id.state, 'posted')
        self.assertEqual(len(wth), 2, "al confirmar a mano conserva las retenciones")
        self.assertAlmostEqual(sum(rec.mapped('balance')), -BRUTO, places=2)

    def test_apagado_igual_que_antes(self):
        if 'mercadolibre_ar_withholding_on_payment' in self.co._fields:
            self.co.mercadolibre_ar_withholding_on_payment = False
        so, mp = self._pago_ml()
        mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertAlmostEqual(pay.amount, BRUTO, places=2)
        wth, liq, rec, base = self._lineas(pay)
        self.assertFalse(wth)
        self.assertFalse(base)
        self.assertNotIn("SIN retenciones", self._chatter(so))

    def test_regla_sin_impuesto_de_cobro_no_aplica_y_avisa(self):
        """Todo o nada: si una retencion no tiene impuesto 'Retencion en pago de cliente', el cobro
        sale por el bruto (como hoy) y queda el motivo en la venta, una sola vez."""
        self.tax_sirtac.l10n_ar_withholding_payment_type = 'supplier'
        so, mp = self._pago_ml()
        mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertAlmostEqual(pay.amount, BRUTO, places=2)
        self.assertFalse(self._lineas(pay)[0])
        self.assertIn("SIN retenciones", self._chatter(so))
        self.assertIn("tax_withholding_sirtac-buenos_aires", self._chatter(so))

    def test_sin_cuenta_base_no_aplica_y_avisa(self):
        self.co.l10n_ar_tax_base_account_id = False
        so, mp = self._pago_ml()
        mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertAlmostEqual(pay.amount, BRUTO, places=2)
        self.assertFalse(self._lineas(pay)[0])
        self.assertIn("cuenta base", self._chatter(so))

    def test_red_si_las_retenciones_se_pierden_cobro_como_siempre(self):
        """Un modulo intermedio (p.ej. grupos de pago) que descarta write_off_line_vals en silencio
        dejaria el cobro por el NETO sin retenciones: factura impaga por la diferencia. La red lo
        detecta, revierte y crea el cobro como siempre (bruto), sin duplicarlo, y avisa en la venta."""
        Pay = type(self.env['account.payment'])
        orig = Pay.create

        def create_sin_retenciones(this, vals_list):
            vl = vals_list if isinstance(vals_list, list) else [vals_list]
            return orig(this, [{k: v for k, v in d.items() if k != 'write_off_line_vals'} for d in vl])

        so, mp = self._pago_ml()
        with patch.object(Pay, 'create', create_sin_retenciones):
            mp.create_payment(config=self.co)
        pay = mp.account_payment_id
        self.assertTrue(pay, "el cobro se crea igual")
        self.assertAlmostEqual(pay.amount, BRUTO, places=2, msg="como siempre: bruto")
        wth, liq, rec, base = self._lineas(pay)
        self.assertFalse(wth)
        self.assertAlmostEqual(sum(rec.mapped('balance')), -BRUTO, places=2)
        self.assertEqual(self.env['account.payment'].search_count([('partner_id', '=', pay.partner_id.id),
                                                                   ('journal_id', '=', self.journal.id)]), 1,
                         "el intento con retenciones se revirtio: un solo cobro")
        self.assertIn("no se pudieron registrar", self._chatter(so))
