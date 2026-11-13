# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import fields, models, api
from odoo.tools.translate import _
from odoo.exceptions import UserError
from .company import ocapi_hide_secrets, ocapi_strip_secret_export
import logging
_logger = logging.getLogger(__name__)


# Secretos que NUNCA van en claro al log (mismo criterio que controllers.main._ocapi_redact_post).
_OCAPI_LOG_SECRET_KEYS = ('access_token', 'refresh_token', 'secret_key', 'app_key', 'client_secret', 'code')


try:  # 26.390: Odoo 18+ lo tiene en odoo.tools.json; en 19+ ya no está en date_utils
    from odoo.tools.json import json_default as _ocapi_json_default
except ImportError:
    from odoo.tools.date_utils import json_default as _ocapi_json_default

# 26.390: campos cuyo VALOR nunca sale por un /ocapi/<connector>[/<channel>]/status.
OCAPI_STATUS_SECRET_SUFFIXES = ('access_token', 'refresh_token', 'secret_key', 'client_secret', 'password')


def _ocapi_redact_status(data):
    """Copia para LOGUEAR: secretos como '****'+ultimos 4, en dicts y listas anidadas."""
    if isinstance(data, dict):
        red = {}
        for k, v in data.items():
            if k in _OCAPI_LOG_SECRET_KEYS and v:
                s = str(v)
                red[k] = '****' + (s[-4:] if len(s) > 8 else '')
            else:
                red[k] = _ocapi_redact_status(v)
        return red
    if isinstance(data, (list, tuple)):
        return [_ocapi_redact_status(x) for x in data]
    return data
import pdb
#from .warning import warning
import requests
import hashlib
from datetime import datetime, timedelta
import json
from odoo.tools import date_utils
import base64

import hashlib
from datetime import datetime

from .versions import *

class OcapiConnectionCredential(models.Model):

    _name = "ocapi.connection.credential"
    _description = "Odoo Connector Api Credentials"

    # [#caso-K19] Secretos/tokens: sólo un Administrador los ve por pantalla, RPC o exportación.
    # No se usa `groups=` en el campo: Odoo 19 también lo controla al leer desde Python y el
    # propio módulo los necesita para publicar en nombre de cualquier usuario.
    def _read_format(self, fnames, load='_classic_read'):
        return ocapi_hide_secrets(self, super()._read_format(fnames, load=load))

    def export_data(self, fields_to_export):
        return super().export_data(ocapi_strip_secret_export(self, fields_to_export))

    name = fields.Char(string='Name',index=True, required=True)

    client_id = fields.Char(string='Client Id/App Id', help='Client ID/App Id',size=128,index=True)
    secret_key = fields.Char(string='Secret Key/App Key', help='Secret Key/App Key',size=128,index=True)
    access_token = fields.Text( string='Access Token/Api Token', help='Access Token/Api Token',index=True)

    def get_connector_state(self):
        ocapi_state = True
        for connacc in self:
            connacc.state = ocapi_state

    state = fields.Boolean( compute='get_connector_state', string='State', help="Estado de la conexión", store=False )
    seller_id = fields.Char(string='App Seller Id', help='App Seller Id',size=128,index=True)

    def connect(self):
        _logger.info("OcapiConnectionCredential connect")

