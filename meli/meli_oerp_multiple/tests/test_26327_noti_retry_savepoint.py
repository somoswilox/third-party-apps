# -*- coding: utf-8 -*-
"""26.327 (caso-K02) -- un serialization error en el intento 1 descartaba la venta del intento 2.

Antes: `_process_notification_order` reintentaba con `cr.rollback()`. Eso tiraba la transaccion
entera, incluido el SAVEPOINT sp_noti_N que abre `cron_process_order_notifications`; el reintento
creaba la venta, el RELEASE del cron fallaba y su `except` hacia OTRO `cr.rollback()` suponiendo
que un commit interno ya la habia persistido (MeliCommit es flush_all: no commitea). La venta buena
se perdia. Ademas la guarda MELI_IMPORT_PARALLEL marcaba SUCCESS aunque la orden no existiera, y
nada la retomaba salvo el barrido (limit=10). Caso real caso-K02: orden 2000759997510062, 28-oct.
Ahora: savepoint por intento, RELEASE protegido, guarda paralela sin orden => RECEIVED.
Sin red: ML y la importacion se simulan; el "serialization" deja la transaccion ABORTADA como el real.
Control (origin 26.326 + este test, de a uno): test_1/2/3/5 FALLAN; test_4 pasa (control positivo).
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from .test_binder_wizard import TestBinderWizard

OID = 2000546550373864
RESOURCE = '/orders/%d' % OID
# los reintentos por serialization loguean WARNING (y ERROR al agotarse): son el escenario, se verifican con assertLogs
NOTI_LOGGER = 'odoo.addons.meli_oerp_multiple.models.connection_notification'


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli:
    access_token = 'TEST'

    def get(self, path, params=None, **kw):
        return _Resp({'id': OID, 'status': 'paid'})

    def need_login(self):
        return False


@tagged('post_install', '-at_install', 'meli', 'meli_26327_noti_retry')
class TestNotiRetrySavepoint(TransactionCase):

    _crear_minimo = TestBinderWizard._crear_minimo
    _cuenta = TestBinderWizard._cuenta

    def setUp(self):
        super().setUp()
        self.account = self._cuenta()
        # el cron toma TODAS las pendientes de la cuenta: se aislan las que ya hubiera en la base
        self.env['mercadolibre.notification'].search(
            [('state', 'in', ['RECEIVED', 'FAILED'])]).write({'state': 'SUCCESS'})
        self.partner = self.env['res.partner'].create({'name': 'Comprador 26327'})
        self.calls = []
        self.fallar = 1          # cuantos intentos fallan con serialization
        self.respuesta = None    # retorno de orders_update_order_json en el intento bueno
        test = self

        def fake_update(orders_self, data=None, meli=None, config=None, **kw):
            n = len(test.calls) + 1
            test.calls.append(n)
            if test.respuesta is not None:
                return test.respuesta
            # el trabajo del intento: la venta, escrita en la base (no solo en cache)
            orders_self.env['sale.order'].create({
                'partner_id': test.partner.id, 'client_order_ref': 'ML-26327-intento-%d' % n})
            orders_self.env.flush_all()
            if n <= test.fallar:
                # un serialization real deja la transaccion PG abortada: se reproduce eso
                try:
                    orders_self.env.cr.execute('SELECT 1/0', log_exceptions=False)
                except Exception:
                    pass
                raise Exception('could not serialize access due to concurrent update')
            return {'ok': True}

        p = patch.object(type(self.env['mercadolibre.orders']), 'orders_update_order_json', fake_update)
        p.start()
        self.addCleanup(p.stop)
        # el cron commitea por orden: en el test alcanza con flush (como test_26309)
        p2 = patch.object(self.env.cr, 'commit', lambda *a: self.env.flush_all())
        p2.start()
        self.addCleanup(p2.stop)
        p3 = patch('time.sleep', lambda *a: None)
        p3.start()
        self.addCleanup(p3.stop)

    def _noti(self):
        return self.env['mercadolibre.notification'].create({
            'resource': RESOURCE, 'notification_id': 'T-26327', 'topic': 'orders_v2',
            'connection_account': self.account.id, 'state': 'RECEIVED'})

    def _ventas(self, n):
        return self.env['sale.order'].search([('client_order_ref', '=', 'ML-26327-intento-%d' % n)])

    def test_1_cron_serialization_en_intento_1_la_venta_persiste(self):
        noti = self._noti()
        with self.assertLogs(NOTI_LOGGER, level='WARNING') as logs:
            self.account.cron_process_order_notifications(meli=_FakeMeli(), limit=10)
        self.assertEqual([r.getMessage() for r in logs.records if 'retry' in r.getMessage()],
                         ['meli_oerp_multiple >> _process_notification_order >> serialization error, retry 1/3'])
        self.assertEqual(self.calls, [1, 2], "hubo reintento")
        self.assertTrue(self.account.exists(), "la transaccion del llamador sigue viva")
        self.assertTrue(noti.exists(), "la notificacion sigue existiendo")
        self.assertEqual(len(self._ventas(2)), 1, "la venta del intento bueno PERSISTE")
        self.assertFalse(self._ventas(1), "lo del intento fallido se revirtio")
        self.assertEqual(noti.state, 'SUCCESS', noti.processing_errors)

    def test_2_webhook_serialization_no_tira_la_transaccion(self):
        """Camino directo (webhook topic 'order'): la noti recien creada no se pierde."""
        noti = self._noti()
        with self.assertLogs(NOTI_LOGGER, level='WARNING') as logs:
            noti._process_notification_order(meli=_FakeMeli())
        self.assertTrue(any('retry 1/3' in m for m in logs.output), logs.output)
        self.assertTrue(noti.exists() and self.partner.exists())
        self.assertEqual(len(self._ventas(2)), 1)
        self.assertEqual(noti.state, 'SUCCESS', noti.processing_errors)

    def test_3_guarda_paralela_sin_orden_queda_reintentable(self):
        self.respuesta = {'error': 'MELI_IMPORT_PARALLEL: orden %d en importacion por otro proceso, '
                                   'se omite en esta pasada' % OID}
        noti = self._noti()
        noti._process_notification_order(meli=_FakeMeli())
        self.assertEqual(noti.state, 'RECEIVED', "sin mercadolibre.orders no puede quedar SUCCESS")
        self.assertIn('MELI_IMPORT_PARALLEL', noti.processing_errors or '')
        # y el cron la vuelve a tomar
        self.account.cron_process_order_notifications(meli=_FakeMeli(), limit=10)
        self.assertEqual(len(self.calls), 2, "el cron la retomo")

    def test_4_guarda_paralela_con_orden_sigue_success(self):
        orden = self._crear_minimo('mercadolibre.orders')
        orden.write({'order_id': str(OID)})
        self.respuesta = {'error': 'MELI_IMPORT_PARALLEL: orden %d ya importada por otro proceso' % OID}
        noti = self._noti()
        noti._process_notification_order(meli=_FakeMeli())
        self.assertEqual(noti.state, 'SUCCESS')

    def test_5_serialization_persistente_queda_failed_y_el_cron_la_retoma(self):
        self.fallar = 3
        noti = self._noti()
        with self.assertLogs(NOTI_LOGGER, level='WARNING') as logs:
            self.account.cron_process_order_notifications(meli=_FakeMeli(), limit=10)
        self.assertEqual(sum('retry' in m for m in logs.output), 2, logs.output)
        self.assertTrue(any(r.levelname == 'ERROR' and 'could not serialize' in r.getMessage()
                            for r in logs.records), logs.output)
        self.assertEqual(self.calls, [1, 2, 3])
        self.assertTrue(self.account.exists())
        self.assertEqual(noti.state, 'FAILED')
        self.assertFalse(self._ventas(1) | self._ventas(2) | self._ventas(3))
        self.fallar = 0
        self.account.cron_process_order_notifications(meli=_FakeMeli(), limit=10)
        self.assertEqual(len(self._ventas(4)), 1, "la proxima corrida la importa")
        self.assertEqual(noti.state, 'SUCCESS', noti.processing_errors)
