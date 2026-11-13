# -*- coding: utf-8 -*-
"""FIX cierre sin stock (29-oct-2026) — una entrega ML ya ENTREGADA en MercadoLibre (Full o
Flex) cuyo producto NO tiene stock en Odoo tiene que cerrarse sola, y la venta tiene que
poder facturarse.

Caso de producción (16.0, post 26.296): el cierre automático (`meli_deliver`) no encuentra
reserva, fuerza la cantidad hecha con `_prepare_move_line_vals(quantity=…)` — que en 16.0
crea la línea con `reserved_uom_qty` pero SIN reservar en el quant (fantasma propia) — y
valida. El saneo de reservas fantasma del override de `button_validate` era lo que alineaba
el quant; la guarda "cantidades cargadas por el operador" (#caso-K41-K42) lo empezó a omitir
porque ve qty_done > 0, y `_action_done` cortaba con "No es posible deshacer la reserva".
La venta quedaba entregada en ML, abierta en Odoo y sin factura.

Lo que se fija: (1) el cierre automático valida; (2) la venta queda con cantidad entregada
y algo para facturar; (3) la guarda del operador sigue en pie para el cierre MANUAL.
"""
import logging

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

LOGGER = 'odoo.addons.meli_oerp_stock.models.stock_location'


@tagged('post_install', '-at_install', 'meli_oerp_stock', 'meli_cierre_sin_stock')
class TestMeliCierreSinStock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Product = env['product.product']
        vals = {'name': 'VEL30 cierre sin stock', 'type': 'consu', 'invoice_policy': 'delivery'}
        if 'is_storable' in Product._fields:
            vals['is_storable'] = True
        else:
            vals['type'] = 'product'
        cls.product = Product.create(vals)
        cls.warehouse = env['stock.warehouse'].search(
            [('company_id', '=', env.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.partner = env['res.partner'].create({'name': 'Comprador cierre sin stock'})

    def _ml_sale(self, logistic_type, n):
        """Venta ML confirmada, envío ML entregado, producto SIN un solo quant."""
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1.0,
                                   'price_unit': 100.0})],
        })
        so.action_confirm()
        so.meli_order_id = '20000189476%05d' % n
        so.meli_shipment = self.env['mercadolibre.shipment'].create({
            'sale_order': so.id, 'shipping_id': '48242%06d' % n,
            'status': 'delivered', 'logistic_type': logistic_type,
        })
        out = so.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')
        self.assertEqual(len(out), 1, "la venta debe generar una salida")
        self.assertFalse(self.env['stock.quant'].search([('product_id', '=', self.product.id)]),
                         "precondición: el producto no tiene ningún quant (sin stock en Odoo)")
        self.assertTrue(out._meli_is_ml_out(), "precondición: es una salida ML")
        return so, out

    def _assert_closed_and_invoiceable(self, so, out, res):
        self.assertFalse(res.get('errors'), "el cierre automático no debe fallar: %s" % res.get('errors'))
        self.assertEqual(out.state, 'done', "la entrega entregada en ML debe cerrarse")
        line = so.order_line.filtered(lambda l: l.product_id == self.product)
        self.assertEqual(line.qty_delivered, 1.0)
        self.assertEqual(line.qty_to_invoice, 1.0, "la venta tiene que quedar para facturar")
        self.assertEqual(so.invoice_status, 'to invoice')
        # La factura en sí: sólo si la base de test tiene plan contable (diario de ventas).
        if self.env['account.journal'].search([('type', '=', 'sale'),
                                               ('company_id', '=', so.company_id.id)], limit=1):
            invoice = so._create_invoices()
            self.assertTrue(invoice, "la factura tiene que poder generarse")
            self.assertEqual(invoice.invoice_line_ids.filtered(
                lambda l: l.product_id == self.product).quantity, 1.0)

    def test_01_full_entregada_sin_stock_cierra_y_factura(self):
        so, out = self._ml_sale('fulfillment', 1)
        res = so.meli_deliver(config=self.env.company) or {}
        self._assert_closed_and_invoiceable(so, out, res)

    def test_02_flex_entregada_sin_stock_cierra_y_factura(self):
        so, out = self._ml_sale('self_service', 2)
        res = so.meli_deliver(config=self.env.company) or {}
        self._assert_closed_and_invoiceable(so, out, res)

    def test_03_guarda_del_operador_sigue_para_el_cierre_manual(self):
        """Sin el contexto del cierre automático, cantidades cargadas = no se sanea."""
        so, out = self._ml_sale('self_service', 3)
        mv = out.move_ids
        if 'quantity_done' in mv._fields:
            mv.quantity_done = 1.0
        else:
            mv.quantity = 1.0
            mv.picked = True
        self.assertTrue(out._meli_operator_loaded_qty())
        with self.assertLogs(LOGGER, level=logging.INFO) as cm:
            out._meli_heal_phantom_reserve()
        self.assertTrue(any('saneo omitido' in m for m in cm.output), cm.output)
        # Con el contexto del cierre automático, la guarda no se aplica.
        with self.assertLogs(LOGGER, level=logging.DEBUG) as cm2:
            logging.getLogger(LOGGER).debug("marcador")  # assertLogs exige al menos una línea
            out.with_context(meli_deliver_forced_qty=True)._meli_heal_phantom_reserve()
        self.assertFalse(any('saneo omitido' in m for m in cm2.output), cm2.output)
