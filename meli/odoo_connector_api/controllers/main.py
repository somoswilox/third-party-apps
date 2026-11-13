# -*- coding: utf-8 -*-

import base64

from odoo import http, api


from odoo import fields
from odoo.http import Controller, Response, request, route

from ..models.versions import route_typejson

import pdb
import logging
_logger = logging.getLogger(__name__)

# Seguridad (26.324): los endpoints OCAPI autentican con access_token (y /status con client_id+secret_key)
# dentro del mismo post. Loguear el post entero dejaba esos secretos en claro en el log de cada cliente.
_OCAPI_SECRET_KEYS = ('access_token', 'refresh_token', 'secret_key', 'app_key', 'client_secret')


def _ocapi_redact_post(post):
    """Copia del post para loguear: secretos de nivel superior como '****'+ultimos 4."""
    if not isinstance(post, dict):
        return post
    red = {}
    for k, v in post.items():
        if k in _OCAPI_SECRET_KEYS and v:
            s = str(v)
            red[k] = '****' + (s[-4:] if len(s) > 8 else '')
        else:
            red[k] = v
    return red



class OcapiAuthorize(http.Controller):

    @http.route('/ocapi/<string:connector>/auth', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def authorize(self, connector, **post):
        #POST api user id and token, create id based on URL if need to create one
        #check all connectors
        client_id = post.get("client_id") or post.get("app_id")
        secret_key = post.get("secret_key") or post.get("app_key")
        connection_account = []
        if client_id and secret_key:
            _logger.info("Authentication request for connector: "+str(connector))
            connection_account = request.env['ocapi.connection.account'].sudo().search([('client_id','=',client_id),('secret_key','=',secret_key)])
        access_tokens = []
        for a in connection_account:
            _logger.info("Trying")
            access_token = a.authorize_token( client_id, secret_key )
            access_tokens.append({ 'client_id': client_id, 'access_token': access_token  })
        _logger.info("ocapi auth: %s token(s) emitidos", len(access_tokens))
        return access_tokens

    @http.route('/ocapi/<string:connector>/status', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def status(self, connector, **post):
        #POST api user id and token, create id based on URL if need to create one
        #check all connectors
        _logger.info("status ocapi base object")
        client_id = post.get("client_id") or post.get("app_id")
        secret_key = post.get("secret_key") or post.get("app_key")
        connection_account = []
        if client_id and secret_key:
            _logger.info("Authentication request for connector: "+str(connector))
            connection_account = request.env['ocapi.connection.account'].sudo().search([('client_id','=',client_id),('secret_key','=',secret_key)])
        access_tokens = []
        for a in connection_account:
            _logger.info("Trying")
            return "connected";
            #access_token = a.status( client_id, secret_key )
            #access_tokens.append({ 'client_id': client_id, 'access_token': access_token  })
        #_logger.info(access_tokens)
        return access_tokens

class OcapiCatalog(http.Controller):

    @http.route( [
    '/ocapi/<string:connector>/img/<string:productid>',
    '/ocapi/<string:connector>/img/<string:productid>/<string:sku>',
    '/ocapi/<string:connector>/img/<string:productid>/<string:sku>/<string:imgid>',
    '/ocapi/<string:connector>/img/<string:productid>/<string:sku>/<string:imgid>/<string:quality>'],
                auth='public', type='http', methods=['GET'], csrf=False, cors='*')
    def get_ocapi_image( self, connector, productid, sku=None, imgid=None, quality=None ):
        """Imagen de un producto para los consumidores OCAPI (p.ej. meli_oerp_multiple arma
        /ocapi/mercadolibre/img/<id>/<sku>/<default|product.image id>).

        [#caso-K14] Antes usaba ir.http.binary_content, que no existe desde Odoo 16 (500 en 16-19), y los
        campos 'image'/'image_medium', que no existen desde 13. Ahora va por ir.binary. Misma
        resolucion que antes: plantilla si el sku coincide, si no variante; imgid != default =
        product.image. Sin imagen => 404 (no placeholder: un consumidor lo subiria como foto).
        """
        record, field = self._ocapi_image_record(productid, sku=sku, imgid=imgid, quality=quality)
        if not record:
            return request.not_found()
        stream = request.env['ir.binary']._get_image_stream_from(record, field_name=field)
        return stream.get_response()

    def _ocapi_image_record(self, productid, sku=None, imgid=None, quality=None):
        """Devuelve (registro, campo) con imagen, o (None, None)."""
        env = request.env
        field = 'image_512' if (sku == 'medium' or quality == 'medium') else 'image_1920'
        try:
            pid = int(productid)
        except (TypeError, ValueError):
            return None, None

        product_tmpl = env['product.template'].sudo().browse(pid).exists()
        product = env['product.product'].sudo().browse(pid).exists()
        valid_tmpl = bool(product_tmpl and sku and sku in (product_tmpl.default_code, product_tmpl.barcode))
        valid_product = bool(product and sku and sku in (product.default_code, product.barcode))

        candidates = []
        if imgid and imgid != 'default':
            try:
                candidates.append(env['product.image'].sudo().browse(int(imgid)).exists())
            except (TypeError, ValueError):
                return None, None
        if valid_tmpl:
            candidates.append(product_tmpl)
        else:
            if product:
                candidates.append(product)
            if product_tmpl:
                candidates.append(product_tmpl)

        for rec in candidates:
            if rec and field in rec._fields and rec[field]:
                return rec, field
        _logger.info("get_ocapi_image: sin imagen productid=%s sku=%s imgid=%s (tmpl=%s variante=%s)",
                     productid, sku, imgid, valid_tmpl, valid_product)
        return None, None

    @http.route('/ocapi/<string:connector>/connection', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def get_connection_account( self, connector, **post ):

        access_token = post.get("access_token")

        if not access_token:
            return False

        connection_account = request.env['ocapi.connection.account'].sudo().search([('access_token','=',access_token)])

        _logger.info(connection_account)

        if not connection_account or not len(connection_account)==1:
            return False

        if not (connector == connection_account.name) and not (connector == connection_account.type):
            return False

        return connection_account

    @http.route('/ocapi/<string:connector>/<string:channel>/status', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def status(self, connector, channel, **post):
        _logger.info("ocapi status: "+str(connector)+" channel: "+str(channel))
        _logger.info(_ocapi_redact_post(post))
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}

        #filter products using connection account and configuration bindings
        return connection.fetch_status(**post)


    @http.route('/ocapi/<string:connector>/githook', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def githook(self, connector, **post):
        _logger.info("ocapi githook: "+str(connector))
        _logger.info(_ocapi_redact_post(post))
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}

        #filter products using connection account and configuration bindings
        return connection.fetch_githook(**post)

    @http.route('/ocapi/<string:connector>/catalog', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def catalog(self, connector, **post):
        _logger.info("catalog: "+str(connector))
        _logger.info(_ocapi_redact_post(post))
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}

        #filter products using connection account and configuration bindings
        return connection.list_catalog(**post)

    @http.route('/ocapi/<string:connector>/pricestock', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def pricestock(self, connector, **post):
        _logger.info("pricestock: "+str(connector))
        _logger.info(_ocapi_redact_post(post))
        if post.get("sales"):
            return { "error": "bad format" }
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {'error': 'no se puede acceder a la cuenta, causa: access_token invalido o vencido! Intente de nuevo con otro access_token.'}
        return connection.list_pricestock(**post)

    @http.route('/ocapi/<string:connector>/pricelist', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def pricelist(self, connector, **post):
        _logger.info("pricelist: "+str(connector))
        _logger.info(_ocapi_redact_post(post))
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {'error': 'no se puede acceder a la cuenta, causa: access_token invalido o vencido! Intente de nuevo con otro access_token.'}
        return connection.list_pricelist(**post)

    @http.route('/ocapi/<string:connector>/stock', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def stock(self, connector, **post):
        _logger.info("stock: "+str(connector))
        _logger.info(_ocapi_redact_post(post))
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}
        return connection.list_stock(**post)

    @http.route('/ocapi/<string:connector>/sales', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def sales(self, connector, **post):
        _logger.info("sales: "+str(connector))
        _logger.info(_ocapi_redact_post(post))
        if not post.get("sales"):
            _logger.error("no sales order found.")
            return { "error": "no sales order" }
        connection = self.get_connection_account(connector,**post)
        if not connection:
            _logger.error("connection not found.")
            return {'error': 'no se puede acceder a la cuenta, causa: access_token invalido o vencido! Intente de nuevo con otro access_token.'}
        return connection.import_sales(**post)


class OcapiConnectorApi(http.Controller):
    """REST API endpoints for OCAPI connector discovery and publishing."""

    @http.route('/ocapi/connectors', auth='public', type=route_typejson,
                methods=['POST', 'GET'], csrf=False, cors='*')
    def connectors(self, **post):
        """List all registered connectors with status and account counts."""
        registry = request.env['ocapi.connector.registry'].sudo()
        return registry.get_connector_summary()

    @http.route('/ocapi/connectors/available', auth='public', type=route_typejson,
                methods=['POST', 'GET'], csrf=False, cors='*')
    def connectors_available(self, **post):
        """List connectors that support publishing, with capabilities per account."""
        registry = request.env['ocapi.connector.registry'].sudo()
        return registry.get_publishing_connectors()

    @http.route('/ocapi/connectors/<string:connector_type>/accounts',
                auth='public', type=route_typejson, methods=['POST', 'GET'],
                csrf=False, cors='*')
    def connector_accounts(self, connector_type, **post):
        """List accounts for a specific connector type."""
        registry = request.env['ocapi.connector.registry'].sudo()
        all_accounts = registry.get_all_connector_accounts()
        return all_accounts.get(connector_type, [])

    @http.route('/ocapi/publish', auth='public', type=route_typejson,
                methods=['POST'], csrf=False, cors='*')
    def publish(self, **post):
        """Publish a product via OCAPI generic protocol.

        Expected POST body:
            access_token: str - authentication token
            account_id: int - connector account ID
            account_model: str - account model name (e.g. mercadolibre.account)
            product_data: dict - OCAPI standard product data
        """
        access_token = post.get('access_token')
        if not access_token:
            return {'success': False, 'error': 'access_token required'}

        conn = request.env['ocapi.connection.account'].sudo().search(
            [('access_token', '=', access_token)], limit=1)
        if not conn:
            return {'success': False, 'error': 'Invalid or expired access_token'}

        account_model = post.get('account_model')
        account_id = post.get('account_id')

        if account_model and account_id and account_model in request.env:
            account = request.env[account_model].sudo().browse(int(account_id))
            if not account.exists():
                return {'success': False, 'error': 'Account not found'}
        else:
            account = conn

        product_data = post.get('product_data', {})
        if not product_data:
            return {'success': False, 'error': 'product_data required'}

        return account.ocapi_publish_product(product_data)
