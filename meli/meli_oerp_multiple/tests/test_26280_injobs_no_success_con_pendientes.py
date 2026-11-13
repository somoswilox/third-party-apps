# -*- coding: utf-8 -*-
"""#caso-K30 (22-oct-2026): el job diferido de stock de una entrada grande (OV/IN/05802,
112 productos) se cayo por `could not serialize access` (40001) y el except externo de
meli_update_remote_stock_injobs lo dejo en SUCCESS con 0/112 procesados y sin errores:
la entrada nunca llego a Mercado Libre y nada lo mostraba.

Ademas, con model_ids_step vacio (0) el ciclo cortaba en el primer punto de control
(5 vinculaciones por ciclo de 5 min).

Sin red: product_post_stock y meli.util quedan parcheados.
"""
import json
import threading
import uuid
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


class _SerializationError(Exception):
    pgcode = '40001'


@tagged('post_install', '-at_install', 'meli_26280')
class TestInjobsNoSuccessConPendientes(TransactionCase):

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
        try:
            self.conf = self._crear_minimo('mercadolibre.configuration')
            self.account = self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("No se pudo armar cuenta/configuracion en esta base: %s" % e)
        self.account.write({'configuration': self.conf.id, 'company_id': self.env.company.id})
        self.conf.write({'mercadolibre_cron_post_update_stock': True})
        self.p1 = self.env['product.product'].create({'name': 'INJK30 A', 'default_code': 'INJK30A'})
        self.p2 = self.env['product.product'].create({'name': 'INJK30 B', 'default_code': 'INJK30B'})

    def _job(self, processed=None, attempts=1):
        return self.env['mercadolibre.notification'].create({
            'notification_id': 'i-testK30-%s' % uuid.uuid4().hex,
            'topic': 'internal_job',
            'resource': 'meli_update_remote_stock_deferred #2 products',
            'connection_account': self.account.id,
            'model_ids': json.dumps([self.p1.id, self.p2.id]),
            'model_ids_processed': json.dumps(processed) if processed is not None else False,
            'state': 'RECEIVED',
            'attempts': attempts,
        })

    # -- tope por paso ------------------------------------------------------------------
    def test_step_vacio_no_corta_el_ciclo(self):
        A = self.account
        self.assertFalse(A._meli_injobs_step_reached(5, 0, 181))
        self.assertFalse(A._meli_injobs_step_reached(5, False, 181))
        self.assertTrue(A._meli_injobs_step_reached(10, 10, 181))
        self.assertFalse(A._meli_injobs_step_reached(181, 10, 181))

    # -- cierre ante excepcion -----------------------------------------------------------
    def test_40001_con_pendientes_vuelve_a_received(self):
        job = self._job(processed=[self.p1.id])
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.connection_account', level='WARNING'):
            state = self.account._meli_injobs_job_failed(job, _SerializationError("could not serialize access"),
                                                         auto_commit=False)
        self.assertEqual(state, 'RECEIVED')
        self.assertEqual(job.state, 'RECEIVED')
        self.assertEqual(job.attempts, 2)
        self.assertIn('40001', job.processing_errors or '')
        self.assertIn('pendientes 1/2', job.processing_errors or '')

    def test_sin_pendientes_sigue_siendo_success(self):
        job = self._job(processed=[self.p1.id, self.p2.id])
        state = self.account._meli_injobs_job_failed(job, _SerializationError("x"), auto_commit=False)
        self.assertEqual(state, 'SUCCESS')
        self.assertEqual(job.state, 'SUCCESS')

    def test_agotados_los_reintentos_queda_failed_no_success(self):
        self.env['ir.config_parameter'].sudo().set_param('meli_oerp_multiple.injobs_max_retries', 2)
        job = self._job(processed=[], attempts=3)
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.connection_account', level='WARNING'):
            state = self.account._meli_injobs_job_failed(job, ValueError("boom"), auto_commit=False)
        self.assertEqual(state, 'FAILED')
        self.assertEqual(job.state, 'FAILED')
        self.assertIn('boom', job.processing_errors or '')

    # -- camino real del cron -----------------------------------------------------------
    def test_injobs_40001_no_marca_success_con_0_procesados(self):
        """El caso de prod: el 1er push revienta con 40001 -> antes SUCCESS 0/2, ahora RECEIVED."""
        MP = self.env['mercadolibre.product']
        try:
            for p, mid in ((self.p1, 'MLMTEST4751'), (self.p2, 'MLMTEST4752')):
                vals = {'product_id': p.id, 'conn_id': mid, 'connection_account': self.account.id}
                if 'meli_id' in MP._fields:
                    vals['meli_id'] = mid
                self._crear_minimo('mercadolibre.product', vals)
        except Exception as e:
            self.skipTest("No se pudo armar la vinculacion en esta base: %s" % e)
        job = self._job(processed=None)
        # el modulo decide auto_commit por threading.current_thread().testing (en 19 no siempre esta)
        with patch.object(threading.current_thread(), 'testing', True, create=True), \
                patch.object(type(MP), 'product_post_stock', side_effect=_SerializationError("could not serialize access")), \
                self.assertLogs('odoo.addons.meli_oerp_multiple.models.connection_account', level='WARNING'):
            self.account.meli_update_remote_stock_injobs(meli=object(), notification=job)
        self.assertNotEqual(job.state, 'SUCCESS', "un job con 0/2 procesados no puede quedar SUCCESS")
        self.assertEqual(job.state, 'RECEIVED')
        self.assertIn('40001', job.processing_errors or '')
