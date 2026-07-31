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
)
from odoo.addons.meli_oerp.models import versions as _versions

from odoo.addons.meli_oerp.models.versions import *

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
    def get_new_instance(self, company=None, account=None, refresh_force=False):

        if not account:
            if "company_ids" in self.env.user._fields and self.env.user.company_ids:
                for comp in self.env.user.company_ids:
                    if comp.mercadolibre_connections and comp.mercadolibre_connections[0] and comp.mercadolibre_connections[0].status == 'connected':
                        account = comp.mercadolibre_connections[0]

        company = account and account.company_id

        if not company:
            company = self.env.user.company_id

        # Proxy de rescate: la cuenta tiene prioridad sobre la empresa para el host alternativo.
        api_host = (account and account.http_proxy) or (company and company.mercadolibre_http_proxy) or "https://api.mercadolibre.com"
        use_custom_host = api_host != "https://api.mercadolibre.com"

        # Crear instancia de MeliApi según modo activo (SDK o requests)
        if _versions.USE_MELI_SDK and MeliApiSDK is not None:
            if use_custom_host:
                sdk_config = _meli_sdk.Configuration(host=api_host)
                # Host de rescate: sin auto-retry (los 429 agravan el rate-limit del proxy).
                sdk_config.retries = False
                api_client = _ApiClient(configuration=sdk_config)
            else:
                api_client = _ApiClient(configuration=configuration_sdk)
            api_rest_client = MeliApi(api_client)
        else:
            config = MeliConfiguration(host=api_host) if use_custom_host else configuration_nosdk
            api_rest_client = MeliApi(config=config)

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
                        body=str(rjson) + str("\naccess_token:") + str(api_rest_client.access_token) + str("\nrefresh_token:") + str(api_rest_client.refresh_token),
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

                if ((rjson and "error" in rjson) or refresh_force == True):

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
                            elif (refresh_force or (message and "invalid" in str(message)) or (message and "expired" in str(message))
                                    or message == "expired_token" or message == "invalid_token" or message == "internal_server_error"):
                                api_rest_client.needlogin_state = True
                                try:
                                    _logger.info("TRY api_rest_client.get_refresh_token: " + str(api_rest_client))
                                    refresh = api_rest_client.get_refresh_token()
                                    _logger.info("Refresh result: " + str(refresh))
                                    account.message_post(
                                        body=str("Refresh result: " + str(refresh)) + str("\naccess_token:") + str(api_rest_client.access_token) + str("\nrefresh_token:") + str(api_rest_client.refresh_token),
                                        message_type="notification"
                                    )
                                    if (refresh):
                                        refjson = refresh
                                        logs += str(refjson) + "\n"
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
