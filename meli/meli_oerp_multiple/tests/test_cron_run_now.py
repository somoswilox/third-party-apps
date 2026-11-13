# -*- coding: utf-8 -*-
"""Tests del "Ejecutar ahora" del panel CRONs de la cuenta ML (26.248, #caso-K29 cliente M).

Promesa: el botón ▶ de un CRON NO se pisa con el cron automático (si ya está
corriendo, avisa y no duplica, como "Ejecutar de forma manual" de ir.cron) y la
corrida queda registrada (historial + lastcall).

El "otro proceso" (scheduler / otro usuario) se simula con una conexión REAL a
la base (sql_db.db_connect), que es lo que hace el scheduler de Odoo.
"""

from unittest.mock import patch

from odoo import fields, sql_db
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'meli_K29')
class TestCronRunNow(TransactionCase):

    def _crear_minimo(self, model, _visitados=None):
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
                    rec = self._crear_minimo(f.comodel_name, _visitados)
                vals[name] = rec.id if rec else False
        return Model.create(vals)

    def setUp(self):
        super().setUp()
        cuenta = self.env['mercadolibre.account'].search([], limit=1)
        if not cuenta:
            try:
                cuenta = self._crear_minimo('mercadolibre.account')
            except Exception as e:
                self.skipTest("No se pudo obtener una mercadolibre.account: %s" % e)
        self.cuenta = cuenta
        cuenta.meli_cron_price_batch_running = False
        cuenta._ensure_cron_status()
        self.st_price = cuenta.cron_status_ids.filtered(lambda c: c.cron_type == 'price')[:1]
        self.st_orders = cuenta.cron_status_ids.filtered(lambda c: c.cron_type == 'orders')[:1]
        self.cron = self.env.ref('meli_oerp.ir_cron_module_cron_meli_process_post_price')
        self.Account = type(self.env['mercadolibre.account'])
        self.llamadas = []

    def _fake(self, res=None, durante=None, falla=False):
        test = self

        def _f(self_acc, *a, **kw):
            test.llamadas.append(self_acc.id)
            if durante:
                durante()
            if falla:
                raise ValueError('ML caido (test)')
            return res
        return _f

    def _otro_proceso(self):
        return sql_db.db_connect(self.env.cr.dbname).cursor()

    def _ejecuciones(self, cron_type):
        return self.env['mercadolibre.cron.execution'].search([
            ('connection_account', '=', self.cuenta.id), ('cron_type', '=', cron_type)])

    def _lastcall(self):
        self.env.cr.execute('SELECT lastcall FROM ir_cron WHERE id = %s', [self.cron.id])
        return self.env.cr.fetchone()[0]

    # ---------------------------------------------------------------- casos
    def test_precio_corre_una_vez_registra_ejecucion_y_lastcall(self):
        antes = self._ejecuciones('price')
        lastcall_antes = self._lastcall()
        res_fake = {'items_processed': 80, 'items_success': 78, 'items_error': 2}
        with patch.object(self.Account, 'meli_update_remote_price', self._fake(res=res_fake)):
            res = self.st_price.action_run_now()
        self.assertEqual(self.llamadas, [self.cuenta.id])
        self.assertEqual(res['tag'], 'display_notification')
        nuevas = self._ejecuciones('price') - antes
        self.assertEqual(len(nuevas), 1, "la corrida manual tiene que quedar en el historial")
        self.assertEqual(nuevas.state, 'success')
        self.assertEqual((nuevas.items_processed, nuevas.items_error), (80, 2))
        self.assertNotEqual(self._lastcall(), lastcall_antes, "tiene que registrar lastcall en el ir.cron")

    def test_cron_corriendo_avisa_y_no_duplica(self):
        antes = self._ejecuciones('price')
        otro = self._otro_proceso()
        try:
            otro.execute('SELECT id FROM ir_cron WHERE id = %s FOR NO KEY UPDATE', [self.cron.id])
            with patch.object(self.Account, 'meli_update_remote_price', self._fake()):
                with self.assertRaises(UserError):
                    self.st_price.action_run_now()
        finally:
            otro.rollback()
            otro.close()
        self.assertEqual(self.llamadas, [], "no tiene que correr si el cron está corriendo")
        self.assertFalse(self._ejecuciones('price') - antes, "no tiene que registrar una corrida que no hizo")

    def test_lock_se_sostiene_toda_la_corrida(self):
        visto = {}

        def _durante():
            otro = self._otro_proceso()
            try:
                otro.execute('SELECT id FROM ir_cron WHERE id = %s FOR NO KEY UPDATE SKIP LOCKED',
                             [self.cron.id])
                visto['filas'] = otro.fetchall()
            finally:
                otro.rollback()
                otro.close()

        with patch.object(self.Account, 'meli_update_remote_price', self._fake(durante=_durante)):
            self.st_price.action_run_now()
        self.assertEqual(visto.get('filas'), [],
                         "el scheduler pudo tomar el cron a mitad de la corrida manual")

    def test_error_queda_registrado_y_no_toca_lastcall(self):
        antes = self._ejecuciones('price')
        lastcall_antes = self._lastcall()
        # try/except y NO assertRaises: el assertRaises de Odoo revierte su
        # savepoint y se llevaría el registro de error que se quiere verificar.
        levanto = False
        with patch.object(self.Account, 'meli_update_remote_price', self._fake(falla=True)):
            try:
                self.st_price.action_run_now()
            except ValueError:
                levanto = True
        self.assertTrue(levanto, "el error del método tiene que propagarse")
        nuevas = self._ejecuciones('price') - antes
        self.assertEqual(nuevas.state, 'error')
        self.assertIn('ML caido', nuevas.error_message or '')
        self.assertEqual(self._lastcall(), lastcall_antes)

    def test_batch_de_precios_en_curso_no_corre(self):
        self.cuenta.meli_cron_price_batch_running = True
        with patch.object(self.Account, 'meli_update_remote_price', self._fake()):
            with self.assertRaises(UserError):
                self.st_price.action_run_now()
        self.assertEqual(self.llamadas, [])

    def test_tipo_que_se_registra_solo_no_duplica_registro(self):
        antes = self._ejecuciones('orders')
        with patch.object(self.Account, 'cron_meli_orders', self._fake()):
            self.st_orders.action_run_now()
        self.assertEqual(self.llamadas, [self.cuenta.id])
        self.assertFalse(self._ejecuciones('orders') - antes,
                         "orders registra su propia ejecución; run_now no tiene que agregar otra")

    def test_crons_incluye_el_individual(self):
        clon = self.cron.copy({'name': 'clon individual K29', 'active': False})
        self.st_price.write({'individual_cron_id': clon.id, 'cron_mode': 'individual'})
        crons, efectivo = self.cuenta._meli_ir_crons_for('price')
        self.assertIn(self.cron, crons)
        self.assertIn(clon, crons)
        self.assertEqual(efectivo, clon)

    # ------------------------------------------------ ajustes 26.248 (module-documenter)
    def test_metodo_de_precio_devuelve_resumen(self):
        """La tarjeta mostraba '0 items': el método devolvía {} (16/17/18)."""
        # flag apagado: no toca ML ni commitea; el contrato es el dict igual.
        (self.cuenta.configuration or self.cuenta.company_id).mercadolibre_cron_post_update_price = False
        res = self.cuenta.meli_update_remote_price(meli=object())
        self.assertIsInstance(res, dict)
        for k in ('items_processed', 'items_success', 'items_error'):
            self.assertIn(k, res)
            self.assertIsInstance(res[k], int)

    def test_precio_no_ofrece_cron_exclusivo(self):
        """Un clon individual de precios DUPLICA al global (los wrappers no miran cron_mode)."""
        crons_antes = self.env['ir.cron'].with_context(active_test=False).search_count([])
        res = self.st_price.action_set_individual()
        self.assertEqual(res['params']['type'], 'warning')
        self.assertEqual(self.env['ir.cron'].with_context(active_test=False).search_count([]), crons_antes)
        self.assertNotEqual(self.st_price.cron_mode, 'individual')

    def test_vista_no_muestra_exclusivo_en_precio(self):
        arch = self.env.ref('meli_oerp_multiple.view_connection_account_mercadolibre').arch_db
        self.assertNotIn("'products_get','price']", arch)
        self.assertIn("'products_get']", arch)

    # ------------------------------------------- 26.251: contador de la corrida de precio
    def _bindings(self, n):
        """n bindings de variante en la cuenta, con price_update vacio (van primero en la cola)."""
        Bind = self.env['mercadolibre.product']
        binds = Bind
        prod = self.env['product.product'].search([], limit=1) or self.env['product.product'].create({'name': 'TEST K29'})
        for k in range(n):
            mid = 'MLA9427%05d' % k
            vals = {'connection_account': self.cuenta.id, 'conn_id': mid, 'meli_id': mid,
                    'product_id': prod.id, 'price_update': False}
            try:
                b = Bind.create(vals)
            except Exception:
                b = self._crear_minimo('mercadolibre.product')
                b.write(vals)
            binds |= b
        return binds

    def test_corrida_de_precio_cuenta_exitos_y_rechazos(self):
        """cliente M 19-oct: 79 publicaciones, 62 aceptadas por ML ({}), 17 rechazadas
        (variations.not_updatable / item.price.not_modifiable). La ejecucion decia
        0 OK / 79 error porque `not resjson` trataba el {} del exito como error."""
        cfg = self.cuenta.configuration or self.cuenta.company_id
        cfg.mercadolibre_cron_post_update_price = True
        self.cuenta.meli_cron_price_top_commit = 5000
        self.cuenta.meli_cron_log_chatter = False
        binds = self._bindings(79)
        rechazadas = set(binds[:17].ids)
        Bind = type(self.env['mercadolibre.product'])

        def _post(bind_self, *a, **kw):
            if bind_self.id in rechazadas:
                return {'error': 'validation_error', 'status': 400,
                        'cause': [{'code': 'variations.not_updatable'}]}
            return {}

        with patch.object(Bind, 'product_post_price', _post):
            res = self.cuenta.meli_update_remote_price(meli=object())
        procesadas = res['items_processed']
        self.assertGreaterEqual(procesadas, 79)
        self.assertEqual(res['items_error'], 17, "solo los rechazos de ML son error")
        self.assertEqual(res['items_success'], procesadas - 17,
                         "el {} de product_post_price es un EXITO (antes: 0 OK)")

    def test_corrida_de_precio_none_sigue_siendo_error(self):
        """None/False = no se intento publicar: no puede sumar como OK."""
        cfg = self.cuenta.configuration or self.cuenta.company_id
        cfg.mercadolibre_cron_post_update_price = True
        self.cuenta.meli_cron_price_top_commit = 5000
        self.cuenta.meli_cron_log_chatter = False
        binds = self._bindings(3)
        Bind = type(self.env['mercadolibre.product'])
        nones = set(binds.ids)

        def _post(bind_self, *a, **kw):
            return None if bind_self.id in nones else {}

        with patch.object(Bind, 'product_post_price', _post):
            res = self.cuenta.meli_update_remote_price(meli=object())
        self.assertEqual(res['items_error'], 3)
        self.assertEqual(res['items_success'], res['items_processed'] - 3)

    @mute_logger('odoo.addons.meli_oerp_multiple.models.connection_binding')
    def test_excepcion_al_publicar_precio_no_es_exito(self):
        """_product_post_price_one tenia un `except: pass` que devolvia {}: con el
        contador corregido una excepcion habria contado como publicada."""
        bind = self._bindings(1)
        Prod = type(self.env['product.product'])

        def _boom(*a, **kw):
            raise ValueError('ML caido (test)')

        with patch.object(Prod, 'x_product_post_price', _boom), \
                patch.object(self.Account, '_meli_instance_or_mine', lambda s, m=None: object()):
            res = bind.product_post_price(meli=object())
        self.assertTrue(res and 'error' in res, res)
