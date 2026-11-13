# -*- coding: utf-8 -*-
"""#caso-K02 (26.237 + 26.245): reintento de etiquetas de envios buffered.

1. Ventana: un envio creado hace mas de 'days' entra igual si ML lo libera dentro de la
   ventana (estimated_buffering_date reciente). Antes se caia por create_date justo
   cuando ML lo liberaba (CORFAM, finde largo).
2. Prioridad: con mas envios que 'limit', los que ML libera esta noche (fecha de
   liberacion vencida o dentro del margen) se miran antes que los pendientes mas nuevos.
   Antes iba por create_date DESC y los liberados viejos quedaban siempre afuera.
3. Rotacion: el resto se mira por write_date ASC (el que hace mas que no se refresca).

Sin red: solo se llaman los helpers de seleccion, no el cron.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli', 'meli_26272')
class TestLabelRetryK02(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Ship = self.env['mercadolibre.shipment']
        self.Acc = self.env['mercadolibre.account']
        if not hasattr(self.Acc, '_label_retry_candidates'):
            self.skipTest('sin reintento de etiquetas en esta version')
        f = self.Ship._fields.get('estimated_buffering_date')
        if not f:
            self.skipTest('sin estimated_buffering_date')
        self.buf_is_date = f.type == 'date'
        self.now = fields.Datetime.now()

    def _buf(self, dt):
        return dt.date() if self.buf_is_date else dt

    def _ship(self, name, status='pending', created_days_ago=0, buffering=None, written_days_ago=0):
        vals = {'shipping_id': name, 'status': status}
        if buffering is not None:
            vals['estimated_buffering_date'] = self._buf(buffering)
        s = self.Ship.create(vals)
        self.env.cr.execute(
            "UPDATE mercadolibre_shipment SET create_date=%s, write_date=%s WHERE id=%s",
            (self.now - timedelta(days=created_days_ago),
             self.now - timedelta(days=written_days_ago), s.id))
        s.invalidate_recordset() if hasattr(s, 'invalidate_recordset') else s.invalidate_cache()
        return s

    def test_window_counts_from_buffering_release(self):
        since = self.now - timedelta(days=3)
        viejo_liberado = self._ship('W1', created_days_ago=8, buffering=self.now)
        viejo_sin_fecha = self._ship('W2', created_days_ago=8)
        nuevo = self._ship('W3', created_days_ago=1)
        ids = (viejo_liberado | viejo_sin_fecha | nuevo).ids
        dom = [('id', 'in', ids)] + self.Acc._label_retry_window_domain(self.Ship, since)
        got = self.Ship.search(dom)
        self.assertIn(viejo_liberado, got, 'el envio liberado por ML dentro de la ventana tiene que entrar')
        self.assertIn(nuevo, got)
        self.assertNotIn(viejo_sin_fecha, got, 'el viejo sin liberacion sigue afuera')

    def test_released_tonight_beats_newer_pending(self):
        ready = self._ship('R1', status='ready_to_ship', created_days_ago=2)
        liberado = self._ship('D1', created_days_ago=3, buffering=self.now - timedelta(days=1))
        nuevos = self.Ship.browse()
        for i in range(4):
            nuevos |= self._ship('N%d' % i, created_days_ago=0)
        futuro = self._ship('F1', created_days_ago=0, buffering=self.now + timedelta(days=5))
        base = [('id', 'in', (ready | liberado | nuevos | futuro).ids)]
        got = self.Acc._label_retry_candidates(self.Ship, base, 2)
        self.assertEqual(len(got), 2)
        self.assertIn(ready, got, 'grupo 1: imprimible primero')
        self.assertIn(liberado, got, 'grupo 2: el que ML libera esta noche antes que los nuevos pendientes')

    def test_rest_rotates_by_write_date(self):
        reciente = self._ship('X1', created_days_ago=0, written_days_ago=0)
        olvidado = self._ship('X2', created_days_ago=0, written_days_ago=4)
        medio = self._ship('X3', created_days_ago=0, written_days_ago=2)
        base = [('id', 'in', (reciente | olvidado | medio).ids)]
        got = self.Acc._label_retry_candidates(self.Ship, base, 1)
        self.assertEqual(got, olvidado, 'grupo 3: primero el que hace mas que no se refresca')
