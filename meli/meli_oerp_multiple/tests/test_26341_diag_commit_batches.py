# -*- coding: utf-8 -*-
"""26.341 (26.190 re-portado, #caso-K59 caso-K30) -- lado meli_oerp_multiple.

- El cron dedicado "Meli Stock Diagnostic" pide al diagnostico commit por lote
  (commit_batches=True) y el resumen de la ejecucion informa los pendientes para la proxima
  corrida (presupuesto por corrida de meli_oerp).
- 'revision_under_review' es recuperable: el binding vuelve a la cola de stock (acotado por
  el tope de reintentos) en vez de quedar varado para siempre.
Sin red.
"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


class _FakeMeli(object):
    access_token = 'TOKEN-341'
    seller_id = 341


@tagged('post_install', '-at_install', 'meli_26341')
class TestDiagCommitBatches(TransactionCase):

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
        self.company = self.env.company
        self.account.write({'configuration': self.conf.id, 'company_id': self.company.id})
        for rec in (self.conf, self.company):
            rec.write({'mercadolibre_cron_post_update_stock': True})

    def test_1_cron_pide_commit_por_lote_y_reporta_pendientes(self):
        calls = []
        ends = []
        Company = type(self.env['res.company'])
        Account = type(self.account)

        def _diag(rec, meli=False, reactivate=None, commit_batches=False):
            calls.append({'meli': meli, 'commit_batches': commit_batches})
            return {'items_to_check': 45, 'items_checked_ok': 20, 'api_errors': 0,
                    'items_processed': 20, 'items_deferred': 25, 'actions_taken': 3,
                    'elapsed_seconds': 1.0, 'diag_state': 'success'}

        def _end(rec, execution, **kw):
            if rec.id == self.account.id:
                ends.append(kw)

        fake = _FakeMeli()
        with patch.object(type(self.env['meli.util']), 'get_new_instance', return_value=fake), \
                patch.object(Company, 'meli_stock_diagnostic', _diag), \
                patch.object(Account, '_end_cron_execution', _end), \
                patch.object(self.env.cr, 'commit', lambda *a: None):
            # (el cron commitea tras _start_cron_execution: en 16/17 eso rompe el savepoint del test)
            self.env['mercadolibre.account'].cron_meli_stock_diagnostic()
        self.assertTrue(calls, "el cron no llamo al diagnostico (control)")
        self.assertTrue(all(c['commit_batches'] is True for c in calls), calls)
        self.assertIs(calls[0]['meli'], fake, "se consulta con la sesion de ESTA cuenta")
        self.assertEqual(len(ends), 1, ends)
        self.assertIn('pendientes proxima corrida: 25', ends[0].get('log_summary') or '', ends[0])
        self.assertEqual(ends[0].get('state'), 'success')

    def test_2_revision_under_review_vuelve_a_la_cola(self):
        self.assertIn('revision_under_review', type(self.account)._MELI_STOCK_RECOVERABLE_STATUS)
        tipo = {'type': 'consu', 'is_storable': True} if 'is_storable' in self.env['product.template']._fields else {'type': 'product'}
        prod = self.env['product.product'].create(dict(tipo, name='TUR341', default_code='TUR341'))
        try:
            bind = self._crear_minimo('mercadolibre.product', {
                'product_id': prod.id, 'connection_account': self.account.id,
                'conn_id': 'MLM932395110', 'meli_id': 'MLM932395110'})
        except Exception as e:
            self.skipTest("No se pudo armar la vinculacion en esta base: %s" % e)
        self.env.flush_all()
        self.env.cr.execute("""
            UPDATE mercadolibre_product
               SET meli_stock_status = 'revision_under_review', meli_last_status = 'under_review',
                   meli_stock_retry_count = 0, stock_error = NULL,
                   stock_update = (NOW() AT TIME ZONE 'UTC') - INTERVAL '2 days',
                   meli_stock_moves_update = (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day'
             WHERE id = %s""", (bind.id,))
        self.env['mercadolibre.product'].invalidate_model()
        self.account._meli_requeue_stranded_stock()
        self.env['mercadolibre.product'].invalidate_model()
        self.assertEqual(bind.meli_stock_status, 'update',
                         "un binding en revision_under_review tiene que volver a la cola de stock")
        self.assertEqual(bind.meli_stock_retry_count, 1)
