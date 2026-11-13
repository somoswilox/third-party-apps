# -*- coding: utf-8 -*-
"""FIX un caso v2 (un cliente, 28-sep-2026) — regresión del savepoint de meli_deliver.

Caso de producción: `button_validate` falla por stock_no_negative ("would become
negative") DESPUÉS de haber escrito el quant. `meli_deliver` atrapaba la excepción
sin savepoint y el `cr.commit()` del barrido persistía la escritura parcial: el
stock bajaba sin ningún move done, y el barrido lo contaba como "cerrado".

Simulación: se envuelve `stock.picking._action_done` para que haga TODO el trabajo
real (moves done, quant descontado) y recién después levante ValidationError. Es
un fallo más tardío —y por lo tanto más dañino— que el de stock_no_negative: si el
savepoint revierte esto, revierte también el caso real.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'meli_oerp_stock')
class TestMeliDeliverSavepoint(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Product = env['product.product']
        vals = {'name': 'MELI savepoint test', 'type': 'consu'}
        if 'is_storable' in Product._fields:
            vals['is_storable'] = True
        else:
            vals['type'] = 'product'
        cls.product = Product.create(vals)
        cls.warehouse = env['stock.warehouse'].search(
            [('company_id', '=', env.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        env['stock.quant']._update_available_quantity(cls.product, cls.stock_loc, 5.0)
        cls.partner = env['res.partner'].create({'name': 'Comprador'})

    def _new_order(self, qty=3.0):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'price_unit': 10.0,
            })],
        })
        so.action_confirm()
        out = so.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')
        self.assertTrue(out, "la venta debe generar una salida")
        return so, out

    def _qty_on_hand(self):
        self.env.invalidate_all()
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product.id),
            ('location_id', '=', self.stock_loc.id)])
        return sum(quants.mapped('quantity'))

    def _failing_action_done(self):
        Picking = type(self.env['stock.picking'])
        orig = Picking._action_done

        test = self

        def _action_done(recs, *args, **kwargs):
            res = orig(recs, *args, **kwargs)  # escribe el quant y marca los moves done
            if not recs:
                # button_validate llama _action_done también sobre el grupo vacío
                # (pickings_not_to_backorder / to_backorder): ese no es el fallo.
                return res
            # control positivo: el daño SÍ ocurrió dentro de la transacción
            quants = recs.env['stock.quant'].search([
                ('product_id', '=', test.product.id),
                ('location_id', '=', test.stock_loc.id)])
            test.qty_inside_failed_validate = sum(quants.mapped('quantity'))
            test.states_inside_failed_validate = recs.mapped('state')
            raise ValidationError("simulado: the stock would become negative")
        return patch.object(Picking, '_action_done', _action_done)

    def test_01_failed_validate_leaves_quant_untouched(self):
        so, out = self._new_order()
        self.assertEqual(self._qty_on_hand(), 5.0)
        with self._failing_action_done(), self.assertLogs('odoo.addons.meli_oerp_stock.models.order', level='WARNING'):
            res = so.meli_deliver(config=self.env.company)
        self.assertTrue(res.get('errors'), "el fallo debe quedar en res['errors']")
        # control positivo: la simulación descontó el quant antes de fallar
        self.assertEqual(self.qty_inside_failed_validate, 2.0)
        self.assertEqual(self.states_inside_failed_validate, ['done'])
        self.env.cr.flush()
        self.assertEqual(self._qty_on_hand(), 5.0,
                         "un button_validate que falla NO puede dejar el quant descontado")
        self.assertNotEqual(out.state, 'done')
        self.assertFalse(out.move_ids.filtered(lambda m: m.state == 'done'))

    def _sweep(self, so):
        SO = type(self.env['sale.order'])
        with patch.object(SO, '_meli_sweep_config', lambda rec: rec.company_id), \
                patch.object(SO, '_meli_delivery_on_delivered_enabled', lambda rec, cfg: True):
            return self.env['sale.order']._meli_close_delivered_process(so, commit=False)

    def test_02_sweep_counts_error_and_stamps_attempt(self):
        so, out = self._new_order()
        with self._failing_action_done(), self.assertLogs('odoo.addons.meli_oerp_stock.models.order', level='WARNING'):
            result = self._sweep(so)
        self.assertEqual(result['processed'], 0, "un pedido con errores NO es 'cerrado'")
        self.assertEqual(result['errors'], 1)
        self.assertIn(so.id, result['failed_order_ids'])
        self.assertTrue(so.meli_close_attempt_date, "el intento se sella para rotar el lote")
        self.assertEqual(self._qty_on_hand(), 5.0)
        self.assertNotEqual(out.state, 'done')

    def test_03_sweep_closes_when_validate_succeeds(self):
        so, out = self._new_order()
        result = self._sweep(so)
        self.assertEqual((result['processed'], result['errors']), (1, 0))
        self.assertEqual(out.state, 'done')
        self.assertEqual(self._qty_on_hand(), 2.0)
        self.assertTrue(so.meli_close_attempt_date)

    def test_04_params_fall_back_to_defaults(self):
        SO = self.env['sale.order']
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(SO._MELI_CLOSE_DAYS_PARAM, 'basura')
        with self.assertLogs('odoo.addons.meli_oerp_stock.models.order', level='WARNING'):
            self.assertEqual(SO._meli_close_param(SO._MELI_CLOSE_DAYS_PARAM, 180), 180)
        ICP.set_param(SO._MELI_CLOSE_DAYS_PARAM, '400')
        self.assertEqual(SO._meli_close_param(SO._MELI_CLOSE_DAYS_PARAM, 180), 400)

    def test_05_candidates_domain_and_cron_run(self):
        """El dominio de candidatos (prefiltro de pickings abiertos + ventana de
        reintento) es SQL válido y el cron sin pedidos ML no procesa nada."""
        SO = self.env['sale.order']
        todo, n = SO._meli_close_delivered_candidates(180, 100)
        self.assertFalse(todo)
        self.assertEqual(n, 0)
        result = SO.cron_meli_close_delivered_pickings()
        self.assertEqual((result['processed'], result['errors']), (0, 0))
