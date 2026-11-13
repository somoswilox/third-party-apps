# -*- coding: utf-8 -*-
"""26.366 (un cliente): la cola de precio NO se traba con publicaciones que fallan.

Antes, fuera de modo lote (`meli_cron_price_batch_hour = '-1'`, el default), una publicación
que ML rechazaba (cerrada / 404 / not_modifiable) o que levantaba excepción NO recibía
`price_update`: volvía primera en la cola (`price_update = False` ordena primero) y con >= 80
fallidas permanentes la corrida procesaba siempre las mismas. Lo mismo un binding sin
conn_id ni meli_id (se salteaba sin marcar, eterno al frente de la cola).
"""

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from . import test_cron_run_now as _base


@tagged('post_install', '-at_install', 'meli_26366')
class TestColaPrecio26366(TransactionCase):

    _crear_minimo = _base.TestCronRunNow._crear_minimo
    _bindings = _base.TestCronRunNow._bindings

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
        cuenta.meli_cron_price_batch_hour = '-1'          # FUERA de lote: el caso del bug
        cuenta.meli_cron_log_chatter = False
        cuenta.meli_cron_price_top_commit = 5000
        cfg = cuenta.configuration or cuenta.company_id
        cfg.mercadolibre_cron_post_update_price = True
        # los bindings preexistentes de la base no entran en las cuentas del test
        self.env['mercadolibre.product'].search([
            ('connection_account', '=', cuenta.id)]).write({'price_update': '2000-01-01 00:00:00'})
        self.Bind = type(self.env['mercadolibre.product'])

    def test_rechazo_de_ml_fuera_de_lote_marca_price_update(self):
        binds = self._bindings(4)
        rechazadas = set(binds[:2].ids)

        def _post(bind_self, *a, **kw):
            if bind_self.id in rechazadas:
                return {'error': 'item.price.not_modifiable', 'status': 400}
            return {}

        with patch.object(self.Bind, 'product_post_price', _post):
            res = self.cuenta.meli_update_remote_price(meli=object())
        self.assertEqual(res['items_error'], 2)
        binds.invalidate_recordset(['price_update'])
        self.assertTrue(all(binds.mapped('price_update')),
                        "fuera de lote la rechazada tiene que salir del frente de la cola")

    @mute_logger('odoo.addons.meli_oerp_multiple.models.connection_account')
    def test_excepcion_fuera_de_lote_marca_price_update(self):
        binds = self._bindings(2)
        boom = binds[0].id

        def _post(bind_self, *a, **kw):
            if bind_self.id == boom:
                raise ValueError('publicación cerrada (test)')
            return {}

        with patch.object(self.Bind, 'product_post_price', _post):
            res = self.cuenta.meli_update_remote_price(meli=object())
        self.assertEqual(res['items_error'], 1)
        binds.invalidate_recordset(['price_update'])
        self.assertTrue(all(binds.mapped('price_update')))

    def test_cola_avanza_con_fallidas_permanentes(self):
        """3 fallidas permanentes con lote de 3: la 2da corrida tiene que llegar a las demás."""
        self.cuenta.meli_cron_price_top_commit = 3
        binds = self._bindings(6)
        fallan = set(binds[:3].ids)
        vistas = []

        def _post(bind_self, *a, **kw):
            vistas.append(bind_self.id)
            if bind_self.id in fallan:
                return {'error': 'not_found', 'status': 404}
            return {}

        with patch.object(self.Bind, 'product_post_price', _post):
            self.cuenta.meli_update_remote_price(meli=object())
            self.cuenta.meli_update_remote_price(meli=object())
        self.assertTrue(set(binds[3:].ids) <= set(vistas),
                        "la cola quedó trabada en las mismas fallidas: %s" % vistas)

    def test_binding_sin_publicacion_sale_de_la_cola(self):
        sin_id = self._bindings(1)
        sin_id.write({'conn_id': False, 'meli_id': False, 'price_update': False})
        llamadas = []

        def _post(bind_self, *a, **kw):
            llamadas.append(bind_self.id)
            return {}

        with patch.object(self.Bind, 'product_post_price', _post):
            self.cuenta.meli_update_remote_price(meli=object())
        self.assertNotIn(sin_id.id, llamadas, "sin publicación no se publica")
        sin_id.invalidate_recordset(['price_update'])
        self.assertTrue(sin_id.price_update, "sin marcar queda eterno al frente de la cola")
