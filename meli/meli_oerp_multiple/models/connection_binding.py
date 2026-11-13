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
import logging
_logger = logging.getLogger(__name__)


# 26.278 (#caso-K31): publicar SOLO el plazo de entrega (sale_term MANUFACTURING_TIME).
# Pedido de un cliente (16-sep): "Actualizar" reenvia la ficha completa y la validacion
# local del titulo (60 caracteres) aborta la operacion entera, aunque el item ya esta
# publicado. Medido entonces contra la API: PUT /items/{id} con solo sale_terms
# MANUFACTURING_TIME es ACEPTADO y deja el titulo intacto. Por las dudas de que ML
# reemplace la lista entera de sale_terms, se LEEN los vigentes y se reenvian junto al
# plazo (la garantia no se pierde). Funcion pura: se prueba sin red.
def meli_sale_terms_with_manufacturing_time(sale_terms, value):
    out = []
    for t in (sale_terms or []):
        if not isinstance(t, dict) or not t.get("id") or t.get("id") == "MANUFACTURING_TIME":
            continue
        if t.get("value_id"):
            out.append({"id": t["id"], "value_id": t["value_id"]})
        elif t.get("value_name"):
            out.append({"id": t["id"], "value_name": t["value_name"]})
    out.append({"id": "MANUFACTURING_TIME", "value_name": value})
    return out


def _meli_post_manufacturing_time(meli, meli_id, value):
    """GET del item -> PUT solo de sale_terms. :return: {} en OK, dict con 'error' si no."""
    try:
        response = meli.get("/items/" + str(meli_id), {"access_token": meli.access_token})
        rjson = response.json() if response is not None else {}
        if not isinstance(rjson, dict) or rjson.get("error"):
            return rjson if isinstance(rjson, dict) else {"error": "get_item", "message": str(rjson)}
        body = {"sale_terms": meli_sale_terms_with_manufacturing_time(rjson.get("sale_terms"), value)}
        response = meli.put_mini("/items/" + str(meli_id), body, {"access_token": meli.access_token})
        pjson = response.json() if response is not None else {}
        if isinstance(pjson, dict) and pjson.get("error"):
            _logger.error("post manufacturing_time /items/%s: %s", meli_id, pjson)
            return pjson
        _logger.info("Posted manufacturing_time ok /items/%s: %s", meli_id, value)
        return {}
    except Exception as e:
        _logger.error("post manufacturing_time exception /items/%s: %s", meli_id, e)
        return {"error": "exception", "message": str(e)}


def _meli_manufacturing_time_action_result(res, count):
    if isinstance(res, dict) and res.get("type"):
        return res   # redirect de login
    if isinstance(res, dict) and res.get("error"):
        raise UserError("MercadoLibre no aceptó el plazo de entrega: %s" % (
            res.get("message") or res.get("error")))
    return {
        "type": "ir.actions.client", "tag": "display_notification",
        "params": {"title": "Plazo de entrega",
                   "message": "Plazo publicado en %s publicación(es)." % count,
                   "type": "success", "sticky": False},
    }
import pdb
#from .warning import warning
import requests
import math
import json
import ast
from . import versions
from .versions import *
from odoo.addons.meli_oerp.models.versions import meli_message_post, meli_payment_method_line_for, meli_money_block_post
from odoo.addons.meli_oerp.models.versions import *

from odoo.exceptions import UserError, ValidationError
from odoo.addons.meli_oerp_accounting.models.versions import payment_group_post as _meli_payment_post
from odoo.addons.meli_oerp.models.versions import *


# Site ID → URLs per country MercadoLibre. Ordenado como company.get_ML_LINK_URL()
# pero extendido con el dominio de artículo (diferente en MLB: produto.mercadolivre.com.br).
# Usamos este map offline para no hacer API calls en el compute del formulario producto.
_ML_SITE_URLS = {
    "MLA": {"link": "https://www.mercadolibre.com.ar", "articulo": "https://articulo.mercadolibre.com.ar"},
    "MLM": {"link": "https://www.mercadolibre.com.mx", "articulo": "https://articulo.mercadolibre.com.mx"},
    "MCO": {"link": "https://www.mercadolibre.com.co", "articulo": "https://articulo.mercadolibre.com.co"},
    "MPE": {"link": "https://www.mercadolibre.com.pe", "articulo": "https://articulo.mercadolibre.com.pe"},
    "MBO": {"link": "https://www.mercadolibre.com.bo", "articulo": "https://articulo.mercadolibre.com.bo"},
    "MLB": {"link": "https://www.mercadolivre.com.br", "articulo": "https://produto.mercadolivre.com.br"},
    "MLC": {"link": "https://www.mercadolibre.cl",     "articulo": "https://articulo.mercadolibre.cl"},
    "MCR": {"link": "https://www.mercadolibre.com.cr", "articulo": "https://articulo.mercadolibre.com.cr"},
    "MLV": {"link": "https://www.mercadolibre.com.ve", "articulo": "https://articulo.mercadolibre.com.ve"},
    "MRD": {"link": "https://www.mercadolibre.com.do", "articulo": "https://articulo.mercadolibre.com.do"},
    "MPA": {"link": "https://www.mercadolibre.com.pa", "articulo": "https://articulo.mercadolibre.com.pa"},
    "MPY": {"link": "https://www.mercadolibre.com.py", "articulo": "https://articulo.mercadolibre.com.py"},
    "MEC": {"link": "https://www.mercadolibre.com.ec", "articulo": "https://articulo.mercadolibre.com.ec"},
    "MLU": {"link": "https://www.mercadolibre.com.uy", "articulo": "https://articulo.mercadolibre.com.uy"},
}

# Fallback de país → site_id cuando account.meli_user_site_id no está seteado.
# Alineado con company._get_ML_sites (país y currency).
_COUNTRY_TO_ML_SITE = {
    "AR": "MLA", "MX": "MLM", "CO": "MCO", "PE": "MPE", "BO": "MBO",
    "BR": "MLB", "CL": "MLC", "CR": "MCR", "VE": "MLV", "DO": "MRD",
    "PA": "MPA", "PY": "MPY", "EC": "MEC", "UY": "MLU",
}


def _resolve_ml_site_urls(account=None, company=None):
    """Resuelve site_id y URLs sin llamar a la API de ML.

    Acepta account y/o company (ambos opcionales). Orden de prioridad:
      1. account.meli_user_site_id (definitivo: lo setea /users/me en login)
      2. (account.company_id o company).country_id.code → _COUNTRY_TO_ML_SITE
      3. "MLA" (último fallback, consistente con company.get_ML_LINK_URL)

    Reutilizable desde cualquier modelo (binding, wizard, etc.) — no hace
    SQL ni HTTP.
    """
    site_id = (account and account.meli_user_site_id) or None
    if not site_id:
        _company = company or (account and account.company_id) or None
        country_code = (
            _company
            and _company.country_id
            and _company.country_id.code
        ) or None
        site_id = _COUNTRY_TO_ML_SITE.get(country_code, "MLA")
    return site_id, _ML_SITE_URLS.get(site_id, _ML_SITE_URLS["MLA"])


def _meli_permalink_from_id(meli_id, site_urls):
    """URL canónica corta desde el meli_id: https://domain/SITE-NUMERICID.
    site_urls es el dict _urls retornado por _resolve_ml_site_urls."""
    if not meli_id:
        return ''
    k = next((i for i, c in enumerate(meli_id) if c.isdigit()), len(meli_id))
    if k >= len(meli_id):
        return ''
    return site_urls.get("articulo", "https://www.mercadolibre.com") + "/" + meli_id[:k] + "-" + meli_id[k:]


#: Estados de item de ML que el Selection `meli_last_status` sabe guardar.
#: ML tambien devuelve `payment_required` y `not_yet_active`, que NO estan en el
#: Selection: escribirlos reventaria con ValueError, asi que se descartan (con log).
MELI_ITEM_STATUSES = ('active', 'paused', 'closed', 'deleted', 'not_found', 'under_review', 'inactive')


def meli_status_from_rjson(rjson):
    """Estado de item ML listo para escribir en `meli_last_status`, o None.

    26.123 (caso-K32 cliente N): el binding nacia SIN `meli_last_status` porque el
    publish no lo estampaba, y `meli_status` (no stored) cae a "unknown" => la
    ficha no muestra el icono/los botones de ML. El dato ya viene en la respuesta
    del POST/PUT y en el re-fetch que el publish YA hace: no cuesta un GET extra.
    """
    if not rjson or not isinstance(rjson, dict):
        return None
    status = rjson.get('status')
    if not status:
        return None
    status = str(status).strip().lower()
    if status not in MELI_ITEM_STATUSES:
        _logger.info("meli_status_from_rjson: status '%s' fuera del Selection meli_last_status, no se guarda", status)
        return None
    return status


class MercadoLibreConnectionBinding(models.Model):

    _name = "mercadolibre.binding"
    _description = "MercadoLibre Connection Binding"
    _inherit = "ocapi.connection.binding"

    #Connection reference defining mkt place credentials
    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )

