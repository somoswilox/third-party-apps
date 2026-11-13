# -*- coding: utf-8 -*-
"""26.346 (#caso-KK52, 31-oct-2026): un error de BASE DE DATOS al crear/validar el cobro ML abortaba la
transaccion de confirm_ml y se perdia la venta entera.

Medido en produccion (Odoo 19 + talonarios de recibos ingadhoc): al numerar el asiento del cobro choca
`account_move_unique_name` (otro proceso carga el mismo talonario) => IntegrityError. `payment_post`
lo tragaba con `except: pass` SIN savepoint => transaccion abortada; el cleanup de duplicados fallaba
con 'current transaction is aborted' (tapando el error raiz) y la orden terminaba en KeyError + rollback.
El mismo camino aplica a bloqueos / serializacion concurrentes sobre account_move/account_payment.

Fix: cobro cliente, comision, envio y cleanup de duplicados van en `cr.savepoint()`; `payment_post`
valida cada paso en savepoint y PROPAGA los errores de base de datos (los funcionales se siguen
registrando y se continua como antes). Un choque CONCURRENTE (serializacion/deadlock/lock) tampoco
tira la venta: el cobro de cliente se reintenta tras el commit en una transaccion nueva.

Control: contra origin (sin el fix) los tests A, B, C y E fallan (transaccion abortada).
"""
import logging
from unittest.mock import patch

import psycopg2

from odoo import fields
from odoo.sql_db import db_connect
from odoo.tests import TransactionCase, tagged

from odoo.addons.meli_oerp.models import orders as meli_orders_mod
from ..models import versions as acc_versions

LOGGER = 'odoo.addons.meli_oerp_accounting.models.order'


