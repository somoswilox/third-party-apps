# -*- coding: utf-8 -*-
"""FIX #caso-K41-caso-K42 (cliente R, 21-oct-2026) — validar una entrega parcial NO debe
cambiar las cantidades cargadas por el operador.

Caso de producción: venta común (sin ML) S07651 / DB/OUT/01247. El operador cargó
9 / 176 / 59 y presionó Validar; Odoo validó 27 / 390 / 150. El override de
button_validate (saneo #caso-K43) tomaba toda entrega a cliente como ML, veía un
"fantasma" en el producto no almacenable (sin reserva en quants) y hacía
do_unreserve()+action_assign() sobre la entrega entera, pisando lo cargado.
"""
import logging

from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase

LOGGER = 'odoo.addons.meli_oerp_stock.models.stock_location'


@tagged('post_install', '-at_install', 'meli_oerp_stock', 'meli_K41_K42')
class TestMeli420674ValidacionParcial(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Product = env['product.product']

        def _prod(name, storable):
            vals = {'name': name, 'type': 'consu'}
            if 'is_storable' in Product._fields:
                vals['is_storable'] = storable
            elif storable:
                vals['type'] = 'product'
            return Product.create(vals)

        cls.p_fp = _prod('FP.156 #caso-K42', True)        # almacenable, stock 27 < demanda 32
        cls.p_cp = _prod('DK.CP corte #caso-K42', False)  # NO almacenable
        cls.p_eo = _prod('EO.PVCBL #caso-K42', True)      # almacenable, stock = demanda
        cls.warehouse = env['stock.warehouse'].search(
            [('company_id', '=', env.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        Quant = env['stock.quant']
        Quant._update_available_quantity(cls.p_fp, cls.stock_loc, 27.0)
        Quant._update_available_quantity(cls.p_eo, cls.stock_loc, 150.0)
        cls.partner = env['res.partner'].create({'name': 'Milajer #caso-K42'})
        cls.demand = {cls.p_fp: 32.0, cls.p_cp: 390.0, cls.p_eo: 150.0}
        cls.loaded = {cls.p_fp: 9.0, cls.p_cp: 176.0, cls.p_eo: 59.0}

    # ---------------------------------------------------------------- helpers
    def _new_out(self, ml=False, demand=None):
        demand = demand or self.demand
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [(0, 0, {'product_id': p.id, 'product_uom_qty': q,
                                   'price_unit': 10.0})
                           for p, q in demand.items()],
        })
        so.action_confirm()
        if ml:
            so.meli_order_id = '2000395335921'
        out = so.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')
        self.assertEqual(len(out), 1, "la venta debe generar una salida")
        if out.state in ('confirmed', 'waiting'):
            out.action_assign()
        return so, out

    def _move_qty(self, mv):
        return mv.quantity_done if 'quantity_done' in mv._fields else mv.quantity

    def _load_operator_qty(self, out):
        """Lo que hace el operador: escribir la cantidad en cada línea."""
        for mv in out.move_ids:
            q = self.loaded[mv.product_id]
            if 'quantity_done' in mv._fields:
                mv.quantity_done = q
            else:
                mv.quantity = q

    def _validate(self, out):
        res = out.button_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
            Form(self.env[res['res_model']].with_context(res['context'])).save().process()
        self.assertEqual(out.state, 'done')

    def _assert_validated_as_loaded(self, so, out):
        done = {mv.product_id: self._move_qty(mv)
                for mv in out.move_ids if mv.state == 'done'}
        self.assertEqual(
            [done.get(p) for p in self.loaded], list(self.loaded.values()),
            "las cantidades validadas deben ser las cargadas por el operador")
        backorder = so.picking_ids.filtered(
            lambda p: p.backorder_id == out and p.state not in ('done', 'cancel'))
        self.assertTrue(backorder, "debe quedar un pendiente (backorder)")
        pending = {mv.product_id: mv.product_uom_qty for mv in backorder.move_ids}
        self.assertEqual(
            [pending.get(p) for p in self.loaded],
            [self.demand[p] - self.loaded[p] for p in self.loaded],
            "el pendiente debe ser demanda - cargado")

    # ------------------------------------------------------------------ tests
    def test_venta_no_ml_parcial_valida_lo_cargado(self):
        """El caso del cliente: venta común, entrega parcial."""
        so, out = self._new_out(ml=False)
        is_ml = out._meli_is_ml_out()
        self._load_operator_qty(out)
        self._validate(out)
        self._assert_validated_as_loaded(so, out)
        self.assertFalse(is_ml, "una venta sin ML no es salida ML (#caso-K43 no debe correr)")

    def test_venta_ml_parcial_no_re_reserva(self):
        """Venta ML con cantidades cargadas: el saneo no toca nada."""
        so, out = self._new_out(ml=True)
        self.assertTrue(out._meli_is_ml_out(), "venta ML: sí es salida ML")
        self._load_operator_qty(out)
        self._validate(out)
        self._assert_validated_as_loaded(so, out)

    def test_control_positivo_heal_sigue_detectando_fantasma(self):
        """Venta ML sin carga del operador + reserva del quant desincronizada:
        el saneo #caso-K43 debe seguir detectándola (el fix no lo apaga).
        Disponibilidad completa: con disponibilidad parcial la cantidad difiere
        de la demanda y el saneo se omite a propósito (#caso-K41-K42)."""
        so, out = self._new_out(ml=True, demand={self.p_eo: 150.0, self.p_cp: 390.0})
        self.env.flush_all() if hasattr(self.env, 'flush_all') else self.env['base'].flush()
        self.env.cr.execute(
            "UPDATE stock_quant SET reserved_quantity = 0 WHERE product_id = %s AND location_id = %s",
            (self.p_eo.id, self.stock_loc.id))
        self.env.invalidate_all() if hasattr(self.env, 'invalidate_all') else self.env['base'].invalidate_cache()
        with self.assertLogs(LOGGER, level=logging.WARNING) as cm:
            out._meli_heal_phantom_reserve()
        self.assertTrue(any('reserva fantasma detectada' in m and 'EO.PVCBL' in m for m in cm.output),
                        cm.output)
        self.assertFalse(any('DK.CP' in m for m in cm.output),
                         "el no almacenable no debe marcarse como fantasma")
