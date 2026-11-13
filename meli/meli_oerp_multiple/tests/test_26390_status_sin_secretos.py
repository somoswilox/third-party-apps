# -*- coding: utf-8 -*-
"""26.390 (seguridad) -- /ocapi/<connector>[/<channel>]/status nunca devuelve VALORES de secretos.

Antes: mercadolibre.account.fetch_status() leia el access_token de MercadoLibre y lo devolvia con
valor en el nivel de seguridad Predeterminado (el default de toda instancia). Cualquiera con las
credenciales OCAPI de la cuenta se llevaba el token del vendedor.
Ahora: sólo presencia (access_token_present) y vencimiento (access_token_expires_at). La copia
prod->test sigue existiendo pero con tres llaves explícitas: el pedido trae token_copy=True, la
cuenta de PRODUCCION tiene meli_token_copy_allowed y el Nivel de seguridad permite token_copy.

Sin red: el pull a produccion se prueba con requests.post simulado.
Control (medido 9-nov, origin 26.389 + este test): 16/17 4F+3E/7, 18/19/20 3F+4E/7. FAIL = el
access_token sale con valor (test_1/2/7) o el pull no lo pide (test_6); ERROR = no existe el interruptor
(test_3/4/5) y, en 18+, el /status custom rompe por date_utils.json_default (test_7). Fix: 0/7 en las 5.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

TOKEN = 'APP_USR-0000000000000000-110926-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-111111111'
REFRESH = 'TG-00000000000000000000000-111111111'
SECRET = 'ml-app-secret-0123456789'
SECRETOS = (TOKEN, REFRESH, SECRET)


def _valores(d):
    out = []
    for v in (d or {}).values():
        if isinstance(v, (list, tuple)):
            out.extend(str(x) for x in v)
        else:
            out.append(str(v))
    return out


@tagged('post_install', '-at_install', 'meli', 'meli_26390')
class TestStatusSinSecretos26390(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
        pl = env['product.pricelist'].search([], limit=1) or env['product.pricelist'].create({'name': 'S390'})
        cls.config = env['mercadolibre.configuration'].create({
            'name': 'S390', 'mode': 'test', 'company_id': env.company.id, 'mercadolibre_pricelist': pl.id,
            'mercadolibre_buying_mode': 'buy_it_now', 'mercadolibre_currency': 'ARS',
            'mercadolibre_stock_warehouse': wh.id, 'mercadolibre_stock_warehouse_full': wh.id,
            'mercadolibre_listing_type': 'gold_special'})
        cls.account = env['mercadolibre.account'].create({
            'name': 'S390', 'type': 'mercadolibre', 'company_id': env.company.id, 'configuration': cls.config.id,
            'country_id': env.ref('base.ar').id, 'meli_login_id': 'S390', 'client_id': '1234567890',
            'secret_key': SECRET, 'seller_id': '111111111', 'redirect_uri': 'http://localhost/meli_login/S390'})
        cls.expires = datetime.now().replace(microsecond=0) + timedelta(hours=5)
        cls.account.sudo().write({'access_token': TOKEN, 'refresh_token': REFRESH,
                                  'access_token_expires_at': cls.expires})
        if 'connection_monitor' in cls.account._fields:
            cls.account.connection_monitor = True
        env.company.sudo().ocapi_security_level = 'default'

    def _status(self, **post):
        res = self.account.sudo().fetch_status(**post)
        self.assertEqual(len(res), 1)
        return res[0]

    def _sin_secretos(self, st):
        for k in ('refresh_token', 'secret_key', 'client_secret'):
            self.assertNotIn(k, st, "el /status devuelve %s" % k)
        for val in _valores(st):
            for sec in SECRETOS:
                self.assertNotIn(sec, val, "un valor secreto salio en el /status")

    def test_1_status_base_no_devuelve_el_token(self):
        """Lo que pide el backend central y la sonda de salud (/ocapi/mercadolibre/status, sin post)."""
        st = self._status()
        self.assertNotIn('access_token', st)
        self._sin_secretos(st)

    def test_2_status_informa_presencia_y_vencimiento(self):
        st = self._status()
        self.assertEqual(st.get('status'), 'connected')
        self.assertIs(st.get('access_token_present'), True)
        self.assertTrue(st.get('access_token_expires_at'))
        self.assertEqual(st.get('client_id'), '1234567890')

    def test_3_pedir_token_copy_sin_permiso_de_la_cuenta_no_lo_da(self):
        self.assertFalse(self.account.sudo().meli_token_copy_allowed)
        st = self._status(token_copy=True, client_id='1234567890', secret_key=SECRET)
        self.assertNotIn('access_token', st)
        self._sin_secretos(st)

    def test_4_copia_explicita_con_permiso_da_solo_el_access_token(self):
        self.account.sudo().meli_token_copy_allowed = True
        st = self._status(token_copy=True)
        self.assertEqual(st.get('access_token'), TOKEN)
        self.assertNotIn('refresh_token', st)
        self.assertNotIn('secret_key', st)
        # con permiso pero SIN pedirlo explícito: no sale
        self.assertNotIn('access_token', self._status())

    def test_5_nivel_bajo_no_copia_aunque_la_cuenta_lo_permita(self):
        self.account.sudo().meli_token_copy_allowed = True
        self.env.company.sudo().ocapi_security_level = 'low'
        st = self._status(token_copy=True)
        self.assertNotIn('access_token', st)
        self._sin_secretos(st)

    def test_6_pull_de_test_pide_token_copy_explicito(self):
        """Lado TEST: el POST a produccion lleva token_copy=True (sin red)."""
        acc = self.account.sudo()
        acc.write({'meli_produccion_enabled': True, 'meli_produccion_uri': 'https://prod.invalid',
                   'meli_produccion_channel': 'canal', 'meli_produccion_client_id': 'c',
                   'meli_produccion_secret_key': 's', 'refresh_token': False})
        enviados = []

        class _R:
            status_code = 200

            def json(self):
                return {'result': [{'status': 'connected', 'access_token': 'APP_USR-NUEVO',
                                    'access_token_expires_at': '2030-01-01 00:00:00'}]}

        def _post(url, json=None, **kw):
            enviados.append((url, json))
            return _R()

        with patch('odoo.addons.meli_oerp_multiple.models.connection_account.requests.post', side_effect=_post):
            msg = acc.pull_token_from_produccion(force=True)
        self.assertTrue(enviados, msg)
        self.assertIs(enviados[0][1]['params'].get('token_copy'), True)
        self.assertEqual(acc.access_token, 'APP_USR-NUEVO')

    def test_7_conector_custom_tampoco_devuelve_su_token(self):
        """odoo_connector_api: la cuenta OCAPI tipo custom informa presencia, no el valor."""
        env = self.env
        conf = env['ocapi.connection.configuration'].create({
            'name': 'S390', 'mode': 'test', 'company_id': env.company.id})
        acc = env['ocapi.connection.account'].create({
            'name': 'S390', 'type': 'custom', 'company_id': env.company.id,
            'country_id': env.ref('base.ar').id, 'configuration': conf.id,
            'client_id': 'cid', 'secret_key': SECRET})
        acc.sudo().write({'access_token': TOKEN, 'connection_monitor': True})
        st = acc.sudo().fetch_status()[0]
        self.assertNotIn('access_token', st)
        self.assertIs(st.get('access_token_present'), True)
        self._sin_secretos(st)
