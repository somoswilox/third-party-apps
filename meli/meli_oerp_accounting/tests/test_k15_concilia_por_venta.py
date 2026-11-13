# -*- coding: utf-8 -*-
"""#caso-K15 (cliente E, 22-oct-2026): meli_reconcile (payment_receipt_validation='concile') conciliaba la factura
con creditos pendientes del partner que NO eran de su venta.

El filtro #caso-K46 comparaba la referencia por SUBCADENA ("S10000" esta dentro de "S100001") y, sin
referencia, no filtraba nada. Ahora el credito es de la venta si:
  - es un cobro del modulo (account.payment.meli_payment_id) de un pago ML de ESA venta, o
  - no es un cobro ML y su memo nombra la venta como token entero.
Sin venta ni referencia no se concilia nada.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_K15_concilia')
class TestConciliaPorVentaK15(TransactionCase):

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
        self.partner = self.env['res.partner'].create({'name': 'Comprador que repite (K15)'})
        self.journal = self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1)
        if not self.journal:
            self.skipTest("sin diario de banco en esta base")
        self.memo_field = next((f for f in ('memo', 'ref') if f in self.env['account.payment']._fields), None)
        self.ml_pay = {}
        self.so_a = self._venta('S10000', '2000275425103430')
        self.so_b = self._venta('S100001', '2000433490064400')
        self.inv = self._factura('S10000')

    def _venta(self, name, ml_id):
        so = self.env['sale.order'].create({'partner_id': self.partner.id})
        so.name = name
        try:
            mo = self._crear_minimo('mercadolibre.orders', {'order_id': ml_id, 'name': ml_id})
            pay = self._crear_minimo('mercadolibre.payments', {'order_id': mo.id, 'payment_id': ml_id[-6:]})
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        self.ml_pay[so.id] = pay
        return so

    def _factura(self, origin):
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id, 'invoice_origin': origin or False,
            'invoice_line_ids': [(0, 0, {'name': 'Producto ML', 'quantity': 1, 'price_unit': 100.0, 'tax_ids': [(6, 0, [])]})],
        })
        inv.action_post()
        return inv

    def _cobro(self, memo, meli_payment=None):
        vals = {'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': self.partner.id,
                'amount': self.inv.amount_total, 'journal_id': self.journal.id}
        if self.memo_field:
            vals[self.memo_field] = memo
        if meli_payment:
            vals['meli_payment_id'] = meli_payment.id
        pay = self.env['account.payment'].create(vals)
        pay.action_post()
        return pay

    def _conciliada(self, inv=None):
        inv = inv or self.inv
        inv.invalidate_recordset(['payment_state', 'amount_residual'])
        return inv.payment_state != 'not_paid'

    def test_subcadena_de_otra_venta_no_concilia(self):
        self._cobro('S100001 OP 9 TOT')
        self.so_a.meli_reconcile(invoice=self.inv)
        self.assertFalse(self._conciliada(), "el cobro de S100001 no es de S10000")

    def test_cobro_ml_de_otra_venta_no_concilia(self):
        # memo con el nombre de la venta, pero el cobro es del pago ML de OTRA venta
        self._cobro('S10000 OP 5 TOT', meli_payment=self.ml_pay[self.so_b.id])
        self.so_a.meli_reconcile(invoice=self.inv)
        self.assertFalse(self._conciliada())

    def test_cobro_ml_propio_sin_nombre_en_memo_concilia(self):
        self._cobro('OP 77', meli_payment=self.ml_pay[self.so_a.id])
        self.so_a.meli_reconcile(invoice=self.inv)
        self.assertTrue(self._conciliada(), "el cobro del pago ML de su venta es suyo aunque el memo no la nombre")

    def test_control_memo_con_su_venta_concilia(self):
        # Control positivo (pasa con y sin el fix).
        self._cobro('S10000 OP 1 TOT')
        self.so_a.meli_reconcile(invoice=self.inv)
        self.assertTrue(self._conciliada())

    def test_sin_venta_ni_referencia_no_concilia(self):
        inv = self._factura(False)
        self._cobro('COBRO SUELTO')
        self.env['sale.order'].meli_reconcile(invoice=inv)
        self.assertFalse(self._conciliada(inv), "sin venta ni referencia no se aplica un credito cualquiera")
