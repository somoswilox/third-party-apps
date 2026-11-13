# -*- coding: utf-8 -*-
# #caso-K07: la cola de notificaciones orders_v2 no puede dejar viejas postergadas.
from datetime import datetime, timedelta
from types import SimpleNamespace

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli', 'meli_26329')
class TestNotifQueue(TransactionCase):

    def _queue(self, n_new, n_old_received, n_old_failed):
        """{resource: [latest]} con n_new recientes, n_old_received viejas RECEIVED
        y n_old_failed viejas FAILED (reintentadas hace poco)."""
        base = datetime(2026, 10, 6, 12, 0, 0)
        q = {}
        for i in range(n_old_received):  # las mas viejas de todas
            q['old_r%d' % i] = [SimpleNamespace(
                received=base - timedelta(days=3) + timedelta(minutes=i),
                state='RECEIVED', write_date=base - timedelta(days=3))]
        for i in range(n_old_failed):
            q['old_f%d' % i] = [SimpleNamespace(
                received=base - timedelta(days=2) + timedelta(minutes=i),
                state='FAILED', write_date=base - timedelta(minutes=i))]
        for i in range(n_new):
            q['new%d' % i] = [SimpleNamespace(
                received=base - timedelta(minutes=i),
                state='RECEIVED', write_date=base)]
        return q

    def test_old_received_get_quota_under_heavy_traffic(self):
        acc = self.env['mercadolibre.account']
        picked = acc._pick_notification_orders(self._queue(50, 8, 0), 10)
        self.assertEqual(len(picked), 10)
        self.assertEqual([r for r in picked if r.startswith('old_r')],
                         ['old_r0', 'old_r1', 'old_r2', 'old_r3', 'old_r4'])
        self.assertEqual(picked[0], 'new0')  # las nuevas siguen primero

    def test_failed_do_not_starve_received_and_rotate(self):
        acc = self.env['mercadolibre.account']
        picked = acc._pick_notification_orders(self._queue(50, 2, 30), 10)
        # 5 nuevas; viejas: 2 RECEIVED y el resto del cupo (spill) a FAILED
        self.assertIn('old_r0', picked)
        self.assertIn('old_r1', picked)
        # cupo viejo 5 = 3 RECEIVED (las 2 viejas + la mas vieja del resto) + 2 FAILED
        self.assertEqual(len([r for r in picked if r.startswith('old_f')]), 2)
        self.assertIn('old_f29', picked)  # write_date mas antiguo
        self.assertIn('old_f28', picked)

    def test_small_queue_and_edges(self):
        acc = self.env['mercadolibre.account']
        self.assertEqual(len(acc._pick_notification_orders(self._queue(3, 0, 0), 10)), 3)
        self.assertEqual(acc._pick_notification_orders({}, 10), [])
        self.assertEqual(len(acc._pick_notification_orders(self._queue(5, 5, 0), 1)), 1)
