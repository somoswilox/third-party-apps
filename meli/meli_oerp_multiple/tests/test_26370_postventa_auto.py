# -*- coding: utf-8 -*-
"""26.370 (#caso-K67, caso-K39 cliente B1) -- mensaje postventa automático por estado del envío.

Reglas de Aztec: Full (fulfillment) al quedar entregado; xd_drop_off al quedar enviado.
Sin red: ML se simula. Control (origin sin el fix): no existe el cron ni los campos => error.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_binder_wizard import TestBinderWizard


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli:
    access_token = 'TEST'
    needlogin_state = False

    def __init__(self):
        self.posts = []
        self.gets = []
        self.cap = 1
        self.caps_error = False

    def get(self, path, params=None, **kw):
        self.gets.append(path)
        if self.caps_error:
            return _Resp({'error': 'internal', 'status': 500})
        return _Resp([{'option_id': 'SEND_INVOICE_LINK', 'cap_available': self.cap},
                      {'option_id': 'OTHER', 'cap_available': 1}])

    def post(self, path, body=None, params=None, **kw):
        self.posts.append((path, body))
        return _Resp({'id': 'x', 'status': 'available'})


@tagged('post_install', '-at_install', 'meli', 'meli_26370')
class TestPostventaAuto26370(TransactionCase):

    _crear_minimo = TestBinderWizard._crear_minimo
    _cuenta = TestBinderWizard._cuenta

    def setUp(self):
        super().setUp()
        self.account = self._cuenta()
        if not self.account.configuration:
            self.account.configuration = self._crear_minimo('mercadolibre.configuration')
        self.config = self.account.configuration
        self.meli = _FakeMeli()
        meli = self.meli
        p = patch.object(type(self.env['meli.util']), 'get_new_instance', lambda *a, **k: meli)
        p.start()
        self.addCleanup(p.stop)
        p2 = patch.object(type(self.env['res.company']), '_get_ML_sites', lambda *a, **k: 'MLM', create=True)
        p2.start()
        self.addCleanup(p2.stop)
        # otras órdenes de la base no deben interferir
        self.env['mercadolibre.orders'].search([]).write({'meli_post_sale_state': 'skipped'})
        self.partner = self.env['res.partner'].create({'name': 'TEST comprador 721'})
        self.product = self.env['product.product'].create({'name': 'TEST 721', 'list_price': 100.0})
        self.buyer = self._crear_minimo('mercadolibre.buyers')
        self.buyer.write({'first_name': 'Ana', 'name': 'Ana Pérez'})
        self.config.write({
            'mercadolibre_post_sale_message': "¡Hola, {BUYER}! Factura: {LINK}",
            'mercadolibre_post_sale_link_field': 'client_order_ref',
            'mercadolibre_post_sale_auto_rules': 'fulfillment:delivered, xd_drop_off:shipped',
        })
        self._n = 0

    def _orden(self, logistic, status, pack=None, link='https://fact.example.mx/X', days_old=1):
        self._n += 1
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'client_order_ref': link,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100.0})],
        })
        ship = self._crear_minimo('mercadolibre.shipment')
        ship.write({'shipping_id': '4872100%s' % self._n, 'status': status, 'logistic_type': logistic})
        mo = self.env['mercadolibre.orders'].create({
            'order_id': '20007210000%s' % self._n, 'name': 'TEST 721 %s' % self._n, 'status': 'paid',
            'sale_order': so.id, 'connection_account': self.account.id, 'buyer': self.buyer.id,
            'shipment': ship.id, 'shipment_logistic_type': logistic, 'pack_id': pack or False,
            'date_created': fields.Datetime.now() - timedelta(days=days_old),
        })
        return mo

    def _activar(self):
        self.config.mercadolibre_post_sale_auto = True

    def _sent(self):
        return [b['text'] for (path, b) in self.meli.posts if b and b.get('option_id') == 'SEND_INVOICE_LINK']

    def test_1_apagado_no_manda(self):
        self._orden('fulfillment', 'delivered')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])

    def test_2_full_entregado_manda_una_sola_vez(self):
        self._activar()
        mo = self._orden('fulfillment', 'delivered')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self._sent(), ["¡Hola, Ana! Factura: https://fact.example.mx/X"])
        self.assertEqual(mo.meli_post_sale_state, 'sent')

    def test_3_full_enviado_todavia_no(self):
        self._activar()
        mo = self._orden('fulfillment', 'shipped')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])
        mo.shipment.status = 'delivered'
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(len(self._sent()), 1)

    def test_4_drop_off_al_enviarse_y_no_antes(self):
        self._activar()
        mo = self._orden('xd_drop_off', 'ready_to_ship')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])
        mo.shipment.status = 'shipped'
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(len(self._sent()), 1)

    def test_5_drop_off_ya_entregado_tambien_cuenta(self):
        """«shipped» = ese estado o posterior: si el refresco lo ve directo entregado, igual sale."""
        self._activar()
        self._orden('xd_drop_off', 'delivered')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(len(self._sent()), 1)

    def test_6_al_activar_lo_previo_no_se_manda(self):
        vieja = self._orden('fulfillment', 'delivered')
        self._activar()
        self.assertEqual(vieja.meli_post_sale_state, 'skipped')
        self.assertTrue(self.config.mercadolibre_post_sale_auto_since)
        nueva = self._orden('fulfillment', 'delivered')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(len(self._sent()), 1)
        self.assertEqual(nueva.meli_post_sale_state, 'sent')

    def test_7_pack_una_sola_vez(self):
        self._activar()
        a = self._orden('fulfillment', 'delivered', pack='2000449027253')
        b = self._orden('fulfillment', 'delivered', pack='2000449027253')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(len(self._sent()), 1)
        self.assertEqual(sorted((a | b).mapped('meli_post_sale_state')), ['sent', 'skipped'])

    def test_8_sin_cupo_de_ml_no_postea(self):
        self._activar()
        self.meli.cap = 0
        mo = self._orden('fulfillment', 'delivered')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])
        self.assertEqual(mo.meli_post_sale_state, 'skipped')

    def test_9_manual_previo_no_se_repite(self):
        self._activar()
        mo = self._orden('xd_drop_off', 'ready_to_ship')
        mo.send_post_message_inv_link()
        self.assertEqual(len(self._sent()), 1)
        self.assertEqual(mo.meli_post_sale_state, 'sent')
        mo.shipment.status = 'shipped'
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(len(self._sent()), 1)

    def test_10_liga_vacia_no_manda(self):
        self._activar()
        mo = self._orden('fulfillment', 'delivered', link=False)
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])
        self.assertEqual(mo.meli_post_sale_state, 'skipped')
        self.assertTrue(any('vacía' in (m.body or '') for m in mo.sale_order.message_ids))

    def test_11_orden_vieja_no(self):
        self._activar()
        mo = self._orden('fulfillment', 'delivered', days_old=60)
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])
        self.assertFalse(mo.meli_post_sale_state)

    def test_12_ml_sin_opciones_se_reintenta_sin_postear(self):
        self._activar()
        self.meli.caps_error = True
        mo = self._orden('fulfillment', 'delivered')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])
        self.assertFalse(mo.meli_post_sale_state)
        self.meli.caps_error = False
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(len(self._sent()), 1)

    def test_13_otro_tipo_de_logistica_no(self):
        self._activar()
        self._orden('cross_docking', 'delivered')
        self.env['mercadolibre.orders'].cron_meli_post_sale_auto()
        self.assertEqual(self.meli.posts, [])

    def test_14_tope_por_corrida(self):
        self._activar()
        for _ in range(3):
            self._orden('fulfillment', 'delivered')
        self.assertEqual(self.env['mercadolibre.orders'].cron_meli_post_sale_auto(limit=2), 2)
        self.assertEqual(len(self._sent()), 2)

    def test_15_reglas_alias_fullfilment(self):
        from odoo.addons.meli_oerp_multiple.models.post_sale_auto import parse_post_sale_rules
        r = parse_post_sale_rules('fullfilment:delivered; xd_drop_off:shipped')
        self.assertEqual(r['fulfillment'], {'delivered'})
        self.assertEqual(r['xd_drop_off'], {'shipped', 'delivered'})