@tagged('post_install', '-at_install', 'meli', 'meli_153')
class TestCobroSavepointK52(TransactionCase):

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
        self.co = self.env.company
        for f, v in (('mercadolibre_process_payments_customer', True),
                     ('mercadolibre_process_payments_supplier_fea', False),
                     ('mercadolibre_process_payments_supplier_shipment', False),
                     ('mercadolibre_notification_mode', 'internal_note')):
            if f in self.co._fields:
                self.co[f] = v
        self.partner = self.env['res.partner'].create({'name': 'Comprador ML K52'})
        self.product = self.env['product.product'].create({'name': 'Cafe K52', 'type': 'service'})
        # tabla con indice unico: el segundo INSERT reproduce un IntegrityError REAL de PostgreSQL
        self.env.cr.execute("CREATE TEMP TABLE tK52_unique (name varchar PRIMARY KEY)")
        self.env.cr.execute("INSERT INTO tK52_unique VALUES ('RE-X 0001-00000001')")
        # confirm_ml de meli_oerp (confirmar, stock, etc.) queda fuera: se prueba la parte contable
        p = patch.object(meli_orders_mod.sale_order, 'confirm_ml',
                         lambda self, meli=None, config=None: None)
        p.start()
        self.addCleanup(p.stop)
        self.n = 0

    def _venta(self):
        self.n += 1
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1.0, 'price_unit': 100.0})],
        })
        ml_id = '20006201654753%02d' % self.n
        try:
            mo = self._crear_minimo('mercadolibre.orders', {'order_id': ml_id, 'name': ml_id, 'sale_order': so.id})
            mp = self._crear_minimo('mercadolibre.payments', {
                'order_id': mo.id, 'payment_id': '153000%02d' % self.n, 'status': 'approved',
                'transaction_amount': 100.0, 'currency_id': self.co.currency_id.name})
        except Exception as e:
            self.skipTest("no se pudo crear la orden/pago ML en esta base: %s" % e)
        so.meli_orders = [(6, 0, [mo.id])]
        self.env.flush_all()
        return so, mp

    def _choque_de_numeracion(self):
        self.env.cr.execute("INSERT INTO tK52_unique VALUES ('RE-X 0001-00000001')")

    def _assert_transaccion_viva(self, so, partner_parcial=None):
        # si la transaccion quedo abortada, cualquier SQL falla con InFailedSqlTransaction
        self.env.cr.execute("SELECT id FROM sale_order WHERE id = %s", [so.id])
        self.assertEqual(self.env.cr.fetchone()[0], so.id, "la venta tiene que seguir creada")
        if partner_parcial:
            self.env.cr.execute("SELECT count(*) FROM res_partner WHERE name = %s", [partner_parcial])
            self.assertEqual(self.env.cr.fetchone()[0], 0, "lo escrito por el cobro fallido se revierte")
        # y el ORM sigue usable (escribir + leer)
        so.write({'note': 'post K52'})
        self.env.flush_all()

    def _chatter(self, so):
        return " || ".join(str(m.body) for m in so.message_ids if m.body)

    # ---------------------------------------------------------------- A
    def test_A_integrity_error_en_cobro_no_tira_la_venta(self):
        so, mp = self._venta()
        test = self

        def create_payment_que_choca(self, meli=None, config=None):
            # escritura parcial por ORM + choque de numeracion (como el receiptbook)
            self.env['res.partner'].create({'name': 'PARCIAL K52 A'})
            self.env.flush_all()
            test._choque_de_numeracion()

        with patch.object(type(mp), 'create_payment', create_payment_que_choca), \
                self.assertLogs(LOGGER, level='ERROR') as logs:
            so.confirm_ml(config=self.co)
        self._assert_transaccion_viva(so, 'PARCIAL K52 A')
        txt = '\n'.join(logs.output)
        self.assertIn('duplicate key', txt, "se loguea el error RAIZ, no 'transaction is aborted'")
        self.assertNotIn('current transaction is aborted', txt)
        self.assertIn('Error creando pago', self._chatter(so))

    # ---------------------------------------------------------------- B
    def test_B_lock_concurrente_en_cobro_no_tira_la_venta(self):
        """Lock REAL: un segundo cursor (otra transaccion, como la migracion de facturas/pagos) tiene
        tomada la fila; el cobro espera lock_timeout y falla con LockNotAvailable."""
        so, mp = self._venta()
        other = db_connect(self.env.cr.dbname).cursor()
        self.addCleanup(other.close)
        other.execute("SET lock_timeout = '5s'")
        # fila YA COMMITEADA antes del test (visible para su snapshot) y que nada del test referencia
        # por FK (una FK toma FOR KEY SHARE y el FOR UPDATE de abajo esperaria al propio test)
        other.execute("SELECT id FROM res_country WHERE code = 'AQ' FOR UPDATE")
        self.assertTrue(other.fetchone(), "falta el pais AQ en la base")
        self.addCleanup(self.env.cr.postcommit.clear)

        def create_payment_bloqueado(self, meli=None, config=None):
            self.env.cr.execute("SET LOCAL lock_timeout = '300ms'")
            self.env.cr.execute("UPDATE res_country SET write_date = write_date WHERE code = 'AQ'")

        with patch.object(type(mp), 'create_payment', create_payment_bloqueado), \
                self.assertLogs(LOGGER, level='WARNING') as logs:
            so.confirm_ml(config=self.co)
        other.rollback()
        self._assert_transaccion_viva(so)
        self.assertIn('lock timeout', '\n'.join(logs.output).lower())
        # choque concurrente: el cobro de cliente queda agendado para reintentarse tras el commit
        self.assertIn(mp.id, self.env.cr.postcommit.data.get('meli_153_replay_payments', set()))

    # ---------------------------------------------------------------- C
    def test_C_payment_post_propaga_el_error_de_bd_y_deja_la_transaccion_viva(self):
        test = self

        class Fake:
            env = self.env

            def action_post(self_):
                test._choque_de_numeracion()

            def action_validate(self_):
                raise AssertionError("no deberia llegar: el error de BD corta antes")

        with self.assertRaises(psycopg2.Error):
            acc_versions.payment_post(Fake())
        self.env.cr.execute("SELECT 1")
        self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_C2_payment_post_sigue_con_errores_funcionales(self):
        if 'K52' not in (acc_versions.payment_post.__doc__ or ''):
            self.skipTest("16.0: payment_post propaga todo (return action_post()); lo atrapa el savepoint de confirm_ml")
        llamados = []

        class Fake:
            env = self.env

            def action_post(self_):
                llamados.append('post')
                from odoo.exceptions import UserError
                raise UserError("ya publicado")

            def action_validate(self_):
                llamados.append('validate')

        acc_versions.payment_post(Fake())
        self.assertEqual(llamados, ['post', 'validate'])

    # ---------------------------------------------------------------- D
    def test_D_cleanup_de_duplicados_en_savepoint(self):
        so, mp = self._venta()
        test = self

        def cleanup_que_choca(self, meli_order, config=None):
            test._choque_de_numeracion()

        with patch.object(type(mp), 'create_payment', lambda self, meli=None, config=None: None), \
                patch.object(type(so), '_cleanup_duplicate_customer_payments', cleanup_que_choca), \
                self.assertLogs(LOGGER, level='ERROR') as logs:
            so.confirm_ml(config=self.co)
        self._assert_transaccion_viva(so)
        self.assertIn('cleanup de pagos duplicados', '\n'.join(logs.output))

    # ---------------------------------------------------------------- E
    def test_E_cobro_real_con_validacion_que_choca(self):
        """create_payment VERDADERO (diario, metodo, account.payment) y action_post que choca al
        numerar: el account.payment creado se revierte y el vinculo queda vacio (antes: KeyError)."""
        if not self.env['account.account'].search([('account_type', '=', 'asset_receivable')], limit=1):
            self.skipTest("sin plan de cuentas en esta base")
        acc_vals = {'name': 'Cobros ML K52', 'code': '1526153', 'account_type': 'asset_current', 'reconcile': True}
        if 'company_ids' in self.env['account.account']._fields:
            acc_vals['company_ids'] = [(6, 0, [self.co.id])]
        else:
            acc_vals['company_id'] = self.co.id
        cuenta = self.env['account.account'].create(acc_vals)
        manual = self.env.ref('account.account_payment_method_manual_in')
        journal = self.env['account.journal'].create({
            'name': 'MP-MELI K52', 'code': 'MK52', 'type': 'bank', 'company_id': self.co.id})
        journal.inbound_payment_method_line_ids = [(5, 0, 0), (0, 0, {
            'name': 'Pago manual', 'payment_method_id': manual.id, 'payment_account_id': cuenta.id})]
        self.co.mercadolibre_process_payments_journal = journal
        if 'mercadolibre_payment_receipt_validation' in self.co._fields:
            self.co.mercadolibre_payment_receipt_validation = 'validate'
        so, mp = self._venta()
        test = self

        def action_post_que_choca(self):
            test._choque_de_numeracion()

        with patch.object(type(self.env['account.payment']), 'action_post', action_post_que_choca):
            so.confirm_ml(config=self.co)
        self._assert_transaccion_viva(so)
        mp.invalidate_recordset()
        self.assertFalse(mp.account_payment_id, "el cobro fallido se revierte entero (se reintenta en la proxima actualizacion)")
        self.assertFalse(self.env['account.payment'].search([('journal_id', '=', journal.id)]))
        self.assertIn('Error creando pago', self._chatter(so))
