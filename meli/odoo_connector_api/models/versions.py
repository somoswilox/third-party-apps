# -*- coding: utf-8 -*-
from dateutil.parser import *
from datetime import *
import logging
_logger = logging.getLogger(__name__)

# Odoo version 18.0

# Odoo 18.0 -> type='json', Odoo 19.0 -> type='jsonrpc'
route_typejson = "json"
view_mode_tree = 'list'

# ---------------------------------------------------------------------------
# UniqueIndex vs _sql_constraints  (Odoo < 17  vs  Odoo 17+)
# ---------------------------------------------------------------------------
HAS_UNIQUE_INDEX = False
_OdooUniqueIndex = None
try:
    from odoo.models import UniqueIndex as _OdooUniqueIndex
    HAS_UNIQUE_INDEX = True
    _logger.info("versions: models.UniqueIndex disponible (Odoo 17+)")
except (ImportError, AttributeError):
    _logger.info("versions: models.UniqueIndex no disponible - usando _sql_constraints")

def UniqueIndex(fields_expr, message=None):
    if _OdooUniqueIndex is not None:
        if message is not None:
            return _OdooUniqueIndex('(%s)' % fields_expr, message=message)
        return _OdooUniqueIndex('(%s)' % fields_expr)
    return None

def sql_constraints_if_no_unique_index(constraints):
    if HAS_UNIQUE_INDEX:
        return []
    return [
        (name, 'unique(%s)' % fields, msg)
        for name, fields, msg in constraints
    ]
# ---------------------------------------------------------------------------
# Constraint (arbitrary SQL CHECK constraints)  —  Odoo 19+
# ---------------------------------------------------------------------------
_OdooConstraint = None
try:
    from odoo.models import Constraint as _OdooConstraint
except (ImportError, AttributeError):
    pass

def Constraint(sql_expr, message=None):
    if _OdooConstraint is not None:
        if message is not None:
            return _OdooConstraint(sql_expr, message=message)
        return _OdooConstraint(sql_expr)
    return None

def sql_constraints_if_no_constraint(constraints):
    if _OdooConstraint is not None:
        return []
    return [(name, sql_expr, msg) for name, sql_expr, msg in constraints]
# ---------------------------------------------------------------------------

# Odoo 12.0 -> Odoo 13.0
uom_model = "uom.uom"

# Odoo 12.0 -> Odoo 13.0
prod_att_line = "product.template.attribute.line"

# account
acc_inv_model  = "account.invoice"

# default_create_variant
default_no_create_variant = "no_variant"
default_create_variant = "always"

def MeliCr( self ):
    return self.env.cr
    #or return self._cr

def MeliCommit( self ):
    # flush_all() en vez de cr.commit(): fuerza writes ORM al DB dentro de la
    # transacción actual sin hacer COMMIT. Un cr.commit() destruiría savepoints
    # activos (ej: wizard batch usa 'with env.cr.savepoint()') causando
    # "savepoint does not exist" y aborto de la transacción en cascada.
    return self.env.flush_all();

def MeliRollback( self ):
    return self.env.cr.rollback();

#variant mage ids
def variant_image_ids(self):
    return self.product_image_ids

#template image ids
def template_image_ids(self):
    #return self.product_image_ids
    return None

#att value ids
def att_value_ids(self):
    return self.attribute_value_ids

#att line ids
def att_line_ids(self):
    return self.attribute_value_ids


def get_image_full(self):
    return self.image

def set_image_full(self, image):
    self.image = image
    return True

def get_first_image_to_publish(self):
    company = self.env.user.company_id
    product = self
    first_image_to_publish = None

    if (company.mercadolibre_do_not_use_first_image):
        image_ids = variant_image_ids(product)
        if (len(image_ids)):
            #Use first image of variant image ids: product.image
            first_image_to_publish = get_image_full(image_ids[0])
    else:
        first_image_to_publish = get_image_full(product)

    return first_image_to_publish

