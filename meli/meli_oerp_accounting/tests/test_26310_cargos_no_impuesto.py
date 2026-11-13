# -*- coding: utf-8 -*-
"""Brasil A / S3 (26.310): _apply_meli_taxes_to_order_lines solo aplica a las lineas de venta las
reglas de cargos de tipo IMPUESTO (retenciones) de Mercado Pago.

Antes recorria todos los charges_details: una regla de comision ('fee', tarifa de venda) o de envio
('shipping', frete) mapeada a un impuesto de Odoo se agregaba a las lineas del pedido y cambiaba su
total. En Brasil es natural querer asociar la tarifa a PIS/COFINS: eso no debe tocar la venta.
Mismo criterio que payments.py _prepare_withholding_lines.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli', 'meli_26310')
class TestCargosNoImpuesto26310(TransactionCase):

    def _crear_minimo(self, model, extra=None, _visitados=None):
        _visitados = _visitados or set()
        Model = self.env[model]
        vals = {}
        for name, f in Model._fields.items():
            if not f.required or f.compute or f.related or f.readonly or name in (extra or {}):
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
        company = self.env.company
        Tax = self.env['account.tax']
        self.tax_fee = Tax.create({'name': 'PIS s/ tarifa 26310', 'amount': 1.65, 'amount_type': 'percent',
                                   'type_tax_use': 'sale', 'company_id': company.id})
        self.tax_shp = Tax.create({'name': 'COFINS s/ frete 26310', 'amount': 7.6, 'amount_type': 'percent',
                                   'type_tax_use': 'sale', 'company_id': company.id})
        vals_ret = {'name': 'IRRF retido 26310', 'amount': -1.5, 'amount_type': 'percent',
                    'type_tax_use': 'sale', 'company_id': company.id}
        if 'is_withholding_tax' in Tax._fields:
            vals_ret['is_withholding_tax'] = False   # retencion en la venta, no al pago
        self.tax_ret = Tax.create(vals_ret)
        Rule = self.env['mercadolibre.tax']
        for ctype, cname, tax in (('fee', 'meli_percentage_fee', self.tax_fee),
                                  ('shipping', 'shp_cross_docking', self.tax_shp),
                                  ('tax', 'tax_withholding-irrf', self.tax_ret)):
            Rule.create({'name': cname, 'meli_charge_type': ctype, 'meli_charge_name': cname,
                         'account_tax_id': tax.id, 'state': 'confirmed', 'company_id': company.id})

        self.mo = self._crear_minimo('mercadolibre.orders', {'order_id': 'MLB-2000212147435'})
        self.mp = self._crear_minimo('mercadolibre.payments', {'payment_id': 'MLBpay26310', 'order_id': self.mo.id})
        partner = self.env['res.partner'].create({'name': 'Comprador BR 26310'})
        product = self.env['product.product'].create({'name': 'Produto 26310', 'list_price': 100.0})
        line_tax_field = 'tax_ids' if 'tax_ids' in self.env['sale.order.line']._fields else 'tax_id'
        self.tf = line_tax_field
        self.so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'meli_orders': [(6, 0, [self.mo.id])],
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1, 'price_unit': 100.0,
                                   line_tax_field: [(6, 0, [])]})],
        })

    def _charge(self, ctype, cname, amount):
        return self.env['mercadolibre.payment.charge'].create({
            'payment_id': self.mp.id, 'charge_type': ctype, 'name': cname, 'amount_original': amount,
        })

    def test_tarifa_y_frete_no_cambian_el_total(self):
        self._charge('fee', 'meli_percentage_fee', 16.0)
        self._charge('shipping', 'shp_cross_docking', 20.0)
        total = self.so.amount_total
        self.so._apply_meli_taxes_to_order_lines()
        self.assertEqual(self.so.amount_total, total, 'tarifa de venda / frete no deben tocar el total')
        self.assertFalse(getattr(self.so.order_line, self.tf) & (self.tax_fee | self.tax_shp))

    def test_retencion_tipo_tax_si_se_aplica(self):
        self._charge('fee', 'meli_percentage_fee', 16.0)
        self._charge('tax', 'tax_withholding-irrf', 1.5)
        self.so._apply_meli_taxes_to_order_lines()
        taxes = getattr(self.so.order_line, self.tf)
        self.assertIn(self.tax_ret, taxes)
        self.assertNotIn(self.tax_fee, taxes)
