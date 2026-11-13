# -*- coding: utf-8 -*-
"""FIX 26.381 (6-nov-2026) — salida ML reservada SIN lote de un producto con lote.

Caso de producción (19.0): 335 salidas FULL de un producto con tracking='lot' quedaron con
una línea SIN lote, `picked`, reservada contra un quant sin lote (cantidad 0). El lote tenía
stock de sobra en la misma ubicación, pero el cierre automático (cron «Cerrar Entregas
Entregadas» → meli_deliver) fallaba en cada pasada con «Debe proporcionar un número de
lote/serie» y no cerraba ninguna. Se simula la línea heredada y se verifica que:
  - meli_deliver la re-reserva con el lote y valida la salida (antes: error, salida abierta);
  - una reserva PARCIAL (carga de operador) no se toca;
  - el hook FIFO no crea líneas con lote ENCIMA de la reserva sin lote (doble reserva).
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'meli_oerp_stock', 'meli_26381')
class TestMeli26381ReservaSinLote(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Product = env['product.product']
        vals = {'name': 'PRODUCTO CON LOTE 26381', 'type': 'consu', 'tracking': 'lot',
                'default_code': 'T26381-LOTE'}
        if 'is_storable' in Product._fields:
            vals['is_storable'] = True
        else:
            vals['type'] = 'product'
        cls.product = Product.create(vals)
        cls.warehouse = env['stock.warehouse'].search(
            [('company_id', '=', env.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.lot = env['stock.lot'].create({'name': 'L26381', 'product_id': cls.product.id,
                                           'company_id': env.company.id})
        env['stock.quant']._update_available_quantity(cls.product, cls.stock_loc, 10.0, lot_id=cls.lot)
        cls.partner = env['res.partner'].create({'name': 'Comprador 26381'})
        cls.v16 = 'reserved_uom_qty' in env['stock.move.line']._fields

    def _uom(self, mv):
        return mv.product_uom if 'product_uom' in mv._fields else mv.uom_id

    def _new_out(self, qty=1.0):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': qty,
                                   'price_unit': 10.0})],
        })
        so.action_confirm()
        self.__class__._n = getattr(self.__class__, '_n', 0) + 1
        so.meli_order_id = '2000026381%03d' % self._n
        # salida FULL con envío entregado en ML: el caso de producción (y el hook FIFO sólo actúa en FULL)
        so.meli_shipment = self.env['mercadolibre.shipment'].create({
            'sale_order': so.id, 'shipping_id': '48381%06d' % self._n,
            'status': 'delivered', 'logistic_type': 'fulfillment',
        })
        out = so.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')
        self.assertEqual(len(out), 1)
        self.assertEqual(out.meli_shipment_logistic_type, 'fulfillment', "precondición: salida FULL")
        return so, out

    def _legacy_lotless(self, out, qty):
        """Deja la salida como la dejaba la versión sin savepoint: una línea SIN lote,
        cargada (16: qty_done; 17+: quantity + picked), sin reserva con lote."""
        out.do_unreserve()
        mv = out.move_ids
        vals = {'move_id': mv.id, 'picking_id': out.id, 'product_id': self.product.id,
                'location_id': mv.location_id.id, 'location_dest_id': mv.location_dest_id.id}
        if self.v16:
            vals.update({'product_uom_id': self._uom(mv).id, 'qty_done': qty})
        else:
            vals.update({'quantity': qty, 'picked': True})
            vals['uom_id' if 'uom_id' in self.env['stock.move.line']._fields else 'product_uom_id'] = self._uom(mv).id
        self.env['stock.move.line'].create(vals)
        self.env.invalidate_all()
        self.assertTrue(out.move_line_ids.filtered(lambda l: not l.lot_id), "control: línea sin lote")

    def _lot_qty(self):
        self.env.invalidate_all()
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id', '=', self.stock_loc.id),
            ('lot_id', '=', self.lot.id)]).mapped('quantity'))

    def test_01_meli_deliver_rereserva_con_lote_y_cierra(self):
        so, out = self._new_out(1.0)
        self._legacy_lotless(out, 1.0)
        res = so.meli_deliver(config=self.env.company) or {}
        self.assertFalse(res.get('errors'), "no debe fallar por el lote: %s" % res.get('errors'))
        self.assertEqual(out.state, 'done')
        self.assertEqual(out.move_line_ids.mapped('lot_id'), self.lot)
        self.assertAlmostEqual(self._lot_qty(), 9.0)
        lotless = self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id', '=', self.stock_loc.id),
            ('lot_id', '=', False)])
        self.assertFalse(any(lotless.mapped('reserved_quantity')), "no queda reserva sin lote")

    def test_02_reserva_parcial_no_se_toca(self):
        so, out = self._new_out(2.0)
        self._legacy_lotless(out, 1.0)   # carga parcial: 1 de 2
        healed = out._meli_heal_lotless_reserve()
        self.assertFalse(healed, "una carga parcial no se re-reserva")
        self.assertTrue(out.move_line_ids.filtered(lambda l: not l.lot_id))

    def test_03_fifo_no_reserva_encima_de_la_linea_sin_lote(self):
        so, out = self._new_out(1.0)
        self._legacy_lotless(out, 1.0)
        n_before = len(out.move_line_ids)
        out._meli_auto_assign_lots_fifo()
        self.env.invalidate_all()
        self.assertEqual(len(out.move_line_ids), n_before, "el hook FIFO no debe sumar otra línea")
