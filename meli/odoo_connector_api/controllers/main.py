# -*- coding: utf-8 -*-

import base64

from odoo import http, api

#from ..melisdk.meli import Meli

from odoo import fields
from odoo.http import Controller, Response, request, route

from ..models.versions import route_typejson

import pdb
import logging
_logger = logging.getLogger(__name__)



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
        _logger.info(access_tokens)
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
        _logger.info("get_ocapi_image")
        _logger.info(str(connector))
        _logger.info(str(productid))
        _logger.info(str(sku))
        _logger.info(str(imgid))
        xmlid = None
        model = "product.template"
        id = productid
        field = "image" #image_medium

        product_tmpl = None
        product = None
        validity = False


        try:
            product_tmpl = request.env["product.template"].sudo().browse([productid])
            validity = product_tmpl and sku and (product_tmpl.default_code==sku or product_tmpl.barcode==sku)
            _logger.info(product_tmpl.default_code)
            _logger.info(product_tmpl.barcode)
            _logger.info("validity product_tmpl:"+str(validity))
        except:
            _logger.info("error no valid product for product_tmpl:"+str(product_tmpl))
            product_tmpl = False
            validity = False

        try:
            if not validity:
                model = "product.product"
                product = request.env["product.product"].sudo(1).browse([productid])
                validity = product and sku and (product.default_code==sku or product.barcode==sku)
                _logger.info(product.default_code)
                _logger.info(product.barcode)
                _logger.info("validity product:"+str(validity))
        except:
            _logger.info("error no valid product for product:"+str(product))
            product = False

        #if sku==None or sku=="default":

        if imgid and not imgid=="default":
            model = "product.image"
            id = imgid

        if sku=="medium" or quality=="medium":
            field = "image_medium"
        #unique = random number
        #filename = None
        #filename_field = None
        #download = None
        #mimetype = None
        #default_mimetype = 'image/png'
        #related_id = None
        #access_mode = None
        #access_token =
        #env = env

        #status, headers, content = binary_content(
        #    xmlid=xmlid, model=model, id=id, field=field, unique=unique, filename=filename,
        #    filename_field=filename_field, download=download, mimetype=mimetype,
        #    default_mimetype='image/png', related_id=related_id, access_mode=access_mode, access_token=access_token)
        #request.registry['ir.http'].binary_content(
            #xmlid=xmlid, model=model, id=id, field=field, unique=unique, filename=filename,
            #filename_field=filename_field, download=download, mimetype=mimetype,
            #default_mimetype=default_mimetype, related_id=related_id, access_mode=access_mode, access_token=access_token,
            #env=env)
        #Binary()
        #/web/image?model=product.template&id=6&field=image_medium&unique=07122020223433

        #status, headers, content = request.registry['ir.http'].binary_content( model=model, id=id, field=field )
        status, headers, content = request.env['ir.http'].sudo().binary_content( model=model, id=id, field=field )
        _logger.info("model:"+str(model)+" id:"+str(id)+" field:"+field )
        _logger.info(str(status))
        _logger.info(str(headers))
        #_logger.info(str(content))

        image_base64 = ""
        if not content and status!=200 and product_tmpl:
            content = product_tmpl.image

        if status==200 and content:
            try:
                image_base64 = base64.b64decode(content)
                headers.append(('Content-Length', len(image_base64)))
            except:
                _logger.error("error processing b64decode")

        response = request.make_response(image_base64, headers)
        response.status_code = status

        return response

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
        _logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}

        #filter products using connection account and configuration bindings
        return connection.fetch_status(**post)


    @http.route('/ocapi/<string:connector>/githook', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def githook(self, connector, **post):
        _logger.info("ocapi githook: "+str(connector))
        _logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}

        #filter products using connection account and configuration bindings
        return connection.fetch_githook(**post)

    @http.route('/ocapi/<string:connector>/catalog', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def catalog(self, connector, **post):
        _logger.info("catalog: "+str(connector))
        _logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}

        #filter products using connection account and configuration bindings
        return connection.list_catalog(**post)

    @http.route('/ocapi/<string:connector>/pricestock', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def pricestock(self, connector, **post):
        _logger.info("pricestock: "+str(connector))
        _logger.info(post)
        if post.get("sales"):
            return { "error": "bad format" }
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {'error': 'no se puede acceder a la cuenta, causa: access_token invalido o vencido! Intente de nuevo con otro access_token.'}
        return connection.list_pricestock(**post)

    @http.route('/ocapi/<string:connector>/pricelist', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def pricelist(self, connector, **post):
        _logger.info("pricelist: "+str(connector))
        _logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {'error': 'no se puede acceder a la cuenta, causa: access_token invalido o vencido! Intente de nuevo con otro access_token.'}
        return connection.list_pricelist(**post)

    @http.route('/ocapi/<string:connector>/stock', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def stock(self, connector, **post):
        _logger.info("stock: "+str(connector))
        _logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}
        return connection.list_stock(**post)

    @http.route('/ocapi/<string:connector>/sales', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def sales(self, connector, **post):
        _logger.info("sales: "+str(connector))
        _logger.info(post)
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
