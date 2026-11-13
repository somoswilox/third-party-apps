# -*- coding: utf-8 -*-

import pytz

from odoo import models, api, fields
from odoo.tools.translate import _

import requests
import json
try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode
import logging
_logger = logging.getLogger(__name__)

# Importar desde meli_oerp (soporta SDK y NoSDK)
from odoo.addons.meli_oerp.models.meli_util import MeliApi as MeliApiBase
from odoo.addons.meli_oerp.models.meli_util import (
    configuration, configuration_nosdk, configuration_sdk,
    MeliApiSDK, MeliApiNoSDK, MeliConfiguration, _ApiClient, _meli_sdk,
    _meli_audit_wrap_request,
)
from odoo.addons.meli_oerp.models import versions as _versions

from odoo.addons.meli_oerp.models.versions import *
from .versions import meli_is_auth_error

# Namespace del advisory lock de Postgres para el single-flight del refresh de token.
_MELI_REFRESH_LOCK_NS = 84532001

# Seguridad (comms 2026-10-05T15:22:47Z, caso-K14): los tokens/secretos NUNCA van en claro al chatter,
# al log ni a mercadolibre.notification.logs -- cualquiera con acceso al chatter veia un token vivo.
_MELI_SECRET_KEYS = ('access_token', 'refresh_token', 'client_secret', 'secret_key', 'code')


def _meli_mask(value):
    """Enmascara un secreto: primeros 4 + '…' + ultimos 4 (o '***' si es corto)."""
    if not value:
        return str(value)
    s = str(value)
    if len(s) <= 12:
        return '***'
    return s[:4] + '…' + s[-4:]


def _meli_redact(data, omit=False):
    """Copia de un dict (respuesta OAuth, login_data) con los secretos enmascarados (omit=True: quitados)."""
    if isinstance(data, dict):
        if omit:
            return {k: v for k, v in data.items() if k not in _MELI_SECRET_KEYS}
        return {k: (_meli_mask(v) if k in _MELI_SECRET_KEYS else v) for k, v in data.items()}
    return data


# Mismo criterio que odoo_connector_api.controllers.main._ocapi_redact_post ('****'+ultimos 4),
# pero PROPIO: meli_oerp_multiple no depende de la version instalada de odoo_connector_api
# (con un odoo_connector_api < 26.324 el import fallaba y el modulo no cargaba). Recursivo:
# sirve para el post de un controller y para el raw_data/result de fetch_status (lista de dicts).
_MELI_LOG_SECRET_KEYS = tuple(_MELI_SECRET_KEYS) + ('app_key',)


# 26.363 (caso-K10): SKUs de ML tipeados con espacios NO separables (U+00A0, p.ej. "5K\xa0X\xa02U") no matcheaban
# la Referencia interna de Odoo (espacios comunes) en el =ilike ⇒ la publicacion quedaba "MISSING".
_MELI_SKU_SPACES = {0x00A0: " ", 0x2007: " ", 0x202F: " ", 0x200B: None, 0xFEFF: None}


def meli_norm_sku(sku):
    """SKU normalizado para buscar en Odoo: espacios no separables -> espacio comun, sin ancho cero, strip.
    Listas/tuplas se normalizan elemento a elemento; None/False/'' vuelven tal cual."""
    if isinstance(sku, (list, tuple)):
        return type(sku)(meli_norm_sku(s) for s in sku)
    if not sku or not isinstance(sku, str):
        return sku
    return sku.translate(_MELI_SKU_SPACES).strip()


def _meli_redact_post(data):
    """Copia para LOGUEAR: secretos como '****'+ultimos 4, en dicts y listas anidadas."""
    if isinstance(data, dict):
        red = {}
        for k, v in data.items():
            if k in _MELI_LOG_SECRET_KEYS and v:
                s = str(v)
                red[k] = '****' + (s[-4:] if len(s) > 8 else '')
            else:
                red[k] = _meli_redact_post(v)
        return red
    if isinstance(data, (list, tuple)):
        return [_meli_redact_post(x) for x in data]
    return data


def _meli_company_allows(company, feature):
    """[un caso] Nivel de seguridad (odoo_connector_api)."""
    if company and hasattr(company, '_ocapi_security_allows'):
        return company.sudo()._ocapi_security_allows(feature)
    return True


def _meli_tokens_in_chatter(account):
    """[un caso] Nivel de seguridad: el token enmascarado va al chatter/log sólo en Predeterminado."""
    company = (account and account.company_id) or (account and account.env.company)
    return _meli_company_allows(company, 'token_in_chatter')


def _meli_token_note(account, client):
    if not _meli_tokens_in_chatter(account):
        return ""
    return str("\naccess_token:") + _meli_mask(client.access_token) + str("\nrefresh_token:") + _meli_mask(client.refresh_token)

