# -*- coding: utf-8 -*-
"""26.309 (caso-K02 cliente H) -- notificacion de una venta BLOQUEADA (`meli_update_forbidden`).

Antes: orders_update_order_json devolvia "Forbidden to upate by meli_oerp" => noti FAILED +
ERROR en el log; cron_process_order_notifications toma RECEIVED **y FAILED** => la misma
notificacion se reprocesaba en cada corrida, para siempre (caso-K02: 60-99/h, 131-238/h tras 26.294).
Ahora: SKIP no reintentable => SUCCESS, log INFO, y el cron no la vuelve a tomar.
Sin red: ML y la importacion se simulan. Control (origin sin el fix): test_1 y test_2 FALLAN.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from .test_binder_wizard import TestBinderWizard

RESOURCE = '/orders/2000417744122917'
LOGGER = 'odoo.addons'  # el modulo loguea con un logger propio; se mira todo odoo.addons


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli:
    access_token = 'TEST'

    def get(self, path, params=None, **kw):
        return _Resp({'id': 2000417744122917, 'status': 'paid'})

    def need_login(self):
        return False


@tagged('post_install', '-at_install', 'meli', 'meli_26309')
class TestNotiVentaBloqueada(TransactionCase):

    _crear_minimo = TestBinderWizard._crear_minimo
    _cuenta = TestBinderWizard._cuenta

    def setUp(self):
        super().setUp()
        self.account = self._cuenta()
        self.calls = []
        test = self

        def fake_update(orders_self, data=None, meli=None, config=None, **kw):
            test.calls.append(data and data.get('order_json', {}).get('id'))
            return {'error': 'Forbidden to upate by meli_oerp', 'meli_update_forbidden': True}

        p = patch.object(type(self.env['mercadolibre.orders']), 'orders_update_order_json', fake_update)
        p.start()
        self.addCleanup(p.stop)
        # el cron commitea por orden: en el test alcanza con flush
        p2 = patch.object(self.env.cr, 'commit', lambda *a: self.env.flush_all())
        p2.start()
        self.addCleanup(p2.stop)

    def _noti(self):
        return self.env['mercadolibre.notification'].create({
            'resource': RESOURCE, 'notification_id': 'T-26309', 'topic': 'orders_v2',
            'connection_account': self.account.id, 'state': 'RECEIVED'})

    def test_1_noti_queda_success_sin_error(self):
        noti = self._noti()
        with self.assertNoLogs(LOGGER, level='ERROR'):
            noti._process_notification_order(meli=_FakeMeli())
        self.assertEqual(self.calls, [2000417744122917], "se proceso la notificacion")
        self.assertEqual(noti.state, 'SUCCESS', noti.processing_errors)

    def test_2_el_cron_no_la_reintenta(self):
        self._noti()
        self.account.cron_process_order_notifications(meli=_FakeMeli(), limit=10)
        self.assertEqual(len(self.calls), 1)
        self.account.cron_process_order_notifications(meli=_FakeMeli(), limit=10)
        self.account.cron_process_order_notifications(meli=_FakeMeli(), limit=10)
        self.assertEqual(len(self.calls), 1, "la notificacion de una venta bloqueada no se reprocesa")

    def test_3_texto_viejo_sin_marca_tambien(self):
        """meli_oerp anterior (sin la marca en el retorno): se reconoce por el texto."""
        def old_update(orders_self, data=None, meli=None, config=None, **kw):
            return {'error': 'Forbidden to upate by meli_oerp'}
        noti = self._noti()
        with patch.object(type(self.env['mercadolibre.orders']), 'orders_update_order_json', old_update):
            noti._process_notification_order(meli=_FakeMeli())
        self.assertEqual(noti.state, 'SUCCESS')

    def test_4_un_error_real_sigue_failed(self):
        def bad_update(orders_self, data=None, meli=None, config=None, **kw):
            return {'error': 'orders_update_order_json > no pricelist defined'}
        noti = self._noti()
        with patch.object(type(self.env['mercadolibre.orders']), 'orders_update_order_json', bad_update):
            noti._process_notification_order(meli=_FakeMeli())
        self.assertEqual(noti.state, 'FAILED', "un fallo real se sigue reintentando")


@tagged('post_install', '-at_install', 'meli', 'meli_26309')
class TestFixStockStatusBatchSQL(TransactionCase):
    """26.309 (pedido MINT): en 26.308 el `# pylint: disable=sql-injection` quedo DENTRO del string
    SQL de fix_inconsistent_stock_status_batch => Postgres "syntax error at or near #" en cada corrida
    del cron de stock (savepoint del llamador: no aborta, pero el backfill 26.223 no corria nunca).
    Control (origin 26.308): falla con ProgrammingError."""

    _crear_minimo = TestBinderWizard._crear_minimo
    _cuenta = TestBinderWizard._cuenta

    def test_1_el_sql_corre(self):
        account = self._cuenta()
        with self.assertNoLogs('odoo.sql_db', level='ERROR'):
            res = account.fix_inconsistent_stock_status_batch(limit=5)
        self.assertEqual(set(res), {'fixed', 'fixed_ids', 'remaining', 'limit'})
        self.assertEqual(res['limit'], 5)