class OcapiConnectionAccount(models.Model):

    _name = "ocapi.connection.account"
    _description = "Odoo Connector Api Account Credentials and Configuration"
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin','image.mixin']

    # [#caso-K19] Secretos/tokens: sólo un Administrador los ve por pantalla, RPC o exportación.
    # No se usa `groups=` en el campo: Odoo 19 también lo controla al leer desde Python y el
    # propio módulo los necesita para publicar en nombre de cualquier usuario.
    def _read_format(self, fnames, load='_classic_read'):
        return ocapi_hide_secrets(self, super()._read_format(fnames, load=load))

    def export_data(self, fields_to_export):
        return super().export_data(ocapi_strip_secret_export(self, fields_to_export))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
            if not company._ocapi_security_allows('status'):
                vals['connection_monitor'] = False
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('connection_monitor'):
            for acc in self:
                if not (acc.company_id or self.env.company)._ocapi_security_allows('status'):
                    raise UserError(_("Con el Nivel de seguridad Alto de la compañía no se puede activar el Monitoreo."))
        return super().write(vals)

    def get_connector_version(self):
        for acc in self:
            acc.connector_version = ''
            cr = MeliCr( self )
            cr = MeliCr( self )
            # nombre del modulo como parametro (antes: armado con %); misma consulta (F8b 20.0)
            resquery = cr.execute("""select name, latest_version from ir_module_module where name like %s""", ("odoo_connector_api",))
            version_module_res = cr.fetchall()
            if version_module_res:
                acc.connector_version = str(version_module_res[0][1])


    connector_version = fields.Char( compute='get_connector_version', string='Connector Version', help="Versión de este conector", store=False )

    def get_ocapi_version(self):
        for acc in self:
            acc.ocapi_version = ''
            cr = MeliCr( self )
            cr = MeliCr( self )
            # nombre del modulo como parametro (antes: armado con %); misma consulta (F8b 20.0)
            resquery = cr.execute("""select name, latest_version from ir_module_module where name like %s""", ("odoo_connector_api",))
            version_module_res = cr.fetchall()
            if version_module_res:
                acc.ocapi_version = str(version_module_res[0][1])
    ocapi_version = fields.Char( compute='get_ocapi_version', string='OCAPI Version', help="Versión de OCAPI", store=False )

    def get_connector_state(self):
        ocapi_state = True
        for connacc in self:
            connacc.state = ocapi_state

    name = fields.Char(string='Name',index=True, required=True)
    type = fields.Selection([("custom","Custom")],string='Connector',index=True, required=True)
    company_id = fields.Many2one("res.company",string="Company",index=True, required=True)
    country_id = fields.Many2one("res.country",string="Country",index=True, required=True)

    client_id = fields.Char(string='Client Id/App Id', help='Client ID/App Id',size=128,index=True)
    secret_key = fields.Char(string='Secret Key/App Key', help='Secret Key/App Key',size=128,index=True)
    access_token = fields.Text( string='Access Token/Api Token', help='Access Token/Api Token',index=True)
    access_token_date = fields.Datetime( string="Alta token", index=True )
    access_token_date_expiration = fields.Datetime( string="Vencimiento token", index=True )
    state = fields.Boolean( compute='get_connector_state', string='State', help="Estado de la conexión", store=False )
    seller_id = fields.Char(string='App Seller Id', help='App Seller Id',size=128,index=True)
    connection_monitor = fields.Boolean( string="Monitoreo", default=True,
        help="Permite que el centro de soporte de Moldeo consulte desde afuera si esta cuenta está "
             "conectada (estado y vencimiento del token). Esa consulta no devuelve ventas, clientes ni "
             "productos, ni la clave secreta. Apagado: la consulta de estado no responde.\n"
             "Lo demás que se expone hacia afuera lo define el Nivel de seguridad de la compañía: con Alto "
             "esta casilla queda apagada y no se puede activar." )

    def get_messages_brief(self):

        for acc in self:
            acc.messages_brief = ""
            com = ""
            a = 0
            m = 3

            for mess in acc.message_ids:

                acc.messages_brief+= com + str(mess.body)

                a+= 1
                if (a>m):
                    break;
    messages_brief = fields.Text( compute='get_messages_brief', string="Messages Overview", help="Messages resume overview.", index=True )

    def get_configuration_brief(self):
        for acc in self:
            acc.configuration_brief = ""
            acc.configuration_brief = acc.get_json_configuration()

    configuration_brief = fields.Text( compute='get_configuration_brief', string="Configuration Overview", help="Configuration resume overview.", index=True )

    configuration = fields.Many2one( "ocapi.connection.configuration", string="Connection Parameters Configuration", help="Connection Parameters Configuration", required=True  )

    def get_json_configuration( self ):

        json_conf = ""
        #convertir el objeto en json...
        jc = 0
        jco = ""
        for acc in self:
            jc+= 1
            fields_configuration = []
            for field in acc.configuration._fields:
                fields_configuration+= [field]
                #field_value = acc.configuration[field]
                #try:
                #    field_value_json = json.dumps(field_value)
                #    conf_str[field] = field_value
                #except:
                #    conf_str[field] = field_value.display_name
                #    pass;

            raw_conf = acc.configuration.read(fields_configuration)

            json_conf+= jco + json.dumps( raw_conf[0], indent=2, default=_ocapi_json_default)
            jco = ","


        return json_conf

    def authorize_token(self, client_id, secret_key ):

        if not secret_key or not client_id or self.client_id != client_id or self.secret_key != secret_key:
            return { "error": "Bad credentials", "message": "Bad credentials, values does not match with any configuration" }

        now = datetime.now()

        if (self.access_token_date_expiration and now<self.access_token_date_expiration):
            return self.access_token

        date_time = now.strftime("%m/%d/%Y, %H:%M:%S")
        base_str = str(client_id) + str(secret_key) + str(date_time)

        hash = hashlib.blake2b()
        hash.update( base_str.encode() )
        hexhash = hash.hexdigest()

        access_token = hexhash
        self.access_token_date = now
        self.access_token_date_expiration = now + timedelta(hours=6)
        self.access_token = access_token

        return access_token

        #self.ocapi_access_token = "
        #self.ocapi_access_token = "MD5ABCDEF0123456789"
    #try to authorize:

    def get_fields_credentials( self ):

        fields_credentials = []

        for acc in self:
            if (acc.type == "custom"):
                # /status nunca devuelve secret_key ni refresh_token: quien consulta ya se
                # autentico con el access_token, y devolverle la credencial permanente es una
                # escalada (analisis caso-K52 cliente X, 27-oct-2026). Nadie los consume: el OFF
                # pide /ocapi/<modulo>/status sin channel.
                # 26.390: el access_token tampoco (aunque el que pregunta ya lo tenga, un /status
                # no devuelve valores de secretos): fetch_status informa access_token_present.
                fields_credentials+= [ 'client_id', 'seller_id']
                fields_credentials+= [ 'state','access_token_date','access_token_date_expiration']

        return fields_credentials

    def get_fields_status( self ):
        fields_status = []

        for acc in self:
            fields_credentials = acc.get_fields_credentials()
            fields_status+= [
                'name', 'company_id',  'country_id',
                'type', 'connector_version','ocapi_version'
            ]+fields_credentials

        return fields_status

    def fetch_status( self, **post ):
        _logger.info("ocapi.account > fetch_status")
        result = []
        for acc in self:
            
            if not acc.connection_monitor:
                json_status = {
                    "status": "monitor down"
                }
                result.append(json_status)
                continue;
            
            json_status = {
                "status": "connected"
            }
            fields_status = acc.get_fields_status()
            raw_data = acc and acc.read(fields_status)

            if raw_data and raw_data[0]:
                #json_status = json.dumps( raw_data, default=_ocapi_json_default)
                json_status = json.loads( json.dumps( raw_data[0], default=_ocapi_json_default) )
                # 26.390 (seguridad): NUNCA valores de secretos en el /status, aunque un módulo
                # hijo los agregue a get_fields_credentials. Sólo presencia.
                for k in [k for k in json_status if k.endswith(OCAPI_STATUS_SECRET_SUFFIXES)]:
                    json_status.pop(k, None)
                json_status["access_token_present"] = bool(acc.access_token)

            result.append(json_status)

        _logger.info("ocapi.account > fetch_status result: "+str(_ocapi_redact_status(result)))
        return result

    def fetch_githook( self, **post ):
        _logger.info("fetch_githook")
        result = []
        json_status = {
            "githook": "received"
        }
        result.append(json_status)
        _logger.info(result)
        return result

    def list_catalog( self, **post ):
        _logger.info("list_catalog")
        result = []
        #catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',self.ids)])
        #catalog = self.env["product.template"].search([])
        bindings = self.env["ocapi.connection.binding.product_template"].search([('connection_account','=',self.id)])
        _logger.info(bindings)
        for bind in bindings:
            _logger.info(bind)

        catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',bindings.ids)])
        for product_tmpl in catalog:
            _logger.info(product_tmpl)
            pjson = {
                "name": product_tmpl.name,
                "sku": product_tmpl.default_code
            }
            result.append(pjson)

        _logger.info(result)
        return result

    def list_pricestock( self, **post ):
        _logger.info("list_pricestock")
        _logger.info(_ocapi_redact_status(post))
        _logger.info(self)
        result = []
        #catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',self.ids)])
        #catalog = self.env["product.template"].search([])
        bindings = self.env["ocapi.connection.binding.product_template"].search([('connection_account','=',self.id)])
        _logger.info(bindings)
        for bind in bindings:
            _logger.info(bind)

        catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',bindings.ids)])
        for product_tmpl in catalog:
            #_logger.info('Product name --->>>   ' + str(product_tmpl.name ))
            pjson = {
                "name": product_tmpl.name,
                "sku": product_tmpl.default_code,
            }
            result.append(pjson)

        _logger.info(result)
        return result

    def list_pricelist( self, **post ):
        _logger.info("list_pricelist")
        result = []
        #catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',self.ids)])
        #catalog = self.env["product.template"].search([])
        bindings = self.env["ocapi.connection.binding.product_template"].search([('connection_account','=',self.id)])
        _logger.info(bindings)
        for bind in bindings:
            _logger.info(bind)

        catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',bindings.ids)])
        for product_tmpl in catalog:
            _logger.info(product_tmpl)
            pjson = {
                "name": product_tmpl.name,
                "sku": product_tmpl.default_code,
            }
            result.append(pjson)

        _logger.info(result)
        return result

    def list_stock( self, **post ):
        _logger.info("list_stock")
        result = []
        #catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',self.ids)])
        #catalog = self.env["product.template"].search([])
        bindings = self.env["ocapi.connection.binding.product_template"].search([('connection_account','=',self.id)])
        _logger.info(bindings)
        for bind in bindings:
            _logger.info(bind)

        catalog = self.env["product.template"].search([('ocapi_connection_bindings','in',bindings.ids)])
        for product_tmpl in catalog:
            _logger.info(product_tmpl)
            pjson = {
                "name": product_tmpl.name,
                "sku": product_tmpl.default_code,
            }
            result.append(pjson)

        _logger.info(result)
        return result

    def import_sales( self, **post ):
        _logger.info("import_sales")
        try:
            internals = {
                "connection_account": self,
                "application_id": self.client_id or '',
                "user_id": self.seller_id or '',
                "topic": "sales",
                "resource": "import_sales",
                "state": "PROCESSING"
            }
            noti = self.env["ocapi.connection.notification"].start_internal_notification( internals )
            logs = "to implement"
            errors = "to implement"

            #do all your stuff here...
            #....
            #....

            noti.stop_internal_notification(errors=errors,logs=logs)
        except:
            _logger.error("import_sales error")
            pass;
        result = []
        _logger.info(result)
        return result

    # ==================================================================
    # OCAPI Generic Publishing Protocol
    # ==================================================================
    # Base methods that each connector should override to support
    # generic publishing via OCAPI. See docs/GENERIC_PUBLISHING.md
    # ==================================================================

    def ocapi_get_capabilities(self):
        """Return this connector's publishing capabilities.

        Each connector overrides this to declare what it supports.
        Returns a dict with boolean flags and numeric limits.
        """
        return {
            'can_publish_products': False,
            'can_publish_images': False,
            'can_publish_descriptions': False,
            'can_publish_prices': False,
            'can_publish_stock': False,
            'can_import_orders': False,
            'can_sync_categories': False,
            'supported_image_formats': [],
            'max_images_per_product': 0,
            'max_title_length': 0,
            'max_description_length': 0,
            'requires_category': False,
            'supports_variants': False,
        }

    def ocapi_publish_product(self, product_data):
        """Publish a product using OCAPI standard format.

        Args:
            product_data (dict): Standard OCAPI product dict with keys:
                name, description, short_description, sku, price, currency,
                stock, images, category_id, attributes, weight, dimensions,
                source_model, source_id.

        Returns:
            dict: {success, external_id, external_url, error, binding_data}
        """
        self.ensure_one()
        return {
            'success': False,
            'error': _('Publishing not implemented for connector type: %s') % self.type,
        }

    def ocapi_update_product(self, external_id, product_data):
        """Update an already-published product.

        Args:
            external_id (str): The external platform ID of the product.
            product_data (dict): Updated product data in OCAPI format.

        Returns:
            dict: {success, error}
        """
        self.ensure_one()
        return {
            'success': False,
            'error': _('Update not implemented for connector type: %s') % self.type,
        }

    def ocapi_unpublish_product(self, external_id):
        """Unpublish / deactivate a product on the external platform.

        Args:
            external_id (str): The external platform ID of the product.

        Returns:
            dict: {success, error}
        """
        self.ensure_one()
        return {
            'success': False,
            'error': _('Unpublish not implemented for connector type: %s') % self.type,
        }

    def ocapi_get_product_status(self, external_id):
        """Get the current status of a published product.

        Args:
            external_id (str): The external platform ID.

        Returns:
            dict: {success, status, external_url, error}
        """
        self.ensure_one()
        return {
            'success': False,
            'error': _('Status check not implemented for connector type: %s') % self.type,
        }

    def ocapi_publish_image(self, image_data):
        """Upload an image to the connector platform.

        Args:
            image_data (dict): {data (base64), name, sequence, mime_type}

        Returns:
            dict: {success, external_id, external_url, error}
        """
        self.ensure_one()
        return {
            'success': False,
            'error': _('Image upload not implemented for connector type: %s') % self.type,
        }