def prepare_attribute( product_template_id, attribute_id, attribute_value_id ):
    att_vals = { 'attribute_id': attribute_id,
                 'value_ids': [(4,attribute_value_id)],
                 'product_tmpl_id': product_template_id
               }
    return att_vals

def stock_inventory_action_done( self ):
    return_id = self.post_inventory()
    return_id = self.action_start()
    return_id = self.action_validate()
    return return_id

def ml_datetime(datestr):
    try:
        #return parse(datestr).isoformat().replace("T"," ")
        return parse(datestr).strftime('%Y-%m-%d %H:%M:%S')
    except:
        _logger.error(datestr)
        return None

def ml_tax_excluded(self):
    #11.0
    #tax_excluded = self.env.user.has_group('sale.group_show_price_subtotal')
    #12.0 and 13.0
    tax_excluded = self.env.user.has_group('account.group_show_line_subtotals_tax_excluded')
    company = self.env.user.company_id
    if (company and company.mercadolibre_tax_included not in ['auto']):
        tax_excluded = (company.mercadolibre_tax_included in ['tax_excluded'])
    return tax_excluded


# ===========================================================================
# OCAPI Connector Detection (added by ocapi_sale_* bridges)
# ===========================================================================
# Funciones nuevas para el ecosistema OCAPI.
# NO modifican ninguna funcion legacy de arriba.
# Cada modulo derivado tiene su propio versions.py con sus propias versiones
# actualizadas de las funciones legacy (meli_oerp, producteca, etc.)
# ===========================================================================

def _check_module_installed(env, module_name):
    """Verifica si un modulo de Odoo esta instalado."""
    module = env['ir.module.module'].sudo().search([
        ('name', '=', module_name),
        ('state', '=', 'installed'),
    ], limit=1)
    return bool(module)

def _check_model_exists(env, model_name):
    """Verifica si un modelo de Odoo existe en el registry."""
    return model_name in env

def get_installed_native_connectors(env):
    """
    Detecta que conectores nativos de Odoo estan instalados.
    Retorna dict con nombre -> info del conector.
    """
    connectors = {}

    # Amazon
    if _check_module_installed(env, 'sale_amazon'):
        connectors['amazon'] = {
            'module': 'sale_amazon',
            'account_model': 'amazon.account',
            'binding_model': 'amazon.offer',
        }

    # eBay
    if _check_module_installed(env, 'sale_ebay'):
        connectors['ebay'] = {
            'module': 'sale_ebay',
            'account_model': None,
            'binding_model': None,
            'uses_config_parameter': True,
        }

    # Shopee (solo 18.0+)
    if _check_module_installed(env, 'sale_shopee'):
        connectors['shopee'] = {
            'module': 'sale_shopee',
            'account_model': 'shopee.account',
            'shop_model': 'shopee.shop',
            'binding_model': 'shopee.item',
        }

    return connectors

def get_installed_ocapi_connectors(env):
    """
    Detecta que conectores OCAPI propios estan instalados.
    Retorna dict con tipo -> modelo de cuenta.
    """
    connectors = {}

    if _check_model_exists(env, 'mercadolibre.account'):
        connectors['mercadolibre'] = {
            'module': 'meli_oerp_multiple',
            'account_model': 'mercadolibre.account',
        }

    if _check_model_exists(env, 'producteca.account'):
        connectors['producteca'] = {
            'module': 'odoo_connector_api_producteca',
            'account_model': 'producteca.account',
        }

    if _check_model_exists(env, 'fulfillment.account'):
        connectors['fulfillment'] = {
            'module': 'odoo_connector_api_fulfillment',
            'account_model': 'fulfillment.account',
        }

    if _check_model_exists(env, 'ldps.account'):
        connectors['ldps'] = {
            'module': 'odoo_connector_api_ldps',
            'account_model': 'ldps.account',
        }

    return connectors
