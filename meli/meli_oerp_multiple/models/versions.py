# -*- coding: utf-8 -*-
from dateutil.parser import *
from datetime import *
import logging
_logger = logging.getLogger(__name__)

# Odoo version 18.0

# Odoo 18.0 -> type='json', Odoo 19.0 -> type='jsonrpc'
route_typejson = "json"

# Odoo < 17.0 -> 'tree', Odoo 17.0+ -> 'list'
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
acc_inv_model  = "account.move"

# default_create_variant
default_no_create_variant = "no_variant"
default_create_variant = "always"

#SOME COUNTRIES BLOCK user_product_seller_id multi origin updates
default_active_user_product_id_multi_stock = False

#'unique(product_tmpl_id,meli_imagen_id)'
unique_meli_imagen_id_fields = 'unique(product_tmpl_id,product_variant_id,meli_imagen_id)'

#variant mage ids
def variant_image_ids(self):
    return self.product_variant_image_ids

#template image ids
def template_image_ids(self):
    return self.product_template_image_ids


#att value ids
def att_value_ids(self):
    return self.product_template_attribute_value_ids

#att line ids
def att_line_ids(self):
    return self.attribute_line_ids

def get_image_full(self):
    return self.image_1920

def set_image_full(self, image):
    self.image_1920 = image
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
        datestr = str(datestr)
        return parse(datestr).strftime('%Y-%m-%d %H:%M:%S')
    except:
        _logger.error(datestr)
        return None

def ml_tax_excluded(self, config=None):
    """[caso-K11/caso-K10] (19-oct-2026) Ver meli_oerp/models/versions.py ml_tax_excluded: `auto` usaba un grupo
    que existe solo hasta Odoo 16; en 17+ ya resolvia False. Se deja explicito, mismo significado."""
    config = config or self.env.user.company_id
    if (config and config.mercadolibre_tax_included not in ['auto']):
        return (config.mercadolibre_tax_included in ['tax_excluded'])
    #11.0: 'sale.group_show_price_subtotal' / 12.0 a 16.0: el grupo de abajo / 17.0+: no existe
    if self.env.ref('account.group_show_line_subtotals_tax_excluded', raise_if_not_found=False):
        return self.env.user.has_group('account.group_show_line_subtotals_tax_excluded')
    return False

def ml_sale_tax_rates(taxes, company=None):
    """[caso-K10] (19-oct-2026) (porcentaje, fijo) de los impuestos de VENTA no incluidos, SOLO de `company`.
    Copia de meli_oerp.models.versions.ml_sale_tax_rates (aca para no exigir un meli_oerp nuevo al cargar)."""
    txpercent = 0.0
    txfixed = 0.0
    for txid in (taxes or []):
        if company and txid.company_id and txid.company_id != company:
            continue
        if (txid.type_tax_use == "sale" and not txid.price_include):
            if (txid.amount_type == "percent"):
                txpercent = txpercent + txid.amount
            if (txid.amount_type == "fixed"):
                txfixed = txfixed + txid.amount
    return txpercent, txfixed

def get_inventory_fields( product, warehouse ):
    return {
            "product_ids": [(4,product.id)],
            #"product_id": product.id,
            #"filter": "product",
            #"location_id": warehouse,
            "name": "INV: "+ product.name
            }

def meli_get_delivery_line( sorder ):
    """Linea de envio de la venta (la que marca is_delivery), o None."""
    lines = sorder.order_line.filtered(lambda l: l.is_delivery)
    return lines[0] if lines else None


def set_delivery_line( sorder, delivery_price, delivery_message ):
    """Setea el precio de la linea de envio SIN riesgo de perderla.

    El core (delivery/models/sale_order.py::set_delivery_line) ejecuta, EN ESTE ORDEN:
        _remove_delivery_line()  ->  carrier_id = carrier.id  ->  _create_delivery_line(...)
    Si el carrier viene VACIO, o si la escritura/creacion posterior falla (compania
    incompatible, orden facturada, impuestos), el BORRADO ya ocurrio: la venta queda sin
    linea de envio y sin transportista, y el flete no se factura nunca mas. Antes esa
    excepcion se tragaba con un except pelado y el borrado quedaba hecho.

    Por eso:
      1) sin carrier valido NO se llama al core -> se actualiza el precio de la linea existente;
      2) la llamada al core va dentro de un savepoint -> si falla despues del borrado, se
         deshace el borrado en vez de dejar la venta pelada.

    Caso que lo destapo (un cliente, jul-2026): 47 ordenes quedaron sin flete y 20 se
    facturaron de menos porque el conector borraba la linea de envio que el mismo habia creado.
    """
    carrier = sorder.carrier_id

    if not carrier:
        # Sin transportista el core borraria la linea y no crearia ninguna.
        oline = meli_get_delivery_line(sorder)
        if oline and abs(oline.price_unit - float(delivery_price)) > 0.01:
            oline.price_unit = delivery_price
        _logger.warning(
            "MELI set_delivery_line: venta %s sin transportista; se conserva la linea de envio "
            "(precio %s) en lugar de recrearla.", sorder.name, delivery_price)
    else:
        try:
            with sorder.env.cr.savepoint():
                sorder.set_delivery_line(carrier, delivery_price)
            oline = meli_get_delivery_line(sorder)
        except Exception as e:
            # El savepoint deshizo el borrado: la linea previa sigue viva.
            oline = meli_get_delivery_line(sorder)
            _logger.warning(
                "MELI set_delivery_line: no se pudo reescribir la linea de envio de %s (%s); "
                "se conserva la linea existente.", sorder.name, e)

    sorder.write({
    	'recompute_delivery_price': False,
    	'delivery_message': delivery_message,
    })
    return oline


def meli_is_auth_error(rjson):
    """[caso-K11] (19-oct-2026) ¿La respuesta de ML es un rechazo del TOKEN?

    Con el token vencido ML responde HTTP 401 {"code": "unauthorized", "message": "invalid access token"},
    SIN las claves `error` ni `status` (medido en producto 1 19-oct). Los chequeos de siempre no lo veian:
    no se refrescaba el token y el barrido de ordenes lo leia como "no hay ordenes nuevas".
    (Igual a meli_oerp.models.meli_util.meli_is_auth_error; copia para no exigir un meli_oerp nuevo.)
    """
    if not isinstance(rjson, dict):
        return False
    code = str(rjson.get("code") or rjson.get("error") or "").lower()
    message = str(rjson.get("message") or "").lower()
    status = rjson.get("status")
    try:
        status = int(status) if status not in (None, "") else 0
    except (TypeError, ValueError):
        status = 0
    if status == 401 or code in ("unauthorized", "invalid_token", "expired_token", "invalid_grant"):
        return True
    return ("access token" in message or "access_token" in message) and ("invalid" in message or "expired" in message)