class MercadoLibreConnectionBindingProductTemplate(models.Model):

    _name = "mercadolibre.product_template"
    _description = "MercadoLibre Product Binding Product Template"
    _inherit = "ocapi.connection.binding.product_template"

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )
    company_id = fields.Many2one("res.company", related="connection_account.company_id",string="Company")
    variant_bindings = fields.One2many("mercadolibre.product","binding_product_tmpl_id",string="Product Variant Bindings")

    image_bindings = fields.One2many('mercadolibre.product.image', "binding_product_tmpl_id", string="Product Template Images")

    active = fields.Boolean(string="Product Template Active",related="product_tmpl_id.active",index=True)

    orphan_reason = fields.Selection([
        ('ok', 'OK'),
        ('unassigned', 'Template desasignado'),
        ('product_archived', 'Producto archivado'),
        ('ml_all_dead', 'Todas las publicaciones muertas en ML'),
    ], string="Estado de vinculación", compute='_compute_orphan_reason', store=True, index=True)

    @api.depends('product_tmpl_id', 'product_tmpl_id.active', 'variant_bindings.orphan_reason')
    def _compute_orphan_reason(self):
        for bind in self:
            if not bind.product_tmpl_id:
                bind.orphan_reason = 'unassigned'
            elif bind.product_tmpl_id and not bind.product_tmpl_id.active:
                bind.orphan_reason = 'product_archived'
            elif bind.variant_bindings and all(
                v.orphan_reason in ('ml_closed', 'ml_not_found', 'ml_inactive', 'ml_deleted')
                for v in bind.variant_bindings
            ):
                bind.orphan_reason = 'ml_all_dead'
            else:
                bind.orphan_reason = 'ok'

    meli_title = fields.Char(string='Nombre del producto en Mercado Libre',size=256,index=True)
    meli_family_name = fields.Char(string='Nombre de la familia del user product en Mercado Libre',size=256)
    meli_family_id = fields.Char(string='ID de familia ML (user_product_seller)',size=128,index=True)
    # #caso-K21 (26.371): con qué camino se publicó. 'classic' = «Publicar» de siempre; 'family' = «Publicar
    # (nuevo)»: modo familia en cuentas user_product, una publicación por variante en cuentas clásicas.
    # Los updates (crons, asistentes) siguen el camino que diga ESTE campo, no el botón que se use después.
    meli_post_mode = fields.Selection([('classic', 'Clásico (Publicar)'), ('family', 'Nuevo (Publicar nuevo)')],
                                      string='Camino de publicación', default='classic', copy=False,
                                      help='Con qué asistente se creó la publicación. Las actualizaciones siguen ese camino.')
    meli_description = fields.Text(string='Descripción')
    meli_category = fields.Many2one("mercadolibre.category",string="Categoría de MercadoLibre")
    meli_buying_mode = fields.Selection( [("buy_it_now","Compre ahora"),("classified","Clasificado")], string='Método de compra')
    meli_price = fields.Char(string='Precio de venta', size=128,index=True)
    meli_price_fixed = fields.Boolean(string='Price is fixed')
    meli_pricelist = fields.Many2one("product.pricelist",string="Pricelist")
    meli_official_store_id = fields.Char(string="ML Off. Store Id",index=True)

    #link_edit = fields.Char(compute='_compute_link_edit', string='Link edit')

    meli_free_shipping = fields.Boolean(string='Envío gratis')
    meli_local_pick_up = fields.Boolean(string='Recoger en tienda')

    def _compute_link_edit(self):
        for record in self:
            link_edit = False
            if record.variant_bindings:
                link_edit = record.variant_bindings[0].meli_permalink_edit
            record.link_edit = link_edit


    @api.onchange('meli_price_fixed')
    def _onchange_meli_price_fixed( self ):
        #_logger.info("bind tpl _onchange_meli_price_fixed:"+str(self and self.name))
        for bindT in self:
            #_logger.info("bind tpl  _onchange_meli_price_fixed:"+str(bindT))
            #product = self._origin
            #product = self
            for bindV in bindT.variant_bindings:
                #_logger.info("bind tpl  _onchange_meli_price_fixed before::"+str(bindV.meli_price_fixed)+" new:"+str(bindT.meli_price_fixed))
                #bindV.write({'meli_price_fixed': bindT.meli_price_fixed})
                bindV.meli_price_fixed = bindT.meli_price_fixed

    @api.onchange('meli_price')
    def _onchange_meli_price( self ):
        #_logger.info("bind tpl _onchange_meli_price meli_price:"+str(self and self.name))
        for bindT in self:
            #_logger.info("bind tpl  _onchange_meli_price:"+str(bindT))
            #product = self._origin
            #product = self
            for bindV in bindT.variant_bindings:
                #_logger.info("bind tpl  _onchange_meli_price before::"+str(bindV.meli_price)+" new:"+str(bindT.meli_price))
                #bindV.write({'meli_price': bindT.meli_price})
                bindV.meli_price = bindT.meli_price

    @api.onchange('meli_pricelist')
    def _onchange_meli_pricelist( self ):
        #_logger.info("_onchange_meli_pricelist:"+str(self and self.name))
        for bindT in self:
            #_logger.info("_onchange_meli_pricelist:"+str(bindT))
            #product = self._origin
            #product = self
            for bindV in bindT.variant_bindings:
                #_logger.info("bind tpl  _onchange_meli_pricelist before::"+str(bindV.meli_pricelist)+" new:"+str(bindT.meli_pricelist))
                #bindV.write({'meli_pricelist': bindT.meli_pricelist})
                bindV.meli_pricelist = bindT.meli_pricelist


    meli_currency = fields.Selection([("ARS","Peso Argentino (ARS)"),
                                    ("MXN","Peso Mexicano (MXN)"),
                                    ("COP","Peso Colombiano (COP)"),
                                    ("PEN","Sol Peruano (PEN)"),
                                    ("BOB","Boliviano (BOB)"),
                                    ("BRL","Real (BRL)"),
                                    ("CLP","Peso Chileno (CLP)"),
                                    ("CRC","Colon Costarricense (CRC)"),
                                    ("UYU","Peso Uruguayo (UYU)"),
                                    ("VES","Bolivar Soberano (VES)"),
                                    ("PAB","Balboa Panameño (PAB)"),
                                    ("USD","Dolar Estadounidense (USD)")],
                                    string='Moneda')
    meli_condition = fields.Selection([ ("new", "Nuevo"),
                                        ("used", "Usado"),
                                        ("not_specified","No especificado")],
                                        'Condición del producto')
    meli_dimensions = fields.Char( string="Dimensiones del producto", size=128)
    meli_pub = fields.Boolean('Meli Publication',help='MELI Product',index=True)
    meli_master = fields.Boolean('Meli Producto Maestro',help='MELI Product Maestro',index=True)
    meli_warranty = fields.Char(string='Garantía', size=256)
    meli_listing_type = fields.Selection([("free","Libre"),("bronze","Bronce"),("silver","Plata"),("gold","Oro"),("gold_premium","Gold Premium"),("gold_special","Gold Special/Clásica"),("gold_pro","Oro Pro")], string='Tipo de lista')
    meli_channel_mkt = fields.Many2many( "meli.channel.mkt", string="Channels", index=True )

    meli_attributes = fields.Text(string='Atributos')
    meli_tags = fields.Text(string='Tags', help="JSON con lista de tags ML")
    meli_sale_terms = fields.Text(string='Sale Terms', help="JSON con lista de condiciones de venta ML")

    # -------------------------------------------------------------------------
    # Helpers internos para normalizar TAGS y SALE TERMS
    # -------------------------------------------------------------------------
    def _parse_meli_tags(self, raw):
        """Devuelve una lista de strings legibles a partir de meli_tags (Json o Text)."""
        if not raw:
            return []

        # Si ya es lista JSON
        if isinstance(raw, list):
            return [str(t) for t in raw if t]

        # Si es dict, usamos los valores
        if isinstance(raw, dict):
            return [str(v) for v in raw.values() if v]

        # Si viene como texto (viejo formato)
        if isinstance(raw, str):
            txt = raw.strip()
            if not txt:
                return []
            # Intento JSON
            for loader in (json.loads, ast.literal_eval):
                try:
                    val = loader(txt)
                except Exception:
                    continue
                if isinstance(val, list):
                    return [str(t) for t in val if t]
                if isinstance(val, dict):
                    return [str(v) for v in val.values() if v]

        return []

    def _parse_meli_sale_terms(self, raw):
        """Devuelve lista de strings tipo 'Tipo de garantía: Garantía del vendedor'."""
        if not raw:
            return []

        terms = None

        if isinstance(raw, list):
            terms = raw
        elif isinstance(raw, dict):
            # Si alguien guardó un mapeo id -> term
            terms = list(raw.values())
        elif isinstance(raw, str):
            txt = raw.strip()
            if not txt:
                return []
            for loader in (json.loads, ast.literal_eval):
                try:
                    val = loader(txt)
                except Exception:
                    continue
                if isinstance(val, list):
                    terms = val
                    break
                if isinstance(val, dict):
                    terms = list(val.values())
                    break

        if not terms:
            return []

        result = []
        for term in terms:
            if isinstance(term, dict):
                name = term.get('name') or term.get('id')
                value = term.get('value_name')
                struct = term.get('value_struct') or {}
                if not value and isinstance(struct, dict):
                    num = struct.get('number')
                    unit = struct.get('unit')
                    if num is not None or unit:
                        value = ("%s %s" % (num or "", unit or "")).strip()

                text = ""
                if name and value:
                    text = f"{name}: {value}"
                elif name:
                    text = name
                elif value:
                    text = value
                if text:
                    result.append(text)

            elif isinstance(term, str):
                if term.strip():
                    result.append(term.strip())

        return result
    
    def _badge(self, label, value, variant='neutral', icon='fa-circle'):
        """Chip con estilo inline (independiente del theme)."""
        if not value:
            return ''
        palette = {
            'neutral':  {'bg': '#f4f6f8', 'bd': '#e5eaef', 'fg': '#2b3648'},
            'primary':  {'bg': '#eef3ff', 'bd': '#d8e3ff', 'fg': '#2042a6'},
            'success':  {'bg': '#ecfbf3', 'bd': '#c9f2dc', 'fg': '#1d7f50'},
            'warning':  {'bg': '#fff7e8', 'bd': '#ffe6b3', 'fg': '#8a5b00'},
            'danger':   {'bg': '#ffeff0', 'bd': '#ffd3d6', 'fg': '#9a1b1f'},
        }.get(variant or 'neutral')
        style = (
            f"display:inline-flex;align-items:center;gap:8px;"
            f"padding:6px 10px;border-radius:18px;"
            f"background:{palette['bg']};border:1px solid {palette['bd']};"
            f"color:{palette['fg']};font-size:13px;line-height:1.2;white-space:nowrap;"
        )
        icon_style = "font-size:12px;opacity:.8"
        return (
            f'<div style="{style}">'
            f'<i class="fa {icon}" style="{icon_style}"></i>'
            f'<span><b>{label}:</b> {value}</span>'
            f'</div>'
        )
    
    def _compute_summary_header_html(self):
        """Resumen visual en el encabezado del template ML."""
        for bind in self:
            wrap_style = (
                "display:flex;flex-wrap:wrap;gap:8px 10px;"
                "align-items:center;margin:6px 0 12px 0;"
            )
            html_parts = [f'<div style="{wrap_style}">']

            # -----------------------------------------------------------------
            # Estado ML (tomamos el de la primera variante, como referencia)
            # -----------------------------------------------------------------
            status = ""
            sub_status = ""
            if bind.variant_bindings:
                first = bind.variant_bindings[0]
                status = (first.meli_status or "").strip()
                sub_status = (first.meli_sub_status or "").strip()

            status_variant = "neutral"
            if status == "active":
                status_variant = "success"
            elif status == "paused":
                status_variant = "warning"
            elif status in ("closed", "under_review"):
                status_variant = "danger"

            if status:
                status_text = status.replace("_", " ").upper()
                color_map = {
                    "success": "#2ECC71",
                    "warning": "#F1C40F",
                    "danger": "#E74C3C",
                    "neutral": "#7F8C8D",
                }
                bg = color_map.get(status_variant, "#7F8C8D")
                html_parts.append(
                    f'<span style="font-size:20px;font-weight:600;'
                    f'padding:8px 18px;border-radius:999px;'
                    f'background-color:{bg};color:#FFFFFF;'
                    f'display:inline-flex;align-items:center;gap:6px;">'
                    f'<i class="fa fa-circle"></i>{status_text}'
                    f'</span>'
                )

            if sub_status:
                html_parts.append(
                    self._badge(
                        "Subestado",
                        sub_status.replace("_", " "),
                        "neutral",
                        "fa-info-circle",
                    )
                )

            # -----------------------------------------------------------------
            # Tags
            # -----------------------------------------------------------------
            for tag in bind._parse_meli_tags(bind.meli_tags):
                html_parts.append(
                    self._badge("Tag", tag, "primary", "fa-tag")
                )

            # -----------------------------------------------------------------
            # Condiciones de venta (sale_terms)
            # -----------------------------------------------------------------
            for st in bind._parse_meli_sale_terms(bind.meli_sale_terms):
                html_parts.append(
                    self._badge("Condición", st, "neutral", "fa-file-text-o")
                )

            # -----------------------------------------------------------------
            # Info básica: Item Id, SKU, Categoría
            # -----------------------------------------------------------------
            if bind.conn_id:
                html_parts.append(
                    self._badge("Item Id", bind.conn_id, "neutral", "fa-hashtag")
                )
            if bind.sku:
                html_parts.append(
                    self._badge("SKU", bind.sku, "neutral", "fa-barcode")
                )
            if bind.meli_category:
                # display_name suele estar en categorías
                cat_name = getattr(bind.meli_category, "display_name", False) or getattr(bind.meli_category, "name", "") or ""
                if cat_name:
                    html_parts.append(
                        self._badge("Categoría", cat_name, "neutral", "fa-sitemap")
                    )

            html_parts.append("</div>")
            bind.summary_header_html = "".join(html_parts)

    # HTML del encabezado
    summary_header_html = fields.Html(
        string="Resumen",
        compute="_compute_summary_header_html",
        sanitize=False,
        store=False,
    )
    #meli_publications = fields.Text(compute=product_template_stats,string='Publicaciones en ML',search=search_template_stats)
    #meli_variants_status = fields.Text(compute=product_template_stats,string='Meli Variant Status')

    meli_pub_as_variant = fields.Boolean('Publicar variantes como variantes en ML',help='Publicar variantes como variantes de la misma publicación, no como publicaciones independientes.')
    meli_pub_variant_attributes = fields.Many2many(prod_att_line, relation='meli_pub_variant_attributes',column1='mercadolibre_product_template_id',column2='product_template_attribute_line_id', string='Atributos a publicar en ML',help='Seleccionar los atributos a publicar')
    meli_pub_principal_variant = fields.Many2one( 'product.product',string='Variante principal',help='Variante principal')

    meli_model = fields.Char(string="Modelo [meli]",size=256)
    meli_brand = fields.Char(string="Marca [meli]",size=256)
    meli_gender = fields.Char(string="Genero",index=True)
    meli_grid_chart_id = fields.Many2one("mercadolibre.grid.chart",string="Guia de talles")
    meli_stock = fields.Float(string="Cantidad inicial (Solo para actualizar stock)[meli]")

    meli_product_bom = fields.Char(string="Lista de materiales (skux:1,skuy:2,skuz:4) [meli]")

    meli_product_price = fields.Float(string="Precio [meli]")
    meli_product_cost = fields.Float(string="Costo del proveedor [meli]")
    meli_product_code = fields.Char(string="Codigo de proveedor [meli]")
    meli_product_supplier = fields.Char(string="Proveedor del producto [meli]")

    meli_ids = fields.Char(size=2048,string="MercadoLibre Ids.",help="ML Ids de variantes separados por coma.",index=True)
    meli_mercadolibre_banner = fields.Many2one("mercadolibre.banner",string="Plantilla Descriptiva")

    meli_user_product_id = fields.Char(string='Product User Id')

    meli_catalog_listing = fields.Boolean(string='Catalog Listing')
    meli_catalog_product_id = fields.Char(string='Catalog Product Id')
    meli_catalog_item_relations = fields.Char(string='Catalog Item Relations')
    meli_catalog_automatic_relist = fields.Boolean(string='Catalog Auto Relist')

    meli_shipping_logistic_type = fields.Char(string="Logistic Type",index=True)
    meli_shipping_free = fields.Boolean(string="Shipping Free",default=False,index=True)


    meli_shipping_mode = fields.Char(string="Shipping Mode",help="Shipping modes (por usuario): custom, not_specified, me2. https://api.mercadolibre.com/users/USERID/shipping_preferences",index=True)
    meli_shipping_method = fields.Char(string="Shipping Method",help="Shipping methods: https://api.mercadolibre.com/sites/SITEID/shipping_methods",index=True)

    meli_max_purchase_quantity = fields.Integer(string='Max Compra', help='Cantidad maxima por compra en ML')
    meli_manufacturing_time = fields.Char(string='Manufacturing time', help='Tiempo de fabricacion (30 días)')


    def meli_status_compute( self ):
        for bindT in self:
            st = None
            sst = None
            for bindv in bindT.variant_bindings:
                st = st or bindv.meli_status
                sst = sst or bindv.meli_sub_status
            bindT.meli_status = str(st)+"-"+str(sst)

    meli_status = fields.Char(string="Status ML", compute=meli_status_compute )

    def product_template_permalink(self):
        for bindT in self:
            bindT.meli_permalink = ""
            bind = bindT.variant_bindings and bindT.variant_bindings[0]
            if bind:
                bindT.meli_permalink = bind.meli_permalink

    meli_permalink = fields.Char( compute=product_template_permalink, size=256, string='Link',help='PermaLink in MercadoLibre', store=False )
    #meli_permalink_edit = fields.Char( compute=product_get_meli_update, size=256, string='Link Edit',help='PermaLink Edit in MercadoLibre', store=False )


    def update_price( self, meli_price=False, meli_pricelist=False, meli_price_fixed=False ):
        for bindT in self:

            account = bindT.connection_account
            config = account and account.configuration

            bindT.meli_pricelist = meli_pricelist or bindT.meli_pricelist
            bindT.meli_price_fixed = meli_price_fixed or bindT.meli_price_fixed
            bindT.meli_price = meli_price or (bindT.meli_price and float(bindT.meli_price)>0 and bindT.meli_price)
            # or (bind.meli_price and float(bind.meli_price)>0 and bind.meli_price)

            pl = bindT.meli_pricelist
            bind = bindT.variant_bindings and bindT.variant_bindings[0]
            pl = pl or (bind.meli_currency and bind.meli_currency in ["USD"] and config.mercadolibre_pricelist_usd and config.mercadolibre_pricelist_usd.currency_id.name=="USD" and config.mercadolibre_pricelist_usd)
            product = bind and bind.product_id
            if pl and product:
                #if manual set in pricelist
                #_logger.info("Pricelist:"+str(pl and pl.name))
                if (meli_price):
                    bind.update_pl_price(meli_price=meli_price)
                return_val = get_price_from_pl( pl, product, 1.0 )
                if pl.id in return_val:
                    new_price = return_val[pl.id]

                    #added taxes here
                    tax_excluded = ml_tax_excluded(self,config=config)
                    if ( price_list_apply_tax and tax_excluded and product and product.taxes_id ):
                        #_logger.info("Adjust taxes for publish")
                        # [caso-K10] solo los impuestos de la compania de la config (antes sumaba los de todas: /1,42 con dos)
                        txpercent, txfixed = ml_sale_tax_rates(product.taxes_id, (account and account.company_id))
                        if (txfixed>0 or txpercent>0):
                            #_logger.info("Tx Total:"+str(txtotal)+" to Price:"+str(ml_price_converted))
                            new_price = txfixed + new_price * (1.0 + txpercent*0.01)
                            #_logger.info("Price adjusted with taxes:"+str(new_price))

                    if (new_price>0):
                        bind.meli_price = new_price

            bindT.price = bindT.meli_price
            for bindv in bindT.variant_bindings:
                bindv.price = bindT.price
                bindv.meli_price = bindT.meli_price
                if (product.meli_id == bind.meli_id):
                    product.meli_price = bind.meli_price
                bindv.meli_pricelist = bindT.meli_pricelist
                bindv.meli_price_fixed = bindT.meli_price_fixed

    def product_template_post( self, context=None, meli_id=None, meli=None, account=None, product_variant=None ):
        context = context or self.env.context
        #_logger.info("[BIND TEMPLATE] >> MercadoLibre Product template Post context: "+str(context)+" meli_id: "+str(meli_id)+" account: "+str(account)+" product_variant: "+str(product_variant))
        warningobj = self.env['meli.warning']
        custom_context = {}
        force_meli_pub = False
        force_meli_active = False
        force_meli_new_pub = False

        force_meli_new_title = False
        force_meli_new_price = False
        force_meli_new_pricelist = False
        force_meli_listing_type = False

        if ("force_meli_pub" in context):
            force_meli_pub = context.get("force_meli_pub")
        if ("force_meli_active" in context):
            force_meli_active = context.get("force_meli_active")
        if ("force_meli_new_pub" in context):
            force_meli_new_pub = context.get("force_meli_new_pub")

        if ("force_meli_new_title" in context):
            force_meli_new_title = context.get("force_meli_new_title")
        if ("force_meli_new_price" in context):
            force_meli_new_price = context.get("force_meli_new_price")
        if ("force_meli_new_pricelist" in context):
            force_meli_new_pricelist = context.get("force_meli_new_pricelist")

        if ("force_meli_listing_type" in context):
            force_meli_listing_type = context.get("force_meli_listing_type")

        custom_context = {
            "force_meli_pub": force_meli_pub,
            "force_meli_active": force_meli_active,
            "force_meli_new_pub": force_meli_new_pub,

            "force_meli_new_title": force_meli_new_title,
            "force_meli_new_price": force_meli_new_price,
            "force_meli_new_pricelist": force_meli_new_pricelist,
            "force_meli_listing_type": force_meli_listing_type,
        }
        #_logger.info("custom_context: "+str(custom_context))

        ret = {}
        posted_products = 0

        for bindT in self:

            account = bindT.connection_account
            company = (account and account.company_id) or self.env.user.company_id
            config = (account and account.configuration) or company
            productT = bindT.product_tmpl_id
            meli_id = bindT.conn_id
            meli_pricelist = force_meli_new_pricelist or bindT.meli_pricelist
            bindT.update_price(meli_price=force_meli_new_price,meli_pricelist=force_meli_new_pricelist)

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            # #caso-K21 (26.371): camino de publicación de ESTE binding. 'family' si el binding ya se publicó
            # por el camino nuevo, o si lo pidió el botón «Publicar (nuevo)» (contexto). custom_context
            # REEMPLAZA el contexto en with_context(dict): el modo viaja adentro.
            _new_mode = (context.get("meli_post_mode") == "family"
                         or ("meli_post_mode" in bindT._fields and bindT.meli_post_mode == "family"))
            if _new_mode:
                custom_context["meli_post_mode"] = "family"
            else:
                custom_context.pop("meli_post_mode", None)
            _pp_mode = self.env["product.product"].with_context(meli_post_mode=(_new_mode and "family") or False)
            if _new_mode and _pp_mode._meli_is_family_mode(config):
                # cuenta user_product_seller ⇒ modo FAMILIA (cada variante su publicación, agrupadas por
                # family_name), con o sin "publicar como variantes": product.template._meli_post_family.
                _fam = productT.with_context(meli_post_mode="family")._meli_post_family(
                    bindT=bindT, account=account, meli=meli, config=config,
                    force_context=custom_context, only_variants=(product_variant or None))
                if _fam is not None and _fam is not False:
                    n_fam, ret_fam, _res_fam = _fam
                    posted_products += n_fam
                    if ret_fam and 'name' in ret_fam:
                        return ret_fam
                    continue

            if (productT.meli_pub_as_variant):
                #_logger.info("[BIND TEMPLATE] >> Posting as variants")

                if not productT.meli_pub_variant_attributes:
                    ret = warningobj.info( title='MELI WARNING', message="Seleccione los atributos a tener en cuenta para publicar como variante en ML. (MercadoLibre Plantilla > Atributos a publicar en ML)", message_html="" )
                    return ret


                variant_principal = productT.meli_pub_principal_variant
                first_product_post = not meli_id and (not variant_principal or (variant_principal and not variant_principal.meli_id))
                new_product_post = (variant_principal and variant_principal.meli_id and not meli_id) and force_meli_new_pub
                update_product_post = (variant_principal and variant_principal.meli_id and meli_id) and not force_meli_new_pub

                _logger.info("[BIND TEMPLATE] >> Posting as variants variant_principal:"+str(variant_principal)
                + "variant meli_id:"+str(variant_principal and variant_principal.meli_id)
                +" first_product_post:"+str(first_product_post)
                +" new_product_post:"+str(new_product_post)
                +" update_product_post:"+str(update_product_post))

                if variant_principal and meli_id and variant_principal.meli_id and variant_principal.meli_id == meli_id:
                    #UPDATE POST (BASE PRODUCT)
                    _logger.info("#UPDATE POST (BASE PRODUCT)")
                    variant_principal.meli_pub = True
                    ret = variant_principal.with_context(custom_context).product_post( meli=meli, config=config )
                    if (ret and len(ret) and 'name' in ret[0]):
                        return ret[0]
                    posted_products+= 1

                    # user_product_seller: actualizar variantes secundarias como listings separados
                    _is_ups = config and 'mercadolibre_user_product_seller' in config._fields and config.mercadolibre_user_product_seller
                    if _is_ups:
                        _logger.info("user_product_seller: updating secondary family_name variants")
                        productT._post_family_name_secondary_variants(meli=meli, config=config, bind_tpl=bindT, force_context=custom_context)

                    #upgrade all binded connections
                    bindT.stock = 0
                    if _is_ups:
                        # user_product_seller: cada variante tiene su propio listing (meli_id distinto)
                        # -> cada variant binding debe apuntar al meli_id de SU variante
                        for variant in productT.product_variant_ids:
                            if variant.meli_id:
                                meli_available_quantity = variant.meli_available_quantity
                                # bindT.conn_id apunta al listing de la variante principal
                                if variant_principal and variant.id == variant_principal.id:
                                    bindT.conn_id = variant.meli_id
                                    bindT.update_price(meli_price=force_meli_new_price,meli_pricelist=force_meli_new_pricelist)
                                bindT.stock += float(meli_available_quantity)
                                for bind in bindT.variant_bindings:
                                    if bind.product_id and bind.product_id.id == variant.id:
                                        bind.conn_id = variant.meli_id
                                        bind.conn_variation_id = False  # no hay variation en family_name flow
                                        bind.update_price(meli_price=force_meli_new_price,meli_pricelist=force_meli_new_pricelist)
                                        break
                    else:
                        # variations[] flow: todos los bindings comparten el mismo meli_id (listing unico)
                        for variant in productT.product_variant_ids:
                            if variant.meli_id:

                                #binding is anew, set with last meli_id if we can
                                meli_id = variant.meli_id
                                meli_price = variant.meli_price or productT.meli_price
                                meli_available_quantity = variant.meli_available_quantity

                                bindT.conn_id = meli_id
                                #bindT.price = meli_price
                                #meli_price = force_meli_new_price or variant.meli_price or productT.meli_price
                                #meli_pricelist = force_meli_new_pricelist or bindT.meli_pricelist
                                bindT.update_price(meli_price=force_meli_new_price,meli_pricelist=force_meli_new_pricelist)
                                bindT.stock+= float(meli_available_quantity)

                                for bind in bindT.variant_bindings:
                                    bind.conn_id = meli_id
                                    #bind.price = meli_price or bind.price
                                    bind.update_price(meli_price=force_meli_new_price,meli_pricelist=force_meli_new_pricelist)
                    #continue;
                elif variant_principal and meli_id!=variant_principal.meli_id and (meli_id!=False and variant_principal.meli_id!=False):
                    _logger.info("TODO: Check this bind how to post it!!! Republish as new with variants, meli_id: "+str(meli_id)+" variant_principal.meli_id: "+str(variant_principal.meli_id))
                    #binded but not principal variants.meli_id != bindT.meli_id
                    if not meli_id and productT.mercadolibre_bindings and len(productT.mercadolibre_bindings)==1 and variant_principal.meli_id:
                        #rebind
                        meli_id = variant_principal.meli_id
                        bindT.conn_id = meli_id
                        for bind in bindT.variant_bindings:
                            bind.conn_id = meli_id
                            bind.meli_id = meli_id
                    bind = bindT and bindT.variant_bindings and bindT.variant_bindings[0]
                    ret = variant_principal.with_context(custom_context).product_post( bind_tpl=bindT, bind=bind, meli=meli, config=config )
                    if (ret and len(ret) and 'name' in ret[0]):
                        return ret[0]
                    posted_products+= 1

                #No hay variante principal definida, elegimos la primera
                if ((not productT.meli_pub_principal_variant) or first_product_post):
                    #_logger.info("[BIND TEMPLATE] >> first_product_post or new_product_post")
                    variant_principal = False
                    #Buscamos la variante principal por si no la teniamos
                    #la primera nos servira...
                    for variant in productT.product_variant_ids:
                        conditions_ok = variant._conditions_ok()
                        #_logger.info("conditions_ok: "+str(conditions_ok))
                        if ( conditions_ok or variant_principal==False):

                            variant.meli_pub = True

                            if (variant_principal==False):
                                _logger.info("Posting variant principal sin necesidad de bindings!!!:"+str(variant))
                                variant_principal = variant
                                productT.meli_pub_principal_variant = variant_principal
                                ret = variant_principal.with_context(custom_context).product_post( meli=meli, config=config )
                                if (ret and len(ret) and 'name' in ret[0]):
                                    # NO desvincular el binding en caso de error — el usuario puede
                                    # corregir el problema y reintentar sin tener que revincular
                                    _logger.error("Error posting principal variant (first post), keeping binding for retry: %s", ret[0])
                                    return ret[0]
                                if (variant_principal and variant_principal.meli_id):
                                    bindT.conn_id = variant_principal.meli_id
                                    bindT.product_template_rebind(unbind_template=True)
                                posted_products+= 1

                                # user_product_seller: publicar variantes secundarias como listings separados con family_name
                                _is_ups = config and 'mercadolibre_user_product_seller' in config._fields and config.mercadolibre_user_product_seller
                                if _is_ups:
                                    _logger.info("user_product_seller: posting secondary family_name variants after principal")
                                    productT._post_family_name_secondary_variants(meli=meli, config=config, bind_tpl=bindT, force_context=custom_context)
                        else:
                            _logger.info("No condition met for:"+variant.display_name)
                            pass;
                        #_logger.info(productT.meli_pub_variant_attributes)
                elif (new_product_post and force_meli_new_pub):
                    #_logger.info("[BIND TEMPLATE] >> new_product_post and force_meli_new_pub")

                    bind = bindT and bindT.variant_bindings and bindT.variant_bindings[0]
                    ret = variant_principal.with_context(custom_context).product_post( bind_tpl=bindT, bind=bind, meli=meli, config=config )
                    if ('name' in ret[0]):
                        #return ret[0]
                        _logger.info(ret)
                        #self.env.cr.rollback()
                        return ret[0]
                    posted_products+= 1


            else:
                _logger.info("[BIND TEMPLATE] >> product_template_post > Posting Variant: " +str( product_variant))

                if _new_mode:
                    # #caso-K21 (a) (camino nuevo, cuenta clásica): cada variante a SU publicación, con savepoint
                    # por variante y resumen. El loop de abajo (camino clásico) queda como estaba.
                    n_sep, ret_sep = bindT._meli_post_separate_variants(
                        productT=productT, meli_id=meli_id, meli=meli, config=config, account=account,
                        custom_context=custom_context, product_variant=product_variant,
                        force_meli_pub=force_meli_pub, force_meli_new_pub=force_meli_new_pub,
                        force_meli_new_price=force_meli_new_price, force_meli_new_pricelist=force_meli_new_pricelist)
                    posted_products += n_sep
                    if ret_sep and 'name' in ret_sep:
                        return ret_sep
                    continue

                for variant in productT.product_variant_ids:
                    #_logger.info("product_template_post > Posting Variant: ", variant, variant.meli_pub)
                    if product_variant and product_variant.id!=variant.id:
                        #only one product variant to import on this iteration
                        continue;

                    if (force_meli_pub==True):
                        variant.meli_pub = True

                    if force_meli_new_pub:
                        meli_id = False

                    first_product_post = (not meli_id and not variant.meli_id)
                    new_product_post = (variant.meli_id and not meli_id) and force_meli_new_pub
                    update_product_post = (variant.meli_id and meli_id) and not force_meli_new_pub

                    #_logger.info("meli_id:"+str(meli_id)+" variant.meli_id:"+str(variant.meli_id)+" force_meli_new_pub:"+str(force_meli_new_pub))
                    #_logger.info("first_product_post:"+str(first_product_post)+" new_product_post:"+str(new_product_post)+" update_product_post:"+str(update_product_post))

                    if (variant.meli_pub and (variant.meli_id==meli_id or first_product_post) ):

                        #_logger.info("Posting variant")
                        ret = variant.with_context(custom_context).product_post( meli=meli, config=config )
                        if ('name' in ret[0]):
                            return ret[0]
                        #_logger.info(ret)

                        if variant.meli_id:
                            #binding is anew, set with last meli_id if we can
                            meli_id = variant.meli_id
                            meli_price = variant.meli_price
                            meli_available_quantity = variant.meli_available_quantity
                            bindT.conn_id = meli_id
                            #bindT.price = meli_price
                            bindT.update_price(meli_price=force_meli_new_price,meli_pricelist=force_meli_new_pricelist)
                            bindT.stock = meli_available_quantity
                            for bind in bindT.variant_bindings:
                                bind.conn_id = meli_id
                                #bind.price = meli_price
                                bind.update_price(meli_price=force_meli_new_price,meli_pricelist=force_meli_new_pricelist)
                                #bind.stock = meli_available_quantity

                        posted_products+= 1
                    elif (new_product_post and force_meli_new_pub):
                        #_logger.info("Posting New variant Publication")
                        #_logger.info("[BIND TEMPLATE] >> product_template_post > Posting New Variant Publication: "+str(variant) )

                        bind = bindT and bindT.variant_bindings and bindT.variant_bindings[0]
                        ret = variant.with_context(custom_context).product_post( bind_tpl=bindT, bind=bind, meli=meli, config=config )
                        if ('name' in ret[0]):
                            #return ret[0]
                            #_logger.info(ret)
                            #self.env.cr.rollback()
                            return ret[0]
                            #_logger.info(ret)
                            #raise ValidationError(str(ret[0]))
                        if bind.meli_id:
                            #binding is anew, set with last meli_id if we can
                            meli_id = bind.meli_id
                            meli_price = bind.meli_price
                            meli_available_quantity = bind.meli_available_quantity
                            bindT.conn_id = meli_id
                            bindT.price = meli_price
                            bindT.stock = meli_available_quantity
                            for bind in bindT.variant_bindings:
                                bind.conn_id = meli_id
                                bind.meli_id = meli_id
                                bind.price = meli_price
                                #bind.stock = meli_available_quantity
                        #_logger.info(ret)
                        posted_products+= 1
                    elif (meli_id and variant.meli_id):
                        #_logger.info("[BIND TEMPLATE] >> product_template_post > Updating Publication: "+str(bind) )
                        bind = bindT and bindT.variant_bindings and bindT.variant_bindings[0]
                        ret = variant.with_context(custom_context).product_post( bind_tpl=bindT, bind=bind, meli=meli, config=config )
                        if ('name' in ret[0]):
                            #return ret[0]
                            #_logger.info(ret)
                            #raise ValidationError(str(ret[0]))
                            #self.env.cr.rollback()
                            return ret[0]

                        if bind.meli_id:
                            #binding is anew, set with last meli_id if we can
                            meli_id = bind.meli_id
                            meli_price = bind.meli_price
                            meli_available_quantity = bind.meli_available_quantity
                            bindT.conn_id = meli_id
                            bindT.price = meli_price
                            bindT.stock = meli_available_quantity
                            for bind in bindT.variant_bindings:
                                bind.conn_id = meli_id
                                bind.meli_id = meli_id
                                bind.price = meli_price
                        #_logger.info(ret)
                        posted_products+= 1
                    else:
                        #if error_product_post:
                        #    #_logger.info("error_product_post: "+str(error_product_post))
                        #binding is new, take the first variant meli_id:
                        error = "No meli_pub or meli_id for:"+variant.display_name + " bind>meli_id: "+str(meli_id) + " meli_pub:" + str(variant.meli_pub) + " variant.meli_id:"+str(variant.meli_id)
                        #+ " error_product_post:"+str(error_product_post)
                        raise ValidationError(error)
                        #_logger.info(error)

        if (posted_products==0):
            raise ValidationError(_("Se intentaron publicar 0 productos. Debe forzar las publicaciones o marcar el producto con el campo Meli Publication, debajo del titulo. Puede tambien intentar revincular el producto. (Vinculando plantilla)"))

        return ret

    def _meli_post_separate_variants(self, productT=None, meli_id=None, meli=None, config=None, account=None,
                                     custom_context=None, product_variant=None, force_meli_pub=False,
                                     force_meli_new_pub=False, force_meli_new_price=False,
                                     force_meli_new_pricelist=False):
        """Plantilla SIN "publicar como variantes" (cuenta clásica), CAMINO NUEVO («Publicar (nuevo)» o
        binding meli_post_mode='family', 26.371): cada variante va a SU publicación. El «Publicar» clásico
        sigue con el loop de siempre de product_template_post.

        #caso-K21 (a) — antes el loop usaba UNA variable `meli_id` para todas las variantes: tras el alta
        de la 1ª quedaba con el id de la 1ª, la 2ª caía al else y hacía `raise ValidationError` ⇒
        rollback de TODO en Odoo con la 1ª ya viva en ML (huérfana). Y pisaba el conn_id de TODOS
        los bindings de variante con el id de la 1ª. Ahora:
          - la publicación de cada variante es la de SU binding / su meli_id; si la plantilla no tenía
            ninguna al empezar, cada variante sin publicación da de alta la suya;
          - sólo se toca el binding de ESA variante; el de plantilla toma el 1er id si no tenía;
          - cada variante en su savepoint, `meli_keep_published`: un error no deshace lo publicado;
            se devuelve un resumen con lo publicado y lo que falló.
        Devuelve (publicadas, acción|{})."""
        self.ensure_one()
        bindT = self
        warningobj = self.env['meli.warning']
        pp = self.env['product.product']
        from .meli_family_post import _MeliFamilyVariantError
        from . import meli_family as _mf
        created_log = []
        ctx = dict(custom_context or {})
        ctx.update({"meli_keep_published": True, "meli_created_listings": created_log, "meli_post_mode": "family"})
        tpl_listing_at_start = (not force_meli_new_pub) and meli_id or False
        results = []
        posted = 0
        for variant in productT.product_variant_ids:
            if product_variant and product_variant.id != variant.id:
                continue
            if force_meli_pub:
                variant.meli_pub = True
            label = variant.default_code or variant.display_name
            vbind = bindT.variant_bindings.filtered(lambda b: b.product_id.id == variant.id)[:1]
            if not (vbind and vbind.conn_id) and account and not product_variant:
                # la variante está vinculada en OTRO binding de plantilla de la cuenta (un binding por
                # variante): se publica en la vuelta de ese binding. Antes se posteaba acá con
                # bind=variant_bindings[0] ⇒ PUT de sus datos sobre la publicación de OTRA variante.
                other_vb = self.env['mercadolibre.product'].search([
                    ('product_id', '=', variant.id), ('connection_account', '=', account.id),
                    ('conn_id', '!=', False), ('binding_product_tmpl_id', '!=', bindT.id)], limit=1)
                if other_vb:
                    continue
            own = _mf.listing_id_for_variant(vbind and vbind.conn_id, variant.meli_id, force_new=force_meli_new_pub)
            if not variant.meli_pub and not own:
                _logger.info("[BIND TEMPLATE] variante sin 'ML Pub' ni publicación, se omite: %s", label)
                continue
            if not own and tpl_listing_at_start and not product_variant:
                # la plantilla ya apunta a una publicación y esta variante no está en ella: antes era
                # un raise (con rollback); ahora se informa sin tocar lo demás.
                results.append({"variant": label, "meli_id": None,
                                "error": "no tiene publicación propia en %s ni binding; publicala sola "
                                         "(Publicar desde la variante) o revinculá" % tpl_listing_at_start})
                continue
            if force_meli_new_pub or (own and variant.meli_id and own != variant.meli_id):
                # "Crear una nueva publicación", o actualizar una publicación ADICIONAL de la variante
                # (N publicaciones por producto): como siempre, va por el BINDING y product.meli_id
                # sigue apuntando a la original.
                vb_new = vbind or (bindT.variant_bindings and bindT.variant_bindings[0])
                n_created = len(created_log)
                try:
                    with self.env.cr.savepoint():
                        ret = variant.with_context(ctx).product_post(bind_tpl=bindT, bind=vb_new, meli=meli, config=config)
                        err = pp._meli_ret_error_text(ret)
                        if err:
                            raise _MeliFamilyVariantError(err)
                except Exception as e:
                    msg = str(e) if isinstance(e, _MeliFamilyVariantError) else ("%s: %s" % (type(e).__name__, e))
                    new_ids = [mid for (pid, mid) in created_log[n_created:] if pid == variant.id]
                    if new_ids and vb_new:
                        vb_new.write({"conn_id": new_ids[-1], "meli_id": new_ids[-1], "meli_post_mode": "family"})
                        if not bindT.conn_id:
                            bindT.conn_id = new_ids[-1]
                        posted += 1
                    results.append({"variant": label, "meli_id": (new_ids and new_ids[-1]) or None,
                                    "created": bool(new_ids),
                                    "error": (new_ids and "publicada y vinculada, pero después falló: " + msg) or msg})
                    continue
                posted += 1
                if vb_new:
                    vb_new.meli_post_mode = "family"
                results.append({"variant": label, "meli_id": vb_new and vb_new.conn_id,
                                "created": bool(force_meli_new_pub)})
                continue
            if own and not variant.meli_id:
                variant.write({"meli_id": own})  # completa el puntero vacío con su publicación (d)
            n_created = len(created_log)
            try:
                with self.env.cr.savepoint():
                    ret = variant.with_context(ctx).product_post(meli=meli, config=config)
                    err = pp._meli_ret_error_text(ret)
                    if err:
                        raise _MeliFamilyVariantError(err)
                    if not variant.meli_id:
                        raise _MeliFamilyVariantError("Mercado Libre no devolvió el id de la publicación")
                    bindT._meli_link_variant_listing(variant, account, meli=meli,
                                                     force_meli_new_price=force_meli_new_price,
                                                     force_meli_new_pricelist=force_meli_new_pricelist)
            except Exception as e:
                msg = str(e) if isinstance(e, _MeliFamilyVariantError) else ("%s: %s" % (type(e).__name__, e))
                if not isinstance(e, _MeliFamilyVariantError):
                    _logger.exception("[BIND TEMPLATE] error inesperado publicando %s", label)
                # (e) ML ya la creó antes del error ⇒ se recupera el vínculo fuera del savepoint
                new_ids = [mid for (pid, mid) in created_log[n_created:] if pid == variant.id]
                if new_ids:
                    variant.write({"meli_id": new_ids[-1]})
                    bindT._meli_link_variant_listing(variant, account, meli=meli)
                    results.append({"variant": label, "meli_id": new_ids[-1], "created": True,
                                    "error": "publicada y vinculada, pero después falló: " + msg})
                    posted += 1
                else:
                    results.append({"variant": label, "meli_id": None, "error": msg})
                continue
            posted += 1
            results.append({"variant": label, "meli_id": variant.meli_id, "created": not own})
        has_error, text = _mf.family_post_summary(results)
        if has_error:
            if not posted and len(results) == 1 and not results[0].get("created"):
                # una sola variante y nada publicado: el mensaje original de ML, sin resumen
                return 0, warningobj.info(title='MELI WARNING', message=results[0]["error"], message_html="")
            return posted, warningobj.info(title='MELI WARNING', message=text, message_html="")
        return posted, {}

    def _meli_link_variant_listing(self, variant, account, meli=None, force_meli_new_price=False,
                                   force_meli_new_pricelist=False):
        """Vincula `variant` a variant.meli_id dentro de ESTE binding de plantilla, sin tocar los
        bindings de las otras variantes (#caso-K21 a)."""
        self.ensure_one()
        bindT = self
        mid = variant.meli_id
        if not mid:
            return
        if not bindT.conn_id:
            bindT.conn_id = mid
        if bindT.meli_post_mode != "family":
            bindT.meli_post_mode = "family"
        vb = bindT.variant_bindings.filtered(lambda b: b.product_id.id == variant.id)[:1]
        if not vb:
            vb = bindT.variant_bindings.filtered(lambda b: not b.product_id and b.conn_id in (False, mid))[:1]
        vals = {"conn_id": mid, "meli_id": mid, "meli_post_mode": "family"}
        if variant.meli_id_variation:
            vals["conn_variation_id"] = variant.meli_id_variation
        if vb:
            vb.write(vals)
        elif account:
            vb = variant.mercadolibre_bind_to(account, binding_product_tmpl_id=bindT, meli_id=mid, meli=meli)
            if vb:
                vb.meli_post_mode = "family"
        if vb:
            try:
                vb.update_price(meli_price=force_meli_new_price, meli_pricelist=force_meli_new_pricelist)
            except Exception:
                _logger.exception("[BIND TEMPLATE] update_price %s", vb)
        if bindT.conn_id == mid:
            bindT.update_price(meli_price=force_meli_new_price, meli_pricelist=force_meli_new_pricelist)
            bindT.stock = sum(float(b.stock or 0) for b in bindT.variant_bindings) or variant.meli_available_quantity

    def product_template_post_stock( self, context=None, meli_id=None, meli=None, account=None ):
        #_logger.info("product_template_post_stock >> MercadoLibre Product Template Post Stock")
        ret = {}
        for bindT in self:

            account = bindT.connection_account
            product = bindT.product_tmpl_id
            meli_id = bindT.conn_id
            stock = 0
            stock_update = ""
            stock_error = ""

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            for bindv in bindT.variant_bindings:
                #_logger.info("bindv:"+str(bindv.name))
                bindv.product_post_stock(meli=meli)
                stock+= (bindv.stock or bindv.meli_available_quantity)
                stock_error+= str(bindv.stock_error)
                stock_update = bindv.stock_update

            bindT.stock = stock
            bindT.stock_error = stock_error
            bindT.stock_update = stock_update

        return ret

    def _qty_by_mk(self, config_prefix, qty):
        if qty == 0.0:
            return qty
        config = self.env['product.template']._find_mk_config(config_prefix)
        if config and config.stock_block and config.stock_block_type:
            if config.stock_block_type == 'qty_hand':
                qty_block = 0.0
                if self.qty_block > self.category_qty_block:
                    qty_block = self.qty_block
                else:
                    qty_block = self.category_qty_block

                new_qty = qty - qty_block
                return new_qty
            elif config.stock_block_type == 'qty_projected':
                sol = self.env['sale.order.line'].sudo().search([('product_id', '=', self.ids[0]),
                                                                 ('qty_delivered', '=', 0.0),
                                                                 ('order_id.state', '=', 'sale'),
                                                                 ])
                total_reserved = sum(x.product_uom_qty for x in sol)
                qty_block = 0.0
                if self.qty_block > self.category_qty_block:
                    qty_block = self.qty_block
                else:
                    qty_block = self.category_qty_block

                new_qty = qty - total_reserved - qty_block
                return new_qty
            else:
                return qty
        else:
            return qty

    def product_template_post_manufacturing_time( self, context=None, meli=None ):
        """26.278 (#caso-K31): publica SOLO el plazo de entrega de la publicacion (item padre)."""
        result, done = {}, 0
        for bindT in self:
            meli_id = bindT.conn_id
            if not meli_id:
                continue
            value = (bindT.meli_manufacturing_time or "").strip()
            if not value:
                for bindV in bindT.variant_bindings:
                    value = bindV._meli_manufacturing_time_value()
                    if value:
                        break
            if not value:
                return {"error": "sin_plazo", "message": _("la publicación %s no tiene cargado el plazo "
                                                           "de entrega (Manufacturing time)") % meli_id}
            account = bindT.connection_account
            if account:
                meli = account._meli_instance_or_mine( meli )
            if not meli:
                return {"error": "sin_conexion", "message": _("sin conexión a MercadoLibre")}
            if meli.need_login():
                return meli.redirect_login()
            result = _meli_post_manufacturing_time(meli, meli_id, value)
            if result:
                return result
            done += 1
        return {}

    def action_meli_post_manufacturing_time( self ):
        return _meli_manufacturing_time_action_result(
            self.product_template_post_manufacturing_time(), len(self.filtered("conn_id")))

    def product_template_post_price( self, context=None, meli_id=None, meli=None, account=None ):
        #_logger.info("product_template_post_price >> MercadoLibre Product Template Post Prices")
        ret = {}
        for bindT in self:

            account = bindT.connection_account
            product = bindT.product_tmpl_id
            meli_id = bindT.conn_id

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            bindT.update_price()

            for bindv in bindT.variant_bindings:
                bindv.product_post_price(meli=meli)

        return ret

    def product_template_post_title( self, context=None, meli_id=None, meli=None, account=None ):
        # Empuja SOLO el título a ML por cada variante de esta binding de plantilla.
        # El título es a nivel item; cada variante binding lo PUTea contra su item padre.
        # Corta y devuelve el dict de error de la primera variante que falle.
        for bindT in self:
            account = bindT.connection_account
            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )
            for bindv in bindT.variant_bindings:
                r = bindv.product_post_title(meli=meli)
                if r and isinstance(r, dict) and 'error' in r:
                    return r
        return {}

    def product_template_update( self, meli=None, import_images=True ):
        #_logger.info("template product_template_update >> MercadoLibre Product template Update "+str(meli))
        ret = {}
        for bindT in self:

            account = bindT.connection_account
            product = bindT.product_tmpl_id
            meli_id = bindT.conn_id

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            rjson = account.fetch_meli_product( meli_id = meli_id, meli = meli )

            if ( product and product.meli_pub_as_variant and product.meli_pub_principal_variant.id ):
                #_logger.info("template product_template_update >> Updating principal variant")
                #como puede que no exista aun el binding de variant??? que hacemos??
                #chequear si tiene un binding de variante:  y ejecutar ese binding
                pvbind = self.env["mercadolibre.product"].search([  ('conn_id','=',meli_id),
                                                                    ('product_tmpl_id','=',product.id),
                                                                    ('product_id','=',product.meli_pub_principal_variant.id),
                                                                    ('connection_account','=',account.id)],limit=1)
                if pvbind:
                    #_logger.info("Founded principal binding variant: getting product: "+str(pvbind.name)+" meli: "+str(meli))
                    pvbind.product_meli_get_product( meli=meli, import_images=import_images )
                else:
                    ret = product.meli_pub_principal_variant.product_meli_get_product( account=account, meli=meli, rjson=rjson, import_images=import_images )
                    #_logger.info("ret:"+str(ret))
                    #_logger.info("MercadoLibre Product template Update >> Updating principal variant >> copy_from_rjson (recursive)")
                    bindT.copy_from_rjson( rjson=rjson, meli=meli )
            else:
                for variant in product.product_variant_ids:
                    #_logger.info("Variant:", variant)
                    if (variant.meli_pub):
                        #_logger.info("template product_template_update >> calling product_meli_get_product Updating variant")
                        pvbind = self.env["mercadolibre.product"].search([  ('conn_id','=',meli_id),
                                                                            ('product_tmpl_id','=',product.id),
                                                                            ('product_id','=',variant.id),
                                                                            ('connection_account','=',account.id)],limit=1)
                        ret = {}
                        if pvbind:
                            pvbind.product_meli_get_product( meli=meli, rjson=rjson, import_images=import_images )
                        else:
                            ret = variant.product_meli_get_product(account=account, meli=meli, rjson=rjson, import_images=import_images)
                        if ('name' in ret):
                            return ret

        return ret

        #if (product_template):
        #    bindT = product_template.mercadolibre_bind_to( account=account, meli_id=meli_id, bind_variants=True )
        #    if bindT:
                # from_meli_oerp = True copy form recent imported
        #        bindT.fetch_meli_product( meli=meli, from_meli_oerp=True, fetch_variants=True )

    def category_predictor( self ):
        _logger.info("MercadoLibre Product template Category Predictor")
        pass;

    def copy_from_meli_oerp( self ):
        for bindT in self:
            productT = bindT.product_tmpl_id
            #basic info
            bindT.meli_title = productT.meli_title
            bindT.meli_description = productT.meli_description
            bindT.meli_category = productT.meli_category
            bindT.meli_price = productT.meli_price
            bindT.price = productT.meli_price
            bindT.meli_stock = productT.meli_stock
            bindT.stock = productT.meli_stock

            #attributes
            bindT.meli_attributes = productT.meli_attributes
            bindT.meli_model = productT.meli_model
            bindT.meli_brand = productT.meli_brand
            bindT.meli_gender = productT.meli_gender
            bindT.meli_grid_chart_id = productT.meli_grid_chart_id


            #publish ref info
            bindT.meli_pub = productT.meli_pub
            bindT.meli_master = productT.meli_master
            bindT.meli_ids = productT.meli_ids

            #config info
            bindT.meli_currency = productT.meli_currency
            bindT.meli_condition = productT.meli_condition
            bindT.meli_warranty = productT.meli_warranty
            bindT.meli_listing_type = productT.meli_listing_type
            bindT.meli_dimensions = productT.meli_dimensions
            bindT.sku = productT.product_variant_ids.mapped("default_code") or productT.default_code
            bindT.barcode = productT.product_variant_ids.mapped("barcode") or productT.barcode

            bindT.meli_shipping_logistic_type = str(productT.product_variant_ids.mapped("meli_shipping_logistic_type"))
            bindT.meli_shipping_free =  productT.product_variant_ids and productT.product_variant_ids[0].meli_shipping_free


    def copy_from_rjson( self, rjson, meli=None ):
        #_logger.info("template bind >> copy_from_rjson")
        if not rjson:
            return
        #_logger.info(f"rjson {rjson}")
        for bindT in self:
            account = bindT.connection_account
            config = account.configuration
            product_tmpl_id = bindT.product_tmpl_id
            product = product_tmpl_id and product_tmpl_id.product_variant_ids and product_tmpl_id.product_variant_ids[0]
            product = product or self.env["product.product"]
            #_logger.info("copy_from_rjson : %s" % rjson)
            #basic info
            catid, wwwid = self.env["mercadolibre.category"].meli_get_category( rjson.get('category_id',''), meli=meli, create_missing_website=config.mercadolibre_create_website_categories, config=config )
            desplain = ("description" in rjson and rjson["description"]) or None
            meli_ids = rjson["id"]
            #seller_sku = product_tmpl_id.product_variant_ids.mapped("default_code") or
            #            ("seller_sku" in rjson and rjson["seller_sku"]) or
            #            product_tmpl_id.default_code
            #barcode = product_tmpl_id.product_variant_ids.mapped("barcode") or
            #        ("barcode" in rjson and rjson["barcode"]) or
            #        product_tmpl_id.barcode
            seller_sku = (rjson and "seller_skus" in rjson and rjson["seller_skus"])
            seller_sku = seller_sku or (rjson and "seller_sku" in rjson and rjson["seller_sku"])

            barcode = (rjson and "barcodes" in rjson and rjson["barcodes"])
            barcode = barcode or (rjson and "barcode" in rjson and rjson["barcode"])

            fields = {
                #'meli_permalink': rjson['permalink'],
                'meli_title': rjson['title'].encode("utf-8"),
                'meli_listing_type': rjson['listing_type_id'],
                'meli_buying_mode':rjson['buying_mode'],
                'meli_local_pick_up':rjson['local_pick_up'] if 'local_pick_up' in rjson else False,
                'meli_free_shipping':rjson['free_shipping'] if 'free_shipping' in rjson else False,
                'meli_price': str(rjson['price']),
                'price': str(rjson['price']),
                'meli_currency': rjson['currency_id'],
                'meli_condition': rjson['condition'],
                #'meli_available_quantity': rjson['available_quantity'],
                'meli_warranty': rjson['warranty'],
                'meli_category': catid,
                'meli_ids': meli_ids,
                'sku': seller_sku or "",
                'barcode': barcode or "",
                'stock': rjson.get('available_quantity', 0), #if it does not have available_quantity, it defaults to 0

                'meli_tags': 'tags' in rjson and str(rjson['tags']),
                'meli_sale_terms': 'sale_terms' in rjson and str(rjson['sale_terms']),

                #'meli_imagen_link': rjson['thumbnail'],
                #'meli_video': str(vid),
                #'meli_dimensions': meli_dim_str,
            }
            # family_name / family_id (user_product_seller)
            if 'family_name' in rjson and rjson['family_name']:
                fields['meli_family_name'] = rjson['family_name']
            _fam = rjson.get('family') or {}
            _fam_id = (_fam.get('id') if isinstance(_fam, dict) else None) or rjson.get('family_id')
            if _fam_id:
                fields['meli_family_id'] = str(_fam_id)
            if desplain:

                #publication specific banner
                mlbanner = product_tmpl_id.meli_mercadolibre_banner
                #configuration banner
                mlbanner = mlbanner or (config and config.mercadolibre_banner)
                meli_description = ""
                if (mlbanner):
                    #get the text, not the header nor the footer
                    meli_description = mlbanner.get_from_ml_description( desplain )

                fields["meli_description"] = meli_description


            if "meli_official_store_id" in bindT._fields:
                fields["meli_official_store_id"] = ('official_store_id' in rjson and rjson['official_store_id']) or ""
                meli_official_store_id = fields["meli_official_store_id"]
                if (str(account.official_store_id)!=str(meli_official_store_id)):
                    #change account
                    #_logger.info("copy_from_rjson > changing account:"+str(meli_official_store_id))
                    account_store_id = self.env['mercadolibre.account'].search( [( 'official_store_id', '=ilike', str(meli_official_store_id) )], limit=1 )
                    #_logger.info("copy_from_rjson > account_store_id:"+str(account_store_id))
                    if (account_store_id):
                        bindT.connection_account = account_store_id
                        account = bindT.connection_account
                        config = account.configuration




            meli_shipping_logistic_type = ( rjson and "shipping" in rjson and "logistic_type" in rjson["shipping"] and rjson["shipping"]["logistic_type"] ) or ""
            has_user_product_id = product._fetch_meli_user_product_id( meli_id=meli_ids, 
                                                        meli_id_variation=None, 
                                                        meli=meli, 
                                                        config=config, 
                                                        item_json=rjson )
            if ( has_user_product_id ):
                meli_shipping_logistic_type+="_user_product_id"
            meli_shipping_logistic_type and fields.update({'meli_shipping_logistic_type': meli_shipping_logistic_type })

            meli_shipping_free = ( rjson and "shipping" in rjson and "free_shipping" in rjson["shipping"] and rjson["shipping"]["free_shipping"] ) or False
            meli_shipping_free and fields.update({'meli_shipping_free': meli_shipping_free })

            #_logger.info("copy in bindT: "+str(fields))
            bindT.write(fields)

            for bind in bindT.variant_bindings:
                bind.connection_account = account
                bind.copy_from_rjson( rjson=rjson, meli=meli )

            #seller_sku = product_tmpl_id.product_variant_ids.mapped("default_code") or ("seller_sku" in rjson and rjson["seller_sku"]) or product_tmpl_id.default_code
            #barcode = product_tmpl_id.product_variant_ids.mapped("barcode") or ("barcode" in rjson and rjson["barcode"]) or product_tmpl_id.barcode
            #fields = {'sku': seller_sku or "",'barcode': barcode or ""}
            #bindT.write(fields)


    def fetch_meli_product( self, meli = None, rjson = None, from_meli_oerp = False, fetch_variants = False ):
        #_logger.info("binding template fetch_meli_product")

        #fetch product full data from MELI into binding
        for bindT in self:

            account = bindT.connection_account
            meli_id = bindT.conn_id
            productT = bindT.product_tmpl_id

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            if not meli_id or not meli:
                continue;

            if from_meli_oerp: #TODO, check validity and meli_id in bindT.product_tmpl_id.meli_ids:
                bindT.copy_from_meli_oerp()
            else:
                rjson = rjson or account.fetch_meli_product( meli_id=meli_id, meli=meli )
                bindT.copy_from_rjson( rjson=rjson, meli=meli )

            if fetch_variants:
                pv_bindings = self.env["mercadolibre.product"].search([("conn_id","=",meli_id),
                                                                        ("binding_product_tmpl_id","=",bindT.id),
                                                                        ("connection_account","=",account.id)])
                if pv_bindings:
                    #_logger.info("Binding template fetch_meli_product >> Fetching variants pv_bindings: "+str(len(pv_bindings)))
                    for pv_bind in pv_bindings:
                        try:
                            pv_bind.fetch_meli_product( meli = meli, rjson = rjson, from_meli_oerp = from_meli_oerp )
                        except Exception as e:
                            _logger.error("Error fetching variant product binding: "+str(pv_bind)+str(e))
                else:
                    _logger.error("Missing variant bindings to fetch meli data")


    def product_meli_status_put( self, context=None, status=None, meli=False):

        company = self.env.user.company_id
        account = self.connection_account
        config = (account and account.configuration) or company
        company = ("company_id" in config._fields and config.company_id) or company

        meli_id = self.conn_id
        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

            if meli.need_login():
                return meli.redirect_login()

        if meli_id and status and (status in ['paused','closed','active']):
            response = meli.put_mini("/items/"+str(meli_id), { 'status': status }, {'access_token':meli.access_token})
            if response:
                _logger.info("put status: /items/"+str(meli_id)+" status:"+str(status)+" response: "+str(response.json()))
        else:
            _logger.error("Undefined status set, meli_id: "+str(meli_id)+" status: "+str(status))
        return {}

    def product_meli_block(self):
        bindT = self
        bindT.meli_update_stock_blocked = True
        #product = bind.product_tmpl_id
        #product.meli_update_stock_blocked = True
        #for variant in product.product_variant_ids:
        #    product.meli_update_stock_blocked = True

    def product_meli_unblock(self):
        bindT = self

        bindT.meli_update_stock_blocked = False
        productT = bindT.product_tmpl_id
        if (productT):
            productT.meli_update_stock_blocked = False
            for product in productT.product_variant_ids:
                product.meli_update_stock_blocked = False


    def product_meli_status_close( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product Tpl product_meli_status_close")
        return self.product_meli_status_put(context=context,status='closed',meli=meli)

    def product_meli_status_pause( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product Tpl product_meli_status_pause")
        self.product_meli_block()
        return self.product_meli_status_put(context=context,status='paused',meli=meli)

    def product_meli_status_active( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product Tpl product_meli_status_active")
        self.product_meli_unblock()
        return self.product_meli_status_put(context=context,status='active',meli=meli)

    def product_meli_delete( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product Tpl product_meli_delete")
        company = self.env.user.company_id
        account = self.connection_account
        config = (account and account.configuration) or company
        company = ("company_id" in config._fields and config.company_id) or company

        meli_id = self.conn_id

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            return meli.redirect_login()

        if meli_id:
            response = meli.put_mini("/items/"+str(meli_id), { 'deleted': 'true' }, {'access_token':meli.access_token})

            rjson = response.json()
            #_logger.info( rjson )
            ML_status = rjson["status"]
            if "error" in rjson:
                ML_status = rjson["error"]
            if "sub_status" in rjson:
                if len(rjson["sub_status"]) and rjson["sub_status"][0]=='deleted':
                    #product.write({ 'meli_id': '','meli_id_variation': '' })
                    _logger.info("Deleted ok: TODO: Delete template binding, and meli_id on base product...")
                    pass;

        return {}

    def product_template_stats(self):
        #_logger.info("bind template >> product_template_stats")
        for bind in self:

            _pubs = ""
            _stats = ""

            product = bind.product_tmpl_id

            if product and 1==2:
                for variant in product.product_variant_ids:
                    if (variant.meli_pub):
                        if ( (variant.meli_status=="active" or variant.meli_status=="paused") and variant.meli_id):
                            ml_full_status = variant.meli_status
                            if (variant.meli_sub_status):
                                ml_full_status+= ' ('+str(variant.meli_sub_status)+')'
                            if (len(_pubs)):
                                _pubs = _pubs + "|" + variant.meli_id + ":" + ml_full_status
                            else:
                                _pubs = variant.meli_id + ":" + ml_full_status

                            if (variant.meli_status=="active"):
                                _stats = "active"

                            if (_stats == "" and variant.meli_status=="paused"):
                                _stats = "paused"

            #bind.meli_publications = _pubs
            bind.meli_variants_status = _stats

        return {}

    def product_template_unbind( self ):

        for bindT in self:
            product_template = bindT.product_tmpl_id
            if product_template:
                res = product_template.mercadolibre_unbind_from( account=bindT.connection_account, meli_id=bindT.conn_id )
                if res and 'name' in res:
                    return res

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def product_template_rebind( self, unbind_template=True ):

        for bindT in self:
            product_template = bindT.product_tmpl_id
            conn_id = bindT.conn_id
            connection_account = bindT.connection_account

            _logger.info("Rebinding "+str(conn_id)+" cuenta:"+str(connection_account and connection_account.name))

            if unbind_template:
                _logger.info("Unbinding "+str(conn_id))
                bindT.product_template_unbind()

            if product_template and conn_id:
                _logger.info("Binding again... connection_account:"+str(connection_account and connection_account.name)+" product_template:"+str(product_template)+" conn_id:"+str(conn_id))
                res = product_template.mercadolibre_bind_to( account=connection_account, meli_id=conn_id, bind_only=True )
                _logger.info("res rebinded:"+str(res))
                if res and res._fields and res.connection_account:
                    _logger.info("Prev binding: "+str(connection_account and connection_account.name)+ " vs. "+str(res.connection_account and res.connection_account.name))
                    if (connection_account and connection_account.id!=res.connection_account.id):
                        _logger.error("Ojo cuentas no coinciden! Reseteando.")
                        res.connection_account = connection_account
                        MeliCommit( self )
                if res and 'name' in res:
                    return res
        return True

    #binding product template
    def search_all( self, connection_account=False, conn_id=False, product_tmpl_id=False ):
        # get all actives and not
        connection_account = connection_account or self.connection_account
        connection_account_id =  connection_account and connection_account.id

        product_tmpl_id = product_tmpl_id or self.product_tmpl_id
        product_tmpl_id_id = product_tmpl_id and product_tmpl_id.id
        product_tmpl_id_str = (product_tmpl_id_id and str(product_tmpl_id_id)) or str("NULL")

        conn_id = conn_id or self.conn_id
        conn_id_str = str(conn_id and ("'" + str(conn_id) + "'" ))
        conn_id_str = (conn_id and conn_id_str) or str("NULL")

        bindt_query_select_res = []

        # conn_id viene de la API de ML: va como parametro, no armado con comillas (F8b 20.0). Mismo SQL:
        # None => NULL (igual que el "NULL" literal de antes) e int() replica el %i (False => 0).
        bindt_query_select = """select id, name, conn_id
            from mercadolibre_product_template
            where connection_account=%s
            and conn_id = %s
            and product_tmpl_id = %s
        """
        bindt_query_params = ( int(connection_account_id), (str(conn_id) if conn_id else None), (product_tmpl_id_id or None) )
        _logger.info("bindT > search_all bindt_query_select:"+str(bindt_query_select)+" params:"+str(bindt_query_params))
        cr = MeliCr( self )
        resquery = cr.execute(bindt_query_select, bindt_query_params)
        bindt_query_select_res = cr.fetchall()
        _logger.info("bindT > search_all:"+str(bindt_query_select_res))
        return bindt_query_select_res

    #binding product template
    def unlink_all( self, connection_account=False, conn_id=False, product_tmpl_id=False ):
        resquery = []
        bindt_all = self.search_all(connection_account=connection_account, conn_id=conn_id, product_tmpl_id=product_tmpl_id)

        bindt_all_ids = []

        all_ids_str = None
        if bindt_all:
            all_ids_str = ','.join([str(bnd[0]) for bnd in bindt_all])

        if all_ids_str:
            bindt_query_delete = """delete
                from mercadolibre_product_template
                where id in %s
            """
            _logger.info("bindT > unlink_all:"+str(bindt_query_delete)+" ids:"+str(all_ids_str))
            cr = MeliCr( self )
            resquery = cr.execute( bindt_query_delete, (tuple(bnd[0] for bnd in bindt_all),) )
            _logger.info("bindT > unlink_all resquery:"+str(resquery))
        MeliCommit( self )
        return resquery





    def _variations( self, meli=None, config = None ):
        self.ensure_one()
        for bindT in self:
            return bindT.product_tmpl_id._variations( meli=meli, config = config )

    meli_variants_status = fields.Text(compute=product_template_stats,string='Meli Variant Status')

    def query_questions( self, meli=None, config=None ):

        #_logger.info("mercadolibre.product_template >> query_questions: meli:"+str(meli)+" config:"+str(config) )

        for bindT in self:

            account = bindT.connection_account
            config = config or account.configuration
            productT = bindT.product_tmpl_id
            meli_id = bindT.conn_id

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            response = meli.get("/questions/search?item_id="+str(meli_id), {'access_token':meli.access_token})
            questions_json = response.json()
            questions_obj = self.env['mercadolibre.questions']

            if 'questions' in questions_json:
                questions = questions_json['questions']
                #_logger.info( questions )
                cn = 0
                for Question in questions:
                    cn = cn + 1

                    question = self.env["mercadolibre.questions"].process_question( Question=Question, meli=meli, config=config )

    meli_questions = fields.One2many( "mercadolibre.questions", "product_template_binding", string="Preguntas" )
    meli_update_stock_blocked = fields.Boolean(string="Bloquea publicacion",default=False,index=True)

    @api.onchange('name')
    def _change_meli_title(self):
        for b in self:
            b.meli_title = b.name
            for bb in b.variant_bindings:
                bb.name = b.name
                bb.meli_title = b.meli_title

    @api.depends('name')
    def change_meli_title(self):
        for b in self:
            b.meli_title = b.name
            for bb in b.variant_bindings:
                bb.name = b.name
                bb.meli_title = b.meli_title


class MercadoLibreConnectionBindingProductVariant(models.Model):

    _name = "mercadolibre.product"
    _description = "MercadoLibre Product Binding Product"
    #_inherit = ["mercadolibre.product_template","ocapi.connection.binding.product"]
    _inherit = ["ocapi.connection.binding.product"]

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account", index=True )
    company_id = fields.Many2one("res.company", related="connection_account.company_id",string="Company")
    binding_product_tmpl_id = fields.Many2one("mercadolibre.product_template",string="Product Template Binding")

    image_bindings = fields.One2many('mercadolibre.product.image', "binding_product_variant_id", string="Product Variant Images")

    meli_free_shipping = fields.Boolean(string='Envío gratis')
    meli_local_pick_up = fields.Boolean(string='Recoger en tienda')

    def init(self):
        super().init()
        # 26.87 (F1e): indice compuesto para el barrido de la cola de stock.
        # Las consultas calientes filtran por cuenta + estado y ordenan/filtran
        # por stock_update (cola del cron y red de seguridad de resync). Con los
        # indices sueltos que ya existian, Postgres tenia que combinar bitmaps
        # sobre decenas de miles de filas en cada corrida.
        # CONCURRENTLY no se puede usar dentro de la transaccion del -u.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS mercadolibre_product_stock_queue_idx
            ON mercadolibre_product (connection_account, meli_stock_status, stock_update)
        """)

    def product_get_meli_update( self ):
        # MULTIGET: Cero llamadas API al abrir el formulario de producto.
        # Antes hacía ~19 GETs a ML cada vez que se abría un producto.
        # Ahora usa meli_last_status (guardado en BD por webhooks/crons) y
        # construye links localmente. La sync real se hace via botones y crons.
        # Ver documentación interna
        #
        # URLs por site: resolvemos con _resolve_ml_site_urls() que usa
        # account.meli_user_site_id (definitivo) con fallback a country_code.
        # Antes estaba hardcodeado a .com.mx/MLM-, rompiendo para MLA, MLB,
        # MLC, MCO, etc. Además duplicaba el prefijo (meli_id ya incluye
        # "MLM"/"MLA"/..., así que "MLM-" + "MLM123" era inválido).

        for bindv in self:
            ML_status = bindv.meli_last_status or "unknown"
            ML_sub_status = ""
            ML_permalink = ""
            ML_permalink_edit = ""
            ML_permalink_api = ""
            ML_state = False

            if bindv.conn_id:
                bindv.meli_id = bindv.conn_id

            if bindv.meli_id:
                _site_id, _urls = _resolve_ml_site_urls(
                    account=bindv.connection_account,
                    company=bindv.company_id,
                )
                # meli_id ya incluye el prefijo de site (ej: "MLM<id>").
                # ML acepta articulo/<meli_id> sin guion ni slug de título y redirige
                # al permalink final. Ver https://articulo.mercadolibre.com.mx/MLM<id>.
                ML_permalink = _meli_permalink_from_id(str(bindv.meli_id), _urls)
                ML_permalink_edit = _urls["link"] + "/publicaciones/" + str(bindv.meli_id) + "/modificar"
                # un caso: sin token en el link (se ve en pantalla); lo resuelve Odoo por cuenta.
                ML_permalink_api = "/meli/item_api/%s" % bindv.meli_id
                if bindv.connection_account:
                    ML_permalink_api += "?account=%s" % bindv.connection_account.id

            bindv.meli_status = ML_status
            bindv.meli_sub_status = ML_sub_status
            bindv.meli_permalink = ML_permalink
            bindv.meli_permalink_edit = ML_permalink_edit
            bindv.meli_permalink_api = ML_permalink_api
            bindv.meli_state = ML_state

            # Update stored status field for searchability (only for valid statuses)
            if ML_status in ('active', 'paused', 'closed', 'under_review', 'inactive'):
                if bindv.meli_last_status != ML_status:
                    bindv.sudo().write({'meli_last_status': ML_status})

#    meli_pub_variant_attributes = fields.Many2many(prod_att_line, relation='meli_pub_variant_attributes',column1='ml_template_id',column2='att_line_id', string='Atributos a publicar en ML',help='Seleccionar los atributos a publicar')

    #typical values
    meli_title = fields.Char(string='Nombre del producto en Mercado Libre',size=256,index=True)
    meli_family_name = fields.Char(string='Nombre de la familia del user product en Mercado Libre',size=256)
    meli_family_id = fields.Char(string='ID de familia ML (user_product_seller)',size=128,index=True)
    # #caso-K21 (26.371): con qué camino se publicó. 'classic' = «Publicar» de siempre; 'family' = «Publicar
    # (nuevo)»: modo familia en cuentas user_product, una publicación por variante en cuentas clásicas.
    # Los updates (crons, asistentes) siguen el camino que diga ESTE campo, no el botón que se use después.
    meli_post_mode = fields.Selection([('classic', 'Clásico (Publicar)'), ('family', 'Nuevo (Publicar nuevo)')],
                                      string='Camino de publicación', default='classic', copy=False,
                                      help='Con qué asistente se creó la publicación. Las actualizaciones siguen ese camino.')
    meli_description = fields.Text(string='Descripción')
    meli_category = fields.Many2one("mercadolibre.category","Categoría de MercadoLibre")
    meli_price = fields.Char( string='Precio',help='Precio de venta en ML', size=128,index=True)
    meli_price_fixed = fields.Boolean(string='Price is fixed')
    meli_pricelist = fields.Many2one("product.pricelist",string="Pricelist")
    active = fields.Boolean(string="Product Active",related="product_id.active",index=True)

    @api.onchange('meli_price_fixed')
    def _onchange_meli_price_fixed( self ):
        #_logger.info("_onchange_meli_price_fixed:"+str(self and self.name))
        for bindV in self:
            #_logger.info("_onchange_meli_price_fixed:"+str(bindV))
            #product = self._origin
            #product = self
            bindT = bindV.binding_product_tmpl_id
            if bindT:
                bindT.write({'meli_price_fixed': bindV.meli_price_fixed})
                for bindV2 in bindT.variant_bindings:
                    #_logger.info("_onchange_meli_price_fixed bind variant before::"+str(bindV2.meli_price_fixed))
                    #bindV2.write({'meli_price_fixed': bindT.meli_price_fixed})
                    bindV2.meli_price_fixed = bindT.meli_price_fixed

    @api.onchange('meli_price')
    def _onchange_meli_price( self ):
        #_logger.info("_onchange_meli_price:"+str(self and self.name))
        for bindV in self:
            #_logger.info("_onchange_meli_price:"+str(bindV))
            #product = self._origin
            #product = self
            bindT = bindV.binding_product_tmpl_id
            if bindT:
                bindT.write({'meli_price': bindV.meli_price})
                bindT.price = bindT.meli_price
                for bindV2 in bindT.variant_bindings:
                    #_logger.info("_onchange_meli_price bind variant before::"+str(bindV2.meli_price))
                    #bindV2.write({'meli_price': bindT.meli_price})
                    bindV2.meli_price = bindT.meli_price
                    bindV2.price = bindV2.meli_price

    @api.onchange('meli_pricelist')
    def _onchange_meli_pricelist( self ):
        #_logger.info("_onchange_meli_pricelist:"+str(self and self.name))
        for bindV in self:
            #_logger.info("_onchange_meli_pricelist:"+str(bindV))
            #product = self._origin
            #product = self
            bindT = bindV.binding_product_tmpl_id
            if bindT:
                bindT.write({'meli_pricelist': bindV.meli_pricelist})
                for bindV2 in bindT.variant_bindings:
                    #_logger.info("_onchange_meli_pricelist bind variant before::"+str(bindV2.meli_pricelist))
                    #bindV2.write({'meli_pricelist': bindT.meli_pricelist})
                    bindV2.meli_pricelist = bindT.meli_pricelist

    meli_dimensions = fields.Char( string="Dimensiones del producto", size=128)
    meli_pub = fields.Boolean('Meli Publication',help='MELI Product',index=True)

    meli_buying_mode = fields.Selection( [("buy_it_now","Compre ahora"),("classified","Clasificado")], string='Método de compra')
    meli_currency = fields.Selection([("ARS","Peso Argentino (ARS)"),
                                        ("MXN","Peso Mexicano (MXN)"),
                                        ("COP","Peso Colombiano (COP)"),
                                        ("PEN","Sol Peruano (PEN)"),
                                        ("BOB","Boliviano (BOB)"),
                                        ("BRL","Real (BRL)"),
                                        ("CLP","Peso Chileno (CLP)"),
                                        ("CRC","Colon Costarricense (CRC)"),
                                        ("UYU","Peso Uruguayo (UYU)"),
                                        ("VES","Bolivar Soberano (VES)"),
                                        ("PAB","Balboa Panameño (PAB)"),
                                        ("USD","Dolar Estadounidense (USD)")],
                                        string='Moneda')
    meli_condition = fields.Selection([ ("new", "Nuevo"), ("used", "Usado"), ("not_specified","No especificado")],'Condición del producto')
    meli_warranty = fields.Char(string='Garantía', size=256)
    meli_listing_type = fields.Selection([("free","Libre"),("bronze","Bronce"),("silver","Plata"),("gold","Oro"),("gold_premium","Gold Premium"),("gold_special","Gold Special/Clásica"),("gold_pro","Oro Pro")], string='Tipo de lista')

    #post only fields
    meli_post_required = fields.Boolean(string='Publicable', help='Este producto es publicable en Mercado Libre')

    #TODO deprecated
    meli_id = fields.Char(string='ML Id', help='Id del item asignado por Meli', size=256, index=True)
    #meli_description_banner_id = fields.Many2one("mercadolibre.banner",string="Description Banner")
    meli_mercadolibre_banner = fields.Many2one("mercadolibre.banner",string="Plantilla Descriptiva")

    meli_buying_mode = fields.Selection(string='Método',help='Método de compra',selection=[("buy_it_now","Compre ahora"),("classified","Clasificado")])
    meli_available_quantity = fields.Integer(string='Cantidades', help='Cantidad disponible a publicar en ML')
    meli_imagen_logo = fields.Char(string='Imagen Logo', size=256)
    meli_imagen_id = fields.Char(string='Imagen Id', size=256)
    meli_imagen_link = fields.Char(string='Imagen Link', size=256)
    meli_imagen_hash = fields.Char(string='Imagen Hash')
    meli_multi_imagen_id = fields.Char(string='Multi Imagen Ids', size=512)
    meli_video = fields.Char( string='Video (id de youtube)', size=256)
    #@api.depends('product_id','product_meli_stock_moves_update')
    @api.depends()  # Empty depends - prevents automatic recompute on stock moves (avoids serialization errors)
    def _meli_stored_moves_stamps( self ):
        """Lee por SQL los sellos YA GUARDADOS de estos bindings.

        Por SQL a proposito: esto se usa dentro del compute de esos mismos dos
        campos; leerlos por ORM dispararia el recomputo del campo que se esta
        calculando. Ademas el valor de la base es justo el que necesitamos (el
        anterior) para no retroceder."""
        stored = {}
        ids = tuple(i for i in self.ids if i)
        if not ids:
            return stored
        self.env.cr.execute(
            "SELECT id, meli_stock_moves_update, product_meli_stock_moves_update "
            "FROM mercadolibre_product WHERE id IN %s", (ids,))
        for bid, a, b in self.env.cr.fetchall():
            stored[bid] = (a, b)
        return stored

    def _meli_stock_moves_update( self ):
        _stored = self._meli_stored_moves_stamps()
        for bind in self:
            if bind.product_id:
                # 26.87 (F1b): el sello es MONOTONO tambien en el binding.
                # Si no lo fuera, un recomputo podria pisar hacia atras el NOW()
                # que escriben por SQL los hooks de cancel/unreserve y sacar de
                # la cola una publicacion que todavia no se republico.
                _stamp = bind.product_id.meli_stock_moves_update
                _current, _current_p = _stored.get(bind.id, (None, None))
                if not (_stamp and _current and _current > _stamp):
                    bind.meli_stock_moves_update = _stamp
                if not (_stamp and _current_p and _current_p > _stamp):
                    bind.product_meli_stock_moves_update = _stamp
            else:
                bind.meli_stock_moves_update = False
                bind.product_meli_stock_moves_update = False

            bind._meli_stock_status()

    def process_meli_stock_moves_update( self ):
        """
        Update binding stock move dates from their linked products.
        OPTIMIZED: Uses SQL for efficiency when updating many bindings (e.g., 400+ kits scenario).
        Also uses batch SQL updates for stock status where possible.
        """
        if not self:
            return

        # 26.253 (#caso-K30): FLUSH antes del SQL. El sello del producto
        # (product.product.meli_stock_moves_update) se acaba de escribir por ORM en
        # _meli_stock_moves_update / _process_stock_update_orm(_batch) y sigue en la
        # cache: el UPDATE de abajo lee product_product por SQL y veia el sello VIEJO.
        # Resultado: al validar una recepcion el binding no avanzaba y
        # _batch_update_stock_status lo dejaba 'updated' si habia tenido un push
        # posterior a su sello anterior => el cron nunca lo publicaba.
        # Se flushean tambien los campos del binding que lee el SQL.
        self.env['product.product'].flush_model(['meli_stock_moves_update'])
        self.flush_recordset()

        # Use SQL UPDATE to efficiently sync dates from product to binding
        # This ensures stored computed field values are actually persisted
        # 26.87 (F1b): GREATEST(...) — el sello del binding es monotono. Sin esto,
        # esta sincronizacion desde el producto puede pisar hacia atras el NOW()
        # que escriben los hooks de cancel/unreserve y sacar de la cola una
        # publicacion que todavia no se republico.
        self.env.cr.execute("""
            UPDATE mercadolibre_product mp
            SET meli_stock_moves_update = GREATEST(
                    mp.meli_stock_moves_update, pp.meli_stock_moves_update),
                product_meli_stock_moves_update = GREATEST(
                    mp.product_meli_stock_moves_update, pp.meli_stock_moves_update)
            FROM product_product pp
            WHERE mp.product_id = pp.id
              AND mp.id IN %s
        """, (tuple(self.ids),))

        # Invalidate cache so Odoo sees the updated values
        self.invalidate_recordset(['meli_stock_moves_update', 'product_meli_stock_moves_update'])

        # OPTIMIZED: Use batch SQL updates for stock status - more reliable than ORM
        # This avoids cache issues where ORM might read stale values after SQL UPDATE
        self._batch_update_stock_status()

    def _batch_update_stock_status(self):
        """
        OPTIMIZED: Batch update stock status using SQL for common cases.
        Falls back to individual _meli_stock_status() only for update_rt checks.
        """
        if not self:
            return

        bind_ids = tuple(self.ids)

        # Case 1: Error states (revision_error and sub-types)
        # First, set all to 'revision' as default, then apply specific states
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision'
            WHERE id IN %s
        """, (bind_ids,))

        # Case 1b: Check meli_last_status FIRST - closed/deleted items
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_closed'
            WHERE id IN %s
            AND meli_last_status IN ('closed', 'deleted')
        """, (bind_ids,))

        # Case 1c: Check meli_last_status - not_found items
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_not_found'
            WHERE id IN %s
            AND meli_last_status = 'not_found'
        """, (bind_ids,))

        # Case 1d: Check meli_last_status - inactive items
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_inactive'
            WHERE id IN %s
            AND meli_last_status = 'inactive'
        """, (bind_ids,))

        # Case 1e: Check meli_last_status - under_review items
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_under_review'
            WHERE id IN %s
            AND meli_last_status = 'under_review'
        """, (bind_ids,))

        # Case 2: revision_fulfillment (takes priority)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_fulfillment'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND stock_error LIKE '%%fulfillment%%'
        """, (bind_ids,))

        # Case 3: revision_has_bids
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_has_bids'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND stock_error LIKE '%%has_bids:true%%'
        """, (bind_ids,))

        # Case 4: revision_under_review
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_under_review'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND stock_error LIKE '%%under_review%%'
        """, (bind_ids,))

        # Case 5: revision_closed
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_closed'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND stock_error LIKE '%%closed%%'
        """, (bind_ids,))

        # Case 6: revision_inactive
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_inactive'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND stock_error LIKE '%%inactive%%'
        """, (bind_ids,))

        # Case 7: revision_blocked
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_blocked'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND stock_error LIKE '%%blocked%%'
        """, (bind_ids,))

        # Case 8: revision_not_modifiable (ML won't allow stock updates)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_not_modifiable'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND stock_error LIKE '%%not_modifiable%%'
        """, (bind_ids,))

        # Case 8b: revision_not_found (item doesn't exist in ML - 404)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_not_found'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error LIKE '%%not_found%%'
        """, (bind_ids,))

        # Case 8c: revision_sku_mismatch (SKU in Odoo doesn't match ML - needs manual review)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_sku_mismatch'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error LIKE '%%different seller_sku%%'
        """, (bind_ids,))

        # Case 8d: revision_variation_not_found (variation doesn't exist in ML item)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_variation_not_found'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error LIKE '%%Variation id not found%%'
        """, (bind_ids,))

        # Case 8e: revision_forbidden (403 - likely belongs to different account)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_forbidden'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error LIKE '%%forbidden:403%%'
        """, (bind_ids,))

        # Case 8f: multiwarehouse (seller uses multi-warehouse, manual update required)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'multiwarehouse'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error LIKE '%%multiwarehouse%%'
        """, (bind_ids,))

        # Case 8g — 26.87 (F7): revision_not_applied (ML respondio 200 y NO aplico
        # la cantidad). Es un fallo silencioso: sin este estado el binding se
        # marcaba 'updated' y salia de la cola con la publicacion desactualizada.
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_not_applied'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error LIKE '%%stock_not_applied%%'
        """, (bind_ids,))

        # Case 9: revision_error (generic error, lower priority than specific errors)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_error'
            WHERE id IN %s
            AND stock_error IS NOT NULL
            AND stock_error NOT LIKE '%%Ok%%'
            AND meli_stock_status = 'revision'
        """, (bind_ids,))

        # Case 9: Non-error states - 'update' (needs sync)
        # Exclude multiwarehouse records and items not in active/paused status
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'update'
            WHERE id IN %s
            AND (meli_last_status IS NULL OR meli_last_status IN ('active', 'paused'))
            AND (stock_error IS NULL OR stock_error = '' OR stock_error LIKE '%%Ok%%')
            AND (stock_error IS NULL OR stock_error NOT LIKE '%%multiwarehouse%%')
            AND meli_stock_moves_update IS NOT NULL
            AND (stock_update IS NULL OR meli_stock_moves_update > stock_update)
        """, (bind_ids,))

        # Case 10: 'updated' (already in sync)
        # Exclude multiwarehouse records and items not in active/paused status
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'updated'
            WHERE id IN %s
            AND (meli_last_status IS NULL OR meli_last_status IN ('active', 'paused'))
            AND (stock_error IS NULL OR stock_error = '' OR stock_error LIKE '%%Ok%%')
            AND (stock_error IS NULL OR stock_error NOT LIKE '%%multiwarehouse%%')
            AND meli_stock_moves_update IS NOT NULL
            AND stock_update IS NOT NULL
            AND meli_stock_moves_update <= stock_update
        """, (bind_ids,))

        # Case 11: 'updated_with_warning'
        # Exclude multiwarehouse records (they should never have 'updated' status anyway, but be safe)
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'updated_with_warning'
            WHERE id IN %s
            AND meli_stock_status = 'updated'
            AND stock_error IS NOT NULL
            AND stock_error != ''
            AND stock_error != 'Ok'
            AND stock_error NOT LIKE '%%multiwarehouse%%'
        """, (bind_ids,))

        # Case 12: 'revision_unmoved' (no stock moves ever)
        # Only for active/paused items
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'revision_unmoved'
            WHERE id IN %s
            AND (meli_last_status IS NULL OR meli_last_status IN ('active', 'paused'))
            AND (stock_error IS NULL OR stock_error = '' OR stock_error LIKE '%%Ok%%')
            AND meli_stock_moves_update IS NULL
            AND meli_stock_status = 'revision'
        """, (bind_ids,))

        # Case 13: 'updated' for unmoved but already synced with positive stock
        # Only for active/paused items
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'updated'
            WHERE id IN %s
            AND (meli_last_status IS NULL OR meli_last_status IN ('active', 'paused'))
            AND meli_stock_status = 'revision_unmoved'
            AND stock_update IS NOT NULL
            AND stock > 0
        """, (bind_ids,))

        # Case 14 — 26.87 (F1d): RED DE SEGURIDAD por antigüedad.
        # Gemelo SQL de _meli_stock_resync_due(). Toda publicación sana cuyo último
        # push sea más viejo que mercadolibre_stock_resync_days vuelve a la cola,
        # haya habido movimientos o no. Sin esto, un evento de stock perdido deja
        # la publicación desincronizada para siempre (el binding se queda en
        # 'updated' y ningún cron lo vuelve a mirar).
        # resync_days = 0 desactiva; NULL (base sin -u todavía) usa el default.
        self.env.cr.execute("""
            UPDATE mercadolibre_product mp
            SET meli_stock_status = 'update'
            FROM mercadolibre_account ma
            LEFT JOIN mercadolibre_configuration mc ON mc.id = ma.configuration
            WHERE mp.id IN %s
              AND mp.connection_account = ma.id
              AND mp.meli_stock_status IN ('updated', 'updated_with_warning', 'revision_unmoved')
              AND (mp.meli_last_status IS NULL OR mp.meli_last_status IN ('active', 'paused'))
              AND (mp.stock_error IS NULL OR mp.stock_error = '' OR mp.stock_error LIKE '%%Ok%%')
              AND (mp.stock_error IS NULL OR mp.stock_error NOT LIKE '%%multiwarehouse%%')
              AND COALESCE(mc.mercadolibre_stock_resync_days, %s) > 0
              AND (
                    mp.stock_update IS NULL
                 OR mp.stock_update < (NOW() AT TIME ZONE 'UTC')
                        - (COALESCE(mc.mercadolibre_stock_resync_days, %s) * INTERVAL '1 day')
              )
        """, (bind_ids, self.MELI_STOCK_RESYNC_DAYS_DEFAULT, self.MELI_STOCK_RESYNC_DAYS_DEFAULT))

        # N1 fix (ticket un caso): reset the auto re-queue retry counter once a binding
        # is healthy again (a push finally succeeded -> stock_error Ok/empty). Prevents
        # a transient-error item that later succeeds from carrying a stale retry count
        # that would prematurely cap future re-queues.
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_retry_count = 0
            WHERE id IN %s
            AND COALESCE(meli_stock_retry_count, 0) > 0
            AND (stock_error IS NULL OR stock_error = '' OR stock_error LIKE '%%Ok%%')
        """, (bind_ids,))

        # Invalidate cache
        self.invalidate_recordset(['meli_stock_status', 'stock_error'])

        # Check for update_rt needed (requires configuration access, so do per-binding)
        # Only check bindings that are currently in 'update' status
        update_bindings = self.filtered(lambda b: b.meli_stock_status == 'update')
        for bind in update_bindings:
            if bind._is_update_rt_needed():
                bind.meli_stock_status = 'update_rt'

    # Changed from related field to computed field to avoid KeyError during module loading
    # (related fields with computed sources fail during registry setup)
    product_meli_stock_moves_update = fields.Datetime(compute=_meli_stock_moves_update, string="Product Stock Last Move", store=True, index=True, readonly=True)
    meli_stock_moves_update = fields.Datetime(compute=_meli_stock_moves_update,string="Stock Last Move",help="Ultimo movimiento de stock",store=True,index=True)

    #meli_stock_moves_ids = fields.One2many(related="product.stock_move_ids")
    def _is_update_rt_needed( self ):
        
        update_rt_needed = False

        for bind in self:
            config = bind.connection_account.configuration
            stock_rules_rt = config.mercadolibre_stock_sku_mapping_rt
            for st in stock_rules_rt:
                #filter the ones that have type "stock"
                #if its a general or sku... check the actual limit...security...
                #or formula based on quantity of SKU similiar publications actives...
                if st.type == 'stock':

                    if ( st.sku=="*" or st.sku==bind.sku ):
                        #TODO: revisar si el valor de bind.stock esta actualizado ok
                        if ( st.formula=="update_rt" and bind.stock <= st.security_virtual_stock_to_pause ):

                            update_rt_needed = True

        return update_rt_needed


    # 26.87 (F1d) — red de seguridad por antigüedad
    MELI_STOCK_RESYNC_DAYS_DEFAULT = 7

    def _meli_stock_resync_days( self ):
        """Días tras los cuales una publicación vuelve a la cola aunque no haya
        habido movimientos. 0/False = desactivado."""
        self.ensure_one()
        config = self.connection_account and self.connection_account.configuration
        if config and "mercadolibre_stock_resync_days" in config._fields:
            value = config.mercadolibre_stock_resync_days
            # OJO con el chequeo de identidad: un 0 explicito significa
            # DESACTIVADO y hay que respetarlo (0 == False, pero `0 is not False`
            # es True, asi que 0 pasa y se devuelve tal cual). Solo caemos al
            # default si el campo viene None/False, es decir sin valor.
            if value is not None and value is not False:
                return value
        return self.MELI_STOCK_RESYNC_DAYS_DEFAULT

    def _meli_stock_resync_due( self ):
        """True si el ultimo push de stock es mas viejo que la ventana de resync.

        Sin esto, cualquier evento de stock que no quede reflejado en
        meli_stock_moves_update deja la publicacion desincronizada PARA SIEMPRE:
        el binding se queda en 'updated' y ningun cron lo vuelve a mirar."""
        self.ensure_one()
        days = self._meli_stock_resync_days()
        if not days or days <= 0:
            return False
        if not self.stock_update:
            return True
        try:
            limit = fields.Datetime.now() - timedelta(days=days)
        except Exception:
            return False
        return self.stock_update < limit

    def _meli_stock_status( self, notify=False ):
        for bind in self:

            bind.meli_stock_status = 'revision'

            # First check item status - if not active/paused, set appropriate status
            if bind.meli_last_status:
                if bind.meli_last_status == 'closed':
                    bind.meli_stock_status = 'revision_closed'
                    continue
                elif bind.meli_last_status == 'deleted':
                    bind.meli_stock_status = 'revision_closed'
                    continue
                elif bind.meli_last_status == 'not_found':
                    bind.meli_stock_status = 'revision_not_found'
                    continue
                elif bind.meli_last_status == 'inactive':
                    bind.meli_stock_status = 'revision_inactive'
                    continue
                elif bind.meli_last_status == 'under_review':
                    bind.meli_stock_status = 'revision_under_review'
                    continue

            # Check multiwarehouse first - this may have "Ok" in the message but still needs special status
            if ( bind.stock_error and "multiwarehouse" in bind.stock_error ):
                bind.meli_stock_status = 'multiwarehouse'
                continue

            if ( bind.stock_error and not ('Ok' in bind.stock_error ) ):

                bind.meli_stock_status = 'revision_error'

                if ( bind.stock_error and 'fulfillment' in bind.stock_error ):

                    bind.meli_stock_status = 'revision_fulfillment'

                if ( bind.stock_error and "has_bids:true" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_has_bids'

                if ( bind.stock_error and "under_review" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_under_review'

                if ( bind.stock_error and "closed" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_closed'

                if ( bind.stock_error and "inactive" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_inactive'

                if ( bind.stock_error and "blocked" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_blocked'

                if ( bind.stock_error and "stock_not_updatable" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_blocked_multiorigin'

                if ( bind.stock_error and "multiwarehouse" in bind.stock_error ):

                    bind.meli_stock_status = 'multiwarehouse'

                if ( bind.stock_error and "not_modifiable" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_not_modifiable'

                if ( bind.stock_error and "Variation id not found" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_variation_not_found'

                elif ( bind.stock_error and "not_found" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_not_found'

                if ( bind.stock_error and "different seller_sku" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_sku_mismatch'

                if ( bind.stock_error and "forbidden:403" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_forbidden'

                # 26.87 (F7): ML devolvio 200 pero la cantidad no quedo aplicada.
                # Va al final para que gane sobre 'revision_error' generico.
                if ( bind.stock_error and "stock_not_applied" in bind.stock_error ):

                    bind.meli_stock_status = 'revision_not_applied'

            else:
                if not bind.stock_error:
                    bind.stock_error = ''

                # 26.87 (F1d): red de seguridad — si el ultimo push es mas viejo
                # que la ventana de resync, vuelve a la cola aunque el sello de
                # movimientos diga que esta al dia.
                _resync_due = bind._meli_stock_resync_due()

                if (bind.meli_stock_moves_update):
                    if (bind.stock_update):
                        if ( bind.meli_stock_moves_update > bind.stock_update or _resync_due ):
                            bind.meli_stock_status = 'update'
                        else:
                            bind.meli_stock_status = 'updated'
                            if (bind.stock_error and bind.stock_error != 'Ok' ):
                                bind.meli_stock_status = 'updated_with_warning'

                    else:
                        bind.meli_stock_status = 'update'

                    if (bind.meli_stock_status == 'update' and bind._is_update_rt_needed() ):
                        bind.meli_stock_status = 'update_rt'

                else:
                    bind.meli_stock_status = 'revision_unmoved'
                    if (bind.stock_update and bind.stock>0):
                        bind.meli_stock_status = 'updated'
                        if (bind.stock_error and bind.stock_error != 'Ok' ):
                            bind.meli_stock_status = 'updated_with_warning'
                    # 26.87 (F1d): un binding sin sello de movimientos que ademas
                    # lleva mas de N dias sin publicarse tambien se resincroniza.
                    if (_resync_due and bind.meli_stock_status in ('updated', 'updated_with_warning', 'revision_unmoved')):
                        bind.meli_stock_status = 'update'


            if notify:
                if (bind.meli_stock_status == 'revision_error' and bind.connection_account.configuration.mercadolibre_seller_user):
                    base_url = ""
                    url = base_url+"/web#id="+str(bind.id)+"&menu_id=240&cids=7&action=503&model=mercadolibre.product&view_type=form"
                    bodymess = "Revisar la publicacion "+str(bind.conn_id)+"\n"+str(bind.stock_error)+"\n"+str(url)
                    if "Internal Server Error" in str(bind.stock_error):
                        bind.meli_stock_status == 'update'
                    else:
                        meli_message_post(bind.connection_account.configuration.mercadolibre_seller_user.partner_id, bodymess)


    meli_stock_status = fields.Selection(selection=[
        ('update','Actualizar'),
        ('update_rt','Actualizar RT'),
        ('updated','Actualizado'),
        ('updated_with_warning','Actualizado con aviso'),
        ('revision','Revisar'),
        ('revision_unmoved','Revisar sin movimientos'),
        ('revision_error','Revisar con error'),
        ('revision_blocked','Producto bloqueado en odoo'),
        ('revision_blocked_multiorigin','Producto bloqueado por MultiOrigen por API'),
        ('revision_fulfillment','Fulfillment'),
        ('revision_has_bids','No se puede actualizar por ventas activas'),
        ('revision_under_review','La publicacion esta bajo revision en ML'),
        ('revision_closed','La publicacion esta cerrada en ML'),
        ('revision_inactive','La publicacion esta inactiva en ML'),
        ('revision_not_modifiable','Stock no modificable en ML'),
        ('revision_not_found','El item no existe en ML (404)'),
        ('revision_sku_mismatch','SKU no coincide con ML (revisar)'),
        ('revision_variation_not_found','Variante no encontrada en ML'),
        ('revision_forbidden','Acceso denegado (403) - verificar cuenta'),
        # 26.87 (F7): ML contesto 200 pero NO aplico la cantidad publicada.
        ('revision_not_applied','ML aceptó el envío pero NO aplicó el stock'),
        ('multiwarehouse','Multiwarehouse - actualizar manualmente en ML')
    ], string="Status de stock", compute=_meli_stock_status, store=True, index=True)

    # N1 fix (ticket un caso): bounded auto re-queue of stranded RECOVERABLE bindings.
    # Counts how many times _meli_requeue_stranded_stock() has put this binding back
    # into the 'update' queue after it parked in a recoverable-error status. Capped
    # (MELI_STOCK_MAX_REQUEUE_RETRIES) so a genuinely-broken item does not cycle
    # forever; reset to 0 by _batch_update_stock_status() once the push succeeds.
    meli_stock_retry_count = fields.Integer(
        string="Reintentos de re-encolado de stock", default=0, copy=False,
        help="Veces que el binding fue re-encolado automáticamente tras un error "
             "recuperable de stock. Acotado para no ciclar sobre items rotos.")

    def get_stock_str(self,meli=None,config=None):
        stocks = []
        stocks_str = ""
        stocks_on_hand = -0.0
        stocks_available = -0.0
        stocks_meli = -0.0
        stocks_meli_str = ""
        #ss = variant._product_available()
        bindv = self
        variant = bindv.product_id
        product = variant
        product_tmpl = variant and variant.product_tmpl_id
        account = bindv.connection_account
        if not variant or not account:
            return stocks_str, stocks_on_hand, stocks_available, stocks_meli, stocks_meli_str

        config = account.configuration
        if not meli:
            meli = self.env['meli.util'].get_new_instance( account.company_id, account )
        #_logger.info("account.configuration.publish_stock_locations")
        #_logger.info(account.configuration.publish_stock_locations.mapped("id"))
        #locids = account.configuration.publish_stock_locations.mapped("id")
        meli_id = bindv.conn_id
        meli_id_variation = bindv.conn_variation_id

        locids = variant._meli_get_location_id( meli_id=meli_id, meli=meli,config=config)
        #_logger.info("get_stock_str locids:"+str(locids))

        quants = None
        sq_json = []
        new_meli_available_quantity = 0

        if (locids):
            #locids_id = [locid.id for locid in locids]
            #_logger.info("get_stock_str locids_id:"+str(locids_id))
            #sq = self.env["stock.quant"].search([('product_id','=',variant.id),('location_id','in',locids_id)],order="location_id asc")
            for loc in locids:
                quants_loc = self.env['stock.quant']._gather( product_id=variant, location_id=loc )

                if quants:
                    quants+= quants_loc

                if not quants:
                    quants = quants_loc

            if not quants:

                if (1==1 and 'mrp.bom' in self.env):

                    bom_id = self.env['mrp.bom'].search([('product_id','=',variant.id)],limit=1)

                    if not bom_id:
                        bom_id = self.env['mrp.bom'].search([('product_tmpl_id','=',product_tmpl.id)],limit=1)

                    if bom_id and bom_id.type == 'phantom':
                        _logger.info("get_stock_str Found BOM for: "+str(product.default_code))
                        _logger.info(bom_id.type)
                        _logger.info("bom_id:"+str(bom_id))
                        #chequear si el componente principal es fabricable
                        stock_material_max = 100000
                        stock_material = 0
                        candidate_quantity = new_meli_available_quantity
                        new_meli_available_quantity = 0
                        for bom_line in bom_id.bom_line_ids:
                            #if (bom_line.product_id.default_code.find(product_tmpl.code_prefix)==0):
                            if (bom_line.product_id):
                                #_logger.info(product_tmpl.code_prefix)
                                #_logger.info("bom product: " + str(bom_line.product_id.default_code) )
                                #for route in product.route_ids:
                                    #if (route.name in ['Fabricar','Manufacture']):
                                        #_logger.info("Fabricar")
                                    #    new_meli_available_quantity = 1
                                    #if (route.name in ['Comprar','Buy'] or route.name in ['Fabricar','Manufacture']):
                                    #_logger.info("Comprar")
                                virtual_comp_av = bom_line.product_id._meli_virtual_available( meli_id=meli_id, meli=meli,config=config)
                                #_logger.info("bom component stock: " + str(virtual_comp_av) )
                                stock_material = int(virtual_comp_av / bom_line.product_qty)
                                if stock_material>=0 and stock_material<=stock_material_max:
                                    stock_material_max = stock_material
                                    new_meli_available_quantity = stock_material_max
                                    #_logger.info("stock _meli_available_quantity based on minimum material available / " +str(bom_line.product_qty)+ ": " + str(new_meli_available_quantity))
                        sjson = {
                            "warehouseId": "KIT",
                            "warehouse": "KIT",
                            "quantity": new_meli_available_quantity,
                            "reserved": new_meli_available_quantity,
                            "available": new_meli_available_quantity
                        }
                        _logger.info( sjson )
                        sq_json.append(sjson)



                #qty_available_op = (quants and sum([(quant.quantity) for quant in quants])) or 0
            #_logger.info("get_stock_str locids_id:"+str(locids)+" quants:"+str(quants))

        if (quants):
            #_logger.info( sq )
            #_logger.info( sq.name )
            for s in quants:
                #TODO: filtrar por configuration.locations
                #TODO: merge de stocks
                #TODO: solo publicar available
                if ( s.location_id.usage == "internal"):
                    #_logger.info( s )
                    sjson = {
                        "warehouseId": s.location_id.id,
                        "warehouse": s.location_id.display_name,
                        "quantity": s.quantity,
                        "reserved": s.reserved_quantity,
                        "available": s.quantity - s.reserved_quantity
                    }
                    _logger.info( sjson )
                    sq_json.append(sjson)

        if sq_json:
            for sjson in sq_json:
                #stocks.append(sjson)
                stocks_str+= str(sjson["warehouse"])+str(": ")+str(sjson["quantity"])+str("/")+str(str(sjson["available"]))
                stocks_str+= " "
                stocks_on_hand+= sjson["quantity"]
                stocks_available+= sjson["available"]
                    #variant.stock = sjson["available"]
        res = "/items/%s" % (meli_id)
        #_logger.info("res:"+str(res)+" meli.access_token:"+str(meli.access_token))
        response = meli.get( res, {'access_token':meli.access_token})
        rjson = response.json()
        
        #Multi Origen
        #ver convivencia-full-y-flex
        if (rjson and "user_product_id" in rjson and rjson["user_product_id"]):
            get_uri_stock = "/user-products/" + str(rjson["user_product_id"]) + "/stock"
            multi_res = meli.get( get_uri_stock,  {'access_token':meli.access_token})
            multi_res_json = multi_res.json()
            if (multi_res_json):
                stocks_meli_str = ""
                multi_res_json_locations = False
                
                if "locations" in multi_res_json:
                    multi_res_json_locations = multi_res_json["locations"]

                if "variations" in multi_res_json and meli_id_variation:

                    #check actual variation
                                        
                    for var in multi_res_json["variations"]:

                        if ("variation_id" in var and str(var["variation_id"]) == str(meli_id_variation)):

                            multi_res_json_locations = var["locations"]

                if multi_res_json_locations:
                    locsep = ""
                    for location in multi_res_json_locations:
                        stocks_meli_str+= locsep + str(location["type"])+": "+str(location["quantity"])
                        locsep = " / "

        if (meli_id_variation):
            if rjson and "variations" in rjson:
                for var in rjson["variations"]:
                    #_logger.info("var:"+str(var))
                    if (str(var["id"])==str(meli_id_variation)):
                        #_logger.info("var YES:"+str(var))
                        stocks_meli = var["available_quantity"]

                        if "user_product_id" in var and var["user_product_id"]:
                            get_uri_stock = "/user-products/" + str(var["user_product_id"]) + "/stock"
                            multi_res = meli.get( get_uri_stock,  {'access_token':meli.access_token})
                            multi_res_json = multi_res.json()
                            if (multi_res_json):
                                stocks_meli_str = ""
                                multi_res_json_locations = False
                                
                                if "locations" in multi_res_json:
                                    multi_res_json_locations = multi_res_json["locations"]
                                    
                                if multi_res_json_locations:
                                    locsep = ""
                                    for location in multi_res_json_locations:
                                        stocks_meli_str+= locsep + str(location["type"])+": "+str(location["quantity"])
                                        locsep = " / "

        else:
            if rjson and "available_quantity" in rjson and rjson["available_quantity"]:
                stocks_meli = rjson["available_quantity"]

        return stocks_str, stocks_on_hand, stocks_available, stocks_meli, stocks_meli_str

    def _search_stock_resume_on_hand(self, operator, value):
        ids = []
        if (operator == '>' or operator == '<' or operator == '=' or operator == '>=' or operator == '<='):

            company = self.env.user.company_id
            account = company.producteca_connections and company.producteca_connections[0]
            if not account:
                return []

            _ps_enabled = account.configuration.publish_stock if hasattr(account.configuration, 'publish_stock') else False
            locids = account.configuration.publish_stock_locations.mapped("id") if (_ps_enabled and account.configuration.publish_stock_locations) else []
            if not locids:
                return []
            sq = self.env["stock.quant"].search([('location_id','in',locids),('quantity',operator,value)],order="quantity asc")
            if sq:
                pids = sq.mapped("product_id")
                vbids = self.search([('product_id','in', pids.ids)])
                if vbids:
                    ids = [('id','in',vbids.ids)]

        return ids

    def _search_stock_resume_available(self, operator, value):
        ids = []
        if (operator == '>' or operator == '<' or operator == '=' or operator == '>=' or operator == '<='):

            company = self.env.user.company_id
            account = company.producteca_connections and company.producteca_connections[0]

            if not account:
                return []
            _ps_enabled = account.configuration.publish_stock if hasattr(account.configuration, 'publish_stock') else False
            locids = account.configuration.publish_stock_locations.mapped("id") if (_ps_enabled and account.configuration.publish_stock_locations) else []

            rsq = self.env["stock.quant"].search([('location_id','in',locids),('reserved_quantity','>',0.0)],order="reserved_quantity asc")
            sq = self.env["stock.quant"].search([('location_id','in',locids),('quantity',operator,value)],order="quantity asc")

            pids = []

            if sq:
                products_quantity = sq.mapped("product_id")
                pids = products_quantity

            if rsq:
                products_reserved = rsq.mapped("product_id")
                pids_reserved = products_reserved.ids
                products_not_reserved = products_quantity - products_reserved
                for q in rsq:
                    qav = q.quantity - q.reserved_quantity
                    if OPERATORS[operator](qav, value):
                        products_not_reserved+= q.product_id
                pids = products_not_reserved

            if pids:
                #_logger.info(pids.ids)
                vbids = self.search([('product_id','in', pids.ids)])
                #_logger.info(vbids)
                if vbids:
                    ids = [('id','in',vbids.ids)]

        return ids


    def _meli_stock_resume(self):
        #_logger.info("Calculate stock resume")
        account_def = None
        meli = None
        config = None
        for bind in self:
            account = bind.connection_account
            if (account_def!=account):
                account_def = account
                meli = None
                if not meli:
                    meli = self.env['meli.util'].get_new_instance( account.company_id, account )
            config = account and account.configuration
            bind.meli_stock_resume = ""
            stocks_str, stocks_on_hand, stocks_available, stocks_meli, stocks_meli_multi = bind.get_stock_str(meli=meli,config=config)
            bind.meli_stock_resume = stocks_str
            # [caso-K01 #caso-K33] "En mano"/"Disponible" ya NO se escriben aca: antes eran una foto que
            # solo se tomaba al abrir el formulario, y la lista y el filtro "Disponible > 0"
            # trabajaban sobre esa foto (vacia en las que nunca se abrieron). Ahora se calculan
            # en vivo en _compute_meli_stock_local. Lo que viene de ML sigue siendo una foto
            # guardada, y queda fechada.
            bind.meli_stock_resume_mercadolibre = stocks_meli
            bind.meli_stock_resume_mercadolibre_multi = stocks_meli_multi
            bind.meli_stock_resume_date = fields.Datetime.now()

    def action_meli_stock_resume_refresh(self):
        """[caso-K01 #caso-K33] Refresca en lote la foto de ML (Stock en MercadoLibre / Resumen).
        Hace 2-3 GET a ML por vinculacion: usar sobre una seleccion, no sobre todo."""
        self._meli_stock_resume()
        return True

    def _meli_stock_logistic_type_hint(self):
        """[caso-K01 #caso-K33] Tipo logistico GUARDADO de la vinculacion (el que dejo el ultimo push)."""
        self.ensure_one()
        lt = self.meli_shipping_logistic_type
        if not lt and self.product_id and self.conn_id and self.product_id.meli_id == self.conn_id:
            lt = self.product_id.meli_shipping_logistic_type
        return lt or ""

    def _meli_stock_local_kit_qty(self, variant, bom, hint, config):
        """Mismo calculo de kit (BoM phantom) que get_stock_str, sin llamadas a ML."""
        stock_material_max = 100000
        qty = 0
        for bom_line in bom.bom_line_ids:
            if bom_line.product_id and bom_line.product_qty:
                comp = bom_line.product_id.with_context(meli_logistic_type_hint=hint)
                virtual_comp_av = comp._meli_virtual_available(meli_id=self.conn_id, meli=None, config=config)
                stock_material = int(virtual_comp_av / bom_line.product_qty)
                if stock_material >= 0 and stock_material <= stock_material_max:
                    stock_material_max = stock_material
                    qty = stock_material_max
        return qty

    def _meli_stock_local_values(self):
        """[caso-K01 #caso-K33] {binding_id: (en_mano, disponible)} con la existencia ACTUAL, SIN llamadas a ML.

        Mismas ubicaciones de las que publica la vinculacion (_meli_get_location_id, con el
        tipo logistico guardado: Full publica desde la ubicacion Full, el resto desde las
        suyas) y mismo calculo que get_stock_str (quants internos: cantidad / cantidad -
        reservado; kit phantom sin quants = minimo de componentes).
        Agrupa por (cuenta, tipo logistico): una busqueda de quants por grupo."""
        res = {}
        groups = {}
        for bind in self:
            res[bind.id] = (0.0, 0.0)
            variant = bind.product_id
            account = bind.connection_account
            if not variant or not account or not hasattr(variant, '_meli_get_location_id'):
                continue
            groups.setdefault((account.id, bind._meli_stock_logistic_type_hint()), []).append(bind)
        Quant = self.env['stock.quant']
        for (account_id, hint), binds in groups.items():
            first = binds[0]
            config = first.connection_account.configuration or None
            locs = first.product_id.with_context(meli_logistic_type_hint=hint)._meli_get_location_id(
                meli_id=first.conn_id, meli=None, config=config) or []
            loc_ids = [l.id for l in locs if l]
            if not loc_ids:
                continue
            pids = list({b.product_id.id for b in binds})
            on_hand, available = {}, {}
            for q in Quant.search([('product_id', 'in', pids), ('location_id', 'child_of', loc_ids),
                                   ('location_id.usage', '=', 'internal')]):
                on_hand[q.product_id.id] = on_hand.get(q.product_id.id, 0.0) + q.quantity
                available[q.product_id.id] = available.get(q.product_id.id, 0.0) + (q.quantity - q.reserved_quantity)
            boms_by_product, boms_by_tmpl = {}, {}
            no_quants = [b for b in binds if b.product_id.id not in on_hand]
            if no_quants and 'mrp.bom' in self.env:
                tmpl_ids = list({b.product_id.product_tmpl_id.id for b in no_quants})
                for bom in self.env['mrp.bom'].search(['|', ('product_id', 'in', [b.product_id.id for b in no_quants]),
                                                       ('product_tmpl_id', 'in', tmpl_ids)]):
                    if bom.product_id:
                        boms_by_product.setdefault(bom.product_id.id, bom)
                    boms_by_tmpl.setdefault(bom.product_tmpl_id.id, bom)
            for bind in binds:
                pid = bind.product_id.id
                if pid in on_hand:
                    res[bind.id] = (on_hand[pid], available[pid])
                    continue
                bom = boms_by_product.get(pid) or boms_by_tmpl.get(bind.product_id.product_tmpl_id.id)
                if bom and bom.type == 'phantom':
                    kit = bind._meli_stock_local_kit_qty(bind.product_id, bom, hint, config)
                    res[bind.id] = (kit, kit)
        return res

    def _compute_meli_stock_local(self):
        values = self._meli_stock_local_values()
        for bind in self:
            on_hand, available = values.get(bind.id, (0.0, 0.0))
            bind.meli_stock_resume_on_hand = on_hand
            bind.meli_stock_resume_available = available

    _MELI_STOCK_LOCAL_OPS = {
        '=': lambda a, b: a == b, '!=': lambda a, b: a != b,
        '<': lambda a, b: a < b, '>': lambda a, b: a > b,
        '<=': lambda a, b: a <= b, '>=': lambda a, b: a >= b,
    }

    def _search_meli_stock_local(self, operator, value, index):
        """[caso-K01 #caso-K33] Filtro en vivo ("Disponible > 0", "En mano = 0"...)."""
        if operator in ('in', 'not in'):
            values = [float(v or 0.0) for v in (value or [])]
            match = (lambda a: a in values) if operator == 'in' else (lambda a: a not in values)
        elif operator in self._MELI_STOCK_LOCAL_OPS:
            fn, ref = self._MELI_STOCK_LOCAL_OPS[operator], float(value or 0.0)
            match = lambda a: fn(a, ref)
        else:
            raise UserError(_("Operador no soportado para el stock de la vinculacion: %s") % operator)
        binds = self.search([('product_id', '!=', False), ('connection_account', '!=', False)])
        values_by_id = binds._meli_stock_local_values()
        return [('id', 'in', [bid for bid, vals in values_by_id.items() if match(vals[index])])]

    def _search_meli_stock_on_hand(self, operator, value):
        return self._search_meli_stock_local(operator, value, 0)

    def _search_meli_stock_available(self, operator, value):
        return self._search_meli_stock_local(operator, value, 1)

    meli_stock_resume = fields.Char(string="Stock Resumen", compute="_meli_stock_resume", store=False )
    meli_stock_resume_on_hand = fields.Float(string="En mano", compute="_compute_meli_stock_local",
        search="_search_meli_stock_on_hand", store=False,
        help="Existencia actual en las ubicaciones desde las que publica esta vinculacion (no consulta Mercado Libre).")
    meli_stock_resume_available = fields.Float(string="Disponible", compute="_compute_meli_stock_local",
        search="_search_meli_stock_available", store=False,
        help="En mano menos lo reservado, en las ubicaciones desde las que publica esta vinculacion (no consulta Mercado Libre).")
    meli_stock_resume_mercadolibre = fields.Float(string="Stock en MercadoLibre")

    meli_stock_resume_mercadolibre_multi = fields.Char(string="Stock en Mercadolibre Resumen" )
    meli_stock_resume_date = fields.Datetime(string="Resumen ML actualizado", readonly=True, copy=False,
        help="Cuando se consulto por ultima vez a Mercado Libre el Stock en MercadoLibre / Resumen.")
    #meli_stock_resume_on_hand = fields.Float(string="Qty On hand", compute="_meli_stock_resume"
                        #, search="_search_stock_resume_on_hand"
    #                    )
    #meli_stock_resume_available = fields.Float(string="Qty Available", compute="_meli_stock_resume"
    #                    #, search="_search_stock_resume_available"
    #                    )
    meli_permalink = fields.Char( compute=product_get_meli_update, size=256, string='Link',help='PermaLink in MercadoLibre', store=False )
    meli_permalink_edit = fields.Char( compute=product_get_meli_update, size=256, string='Link Edit',help='PermaLink Edit in MercadoLibre', store=False )
    meli_permalink_api = fields.Char( compute=product_get_meli_update, size=256, string='Link API',help='PermaLink API MercadoLibre', store=False )
    meli_state = fields.Boolean( compute=product_get_meli_update, string='Login',help="Inicio de sesión requerida", store=False )
    meli_status = fields.Char( compute=product_get_meli_update, size=128, string='Status', help="Estado del producto en ML", store=False )
    meli_sub_status = fields.Char( compute=product_get_meli_update, size=128, string='Sub status',help="Sub Estado del producto en ML", store=False )

    meli_last_status = fields.Selection([
        ('active', 'Activo'),
        ('paused', 'Pausado'),
        ('closed', 'Cerrado'),
        ('deleted', 'Borrado'),
        ('not_found', 'No encontrado'),
        ('under_review', 'Bajo revisión'),
        ('inactive', 'Inactivo'),
    ], string="Estado ML", index=True)

    orphan_reason = fields.Selection([
        ('ok', 'OK'),
        ('unassigned', 'Producto desasignado'),
        ('product_archived', 'Producto archivado'),
        ('ml_closed', 'Publicación cerrada en ML'),
        ('ml_not_found', 'Publicación no existe en ML (404)'),
        ('ml_inactive', 'Publicación inactiva en ML'),
        ('ml_deleted', 'Publicación eliminada en ML'),
    ], string="Estado de vinculación", compute='_compute_orphan_reason', store=True, index=True)

    @api.depends('product_id', 'product_id.active', 'meli_last_status')
    def _compute_orphan_reason(self):
        for bind in self:
            if not bind.product_id:
                bind.orphan_reason = 'unassigned'
            elif bind.product_id and not bind.product_id.active:
                bind.orphan_reason = 'product_archived'
            elif bind.meli_last_status == 'closed':
                bind.orphan_reason = 'ml_closed'
            elif bind.meli_last_status == 'not_found':
                bind.orphan_reason = 'ml_not_found'
            elif bind.meli_last_status == 'inactive':
                bind.orphan_reason = 'ml_inactive'
            elif bind.meli_last_status == 'deleted':
                bind.orphan_reason = 'ml_deleted'
            else:
                bind.orphan_reason = 'ok'

    meli_attributes = fields.Text(string='Atributos')
    meli_tags = fields.Text(related="binding_product_tmpl_id.meli_tags", string='Tags',readonly=True)
    meli_sale_terms = fields.Text(related="binding_product_tmpl_id.meli_sale_terms", string='Sale Terms',readonly=True)

    def _parse_meli_tags(self, raw):
        """Delegamos al template si existe, sino usamos una versión local."""
        if self.binding_product_tmpl_id:
            return self.binding_product_tmpl_id._parse_meli_tags(raw)
        # fallback simple
        if isinstance(raw, list):
            return [str(t) for t in raw if t]
        return []

    def _parse_meli_sale_terms(self, raw):
        if self.binding_product_tmpl_id:
            return self.binding_product_tmpl_id._parse_meli_sale_terms(raw)
        if isinstance(raw, list):
            return [str(t) for t in raw if t]
        return []

    def _badge(self, label, value, variant='neutral', icon='fa-circle'):
        """Chip con estilo inline (independiente del theme)."""
        if not value:
            return ''
        palette = {
            'neutral':  {'bg': '#f4f6f8', 'bd': '#e5eaef', 'fg': '#2b3648'},
            'primary':  {'bg': '#eef3ff', 'bd': '#d8e3ff', 'fg': '#2042a6'},
            'success':  {'bg': '#ecfbf3', 'bd': '#c9f2dc', 'fg': '#1d7f50'},
            'warning':  {'bg': '#fff7e8', 'bd': '#ffe6b3', 'fg': '#8a5b00'},
            'danger':   {'bg': '#ffeff0', 'bd': '#ffd3d6', 'fg': '#9a1b1f'},
        }.get(variant or 'neutral')
        style = (
            f"display:inline-flex;align-items:center;gap:8px;"
            f"padding:6px 10px;border-radius:18px;"
            f"background:{palette['bg']};border:1px solid {palette['bd']};"
            f"color:{palette['fg']};font-size:13px;line-height:1.2;white-space:nowrap;"
        )
        icon_style = "font-size:12px;opacity:.8"
        return (
            f'<div style="{style}">'
            f'<i class="fa {icon}" style="{icon_style}"></i>'
            f'<span><b>{label}:</b> {value}</span>'
            f'</div>'
        )

    def _compute_summary_header_html(self):
        """Resumen visual en el encabezado de la variante ML."""
        for bind in self:
            wrap_style = (
                "display:flex;flex-wrap:wrap;gap:8px 10px;"
                "align-items:center;margin:6px 0 12px 0;"
            )
            html_parts = [f'<div style="{wrap_style}">']

            # -----------------------------------------------------------------
            # Estado ML de la variante (directo)
            # -----------------------------------------------------------------
            status = (bind.meli_status or "").strip()
            sub_status = (bind.meli_sub_status or "").strip()

            status_variant = "neutral"
            if status == "active":
                status_variant = "success"
            elif status == "paused":
                status_variant = "warning"
            elif status in ("closed", "under_review"):
                status_variant = "danger"

            if status:
                status_text = status.replace("_", " ").upper()
                color_map = {
                    "success": "#2ECC71",
                    "warning": "#F1C40F",
                    "danger": "#E74C3C",
                    "neutral": "#7F8C8D",
                }
                bg = color_map.get(status_variant, "#7F8C8D")
                html_parts.append(
                    f'<span style="font-size:20px;font-weight:600;'
                    f'padding:8px 18px;border-radius:999px;'
                    f'background-color:{bg};color:#FFFFFF;'
                    f'display:inline-flex;align-items:center;gap:6px;">'
                    f'<i class="fa fa-circle"></i>{status_text}'
                    f'</span>'
                )

            if sub_status:
                html_parts.append(
                    self._badge(
                        "Subestado",
                        sub_status.replace("_", " "),
                        "neutral",
                        "fa-info-circle",
                    )
                )

            # -----------------------------------------------------------------
            # Tags / Sale Terms (desde el template)
            # -----------------------------------------------------------------
            for tag in bind._parse_meli_tags(bind.meli_tags):
                html_parts.append(
                    self._badge("Tag", tag, "primary", "fa-tag")
                )

            for st in bind._parse_meli_sale_terms(bind.meli_sale_terms):
                html_parts.append(
                    self._badge("Condición", st, "neutral", "fa-file-text-o")
                )

            # -----------------------------------------------------------------
            # IDs, SKU, Stock, Precio
            # -----------------------------------------------------------------
            if bind.meli_id:
                html_parts.append(
                    self._badge("Item Id", bind.meli_id, "neutral", "fa-hashtag")
                )
            if bind.meli_id_variation:
                html_parts.append(
                    self._badge("Var Id", bind.meli_id_variation, "neutral", "fa-random")
                )
            if bind.sku:
                html_parts.append(
                    self._badge("SKU", bind.sku, "neutral", "fa-barcode")
                )

            if bind.meli_stock_resume:
                html_parts.append(
                    self._badge("Stock", bind.meli_stock_resume, "neutral", "fa-cubes")
                )

            if bind.meli_price:
                html_parts.append(
                    self._badge("Precio ML", bind.meli_price, "primary", "fa-money")
                )

            html_parts.append("</div>")
            bind.summary_header_html = "".join(html_parts)

    # HTML del encabezado
    summary_header_html = fields.Html(
        string="Resumen",
        compute="_compute_summary_header_html",
        sanitize=False,
        store=False,
    )

    meli_model = fields.Char(string="Modelo",size=256)
    meli_brand = fields.Char(string="Marca",size=256)
    meli_gender = fields.Char(string="Genero",index=True)
    meli_grid_chart_id = fields.Many2one("mercadolibre.grid.chart",string="Guia de talles")

    meli_default_stock_product = fields.Many2one("product.product","Producto de referencia para stock")

    #TODO deprecated
    meli_id_variation = fields.Char( string='Variation Id',help='Id de Variante de Meli', size=256)

    meli_user_product_id = fields.Char(string='Product User Id')

    meli_catalog_listing = fields.Boolean(string='Catalog Listing')
    meli_catalog_product_id = fields.Char(string='Catalog Product Id', size=256)
    meli_catalog_item_relations = fields.Char(string='Catalog Item Relations', size=256)
    meli_catalog_automatic_relist = fields.Boolean(string='Catalog Auto Relist')

    meli_shipping_logistic_type = fields.Char(string="Logistic Type",index=True)
    meli_shipping_free = fields.Boolean(string="Shipping Free",default=False,index=True)


    meli_inventory_id = fields.Char(string="Inventory Id",index=True)

    meli_shipping_mode = fields.Char(string="Shipping Mode",help="Shipping modes (por usuario): custom, not_specified, me2. https://api.mercadolibre.com/users/USERID/shipping_preferences",index=True)
    meli_shipping_method = fields.Char(string="Shipping Method",help="Shipping methods: https://api.mercadolibre.com/sites/SITEID/shipping_methods",index=True)

    meli_max_purchase_quantity = fields.Integer(string='Max Compra', help='Cantidad maxima por compra en ML')
    meli_manufacturing_time = fields.Char(string='Manufacturing time', help='Tiempo de fabricacion (30 días)')

    #meli_update_stock_blocked = fields.Boolean(string="Bloquea publicacion",default=False,index=True)
    meli_update_stock_blocked = fields.Boolean(string="Bloquea publicacion",related="binding_product_tmpl_id.meli_update_stock_blocked")

    def copy_from_meli_oerp( self ):
        for bind in self:
            product = bind.product_id
            #_logger.info("variant bind copy_from_meli_oerp meli_id: %s meli_id_variation: %s" % (str(bind.conn_id),str(bind.conn_variation_id)))
            #_logger.info("variant bind copy_from_meli_oerp p.meli_id: %s p.meli_id_variation: %s" % (str(product.meli_id),str(product.meli_id_variation)))
            if (product.meli_id_variation!=bind.conn_variation_id):
                pb2 = self.env["mercadolibre.product"].search([ ('conn_id','=',product.meli_id),
                                                          ('conn_variation_id','=',product.meli_id_variation),
                                                          ('product_tmpl_id','=',bind.product_tmpl_id),
                                                          ('connection_account','=',bind.connection_account.id)])
                if pb2:
                    #_logger.info("Look! Duplicates for: "+str(product.meli_id_variation))
                    return

            #id assignation
            bind.meli_id = product.meli_id
            bind.meli_id_variation = product.meli_id_variation
            bind.conn_id = product.meli_id
            bind.conn_variation_id = product.meli_id_variation

            #TODO: sku assign?
            bind.sku = product.default_code
            bind.barcode = product.barcode

            #basic info
            bind.meli_title = product.meli_title
            bind.meli_description = product.meli_description
            bind.meli_category = product.meli_category
            bind.meli_price = product.meli_price
            bind.price = product.meli_price
            bind.stock = product.meli_available_quantity
            bind.meli_available_quantity = product.meli_available_quantity

            bind.meli_shipping_logistic_type = product.meli_shipping_logistic_type
            bind.meli_shipping_free = product.meli_shipping_free

            #attributes
            bind.meli_attributes = product.meli_attributes
            bind.meli_model = product.meli_model
            bind.meli_brand = product.meli_brand
            bind.meli_gender = bind.product_tmpl_id and bind.product_tmpl_id.meli_gender
            bind.meli_grid_chart_id = bind.product_tmpl_id and bind.product_tmpl_id.meli_grid_chart_id

            #publish ref info
            bind.meli_pub = product.meli_pub
            #bind.meli_master = product.meli_master
            #bind.meli_ids = product.meli_ids

            #config info
            bind.meli_currency = product.meli_currency
            bind.meli_condition = product.meli_condition
            bind.meli_warranty = product.meli_warranty
            bind.meli_listing_type = product.meli_listing_type
            bind.meli_dimensions = product.meli_dimensions

    def meli_stamp_last_status( self, rjson ):
        """Estampa `meli_last_status` desde el json del item que YA tenemos.

        26.123 (caso-K32 cliente N): el publish creaba/actualizaba el binding sin
        tocar `meli_last_status`. Como `meli_status` (no stored) se computa
        leyendo ese campo y cae a "unknown" cuando esta vacio, la ficha del
        producto se quedaba SIN el icono ni los botones de MercadoLibre, y solo
        se arreglaba si mas tarde pasaba un webhook o un cron por encima.

        No agrega ni una llamada a la API: el estado viene en la respuesta del
        POST/PUT del item (y en el re-fetch que el publish ya hace). La
        optimizacion que saco los ~19 GETs por apertura de formulario se respeta.

        Devuelve el estado estampado, o None si el json no traia uno usable.
        """
        status = meli_status_from_rjson(rjson)
        if not status:
            return None
        for bindv in self:
            try:
                if bindv.meli_last_status != status:
                    bindv.sudo().write({'meli_last_status': status})
            except Exception as e:
                # Estampar el estado NUNCA puede voltear una publicacion exitosa.
                _logger.warning("meli_stamp_last_status: no se pudo estampar '%s' en %s: %s",
                                status, bindv, e)
        return status

    def copy_from_rjson( self, rjson, meli=None ):
        #copia correctamente el sku correspondiente al conn_variation_id
        #conn_variation_id debe setearse al traer el producto ?
        #_logger.info("variant bind >> copy_from_rjson")
        if not rjson:
            return

        for bind in self:
            account = bind.connection_account
            config = account.configuration
            #productT = bindT.product_tmpl_id
            #basic info
            catid, wwwid = self.env["mercadolibre.category"].meli_get_category( rjson.get('category_id',''), meli=meli, create_missing_website=config.mercadolibre_create_website_categories, config=config )
            desplain = ("description" in rjson and rjson["description"]) or None
            seller_sku = None
            barcode = None
            variant_stock = 0
            if "variations" in rjson and len(rjson["variations"]):
                for var in rjson["variations"]:
                    if not "id" in var:
                        _logger.error(var)
                    if ("id" in var and str(var["id"]) == str(bind.conn_variation_id) ):
                        #_logger.info("FOUNDED IN ML VARIATIONS same variation id !!! " +str(bind.conn_variation_id))
                        seller_sku = ("seller_sku" in var and var["seller_sku"]) or ""
                        barcode = ("barcode" in var and var["barcode"]) or ""
                        #_logger.info("IN ML VARIATIONS seller_sku is " +str(seller_sku)+ " and barcode is:" + str(barcode))
                        variant_stock = ("available_quantity" in var and var["available_quantity"])
                    if (not bind.conn_variation_id):
                        if (len(rjson["variations"])==1):
                            seller_sku = ("seller_sku" in var and var["seller_sku"]) or None
                            barcode = ("barcode" in var and var["barcode"]) or None
                            variant_stock = ("available_quantity" in var and var["available_quantity"])
                            bind.conn_variation_id = str(var["id"])

                if not seller_sku:
                    _logger.error("seller sku not found >> meli_id: "+str(bind.conn_id)+" varid: "+str(bind.conn_variation_id))
            if not seller_sku:
                seller_sku = ("seller_sku" in rjson and rjson["seller_sku"]) or ""
            if not barcode:
                barcode = ("barcode" in rjson and rjson["barcode"]) or ""
            fields = {
                'meli_title': rjson['title'].encode("utf-8"),
                'meli_listing_type': rjson['listing_type_id'],
                'meli_buying_mode':rjson['buying_mode'],
                'meli_local_pick_up': rjson['local_pick_up'] if 'local_pick_up' in rjson else False,
                'meli_free_shipping': rjson['free_shipping'] if 'free_shipping' in rjson else False,
                'meli_price': str(rjson['price']),
                'price': str(rjson['price']),
                'meli_available_quantity': variant_stock,
                'stock': variant_stock,
                'meli_currency': rjson['currency_id'],
                'meli_condition': rjson['condition'],
                #'meli_available_quantity': rjson['available_quantity'],
                'meli_warranty': rjson['warranty'],
                'meli_category': catid,
                'meli_id': rjson["id"],
                'sku': seller_sku or '',
                'barcode': barcode or '',
                'meli_id_variation': bind.conn_variation_id,
                #'meli_imagen_link': rjson['thumbnail'],
                #'meli_video': str(vid),
                #'meli_dimensions': meli_dim_str,
            }
            # 26.123 (caso-K32 cliente N): el estado del item viaja en el MISMO json que
            # ya estamos copiando. Guardarlo aca cubre de una todos los caminos que
            # pasan por copy_from_rjson (publish, import, rebind, fetch) sin sumar
            # un solo GET a ML. Si no se guarda, `meli_status` cae a "unknown" y la
            # ficha del producto se queda sin el icono/los botones de MercadoLibre.
            _ml_status = meli_status_from_rjson(rjson)
            if _ml_status:
                fields['meli_last_status'] = _ml_status
            if desplain:

                #publication specific banner
                bindT = bind.binding_product_tmpl_id
                mlbanner = bindT and bindT.product_tmpl_id.meli_mercadolibre_banner
                #configuration banner
                mlbanner = mlbanner or (config and config.mercadolibre_banner)
                meli_description = ""
                if (mlbanner):
                    #get the text, not the header nor the footer
                    meli_description = mlbanner.get_from_ml_description( desplain )

                fields["meli_description"] = meli_description

            meli_shipping_logistic_type = ( rjson and "shipping" in rjson and "logistic_type" in rjson["shipping"] and rjson["shipping"]["logistic_type"] ) or ""
            if ( rjson and "user_product_id" in rjson and rjson["user_product_id"]):
                meli_shipping_logistic_type+="_user_product_id"            
            meli_shipping_logistic_type and fields.update({'meli_shipping_logistic_type': meli_shipping_logistic_type })

            meli_shipping_free = ( rjson and "shipping" in rjson and "free_shipping" in rjson["shipping"] and rjson["shipping"]["free_shipping"] ) or False
            meli_shipping_free and fields.update({'meli_shipping_free': meli_shipping_free })

            #_logger.info("REWRITING variant bind >> copy_from_rjson: var id: "+str(fields["meli_id_variation"])+" sku: "+str(fields["sku"])+" barcode: "+str(fields["barcode"]) )
            # MULTIGET PROFILING
            import time as _time_bind
            _tb0 = _time_bind.time()
            bind.write(fields)
            _tb1 = _time_bind.time()
            if _tb1 - _tb0 > 0.01:
                _logger.info("MULTIGET copy_from_rjson write: %.3fs conn_id=%s", _tb1-_tb0, bind.conn_id)

    def fetch_meli_product( self, meli = None, rjson = None, from_meli_oerp=False ):
        #_logger.info("binding variant fetch_meli_product")

        #fetch product full data from MELI into binding
        for bind in self:

            account = bind.connection_account
            config = account and account.configuration
            meli_id = bind.conn_id
            meli_id_variation = bind.conn_variation_id

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            if not meli_id or not meli:
                continue;

            if from_meli_oerp: #TODO, check validity and meli_id in bindT.product_tmpl_id.meli_ids:
                bind.copy_from_meli_oerp()
            else:
                rjson = rjson or account.fetch_meli_product( meli_id=meli_id, meli=meli )
                bind.copy_from_rjson( rjson=rjson, meli=meli )

            if (config.mercadolibre_update_local_stock):
                product = bind.product_id
                #_logger.info("product_update_stock: "+str(bind.stock))
                #_logger.info("product_update_stock: rjson: "+str(rjson))
                #_logger.info("meli: "+str(meli))
                #_logger.info("account: "+str(account))
                product and product.product_update_stock(stock=bind.stock, meli_id=meli_id, meli=meli, config=config )

    def update_pl_price( self, meli_price=meli_price):

        bind = self
        account = bind.connection_account
        config = account and account.configuration

        force_variant = False
        pli = self.env['product.pricelist.item']
        pli_tpl = False

        pl = bind.meli_pricelist
        product = bind.product_id
        product_template = product.product_tmpl_id

        if force_variant:
            pli_tpl = False
        else:
            pli_tpl = pli.search([('pricelist_id','in',[pl.id]),('product_tmpl_id','=',product_template.id)])

        ml_price_converted = product._meli_price_converted( meli_price=meli_price, config=config )

        pli_var = pli.search([('pricelist_id','in',[pl.id]),('product_id','=',product.id)])

        if (pli_tpl or pli_var):
            #_logger.info("Updating price")
            # Odoo 18/19: product.pricelist.price_get() fue eliminado (AttributeError al
            # publicar producto nuevo). old_price no se usaba -> escribir fixed_price directo.
            if pli_tpl:
                pli_tpl.write({'fixed_price': float(ml_price_converted)})
            if pli_var:
                pli_var.write({'fixed_price': float(ml_price_converted)})
        else:
            #_logger.info("Creating price")
            if force_variant and not pli_var:
                pli_var = pli.create({
                        'product_id': product.id,
                        'min_quantity': 0,
                        'applied_on': '0_product_variant',
                        'pricelist_id': pl.id,
                        'compute_price': 'fixed',
                        'currency_id': pl.currency_id.id,
                        'fixed_price': float(ml_price_converted)
                         })
            else:
                if not force_variant and not pli_tpl:
                    pli_tpl = pli.create({
                            'product_tmpl_id': product_template.id,
                            'min_quantity': 0,
                            'applied_on': '1_product',
                            'pricelist_id': pl.id,
                            'compute_price': 'fixed',
                            'currency_id': pl.currency_id.id,
                            'fixed_price': float(ml_price_converted)
                             })


    def update_price( self, meli_price=False, meli_pricelist=False, meli_price_fixed=False ):
        for bind in self:

            account = bind.connection_account
            config = account and account.configuration

            #Update variant product price
            product = bind.product_id
            product_tmpl = product and product.product_tmpl_id
            base_meli_price = product.set_meli_price(config=config)
            bindT = bind.binding_product_tmpl_id

            #set if manually set
            #_logger.info("1 bind.meli_price: "+str(bind.meli_price))
            #_logger.info("bindT.meli_price: "+str(bindT.meli_price))
            bind.meli_pricelist = meli_pricelist or bind.meli_pricelist or (bindT and bindT.meli_pricelist)
            bind.meli_price_fixed = meli_price_fixed or bind.meli_price_fixed or (bindT and bindT.meli_price_fixed)
            bind.meli_price = meli_price or (bindT and bindT.meli_price) or bind.meli_price
            #_logger.info("2 bind.meli_price: "+str(bind.meli_price))

            #if price is fixed use binding price or if not, using odoo product pricing
            if bind.meli_price_fixed:
                bind.meli_price = bind.meli_price or bind.product_id.meli_price or bind.product_id.product_tmpl_id.meli_price
            elif not bind.meli_price_fixed:
                bind.meli_price = base_meli_price


            #_logger.info("3 bind.meli_price: "+str(bind.meli_price))
            #price list is preferred if selected, always, but only if it's selected
            pl = bind.meli_pricelist
            #check binding currency based for USD
            pl = pl or (bind.meli_currency and bind.meli_currency in ["USD"] and config.mercadolibre_pricelist_usd and config.mercadolibre_pricelist_usd.currency_id.name=="USD" and config.mercadolibre_pricelist_usd)
            product = bind.product_id
            if pl and product:
                #_logger.info("Pricelist:"+str(pl and pl.name)+" product:"+str(product.name)+" ["+str(product.default_code)+"]")
                #if manual set in pricelist
                if (meli_price):
                    bind.update_pl_price(meli_price=meli_price)
                #if not update from pricelist
                return_val = get_price_from_pl( pl, product, 1.0 )
                if pl.id in return_val:
                    new_price = return_val[pl.id]
                    #added taxes here
                    tax_excluded = ml_tax_excluded(self,config=config)
                    if ( price_list_apply_tax and tax_excluded and product_tmpl and product_tmpl.taxes_id ):
                        #_logger.info("Adjust taxes for publish")
                        # [caso-K10] solo los impuestos de la compania de la config (antes sumaba los de todas: /1,42 con dos)
                        txpercent, txfixed = ml_sale_tax_rates(product_tmpl.taxes_id, (account and account.company_id))
                        if (txfixed>0 or txpercent>0):
                            #_logger.info("Tx Total:"+str(txtotal)+" to Price:"+str(ml_price_converted))
                            new_price = txfixed + new_price * (1.0 + txpercent*0.01)

                    #_logger.info("Price adjusted:"+str(new_price))

                    if (new_price>0):
                        bind.meli_price = new_price

            bind.meli_price = round(float(bind.meli_price),2)

            if (product_tmpl.meli_currency and (product_tmpl.meli_currency == 'MXN' or product_tmpl.meli_currency == 'USD')):
                bind.meli_price = str((float(bind.meli_price)))
            elif (product_tmpl.meli_currency and product_tmpl.meli_currency == 'CLP'):
                bind.meli_price = str( int( int( math.floor(int(bind.meli_price) / 100 ) * 100 + 90 ) ) )
            else:
                bind.meli_price = math.ceil(float(bind.meli_price))
                bind.meli_price = str(int(float(bind.meli_price)))

            #_logger.info("update_price meli_price (forced?): "+str(meli_price))
            #_logger.info("update_price bind.meli_price: "+str(bind.meli_price))
            #_logger.info("update_price bind.meli_pricelist: "+str(bind.meli_pricelist))
            #_logger.info("update_price bind.meli_price_fixed: "+str(bind.meli_price_fixed))

            bind.price = bind.meli_price

            bind._onchange_meli_price()


    def product_post( self, meli=None ):
        #_logger.info("MercadoLibre Bind Product Post")
        result = []
        for bind in self:

            product = bind.product_id
            account = bind.connection_account
            meli_id = bind.conn_id
            meli_id_variation = bind.conn_variation_id
            bind_tpl = bind.binding_product_tmpl_id

            # 26.101 (un cliente): idem stock/precio/titulo. Ademas el `for`
            # reusaba el `meli` resuelto para el PRIMER binding en todos los
            # siguientes, aunque fueran de otra cuenta.
            if account:
                meli = account._meli_instance_or_mine( meli )
            elif not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            if not meli_id or not meli:
                continue;

            if product:
                res = product.product_post( bind_tpl=bind_tpl, bind=bind, meli=meli, config=account.configuration )
                result.append(res)
        #_logger.info( "result: " + str(result) )
        return result

    def product_update( self ):
        _logger.info("meli_oerp_multiple >> MercadoLibre Product Binding Update")
        pass;

    #def category_predictor( self ):
    #    #_logger.info("MercadoLibre Product template Category Predictor")
    def product_meli_get_product( self, meli=None, rjson=None, import_images=True ):

        #_logger.info("meli_oerp_multiple >> product_meli_get_product >> (Binding) MercadoLibre Product product_meli_get_product: "+str(meli))
        #_logger.info(str(rjson))
        for bind in self:

            account = bind.connection_account
            product = bind.product_id
            product_template = bind.product_tmpl_id
            meli_id = bind.conn_id
            meli_id_variation = bind.conn_variation_id

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            rjson = rjson or account.fetch_meli_product( meli_id=meli_id, meli=meli )
            #is this binding the master odoo product meli id?
            meli_oerp_match_import = (product.meli_id and meli_id and product.meli_id==meli_id)
            #just bind, never import
            bind_only = (meli_oerp_match_import==False)
            #TODO: recheck to not import ML to Odoo Product if this is not the principal bind conn_id
            if (not product.meli_id or meli_oerp_match_import):
                #_logger.info("product_meli_get_product: meli_oerp_match_import:" + str(meli_oerp_match_import) +" bind_only: "+str(bind_only))
                res = product.product_meli_get_product( meli_id=meli_id, account=account, meli=meli, rjson=rjson, import_images=import_images )
                #_logger.info("variant get product >> product_meli_get_product res:"+str(res))
                if res and "error" in res:
                    _logger.error(res)
                    return res

            #TODO: recheck bindings for this product and this binding
            if (product_template):
                bindT = product_template.mercadolibre_bind_to( account=account, meli_id=meli_id, bind_variants=True, meli=meli, rjson=rjson, bind_only=bind_only )
                if bindT:
                    # from_meli_oerp = True copy form recent imported
                    bindT.fetch_meli_product( meli=meli, from_meli_oerp=False, fetch_variants=True, rjson=rjson )

    def action_category_predictor( self ):
        _logger.info("MercadoLibre Product action_category_predictor")
        pass;
    
    def _fetch_meli_user_product_id( self, meli=None, item_json={} ):
        
        self.ensure_one()
        
        upid = None
        
        account = self.connection_account
        config = account and account.configuration
        meli_id = self.conn_id
        meli_id_variation = self.conn_variation_id
        product = self.product_id
        
        if not account:
            return upid
        
        if not meli:
            meli = self.env['meli.util'].get_new_instance( account.company_id, account )

        if not item_json:
            item_json = account and meli_id and meli and account.fetch_meli_product( meli_id=meli_id, meli=meli )

        return product._fetch_meli_user_product_id( meli_id=meli_id, meli_id_variation=meli_id_variation, meli=meli, config=config, item_json=item_json )
    

    #VARIANT binding product_post_stock
    def _meli_stock_rebind_variation( self, variation_id ):
        """131 (26.337, port de 13.0.26.336): re-vincula este binding a otra variacion de ML ANTES de publicar stock.

        Se valida primero (otra fila de la misma cuenta+publicacion ya tiene esa variacion => error, sin escribir)
        y se escribe en un savepoint con flush: si la base la rechaza, el error vuelve aca y NO sale el PUT a ML.
        Devuelve None si quedo re-vinculado, o {"error": ...}.
        """
        self.ensure_one()
        variation_id = str(variation_id)
        other = self.search([
            ('connection_account', '=', self.connection_account.id),
            ('conn_id', '=', self.conn_id),
            ('conn_variation_id', '=', variation_id),
            ('id', '!=', self.id),
        ], limit=1)
        if other:
            return { "error": "Variacion ya vinculada: %s/%s esta vinculada a %s (binding %s). No se re-vincula %s (binding %s, variacion %s) ni se publica stock: revisar los SKU o la vinculacion." % (
                self.conn_id, variation_id, other.product_id.display_name, other.id,
                self.product_id.display_name, self.id, self.conn_variation_id ) }
        _logger.warning("131 post stock: re-vinculando binding %s %s variacion %s -> %s",
                        self.id, self.conn_id, self.conn_variation_id, variation_id)
        try:
            with self.env.cr.savepoint():
                self.write({ 'conn_variation_id': variation_id, 'meli_id_variation': variation_id })
        except Exception as e:
            return { "error": "No se pudo re-vincular %s binding %s a la variacion %s: %s" % (
                self.conn_id, self.id, variation_id, str(e).split("\n")[0] ) }
        return None

    def product_post_stock( self, context=None, meli=None, optimize=False ):
        """26.87 (H2) — despachador por registro.

        El cuerpo historico era `for bindv in self: ... return ...`, con el
        `return` DENTRO del for: al pasarle un recordset de N bindings procesaba
        SOLO EL PRIMERO y devolvia, en silencio. Hoy los llamadores iteran de a
        uno, asi que el bug estaba latente — pero es una trampa: cualquier
        `bindings.product_post_stock()` publicaba una sola publicacion.

        Ahora se recorren todos y se devuelve el primer error encontrado (o {}).
        El comportamiento POR REGISTRO no cambia: el cuerpo esta intacto en
        _product_post_stock_one()."""
        result = {}
        for bindv in self:
            res = bindv._product_post_stock_one(context=context, meli=meli, optimize=optimize)
            if res and 'error' in res and 'error' not in result:
                result = res
        return result

    def _product_post_stock_one( self, context=None, meli=None, optimize=False ):
        #_logger.info("MercadoLibre Product product_post_stock: context: "+str(context)+" meli: "+str(meli)+" optimize:"+str(optimize))
        #_logger.info("ml.product > product_post_stock: self: "+str(self))
        for bindv in self:
            #_logger.info("ml.product > product_post_stock: bindv "+str(bindv))
            bindv._meli_stock_status()
            account = bindv.connection_account
            config = account and account.configuration
            product = bindv.product_id
            product_template = bindv.product_tmpl_id or (product and product.product_tmpl_id)
            meli_id = bindv.conn_id
            meli_id_variation = bindv.conn_variation_id
            bindT = bindv.binding_product_tmpl_id

            if (config and config.mercadolibre_stock_sku_mapping):

                sku = product.default_code
                
                stock_rules = config.mercadolibre_stock_sku_mapping.filtered(
                    lambda r: r.type == 'stock' and bool(r.sku and r.sku.strip())
                )
                #_logger.info("Check stock rules: "+str(stock_rules and stock_rules[0] and stock_rules[0].name))
                if (stock_rules and stock_rules[0] and stock_rules[0].name.startswith("Filtro")):
                    #_logger.info("check rule! check SKU")
                    founded = False

                    for sr in stock_rules:
                        #check all rules if type filter... check sku in that
                        if (sku == sr.sku):
                            founded = True
                            #_logger.info("check rule! FOUNDED SKU: "+str(sku))

                    if not founded:
                        res = { "error": "product blocked" }
                        bindv.stock_error = str(res)
                        bindv.stock_update = ml_datetime( str( datetime.now() ) )
                        bindv._meli_stock_status(notify=True)
                        bindT.stock_update = bindv.stock_update
                        bindT.stock_error = bindv.stock_error
                        #_logger.error(bindv.stock_error)
                        return res

            if bindT.meli_update_stock_blocked or product.meli_update_stock_blocked or product_template.meli_update_stock_blocked:
                res = { "error": "product blocked"}
                bindv.stock_error = str(res)
                bindv.stock_update = ml_datetime( str( datetime.now() ) )
                bindv._meli_stock_status(notify=True)
                bindT.stock_update = bindv.stock_update
                bindT.stock_error = bindv.stock_error
                #_logger.error(bindv.stock_error)
                return res


            if not product or not product_template or not product.active or not product_template.active:
                # Publicación vinculada a producto archivado (o faltante).
                # Estrategia: intentar REVINCULAR a un producto activo con el
                # mismo SKU antes de pausar. Si no hay reemplazo claro, pausar
                # la publicación en ML y skip del stock push.
                rebound = False
                if bindT:
                    try:
                        rebound = self.env['product.template']._meli_try_rebind_binding_by_sku(bindT)
                    except Exception as e:
                        _logger.warning(
                            "bindv > product_post_stock > rebind by SKU falló para bindT id=%s: %s",
                            bindT.id, e,
                        )

                if rebound:
                    # Refrescar referencias tras el rebind y caer al flujo normal
                    product = bindv.product_id
                    product_template = bindv.product_tmpl_id or (product and product.product_tmpl_id)
                    _logger.info(
                        "bindv > product_post_stock > revinculado a producto activo '%s' (bindT id=%s)",
                        product and product.name, bindT.id,
                    )

                if not product or not product_template or not product.active or not product_template.active:
                    # No hay reemplazo útil → pausar publicación y skip
                    try:
                        if bindT and not bindT.meli_update_stock_blocked:
                            _logger.info(
                                "bindv > product_post_stock > producto archivado sin reemplazo → pausando binding id=%s conn_id=%s",
                                bindT.id, bindT.conn_id,
                            )
                            bindT.product_meli_block()
                            bindT.product_meli_status_pause()
                    except Exception as e:
                        _logger.warning(
                            "bindv > product_post_stock > fallo pausando publicación de producto archivado (bindT id=%s): %s",
                            getattr(bindT, 'id', None), e,
                        )

                    res = { "error": "product archived"}
                    bindv.stock_error = str(res)
                    bindv.stock_update = ml_datetime( str( datetime.now() ) )
                    bindv._meli_stock_status(notify=True)
                    bindT.stock_update = bindv.stock_update
                    bindT.stock_error = bindv.stock_error
                    return res

            # 26.101 (un cliente): la instancia recibida puede ser de OTRA
            # cuenta — el asistente masivo de variantes resolvia una sola y la
            # empujaba a todos los bindings. Si no es de esta cuenta se descarta
            # y se resuelve la propia; si lo es, se reusa (no se pierde el ahorro).
            if account:
                meli = account._meli_instance_or_mine( meli )
            elif not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            # Timing debug flag - set to True to see detailed timing per operation
            _timing_debug = account and account.meli_cron_log_chatter

            try:
                #_logger.info("mercadolibre.product product_post_stock bindv:"+str(bindv)+" meli_id:"+str(meli_id)+" meli_id_variation:"+str(meli_id_variation))
                res = {}

                # TIMING: fetch_meli_product (HTTP GET /items/{id})
                _t0 = datetime.now()
                item_json = account and meli_id and meli and account.fetch_meli_product( meli_id=meli_id, meli=meli )
                _t1 = datetime.now()
                _dt_fetch = (_t1 - _t0).total_seconds()

                # Check for 403/404 errors at fetch level - mark item and skip processing
                if item_json:
                    fetch_status = item_json.get('status')
                    fetch_error = str(item_json.get('error', '')).lower()

                    # Convert status to int for comparison (ML may return as string or int)
                    fetch_status_code = None
                    if isinstance(fetch_status, int):
                        fetch_status_code = fetch_status
                    elif isinstance(fetch_status, str) and fetch_status.isdigit():
                        fetch_status_code = int(fetch_status)

                    # 403 Forbidden - mark as revision_forbidden and skip
                    # This happens when trying to access an item that belongs to a different seller
                    if fetch_status_code == 403 or fetch_error == 'forbidden':
                        # 26.101 (un cliente): el texto anterior era
                        # "Item belongs to different seller", y era FALSO: las 21
                        # publicaciones asi marcadas resultaron ser del propio
                        # vendedor (verificado contra la API de ML con su token).
                        # El 403 sale de PREGUNTAR con el token de otra cuenta.
                        # El cartel mandaba al cliente a revisar sus credenciales.
                        # OJO: el literal 'forbidden:403' es parte del contrato —
                        # lo buscan _meli_stock_status() y el reclasificador SQL
                        # (LIKE '%forbidden:403%'); no sacarlo del mensaje. Y no
                        # meter palabras que ese clasificador matchea por
                        # substring (closed / inactive / blocked / not_found /
                        # fulfillment / multiwarehouse / not_modifiable / Ok).
                        _logger.warning(
                            "fetch_meli_product forbidden:403 para %s consultado con la cuenta '%s' (seller_id %s) "
                            "- token de otra cuenta o permisos revocados - se marca revision_forbidden",
                            meli_id, account and account.name, account and account.seller_id)
                        bindv.sudo().write({
                            'meli_stock_status': 'revision_forbidden',
                            'stock_error': (
                                "forbidden:403 - ML denego el acceso a la publicacion " + str(meli_id) +
                                " al consultarla con la cuenta '" + str(account and account.name) +
                                "' (seller_id " + str(account and account.seller_id) + "). "
                                "Casi siempre significa que se pregunto con el token de OTRA cuenta, "
                                "no que la publicacion sea de otro vendedor. "
                                "Verificar a que cuenta de ML pertenece esta publicacion. "
                                "Respuesta de ML: " + str(item_json)
                            ),
                            'stock_update': ml_datetime(str(datetime.now()))
                        })
                        bindT.stock_update = bindv.stock_update
                        bindT.stock_error = bindv.stock_error
                        return {'error': 'forbidden', 'status': 403}

                    # 404 Not Found - mark as revision_not_found and skip
                    if fetch_status_code == 404 or fetch_error == 'not_found':
                        _logger.warning("fetch_meli_product 404 not found for %s - marking as revision_not_found", meli_id)
                        bindv.sudo().write({
                            'meli_last_status': 'not_found',
                            'meli_stock_status': 'revision_not_found',
                            'stock_error': str(item_json),
                            'stock_update': ml_datetime(str(datetime.now()))
                        })
                        bindT.stock_update = bindv.stock_update
                        bindT.stock_error = bindv.stock_error
                        return {'error': 'not_found', 'status': 404}

                # Update meli_last_status from fetched item (stored field for SQL queries)
                if item_json and 'status' in item_json:
                    ml_status = item_json['status']
                    if ml_status in ('active', 'paused', 'closed', 'under_review', 'inactive'):
                        if bindv.meli_last_status != ml_status:
                            bindv.sudo().write({'meli_last_status': ml_status})

                bindv.meli_user_product_id = bindv._fetch_meli_user_product_id( meli=meli, item_json=item_json )
                _t2 = datetime.now()
                _dt_user_product = (_t2 - _t1).total_seconds()

                #one variant bind from variant product
                bindv.meli_available_quantity = product._meli_available_quantity( meli_id=meli_id, meli=meli, config=config)
                bindv.stock = bindv.meli_available_quantity
                _t3 = datetime.now()
                _dt_avail_qty = (_t3 - _t2).total_seconds()

                # 26.371 (#caso-K21): KIT de ML (tag 'bundle', user-product con bundle.type=kit). Su stock lo
                # calcula ML con el de los componentes y rechaza cualquier PUT ("stock cannot be modified ...
                # kit user product"). No se intenta: se deja el motivo en el binding, sin error en el log.
                if isinstance(item_json, dict) and 'bundle' in (item_json.get('tags') or []):
                    res = {"error": "bundle", "message": "Kit de Mercado Libre: el stock lo calcula Mercado Libre con el de sus componentes; no se publica desde Odoo."}
                    bindv.stock_error = str(res)
                    bindv.stock_update = ml_datetime( str( datetime.now() ) )
                    bindT.stock_update = bindv.stock_update
                    bindT.stock_error = bindv.stock_error
                    return res

                #if bindv.meli_inventory_id and bindv.product_id and bindv.product_id.active:
                if bindv.product_id and bindv.product_id.active:
                    logistic_type = bindv.product_id._meli_update_logistic_type(meli_id=meli_id, meli=meli,config=config, rjson=item_json)
                    if logistic_type and logistic_type in ["fulfillment"]:
                        bindv.stock_update = ml_datetime( str( datetime.now() ) )
                        res = { "error": "fulfillment"}
                        bindv.stock_error = str(res)
                        bindv.stock_update = ml_datetime( str( datetime.now() ) )
                        bindv._meli_stock_status()
                        bindT.stock_update = bindv.stock_update
                        bindT.stock_error = bindv.stock_error
                        #_logger.info(bindv.stock_error)
                        rjson = account.fetch_meli_product(meli_id=meli_id,meli=meli)
                        if bindv.stock<=0:
                            stock_total = rjson and rjson["available_quantity"]
                            if stock_total and stock_total>0 and bindv.meli_status not in ['active']:
                                _logger.info("bindv > product_post_stock > fulfillment Activate!")
                                bindv.product_meli_status_active(meli=meli)

                        if rjson and "variations" in rjson and len(rjson["variations"]):
                            for var in rjson["variations"]:
                                for bv in bindT.variant_bindings:
                                    if bv.conn_variation_id == "id" in var and var["id"]:
                                        bv.stock = var["available_quantity"]
                                        bv.meli_available_quantity = var["available_quantity"]

                        if bindv.stock>0 and bindv.meli_status not in ['active']:
                            _logger.info("bindv > product_post_stock > fulfillment Activate!")
                            bindv.product_meli_status_active(meli=meli)
                        return res
                    
                if bindv.product_id and not bindv.product_id.active:
                    res = { "error": "product archived"}
                    bindv.stock_error = str(res)
                    bindv.stock_update = ml_datetime( str( datetime.now() ) )
                    bindv._meli_stock_status(notify=True)
                    bindT.stock_update = bindv.stock_update
                    bindT.stock_error = bindv.stock_error
                    #_logger.error(bindv.stock_error)
                    return res
                
                if not bindv.product_id:
                    res = { "error": "no product binded"}
                    bindv.stock_error = str(res)
                    bindv.stock_update = ml_datetime( str( datetime.now() ) )
                    bindv._meli_stock_status(notify=True)
                    bindT.stock_update = bindv.stock_update
                    bindT.stock_error = bindv.stock_error
                    _logger.error(bindv.stock_error)
                    return res

                post_stock = True
                is_pub_as_variant_ok = True
                if (optimize):
                    #avoid posting when pub_as_variant
                    is_pub_as_variant_ok = product_template.meli_pub_as_variant and product_template.meli_pub_principal_variant
                    is_pub_as_variant_ok = is_pub_as_variant_ok and (product_template.meli_pub_principal_variant.id==bindv.product_id.id)
                    post_stock = is_pub_as_variant_ok

                if (post_stock or is_pub_as_variant_ok):
                    #_logger.info("mercadolibre.product product_post_stock "+str(meli_id)+" product:" +str(product))
                    _t4 = datetime.now()
                    res = product.x_product_post_stock( context=context, meli=meli, config=config,
                                                        meli_id=meli_id, meli_id_variation=meli_id_variation,
                                                        target=bindv, item_json=item_json )
                    _t5 = datetime.now()
                    _dt_post_stock = (_t5 - _t4).total_seconds()

                    # Log timing breakdown with detailed POST internals (if debug enabled)
                    if _timing_debug:
                        _total = _dt_fetch + _dt_user_product + _dt_avail_qty + _dt_post_stock
                        _timing_summary = "fetch=%.2fs user_prod=%.2fs avail_qty=%.2fs post=%.2fs" % (
                            _dt_fetch, _dt_user_product, _dt_avail_qty, _dt_post_stock)

                        # Extract POST breakdown from result if available
                        _post_timing = res.get('_timing', {}) if res else {}
                        if _post_timing:
                            _post_parts = []
                            # Order of common timing keys for readability
                            _timing_keys = ['fetch_product', 'first_avail_qty', 'var_loop', 'var_loop_count',
                                           'var_get_headers', 'var_put_api', 'variant_bindings_loop',
                                           'variant_bindings_count', 'vb_min', 'vb_max', 'vb_avg',
                                           'get_variation_api', 'get_headers_stock',
                                           'put_stock_api', 'x_match_variation_id', 'second_avail_qty',
                                           'get_headers_stock_alt', 'put_stock_api_alt']
                            for k in _timing_keys:
                                if k in _post_timing:
                                    v = _post_timing[k]
                                    if isinstance(v, float):
                                        _post_parts.append("%s=%.2fs" % (k, v))
                                    else:
                                        _post_parts.append("%s=%s" % (k, v))
                            if _post_parts:
                                _timing_summary += " | POST_DETAIL[%s]" % " ".join(_post_parts)

                        _logger.info("TIMING %s: %s | total=%.2fs", bindv.sku, _timing_summary, _total)

                #_logger.info("product_post_stock res:"+str(res))
                if res and 'error' in res:
                    #if 'fulfillment' in str(res):
                    #    bindv.meli_inventory_id = "fetch"
                    bindv.stock_error = str(res)
                    bindv.stock_update = ml_datetime( str( datetime.now() ) )

                    # Set appropriate status based on error type to exclude from future CRON runs
                    if res.get('not_found') or res.get('status') == 404:
                        bindv.sudo().write({
                            'meli_last_status': 'not_found',
                            'meli_stock_status': 'revision_not_found'
                        })
                    elif res.get('status') == 403 or res.get('error') == 'forbidden':
                        bindv.sudo().write({'meli_stock_status': 'revision_forbidden'})
                    elif res.get('under_review'):
                        bindv.sudo().write({'meli_stock_status': 'revision_under_review'})
                    elif res.get('closed'):
                        bindv.sudo().write({'meli_stock_status': 'revision_not_modifiable'})
                    elif res.get('not_applied'):
                        # 26.87 (F7): ML respondio 200 pero no aplico la cantidad.
                        bindv.sudo().write({'meli_stock_status': 'revision_not_applied'})
                    elif res.get('not_modifiable'):
                        bindv.sudo().write({'meli_stock_status': 'revision_not_modifiable'})
                    elif 'seller_sku' in str(res).lower() or 'different seller_sku' in str(res).lower():
                        bindv.sudo().write({'meli_stock_status': 'revision_sku_mismatch'})
                    else:
                        bindv._meli_stock_status(notify=True)

                    bindT.stock_update = bindv.stock_update
                    bindT.stock_error = bindv.stock_error
                    return res
                
                #bindv.meli_inventory_id = None
                #more than one
                bindv.stock_error = "Ok"
                if res and 'warning' in res:
                    bindv.stock_error+=" con aviso: "+str(res["warning"])
                bindv.stock_update = ml_datetime( str( datetime.now() ) )
                bindv._meli_stock_status()
                bindT.stock_update = bindv.stock_update
                bindT.stock_error = bindv.stock_error

                #TODO
                stock = 0
                stock_error = ""
                for bindvariant in bindT.variant_bindings:
                    stock+= (bindvariant.stock or bindvariant.meli_available_quantity)
                    stock_error+= str(bindvariant.stock_error)
                    
                bindT.stock = stock

            except Exception as e:
                #_logger.info("mercadolibre.product product_post_stock > exception error")
                #_logger.info(e, exc_info=True)
                bindv.stock_error = str(e)
                bindv.stock_update = ml_datetime( str( datetime.now() ) )
                bindv._meli_stock_status(notify=True)

                bindT.stock_update = bindv.stock_update
                bindT.stock_error = bindv.stock_error
                pass;

            return {}

    def product_post_price( self, context=None, meli=None ):
        """26.87 (H2) — despachador por registro (mismo caso que product_post_stock:
        el `return` estaba dentro del for y procesaba solo el primer binding)."""
        result = {}
        for bindv in self:
            res = bindv._product_post_price_one(context=context, meli=meli)
            if res and 'error' in res and 'error' not in result:
                result = res
        return result

    def _product_post_price_one( self, context=None, meli=None ):
        #_logger.info("MercadoLibre Product product_post_price: context: "+str(context)+" self:"+str(self))
        for bindv in self:

            account = bindv.connection_account
            config = account and account.configuration
            product = bindv.product_id
            product_template = bindv.product_tmpl_id or (product and product.product_tmpl_id)
            meli_id = bindv.conn_id
            meli_id_variation = bindv.conn_variation_id
            bindT = bindv.binding_product_tmpl_id

            if not product or not product_template:
                _logger.error("product_template:"+str(product_template)+" product:"+str(product))
                # 26.251 (#caso-K29): antes `continue` => devolvia None y, con el contador
                # corregido ({} = exito), un binding sin producto contaba como publicado.
                return { 'error': 'sin_producto', 'meli_id': str(meli_id) }

            # 26.101 (un cliente): la instancia recibida puede ser de OTRA
            # cuenta — el asistente masivo de variantes resolvia una sola y la
            # empujaba a todos los bindings. Si no es de esta cuenta se descarta
            # y se resuelve la propia; si lo es, se reusa (no se pierde el ahorro).
            if account:
                meli = account._meli_instance_or_mine( meli )
            elif not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            #
            try:
                #_logger.info("mercadolibre.product product_post_price: price:"+str(bindv.price)+" meli_price: "+str(bindv.meli_price))
                #one variant bind from variant product

                #if not bindv.meli_price:
                #    bindv.meli_price = base_meli_price
                #else:
                #    bindv.meli_price = (not bindv.meli_price_fixed and base_meli_price) or bindv.meli_price
                #bindv.price = bindv.meli_price

                bindv.update_price()
                meli_currency = bindv.meli_currency or bindT.meli_currency

                #_logger.info("mercadolibre.product product_post_price: bindv.price:"+str(bindv.price)+" meli_price: "+str(bindv.meli_price))
                res = product.x_product_post_price( context=context, meli_price=bindv.meli_price, meli_currency=meli_currency, meli=meli, config=config, meli_id=meli_id, meli_id_variation=meli_id_variation )
                if res and 'error' in res:
                    bindv.price_update = ml_datetime( str( datetime.now() ) )
                    return res
                bindv.price_update = ml_datetime( str( datetime.now() ) )
                #more than one

            except Exception as e:
                # 26.251 (#caso-K29): era un `pass` mudo que devolvia {} = "publicado". Con el
                # contador corregido eso contaria una excepcion como exito.
                _logger.error("product_post_price: excepcion publicando el precio de %s (%s): %s",
                              str(meli_id), str(bindv.sku or '-'), e, exc_info=True)
                return { 'error': 'excepcion', 'meli_id': str(meli_id), 'detalle': str(e) }

            return {}

    def _meli_manufacturing_time_value( self ):
        """Plazo a publicar: el del binding, el del binding de la plantilla o el del producto."""
        self.ensure_one()
        bindT = self.binding_product_tmpl_id
        product = self.product_id
        value = self.meli_manufacturing_time or (bindT and bindT.meli_manufacturing_time) or (
            product and "meli_manufacturing_time" in product._fields and product.meli_manufacturing_time) or ""
        return str(value).strip()

    def product_post_manufacturing_time( self, context=None, meli=None ):
        """26.278 (#caso-K31): publica SOLO el plazo de entrega (MANUFACTURING_TIME) contra el item
        padre, sin reenviar la ficha. {} en OK, dict con 'error' si ML lo rechaza."""
        seen = set()
        for bindv in self:
            meli_id = bindv.conn_id
            if not meli_id or meli_id in seen:
                continue
            seen.add(meli_id)
            value = bindv._meli_manufacturing_time_value()
            if not value:
                return {"error": "sin_plazo", "message": _("la publicación %s no tiene cargado el plazo "
                                                           "de entrega (Manufacturing time)") % meli_id}
            account = bindv.connection_account
            if account:
                meli = account._meli_instance_or_mine( meli )
            if not meli:
                return {"error": "sin_conexion", "message": _("sin conexión a MercadoLibre")}
            if meli.need_login():
                return meli.redirect_login()
            res = _meli_post_manufacturing_time(meli, meli_id, value)
            if res:
                return res
        return {}

    def action_meli_post_manufacturing_time( self ):
        return _meli_manufacturing_time_action_result(
            self.product_post_manufacturing_time(), len(set(self.mapped("conn_id")) - {False}))

    def product_post_title( self, context=None, meli=None ):
        # Empuja SOLO el título de la publicación a ML (no el producto completo).
        # Espejo de product_post_price: PUT /items/{meli_id} { 'title': <titulo> }.
        # El título es un campo a nivel item, no por variación, asi que el body es
        # siempre { 'title': title } contra el item padre (conn_id), aun con variaciones.
        # Devuelve {} en OK o el rjson con 'error' en falla (para que el wizard lo muestre).
        for bindv in self:

            account = bindv.connection_account
            product = bindv.product_id
            product_template = bindv.product_tmpl_id or (product and product.product_tmpl_id)
            meli_id = bindv.conn_id
            bindT = bindv.binding_product_tmpl_id

            if not product or not product_template:
                _logger.error("product_post_title product_template:"+str(product_template)+" product:"+str(product))
                continue;

            if not meli_id:
                continue;

            # 26.101 (un cliente): ver _meli_instance_or_mine — un token ajeno
            # al binding hace que ML rechace el PUT del titulo con 403.
            if account:
                meli = account._meli_instance_or_mine( meli )
            elif not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )
            if meli and meli.need_login():
                return meli.redirect_login()

            # Fuente del título: meli_title del binding -> del producto -> nombre -> del binding de plantilla
            title = bindv.meli_title or (product and (product.meli_title or product.name)) or (bindT and bindT.meli_title)
            if not title:
                _logger.error("product_post_title: título vacío para meli_id:"+str(meli_id))
                continue;

            try:
                response = meli.put_mini("/items/"+str(meli_id), { 'title': title }, {'access_token':meli.access_token})
                if response:
                    rjson = response.json()
                    if rjson and "error" in rjson:
                        _logger.error("product_post_title not updated: /items/"+str(meli_id)+" "+str(rjson))
                        return rjson
                    _logger.info("Posted title ok /items/"+str(meli_id)+": "+str(title))
            except Exception as e:
                _logger.error("product_post_title exception /items/"+str(meli_id)+": "+str(e))
                return { 'error': str(e) }

        return {}

    def product_meli_status_put( self, context=None, status=None, meli=False):

        company = self.env.user.company_id
        account = self.connection_account
        config = (account and account.configuration) or company
        company = ("company_id" in config._fields and config.company_id) or company

        meli_id = self.conn_id
        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

            if meli.need_login():
                return meli.redirect_login()

        if meli_id and status and (status in ['paused','closed','active']):
            response = meli.put_mini("/items/"+str(meli_id), { 'status': status }, {'access_token':meli.access_token})
            if response:
                _logger.info("put status (variant): /items/"+str(meli_id)+" status:"+str(status)+" response: "+str(response.json()))
                pass;
        else:
            _logger.error("Undefined status set, meli_id: "+str(meli_id)+" status: "+str(status))
        return {}

    def product_meli_status_close( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product product_meli_status_close")
        return self.product_meli_status_put(context=context,status='closed',meli=meli)

    def product_meli_status_pause( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product product_meli_status_pause")
        for bindv in self:
            bindT = bindv.binding_product_tmpl_id
            bindT.product_meli_block()

        return self.product_meli_status_put(context=context,status='paused',meli=meli)

    def product_meli_status_active( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product product_meli_status_active")
        for bindv in self:
            bindT = bindv.binding_product_tmpl_id
            bindT.product_meli_unblock()
        return self.product_meli_status_put(context=context,status='active',meli=meli)

    def product_meli_delete( self, context=None, meli=False ):
        #_logger.info("MercadoLibre Product product_meli_delete")
        company = self.env.user.company_id
        account = self.connection_account
        config = (account and account.configuration) or company
        company = ("company_id" in config._fields and config.company_id) or company

        meli_id = self.conn_id

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            return meli.redirect_login()

        if meli_id:
            response = meli.put_mini("/items/"+str(meli_id), { 'deleted': 'true' }, {'access_token':meli.access_token})

            rjson = response.json()
            #_logger.info( rjson )
            ML_status = rjson["status"]
            if "error" in rjson:
                ML_status = rjson["error"]
            if "sub_status" in rjson:
                if len(rjson["sub_status"]) and rjson["sub_status"][0]=='deleted':
                    #product.write({ 'meli_id': '','meli_id_variation': '' })
                    _logger.info("Deleted ok: TODO: Delete variant binding, and meli_id on base product...")
                    pass;

        return {}

    def process_item_notification(self, item_json=None, meli=None):
        """
        Process item notification to update status efficiently.
        Called from notification.py when item notification is received.

        :param item_json: JSON data from MercadoLibre API (already fetched)
        :param meli: meli instance (optional, will be created if needed)
        :return: dict with result
        """
        for bindv in self:
            try:
                account = bindv.connection_account
                company = (account and account.company_id) or self.env.user.company_id

                # If no item_json provided, fetch from API
                if not item_json:
                    if not meli:
                        meli = self.env['meli.util'].get_new_instance(company, account)
                    if meli.need_login():
                        return {'error': 'Login required'}

                    response = meli.get("/items/" + str(bindv.meli_id), {'access_token': meli.access_token})
                    item_json = response.json()

                if not item_json or 'error' in item_json:
                    error_msg = item_json.get('message', item_json.get('error', 'Unknown error')) if item_json else 'No data'
                    return {'error': error_msg}

                # Extract status info
                new_status = item_json.get('status', '')
                new_sub_status = ''
                if 'sub_status' in item_json and item_json['sub_status']:
                    new_sub_status = item_json['sub_status'][0] if len(item_json['sub_status']) else ''

                # Update stored status if valid and changed
                if new_status in ('active', 'paused', 'closed', 'under_review', 'inactive'):
                    if bindv.meli_last_status != new_status:
                        _logger.info(f"Item notification: {bindv.meli_id} status changed {bindv.meli_last_status} -> {new_status}")

                        # Map ML status to meli_stock_status
                        stock_status_map = {
                            'closed': 'revision_closed',
                            'inactive': 'revision_inactive',
                            'under_review': 'revision_under_review',
                        }

                        write_vals = {'meli_last_status': new_status}

                        # Set stock status for non-active publications
                        if new_status in stock_status_map:
                            write_vals['meli_stock_status'] = stock_status_map[new_status]

                        bindv.sudo().write(write_vals)

                        # Handle closed items - block stock updates
                        if new_status == 'closed':
                            bindT = bindv.binding_product_tmpl_id
                            if bindT:
                                bindT.product_meli_block()
                        elif new_status == 'active':
                            bindT = bindv.binding_product_tmpl_id
                            if bindT:
                                bindT.product_meli_unblock()

                # Handle deleted items
                if new_sub_status == 'deleted':
                    _logger.info(f"Item notification: {bindv.meli_id} marked as deleted")
                    bindv.write({'meli_id': '', 'meli_id_variation': ''})

                return {'success': True, 'status': new_status, 'sub_status': new_sub_status}

            except Exception as e:
                _logger.error(f"Error processing item notification: {e}")
                return {'error': str(e)}

        return {'error': 'No bindings to process'}

    def product_meli_upload_image( self ):
        _logger.info("MercadoLibre Product product_meli_upload_image")
        pass;

    def product_meli_login( self ):
        _logger.info("MercadoLibre Product product_meli_login")
        pass;

    def _update_sale_terms( self, meli, productjson=None, config=None ):
        # [caso de un cliente] La firma tiene que ser la MISMA que la del metodo base
        # (meli_oerp/models/product.py: _update_sale_terms(self, meli, productjson=None, config=None)).
        # Este override la declaraba sin `config` mientras product.py lo llama con config=config, asi
        # que TODA publicacion que pasa por el binding (el camino multi-cuenta, o sea el del wizard)
        # moria con:
        #   TypeError: _update_sale_terms() got an unexpected keyword argument 'config'
        # `config` ademas se PROPAGA: es la configuracion por cuenta, que es justo lo que distingue
        # al multi-cuenta; tragarsela aca daria terminos de venta de la cuenta equivocada.
        bind = self

        product = bind.product_id

        terms = []

        if product:
            terms = product._update_sale_terms( meli=meli, productjson=productjson, config=config )

        return terms

    def product_meli_unblock( self ):
        bindv = self
        bindT = bindv and bindv.binding_product_tmpl_id
        if bindT:
            bindT.product_meli_unblock()

    def product_meli_block( self ):
        bindv = self
        bindT = bindv and bindv.binding_product_tmpl_id
        if bindT:
            bindT.product_meli_block()

    #binding product variant
    def search_all( self, connection_account=False, conn_id=False, conn_variation_id=False, product_id=False ):
        # get all actives and not
        connection_account = connection_account or self.connection_account
        connection_account_id =  connection_account and connection_account.id

        product_id = product_id or self.product_id
        product_id_id = product_id and product_id.id
        product_id_str = (product_id_id and str(product_id_id)) or str("NULL")

        conn_id = conn_id or self.conn_id
        conn_id_str = str(conn_id and ("'" + str(conn_id) + "'" ))
        conn_id_str = (conn_id and conn_id_str) or str("NULL")

        conn_variation_id = conn_variation_id or self.conn_variation_id
        conn_variation_id_str = str(conn_variation_id and ("'" + str(conn_variation_id) + "'" ))
        conn_variation_id_str = (conn_variation_id and conn_variation_id_str) or str("NULL")

        bindv_query_select_res = []

        # conn_id / conn_variation_id vienen de la API de ML: van como parametro (F8b 20.0). Mismo SQL:
        # None => NULL (igual que el "NULL" literal de antes) e int() replica el %i (False => 0).
        bindv_query_select = """select id, name, conn_id
            from mercadolibre_product
            where connection_account=%s
            and conn_id = %s
            and (conn_variation_id = %s OR conn_variation_id = '')
            and product_id = %s
        """
        bindv_query_params = ( int(connection_account_id), (str(conn_id) if conn_id else None),
                               (str(conn_variation_id) if conn_variation_id else None), (product_id_id or None) )
        _logger.info("bindV > search_all bindv_query_select:"+str(bindv_query_select)+" params:"+str(bindv_query_params))
        cr = MeliCr( self )
        resquery = cr.execute(bindv_query_select, bindv_query_params)
        bindv_query_select_res = cr.fetchall()
        _logger.info("bindV > search_all:"+str(bindv_query_select_res))
        return bindv_query_select_res

    #product variant
    def unlink_all( self, connection_account=False, conn_id=False, conn_variation_id=False, product_id=False ):
        resquery = []
        bindv_all = self.search_all(connection_account=connection_account, conn_id=conn_id, conn_variation_id=conn_variation_id, product_id=product_id )

        bindv_all_ids = []

        all_ids_str = None
        if bindv_all:
            all_ids_str = ','.join([str(bnd[0]) for bnd in bindv_all])

        if all_ids_str:
            bindv_query_delete = """delete
                from mercadolibre_product
                where id in %s
            """
            _logger.info("bindV > unlink_all:"+str(bindv_query_delete)+" ids:"+str(all_ids_str))
            cr = MeliCr( self )
            resquery = cr.execute( bindv_query_delete, (tuple(bnd[0] for bnd in bindv_all),) )
            _logger.info("bindV > unlink_all resquery:"+str(resquery))
        MeliCommit( self )
        return resquery

    @api.onchange('name')
    def _change_meli_title(self):
        for b in self:
            b.meli_title = b.name
            #change all
            bt = b.binding_product_tmpl_id
            if bt:
                bt.name = b.name
                bt.meli_title = bt.name
                for bb in bt.variant_bindings:
                    bb.name = bt.name
                    bb.meli_title = bt.meli_title

    @api.depends('name')
    def change_meli_title(self):
        for b in self:
            b.meli_title = b.name
            #change all
            bt = b.binding_product_tmpl_id
            if bt:
                bt.name = b.name
                bt.meli_title = bt.name
                for bb in bt.variant_bindings:
                    bb.name = bt.name
                    bb.meli_title = bt.meli_title

class MercadoLibreConnectionBindingSaleOrderPayment(models.Model):

    _name = "mercadolibre.payment"
    _description = "MercadoLibre Sale Order Payment Binding"
    _inherit = ["ocapi.binding.payment","mercadolibre.payments"]

    order_id = fields.Many2one("mercadolibre.sale_order",string="Order")
    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )
    name = fields.Char(string="Payment Name")

    meli_oerp_payment = fields.Many2one( "mercadolibre.payments",string="Payment from meli_oerp")

    def _get_ml_journal(self):
        journal_id = None
        #journal_id = self.env.user.company_id.mercadolibre_process_payments_journal
        #if not journal_id:
        #    journal_id = self.env['account.journal'].search([('code','=','ML')])
        #if not journal_id:
        #    journal_id = self.env['account.journal'].search([('code','=','MP')])
        return journal_id

    def _get_ml_partner(self):
        partner_id = None
        #partner_id = self.env.user.company_id.mercadolibre_process_payments_res_partner
        #if not partner_id:
        #    partner_id = self.env['res.partner'].search([('ref','=','MELI')])
        #if not partner_id:
        #    partner_id = self.env['res.partner'].search([('name','=','MercadoLibre')])
        return partner_id

    def _get_ml_customer_partner(self):
        # Usar partner_invoice_id (entidad fiscal) para que el pago concilie
        # con la factura. Fallback al buyer (partner_id) si no hay entidad fiscal.
        sale_order = self._get_ml_customer_order()
        return (sale_order and (sale_order.partner_invoice_id or sale_order.partner_id))

    def _get_ml_customer_order(self):
        mlorder = self.order_id
        mlshipment = mlorder.shipment
        return (mlorder and mlorder.sale_order) or (mlshipment and mlshipment.sale_order)

    def create_payment(self):
        self.ensure_one()
        if self.account_payment_id:
            raise ValidationError(_('Ya esta creado el pago'))
        if self.status != 'approved':
            return None
        journal_id = self._get_ml_journal()
        payment_method_id = self.env['account.payment.method'].search([('code','=','electronic'),('payment_type','=','inbound')])
        # [26.270] el metodo lo define la linea elegida (meli_payment_method_line_for): basta el diario.
        if not journal_id:
            raise ValidationError(_('Debe configurar el diario/metodo de pago'))
        partner_id = self._get_ml_customer_partner()
        currency_id = self.env['res.currency'].search([('name','=',self.currency_id)])
        if not currency_id:
            raise ValidationError(_('No se puede encontrar la moneda del pago'))

        communication = self.payment_id
        if self._get_ml_customer_order():
            communication = ""+str(self._get_ml_customer_order().name)+" OP "+str(self.payment_id)+str(" TOT")

        # Multi-empresa: fijar company_id explicito (el cron corre con su=True sin compania
        # en contexto -> NOT NULL violation). Debe coincidir con la del diario.
        payment_company = (journal_id and journal_id.company_id) \
                          or (self._get_ml_customer_order() and self._get_ml_customer_order().company_id) \
                          or self.env.company
        # [26.269] Linea de metodo EXPLICITA con cuenta de pagos pendientes (sin ella el
        # cobro queda sin asiento en 18/19). Si ninguna sirve: no se crea, aviso en la venta.
        payment_method_line, pml_reason = meli_payment_method_line_for(journal_id, 'inbound', partner=partner_id)
        if not payment_method_line:
            msg = "No se registro el cobro de MercadoLibre %s: %s" % (self.payment_id, pml_reason)
            _logger.warning('create_payment: %s', msg)
            so_noline = self._get_ml_customer_order()
            if so_noline:
                meli_money_block_post(so_noline, msg, once_key="meli-pay-noline-%s" % self.payment_id)
            return None
        vals_payment = {
                'company_id': payment_company.id,
                'partner_id': partner_id.id,
                'payment_type': 'inbound',
                'payment_method_id': payment_method_line.payment_method_id.id,
                'payment_method_line_id': payment_method_line.id,
                'journal_id': journal_id.id,
                # [26.270] meli_payment_id apunta a mercadolibre.payments (meli_oerp), no a este binding
                'meli_payment_id': (self.meli_oerp_payment and self.meli_oerp_payment.id) or False,
                'currency_id': currency_id.id,
                'partner_type': 'customer',
                'amount': self.total_paid_amount,
                }
        # [26.270] 'communication' no existe en account.payment desde Odoo 14: la referencia va al
        # campo que exista (memo 18+, ref 16/17). Antes el alta tiraba "Invalid field".
        _ref_f = next((f for f in ('memo', 'ref') if f in self.env['account.payment']._fields), False)
        if _ref_f:
            vals_payment[_ref_f] = communication
        acct_payment_id = self.env['account.payment'].with_company(payment_company).create(vals_payment)
        # [un caso, 26.217] account.payment no tiene post() desde Odoo 14 (action_post);
        # misma resolucion que payment_group_post de meli_oerp_accounting.
        _meli_payment_post(acct_payment_id)
        self.account_payment_id = acct_payment_id.id

    def create_supplier_payment(self):
        self.ensure_one()
        if self.status != 'approved':
            return None
        if self.account_supplier_payment_id:
            raise ValidationError(_('Ya esta creado el pago'))
        journal_id = self._get_ml_journal()
        payment_method_id = self.env['account.payment.method'].search([('code','=','outbound_online'),('payment_type','=','outbound')])
        # [26.270] el metodo lo define la linea elegida (meli_payment_method_line_for): basta el diario.
        if not journal_id:
            raise ValidationError(_('Debe configurar el diario/metodo de pago'))
        partner_id = self._get_ml_partner()
        if not partner_id:
            raise ValidationError(_('No esta dado de alta el proveedor MercadoLibre'))
        currency_id = self.env['res.currency'].search([('name','=',self.currency_id)])
        if not currency_id:
            raise ValidationError(_('No se puede encontrar la moneda del pago'))

        communication = self.payment_id
        if self._get_ml_customer_order():
            communication = ""+str(self._get_ml_customer_order().name)+" OP "+str(self.payment_id)+str(" FEE")

        # Multi-empresa: fijar company_id explicito (ver create_payment).
        payment_company = (journal_id and journal_id.company_id) \
                          or (self._get_ml_customer_order() and self._get_ml_customer_order().company_id) \
                          or self.env.company
        vals_payment = {
                'company_id': payment_company.id,
                'partner_id': partner_id.id,
                'payment_type': 'outbound',
                'payment_method_id': payment_method_id.id,
                'journal_id': journal_id.id,
                # [26.270] meli_payment_id apunta a mercadolibre.payments (meli_oerp), no a este binding
                'meli_payment_id': (self.meli_oerp_payment and self.meli_oerp_payment.id) or False,
                'currency_id': currency_id.id,
                'partner_type': 'supplier',
                'amount': self.fee_amount,
                }
        # [26.270] 'communication' no existe en account.payment desde Odoo 14: la referencia va al
        # campo que exista (memo 18+, ref 16/17). Antes el alta tiraba "Invalid field".
        _ref_f = next((f for f in ('memo', 'ref') if f in self.env['account.payment']._fields), False)
        if _ref_f:
            vals_payment[_ref_f] = communication
        # [26.270] Linea de metodo SALIENTE explicita con cuenta de pagos pendientes (criterio 26.269).
        payment_method_line, pml_reason = meli_payment_method_line_for(journal_id, 'outbound', partner=partner_id)
        if not payment_method_line:
            msg = "No se registro el pago de comision a %s de MercadoLibre %s: %s" % (
                partner_id.display_name, self.payment_id, pml_reason)
            meli_money_block_post(self._get_ml_customer_order() or self.order_id, msg,
                                  once_key="meli-pay-noline-fee-%s" % self.payment_id)
            return None
        vals_payment['payment_method_id'] = payment_method_line.payment_method_id.id
        vals_payment['payment_method_line_id'] = payment_method_line.id
        acct_payment_id = self.env['account.payment'].with_company(payment_company).create(vals_payment)
        # [un caso, 26.217] account.payment no tiene post() desde Odoo 14 (action_post);
        # misma resolucion que payment_group_post de meli_oerp_accounting.
        _meli_payment_post(acct_payment_id)
        self.account_supplier_payment_id = acct_payment_id.id

    def create_supplier_payment_shipment(self):
        self.ensure_one()
        if self.status != 'approved':
            return None
        if self.account_supplier_payment_shipment_id:
            raise ValidationError(_('Ya esta creado el pago'))
        journal_id = self._get_ml_journal()
        payment_method_id = self.env['account.payment.method'].search([('code','=','outbound_online'),('payment_type','=','outbound')])
        # [26.270] el metodo lo define la linea elegida (meli_payment_method_line_for): basta el diario.
        if not journal_id:
            raise ValidationError(_('Debe configurar el diario/metodo de pago'))
        partner_id = self._get_ml_partner()
        if not partner_id:
            raise ValidationError(_('No esta dado de alta el proveedor MercadoLibre'))
        currency_id = self.env['res.currency'].search([('name','=',self.currency_id)])
        if not currency_id:
            raise ValidationError(_('No se puede encontrar la moneda del pago'))
        if (not self.order_id or (not self.order_id.shipping_seller_cost>0.0 and not self.order_id.payments_shipment_amount>0.0)):
            raise ValidationError(_('No hay datos de costo de envio'))

        communication = self.payment_id
        if self._get_ml_customer_order():
            communication = ""+str(self._get_ml_customer_order().name)+" OP "+str(self.payment_id)+str(" SHP")

        # Multi-empresa: fijar company_id explicito (ver create_payment).
        payment_company = (journal_id and journal_id.company_id) \
                          or (self._get_ml_customer_order() and self._get_ml_customer_order().company_id) \
                          or (self.order_id and self.order_id.company_id) \
                          or self.env.company
        vals_payment = {
                'company_id': payment_company.id,
                'partner_id': partner_id.id,
                'payment_type': 'outbound',
                'payment_method_id': payment_method_id.id,
                'journal_id': journal_id.id,
                # [26.270] meli_payment_id apunta a mercadolibre.payments (meli_oerp), no a este binding
                'meli_payment_id': (self.meli_oerp_payment and self.meli_oerp_payment.id) or False,
                'currency_id': currency_id.id,
                'partner_type': 'supplier',
                'amount': (self.order_id.payments_shipment_amount or self.order_id.shipping_seller_cost),
                }
        # [26.270] 'communication' no existe en account.payment desde Odoo 14: la referencia va al
        # campo que exista (memo 18+, ref 16/17). Antes el alta tiraba "Invalid field".
        _ref_f = next((f for f in ('memo', 'ref') if f in self.env['account.payment']._fields), False)
        if _ref_f:
            vals_payment[_ref_f] = communication
        # [26.270] Linea de metodo SALIENTE explicita con cuenta de pagos pendientes (criterio 26.269).
        payment_method_line, pml_reason = meli_payment_method_line_for(journal_id, 'outbound', partner=partner_id)
        if not payment_method_line:
            msg = "No se registro el pago de envio a %s de MercadoLibre %s: %s" % (
                partner_id.display_name, self.payment_id, pml_reason)
            meli_money_block_post(self._get_ml_customer_order() or self.order_id, msg,
                                  once_key="meli-pay-noline-shp-%s" % self.payment_id)
            return None
        vals_payment['payment_method_id'] = payment_method_line.payment_method_id.id
        vals_payment['payment_method_line_id'] = payment_method_line.id
        acct_payment_id = self.env['account.payment'].with_company(payment_company).create(vals_payment)
        # [un caso, 26.217] account.payment no tiene post() desde Odoo 14 (action_post);
        # misma resolucion que payment_group_post de meli_oerp_accounting.
        _meli_payment_post(acct_payment_id)
        self.account_supplier_payment_shipment_id = acct_payment_id.id

class MercadoLibreConnectionBindingSaleOrderShipmentItem(models.Model):

    _name = "mercadolibre.bind_shipment.item"
    _description = "Ocapi Sale Order Shipment Item"
    _inherit = ["ocapi.binding.shipment.item", "mercadolibre.shipment.item"]

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )
    shipping_id = fields.Many2one("mercadolibre.bind_shipment",string="Shipment Binding")
    product = fields.Char(string="Product Id")
    variation = fields.Char(string="Variation Id Binded")
    quantity = fields.Float(string="Quantity")

class MercadoLibreConnectionBindingSaleOrderShipment(models.Model):

    _name = "mercadolibre.bind_shipment"
    _description = "Ocapi Sale Order Shipment Binding"
    _inherit = ["ocapi.binding.shipment","mercadolibre.shipment"]

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )

    order_id = fields.Many2one("mercadolibre.sale_order",string="Order Id", index='btree_not_null')
    products = fields.One2many("mercadolibre.bind_shipment.item", "shipping_id", string="Product Items")

class MercadoLibreConnectionBindingSaleOrderClient(models.Model):

    _name = "mercadolibre.client"
    _description = "MercadoLibre Client Binding"
    _inherit = ["ocapi.binding.client","mercadolibre.buyers"]

    def get_display_name(self):
        for client in self:
            # [26.269] 'contactPerson' no existe en el modelo: leer display_name tiraba
            # AttributeError (formulario del contacto / many2one client), a cualquier usuario.
            persona = client.nickname or " ".join(filter(None, [client.first_name, client.last_name]))
            client.display_name = ("%s [%s]" % (persona, client.name or "")) if persona else (client.name or "")

    display_name = fields.Char(string="Display Name",store=False,compute=get_display_name)
    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )

class MercadoLibreConnectionBindingSaleOrderLine(models.Model):

    _name = "mercadolibre.sale_order_line"
    _description = "MercadoLibre Sale Order Line Binding"
    _inherit = ["ocapi.binding.sale_order_line", "mercadolibre.order_items" ]

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )
    order_id = fields.Many2one("mercadolibre.sale_order",string="Order")

class MercadoLibreConnectionBindingSaleOrder(models.Model):

    _name = "mercadolibre.sale_order"
    _description = "MercadoLibre Sale Order Binding Sale"
    _inherit = ["ocapi.binding.sale_order","mercadolibre.orders"]

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )
    mercadolibre_old_order = fields.Many2one( "mercadolibre.orders", string="MercadoLibre Old Order" )
    client = fields.Many2one("mercadolibre.client",string="Client",index=True)

    lines = fields.One2many("mercadolibre.sale_order_line","order_id", string="Order Items Lines")
    payments = fields.One2many("mercadolibre.payment","order_id",string="Order Payments")
    shipments = fields.One2many("mercadolibre.bind_shipment","order_id",string="Order Shipments")


    def orders_query_iterate( self, offset=0, account=None, meli=None, context=None ):

        offset_next = 0

        account = account or self.connection_account
        company = (account and account.company_id) or self.env.user.company_id
        config = account.configuration or company
        context = context or self.env.context

        orders_obj = self.env['mercadolibre.sale_order']

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        orders_query = "/orders/search?seller="+meli.seller_id+"&sort=date_desc"
        #TODO: "create parameter for": orders_query+= "&limit=10"

        if (offset):
            orders_query = orders_query + "&offset="+str(offset).strip()

        response = meli.get( orders_query, {'access_token':meli.access_token})
        orders_json = response.json()

        if "error" in orders_json:
            _logger.error( orders_query )
            _logger.error( orders_json["error"] )
            if (orders_json["message"]=="invalid_token"):
                _logger.error( orders_json["message"] )
            return {}

        order_date_filter = ("mercadolibre_filter_order_datetime" in config._fields and config.mercadolibre_filter_order_datetime)

        if "paging" in orders_json:
            if "total" in orders_json["paging"]:
                if (orders_json["paging"]["total"]==0):
                    return {}
                else:
                    if (orders_json["paging"]["total"]>=(offset+orders_json["paging"]["limit"])):
                        if not order_date_filter:
                            offset_next = 0
                        else:
                            offset_next = offset + orders_json["paging"]["limit"]
                        #_logger.info("offset_next:"+str(offset_next))

        if "results" in orders_json:
            for order_json in orders_json["results"]:
                if order_json:
                    #_logger.info( order_json )
                    pdata = {"id": False, "order_json": order_json}
                    try:
                        self.orders_update_order_json( data=pdata, config=config, meli=meli )
                        MeliCommit( self )
                    except Exception as e:
                        _logger.error("orders_query_iterate > Error actualizando ORDEN")
                        _logger.error(e, exc_info=True)
                        pass

        if (offset_next>0):
            self.orders_query_iterate(offset=offset_next, account=account, meli=meli)

        return {}

    def orders_query_recent( self, account=None, meli=None, context=None ):

        context = context or self.env.context
        account = account or self.connection_account

        #_logger.info("mercadolibre.sale_order >> orders_query_recent("+str(account)+","+str(meli)+") context: " + str(context))
        if not account:
            return {}

        company = (account and account.company_id) or self.env.user.company_id
        config = account.configuration or company

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        if 1==1:
            #_logger.info("mercadolibre.sale_order >> recall mercadolibre.orders >> orders_query_recent: "+str(config and config.name))
            self.env['mercadolibre.orders'].orders_query_recent( meli=meli, config=config )
            return {}

        Autocommit( self )

        try:
            self.orders_query_iterate( offset=0, account=account, meli=meli )
        except Exception as e:
            #_logger.info("orders_query_recent > Error iterando ordenes")
            _logger.error(e, exc_info=True)
            MeliRollback( self )

        return {}

#class MercadoLibreConnectionBindingProductCategory(models.Model):

#    _name = "mercadolibre.category"
#    _description = "MercadoLibre Binding Category"
#    _inherit = "ocapi.binding.category"

#    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )

#    name = fields.Char(string="Category",index=True)
#    category_id = fields.Char(string="Category Id",index=True)