from datetime import datetime, timedelta


class MeliApi(MeliApiBase):
    """
    Extensión de MeliApi para soporte de múltiples cuentas.
    Agrega meli_login_id para gestión de múltiples conexiones.
    """

    meli_login_id = None

    def auth_url(self, redirect_URI=None):
        """Genera URL de autorización, soporta múltiples cuentas"""
        now = datetime.now()

        if redirect_URI:
            self.redirect_uri = redirect_URI

        random_id = str(now)
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'state': random_id
        }

        url = self.AUTH_URL + '?' + urlencode(params)
        return url

    def redirect_login(self):
        """Redirección a login con soporte de meli_login_id"""
        url_login_meli = str(self.auth_url())

        if self.meli_login_id:
            url_login_meli = url_login_meli + str("/") + str(self.meli_login_id)

        return {
            "type": "ir.actions.act_url",
            "url": url_login_meli,
            "target": "self",
        }

class MeliUtilMultiple(models.AbstractModel):

    _inherit = 'meli.util'

    def get_meli_state(self):
        return self.get_new_instance()

    @api.model
    def _meli_view_instance(self, account_id=False):
        """un caso: instancia para /meli/item_api con el token de la CUENTA pedida (si el usuario la puede leer)."""
        if account_id:
            account = self.env['mercadolibre.account'].browse(account_id).exists()
            if account:
                if hasattr(account, 'check_access_rule'):
                    account.check_access_rights('read')
                    account.check_access_rule('read')
                else:
                    account.check_access('read')
                return self.get_new_instance(account.company_id, account)
        return super()._meli_view_instance(account_id=account_id)

    @api.model
    def get_new_instance(self, company=None, account=None, refresh_force=False):

        if not account:
            if "company_ids" in self.env.user._fields and self.env.user.company_ids:
                for comp in self.env.user.company_ids:
                    if comp.mercadolibre_connections and comp.mercadolibre_connections[0] and comp.mercadolibre_connections[0].status == 'connected':
                        account = comp.mercadolibre_connections[0]

        company = account and account.company_id

        if not company:
            company = self.env.user.company_id

        # [un caso fase 3] Host de la API: único campo validado res.company.meli_api_url (proxy de
        # rescate si no es el oficial; el viejo http_proxy por cuenta migró a la compañía).
        # Host alternativo ⇒ cada request queda en el rastro; con Nivel de seguridad Alto se ignora.
        _acc_label = account and ("%s [%s]" % (account.name or '', account.id)) or ''
        api_host, _audit_cb = self._meli_resolve_api_host(company, account_label=_acc_label)
        use_custom_host = api_host != "https://api.mercadolibre.com"

        # Crear instancia de MeliApi según modo activo (SDK o requests)
        if _versions.USE_MELI_SDK and MeliApiSDK is not None:
            if use_custom_host:
                sdk_config = _meli_sdk.Configuration(host=api_host)
                # Host de rescate: sin auto-retry (los 429 agravan el rate-limit del proxy).
                sdk_config.retries = False
                api_client = _ApiClient(configuration=sdk_config)
                if not _meli_audit_wrap_request(getattr(api_client, 'rest_client', None), _audit_cb):
                    _logger.warning("meli proxy audit: el cliente SDK no expone rest_client.request")
            else:
                api_client = _ApiClient(configuration=configuration_sdk)
            api_rest_client = MeliApi(api_client)
        else:
            if use_custom_host:
                config = MeliConfiguration(host=api_host, audit=_audit_cb)
                # Host de rescate: sin auto-retry. Espeja lo que meli_oerp ya hacía (fix 26.49,
                # 18-jun-2026) y que en este módulo NUNCA se había replicado: el config fresco
                # por-host nace con Retry(status_forcelist=[413,429,503]) y reintentar contra el
                # proxy sólo amplifica el bloqueo.
                config.retries = False
            else:
                config = configuration_nosdk
            api_rest_client = MeliApi(config=config)

        # El host efectivo viaja con la instancia (lo usan post_mini/put_mini para no perder el proxy).
        api_rest_client.api_host = api_host
        api_rest_client._meli_audit = _audit_cb
        api_rest_client.meli_login_id = (account and account.meli_login_id)
        api_rest_client.client_id = (account and account.client_id) or ''
        api_rest_client.client_secret = (account and account.secret_key) or ''
        api_rest_client.access_token = (account and account.access_token) or ''
        api_rest_client.refresh_token = (account and account.refresh_token) or ''
        api_rest_client.redirect_uri = (account and account.redirect_uri) or ''
        api_rest_client.seller_id = (account and account.seller_id) or ''
        api_rest_client.AUTH_URL = company.get_ML_AUTH_URL(meli=api_rest_client)

        if not account:
            return api_rest_client

        last_token = api_rest_client.access_token

        api_rest_client.needlogin_state = False
        message = "Login to ML needed in Odoo."

        if not account:
            return api_rest_client

        right_access_token = False
        try:
            if not (account.seller_id == False) and api_rest_client.access_token != '':

                response = api_rest_client.get("/users/" + str(account.seller_id), {'access_token': api_rest_client.access_token})

                rjson = response.json()

                status = "status" in rjson and rjson["status"]
                cause = "cause" in rjson and rjson["cause"]

                if status and cause and int(status) >= 400:
                    account.message_post(
                        body=str(rjson) + _meli_token_note(account, api_rest_client),
                        message_type="notification"
                    )

                if status == 429:
                    return api_rest_client

                if status == 500 and cause == "Internal Server Error":
                    return api_rest_client

                if status == 504 and cause == "Gateway Time-out":
                    return api_rest_client

                if cause and status and int(status) >= 500:
                    return api_rest_client

                right_access_token = ("-" + str(account.seller_id)) in str(api_rest_client.access_token)
                if not right_access_token:
                    api_rest_client.needlogin_state = True
                    return api_rest_client

                # [caso-K11] un 401 de token vencido viene sin "error": tambien dispara el refresh
                if ((rjson and "error" in rjson) or meli_is_auth_error(rjson) or refresh_force == True):

                    if account.cron_refresh or api_rest_client.access_token:
                        internals = {
                            "application_id": account.client_id,
                            "user_id": account.seller_id,
                            "topic": "internal",
                            "resource": "get_new_instance #" + str(account.name),
                            "state": "PROCESSING"
                        }
                        noti = self.env["mercadolibre.notification"].start_internal_notification(internals, account=account)

                        errors = str(rjson) + "\n"
                        logs = str(rjson) + "\n"

                        api_rest_client.needlogin_state = True

                        _logger.info(str(rjson))

                        if ("error" in rjson and rjson["error"] == "not_found"):
                            api_rest_client.needlogin_state = True
                            logs += "NOT FOUND" + "\n"

                        if ("message" in rjson) or refresh_force:
                            message = "message" in rjson and rjson["message"]
                            if message and "message" in message:
                                try:
                                    mesjson = json.loads(message)
                                    message = mesjson["message"]
                                except:
                                    message = "invalid_token"
                                    pass
                            logs += str(message) + "\n"
                            _logger.info("message: " + str(message))
                            if self._meli_is_neutralized():
                                # DB neutralizada (staging/duplicado en Odoo.sh): NUNCA rotar el refresh_token.
                                # El POST grant_type=refresh_token lo rota server-side en ML y le robaría la
                                # sesión a PRODUCCIÓN. needlogin_state ya quedó True arriba; el entorno de test
                                # puede seguir LEYENDO con el access_token vigente hasta que expire (aceptable).
                                self._meli_log_neutralized_skip()
                                # …y cuando ese access_token EXPIRA, se cierra la sesión de ML en la copia.
                                # Antes sólo se omitía el refresh y no quedaba rastro: la cuenta seguía
                                # figurando "Activo" en staging y cada llamada fallaba en silencio para
                                # siempre, sin forma de que el dev supiera por qué. (Política Moldeo, 4-ago-2026.)
                                if account and account.account_state != 'disconnected':
                                    account.sudo().write({'account_state': 'disconnected',
                                                          'cron_refresh': False})
                                    account.message_post(body=(
                                        "Base neutralizada (staging o copia): el token de MercadoLibre "
                                        "expiró. Se cierra la sesión en esta copia para no rotar el "
                                        "refresh_token de PRODUCCIÓN. Para seguir probando, conectá una "
                                        "cuenta de test."))
                            elif (refresh_force or (message and "invalid" in str(message)) or (message and "expired" in str(message))
                                    or message == "expired_token" or message == "invalid_token" or message == "internal_server_error"):
                                api_rest_client.needlogin_state = True
                                # SINGLE-FLIGHT del refresh (un cliente, 4-ago-2026): cuando el token vence,
                                # CADA cron/job intentaba refrescar por su cuenta -> decenas de
                                # POST /oauth/token por minuto -> ML rate-limita (429) -> NADIE logra
                                # refrescar -> deadlock. Medido en el cliente: 5 horas muerto el 03/08.
                                # Advisory lock por cuenta: solo un proceso intenta a la vez y el resto
                                # sigue de largo. Es `xact` a proposito -> se libera solo al cerrar la
                                # transaccion, SIN cr.commit() (commitear a mitad de un flujo de negocio
                                # rompe la atomicidad de todo lo que venga despues).
                                _refresh_lock_ok = True
                                try:
                                    self.env.cr.execute(
                                        "SELECT pg_try_advisory_xact_lock(%s, %s)",
                                        (_MELI_REFRESH_LOCK_NS, int(account.id) if account else 0))
                                    _refresh_lock_ok = bool(self.env.cr.fetchone()[0])
                                except Exception:
                                    _refresh_lock_ok = True  # ante la duda, comportamiento anterior
                                if not _refresh_lock_ok:
                                    _logger.info("refresh de token ML ya en curso en otro proceso "
                                                 "(cuenta %s): se omite este intento",
                                                 account and account.id)
                                    return api_rest_client
                                try:
                                    _logger.info("TRY api_rest_client.get_refresh_token: " + str(api_rest_client))
                                    refresh = api_rest_client.get_refresh_token()
                                    _omit = not _meli_tokens_in_chatter(account)
                                    _logger.info("Refresh result: " + str(_meli_redact(refresh, omit=_omit)))
                                    account.message_post(
                                        body=str("Refresh result: " + str(_meli_redact(refresh, omit=_omit))) + _meli_token_note(account, api_rest_client),
                                        message_type="notification"
                                    )
                                    if (refresh):
                                        refjson = refresh
                                        logs += str(_meli_redact(refjson, omit=_omit)) + "\n"
                                        if "access_token" in refjson:
                                            api_rest_client.access_token = refjson["access_token"]
                                            api_rest_client.refresh_token = refjson["refresh_token"]
                                            api_rest_client.code = ''
                                            # ML devuelve expires_in en segundos (típicamente 21600 = 6h)
                                            expires_in = refjson.get("expires_in", 21600)
                                            expires_at = fields.Datetime.now() + timedelta(seconds=int(expires_in))
                                            account.write({
                                                'access_token': api_rest_client.access_token,
                                                'refresh_token': api_rest_client.refresh_token,
                                                'code': '',
                                                'access_token_expires_at': expires_at,
                                            })
                                            api_rest_client.needlogin_state = False
                                        # Si el POST /oauth/token devolvió error (status>=400), NO falseamos
                                        # el estado: la cuenta está genuinamente desconectada y así debe
                                        # reportarse. El refresh_token se conserva para reintentar la
                                        # próxima corrida del cron.
                                except Exception as e:
                                    errors += str(e)
                                    logs += str(e)
                                    pass

                        noti.stop_internal_notification(errors=errors, logs=logs)

                else:
                    response.user = rjson
                    if "user_product_seller" in account._fields:
                        user_product_seller = ("tags" in rjson and "user_product_seller" in rjson["tags"])
                        if (account.user_product_seller != user_product_seller):
                            account.user_product_seller = user_product_seller

            else:
                api_rest_client.needlogin_state = True

        except requests.exceptions.ConnectionError as e:
            api_rest_client.needlogin_state = True
            error_msg = 'MELI WARNING: NO INTERNET CONNECTION TO API.MERCADOLIBRE.COM: complete the Client Id, and Secret Key and try again '
            _logger.error(error_msg)

        if api_rest_client.access_token == '' or api_rest_client.access_token == False:
            api_rest_client.needlogin_state = True

        try:
            if api_rest_client.needlogin_state:
                _logger.warning("Need login for " + str(account.name))

                # IMPORTANTE: NO se borran access_token/refresh_token/code ni se apaga
                # cron_refresh. El refresh_token de ML sigue siendo válido por meses aunque
                # el access_token haya vencido hace horas, así que conservarlo permite al
                # cron recuperar la conexión en la próxima corrida sin intervención manual.
                # Solo se manda el mail de aviso si está configurado.
                if (account.cron_refresh and company.mercadolibre_cron_mail):
                    context = {
                        'job_exception': message,
                        'dbname': MeliCr(self).dbname,
                    }

                    rese = self.env['mail.template'].browse(
                        company.mercadolibre_cron_mail.id
                    ).with_context(context).sudo().send_mail((company.id), force_send=True)

        except Exception as e:
            _logger.info(e)
            pass

        for acc in account:
            if (last_token != acc.access_token):
                astate = api_rest_client.needlogin_state
                if astate:
                    acc.status = "disconnected"
                else:
                    acc.status = "connected"

        return api_rest_client

    @api.model
    def get_url_meli_login(self, app_instance):
        company = self.env.user.company_id
        REDIRECT_URI = company.mercadolibre_redirect_uri
        url_login_meli = app_instance.auth_url(redirect_URI=REDIRECT_URI)
        return {
            "type": "ir.actions.act_url",
            "url": url_login_meli,
            "target": "self",
        }
