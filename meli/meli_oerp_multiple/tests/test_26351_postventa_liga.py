# -*- coding: utf-8 -*-
"""26.351 (#caso-K68, caso-K39 cliente B1) -- botones «Mensaje Postventa» de la orden ML sin la liga de facturación.

Antes: send_post_message_inv_link() pasaba message=None; send_post_message() lo convertía en
"Buen día, gracias por su compra" al entrar y luego `base_autofac = message or <plantilla>` =>
la plantilla con la liga nunca salía, y el texto no se podía configurar sin autofacturación.
Ahora: «Mensaje postventa» + «Campo de la liga de facturación» por cuenta (liga propia de cada
venta; vacía => no se envía), {BUYER} sin nickname, el mismo texto en los dos botones; sin nada
configurado: mensaje de autofacturación o plantilla /AUTOFACTURA/register (sólo si está instalada).
Sin red: ML se simula. Control (origin sin el fix): fallan los que esperan la liga o el texto propio.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from .test_binder_wizard import TestBinderWizard

GREETING = 'Buen día, gracias por su compra'
LOGGER = 'odoo.addons.meli_oerp_multiple.models.sale'


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli:
    access_token = 'TEST'

    def __init__(self):
        self.posts = []

    def get(self, path, params=None, **kw):
        return _Resp([{'option_id': 'SEND_INVOICE_LINK', 'cap_available': 1},
                      {'option_id': 'OTHER', 'cap_available': 1}])

    def post(self, path, body=None, params=None, **kw):
        self.posts.append((path, body))
        return _Resp({'id': 'x', 'status': 'available'})


@tagged('post_install', '-at_install', 'meli', 'meli_26351')
class TestPostventaLiga26351(TransactionCase):

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
        util = type(self.env['meli.util'])
        p = patch.object(util, 'get_new_instance', lambda *a, **k: meli)
        p.start()
        self.addCleanup(p.stop)
        p2 = patch.object(type(self.env['res.company']), '_get_ML_sites', lambda *a, **k: 'MLM', create=True)
        p2.start()
        self.addCleanup(p2.stop)
        partner = self.env['res.partner'].create({'name': 'TEST comprador K68'})
        product = self.env['product.product'].create({'name': 'TEST K68', 'list_price': 100.0})
        self.so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1, 'price_unit': 100.0})],
        })
        self.buyer = self._crear_minimo('mercadolibre.buyers')
        self.buyer.write({'first_name': 'Ana', 'name': 'Ana Pérez', 'nickname': 'VIEIROBRIAN20210623234209'})
        self.mo = self.env['mercadolibre.orders'].create({
            'order_id': '2000505871175634', 'name': 'TEST K68', 'status': 'paid',
            'sale_order': self.so.id, 'connection_account': self.account.id, 'buyer': self.buyer.id,
        })
        self.assertEqual(self.mo._get_config(), self.config)
        self.base_url = self.account.company_id.get_base_url()
        if 'autoinvoice_message' in self.config._fields:
            self.config.autoinvoice_message = False

    def _sent(self):
        return [b['text'] for (path, b) in self.meli.posts if b and b.get('option_id') == 'SEND_INVOICE_LINK']

    def _sent_text(self):
        sent = self._sent()
        self.assertEqual(len(sent), 1, "debe mandar UNA vez la opción SEND_INVOICE_LINK: %s" % self.meli.posts)
        return sent[0]

    def _aztec(self, link='https://facturacion.example.mx/doc/ABC123'):
        """Config como la pidió el cliente en #caso-K68: su texto, liga propia de cada venta."""
        self.config.mercadolibre_post_sale_message = "¡Hola, {BUYER}!\nGracias por tu compra.\nFactura: {LINK}"
        self.config.mercadolibre_post_sale_link_field = 'client_order_ref'
        self.so.client_order_ref = link

    # -- sin nada configurado (comportamiento de siempre, ahora con la liga) --------------------
    def test_1_boton_autofactura_manda_la_liga(self):
        """Sin mensaje propio, con autofacturación: la plantilla CON la liga y los datos de la venta."""
        with patch.object(type(self.mo), '_meli_autofactura_installed', lambda s: True):
            self.mo.send_post_message_inv_link()
        text = self._sent_text()
        self.assertIn(self.base_url + '/AUTOFACTURA/register', text)
        self.assertIn(self.so.name, text)
        self.assertNotIn(GREETING, text)

    def test_2_boton_simple_sin_configurar_no_manda(self):
        """«Mensaje Postventa» sin mensaje propio sólo consulta las opciones: no le escribe al comprador."""
        self.mo.action_send_post_message()
        self.assertEqual(self.meli.posts, [])

    def test_3_mensaje_de_autofacturacion(self):
        """Con «Mensaje y link autofactura» (autofacturación) y sin mensaje propio, el botón manda ése."""
        if 'autoinvoice_message' not in self.config._fields:
            self.skipTest('meli_oerp_autofacturacion no instalado')
        self.config.autoinvoice_message = 'Factura en {LINK} pedido {ORDERID}'
        self.mo.send_post_message_inv_link()
        self.assertEqual(self._sent_text(), 'Factura en %s/AUTOFACTURA/register pedido %s' % (self.base_url, self.so.name))

    def test_4_sin_autofacturacion_ni_mensaje_no_manda_liga_rota(self):
        """Sin mensaje propio y sin autofacturación instalada NO se envía (la liga por defecto daría 404)."""
        with patch.object(type(self.mo), '_meli_autofactura_installed', lambda s: False), \
                self.assertLogs(LOGGER, level='WARNING'):
            self.assertFalse(self.mo.send_post_message_inv_link())
        self.assertEqual(self._sent(), [])
        self.assertTrue(any('NO enviado' in (m.body or '') for m in self.so.message_ids))

    # -- caso Aztec (#caso-K68): texto propio + liga por venta --------------------------------------
    def test_5_mensaje_propio_con_liga_de_la_venta(self):
        self._aztec()
        self.mo.send_post_message_inv_link()
        self.assertEqual(self._sent_text(),
                         "¡Hola, Ana!\nGracias por tu compra.\nFactura: https://facturacion.example.mx/doc/ABC123")

    def test_6_los_dos_botones_mandan_lo_mismo(self):
        self._aztec()
        self.mo.action_send_post_message()
        self.mo.send_post_message_inv_link()
        sent = self._sent()
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], sent[1])

    def test_7_liga_vacia_no_se_envia(self):
        self._aztec(link=False)
        with self.assertLogs(LOGGER, level='WARNING'):
            self.assertFalse(self.mo.send_post_message_inv_link())
        self.assertEqual(self._sent(), [])
        self.assertTrue(any('client_order_ref' in (m.body or '') for m in self.so.message_ids))

    def test_8_sin_nombre_saluda_sin_nickname(self):
        self._aztec()
        self.buyer.write({'first_name': False, 'name': False})
        self.mo.send_post_message_inv_link()
        text = self._sent_text()
        self.assertTrue(text.startswith('¡Hola!\n'), text)
        self.assertNotIn('VIEIROBRIAN', text)

    def test_9_mensaje_propio_gana_sobre_autofacturacion(self):
        self._aztec()
        if 'autoinvoice_message' in self.config._fields:
            self.config.autoinvoice_message = 'OTRO {LINK}'
        self.mo.send_post_message_inv_link()
        self.assertTrue(self._sent_text().startswith('¡Hola, Ana!'))

    def test_10_texto_helper_sin_venta(self):
        mo = self.env['mercadolibre.orders'].create({'order_id': '2000271421208692', 'name': 'x'})
        with patch.object(type(mo), '_meli_autofactura_installed', lambda s: True):
            text, why = mo._meli_post_sale_invoice_text(base_url='https://example.com', config=self.config)
        self.assertIn('https://example.com/AUTOFACTURA/register', text)
