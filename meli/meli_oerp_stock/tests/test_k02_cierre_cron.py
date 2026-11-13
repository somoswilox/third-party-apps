# -*- coding: utf-8 -*-
"""[caso-K02, 26.307] Cron "Cerrar Entregas Entregadas": recurrente y con fallas por stock calladas.

Caso de producción (caso-K02 cliente H, 25-oct-2026, pase 26.294): el cron 194 corrió UNA vez y quedó
`numbercall=0, active=False` — el XML de 16/17 no declaraba `numbercall` (default 1). En esa única
corrida 46 pedidos fallaron por falta de stock y cada uno dejó ERROR + traceback en el log.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

LOGGER = 'odoo.addons.meli_oerp_stock.models.order'


@tagged('post_install', '-at_install', 'meli_K02_cierre')
class TestMeliK02CierreCron(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Product = env['product.product']
        vals = {'name': 'MELI K02 cierre', 'type': 'consu'}
        if 'is_storable' in Product._fields:
            vals['is_storable'] = True
        else:
            vals['type'] = 'product'
        cls.product = Product.create(vals)
        cls.warehouse = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
        env['stock.quant']._update_available_quantity(cls.product, cls.warehouse.lot_stock_id, 5.0)
        cls.partner = env['res.partner'].create({'name': 'Comprador K02'})
        cls.cron = env.ref('meli_oerp_stock.ir_cron_meli_close_delivered_pickings').with_context(active_test=False)

    # --- recurrencia -------------------------------------------------------------------------
    def test_01_cron_instalado_es_recurrente(self):
        self.assertTrue(self.cron.active)
        if 'numbercall' in self.cron._fields:
            self.assertEqual(self.cron.numbercall, -1, "16/17: sin numbercall=-1 el cron corre UNA vez")
        else:
            self.assertFalse(self.env['sale.order']._meli_close_delivered_cron_repair(),
                             "18+: no existe numbercall, la reparación es no-op")

    def test_02_reparacion_reactiva_el_agotado_por_odoo(self):
        if 'numbercall' not in self.cron._fields:
            self.skipTest("18+ no tiene numbercall")
        self.cron.write({'numbercall': 0, 'active': False})   # estado medido en caso-K02 (cron 194)
        res = self.env['sale.order']._meli_close_delivered_cron_repair()
        self.assertEqual(res, {'numbercall': -1, 'active': True})
        self.assertEqual((self.cron.numbercall, self.cron.active), (-1, True))
        self.assertFalse(self.env['sale.order']._meli_close_delivered_cron_repair(), "idempotente")

    def test_03_reparacion_respeta_el_apagado_a_mano(self):
        if 'numbercall' not in self.cron._fields:
            self.skipTest("18+ no tiene numbercall")
        self.cron.write({'numbercall': 1, 'active': False})   # apagado por un usuario antes de correr
        self.env['sale.order']._meli_close_delivered_cron_repair()
        self.assertEqual((self.cron.numbercall, self.cron.active), (-1, False))

    # --- fallas por regla de negocio ---------------------------------------------------------
    def _order(self):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'warehouse_id': self.warehouse.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 2.0, 'price_unit': 10.0})],
        })
        so.action_confirm()
        return so

    def _sweep(self, so, exc):
        Picking = type(self.env['stock.picking'])
        SO = type(self.env['sale.order'])

        def _boom(recs, *a, **k):
            if recs:
                raise exc
            return True
        with patch.object(Picking, '_action_done', _boom), \
                patch.object(SO, '_meli_sweep_config', lambda rec: rec.company_id), \
                patch.object(SO, '_meli_delivery_on_delivered_enabled', lambda rec, cfg: True):
            return self.env['sale.order']._meli_close_delivered_process(so, commit=False)

    def test_04_falta_de_stock_es_aviso_no_error(self):
        so = self._order()
        with self.assertLogs(LOGGER, level='WARNING') as cm:
            res = self._sweep(so, ValidationError("simulado: the stock would become negative"))
        self.assertEqual((res['processed'], res['errors'], res['blocked']), (0, 1, 1))
        self.assertIn(so.id, res['failed_order_ids'])
        self.assertTrue(so.meli_close_attempt_date, "se sella igual para que el lote rote")
        self.assertFalse([r for r in cm.records if r.levelname == 'ERROR'],
                         "falta de stock: sin ERROR ni traceback")
        self.assertTrue(any('regla de negocio' in r.getMessage() and so.name in r.getMessage()
                            for r in cm.records if r.levelname == 'WARNING'), "un resumen que nombra el pedido")

    def test_05_error_de_codigo_sigue_siendo_error(self):
        so = self._order()
        with self.assertLogs(LOGGER, level='WARNING') as cm:
            res = self._sweep(so, RuntimeError("simulado: bug"))
        self.assertEqual((res['errors'], res['blocked']), (1, 0))
        self.assertTrue([r for r in cm.records if r.levelname == 'ERROR'])
