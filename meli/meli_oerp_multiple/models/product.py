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
import json
from odoo import fields, models, api
from odoo.tools.translate import _
import logging
_logger = logging.getLogger(__name__)
import pdb
from odoo.addons.meli_oerp.models.warning import warning

# Cache en proceso de los atributos de categoría de MercadoLibre
# (GET /categories/{id}/attributes). Clave = meli_category_id (str). Evita pegarle
# a la API en cada intento de publicación del pre-flight de atributos obligatorios (#532).
# Los atributos de categoría son muy estables; se cachean por vida del worker.
_MELI_CATEGORY_ATTRIBUTES_CACHE = {}
import requests

from odoo.addons.meli_oerp.models.versions import *

from . import versions
from .versions import *

from odoo.exceptions import UserError, ValidationError

import hashlib
import math
import base64
import mimetypes
from urllib.request import urlopen
import string

if (not ('replace' in string.__dict__)):
    string = str


_MELI_PRODUCT_DOMAINS = {
    'MLB': 'https://produto.mercadolivre.com.br',
    'MLA': 'https://articulo.mercadolibre.com.ar',
    'MLM': 'https://articulo.mercadolibre.com.mx',
    'MCO': 'https://articulo.mercadolibre.com.co',
    'MPE': 'https://articulo.mercadolibre.com.pe',
    'MLC': 'https://articulo.mercadolibre.cl',
    'MLU': 'https://articulo.mercadolibre.com.uy',
    'MLV': 'https://articulo.mercadolibre.com.ve',
    'MRD': 'https://articulo.mercadolibre.com.do',
    'MPA': 'https://articulo.mercadolibre.com.pa',
    'MPY': 'https://articulo.mercadolibre.com.py',
    'MEC': 'https://articulo.mercadolibre.com.ec',
    'MBO': 'https://articulo.mercadolibre.com.bo',
}

def _meli_short_permalink(meli_id):
    """URL corta canónica construida directamente desde el meli_id guardado.
    Formato: https://<dominio-pais>/<SITE>-<NUMEROID>
    No requiere llamada a la API."""
    if not meli_id:
        return ''
    k = next((i for i, c in enumerate(meli_id) if c.isdigit()), len(meli_id))
    if k >= len(meli_id):
        return ''
    site = meli_id[:k]
    domain = _MELI_PRODUCT_DOMAINS.get(site, 'https://www.mercadolibre.com')
    return domain + '/' + site + '-' + meli_id[k:]


class product_template(models.Model):

    _inherit = "product.template"

    def _meli_backfill_get_accounts(self):
        """Multi-account override of the MELI "Plantilla" backfill hook.

        In the multi-account layout the ML tokens do NOT live on res.company
        (there seller_id/access_token are False); they live on
        mercadolibre.account. Iterate the connected accounts and build one
        logged-in meli.util per account so the backfill fetches each item with
        the token of its OWNING seller (the wrong token returns 403). Each
        account's own item ids are listed by the generic hook via
        mercadolibre.account.fetch_list_meli_ids. Falls back to the base
        (res.company) layout when there are no connected accounts."""
        if 'mercadolibre.account' not in self.env:
            return super()._meli_backfill_get_accounts()
        util = self.env['meli.util']
        accounts = []
        for acc in self.env['mercadolibre.account'].search([('access_token', '!=', False)]):
            meli = util.get_new_instance(account=acc)
            if meli and not meli.need_login():
                accounts.append({
                    'key': 'account-%s' % acc.id,
                    'meli': meli,
                    'company': acc.company_id,
                    'source': acc,
                })
            else:
                _logger.warning("MELI backfill: cuenta '%s' sin login, se omite", acc.display_name)
        return accounts or super()._meli_backfill_get_accounts()

    mercadolibre_bindings = fields.Many2many( "mercadolibre.product_template", string="MercadoLibre Connection Bindings", copy=False,
                                             groups="meli_oerp_multiple.group_mercadolibre_connectors_manager" )

    def _mercadolibre_bindings_has_fulfillment(self):
        for ptpl in self:
            ptpl.mercadolibre_bindings_has_fulfillment = False
            for bindT in ptpl.mercadolibre_bindings:
                if bindT.meli_shipping_logistic_type and bindT.meli_shipping_logistic_type == "fulfillment":
                    ptpl.mercadolibre_bindings_has_fulfillment = True

    mercadolibre_bindings_has_fulfillment = fields.Boolean(string="Meli Has Fulfillment Publications",compute=_mercadolibre_bindings_has_fulfillment,store=True)
    meli_free_shipping = fields.Boolean(string='Envío gratis')
    meli_local_pick_up = fields.Boolean(string='Recoger en tienda')

    def ocapi_price(self, account):
        return self.lst_price

    def ocapi_stock(self, account):
        return self.virtual_available

    def mercadolibre_image_url_principal(self):
        return "/ocapi/mercadolibre/img/%s/%s/%s" % (str(self.id), str(self.default_code), str("default"))

    def mercadolibre_image_id_principal(self):
        return "%s" % (str(self.id))

    def mercadolibre_image_url(self, image):
        return "/ocapi/mercadolibre/img/%s/%s/%s" % (str(self.id), str(self.default_code), str(image.id))

    def mercadolibre_image_id(self, image):
        return "%s" % (str(image.id))

    def action_meli_preview_publication(self):
        """Abre el wizard de preview de publicación ML"""
        self.ensure_one()
        return self.env['meli.publication.preview.wizard'].create_preview(product_tmpl_id=self.id)

    # Binding template
    # @param account
    # @param meli_id (meli_id to bind the product.template to, fetch the meli_id publication to check ids validaty too)
    # @param bind_variant (set with product.product to bind specific variant)
    # @param bind_variants (set to bind all variants to Producteca, if meli_id exists fetchs meli ids and id variations)
    # @param meli (set to optimize access to meli api (account specific))
    # @param bind_only (do not bind blindly, just make the binding using SKU reference and such)
    # @param fast_create (mass-import path: skip search/write of existing bindings,
    #         create directly. Only safe when the caller has confirmed the binding
    #         doesn't exist yet — see connection_account.py:_process_meli_item_direct
    #         and product_meli_get_products.)
    def mercadolibre_bind_to(self, account, meli_id=None, rjson=None, bind_variants=True, bind_variant=None, meli=None, bind_only=False, fast_create=False):

        pt_bind = None
        account_id = (account and type(account)!=int and account.id) or (type(account)==int and account)
        account = self.env["mercadolibre.account"].browse(account_id)
        _logger.debug("BINDING TEMPLATE > mercadolibre_bind_to account: "+str(account and account.name))
        bind_single_variant = bind_variant
        #_logger.info("product_template > mercadolibre_bind_to > "+" context:"+str(self.env.context)+" account_id:"+str(account_id) + " account:"+str(account.name) )
        for product_tmpl_id in self:

            #for bind in product_tmpl_id.mercadolibre_bindings:
                #_logger.info("Before binding > bind in product_tmpl_id.mercadolibre_bindings: "+str(bind))
            #    if ( account_id in bind.connection_account.ids):
                    #account ok, now check if conn_id/meli_id is ok.
            #        if ( bind.conn_id == meli_id ):
            #            _logger.info("mercadolibre_bind_to > No need to add, bindT exists")
            #            continue;

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account)

            if rjson or meli_id:
                #if meli is not set, its a new pub or a new bind
                rjson = rjson or account.fetch_meli_product( meli_id = meli_id, meli=meli )
                _logger.debug("Checking rjson: seller_id:"+str(rjson and rjson.get("seller_id"))+" vs. account seller_id:"+str(account and account.seller_id))

            meli_title = rjson and "title" in rjson and rjson["title"].encode("utf-8")
            meli_title = meli_title or product_tmpl_id.meli_title or product_tmpl_id.name

            meli_sku = (rjson and "seller_skus" in rjson and rjson["seller_skus"])
            meli_sku = meli_sku or (rjson and "seller_sku" in rjson and rjson["seller_sku"])

            meli_barcode = (rjson and "barcodes" in rjson and rjson["barcodes"])
            meli_barcode = meli_barcode or (rjson and "barcode" in rjson and rjson["barcode"])

            meli_variation_ids = (rjson and "variation_ids" in rjson and rjson["variation_ids"])

            #TODO: clean old code
            #meli_sku = product_tmpl_id.product_variant_ids.mapped("default_code") or product_tmpl_id.default_code or ''
            #meli_barcode = product_tmpl_id.product_variant_ids.mapped("barcode") or product_tmpl_id.barcode or ''

            #_logger.info(_("mercadolibre_bind_to >> Adding/Update product (tpl) %s to %s, id: %s, bind_variants: %i") % (product_tmpl_id.display_name, account.name, str(meli_id), bind_variants))
            try:
                prod_binding = {
                    "connection_account": account.id,
                    "product_tmpl_id": product_tmpl_id.id,
                    "name": meli_title,
                    "meli_title": meli_title,
                    "description": product_tmpl_id.description_sale,
                    "sku": meli_sku,
                    "barcode": meli_barcode,
                    "conn_id": meli_id,
                    "conn_variation_id": meli_variation_ids
                }
                #TODO: agregar check de activos via query
                # MULTIGET: fast_create — importación masiva, create directo sin search
                if fast_create:
                    pt_bind = self.env["mercadolibre.product_template"].create([prod_binding])
                else:
                    pt_bind = self.env["mercadolibre.product_template"].search([ ("product_tmpl_id","=",product_tmpl_id.id),
                                                                                 ("connection_account","=",account.id),
                                                                                 ("conn_id", "=", meli_id)])

                    _logger.debug("Searching for template bindings for "+str(meli_id)+": "+str(pt_bind))
                    if len(pt_bind):
                        pt_bind = pt_bind[0]
                        pt_bind.write(prod_binding)
                    else:
                        pt_bind = self.env["mercadolibre.product_template"].create([prod_binding])

                if pt_bind:

                    pt_bind.copy_from_rjson( rjson=rjson, meli=meli )
                    #_logger.info("BINDING TEMPLATE > copy_from_rjson: "+str(pt_bind.connection_account and pt_bind.connection_account.name))

                    product_tmpl_id.mercadolibre_bindings = [(4, pt_bind.id)]

                    if (bind_variants or bind_variant):
                        #_logger.info( "[PRODUCT.TEMPLATE] mercadolibre_bind_to > Binding Variants X "+str(len(product_tmpl_id.product_variant_ids)) )
                        vari = 0
                        has_variations = False
                        for variant in product_tmpl_id.product_variant_ids:
                            vari+= 1
                            #_logger.info( "[PRODUCT.TEMPLATE] mercadolibre_bind_to > Binding Variant: #"+str(vari))
                            if (bind_variant and bind_variant.id==variant.id):
                                pv_bind = variant.mercadolibre_bind_to( account, binding_product_tmpl_id=pt_bind, meli_id=meli_id, meli=meli, rjson=rjson, bind_only=bind_only, fast_create=fast_create )

                            elif (bind_variants and not bind_variant):
                                pv_bind = variant.mercadolibre_bind_to( account, binding_product_tmpl_id=pt_bind, meli_id=meli_id, meli=meli, rjson=rjson, bind_only=bind_only, fast_create=fast_create )


                            if (pv_bind and pv_bind.conn_variation_id):
                                has_variations = True
                        #DROP UNASSIGNED variation_ids
                        #is multi variation binding, but old bindings must not persist if conn_variation_id not set
                        if (has_variations and (pt_bind.variant_bindings and len(pt_bind.variant_bindings)>len(product_tmpl_id.product_variant_ids))):
                            #drop all UNASSIGNED bindings for this meli_id_variation
                            un_pv_bind = self.env["mercadolibre.product"].search([ ("conn_id","=",meli_id),
                                                                                ("conn_variation_id","=",False),
                                                                                #("product_tmpl_id","=",product_tmpl_id.id),
                                                                                ("connection_account","=",account.id)])
                            #_logger.info("BINDING TEMPLATE > WARNING dropping because no variations match: "+str(un_pv_bind))
                            if un_pv_bind:
                                pvba = None
                                for pvb in un_pv_bind:
                                    pvba = pvb
                                    if pvba:
                                        #_logger.info("Unlink UNASSIGNED conn_variation_id:"+str(pv_bind))
                                        pvba.unlink()
                                        MeliCommit( self )

                    
                    if ( pt_bind and pt_bind.connection_account and account and account.id!=pt_bind.connection_account.id ):
                        #_logger.error("Ojo cuentas no coinciden! Settig correct account.")
                        pt_bind.connection_account = account
                        MeliCommit( self )

            except Exception as e:
                _logger.error("Exception")
                _logger.error(e, exc_info=True)
                pass;

        return pt_bind

    def mercadolibre_unbind_from( self, account, meli_id=None, unbind_variants=True):
        pt_bind = None

        for productT in self:

            #for bind in productT.mercadolibre_bindings:
            #    if not (account.id in bind.connection_account.ids):
            #        #_logger.info("No need to remove")
            #        continue;

            #_logger.info(_("Removing product %s to %s") % (productT.display_name, account.name))
            try:
                #meli_id_filter = []
                #if meli_id:
                #    meli_id_filter = [( 'conn_id', '=', meli_id )]
                #else:
                #    meli_id_filter = [( 'conn_id', '=', None )]

                #pt_binds = self.env["mercadolibre.product_template"].search( [("product_tmpl_id","=",productT.id),
                #                                                             ("connection_account","=",account.id)]
                #                                                             + meli_id_filter)
                _logger.info("product.template mercadolibre_unbind_from()")
                pt_binds_all = self.env["mercadolibre.product_template"].search_all(connection_account=account, conn_id=meli_id, product_tmpl_id=productT )

                #for pv_bind in pv_binds:
                _logger.info("product.template mercadolibre_unbind_from() pt_binds_all: "+str(pt_binds_all))
                if (pt_binds_all and pt_binds_all[0]):
                    for pt_bind in pt_binds_all:
                        _logger.info("product.template mercadolibre_unbind_from() pt_bind: "+str(pt_bind))
                        _logger.info("product.template mercadolibre_unbind_from() productT.mercadolibre_bindings: "+str(productT.mercadolibre_bindings))
                        for ptb in productT.mercadolibre_bindings:
                            if ptb.id == pt_bind[0]:
                                productT.mercadolibre_bindings = [(3, ptb.id)]

                        _logger.info("product.template mercadolibre_unbind_from() productT.mercadolibre_bindings: "+str(productT.mercadolibre_bindings))

                        if (unbind_variants):
                            _logger.info("product.template deleting variants bindings of this ptpl binding")
                            if (pt_bind[0]):                                
                                pt_bind_obj = self.env["mercadolibre.product_template"].browse(pt_bind[0]);                                
                                if (pt_bind_obj and pt_bind_obj.variant_bindings):
                                    for pv_bind in pt_bind_obj.variant_bindings:
                                        _logger.info("product.template  unbind linking variant binding "+str(pv_bind) )
                                        pv_bind.unlink()

                            _logger.info("product.template  unbinding meli id from all possible variants of this product template")
                            for variant in productT.product_variant_ids:
                                pv_bind = variant.mercadolibre_unbind_from( account, binding_product_tmpl_id=False, meli_id=pt_bind[2] )

                self.env["mercadolibre.product_template"].unlink_all(connection_account=account, conn_id=meli_id, product_tmpl_id=productT )

                MeliCommit( self )
                #for pt_bind in pt_binds:
                #    if pt_bind:
                #        productT.mercadolibre_bindings = [(3, pt_bind.id)]

                #        if (unbind_variants):
                #            for variant in productT.product_variant_ids:
                #                pv_bind = variant.mercadolibre_unbind_from( account, binding_product_tmpl_id=pt_bind )

                #        pt_bind.unlink()
                #        MeliCommit( self )
            except Exception as e:
                _logger.error(e, exc_info=True)
                pass;

        return pt_bind

    def product_template_update( self, meli_id=None, meli=None, account=None, import_images=True ):
        #_logger.info("product.template >> product_template_update meli_id: "+str(meli_id)+" account: "+str(account)+" meli: "+str(meli))
        res = {}
        for productT in self:
            if not productT.mercadolibre_bindings:
                #bind and continue
                #_logger.info("bind and continue: "+str(meli))
                productT.mercadolibre_bind_to( account=account, meli_id=meli_id, meli=meli )

            for bindT in productT.mercadolibre_bindings:
                #_logger.info("Update bindings: bindT:"+str(bindT))
                res = bindT.product_template_update( meli=meli, import_images=import_images )
                if 'name' in res:
                    return res

        return res

    # Post product and bind them if needed
    # WARNING: the meli_oerp_multiple version always call the mercadolibre.product_template (bindings) method: product_template_post

    # @param meli_id if False try to post as a new ML post
    #                if MLABBBBBBB try to post/update the specific product itself
    def product_template_post( self, context=None, meli_id=None, meli=None, account=None ):

        context = context or self.env.context
        new_pub = context.get("force_meli_new_pub")
        #_logger.info("product.template >> product_template_post context: "+str(context)+" meli_id: "+str(meli_id)+" account: "+str(account)+" new_pub: "+str(new_pub))


        res = {}
        for productT in self:
            #POST NEW
            #_logger.info( "productT.mercadolibre_bindings:" + str(productT.mercadolibre_bindings) )
            if ((not productT.mercadolibre_bindings) or new_pub):
                #bind and continue post (meli_id defined or None(new pub))
                #_logger.info("[PRODUCT.TEMPLATE] >> product_template_post > NEW PUBLICATION")

                if new_pub:
                    meli_id = None
                    #_logger.info("[PRODUCT.TEMPLATE] >> Creating new pub")
                elif not productT.mercadolibre_bindings:
                    if productT.meli_pub_as_variant:
                        #_logger.info("Auto binding old pub and update it")
                        autocorrect_principal = productT.meli_pub_principal_variant and productT.meli_pub_principal_variant.product_tmpl_id.id!=productT.id
                        if (autocorrect_principal):
                            productT.meli_pub_principal_variant = (productT.product_variant_ids and productT.product_variant_ids[0]) or None

                        meli_id = (productT.meli_pub_principal_variant and productT.meli_pub_principal_variant.meli_id) or None

                        #_logger.info("Auto binding old pub and update it: 1st, meli_id: "+str(meli_id))
                        for variant in productT.product_variant_ids:
                            if variant.meli_id:
                                #_logger.info("Auto binding old pub and update it: variant.meli_id: "+str(variant.meli_id))
                                meli_id = meli_id or variant.meli_id
                        #_logger.info("Auto binding old pub and update it: Last, meli_id: "+str(meli_id))

                if productT.meli_pub_as_variant:
                    #create new binding template

                    #_logger.info("[PRODUCT.TEMPLATE] >> create new binding template for:"+str(productT))
                    bindT = productT.mercadolibre_bind_to( account=account, meli_id=meli_id, meli=meli )
                    #WARNING: TODO: new pub have no conn_variation_id, so they are deleted automatically
                    #we must call product_template_rebind (somewhere after posting)
                    if bindT:
                        #_logger.info("[PRODUCT.TEMPLATE] >> created new binding template: calling product_template_post")
                        #use it to post new item
                        res = bindT.product_template_post( meli=meli )
                        #_logger.info("res bindT.product_template_post:"+str(res))
                        #bindT.product_template_rebind()
                        if res and 'name' in res:
                            return res
                else:
                    #post NEW PUB for each variant (new bind template also)
                    for variant in productT.product_variant_ids:
                        #meli_id = (variant.meli_id) or None
                        if variant.meli_id and not new_pub:
                            meli_id = variant.meli_id
                        else:
                            meli_id = None
                        bindT = productT.mercadolibre_bind_to( account=account, meli_id=meli_id, meli=meli, bind_variant=variant )
                        if bindT:
                            res = bindT.product_template_post( meli=meli, product_variant=variant )
                            #bindT.product_template_rebind()
                            if res and 'name' in res:
                                return res

            #UPDATE OLD
            else:
                #re post all bindings...
                #_logger.info("[PRODUCT.TEMPLATE] >> product_template_post > repost all bindings: " +str(productT.mercadolibre_bindings.mapped('conn_id')) )
                for bindT in productT.mercadolibre_bindings:
                    #solo los bindings de la cuenta pedida (multi-cuenta):
                    #sin este filtro se repostean las publicaciones de las OTRAS
                    #cuentas usando el `meli` (token) de esta -> 403 de ML.
                    #mismo criterio que product_template_post_stock/_price/_title.
                    condition = not account
                    condition = condition or (account and bindT.connection_account and account.id == bindT.connection_account.id )
                    if not condition:
                        continue
                    meli_id_match = meli_id and ( meli_id==bindT.conn_id )
                    if not meli_id or meli_id_match:
                        res = bindT.product_template_post( meli=meli, account=account )
                        #bindT.product_template_rebind()
                        #_logger.info("bindT.product_template_post res: "+str(res))
                        if res and 'name' in res:
                            return res

        return res

    def action_meli_pause(self):
        #product.meli_stock_block()
        for product in self:
            product.product_meli_block()
            for bind in product.mercadolibre_bindings:
                bind.product_meli_block()
                bind.product_meli_status_pause()
                #if (variant.meli_pub):
                #    variant.product_meli_status_pause()
            #for variant in product.product_variant_ids:
                #if (variant.meli_pub):
                #    variant.product_meli_status_pause()
        return {}

    def action_meli_activate(self):
        for product in self:
            product.product_meli_unblock()
            for bind in product.mercadolibre_bindings:
                product.product_meli_unblock()
                bind.product_meli_status_active()
            #for variant in product.product_variant_ids:
                #if (variant.meli_pub):
                #    variant.product_meli_status_active()
        return {}

    def action_meli_close(self):
        for product in self:
            for bind in product.mercadolibre_bindings:
                bind.product_meli_status_close()
            #for variant in product.product_variant_ids:
                #if (variant.meli_pub):
                #    variant.product_meli_status_close()
        return {}

    def action_meli_delete(self):
        for product in self:
            for bind in product.mercadolibre_bindings:
                bind.product_meli_delete()
            #for variant in product.product_variant_ids:
                #if (variant.meli_pub):
                #    variant.product_meli_delete()
        return {}

    def _meli_try_rebind_binding_by_sku(self, bindT):
        """
        Intenta revincular `bindT` (mercadolibre.product_template) a un
        `product.template` activo con el mismo SKU.

        Escenario: el usuario archivó el producto viejo y creó un reemplazo
        con el mismo SKU. Antes de pausar la publicación en ML, conviene
        revincularla al producto nuevo para mantener la vinculación viva.

        Retorna True si revinculó exitosamente (caller debe NO pausar).
        Retorna False si no hay match, es ambiguo, o hay conflicto de unicidad.
        """
        # 1. Extraer SKU del binding (o de la primera variante si el template no tiene)
        sku = bindT.sku or ''
        sku = sku.strip()
        if not sku or sku == 'False' or sku.startswith('['):
            for vb in bindT.variant_bindings:
                if vb.sku and vb.sku != 'False':
                    sku = vb.sku.strip()
                    break
        if not sku or sku == 'False':
            return False

        # 2. Buscar variante activa con ese SKU — preferimos product.product
        # porque cubre tanto single-variant como multi-variant (tomamos su product_tmpl_id)
        new_variant = self.env['product.product'].search([
            ('default_code', '=', sku),
            ('active', '=', True),
        ], limit=2)
        if len(new_variant) != 1:
            _logger.info(
                "[auto-rebind] bindT id=%s skip: SKU=%s matches %d productos activos (esperaba 1)",
                bindT.id, sku, len(new_variant),
            )
            return False

        new_tmpl = new_variant.product_tmpl_id
        old_tmpl = bindT.product_tmpl_id

        if not new_tmpl or not new_tmpl.active:
            return False
        if old_tmpl and new_tmpl.id == old_tmpl.id:
            return False

        # 3. Validar unicidad: no puede existir otro binding con el mismo
        # (connection_account, conn_id, conn_variation_id, product_tmpl_id=new_tmpl)
        existing = self.env['mercadolibre.product_template'].with_context(active_test=False).search([
            ('connection_account', '=', bindT.connection_account.id),
            ('conn_id', '=', bindT.conn_id),
            ('product_tmpl_id', '=', new_tmpl.id),
            ('id', '!=', bindT.id),
        ], limit=1)
        if existing:
            _logger.warning(
                "[auto-rebind] bindT id=%s skip: ya existe binding id=%s para nuevo template id=%s",
                bindT.id, existing.id, new_tmpl.id,
            )
            return False

        # 4. Snapshot de variantes ANTES de reescribir (para actualizar M2M inverso)
        variant_migrations = []
        for vb in bindT.variant_bindings:
            vb_sku = (vb.sku or '').strip()
            if not vb_sku or vb_sku == 'False':
                continue
            candidate = new_tmpl.product_variant_ids.filtered(
                lambda p: p.default_code == vb_sku and p.active
            )
            if len(candidate) != 1:
                continue
            variant_migrations.append((vb, vb.product_id, candidate))

        # 5. Ejecutar la revinculación (template binding)
        bindT.sudo().write({'product_tmpl_id': new_tmpl.id})

        # 6. Mantener consistente el M2M inverso product.template ↔ mercadolibre_bindings
        if old_tmpl:
            try:
                old_tmpl.sudo().write({'mercadolibre_bindings': [(3, bindT.id)]})
            except Exception as e:
                _logger.warning("[auto-rebind] no pude desvincular M2M del viejo template id=%s: %s", old_tmpl.id, e)
        try:
            new_tmpl.sudo().write({'mercadolibre_bindings': [(4, bindT.id)]})
        except Exception as e:
            _logger.warning("[auto-rebind] no pude vincular M2M al nuevo template id=%s: %s", new_tmpl.id, e)

        # 7. Revincular variantes (una por una, cada una defensiva)
        rebind_variants_ok = 0
        for vb, old_variant, new_variant_rec in variant_migrations:
            try:
                # chequeo de unicidad a nivel variante
                existing_v = self.env['mercadolibre.product'].with_context(active_test=False).search([
                    ('connection_account', '=', vb.connection_account.id),
                    ('conn_id', '=', vb.conn_id),
                    ('conn_variation_id', '=', vb.conn_variation_id),
                    ('product_id', '=', new_variant_rec.id),
                    ('id', '!=', vb.id),
                ], limit=1)
                if existing_v:
                    _logger.warning(
                        "[auto-rebind] variante vb id=%s skip: ya existe binding id=%s para variante nueva id=%s",
                        vb.id, existing_v.id, new_variant_rec.id,
                    )
                    continue
                vb.sudo().write({'product_id': new_variant_rec.id})
                if old_variant and 'mercadolibre_bindings' in old_variant._fields:
                    old_variant.sudo().write({'mercadolibre_bindings': [(3, vb.id)]})
                if 'mercadolibre_bindings' in new_variant_rec._fields:
                    new_variant_rec.sudo().write({'mercadolibre_bindings': [(4, vb.id)]})
                rebind_variants_ok += 1
            except Exception as e:
                _logger.exception("[auto-rebind] fallo revinculando variante vb id=%s: %s", vb.id, e)

        _logger.info(
            "[auto-rebind] bindT id=%s conn_id=%s revinculado: template %s → %s (SKU=%s, variantes=%d/%d)",
            bindT.id, bindT.conn_id,
            old_tmpl.display_name if old_tmpl else '(sin template)',
            new_tmpl.display_name, sku,
            rebind_variants_ok, len(variant_migrations),
        )
        return True

    def _meli_auto_pause_on_archive(self):
        """
        Al archivar una plantilla (active=False), por cada publicación ML
        asociada:

        1. Intentar REVINCULAR a un product.template activo con el mismo SKU
           (escenario: usuario reemplazó el producto viejo por uno nuevo).
        2. Si no se revinculó → PAUSAR la publicación si aún estaba activa en ML.

        Esto evita pausar innecesariamente cuando hay un reemplazo claro y
        mantiene la publicación funcional vinculada al producto vigente.

        Cada binding se procesa en try/except para no bloquear el archivado
        si la API ML falla. Bypass disponible vía context flag
        `meli_skip_auto_pause=True`.
        """
        if self.env.context.get('meli_skip_auto_pause'):
            return
        for product in self:
            if product.active:
                continue
            for bindT in product.mercadolibre_bindings:
                try:
                    if not bindT.conn_id:
                        continue

                    # 1. Intentar revincular a producto nuevo con mismo SKU
                    if self._meli_try_rebind_binding_by_sku(bindT):
                        # revinculado: NO pausar, NO tocar status ML.
                        # El usuario activará manualmente si la publicación
                        # estaba pausada por un auto-pause previo.
                        continue

                    # 2. No hay reemplazo → pausar si está activa en ML
                    variant_bindings = bindT.variant_bindings if 'variant_bindings' in bindT._fields else None
                    has_active = False
                    if variant_bindings:
                        has_active = any(v.meli_last_status == 'active' for v in variant_bindings)
                    else:
                        has_active = bindT.meli_status and 'active' in (bindT.meli_status or '')
                    if not has_active:
                        _logger.info(
                            "[auto-pause] bindT id=%s conn_id=%s skip: ninguna variante activa",
                            bindT.id, bindT.conn_id,
                        )
                        continue
                    _logger.info(
                        "[auto-pause] product.template id=%s archivado sin reemplazo → pausando binding id=%s conn_id=%s",
                        product.id, bindT.id, bindT.conn_id,
                    )
                    bindT.product_meli_block()
                    bindT.product_meli_status_pause()
                except Exception as e:
                    _logger.exception(
                        "[auto-pause] fallo procesando binding id=%s del product.template id=%s: %s",
                        getattr(bindT, 'id', None), product.id, e,
                    )

    def write(self, vals):
        # Detectar transición active: True → False por registro ANTES de escribir
        templates_to_autopause = self.env['product.template']
        if 'active' in vals and not vals.get('active') \
                and not self.env.context.get('meli_skip_auto_pause'):
            templates_to_autopause = self.filtered(lambda p: p.active)
        res = super(product_template, self).write(vals)
        if templates_to_autopause:
            templates_to_autopause._meli_auto_pause_on_archive()
        return res

    def product_template_post_stock( self, context=None, meli=None, account=None ):
        #_logger.info("producte.template: product_template_post_stock")
        res = []
        for productT in self:
            for bindT in productT.mercadolibre_bindings:
                condition = not account
                condition = condition or (account and bindT.connection_account and account.id == bindT.connection_account.id )
                if condition:
                    r = bindT.product_template_post_stock(meli=meli,account=account)
                    res.append(r)
        return res

    def product_template_post_price( self, context=None, meli=None, account=None ):
        #_logger.info("producte.template: product_template_post_price")
        res = []
        for productT in self:
            for bindT in productT.mercadolibre_bindings:
                condition = not account
                condition = condition or (account and bindT.connection_account and account.id == bindT.connection_account.id )
                if condition:
                    r = bindT.product_template_post_price(meli=meli,account=account)
                    res.append(r)
        return res

    def product_template_post_title( self, context=None, meli=None, account=None ):
        # Empuja SOLO el título a ML por cada binding de plantilla (multi-cuenta).
        # Corta y devuelve el dict de error del primer binding que falle.
        for productT in self:
            for bindT in productT.mercadolibre_bindings:
                condition = not account
                condition = condition or (account and bindT.connection_account and account.id == bindT.connection_account.id )
                if condition:
                    r = bindT.product_template_post_title(meli=meli,account=account)
                    if r and isinstance(r, dict) and 'error' in r:
                        return r
        return {}

    def _post_family_name_secondary_variants(self, meli=None, config=None, bind_tpl=None, force_context=None):
        """
        user_product_seller: publica cada variante no-principal como listing independiente
        en ML usando family_name. ML las agrupa automaticamente por family_id.

        Flujo ML para user_product_seller con multiples variantes:
          POST /items { family_name: "...", ... }  <- variante principal (ya publicada)
          POST /items { family_name: "...", ... }  <- variante 2 (este metodo)
          POST /items { family_name: "...", ... }  <- variante 3 (este metodo)
        ML agrupa todas bajo el mismo family_id automaticamente.

        @param meli: instancia de meli.util
        @param config: configuracion de cuenta (mercadolibre.config o mercadolibre.account)
        @param bind_tpl: binding de plantilla (mercadolibre.product_template), opcional
        @param force_context: contexto adicional a pasar al product_post de cada variante
        @return: (posted_count, errors_list)
        """
        for product_tmpl in self:
            variant_principal = product_tmpl.meli_pub_principal_variant
            posted = 0
            errors = []

            for variant in product_tmpl.product_variant_ids:
                # skip la variante principal — ya fue publicada por el caller
                if variant_principal and variant.id == variant_principal.id:
                    continue

                # skip variantes no marcadas para publicacion
                if not variant.meli_pub:
                    _logger.info("user_product_seller family_name: skipping variant (meli_pub=False): %s", variant)
                    continue

                _logger.info("user_product_seller family_name: posting secondary variant: %s (meli_id=%s)", variant, variant.meli_id)

                ctx = dict(force_context or {})
                ctx['family_name_variant_post'] = True

                ret = variant.with_context(ctx).product_post(meli=meli, config=config)

                if ret and len(ret) and isinstance(ret[0], dict) and 'name' in ret[0]:
                    _logger.error("user_product_seller family_name: error posting variant %s: %s", variant, ret[0])
                    errors.append({'variant': str(variant), 'error': ret[0]})
                else:
                    posted += 1
                    _logger.info("user_product_seller family_name: variant posted OK: %s meli_id=%s", variant, variant.meli_id)
                    # Actualizar binding de variante con su propio meli_id
                    if bind_tpl and variant.meli_id:
                        for bind in bind_tpl.variant_bindings:
                            if bind.product_id and bind.product_id.id == variant.id:
                                bind.conn_id = variant.meli_id
                                bind.update_price()
                                break

            _logger.info("user_product_seller family_name: secondary variants done — posted:%d errors:%d", posted, len(errors))
        return posted, errors


class product_product(models.Model):

    _inherit = "product.product"

    mercadolibre_bindings = fields.Many2many( "mercadolibre.product", string="MercadoLibre Connection Bindings", copy=False,
                                             groups="meli_oerp_multiple.group_mercadolibre_connectors_manager" )

    def _meli_price_converted( self, meli_price=None, config=None ):
        company = (config and 'company_id' in config._fields and config.company_id) or self.env.user.company_id
        config = config or company
        #_logger.info("_meli_set_product_price: config: "+str(config and config.name))
        ml_price_converted = meli_price
        product = self
        product_template = self.product_tmpl_id
        tax_excluded = ml_tax_excluded(self, config=config)

        if ( tax_excluded and product_template.taxes_id ):
            #_logger.info("Adjust taxes")
            txfixed = 0
            txpercent = 0
            #_logger.info("Adjust taxes")
            for txid in product_template.taxes_id:
                if (txid.type_tax_use=="sale" and not txid.price_include):
                    if (txid.amount_type=="percent"):
                        txpercent = txpercent + txid.amount
                    if (txid.amount_type=="fixed"):
                        txfixed = txfixed + txid.amount
            if (txfixed>0 or txpercent>0):
                #_logger.info("Tx Total:"+str(txtotal)+" to Price:"+str(ml_price_converted))
                ml_price_converted = txfixed + ml_price_converted / (1.0 + txpercent*0.01)
                #_logger.info("Price adjusted with taxes:"+str(ml_price_converted))

        return ml_price_converted

    def ocapi_price(self, account):
        return self.lst_price

    def _ocapi_virtual_available(self, account):

        product_id = self
        qty_available = product_id.virtual_available
        #loc_id = self._ocapi_get_location_id()

        #quant_obj = self.env['stock.quant']

        #qty_available = quant_obj._get_available_quantity(product_id, loc_id)

        return qty_available

    def ocapi_stock(self, account=None):
        stocks = []
        #ss = variant._product_available()
        sq = self.env["stock.quant"].search([('product_id','=',self.id)])
        if (sq):
            #_logger.info( sq )
            #_logger.info( sq.name )
            for s in sq:
                if ( s.location_id.usage == "internal" ):
                    #_logger.info( s )
                    sjson = {
                        "warehouseId": s.location_id.id,
                        "warehouse": s.location_id.display_name,
                        "quantity": s.quantity,
                        "reserved": s.reserved_quantity,
                        "available": s.quantity - s.reserved_quantity
                    }
                    stocks.append(sjson)
        return stocks

    def mercadolibre_image_url_principal(self):
        code = self.default_code or self.barcode
        return "/ocapi/mercadolibre/img/%s/%s/%s" % (str(self.id), str(code), str("default") )

    def mercadolibre_image_id_principal(self):
        return "%s" % ( str(self.id) )

    def mercadolibre_image_url(self, image):
        code = self.default_code or self.barcode
        return "/ocapi/mercadolibre/img/%s/%s/%s" % (str(self.id), str(code), str(image.id) )

    def mercadolibre_image_id(self, image):
        return "%s" % ( str(image.id) )

    def mercadolibre_bind_variation_id( self, account=None, meli_id=None, meli=None, rjson=None ):

        #associate using SKU
        product = self

        #_logger.info("mercadolibre_bind_variation_id > associate right variation id to this product..., using SKU or combination (not using barcode yet)")

        meli_id_variation = False

        if not rjson:
            return meli_id_variation

        if ("variations" in rjson and len(rjson["variations"])>0 ):

            for var in rjson["variations"]:

                sku = ("seller_sku" in var and var["seller_sku"]) or ("seller_custom_field" in var and var["seller_custom_field"]) or None
                bcode = ("barcode" in var and var["barcode"]) or None

                seller_sku = None

                if sku and product.default_code:
                    #TODO: cap unsensitive comparison?
                    #_logger.info("mercadolibre_bind_variation_id >> check sku and default_code: "+str(sku)+" vs." + str(product.default_code) )
                    if product.default_code == sku:
                        #_logger.info("mercadolibre_bind_variation_id >> meli_id_variation match: same SKU: " + product.name + " << " + str(sku) + " >>>> var id:" +str(var["id"]))
                        meli_id_variation = var["id"]
                        seller_sku = sku
                        barcode = bcode

                if not sku or not product.default_code:
                    #check if combination is related to base product binded variant
                    #_logger.info("mercadolibre_bind_variation_id >> check combination: "+str(product._combination())+" vs." + str(var) )
                    if (product._is_product_combination(var)):
                        meli_id_variation = var["id"]
                        #_logger.info("mercadolibre_bind_variation_id >> meli_id_variation match: "+str(meli_id_variation)+" >> var: "+str(var) )

            if not meli_id_variation:
                _logger.error("mercadolibre_bind_variation_id >> meli_id_variation NOT match: "+str(meli_id_variation) )
                pass;

        else: #no variations
            # RPM #532: un item SIN variaciones puede traer el SKU SOLO en el
            # atributo SELLER_SKU (attributes[] id=='SELLER_SKU'), con
            # seller_custom_field/seller_sku a nivel item en None. La extraccion
            # vieja miraba solo esas dos claves -> None -> abort "NO SKU" falso.
            # Reutilizar fetch_meli_sku (lee tambien el atributo), consistente con
            # _process_meli_item_direct. Comparacion case-insensitive (el SKU en ML
            # puede diferir solo en mayus/minus del default_code de Odoo).
            sku = account.fetch_meli_sku(meli_id=meli_id, meli_id_variation=None, meli=meli, rjson=rjson)
            if isinstance(sku, (list, tuple)):
                sku = None
            bcode = ("barcode" in rjson and rjson["barcode"])
            _logger.debug(f"SKU_MELI: {sku}, default_code: {product.default_code}")
            seller_sku = None

            if sku and product.default_code and product.default_code.lower() == sku.lower():
                seller_sku = sku
                barcode = bcode
                meli_id_variation = None

            if not seller_sku:
                #abort binding (using Only SKU binding)
                _logger.error(_("mercadolibre_bind_to >> Aborting binding product (using Only SKU: NO SKU) %s to %s, id: %s, var id: %s, sku: %s") % (product.display_name, account.name, str(meli_id), str(meli_id_variation),str(seller_sku)))
                seller_sku = None
                meli_id_variation = None

        #_logger.info("mercadolibre_bind_variation_id > IS: " + str(meli_id_variation))
        return meli_id_variation

    def mercadolibre_bind_to( self, account, binding_product_tmpl_id=False, meli_id=None, meli_id_variation=None, meli=None, rjson=None, bind_only=False, fast_create=False ):
        # `fast_create` enables the mass-import path: skip the search/cleanup of
        # existing bindings and create directly. Only safe when the caller knows
        # the binding doesn't exist yet (see _process_meli_item_direct and
        # product_meli_get_products in connection_account.py). The actual
        # fast-path branch is implemented further down inside the for-loop
        # (look for `if fast_create:`).
        pv_bind = None
        pvba = None
        #_logger.info( "mercadolibre_bind_to >> product bind_only: " + str(bind_only)+" meli_id: "+str(meli_id)+" meli_id_variation: "+str(meli_id_variation)+" context:"+str(self.env.context) )
        for product in self:

            #for bind in product.mercadolibre_bindings:
            #    if (account.id in bind.connection_account.ids):
            #        #account ok, now check if conn_id/meli_id is ok.
            #        if ( bind.conn_id == meli_id ):
            #            #_logger.info("No need to add")
            #            if (bind.binding_product_tmpl_id and
            #                product.product_tmpl_id.id==bind.binding_product_tmpl_id.id):
            #                binding_product_tmpl_id = bind.binding_product_tmpl_id
            #                continue;

            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account)

            if rjson or meli_id:
                rjson = rjson or account.fetch_meli_product( meli_id = meli_id, meli=meli )

            meli_title = (rjson and "title" in rjson and rjson["title"].encode("utf-8")) or product.name
            seller_sku = account.fetch_meli_sku( meli_id = meli_id, meli_id_variation = meli_id_variation, meli=meli, rjson=rjson)
            barcode = False

            #TODO: check if id variation correspond really to this default_code/sku or attribute combination
            product_not_imported = (product and not product.meli_id and meli_id and (1==1))
            product_imported_not_matching_binding = (product and product.meli_id and meli_id and product.meli_id!=meli_id)
            #define bind_only depending on importing status
            bind_only = bind_only or ( product_not_imported ) or (product_imported_not_matching_binding)
            #_logger.info("bind_only: "+str(bind_only))
            if (meli_id_variation==None and bind_only==True):
                meli_id_variation = product.mercadolibre_bind_variation_id( account=account, meli_id=meli_id, meli=meli, rjson=rjson )

                # seller_sku can be a list if product has variations
                # Check if default_code matches any SKU in the list
                sku_matches = False
                if product.default_code and seller_sku:
                    # RPM #532: comparar case-insensitive. El SKU en ML puede diferir
                    # solo en mayus/minus del default_code de Odoo; el lookup de
                    # _process_meli_item_direct ya matchea con .lower() (por eso el
                    # producto SE encuentra), pero este gate case-sensitive hacia
                    # `continue` y abortaba el binding de ~392 items pausados.
                    dc_lower = product.default_code.lower()
                    if isinstance(seller_sku, (list, tuple)):
                        sku_matches = dc_lower in [s.lower() for s in seller_sku if s]
                    else:
                        sku_matches = (seller_sku.lower() == dc_lower)

                if not meli_id_variation and product.default_code and seller_sku and not sku_matches:
                    #_logger.info("Dont bind, sku not match: sku: "+str(seller_sku)+" vs default_code:"+str( product.default_code))
                    continue;
                #call with meli_id_variation set!
                seller_sku = account.fetch_meli_sku( meli_id = meli_id, meli_id_variation = meli_id_variation, meli=meli, rjson=rjson)

            #TODO: esto es para vincular directo sin chequeo
            meli_id_variation = meli_id_variation or (bind_only==False and meli_id and product.meli_id==meli_id and product.meli_id_variation)
            # Ensure seller_sku is a string (fetch_meli_sku returns list for variations)
            if isinstance(seller_sku, (list, tuple)):
                seller_sku = ', '.join(seller_sku) if seller_sku else ''
            seller_sku = seller_sku or (bind_only==False and product.default_code) or ''
            barcode = barcode or (bind_only==False and product.barcode) or None

            #_logger.info(_("mercadolibre_bind_to >> Adding/Update product %s to %s, id: %s, var id: %s, sku: %s, barcode: %s") % (product.display_name, account.name, str(meli_id), str(meli_id_variation),str(seller_sku),str(barcode)))

            try:
                # [solsun-local->source] Savepoint sobre TODO el cuerpo del bind: cualquier
                # fallo SQL (unlink/write/create/copy_from_rjson) abortaba la tx PG; el except
                # desnudo atrapaba la excepcion Python pero dejaba la tx muerta y el llamador
                # seguia con SQL (fetch_meli_product -> copy_from_rjson) cayendo con
                # InFailedSqlTransaction. Seguro en Odoo 19: MeliCommit()=env.flush_all() (ERROR-010).
                with self.env.cr.savepoint():

                    prod_binding = {
                        "connection_account": account.id,
                        "product_tmpl_id": product.product_tmpl_id.id,
                        "product_id": product.id,
                        "name": meli_title,
                        "meli_title": meli_title,
                        "description": product.description_sale, #TODO: same as seller_sku and barcode
                        "sku": seller_sku,
                        "barcode": barcode,
                        "conn_id": meli_id,
                        "conn_variation_id": meli_id_variation,
                        #TODO deprecated meli_id and meli_id_variation
                        "meli_id": meli_id,
                        "meli_id_variation": meli_id_variation,
                        #"price": product.ocapi_price(account),
                        #"stock": product.ocapi_stock(account),
                    }

                    #Binding Product Template (parent) if missing
                    if binding_product_tmpl_id:
                        prod_binding["binding_product_tmpl_id"] = binding_product_tmpl_id.id
                    else:
                        pt_bind = self.env["mercadolibre.product_template"].search([("conn_id","=",meli_id),
                                                                                    ("product_tmpl_id","=",product.product_tmpl_id.id),
                                                                                    ("connection_account","=",account.id)])
                        if pt_bind and len(pt_bind):
                            prod_binding["binding_product_tmpl_id"] = pt_bind[0].id
                        else:
                            pt_bind = product.product_tmpl_id.mercadolibre_bind_to( account, meli_id=meli_id, bind_variants=False, meli=meli, rjson=rjson, bind_only=bind_only, fast_create=fast_create )
                            if pt_bind and len(pt_bind):
                                prod_binding["binding_product_tmpl_id"] = pt_bind[0].id

                    # fast_create — importación masiva desde cero.
                    # Saltarse las 5 queries de búsqueda/limpieza de bindings existentes.
                    # Usar solo cuando el cron confirma que el binding NO existe en BD.
                    if fast_create:
                        pvba = self.env["mercadolibre.product"].create([prod_binding])
                        if pvba:
                            pvba.copy_from_rjson(rjson=rjson, meli=meli)
                            product.mercadolibre_bindings = [(4, pvba.id)]
                        pv_bind = pvba
                        continue  # saltar el bloque normal de búsqueda/write

                    #Binding Variant finally
                    #_logger.info(prod_binding)

                    pv_bind = self.env["mercadolibre.product"].search([ ("conn_id","=",meli_id),
                                                                        ("conn_variation_id","=",meli_id_variation),
                                                                        ("product_id","=",product.id),
                                                                        ("product_tmpl_id","=",product.product_tmpl_id.id),
                                                                        ("connection_account","=",account.id)],
                                                                        order="id desc")
                    pvba = (pv_bind and pv_bind[0]) or None

                    if pv_bind: #unlink last ones
                        #_logger.info("#### UNLINK LAST WELL DEFINED #### "+str(meli_id)+"/"+str(meli_id_variation))
                        #_logger.info( "Found [complete] var binding: " + str(pv_bind) )
                        pvba = pv_bind[0]
                        for pvb in pv_bind:
                            if not (pvb==pvba):
                                #_logger.info("Unlinking:"+str(pvb))
                                pvb.unlink()
                                MeliCommit( self )
                                #_logger.info("####")


                    if not pv_bind: #then search first for any variant binding with same conn_variation_id == meli_id_variation
                        pv_bind = self.env["mercadolibre.product"].search([ ("conn_id","=",meli_id),
                                                                            ("conn_variation_id","=",meli_id_variation),
                                                                            #search not using product id: ("product_id","=",product.id),
                                                                            ("product_tmpl_id","=",product.product_tmpl_id.id),
                                                                            ("connection_account","=",account.id)],
                                                                            order="id desc")
                        if pv_bind:
                            #unlink last ones
                            #_logger.info("#### UNLINK WITH ANY PRODUCT ID #### "+str(meli_id)+"/"+str(meli_id_variation))
                            #_logger.info( "Found [conn_variation_id] var binding: " + str(pv_bind) )
                            pvba = pv_bind[0]
                            #_logger.info( "Found [conn_variation_id] var binding PVBA: " + str(pvba) )
                            for pvb in pv_bind:
                                if not (pvb==pvba):
                                    #_logger.info("Unlinking:"+str(pvb))
                                    pvb.unlink()
                                    MeliCommit( self )
                                    #_logger.info("####")

                    if not pv_bind: #then search first for any variant binding binded to this product  - always from this publication
                        pv_bind = self.env["mercadolibre.product"].search([ ("conn_id","=",meli_id),
                                                                        #("conn_variation_id","=",meli_id_variation or product.meli_id_variation),
                                                                        ("product_id","=",product.id),
                                                                        ("product_tmpl_id","=",product.product_tmpl_id.id),
                                                                        ("connection_account","=",account.id)])

                        if pv_bind:
                            #unlink last ones
                            #_logger.info("#### UNLINK WITH ANY VAR ID #### "+str(meli_id)+"/"+str(meli_id_variation))
                            #_logger.info( "Found [product_id] var binding: " + str(pv_bind) )
                            pvba = pv_bind[0]
                            #_logger.info( "Found [conn_variation_id] var binding PVBA: " + str(pvba) )
                            if len(pv_bind)>0:
                                for pvb in pv_bind:
                                    if not (pvb==pvba):
                                        #_logger.info("Unlinking:"+str(pvb))
                                        pvb.unlink()
                                        MeliCommit( self )
                                        #_logger.info("####")

                    if pvba:
                        #_logger.info(pv_bind)
                        #_logger.info("#### REWRITE PVBA ####")
                        #_logger.info("Rewrite variant binding: pvba:"+str(pvba) + " vals: " + str(prod_binding))
                        pvba.write(prod_binding)
                    else:
                        #really need to create it
                        #_logger.info("#### CREATE PVBA ####")
                        #_logger.info("creating variant binding: " + str(prod_binding))
                        pvba = self.env["mercadolibre.product"].create([prod_binding])

                    if pvba:

                        pvba.copy_from_rjson( rjson=rjson, meli=meli )

                        product.mercadolibre_bindings = [(4, pvba.id)]

                        if (meli_id_variation):
                            #drop all UNASSIGNED bindings for this meli_id_variation
                            un_pv_bind = self.env["mercadolibre.product"].search([ ("conn_id","=",meli_id),
                                                                                ("conn_variation_id","=",meli_id_variation),
                                                                                ("product_id","=",False),
                                                                                #("product_tmpl_id","=",product.product_tmpl_id.id),
                                                                                ("connection_account","=",account.id)])
                            if un_pv_bind:
                                for pvb in un_pv_bind:
                                    #_logger.info("Unlink UNASSIGNED")
                                    pvb.unlink()
                                    MeliCommit( self )

                        if (not meli_id_variation):
                            #drop all UNASSIGNED bindings
                            un_pv_bind = self.env["mercadolibre.product"].search([ ("conn_id","=",meli_id),
                                                                                ("conn_variation_id","=",False),
                                                                                ("product_id","=",False),
                                                                                #("product_tmpl_id","=",product.product_tmpl_id.id),
                                                                                ("connection_account","=",account.id)])
                            if un_pv_bind:
                                for pvb in un_pv_bind:
                                    #_logger.info("Unlink UNASSIGNED")
                                    pvb.unlink()
                                    MeliCommit( self )

                    if ( pvba and pvba.connection_account and account and account.id!=pvba.connection_account.id ):
                        _logger.error("Ojo cuentas no coinciden! Setting correct account pvba.")
                        pvba.connection_account = account
                        MeliCommit( self )

            except Exception as e:
                _logger.error("mercadolibre_bind_to > "+str(meli_title))
                _logger.error(e, exc_info=True)
                pass;

        return pvba

    def mercadolibre_unbind_from( self, account, binding_product_tmpl_id=False, meli_id=None, meli_id_variation=None):
        pv_bind = None

        for product in self:

            #for bind in product.mercadolibre_bindings:
            #    if not (account.id in bind.connection_account.ids):
                    #_logger.info("No need to remove")
            #        continue;

            #_logger.info(_("Removing product %s from %s") % (product.display_name, account.name))
            try:
                #meli_id_filter = []
                meli_id = meli_id or (binding_product_tmpl_id and binding_product_tmpl_id.conn_id)
                #if meli_id:
                #    meli_id_filter = [('conn_id','=',meli_id)]
                #if meli_id and meli_id_variation:
                #    meli_id_filter = [('conn_id','=',meli_id),('conn_variation_id','=',meli_id_variation)]

                #pv_binds = self.env["mercadolibre.product"].search([("product_id","=",product.id),
                #                                                    ("connection_account","=",account.id)]
                #                                                    + meli_id_filter )
                _logger.info("product.product mercadolibre_unbind_from()")

                pv_binds_all = self.env["mercadolibre.product"].search_all( connection_account=account, conn_id=meli_id, conn_variation_id=meli_id_variation, product_id=product )
                _logger.info("product.product mercadolibre_unbind_from() pv_binds:"+str(pv_binds_all))

                if pv_binds_all:
                    for pv_bind in pv_binds_all:
                        if pv_bind and pv_bind[0]:
                            _logger.info("product.product mercadolibre_unbind_from() pv_bind:"+str(pv_bind))
                            _logger.info("product.product mercadolibre_unbind_from() product.mercadolibre_bindings:"+str(product.mercadolibre_bindings))
                            for pvb in product.mercadolibre_bindings:
                                if pvb.id == pv_bind[0]:
                                    product.mercadolibre_bindings = [(3, pvb.id)]
                            _logger.info("product.product mercadolibre_unbind_from() product.mercadolibre_bindings:"+str(product.mercadolibre_bindings))

                pv_bind = self.env["mercadolibre.product"].unlink_all( connection_account=account, conn_id=meli_id, conn_variation_id=meli_id_variation, product_id=product )

                #    if pv_bind:
                #        product.mercadolibre_bindings = [(3, pv_bind.id)]
                #        pv_bind.unlink()
                MeliCommit( self )

            except Exception as e:
                _logger.error(e, exc_info=True)
                pass;

        return pv_bind

    def is_variant_in_combination( self, ml_var_comb_default_code, var_default_code ):
        splits = ml_var_comb_default_code.split(";")
        is_in = True
        for att in splits:
            att_closed = att+";"
            if not att_closed in var_default_code:
                is_in = False
                break;
        return is_in

    def product_meli_get_product( self, meli_id=None, account=None, meli=None, rjson=None, import_images=True ):
        product = self
        meli_id = meli_id or product.meli_id
        product.meli_id = meli_id

        #_logger.info("meli_oerp_multiple >> product_meli_get_product >> meli_id: "+str(meli_id)+" default_code: "+str(product.default_code))
        if not account:
            return { "error": "product_meli_get_product: no account" }

        company = (account and account.company_id) or self.env.user.company_id
        config = account.configuration
        product_obj = self.env['product.product']
        uomobj = self.env[uom_model]
        #pdb.set_trace()

        product_template_obj = self.env['product.template']
        product_template = product_template_obj.browse(product.product_tmpl_id.id)

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        try:
            #response = meli.get("/items/"+product.meli_id, {'access_token':meli.access_token})
            #_logger.info(response)
            rjson = rjson or account.fetch_meli_product( meli_id=product.meli_id, meli=meli )
            #_logger.info(rjson)
            if not rjson:
                return { "error": "No meli data" }
        except IOError as e:
            _logger.error( "I/O error({0}): {1}".format(e.errno, e.strerror) )
            return { "error": "product_meli_get_product I/O error({0}): {1}".format(e.errno, e.strerror) }
        except:
            _logger.error( "Rare error" )
            return { "error": "Rare error" }

        des = ''
        desplain = ''
        vid = ''
        if rjson and 'error' in rjson:
            return { "error": rjson["error"] }

        #TODO: traer la descripcion: con
        #https://api.mercadolibre.com/items/{ITEM_ID}/description?access_token=$ACCESS_TOKEN
        if rjson and 'descriptions' in rjson:
            response2 = meli.get("/items/"+str(meli_id)+"/description", {'access_token':meli.access_token})
            rjson2 = response2.json()
            if 'text' in rjson2:
               des = rjson2['text']
            if 'plain_text' in rjson2:
               desplain = rjson2['plain_text']
            if (len(des)>0):
                desplain = des

            #publication specific banner
            mlbanner = product.meli_mercadolibre_banner or product_template.meli_mercadolibre_banner
            #configuration banner
            mlbanner = mlbanner or (config and config.mercadolibre_banner)
            if (mlbanner):
                #get the text, not the header nor the footer
                desplain = mlbanner.get_from_ml_description(desplain)

        #TODO: verificar q es un video
        if 'video_id' in rjson and rjson['video_id']:
            vid = rjson['video_id']

        #TODO: traer las imagenes
        #TODO:
        pictures = rjson['pictures']
        if import_images:
            if pictures and len(pictures):
                #remove all meli images not in pictures:
                product._meli_remove_images_unsync( product_template, pictures )
                product._meli_set_images(product_template, pictures)

        #categories
        # [solsun-local->source] Savepoint: un fallo SQL en _meli_set_category abortaba la tx y
        # TODO lo posterior de la sync (precio, posting.search, ...) caia con InFailedSqlTransaction.
        try:
            with self.env.cr.savepoint():
                product._meli_set_category( product_template, rjson['category_id'], meli=meli, config=config )
        except Exception as e:
            _logger.error(e, exc_info=True)

        #prices
        force_price_for_variant = True

        # if 2 or more variations, its a variant publication, one price for all else one for each product variant as they are independent
        if "variations" in rjson and len(rjson["variations"])>1:
            force_price_for_variant = False

        try:
            if (float(rjson['price'])>=0.0):
                # [solsun-local->source] Savepoint: el except desnudo dejaba la tx PG abortada ->
                # InFailedSqlTransaction en el SQL siguiente (posting.search).
                with self.env.cr.savepoint():
                    product._meli_set_product_price( product_template, rjson['price'], force_variant=force_price_for_variant, config=config )
        except Exception as e:
            _logger.error(e, exc_info=True)
            rjson['price'] = 0.0
            pass;

        imagen_id = ''
        meli_dim_str = ''
        if ('dimensions' in rjson):
            if (rjson['dimensions']):
                meli_dim_str = rjson['dimensions']

        if ('pictures' in rjson):
            if (len(rjson['pictures'])>0):
                imagen_id = rjson['pictures'][0]['id']

        try:
            if (float(rjson['price'])>=0.0):
                product._meli_set_product_price( product_template, rjson['price'], config=config )
        except:
            rjson['price'] = 0.0
            pass;

        try:
            rjson['warranty'] = rjson['warranty']
        except:
            pass;

        meli_fields = {
            'name': rjson['title'].encode("utf-8"),
            #'default_code': rjson['id'],
            'meli_imagen_id': imagen_id,
            #'meli_post_required': True,
            'meli_id': rjson['id'],
            'meli_title': rjson['title'].encode("utf-8"),
            'meli_description': desplain,
            'meli_listing_type': rjson['listing_type_id'],
            'meli_buying_mode':rjson['buying_mode'],
            'meli_price': str(rjson['price']),
            'meli_price_fixed': True,
            'meli_currency': rjson['currency_id'],
            'meli_condition': rjson['condition'],
            'meli_available_quantity': rjson.get('available_quantity', 0), #if it does not have available_quantity, it defaults to 0
            'meli_warranty': rjson['warranty'],
            'meli_imagen_link': rjson['thumbnail'],
            'meli_video': str(vid),
            'meli_dimensions': meli_dim_str,
        }

        tmpl_fields = {
          'name': meli_fields["name"],
          'description_sale': desplain,
          #'company_id': company.id,
          #'name': str(rjson['id']),
          #'lst_price': ml_price_convert,
          'meli_title': meli_fields["meli_title"],
          'meli_description': meli_fields["meli_description"],
          #'meli_category': meli_fields["meli_category"],
          'meli_listing_type': meli_fields["meli_listing_type"],
          'meli_buying_mode': meli_fields["meli_buying_mode"],
          'meli_price': meli_fields["meli_price"],
          'meli_currency': meli_fields["meli_currency"],
          'meli_condition': meli_fields["meli_condition"],
          'meli_warranty': meli_fields["meli_warranty"],
          'meli_dimensions': meli_fields["meli_dimensions"]
        }

        if (product.name and not config.mercadolibre_overwrite_variant):
            del meli_fields['name']
        if (product_template.name and not config.mercadolibre_overwrite_template):
            del tmpl_fields['name']
        if (product_template.description_sale and not config.mercadolibre_overwrite_template):
            del tmpl_fields['description_sale']

        has_user_product_id = product._fetch_meli_user_product_id( meli_id=meli_id, meli_id_variation=None, meli=meli, config=config, item_json=rjson )
        if (has_user_product_id):
            meli_fields["meli_user_product_id"] = has_user_product_id
            tmpl_fields["meli_user_product_id"] = has_user_product_id

        if ("catalog_listing" in rjson):
            meli_fields["meli_catalog_listing"] = rjson["catalog_listing"]
            if (meli_fields["meli_catalog_listing"]==True):
                tmpl_fields["meli_catalog_listing"] = True

            if ("automatic_relist" in rjson):
                meli_fields["meli_catalog_automatic_relist"] = rjson["automatic_relist"]
                if (meli_fields["meli_catalog_listing"]==True):
                    tmpl_fields["meli_catalog_automatic_relist"] = True

            if ("catalog_product_id" in rjson):
                meli_fields["meli_catalog_product_id"] = rjson["catalog_product_id"]
                if (meli_fields["meli_catalog_listing"]==True):
                    tmpl_fields["meli_catalog_product_id"] = rjson["catalog_product_id"]

            if ("item_relations" in rjson):
                meli_fields["meli_catalog_item_relations"] = rjson["item_relations"]
                if (meli_fields["meli_catalog_listing"]==True):
                    tmpl_fields["meli_catalog_item_relations"] = rjson["item_relations"]

        product.write( meli_fields )
        product_template.write( tmpl_fields )

        if "mercadolibre_update_product_company" in config._fields and config.mercadolibre_update_product_company:
            #_logger.info(" > mercadolibre_update_product_company ")
            product_template.company_id = account.company_id
        meli_available_quantity = rjson.get('available_quantity', 0)
        if (meli_available_quantity >=0):
            try:
                # [solsun-local->source] Savepoint: write(ProductType()) fallido dejaba la tx
                # abortada y arrastraba al resto de la importacion.
                with self.env.cr.savepoint():
                    product_template.write( ProductType() )
            except Exception as e:
                #_logger.info("Set type almacenable ('product') not possible:")
                _logger.error(e, exc_info=True)
                pass;
            #TODO: agregar parametro para esto: ml_auto_website_published_if_available  default true
            if (1==1 and meli_available_quantity >0):
                product_template.website_published = True

        #TODO: agregar parametro para esto: ml_auto_website_unpublished_if_not_available default false
        if (1==2 and meli_available_quantity ==0):
            product_template.website_published = False

        posting_fields = {
            'posting_date': str(datetime.now()),
            'meli_id':rjson['id'],
            'product_id':product.id,
            'name': 'Post ('+str(product.meli_id)+'): ' + product.meli_title
        }

        posting = self.env['mercadolibre.posting'].search([('meli_id','=',rjson['id'])], limit=1)
        posting_id = posting.id

        if not posting_id:
            posting = self.env['mercadolibre.posting'].create((posting_fields))
            posting_id = posting.id
            #if (posting):
            #    posting.posting_query_questions()
        else:
            posting.write({'product_id':product.id })
            #posting.posting_query_questions()

        b_search_nonfree_ship = False
        if ('shipping' in rjson):

            if "logistic_type" in rjson["shipping"]:
                product.meli_shipping_logistic_type = rjson["shipping"]["logistic_type"]

            att_shipping = {
                'name': 'Con envío',
                'create_variant': default_no_create_variant
            }
            if ('variations' in rjson):
                #_logger.info("has variations")
                pass
            else:
                rjson['variations'] = []

            if ('free_methods' in rjson['shipping']):
                att_shipping['value_name'] = 'Sí'
                #buscar referencia del template correspondiente
                b_search_nonfree_ship = True
            else:
                att_shipping['value_name'] = 'No'

            #TODO: remove! warning! obsolete!
            #rjson['variations'].append({'attribute_combinations': [ att_shipping ]})

        #_logger.info(rjson['variations'])
        #COMPLETING ATTRIBUTES VARIATION INFORMATION FROM /items/[MLID]/variations/[VARID]...
        if ('variations' in rjson and len(rjson['variations'])>0 and 1==1):
            vindex = -1
            realmeliv = 0
            for variation in rjson['variations']:
                vindex = vindex+1
                #_logger.info(variation)
                #_logger.info(rjson['variations'][vindex])
                if 'id' in rjson['variations'][vindex]:
                    #_logger.info(vid)
                    realmeliv = realmeliv+1
                    vid = rjson['variations'][vindex]['id']
                    #resvar = meli.get("/items/"+str(product.meli_id)+"/variations/"+str(vid), {'access_token':meli.access_token})
                    #vjson = resvar.json()
                    vjson = variation
                    #if ( "error" in vjson ):
                    #    continue;
                    if ("attributes" in vjson):
                        rjson['variations'][vindex]["attributes"] = vjson["attributes"]
                        for att in vjson["attributes"]:
                            if ("id" in att and att["id"] == "SELLER_SKU"):
                                rjson['variations'][vindex]["seller_sku"] = att["value_name"]
            #_logger.info(rjson['variations'])

            if ( realmeliv>0 and 1==1 ):
                #associate var ids for every variant
                product_template.meli_pub_as_variant = True
                if (not product_template.meli_pub_principal_variant
                    or not product_template.meli_pub_principal_variant.id == product.id):
                    for variant in product_template.product_variant_ids:
                        if not product_template.meli_pub_principal_variant:
                            product_template.meli_pub_principal_variant = variant
                        for variation in rjson['variations']:
                            if ("seller_sku" in variation and variant.default_code == variation["seller_sku"]):
                                variant.meli_id_variation = variation["id"]
                                variant.meli_pub = True
                                variant.meli_id = product.meli_id
                                variant.meli_available_quantity = variation["available_quantity"]

        published_att_variants = False
        if (config.mercadolibre_update_existings_variants and 'variations' in rjson and len(rjson['variations'])>0):
            published_att_variants = self._get_variations( rjson['variations'])

            update_pvid = True
            for pv in product_template.product_variant_ids:
                if product.id==pv.id:
                    update_pvid = False
            if update_pvid:
                product = product_template.product_variant_ids and product_template.product_variant_ids[0]


        #_logger.info("product_uom_id")
        product_uom_id = uomobj.search([('name','=','Unidad(es)')])
        if (product_uom_id.id==False):
            product_uom_id = 1
        else:
            product_uom_id = product_uom_id.id

        _product_id = False
        _product_meli_id = False
        try:
            _product_id = product and product.id
            #_product_name = product.name
            _product_meli_id = product and product.meli_id
        except:
            _logger.info("product: "+str(product))
            _logger.info("product_template: "+str(product_template))
            _logger.info("product_template variants 4: "+str(product_template and product_template.product_variant_ids))
            return { "error": "product undefined, check import creation and attributes"}

        #this write pull the trigger for create_variant_ids()...
        #_logger.info("rewrite to create variants")
        if (config.mercadolibre_update_existings_variants):
            product_template.write({ 'attribute_line_ids': product_template.attribute_line_ids  })
            #TODO: fix meli_user_product_id for each variant...

        #_logger.info("published_att_variants: "+str(published_att_variants))
        if (published_att_variants):
            product_template.meli_pub_as_variant = True

            #_logger.info("Auto check product.template meli attributes to publish")
            for line in  product_template.attribute_line_ids:
                if (line.id not in product_template.meli_pub_variant_attributes.ids):
                    if (line.attribute_id.create_variant=="always"):
                        product_template.meli_pub_variant_attributes = [(4,line.id)]

            #_logger.info("check variants")
            for variant in product_template.product_variant_ids:
                #_logger.info("Created variant:")
                #_logger.info(variant)
                variant.meli_pub = product_template.meli_pub
                variant.meli_id = rjson['id']
                #variant.default_code = rjson['id']
                #variant.name = rjson['title'].encode("utf-8")
                has_sku = False

                _v_default_code = ""
                for att in att_value_ids(variant):
                    _v_default_code = _v_default_code + att.attribute_id.name+':'+att.name+';'
                #_logger.info("_v_default_code: " + _v_default_code)
                therecanbeonlyone = len(rjson['variations'])==1 and len(product_template.product_variant_ids)==1
                for variation in rjson['variations']:
                    #_logger.info(variation)
                    #_logger.info("variation[default_code]: " + variation["default_code"])
                    match_variation = len(variation["default_code"]) and variant.is_variant_in_combination( variation["default_code"], _v_default_code )
                    #_logger.info("Updating variant: "+str(len(rjson['variations']))+" match_variation:"+str(match_variation)+" therecanbeonlyone:"+str(therecanbeonlyone))
                    if ( match_variation or therecanbeonlyone ):
                        #_logger.info("Updating variant with variation")
                        if ("seller_custom_field" in variation or "seller_sku" in variation):
                            #_logger.info("has_sku")
                            #_logger.info(variation["seller_custom_field"])
                            variant.default_code = ("seller_sku" in variation and variation["seller_sku"]) or variation["seller_custom_field"]
                            bcode = ("barcode" in variation and variation["barcode"]) or None
                            try:
                                bcodes = self.env["product.product"].sudo().search([('barcode','=',bcode),('active','=',True)])
                                bcodes_archived = self.env["product.product"].sudo().search([('barcode','=',bcode),('active','=',False)])

                                if not bcodes and bcodes_archived:
                                    _logger.error("Error barcode already defined! In archived product variant!!"+str(bcode))
                                    bcodes = bcodes_archived

                                if bcodes and len(bcodes):
                                    _logger.error("Error barcode already defined! "+str(bcode))
                                else:
                                    variant.barcode = bcode
                            except:
                                pass;
                            variant.meli_id_variation = variation["id"]
                            has_sku = True
                        else:
                            variant.default_code = variant.meli_id+'-'+_v_default_code
                        variant.meli_available_quantity = variation["available_quantity"]

                if (has_sku):
                    variant.set_bom()

                #_logger.info('meli_pub_principal_variant')
                #_logger.info(product_template.meli_pub_principal_variant.id)
                if (product_template.meli_pub_principal_variant.id is False):
                    #_logger.info("meli_pub_principal_variant set!")
                    product_template.meli_pub_principal_variant = variant
                    product = variant

                if (_product_id==variant.id):
                    product = variant
        else:
            #NO TIENE variantes pero tiene SKU
            seller_sku = None
            if not seller_sku and "attributes" in rjson:
                for att in rjson['attributes']:
                    if att["id"] == "SELLER_SKU":
                        seller_sku = att["value_name"]
                        break;

            if (not seller_sku and "seller_sku" in rjson):
                seller_sku = rjson["seller_sku"]

            if (not seller_sku and "seller_custom_field" in rjson):
                seller_sku = rjson["seller_custom_field"]

            if seller_sku:
                product.default_code = seller_sku
                product.set_bom()
            bcode = ("barcode" in rjson and rjson["barcode"]) or None
            if bcode:
                try:
                    bcodes = self.env["product.product"].sudo().search([('barcode','=',bcode),('active','=',True)])
                    bcodes_archived = self.env["product.product"].sudo().search([('barcode','=',bcode),('active','=',False)])

                    if not bcodes and bcodes_archived:
                        _logger.error("Error barcode already defined! In archived product variant!!"+str(bcode))
                        bcodes = bcodes_archived

                    if bcodes and len(bcodes):
                        _logger.error("Error barcode already defined! "+str(bcode))
                    else:
                        product.barcode = bcode
                except:
                    pass;

        if (config.mercadolibre_update_local_stock):
            product_template.write( ProductType() )

            if (len(product_template.product_variant_ids)):
                for variant in product_template.product_variant_ids:

                    _product_id = variant.id
                    #_product_name = variant.name
                    _product_meli_id = variant.meli_id

                    if (variant.meli_available_quantity != variant.virtual_available):
                        variant.product_update_stock(stock=variant.meli_available_quantity, meli=meli, config=config)
            else:
                product.product_update_stock(stock=product.meli_available_quantity, meli=meli, config=config )

        #assign envio/sin envio
        #si es (Con envio: Sí): asigna el meli_default_stock_product al producto sin envio (Con evio: No)
        if (b_search_nonfree_ship and 1==2):
            ptemp_nfree = False
            ptpl_same_name = self.env['product.template'].search([('name','=',product_template.name),('id','!=',product_template.id)])
            #_logger.info("ptpl_same_name:"+product_template.name)
            #_logger.info(ptpl_same_name)
            if len(ptpl_same_name):
                for ptemp in ptpl_same_name:
                    #check if sin envio
                    #_logger.info(ptemp.name)
                    for line in ptemp.attribute_line_ids:
                        #_logger.info(line.attribute_id.name)
                        #_logger.info(line.value_ids)
                        es_con_envio = False
                        try:
                            line.attribute_id.name.index('Con env')
                            es_con_envio = True
                        except ValueError:
                            pass
                            #_logger.info("not con envio")
                        if (es_con_envio==True):
                            for att in line.value_ids:
                                #_logger.info(att.name)
                                if (att.name=='No'):
                                    #_logger.info("Founded")
                                    if (ptemp.meli_pub_principal_variant.id):
                                        #_logger.info("has meli_pub_principal_variant!")
                                        ptemp_nfree = ptemp.meli_pub_principal_variant
                                        if (ptemp_nfree.meli_default_stock_product):
                                            #_logger.info("has meli_default_stock_product!!!")
                                            ptemp_nfree = ptemp_nfree.meli_default_stock_product
                                    else:
                                        if (ptemp.product_variant_ids):
                                            if (len(ptemp.product_variant_ids)):
                                                ptemp_nfree = ptemp.product_variant_ids[0]

            if (ptemp_nfree):
                #_logger.info("Founded ptemp_nfree, assign to all variants")
                for variant in product_template.product_variant_ids:
                    variant.meli_default_stock_product = ptemp_nfree

        if (config.mercadolibre_update_existings_variants and 'attributes' in rjson):
            product._get_non_variant_attributes(rjson['attributes'])

        # Fill the MELI "Plantilla" tab fields (package dims, brand/model/gender,
        # product dimensions WIDTH/HEIGHT/LENGTH, IVA/impuesto interno) on import.
        # This override does NOT chain to base product_meli_get_product, so the
        # call base makes there never runs for multi-account clients; without
        # this the dedicated fields only filled via the "Traer medidas" backfill.
        # [#424/#474 Deco/KPI]
        product._meli_import_template_attributes(product_template, rjson)

        #TODO: images complete
        pictures = rjson['pictures']
        if import_images and pictures and len(pictures):
            #remove all meli images not in pictures:
            if 1==2:
                product.product_tmpl_id.delete_image_product_now()
            product._meli_remove_images_unsync( product_template, pictures )
            product._meli_set_images_x(product_template=product_template, pictures=pictures, rjson=rjson)

        posting_fields = {
            'posting_date': str(datetime.now()),
            'meli_id': rjson['id'],
            'meli_variation_id': ('variations' in rjson and len(rjson['variations'])) and rjson['variations'][0]["id"],
            'product_id': product.id,
            'name': 'Post ('+str(product.meli_id)+'): ' + str(product.meli_title)
        }
        posting = self.env['mercadolibre.posting'].search( [
                                                        ('meli_id','=',posting_fields['meli_id']) ,
                                                        ('meli_variation_id','=',posting_fields['meli_variation_id']),
                                                        ('product_id','=',posting_fields["product_id"]) ],
                                                        limit=1 )
        posting_id = posting.id
        if not posting_id:
            posting = self.env['mercadolibre.posting'].create((posting_fields))
            posting_id = posting.id
            #if (posting):
            #    posting.posting_query_questions()
        else:
            posting.write({'product_id':product.id })
            #posting.posting_query_questions()


        return {}

    def product_update_stock(self, stock=False, meli_id=False, meli=False, config=None):
        product = self
        uomobj = self.env[uom_model]
        _stock = product.virtual_available
        meli_id = meli_id or product.meli_id

        try:
            if (stock!=False):
                _stock = stock
                if (_stock<0):
                    _stock = 0

            if (product.default_code):
                product.set_bom()

            if (product.meli_default_stock_product and meli_id!=product.meli_id):
                _stock = product.meli_default_stock_product._meli_available_quantity(meli=meli,config=config)
                if (_stock<0):
                    _stock = 0

            if (1==2 and _stock>=0 and product._meli_available_quantity( meli_id=meli_id, meli=meli, config=config )!=_stock):
                #_logger.info("Updating stock for variant." + str(_stock) )
                #wh = self.env['stock.location'].search([('usage','=','internal')]).id
                #wh = product._meli_get_location_id(meli_id=product.id,meli=meli,config=config)
                wh = product._meli_get_location_id( meli_id=meli_id, meli=meli, config=config )
                #_logger.info("Updating stock for variant. location: " + str(wh and wh.display_name) )
                #product_uom_id = uomobj.search([('name','=','Unidad(es)')])
                #if (product_uom_id.id==False):
                #    product_uom_id = 1
                #else:
                #    product_uom_id = product_uom_id.id
                product_uom_id = product.uom_id and product.uom_id.id

                stock_inventory_fields = get_inventory_fields(product, wh)

                #_logger.info("stock_inventory_fields:")
                #_logger.info(stock_inventory_fields)
                StockInventory = self.env['stock.inventory'].create(stock_inventory_fields)
                #_logger.info("StockInventory:")
                #_logger.info(StockInventory)
                if (StockInventory):
                    stock_inventory_field_line = {
                        "product_qty": _stock,
                        'theoretical_qty': 0,
                        "product_id": product.id,
                        "product_uom_id": product_uom_id,
                        "location_id": wh and wh.id,
                        #'inventory_location_id': wh and wh.id,
                        "inventory_id": StockInventory.id,
                        #"name": "INV "+ nombre
                        #"state": "confirm",
                    }
                    StockInventoryLine = self.env['stock.inventory.line'].create(stock_inventory_field_line)
                    #print "StockInventoryLine:", StockInventoryLine, stock_inventory_field_line
                    #_logger.info("StockInventoryLine:")
                    #_logger.info(stock_inventory_field_line)
                    if (StockInventoryLine):
                        return_id = stock_inventory_action_done(StockInventory)
                        #_logger.info("action_done:"+str(return_id))
        except Exception as e:
            _logger.info("product_update_stock Exception")
            _logger.info(e, exc_info=True)
            pass;

    #call with product_tmpl or bind template
    def _product_post_set_basic_configuration( self, product_tmpl=None, bind_tpl=None, meli=None, config=None ):
        #check from company's default
        context = self.env.context
        #_logger.info("_product_post_set_basic_configuration: setting template configuration for this configuration. "+str(context))
        force_meli_listing_type = context.get("force_meli_listing_type")

        product_tmpl.meli_listing_type = force_meli_listing_type or (bind_tpl and bind_tpl.meli_listing_type) or product_tmpl.meli_listing_type or config.mercadolibre_listing_type
        product_tmpl.meli_currency = (bind_tpl and bind_tpl.meli_currency) or product_tmpl.meli_currency or config.mercadolibre_currency
        product_tmpl.meli_condition = (bind_tpl and bind_tpl.meli_condition) or product_tmpl.meli_condition or config.mercadolibre_condition
        product_tmpl.meli_warranty = (bind_tpl and bind_tpl.meli_warranty) or product_tmpl.meli_warranty or config.mercadolibre_warranty
        product_tmpl.meli_title = product_tmpl.meli_title or product_tmpl.name
        product_tmpl.meli_buying_mode = (bind_tpl and bind_tpl.meli_buying_mode) or product_tmpl.meli_buying_mode or config.mercadolibre_buying_mode

        product_tmpl.meli_free_shipping = product_tmpl.meli_free_shipping
        product_tmpl.meli_local_pick_up = product_tmpl.meli_local_pick_up

        #Si la descripcion de template esta vacia la asigna del description_sale
        force_template_description = ( config.mercadolibre_product_template_override_variant
                                        and config.mercadolibre_product_template_override_method
                                        and config.mercadolibre_product_template_override_method in ['default','description','title_and_description']
                                        )
        # Leer description_sale con contexto de idioma del país de la conexión
        _COUNTRY_LANG_MAP = {'BR': 'pt_BR', 'AR': 'es_AR', 'MX': 'es_MX', 'CO': 'es', 'CL': 'es', 'UY': 'es', 'PE': 'es'}
        _meli_lang = None
        if config and 'country_id' in config._fields and config.country_id:
            _meli_lang = _COUNTRY_LANG_MAP.get(config.country_id.code)
        if not _meli_lang and config and 'company_id' in config._fields and config.company_id:
            _meli_lang = config.company_id.partner_id.lang
        _desc_sale = (product_tmpl.with_context(lang=_meli_lang).description_sale if _meli_lang
                      else product_tmpl.description_sale) or ''
        # Eliminar tags HTML (description_sale es fields.Html)
        import re as _re_desc
        _desc_plain = _re_desc.sub(r'<[^>]+>', ' ', _desc_sale).strip() if _desc_sale else ''
        _desc_plain = _re_desc.sub(r'\s+', ' ', _desc_plain).strip()
        product_tmpl.meli_description = (force_template_description and _desc_plain) or product_tmpl.meli_description or _desc_plain or ''
        #_logger.info("product_tmpl.meli_description: "+str(product_tmpl)+" description: " +str(product_tmpl.meli_description))

        return {}

    def _product_post_set_price( self, meli_price=None, meli_pricelist=None, source_tmpl=None, target=None, meli=None, config=None ):
        #asigna del template si no esta definido
        source_tmpl.meli_price = meli_price or source_tmpl.meli_price
        if target.meli_price==False or target.meli_price==0.0 or target.meli_price!=source_tmpl.meli_price:
            if source_tmpl.meli_price:
                #_logger.info("Assign source_tmpl price:"+str(meli_price or source_tmpl.meli_price))
                target.meli_price = source_tmpl.meli_price

    def _product_post_set_title( self, meli_title=None, source_tmpl=None, target=None, meli=None, config=None ):
        product_tmpl = source_tmpl
        product = target
        if (
            ( product.meli_title==False or len(product.meli_title)==0 )
            or
            ( product_tmpl.meli_pub_variant_attributes
                and not product_tmpl.meli_pub_as_variant
                    and len(product_tmpl.meli_pub_variant_attributes) )
            ):
            # #_logger.info( 'Assigning title: product.meli_title: %s name: %s' % (product.meli_title, product.name) )
            product.meli_title = product_tmpl.meli_title

            #obsoleto > generacion de titulo automatico en funcion de atributos....
            if (1==2 and len(product_tmpl.meli_pub_variant_attributes)):
                values = ""
                for line in product_tmpl.meli_pub_variant_attributes:
                    for value in att_value_ids(product):
                        if (value.attribute_id.id==line.attribute_id.id):
                            values+= " "+value.name
                if (not product_tmpl.meli_pub_as_variant):
                    product.meli_title = string.replace(product.meli_title,product.name,product.name+" "+values)

        force_template_title = meli_title or ( config.mercadolibre_product_template_override_variant
                                 and config.mercadolibre_product_template_override_method
                                 and config.mercadolibre_product_template_override_method in ['title','title_and_description']
                                )

        product_tmpl.meli_title = meli_title or product_tmpl.meli_title
        product.meli_title = ( force_template_title and product_tmpl.meli_title ) or product.meli_title

        if ( product.meli_title and len(product.meli_title)>60 ):
            message=("El título tiene "+str(len(product.meli_title))+" caracteres y MercadoLibre "
                     "permite un máximo de 60. Acortá el campo 'Nombre del producto en Mercado Libre' "
                     "(pestaña MercadoLibre del producto). Recordá que el título se puede editar hasta "
                     "que entre la primera venta.")
            raise ValidationError(message)
            #return warningobj.info( title='MELI WARNING', message="La longitud del título ("+str(len(product.meli_title))+") es superior a 60 caracteres.", message_html=product.meli_title )

    def _product_post_set_category( self, product_tmpl=None, product=None, meli=None, config=None ):
        www_cats = False
        if 'product.public.category' in self.env:
            www_cats = self.env['product.public.category']

        if www_cats:
            if product.public_categ_ids:
                for cat_id in product.public_categ_ids:
                    #_logger.info(cat_id)
                    if (cat_id.mercadolibre_category):
                        #_logger.info(cat_id.mercadolibre_category)
                        product.meli_category = cat_id.mercadolibre_category
                        product_tmpl.meli_category = cat_id.mercadolibre_category

        if product_tmpl.meli_category and not product.meli_category:
            product.meli_category = product_tmpl.meli_category

    def _product_post_set_quantity( self, target=None, product=None, meli_id=None, meli=None, config=None ):

        target.meli_available_quantity = product._meli_available_quantity( meli_id=meli_id, meli=meli, config=config)
        if (target.meli_available_quantity<0.0):
            target.meli_available_quantity = 0.0

    def _product_post_set_template_configuration( self, source=None, target=None, meli=None, config=None, force_source_description=True ):
        warningobj = self.env['meli.warning']
        #_logger.info("_product_post_set_template_configuration: from " + str(source)+" to:"+str(target))
        res = {}
        #product template > product variant > binding template > binding variant
        force_template_description = ( config.mercadolibre_product_template_override_variant
                                        and config.mercadolibre_product_template_override_method
                                        and config.mercadolibre_product_template_override_method in ['default','description','title_and_description']
                                        )
        meli_description = (force_template_description and source.meli_description)
        meli_description = meli_description or ( force_source_description==False and target.meli_description )

        target.meli_description = meli_description or source.meli_description

        #_logger.info("target.meli_description: target:"+str(target)+" target.meli_description: " +str(target.meli_description))


        if not target.meli_description:
            res = warningobj.info(title='MELI WARNING', message="Debe completar el campo description en la plantilla de MercadoLibre o del producto (Descripción de Ventas)", message_html="<h3>Descripción faltante</h3>")

        target.meli_category = target.meli_category or source.meli_category
        target.meli_listing_type = target.meli_listing_type or source.meli_listing_type
        target.meli_buying_mode = target.meli_buying_mode or source.meli_buying_mode

        target.meli_free_shipping = target.meli_free_shipping or source.meli_free_shipping
        target.meli_local_pick_up = target.meli_local_pick_up or source.meli_local_pick_up

        target.meli_price = target.meli_price or source.meli_price
        target.meli_currency = target.meli_currency or source.meli_currency
        target.meli_condition = target.meli_condition or source.meli_condition
        target.meli_warranty = target.meli_warranty or source.meli_warranty

        #TODO: check
        target.meli_shipping_mode =  target.meli_shipping_mode or source.meli_shipping_mode
        target.meli_shipping_method =  target.meli_shipping_method or source.meli_shipping_method

        target.meli_brand = target.meli_brand or source.meli_brand
        target.meli_model = target.meli_model or source.meli_model
        target.meli_brand = source.meli_brand
        target.meli_model = source.meli_model
        if ("meli_gender" in source._fields):
            target.meli_gender = source.meli_gender
            target.meli_grid_chart_id = source.meli_grid_chart_id
        return res

    def _product_post_set_attributes( self, product_tmpl=None, product=None, meli=None, config=None ):
        attributes = []
        attributes_ids = {}
        # #532 (import ficha ML): capturar el set de atributos IMPORTADOS de MercadoLibre
        # (persistidos en meli_attributes por _meli_import_attributes) ANTES de que la lógica de
        # abajo pise ese campo con str(attributes). Se reincorporan al final (seed-merge) para los
        # ids que esta función NO computa (TREADWEAR, LINE, ITEM_CONDITION, etc.), cerrando el loop
        # import↔publish y destrabando el pre-flight de atributos obligatorios de la categoría.
        _imported_attributes_raw = product.meli_attributes if (product and "meli_attributes" in product._fields) else None
        variations_candidates = (product_tmpl and "meli_pub_as_variant" in product_tmpl._fields and product_tmpl.meli_pub_as_variant)
        att_line_ids = ("attribute_line_ids" in product_tmpl._fields and product_tmpl.attribute_line_ids)

        #binding template
        att_line_ids = att_line_ids or ("product_tmpl_id" in product_tmpl._fields and product_tmpl.product_tmpl_id.attribute_line_ids )

        # Determinar idioma del conector ML para leer traducciones correctas de valores
        # Brasil → pt_BR, Argentina → es_AR, etc.
        _COUNTRY_LANG_MAP = {
            'BR': 'pt_BR', 'AR': 'es_AR', 'MX': 'es_MX', 'CO': 'es_CO',
            'CL': 'es_CL', 'PE': 'es_PE', 'UY': 'es_UY', 'VE': 'es_VE',
            'EC': 'es_EC', 'BO': 'es_BO', 'PY': 'es_PY',
        }
        _meli_lang = None
        if config and 'country_id' in config._fields and config.country_id:
            _meli_lang = _COUNTRY_LANG_MAP.get(config.country_id.code)
        if not _meli_lang and config and 'company_id' in config._fields and config.company_id:
            _meli_lang = config.company_id.partner_id.lang
        _logger.debug("_product_post_set_attributes: using lang=%s for attribute values", _meli_lang)

        if att_line_ids:
            #_logger.info(" att_line_ids:"+str(att_line_ids))
            for at_line_id in att_line_ids:
                atname = at_line_id.attribute_id.name
                is_not_variant_attribute = at_line_id.attribute_id.create_variant!='always'
                is_not_meli_variant_attribute = at_line_id.attribute_id.meli_default_id_attribute and not at_line_id.attribute_id.meli_default_id_attribute.variation_attribute
                is_not_meli_variant_attribute = is_not_meli_variant_attribute or (at_line_id.attribute_id.meli_default_id_attribute and at_line_id.attribute_id.meli_default_id_attribute.hidden and at_line_id.attribute_id.meli_default_id_attribute.variation_attribute)
                is_meli_gtin = (at_line_id.attribute_id.meli_default_id_attribute and at_line_id.attribute_id.meli_default_id_attribute.att_id=="GTIN")
                #atributos, no variantes! solo con un valor...
                if (len(at_line_id.value_ids)==1 and (is_not_variant_attribute or is_not_meli_variant_attribute or is_meli_gtin) ):
                    # Leer el valor en el idioma del conector ML (pt_BR para Brasil, etc.)
                    atval = (at_line_id.value_ids.with_context(lang=_meli_lang).name
                             if _meli_lang else at_line_id.value_ids.name)
                    #_logger.info(atname+":"+atval)
                    if (atname=="MARCA" or atname=="BRAND"):
                        attribute = { "id": "BRAND", "value_name": atval }
                        attributes_ids[attribute["id"]] = attribute["value_name"]
                        attributes.append(attribute)
                    if (atname=="MODELO" or atname=="MODEL"):
                        attribute = { "id": "MODEL", "value_name": atval }
                        attributes_ids[attribute["id"]] = attribute["value_name"]
                        attributes.append(attribute)
                    if (atname=="GENERO" or atname=="GENDER"):
                        attribute = { "id": "GENDER", "value_name": atval }
                        attributes_ids[attribute["id"]] = attribute["value_name"]
                        attributes.append(attribute)

                    if (at_line_id.attribute_id.meli_default_id_attribute.id):
                        _att_id = at_line_id.attribute_id.meli_default_id_attribute.att_id
                        # PACKAGE_* are catalog attrs (not modifiable); remap to SELLER_PACKAGE_*
                        _PACKAGE_REMAP = {
                            "PACKAGE_HEIGHT": "SELLER_PACKAGE_HEIGHT",
                            "PACKAGE_WIDTH":  "SELLER_PACKAGE_WIDTH",
                            "PACKAGE_LENGTH": "SELLER_PACKAGE_LENGTH",
                            "PACKAGE_WEIGHT": "SELLER_PACKAGE_WEIGHT",
                        }
                        _att_id = _PACKAGE_REMAP.get(_att_id, _att_id)
                        attribute = {
                            "id": _att_id,
                            "value_name": atval
                        }
                        attributes_ids[attribute["id"]] = attribute["value_name"]
                        attributes.append(attribute)
                elif (len(at_line_id.value_ids)>1):
                    variations_candidates = True

        if product.meli_brand and len(product.meli_brand) > 0:
            attribute = { "id": "BRAND", "value_name": product.meli_brand }
            attributes_ids[attribute["id"]] = attribute["value_name"]
            attributes.append(attribute)
            #_logger.info(attributes)
            product.meli_attributes = str(attributes)

        if product.meli_model and len(product.meli_model) > 0:
            attribute = { "id": "MODEL", "value_name": product.meli_model }
            attributes_ids[attribute["id"]] = attribute["value_name"]
            attributes.append(attribute)
            #_logger.info(attributes)
            product.meli_attributes = str(attributes)

        #GRID_SIZE_ID > GUIA DE TALLES
        if (product.meli_category):
            if (product.meli_category.catalog_domain_chart_active):

                if product.meli_gender and len(product.meli_gender) > 0 and not "GENDER" in attributes_ids:
                    attribute = { "id": "GENDER", "value_name": product.meli_gender }
                    attributes_ids[attribute["id"]] = attribute["value_name"]
                    attributes.append(attribute)
                    #_logger.info("attributes:"+str(attributes))
                    product.meli_attributes = str(attributes)

                #buscar una guia de talles ok
                rjson_charts = product.meli_category.get_search_chart( meli=meli, brand=product.meli_brand, gender=product.meli_gender)
                #_logger.info("rjson_charts: " +str(rjson_charts))
                if rjson_charts:
                    rjson_charts_a = "charts" in rjson_charts and rjson_charts["charts"]
                    if rjson_charts_a:
                        for charts in rjson_charts_a:
                            #_logger.info("charts: " +str(charts))
                            self.env["mercadolibre.grid.chart"].create_chart(charts)
                            MeliCommit( self )


        if (product.meli_grid_chart_id):
            product.meli_grid_chart_id.update_attributes(product=product)
            #get_search_chart
            attribute = { "id": "SIZE_GRID_ID", "value_name": product.meli_grid_chart_id.meli_id }
            attributes_ids[attribute["id"]] = attribute["value_name"]
            attributes.append(attribute)
            #_logger.info("attributes:"+str(attributes))
            product.meli_attributes = str(attributes)

        # Seller package dimensions - required for Mercado Envíos (SELLER_PACKAGE_* attributes)
        _seller_pkg_fields = [
            ("meli_seller_package_height", "SELLER_PACKAGE_HEIGHT"),
            ("meli_seller_package_width",  "SELLER_PACKAGE_WIDTH"),
            ("meli_seller_package_length", "SELLER_PACKAGE_LENGTH"),
            ("meli_seller_package_weight", "SELLER_PACKAGE_WEIGHT"),
        ]
        for _field, _att_id in _seller_pkg_fields:
            if _att_id not in attributes_ids:
                _src = product_tmpl if hasattr(product_tmpl, _field) else product
                _val = getattr(_src, _field, None) or getattr(product, _field, None)
                if _val:
                    attribute = {"id": _att_id, "value_name": str(_val)}
                    attributes_ids[_att_id] = _val
                    attributes.append(attribute)

        if attributes:
            #_logger.info(attributes)
            product.meli_attributes = str(attributes)

        # ML business conditional: cuando SALE_FORMAT=Unidade/Unidad/Unit se requiere UNITS_PER_PACK
        # ML retorna cause_id:3709 "Preencha o campo Unidades por kit" si no se incluye
        _SALE_FORMAT_UNIT_VALS = {'unidade', 'unidad', 'unit', 'un', '1 unidade', '1 unidad', '1 unit'}
        _sale_format_attr = next((a for a in attributes if a.get('id') == 'SALE_FORMAT'), None)
        if _sale_format_attr:
            _sfval = (_sale_format_attr.get('value_name') or '').strip().lower()
            _has_units_per_pack = any(a.get('id') == 'UNITS_PER_PACK' for a in attributes)
            if _sfval in _SALE_FORMAT_UNIT_VALS and not _has_units_per_pack:
                attributes.append({"id": "UNITS_PER_PACK", "value_name": "1"})
                attributes_ids['UNITS_PER_PACK'] = "1"
                _logger.info("Auto-added UNITS_PER_PACK=1 (ML requires it when SALE_FORMAT=%s)", _sale_format_attr.get('value_name'))

        if (not variations_candidates):

            if ("sku" in product._fields and "product_id" in product._fields and config.mercadolibre_post_default_code and product.product_id and product.product_id.default_code):
                attribute = { "id": "SELLER_SKU", "value_name": product.product_id.default_code }
                attributes_ids[attribute["id"]] = attribute["value_name"]
                attributes.append(attribute)
                product.meli_attributes = str(attributes)

            if ( (("barcode" in product._fields and "product_id" in product._fields)) and config.mercadolibre_post_barcode and product.product_id and product.product_id.barcode):
                #SKU as attribute is default now
                # category-aware: solo mandar GTIN si el barcode es un EAN/GTIN válido (no un SKU)
                _cat = (("meli_category" in product._fields and product.meli_category) or product.product_id.meli_category)
                attribute = product.product_id._meli_gtin_attribute(product.product_id.barcode, _cat)
                if attribute:
                    attributes_ids[attribute["id"]] = attribute["value_name"]
                    attributes.append(attribute)
                    product.meli_attributes = str(attributes)

            if ( (("default_code" in product._fields and product.default_code)) and config.mercadolibre_post_default_code):
                #SKU as attribute is default now
                attribute = { "id": "SELLER_SKU", "value_name": product.default_code }
                attributes_ids[attribute["id"]] = attribute["value_name"]
                attributes.append(attribute)
                product.meli_attributes = str(attributes)
            if ( (("sku" in product._fields and product.sku)) and config.mercadolibre_post_default_code):
                #SKU as attribute is default now
                attribute = { "id": "SELLER_SKU", "value_name": product.sku }
                attributes_ids[attribute["id"]] = attribute["value_name"]
                attributes.append(attribute)
                product.meli_attributes = str(attributes)
            if ( (("barcode" in product._fields and not "product_id" in product._fields and product.barcode)) and config.mercadolibre_post_barcode):
                #SKU as attribute is default now
                # category-aware: solo mandar GTIN si el barcode es un EAN/GTIN válido (no un SKU)
                _cat = ("meli_category" in product._fields and product.meli_category)
                attribute = product._meli_gtin_attribute(product.barcode, _cat)
                if attribute:
                    attributes_ids[attribute["id"]] = attribute["value_name"]
                    attributes.append(attribute)
                    product.meli_attributes = str(attributes)

        # #532 SEED-MERGE: reincorporar los atributos IMPORTADOS de la ficha ML que esta función
        # NO computó (BRAND/MODEL/SKU/package ya calculados tienen prioridad: solo se agregan ids
        # que aún no estén en attributes_ids). Defensivo: cualquier error NO bloquea la publicación.
        if _imported_attributes_raw:
            try:
                import ast as _ast
                _seeded = _ast.literal_eval(_imported_attributes_raw)
                if isinstance(_seeded, (list, tuple)):
                    for _a in _seeded:
                        if not isinstance(_a, dict):
                            continue
                        _aid = _a.get("id")
                        if not _aid or _aid in attributes_ids:
                            continue
                        _aval = _a.get("value_name") or _a.get("value_id") or _a.get("values")
                        if not _aval:
                            continue
                        attributes.append(_a)
                        attributes_ids[_aid] = _aval
            except Exception:
                _logger.exception("_product_post_set_attributes: seed-merge de meli_attributes falló (no bloqueante)")

        if attributes:
            product.meli_attributes = str(attributes)

        return attributes

    def _meli_import_attributes( self, rjson_attributes, write_template=True, write_binding=True ):
        """#532 (ML → Odoo): persiste los atributos de la ficha de una publicación de MercadoLibre
        (lista cruda `rjson['attributes']` de GET /items/{id}) en el/los objeto(s) Odoo, en el formato
        que (a) se ve en la ficha (campo `meli_attributes`) y (b) se re-envía igual al publicar
        (seed-merge en `_product_post_set_attributes`).

        - Normaliza a `[{id, name?, value_id?, value_name?, values?}, ...]`, dedup por id, descartando
          atributos SIN valor (value_name/value_id/values todos vacíos → catalog/read-only sin dato).
        - Escribe el set serializado en `self` (product.product), y opcionalmente en su template y en el
          binding ML vinculado (para que se vea en las 3 fichas).
        - Además vuelca BRAND/MODEL/GENDER a los campos meli_brand/meli_model/meli_gender.
        - IDEMPOTENTE: reimportar reescribe el mismo set normalizado (no acumula ni duplica).
        Devuelve la lista normalizada (o [] si no había nada persistible)."""
        norm = []
        seen = set()
        for a in (rjson_attributes or []):
            if not isinstance(a, dict):
                continue
            aid = a.get("id")
            if not aid or aid in seen:
                continue
            entry = {"id": aid}
            if a.get("name"):
                entry["name"] = a.get("name")
            if a.get("value_id") is not None:
                entry["value_id"] = a.get("value_id")
            if a.get("value_name") is not None:
                entry["value_name"] = a.get("value_name")
            # multivaluado / estructurado (ej. values=[{id,name,struct}])
            if a.get("values"):
                entry["values"] = a.get("values")
            if entry.get("value_name") is None and entry.get("value_id") is None and not entry.get("values"):
                # atributo de catálogo sin valor asignado → no aporta al publicar, se omite
                continue
            norm.append(entry)
            seen.add(aid)

        def _apply(rec):
            if not (rec and "meli_attributes" in rec._fields):
                return
            rec.meli_attributes = str(norm)
            for _a in norm:
                _v = _a.get("value_name")
                if not _v:
                    continue
                if _a["id"] == "BRAND" and "meli_brand" in rec._fields:
                    rec.meli_brand = _v
                elif _a["id"] == "MODEL" and "meli_model" in rec._fields:
                    rec.meli_model = _v
                elif _a["id"] == "GENDER" and "meli_gender" in rec._fields:
                    rec.meli_gender = _v

        _apply(self)
        if write_template and "product_tmpl_id" in self._fields and self.product_tmpl_id:
            _apply(self.product_tmpl_id)
        if write_binding and "meli_id" in self._fields and self.meli_id and "mercadolibre.product" in self.env:
            try:
                binds = self.env["mercadolibre.product"].search([("product_id", "=", self.id)])
                for b in binds:
                    _apply(b)
            except Exception:
                _logger.exception("_meli_import_attributes: no se pudo escribir el binding ML (no bloqueante)")
        return norm

    def _meli_get_category_attributes( self, category, meli=None ):
        """GET /categories/{code}/attributes (cacheado por proceso). Devuelve la lista
        cruda de atributos de la categoría, o [] si algo falla (defensivo)."""
        catcode = category and category.meli_category_id
        if not catcode:
            return []
        catcode = str(catcode)
        if catcode in _MELI_CATEGORY_ATTRIBUTES_CACHE:
            return _MELI_CATEGORY_ATTRIBUTES_CACHE[catcode]
        rjs = []
        try:
            resp = meli.get("/categories/" + catcode + "/attributes", {'access_token': meli.access_token})
            rjs = resp.json()
            if not isinstance(rjs, list):
                _logger.warning("_meli_get_category_attributes: respuesta inesperada p/ %s: %s", catcode, rjs)
                rjs = []
        except Exception:
            _logger.exception("_meli_get_category_attributes: fallo GET /categories/%s/attributes", catcode)
            rjs = []
        _MELI_CATEGORY_ATTRIBUTES_CACHE[catcode] = rjs
        return rjs

    def _meli_preflight_missing_required_attributes( self, product=None, attributes=None, meli=None, config=None, catalog_mode=False ):
        """Pre-flight (#532): antes de publicar, resuelve los atributos OBLIGATORIOS de la
        categoría (GET /categories/{code}/attributes → tags `required` / `catalog_required`)
        y los compara con los que el producto realmente tiene armados. Devuelve la lista de
        nombres legibles de los atributos obligatorios FALTANTES (vacía = todo ok).

        100% defensivo: ante cualquier error (API caída, formato raro) devuelve [] para NO
        bloquear la publicación por un fallo del propio pre-flight."""
        try:
            product = product or self
            category = ("meli_category" in product._fields and product.meli_category) or None
            if not category or not category.meli_category_id:
                return []

            cat_atts = self._meli_get_category_attributes(category, meli=meli)
            if not cat_atts:
                return []

            # Set de atributos que el producto YA aporta (con valor no vacío)
            provided = set()
            for a in (attributes or []):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                aval = a.get("value_name") or a.get("value_id") or a.get("values")
                if aid and aval:
                    provided.add(str(aid))
            # ITEM_CONDITION se manda como body["condition"], no en la lista attributes
            if "meli_condition" in product._fields and product.meli_condition:
                provided.add("ITEM_CONDITION")
            # GTIN: si el producto tiene barcode, se considera aportado (evita falso positivo)
            if "barcode" in product._fields and product.barcode:
                provided.add("GTIN")

            missing = []
            for att in cat_atts:
                if not isinstance(att, dict):
                    continue
                tags = att.get("tags") or {}
                is_required = ("required" in tags) or (catalog_mode and ("catalog_required" in tags))
                if not is_required:
                    continue
                # atributos que ML resuelve/completa solo o que no debe cargar el usuario
                if ("read_only" in tags) or ("fixed" in tags) or ("variation_attribute" in tags):
                    continue
                if att.get("default_value"):
                    continue
                att_id = str(att.get("id") or "")
                if not att_id or att_id in provided:
                    continue
                missing.append(att.get("name") or att_id)
            return missing
        except Exception:
            _logger.exception("_meli_preflight_missing_required_attributes: fallo; no bloqueo publicación")
            return []

    def _product_post_set_images( self, product_tmpl=None, product=None, meli=None, config=None ):
        warningobj = self.env['meli.warning']
        #publicando multiples imagenes
        multi_images_ids = {}
        banner_images = config and "mercadolibre_banner" in config and config.mercadolibre_banner and "images_id" in config.mercadolibre_banner and config.mercadolibre_banner.images_id
        if (variant_image_ids(product) or template_image_ids(product) or banner_images):
            multi_images_ids = product.product_meli_upload_multi_images(meli=meli,config=config)
            #_logger.info(multi_images_ids)
            if 'status' in multi_images_ids:
                _logger.error("_product_post_set_images > "+str(multi_images_ids))
                #return warningobj.info( title='MELI WARNING', message="Error publicando imagenes", message_html="Error: "+str(("error" in multi_images_ids and multi_images_ids["error"]) or "")+" Status:"+str(("status" in multi_images_ids and multi_images_ids["status"]) or "") )
                return warningobj.info( title='MELI WARNING', message="Error publicando imagenes", message_html="Error: "+str(multi_images_ids), context = { "rjson": multi_images_ids })

        return multi_images_ids

    def _product_post_set_body( self, product_tmpl=None, product=None, meli=None, config=None, attributes=None, meli_imagen_id=None, meli_multi_imagen_id=None, productjson=None ):

        body = {
            #"title": product.meli_title or '',
            "category_id": product.meli_category.meli_category_id or '0',
            "listing_type_id": product.meli_listing_type or '0',
            "buying_mode": product.meli_buying_mode or '',
            "price": product.meli_price  or '0',
            "currency_id": product.meli_currency  or '0',
            "condition": product.meli_condition  or '',
            "available_quantity": product.meli_available_quantity  or '0',
            #"warranty": product.meli_warranty or '',
            "sale_terms": product._update_sale_terms( meli=meli, productjson=productjson, config=config ),
            #"pictures": [ { 'source': product.meli_imagen_logo} ] ,
            "video_id": product.meli_video  or '',
        }
        _title_val = ("meli_family_name" in product._fields and product.meli_family_name) or product.meli_title or ''
        if (config and "mercadolibre_user_product_seller" in config._fields ):
            if (config.mercadolibre_user_product_seller):
                body["family_name"] = _title_val
            else:
                body["title"] = _title_val
        else:
            body["title"] = _title_val
        #TODO: upgrade > body = product._validate_category_settings( body )

        bodydescription = {
            "plain_text": product.meli_description or '',
        }

        mlbanner = product.meli_mercadolibre_banner or product_tmpl.meli_mercadolibre_banner
        mlbanner = mlbanner or (config and "mercadolibre_banner" in config._fields and config.mercadolibre_banner)
        # `config` puede ser la CONFIGURACIÓN de la cuenta o, si la cuenta no tiene una
        # propia, directamente la res.company. En ese segundo caso no existe `company_id`
        # y pedirlo rompía la publicación con
        #     AttributeError: 'res.company' object has no attribute 'company_id'
        config_company = config.company_id if (config and "company_id" in config._fields) else None
        mlbanner = mlbanner or (config_company and "mercadolibre_banner" in config_company._fields and config_company.mercadolibre_banner)
        if (mlbanner):
            bodydescription = {
                "plain_text": mlbanner.get_description(product=product) or '',
            }


        #product.meli_shipping_mode and body.update({ "shipping_mode": product.meli_shipping_mode })
        #product.meli_shipping_method and body.update({ "shipping_method": product.meli_shipping_method })
        shipping = {
            "mode": "not_specified",
            #"local_pick_up": product.meli_local_pick_up, #MACK:Comentado por mientras
            #"free_shipping": product.meli_free_shipping, #MACK: Comentado por mientras
            # "methods": [],
            # "dimensions": null,
            # "tags": [],
            # "logistic_type": "not_specified",
            # "local_pick_up": false
        }
        product.meli_shipping_mode and shipping.update({"mode": product.meli_shipping_mode})
        product.meli_shipping_method and shipping.update({"methods": [{"id": product.meli_shipping_method}]})
        _days = 0
        if config:
            _days = ('mercadolibre_days_to_availability' in config._fields and config.mercadolibre_days_to_availability) or 0
            if not _days and 'company_id' in config._fields and config.company_id:
                _days = ('mercadolibre_days_to_availability' in config.company_id._fields and config.company_id.mercadolibre_days_to_availability) or 0
        if _days:
            shipping['days_to_availability'] = int(_days)
        shipping and body.update({"shipping": shipping})
        #_logger.info("shipping mode:"+str(shipping))
        # store id
        if config.mercadolibre_official_store_id:
            body["official_store_id"] = config.mercadolibre_official_store_id

        if (product.meli_id or ("conn_id" in product._fields and product.conn_id)):
            body = {
                 #"title": product.meli_title or '',
                #"buying_mode": product.meli_buying_mode or '',
                "price": product.meli_price or '0',
                #"condition": product.meli_condition or '',
                "available_quantity": product.meli_available_quantity or '0',
                #"warranty": product.meli_warranty or '',
                "sale_terms": product._update_sale_terms( meli=meli, productjson=productjson, config=config ),

                "pictures": [],
                "video_id": product.meli_video or '',
            }
            # family_name solo se puede actualizar si el User Product NO tiene ventas
            # Por seguridad, no enviamos family_name en actualizaciones
            # Solo enviamos title que es mas seguro
            if (config and "mercadolibre_user_product_seller" in config._fields ):
                if (config.mercadolibre_user_product_seller):
                    # En modo user_product, verificar si podemos actualizar family_name
                    # Solo actualizar si el producto no tiene ventas (sold_quantity == 0)
                    can_update_family_name = False
                    if productjson:
                        sold_quantity = productjson.get('sold_quantity', 0)
                        can_update_family_name = (sold_quantity == 0)

                    if can_update_family_name:
                        body["family_name"] = product.meli_family_name or product.meli_title or ''
                    # Si tiene ventas, no enviamos family_name ni title para evitar error
                else:
                    body["title"] = product.meli_family_name or product.meli_title or ''
            else:
                body["title"] = product.meli_family_name or product.meli_title or ''

            if (productjson):
                if ("attributes" in productjson):
                    if (len(attributes)):
                        dicatts = {}
                        for att in attributes:
                            dicatts[att["id"]] = att
                        attributes_ml =  productjson["attributes"]
                        x = 0
                        for att in attributes_ml:
                            if (att["id"] in dicatts):
                                attributes_ml[x] = dicatts[att["id"]]
                            else:
                                if att.get("value_id") is not None:
                                    attributes.append(att)
                                else:
                                    _logger.info("attributes SKIPPING from ML (null value_id, catalog attr):"+str(att["id"]))
                            x = x + 1

                        body["attributes"] = attributes
                    else:
                        attributes = productjson["attributes"]
                        body["attributes"] = attributes
        else:
            body["description"] = bodydescription

        if len(attributes):
            body["attributes"] = attributes

        if meli_imagen_id:
            #_logger.info("PICTURES")
            if 'pictures' in body.keys():
                body["pictures"] = [ { 'id': meli_imagen_id } ]
            else:
                body["pictures"] = [ { 'id': meli_imagen_id } ]

            if (meli_multi_imagen_id):
                if 'pictures' in body.keys():
                    if type(meli_multi_imagen_id) == dict:
                        body["pictures"] += meli_multi_imagen_id
                    elif meli_multi_imagen_id not in ['[', ']','[]']:
                        if body["pictures"]:
                            for mi in meli_multi_imagen_id:
                                body["pictures"].append(mi)
                        else:
                            body["pictures"] = meli_multi_imagen_id

            if product.meli_imagen_logo and product.meli_imagen_logo not in ('None', 'False', False, ''):
                if 'pictures' in body.keys():
                    body["pictures"] += [{'source': product.meli_imagen_logo}]
                elif  product.meli_imagen_log not in ['[', ']']:
                    body["pictures"] = [{'source': product.meli_imagen_logo}]
        else:
            imagen_producto = ""

        # MAX 12 imagenes en total (limite de MercadoLibre para la mayoria de categorias)
        # Limitamos a 10 para dejar espacio a imagenes de variaciones
        MAX_PICTURES = 10
        if body.get("pictures") and len(body["pictures"]) > MAX_PICTURES:
            body["pictures"] = body["pictures"][:MAX_PICTURES]

        # TODO: OBSOLETE check and set only if no variations
        # if (not variations_candidates):
        if (("default_code" in product._fields and product.default_code) and config.mercadolibre_post_default_code):
            body["seller_custom_field"] = product.default_code

        if ( (("sku" in product._fields and product.sku)) and config.mercadolibre_post_default_code):
            #SKU as attribute is default now
            body["seller_custom_field"] = product.sku


        if "meli_max_purchase_quantity" in product._fields and product.meli_max_purchase_quantity:
            body["sale_terms"].append({
                "id": "PURCHASE_MAX_QUANTITY",
                "value_name": str(product.meli_max_purchase_quantity)
            })

        if "meli_manufacturing_time" in product._fields and product.meli_manufacturing_time:
            body["sale_terms"].append({
                "id": "MANUFACTURING_TIME",
                "value_name": str(product.meli_manufacturing_time)
            })

        channels = []
        if channels:
            body['channels'] = channels


        return body, bodydescription

    def _meli_resolve_account(self, config=None, bind=None, bind_tpl=None):
        """Resolve a mercadolibre.account robustly.

        Legacy code did:
            account = "accounts" in config._fields and config.accounts and config.accounts[0]
        which only works when `config` is a mercadolibre.configuration. When a UI
        button invokes the method, `config` is a res.company (which has NO
        `accounts` field), so the whole expression collapses to False and the
        later `account.company_id` raises
        `AttributeError: 'bool' object has no attribute 'company_id'`.

        This helper resolves the account from (in order): an explicit
        configuration carrying accounts (legacy path, unchanged), the variant's
        own ML binding (mercadolibre.product), the explicit bind/bind_tpl args,
        the template binding (mercadolibre.product_template) and finally the
        company's mercadolibre_connections.

        Returns a mercadolibre.account recordset (possibly empty) — never a bool.
        """
        Account = self.env['mercadolibre.account']
        # 1) explicit configuration carrying accounts (legacy path, unchanged)
        if config and 'accounts' in config._fields and config.accounts:
            return config.accounts[0]
        # 2) variant binding (mercadolibre.product) of this product.product
        for rec in self:
            bindv = self.env['mercadolibre.product'].search(
                [('product_id', '=', rec.id), ('connection_account', '!=', False)], limit=1)
            if bindv.connection_account:
                return bindv.connection_account
        # 3) explicit bind / bind_tpl arguments
        if bind and 'connection_account' in bind._fields and bind.connection_account:
            return bind.connection_account
        if bind_tpl and 'connection_account' in bind_tpl._fields and bind_tpl.connection_account:
            return bind_tpl.connection_account
        # 4) template binding (mercadolibre.product_template)
        for rec in self:
            tmpl = rec.product_tmpl_id if 'product_tmpl_id' in rec._fields else rec
            bindt = self.env['mercadolibre.product_template'].search(
                [('product_tmpl_id', '=', tmpl.id), ('connection_account', '!=', False)], limit=1)
            if bindt.connection_account:
                return bindt.connection_account
        # 5) company fallback: config may itself be a res.company
        company = config if (config and config._name == 'res.company') else self.env.user.company_id
        if company and 'mercadolibre_connections' in company._fields and company.mercadolibre_connections:
            return company.mercadolibre_connections[:1]
        return Account  # empty recordset — callers must guard

    def product_meli_upload_image( self, bind_tpl=None, meli=False, config=False ):

        company = self.env.user.company_id
        config = config or company
        account = self._meli_resolve_account(config, bind_tpl=bind_tpl)
        if not account:
            return { 'status': 'error', 'message': 'no ML account for product' }
        company = account.company_id or company

        product_obj = self.env['product.product']
        product = self

        if not meli:
            meli = self.env['meli.util'].get_new_instance( account.company_id, account)
            if meli.need_login():
                return meli.redirect_login()

        first_image_to_publish = get_first_image_to_publish( product )

        if first_image_to_publish==None or first_image_to_publish==False:
            return { 'status': 'error', 'message': 'no image to upload' }
        #_logger.info("product_meli_upload_image: ")
        imagebin = base64.b64decode(first_image_to_publish)
        imageb64 = first_image_to_publish
        files = { 'file': ('image.jpg', imagebin, "image/jpeg"), }
        product_image = None
        try:
            hash = hashlib.blake2b()
            hash.update(imagebin)
            #product_image.meli_imagen_hash = hash.hexdigest()
            if (config.mercadolibre_do_not_use_first_image):
                product_image = variant_image_ids(product)[0]
                if (product_image):
                    product_image.meli_imagen_hash = hash.hexdigest()

        except:
            pass;
        #_logger.info("product_meli_upload_image: "+str(len(files)) )
        response = meli.upload("/pictures", files, { 'access_token': meli.access_token } )

        rjson = response.json()
        if ("error" in rjson):
            #raise osv.except_osv( _('MELI WARNING'), _('No se pudo cargar la imagen en MELI! Error: %s , Mensaje: %s, Status: %s') % ( rjson["error"], rjson["message"],rjson["status"],))
            return rjson
            #return { 'status': 'error', 'message': 'not uploaded'}

        if "id" not in rjson:
            _logger.error("product_meli_upload_image: ML response missing 'id': " + str(rjson))
            return {"status": "error", "message": "ML image upload response missing 'id': " + str(rjson)}

        #_logger.info( rjson )
        new_image_id = False
        if ("id" in rjson):
            #guardar id
            if not bind_tpl:
                product.write( { "meli_imagen_id": rjson["id"], "meli_imagen_link": rjson["variations"][0]["url"] })
                if (product_image):
                    product_image.meli_imagen_id = rjson["id"]
                    product_image.meli_imagen_link = rjson["variations"][0]["secure_url"]
                    product_image.meli_imagen_size = rjson["variations"][0]["size"]
            #asociar imagen a producto
                if product.meli_id:
                    return rjson["id"]
                #response = meli.post("/items/"+product.meli_id+"/pictures", { 'id': rjson["id"] }, { 'access_token': meli.access_token } )
                else:
                    return {'status': 'warning', 'message': 'uploaded but not assigned', 'new_image_id': new_image_id}

            new_image_id = rjson['id']

        return {'status': 'success', 'message': 'uploaded and assigned', 'new_image_id': new_image_id}

    def _product_set_variations(self, product_tmpl=None, product=None, bind_tpl=None, meli=None, config=None, attributes=None, productjson=None, body=None, bodydescription=None, image_data=None):
        """
        Configura las variaciones del producto para MercadoLibre.

        @param image_data: dict retornado por _collect_and_upload_images_for_meli.
                          Si se proporciona, se usara para asignar imagenes especificas
                          a cada variante segun su atributo (ej: Color).
        """
        warningobj = self.env['meli.warning']
        source = product_tmpl
        target = product
        meli_id = (bind_tpl and bind_tpl.conn_id) or product.meli_id

        # user_product_seller family_name flow: esta variante se publica como
        # listing independiente — no armar variations[] en el body.
        # Sí se agregan los atributos de combinación (COLOR, SIZE, etc.) como
        # atributos regulares para que figuren en la publicación de la variante.
        if self.env.context.get('family_name_variant_post'):
            _logger.info("user_product_seller family_name flow: skipping variations for variant %s", product)
            _COUNTRY_LANG_MAP = {
                'BR': 'pt_BR', 'AR': 'es_AR', 'MX': 'es_MX', 'CO': 'es_CO',
                'CL': 'es_CL', 'PE': 'es_PE', 'UY': 'es_UY', 'VE': 'es_VE',
                'EC': 'es_EC', 'BO': 'es_BO', 'PY': 'es_PY',
            }
            _meli_lang = None
            if config and 'country_id' in config._fields and config.country_id:
                _meli_lang = _COUNTRY_LANG_MAP.get(config.country_id.code)
            if not _meli_lang and config and 'company_id' in config._fields and config.company_id:
                _meli_lang = config.company_id.partner_id.lang
            # Atributos ya presentes en el body (para no duplicar)
            _existing_ids = {att["id"] for att in (body.get("attributes") or [])}
            _variant_attrs = []
            for ptav in att_value_ids(product):
                if (ptav.attribute_id.meli_default_id_attribute
                        and ptav.attribute_id.meli_default_id_attribute.variation_attribute
                        and ptav.attribute_id.meli_default_id_attribute.att_id):
                    _att_id = ptav.attribute_id.meli_default_id_attribute.att_id
                    if _att_id not in _existing_ids:
                        _val = ptav.with_context(lang=_meli_lang).name if _meli_lang else ptav.name
                        _variant_attrs.append({"id": _att_id, "value_name": _val})
                        _existing_ids.add(_att_id)
            if _variant_attrs:
                body.setdefault("attributes", [])
                body["attributes"] = body["attributes"] + _variant_attrs
                _logger.info("family_name_variant_post: added variant combination attrs: %s", _variant_attrs)
            return body

        #product_tmpl = "" in source._fields
        if (product_tmpl.meli_pub_as_variant):
            #es probablemente la variante principal
            if (product_tmpl.meli_pub_principal_variant and product_tmpl.meli_pub_principal_variant.id):
                #esta definida la variante principal, veamos si es esta
                if (product_tmpl.meli_pub_principal_variant.id == product.id):
                    # esta es la variante principal, si aun el producto no se publico
                    # preparamos las variantes

                    # product_json is Product Json from ML
                    if ( productjson and "variations" in productjson and len(productjson["variations"]) ):
                        #ya hay variantes publicadas en ML
                        body_varias = {
                            "title": body["title"],
                            "pictures": body["pictures"],
                            "attributes": attributes or ("attributes" in body and body["attributes"]),
                            "variations": []
                        }

                        #TODO: add pictures from real variant images
                        var_pics = []
                        var_pics_full = []

                        if ( len(body["pictures"]) ):
                            if (type(body["pictures"])==list):

                                for pic in body["pictures"]:
                                    ret = {'error': "Imagen sin Id revisar: pic: "+str(pic)}
                                    if 'id' in pic:
                                        var_pics.append(pic['id'])
                                        var_pics_full.append({ 'id': pic['id']})
                                    else:
                                        _logger.error("Revisar body pictures"+ str( pretty_json(body["pictures"]) ) )
                                        return ret
                            else:
                                if type(body["pictures"])==str or type(body["pictures"])==dict:
                                    ret = {'error': "Formato de imagenes a revisar: "+str(body["pictures"])}
                                    return ret

                        #_logger.info("Variations already posted, must update them only")
                        vars_updated = self.env["product.product"]
                        for ix in range(len(productjson["variations"]) ):
                            var_info = productjson["variations"][ix]
                            #_logger.info("Variation to update!!")
                            #_logger.info(var_info)
                            var_product = None
                            var_pics = []
                            # Usar las imagenes del template como base para las variaciones
                            # Esto evita exceder el limite de 12 imagenes de MercadoLibre
                            template_pic_ids = [pic['id'] for pic in body["pictures"] if 'id' in pic]
                            for pvar in product_tmpl.product_variant_ids:
                                if (pvar._is_product_combination(var_info)):
                                    var_product = pvar
                                    #upgrade variant stock
                                    var_product.meli_available_quantity = var_product._meli_available_quantity(meli=meli,config=config)

                                    # Asignar imagenes segun el nuevo sistema (si image_data esta disponible)
                                    # o usar template images como fallback
                                    if image_data:
                                        var_pics = product_tmpl._get_variation_picture_ids(pvar, image_data)
                                    else:
                                        var_pics = template_pic_ids.copy()
                                    var_pics_full = [{ 'id': pic_id } for pic_id in var_pics]

                                    var_attributes = var_product._update_sku_attribute( attributes=("attributes" in var_info and var_info["attributes"]) or [],
                                                                                        set_sku=config.mercadolibre_post_default_code,
                                                                                        set_barcode=config.mercadolibre_post_barcode,
                                                                                        var_info=var_info)

                                    vars_updated+= var_product

                            # Limit variation pictures to 10 (MercadoLibre API limit per variation)
                            if var_pics and len(var_pics) > 10:
                                var_pics = var_pics[:10]

                            if not var_product:
                                verb = ""
                                for pvar in product_tmpl.product_variant_ids:
                                    verb+= " ##"+str(pvar) + " >>> " + str(pvar._is_product_combination( var_info, verbose=True ) )

                                ret = {'error': "No se pudo asociar la combinacion con alguna variante: "+str(var_info)+verb}
                                _logger.error(ret)
                                return ret

                            var = {
                                "id": str(var_info["id"]),
                                "price": (bind_tpl and bind_tpl.meli_price) or str(product_tmpl.meli_price),
                                "available_quantity": var_product and var_product.meli_available_quantity,
                                "picture_ids": var_pics,
                                #resend the same combination just bc of grid size
                                #"attribute_combinations": var_info["attribute_combinations"]
                            }
                            var_attributes and var.update({"attributes": var_attributes })
                            body_varias["variations"].append(var)
                            body_varias["pictures"] = var_pics_full

                        # Pasar las imagenes del template para nuevas variaciones
                        # Si tenemos image_data, usarlo para asignar imagenes especificas por variante
                        _all_variations = product_tmpl._variations(meli=meli, config=config, template_pic_ids=template_pic_ids, image_data=image_data)
                        _logger.info("_all_variations:"+str(_all_variations))

                        _updated_ids = vars_updated.mapped('id')
                        _logger.info("_updated_ids:"+str(_updated_ids))

                        _new_candidates = product_tmpl.product_variant_ids.filtered(lambda pv: pv.id not in _updated_ids)
                        _logger.info("_new_candidates:"+str(_new_candidates))

                        if _all_variations:
                            for aix in range(len(_all_variations)):
                                var_info = _all_variations[aix]
                                for pvar in _new_candidates:
                                    if (pvar._is_product_combination(var_info)):
                                        var_attributes = pvar._update_sku_attribute( attributes=("attributes" in var_info and var_info["attributes"]), set_sku=config.mercadolibre_post_default_code, var_info=var_info )
                                        var_attributes and var_info.update({"attributes": var_attributes })

                                        #body_varias se actualiza
                                        body_varias["variations"].append(var_info)

                                        _logger.info("news:")
                                        _logger.info(var_info)

                        import pprint
                        formatted_json_str = pprint.pformat(body_varias)
                        _logger.info("body_varias (N var):"+str(formatted_json_str))
                        for pic in body_varias["pictures"]:
                            idpic = pic["id"]
                            for var in body_varias["variations"]:
                                for picid in var["picture_ids"]:
                                    if (picid==idpic):
                                        _logger.info("FOUNDED! "+str(pic))

                        responsevar = meli.put_mini("/items/"+str(meli_id), body_varias, {'access_token':meli.access_token})
                        rjsonv = responsevar.json()
                        #_logger.info(rjsonv)
                        if ("error" in rjsonv):
                            error_msg = 'MELI RESP.: <h6>Mensaje de error</h6><br/><h6>Mensaje</h6> %s<br/><h6>Status</h6> %s<br/><h6>Cause</h6> %s<br/><h7>Error completo:</h7><span>%s</span><br/>' % (rjsonv["message"], rjsonv["status"], rjsonv["cause"], rjsonv["error"])
                            _logger.error(error_msg)
                            if (rjsonv["error"]=="forbidden"):
                                url_login_meli = meli.auth_url()
                                return warningobj.info( title='MELI WARNING', message="Debe iniciar sesión en MELI con el usuario correcto.", message_html="<br><br>"+error_msg, context = { "rjson": rjsonv })
                            else:
                                return warningobj.info( title='MELI WARNING', message="Completar todos los campos y revise el mensaje siguiente.", message_html="<br><br>"+error_msg, context = { "rjson": rjsonv })


                        #verifica combinaciones in re-asigna id de variation
                        #if ("variations" in rjsonv):
                        #    for ix in range(len(rjsonv["variations"]) ):
                        #        _var = rjsonv["variations"][ix]
                        #        for pvar in product_tmpl.product_variant_ids:
                        #            if (pvar._is_product_combination(_var) and 'id' in _var):
                        #                pvar.meli_id = productjson["id"]
                        #                pvar.meli_id_variation = _var["id"]
                        #                pvar.meli_price = str(_var["price"])

                        #_logger.debug(responsevar.json())
                        #resdes = meli.put("/items/"+product.meli_id+"/description", bodydescription, {'access_token':meli.access_token})
                        #_logger.debug(resdes.json())
                        del body['pictures']
                        del body['price']
                        del body['available_quantity']
                        #resbody = meli.put("/items/"+product.meli_id, body, {'access_token':meli.access_token})
                        return body

                        #_logger.debug(resbody.json())
                         #responsevar = meli.put("/items/"+product.meli_id, {"initial_quantity": product.meli_available_quantity, "available_quantity": product.meli_available_quantity }, {'access_token':meli.access_token})
                         #_logger.debug(responsevar)
                         #_logger.debug(responsevar.json())

                    else:
                        #first variations post
                        # Pasar las imagenes del template para que las variaciones las usen
                        # Esto evita exceder el limite de 12 imagenes de MercadoLibre
                        # Si tenemos image_data, usarlo para asignar imagenes especificas por variante
                        template_pic_ids = [pic['id'] for pic in body["pictures"] if 'id' in pic]
                        variations = product_tmpl._variations(meli=meli, config=config, template_pic_ids=template_pic_ids, image_data=image_data)
                        #_logger.info("Variations:")
                        #_logger.info(variations)
                        if (variations):
                            body["variations"] = []
                            for var in variations:
                                var["price"] = (bind_tpl and bind_tpl.meli_price) or str(product_tmpl.meli_price)
                                body["variations"].append(var)

                            _logger.info("body_varias (N var):"+str(pretty_json(body["variations"])))
                else:
                    _logger.debug("Variant not able to post, variant principal.")
                    return {}
            else:
                _logger.debug("Variant principal not defined yet. Cannot post.")
                return {}
        else:
            #caso 1 sola combinacion, se trata especialmente
            if ( productjson and "variations" in productjson and productjson["variations"] and len(productjson["variations"])==1 ):
                body_varias = {
                    "title": body["title"],
                    "pictures": body["pictures"],
                    "variations": []
                }
                var_pics = []
                if (len(body["pictures"])):
                    for pic in body["pictures"]:
                        var_pics.append(pic['id'])
                # Limit variation pictures to 10 (MercadoLibre API limit per variation)
                if var_pics and len(var_pics) > 10:
                    var_pics = var_pics[:10]
                #_logger.info("Single variation already posted, must update it")

                #update variations structure for: "attributes" (SELLER_SKU, GTIN), "stock", "price", and "pictures"
                for ix in range(len(productjson["variations"]) ):
                    #_logger.info("Variation to update!!")
                    #_logger.info(productjson["variations"][ix])
                    var_info = productjson["variations"][ix]
                    var = {
                        "id": str(productjson["variations"][ix]["id"]),
                        "price": str(product_tmpl.meli_price),
                        "available_quantity": product.meli_available_quantity,
                        "picture_ids": var_pics
                    }
                    var_attributes = product._update_sku_attribute( attributes=("attributes" in var_info and var_info["attributes"]), set_sku=config.mercadolibre_post_default_code, var_info=var_info )
                    var_attributes and var.update({"attributes": var_attributes })
                    body_varias["variations"].append(var)

                    #WARNING: only for single variation
                    if not bind_tpl:
                        product.meli_id_variation = productjson["variations"][ix]["id"]
                    else:
                        bind_tpl.conn_variation_id = productjson["variations"][ix]["id"]
                        if bind_tpl.variant_bindings:
                            bind_tpl.variant_bindings[0].conn_id = productjson["id"]
                            bind_tpl.variant_bindings[0].conn_variation_id = productjson["variations"][ix]["id"]

                _logger.info("body_varias (1 var):"+str(pretty_json(body_varias)))
                responsevar = meli.put_mini("/items/"+str(meli_id), body_varias, {'access_token':meli.access_token})
                #_logger.info(responsevar.json())
                #_logger.debug(responsevar.json())
                #resdes = meli.put("/items/"+product.meli_id+"/description", bodydescription, {'access_token':meli.access_token})
                #_logger.debug(resdes.json())
                del body['pictures']
                del body['price']
                del body['available_quantity']
                #resbody = meli.put("/items/"+product.meli_id, body, {'access_token':meli.access_token})
                #return {}
        return body

    ## special _product_post   that accept a binding variant as parameter to post...
    #
    # @param bind_tpl binded template; used when posting an alternative derived binded publication (not the base product)
    # @param bind  binded variant; specify the variant binding
    def _product_post( self, bind_tpl=None, bind=None, meli=None, config=None ):

        warningobj = self.env['meli.warning']
        context = self.env.context
        #import pdb;pdb.set_trace();
        #_logger.info('[DEBUG] MercadoLibre Bind _product_post: ')
        #_logger.info("self.env.context:" + str(context))
        force_meli_new_pub = context.get("force_meli_new_pub")
        force_meli_new_price = context.get("force_meli_new_price")
        force_meli_new_pricelist = context.get("force_meli_new_pricelist")
        force_meli_new_title = context.get("force_meli_new_title")
        force_meli_listing_type = context.get("force_meli_listing_type")

        #_logger.info("self.env.context force_meli_new_pub:" + str(force_meli_new_pub))

        #binded title setting (use name or meli_title)
        if bind_tpl:
            bind_tpl.meli_title = force_meli_new_title or bind_tpl.meli_title or bind_tpl.name
            bind_tpl.meli_listing_type = force_meli_listing_type or bind_tpl.meli_listing_type
            if bind:
                bind.name = bind_tpl.name
                bind.meli_title = bind_tpl.meli_title
            #_logger.info("bind_tpl.meli_title: "+str(bind_tpl.meli_title))

        if bind:
            bind.meli_title = force_meli_new_title or bind.meli_title or bind.name
            bind.meli_listing_type = force_meli_listing_type or bind.meli_listing_type
            #_logger.info("bind.meli_title: "+str(bind.meli_title))

        if bind_tpl:
            bind_tpl.meli_title = force_meli_new_title or bind_tpl.meli_title or bind_tpl.name
            #_logger.info("bind_tpl.meli_title: "+str(bind_tpl.meli_title))

        www_cats = False
        if 'product.public.category' in self.env:
            www_cats = self.env['product.public.category']

        product_obj = self.env['product.product']
        product_tpl_obj = self.env['product.template']
        product = (bind and bind.product_id) or self
        product_tmpl = product and product.product_tmpl_id
        company = self.env.user.company_id
        if not config:
            config = company
        warningobj = self.env['meli.warning']

        if not meli:
            account = self._meli_resolve_account(config, bind=bind, bind_tpl=bind_tpl)
            meli = self.env['meli.util'].get_new_instance( account.company_id, account)
            if meli.need_login():
                return meli.redirect_login()

        #import pdb;pdb.set_trace();
        #_logger.info('[DEBUG] product_post')
        #_logger.info("self.env.context:" + str(self.env.context))

        www_cats = False
        if 'product.public.category' in self.env:
            www_cats = self.env['product.public.category']

        product_obj = self.env['product.product']
        product_tpl_obj = self.env['product.template']
        product = self
        product_tmpl = self.product_tmpl_id
        company = self.env.user.company_id
        if not config:
            config = company
        warningobj = self.env['meli.warning']

        account = bind and bind.connection_account
        company = (account and account.company_id) or company
        config = config or (account and account.configuration) or company

        if not meli:
            account = self._meli_resolve_account(config, bind=bind, bind_tpl=bind_tpl)
            meli = self.env['meli.util'].get_new_instance( account.company_id, account)
            if meli.need_login():
                return meli.redirect_login()

        #return {}
        #description_sale =  product_tmpl.description_sale
        #translation = self.env['ir.translation'].search([('res_id','=',product_tmpl.id),
        #                                                ('name','=','product.template,description_sale'),
        #                                                ('lang','=','es_AR')])
        #if translation:
            #_logger.info("translation")
            #_logger.info(translation.value)
        #    description_sale = translation.value
        description_sale = product_tmpl.description_sale or ""

        productjson = False

        #meli_id, id of the ML publication destination, if None, create a new publication
        if force_meli_new_pub:
            meli_id = None
        else:
            meli_id = (bind and bind.conn_id) or (bind_tpl and bind_tpl.conn_id) or product.meli_id

        #_logger.info("_product_post meli_id is: "+str(meli_id))

        if (meli_id):
            response = meli.get("/items/%s" % str(meli_id), {'access_token':meli.access_token})
            if (response):
                productjson = response.json()

        #product_json is the data json Object from ML, use this data to update

        #translate everything to be compatible with bindings parameters
        #.....
        #se traduce muchos product. por bind.
        #luego se toman ciertos datos de product. y se los pasa a bind.
        #funcion que pasa entonces todos los parametros necesarios de product. a bind. (los seleccionados/clasicos por el usuario??)

        self._product_post_set_basic_configuration( product_tmpl=product_tmpl, bind_tpl=bind_tpl, meli=meli, config=config )

        source = product_tmpl
        target = product

        if bind_tpl and bind:
            #Cascading template configurations
            #_logger.info("Setting binding template from product template.")
            #aqui no forzamos el force_source_description para que cada publicacion pueda tener su propia descripcion
            res = self._product_post_set_template_configuration( source=product_tmpl, target=bind_tpl, meli=meli, config=config, force_source_description=False )
            #_logger.info("Setting binding variant from binding template.")
            res = self._product_post_set_template_configuration( source=bind_tpl, target=bind, meli=meli, config=config )

            #match for vpub as variant
            bind_tpl.meli_pub_as_variant = product_tmpl.meli_pub_as_variant
            bind_tpl.meli_pub_principal_variant = product_tmpl.meli_pub_principal_variant
            #bind_tpl.meli_pub_principal_variant = source.meli_pub_principal_variant
            bind_tpl.meli_pub_variant_attributes = product_tmpl.meli_pub_variant_attributes

            source = bind_tpl
            target = bind
        else:
            res = self._product_post_set_template_configuration( source=product_tmpl, target=product, meli=meli, config=config )

        #_logger.info("source: "+str(source)+str(source.display_name)+" target: "+str(target)+str(target.name))
        self._product_post_set_title( meli_title=force_meli_new_title, source_tmpl=source, target=target, meli=meli, config=config )

        #revisar regla e precio
        product and product.set_meli_price( meli=meli, config=config)
        #target.price = product.meli_price
        if force_meli_new_price and target and target.meli_currency!="MXN":
            force_meli_new_price = str(int(float(force_meli_new_price)))
        #_logger.info("force_meli_new_price: "+str(force_meli_new_price))
        self._product_post_set_price( meli_price=force_meli_new_price, meli_pricelist=force_meli_new_pricelist, source_tmpl=source, target=target, meli=meli, config=config )
        #_logger.info("source.meli_price: "+str(source and source.meli_price))
        #_logger.info("target.meli_price: "+str(target and target.meli_price))

        attributes = self._product_post_set_attributes( product_tmpl=source, product=target, meli=meli, config=config )
        #_logger.info("attributes: "+str(attributes))
        self._product_post_set_category( product_tmpl=source, product=target, meli=meli, config=config )

        if not target.meli_category:
            return warningobj.info( title='MELI WARNING', message="Debe seleccionar una Categoría de MercadoLibre antes de publicar. Usá el botón 'Sugerir Categoría' en la pestaña MercadoLibre del producto para que MercadoLibre proponga una según el título, o elegila manualmente.", message_html="<p>El producto no tiene una categoría de MercadoLibre asignada. Usá el botón <strong>'Sugerir Categoría'</strong> (pestaña MercadoLibre del producto) para que ML proponga una a partir del título, o seleccioná una manualmente.</p>" )

        meli_id = target.meli_id or ("conn_id" in target._fields and target.conn_id)
        #if meli_id is false, publish on base product

        # PRE-FLIGHT #532: en la CREACIÓN (sin meli_id), verificar que estén los atributos
        # OBLIGATORIOS de la categoría ANTES de pegarle a ML. Si faltan, cortamos con un aviso
        # humanizado/estilado (rojo) listando los faltantes por su nombre, en vez de dejar que
        # ML devuelva el críptico build-title "attributes are required".
        if not meli_id:
            _catalog_mode = bool(config and "mercadolibre_user_product_seller" in config._fields and config.mercadolibre_user_product_seller)
            _missing_required = self._meli_preflight_missing_required_attributes(
                product=target, attributes=attributes, meli=meli, config=config, catalog_mode=_catalog_mode )
            if _missing_required:
                _missing_txt = ", ".join([str(x) for x in _missing_required])
                _logger.warning("PRE-FLIGHT #532: faltan atributos obligatorios de la categoría %s: %s",
                                target.meli_category.meli_category_id, _missing_txt)
                _preflight_rjson = {
                    "error": "missing_required_attributes",
                    "status": "400",
                    "message": "No se pudo publicar: faltan atributos obligatorios de la categoría",
                    "cause": [{
                        "type": "error",
                        "code": "item.attributes.missing_required",
                        "message": ("Para publicar faltan estos atributos obligatorios de la categoría: %s. "
                                    "Completá la ficha técnica del producto (pestaña MercadoLibre) y volvé a publicar." % _missing_txt),
                    }],
                }
                self.env.cr.rollback()
                return warningobj.info(
                    title='MELI WARNING',
                    message=("Para publicar faltan estos atributos obligatorios de la categoría: %s. "
                             "Completá la ficha técnica del producto en la pestaña MercadoLibre." % _missing_txt),
                    message_html="",
                    context={'rjson': _preflight_rjson} )

        self._product_post_set_quantity( target=target, product=product, meli_id=meli_id, meli=meli, config=config )

        #TODO: publicando imagenes
        first_image_to_publish = get_first_image_to_publish( product )
        #if (productjson and "pictures" in productjson):
        #    product._meli_remove_images_unsync( product_tmpl, productjson["pictures"] )

        if first_image_to_publish==None:
            raise ValidationError("Debe cargar una imagen de base en el producto, si chequeo el 'Dont use first image' debe al menos poner una imagen adicional en el producto.")
            #return warningobj.info( title='MELI WARNING', message="Debe cargar una imagen de base en el producto, si chequeo el 'Dont use first image' debe al menos poner una imagen adicional en el producto.", message_html="" )
        else:
            # #_logger.info( "try uploading image..." )
            resim = product.product_meli_upload_image( bind_tpl=bind_tpl, meli=meli, config=config )
            #_logger.info("resim: " +str(resim))
            if "status" in resim:
                if (resim["status"]=="error" or resim["status"]=="warning"):
                    error_msg = 'MELI: mensaje de error:   ', resim
                    _logger.error(error_msg)
                    if (resim["status"]=="error"):
                        #raise ValidationError("Problemas cargando la imagen principal. Imagen principal faltante.")
                        self.env.cr.rollback()
                        return warningobj.info( title='MELI WARNING', message="Problemas cargando la imagen principal.", message_html=error_msg, context= { 'rjson': resim } )
                else:
                    assign_img = True and product.meli_imagen_id

                if 'new_image_id' in resim and bind:
                    bind.meli_imagen_id = resim['new_image_id']
                    _logger.info("bind.meli_imagen_id mack: " + str(bind.meli_imagen_id))
            if bind and not bind.meli_imagen_id:
                bind.meli_imagen_id = product.meli_imagen_id
                #_logger.info("bind.meli_imagen_id: " +str(bind.meli_imagen_id))

        meli_imagen_id = (bind and bind.meli_imagen_id) or product.meli_imagen_id
        #FIN IMAGEN PRINCIPAL

        #publicando multiples imagenes: TODO use bind images
        multi_images_ids = {}
        image_data = None  # Nuevo: datos de imagenes con mapeo por variante
        banner_images = config and "mercadolibre_banner" in config and config.mercadolibre_banner and "images_id" in config.mercadolibre_banner and config.mercadolibre_banner.images_id

        # Usar nuevo sistema de imagenes cuando se publican variantes
        # Esto permite asignar imagenes especificas a cada variante (ej: por color)
        use_new_image_system = product_tmpl.meli_pub_as_variant and len(product_tmpl.product_variant_ids) > 1

        if use_new_image_system:
            # Nuevo sistema: recolectar y subir todas las imagenes con mapeo por variante
            _logger.info("Using new image system for variant publication")
            image_data = product_tmpl._collect_and_upload_images_for_meli(meli=meli, config=config)
            if image_data and image_data.get('all_pictures'):
                # Usar las imagenes recolectadas
                meli_imagen_id = image_data['all_pic_ids'][0] if image_data['all_pic_ids'] else None
                multi_images_ids = image_data['all_pictures'][1:] if len(image_data['all_pictures']) > 1 else []
                _logger.info("Image data collected: %d images, variant_map: %s",
                           len(image_data['all_pic_ids']), list(image_data.get('variant_pic_map', {}).keys()))
            else:
                _logger.warning("New image system returned no images, falling back to legacy")
                image_data = None
                use_new_image_system = False

        if not use_new_image_system:
            # Sistema legacy
            if (variant_image_ids(product) or template_image_ids(product) or banner_images):
                multi_images_ids = product.product_meli_upload_multi_images(meli=meli,config=config)
                #_logger.info("_product_post >> multi_images_ids"+str(multi_images_ids))
                if 'status' in multi_images_ids:
                    _logger.error("product_meli_upload_multi_images > "+str(multi_images_ids) )
                    self.env.cr.rollback()
                    #return warningobj.info( title='MELI WARNING', message="Error publicando imagenes", message_html="Error: "+str(("error" in multi_images_ids and multi_images_ids["error"]) or "")+" Status:"+str(("status" in multi_images_ids and multi_images_ids["status"]) or "") )
                    return warningobj.info( title='MELI WARNING', message="Error publicando imagenes", message_html="Error: "+str(multi_images_ids), context = { 'rjson': multi_images_ids } )
                    #raise ValidationError("Error publicando multiples imagenes")


        meli_multi_imagen_id = multi_images_ids
        #or product.meli_multi_imagen_id

        #FIN IMAGENES PRINCIPAL

        body, bodydescription = self._product_post_set_body( product_tmpl=source, product=target, meli=meli, config=config,
                                                             attributes=attributes,
                                                             meli_imagen_id=meli_imagen_id,
                                                             meli_multi_imagen_id=meli_multi_imagen_id,
                                                             productjson=productjson )

        # Si usamos el nuevo sistema, actualizar body["pictures"] con todas las imagenes
        if use_new_image_system and image_data and image_data.get('all_pictures'):
            body["pictures"] = image_data['all_pictures']

        #if target
        body = self._product_set_variations( product_tmpl=product_tmpl,
                                                product=product,
                                                bind_tpl=bind_tpl,
                                                meli=meli,
                                                config=config,
                                                attributes=attributes,
                                                productjson=productjson,
                                                body=body,
                                                image_data=image_data,
                                                bodydescription=bodydescription )

        if not body or (body and 'error' in body):
            error_msg =  str(body)
            rjson = body
            return warningobj.info( title='MELI WARNING', message="Error posible de combinaciones", message_html="<br><br>"+error_msg, context = { 'rjson': rjson } )


        # ML rejects family_name together with variations[]
        # - user_product_seller: family_name required, variations[] prohibited -> remove variations
        # - regular account: title required, family_name should not be present -> switch to title
        if body.get("variations") and "family_name" in body:
            _is_ups = config and 'mercadolibre_user_product_seller' in config._fields and config.mercadolibre_user_product_seller
            if _is_ups:
                del body["variations"]
                _logger.info("user_product_seller: removed variations (incompatible with family_name) — secondary variants posted as separate listings")
            else:
                body["title"] = body.pop("family_name")
                _logger.info("non-user_product_seller: family_name switched to title for variations")

        if 1==1:
            _logger.info("Info to post:")
            _logger.info(pretty_json(body))
        if meli_id:
            #_logger.info("update post:"+str(body))
            response = meli.put_mini("/items/"+str(meli_id), body, {'access_token':meli.access_token})
        else:
            assign_img = True and product.meli_imagen_id
            #_logger.info("first post:" + str(body)+" meli: login_id: "+str(meli.meli_login_id)+" client_id: "+str(meli.client_id)+" seller_id: "+str(meli.seller_id)+" access_token: "+str(meli.access_token))
            response = meli.post("/items", body, {'access_token':meli.access_token})

        rjson = response.json()
        #_logger.info("rjson after post:"+str(rjson))

        #check error
        if "error" in rjson:
            #error_msg = '<h6>Mensaje de error de MercadoLibre: %s; status: %s </h6><h2>Mensaje: %s</h2><br/><h6>Cause: </h6> %s' % (rjson["error"], rjson["status"], rjson["message"], rjson["cause"])
            error_msg = '<h6>Mensaje de error de MercadoLibre</h6><br/><h2>Mensaje: %s</h2><br/><h6>Status</h6> %s<br/><h6>Cause</h6> %s<br/><h6>Error completo:</h6><br/><span>%s</span><br/>' % (rjson.get("message"), rjson.get("status"), rjson.get("cause"), rjson.get("error"))
            _logger.error(error_msg)
            _cause = rjson.get("cause")
            if isinstance(_cause, list) and _cause and isinstance(_cause[0], dict) and "message" in _cause[0]:
                error_msg+= '<h3>'+str(_cause[0]["message"])+'</h3>'
            elif _cause:
                error_msg+= '<h3>'+str(_cause)+'</h3>'
            #expired token
            if "message" in rjson and (rjson["error"]=="forbidden" or rjson["message"]=='invalid_token' or rjson["message"]=="expired_token"):
                url_login_meli = meli.auth_url()
                self.env.cr.rollback()
                #raise ValidationError("Debe iniciar sesión en MELI:  "+str(rjson["message"]))
                return warningobj.info( title='MELI WARNING', message="Debe iniciar sesión en MELI:  "+str(rjson["message"]), message_html="<br><br>"+error_msg, context = { 'rjson': rjson })
            else:
                #Any other errors
                self.env.cr.rollback()
                #raise ValidationError("Recuerde completar todos los campos y revise el mensaje siguiente."+str(error_msg))
                return warningobj.info( title='MELI WARNING', message="Recuerde completar todos los campos y revise el mensaje siguiente.", message_html="<br><br>"+error_msg, context = { 'rjson': rjson } )

        #last modifications if response is OK
        if "id" in rjson:
            otros_errores = []
            meli_id = rjson["id"]

            #vuelve a traer el registro completo formateandolo con barcode y sku
            rjson = account and account.fetch_meli_product( meli_id=meli_id, meli=meli ) or self.env["mercadolibre.account"].fetch_meli_product( meli_id=meli_id, meli=meli ) or rjson

            if meli_id and bodydescription:
                resdescription = meli.put_mini("/items/"+str(meli_id)+"/description", bodydescription, {'access_token':meli.access_token})
                rjsondes = resdescription.json()

                if "error" in rjsondes:
                    _logger.info("error posteando descripcion: ")
                    _logger.info("rjson descripcion: "+str(rjsondes))
                    #self.env.cr.rollback()
                    otros_errores.append(rjsondes)
                    #return warningobj.info( title='MELI WARNING', message="Error en la descripción", message_html="", context = { 'rjson': rjsondes })

            _logger.info("Posted Ok! meli_id: "+str(meli_id))

            # Extraer family_id del response (ML lo devuelve como {"family": {"id": "..."}} o "family_id")
            _family_id = None
            if "family" in rjson and isinstance(rjson["family"], dict):
                _family_id = rjson["family"].get("id")
            elif "family_id" in rjson:
                _family_id = rjson["family_id"]

            if bind and bind_tpl:
                _logger.info("Last updates: binded publication: bind_tpl > "+str(bind_tpl))
                _bind_tpl_vals = {'conn_id': rjson["id"]}
                if _family_id:
                    _bind_tpl_vals['meli_family_id'] = _family_id
                bind_tpl.write(_bind_tpl_vals)
                _bind_vals = {'meli_id': rjson["id"], 'conn_id': rjson["id"]}
                if _family_id:
                    _bind_vals['meli_family_id'] = _family_id
                bind.write(_bind_vals)
                MeliCommit( self )
                #WARNING IF NEW PUB with variants, must call product_template_rebind, to create all variant binding too
            else:
                _logger.info("Last updates: base product publication target:"+str(target))
                _target_vals = {'meli_id': rjson["id"]}
                if _family_id:
                    _target_vals['meli_family_id'] = _family_id
                # family_name flow: listing propio sin variation ID — limpiar valores residuales
                if self.env.context.get('family_name_variant_post') and target.meli_id_variation:
                    _target_vals['meli_id_variation'] = False
                    _logger.info("user_product_seller family_name: clearing stale meli_id_variation for %s", target)
                target.write(_target_vals)
                MeliCommit( self )
                #TODO: check variations
                if ("variations" in rjson):
                    #_logger.info("Check variations:"+str(len(rjson["variations"])))
                    for ix in range(len(rjson["variations"]) ):
                        _var = rjson["variations"][ix]
                        for pvar in product_tmpl.product_variant_ids:
                            if (pvar._is_product_combination(_var) and 'id' in _var):
                                pvar.meli_id_variation = _var["id"]
                                pvar.meli_id = rjson["id"]

        if bind and bind_tpl:
            rebind_needed = bind_tpl.variant_bindings and product_tmpl.product_variant_ids and len(bind_tpl.variant_bindings) != len(product_tmpl.product_variant_ids)
            _logger.info("_product_post: Rebind needed:"+str(rebind_needed))
            if force_meli_new_pub or rebind_needed:
                _logger.info("_product_post: Rebind needed or forced: force_meli_new_pub:"+str(force_meli_new_pub))
                bind_tpl.product_template_rebind(unbind_template=False)
            if "id" in rjson:
                bind_tpl.copy_from_rjson( rjson=rjson, meli=meli )

            stock = 0
            bind_tpl.price = bind_tpl.price or product_tmpl.meli_price
            for bindv in bind_tpl.variant_bindings:
                bindv.meli_available_quantity = (bindv.product_id and bindv.product_id.meli_available_quantity) or 0
                bindv.price = bind_tpl.price
                bindv.stock = bindv.meli_available_quantity
                stock+= bindv.stock
            bind_tpl.stock = stock
            #bind.copy_from_rjson( rjson=rjson, meli=meli )
        else:
            for bindT in product_tmpl.mercadolibre_bindings:
                if (bindT.conn_id==target.meli_id):
                    rebind_needed = target.meli_pub_as_variant and bindT.variant_bindings and product_tmpl.product_variant_ids and len(bindT.variant_bindings) != len(product_tmpl.product_variant_ids)
                    _logger.info("_product_post > Rebind needed:"+str(rebind_needed))
                    if force_meli_new_pub or rebind_needed:
                        _logger.info("_product_post > Rebind needed or forced: force_meli_new_pub:"+str(force_meli_new_pub))
                        bindT.product_template_rebind(unbind_template=False)
                    if "id" in rjson:
                        bindT.copy_from_rjson( rjson=rjson, meli=meli )
                    stock = 0
                    bindT.price = bindT.price or product_tmpl.meli_price
                    for bindv in bindT.variant_bindings:
                        bindv.meli_available_quantity = (bindv.product_id and bindv.product_id.meli_available_quantity) or 0
                        bindv.stock = bindv.meli_available_quantity
                        bindv.meli_price = bindv.product_id.meli_price
                        bindv.price = bindv.meli_price
                        stock+= bindv.stock
                    bindT.stock = stock


        #raise ValidationError(str(rjson)+str(body))

        #TODO: check target activation
        force_meli_active = False
        if ("force_meli_active" in self.env.context):
            force_meli_active = self.env.context.get("force_meli_active")
        if (force_meli_active==True):
            target.product_meli_status_active()

        return {}


    def product_post(self, bind_tpl=None, bind=None, meli=None, config=None ):
        res = []
        for product in self:
            res.append(product._product_post( bind_tpl=bind_tpl, bind=bind, meli=meli, config=config ))

        return res

    def product_get_meli_update( self ):

        #_logger.info("meli_oerp_multiple >> product_get_meli_update")

        company = self.env.company or self.env.user.company_id
        warningobj = self.env['meli.warning']
        product_obj = self.env['product.product']

        ML_status = "unknown"
        ML_sub_status = ""
        ML_permalink_edit = ""
        ML_permalink_api = ""
        ML_state = False

        #meli = None
        product = self
        product.meli_status = ML_status
        product.meli_sub_status = ML_sub_status
        product.meli_permalink_edit = ML_permalink_edit
        product.meli_permalink_api = ML_permalink_api
        product.meli_state = ML_state

        account = company.mercadolibre_connections and company.mercadolibre_connections[0]
        company = (account and account.company_id) or self.env.company or self.env.user.company_id
        #_logger.info("product_get_meli_update > company:"+str(company and company.name)+" account:"+str(account))

        if not account or not company:
            return {}
        
        meli = self.env['meli.util'].get_new_instance( company, account )

        if meli and meli.need_login():
            ML_status = "unknown"
            ML_permalink_edit = ""
            ML_permalink_api = ""
            ML_state = True

        for product in self:
            if product.meli_id and meli and not meli.need_login():
                response = meli.get("/items/"+product.meli_id, {'access_token':meli.access_token} )
                rjson = response.json()
                if "status" in rjson:
                    ML_status = rjson["status"]
                if "permalink" in rjson:
                    ML_permalink_edit = company.get_ML_LINK_URL(meli=meli)+str("publicaciones/")+str(product.meli_id)+str("/modificar")
                    ML_permalink_api = str("https://api.mercadolibre.com/items/")+str(product.meli_id)+str("?include_attributes=all&access_token="+str(meli and meli.access_token))
                if "error" in rjson:
                    ML_status = rjson["error"]
                if "sub_status" in rjson:
                    if len(rjson["sub_status"]):
                        ML_sub_status =  rjson["sub_status"][0]
                        if ( ML_sub_status =='deleted' ):
                            product.write({ 'meli_id': '','meli_id_variation': '' })

            product.meli_status = ML_status
            product.meli_sub_status = ML_sub_status
            product.meli_permalink_edit = ML_permalink_edit
            product.meli_permalink_api = ML_permalink_api
            product.meli_state = ML_state

    def _compute_meli_permalink(self):
        for product in self:
            product.meli_permalink = _meli_short_permalink(product.meli_id or '')

    meli_permalink = fields.Char( compute='_compute_meli_permalink', size=256, string='Link', help='PermaLink en MercadoLibre (calculado desde meli_id, sin llamada API)', depends=['meli_id'], compute_sudo=True )
    meli_permalink_edit = fields.Char( compute=product_get_meli_update, size=256, string='Link Edit',help='PermaLink Edit in MercadoLibre', compute_sudo=True )
    meli_permalink_api = fields.Char( compute=product_get_meli_update, size=256, string='Link Api',help='PermaLink Api in MercadoLibre', compute_sudo=True )
    meli_state = fields.Boolean( compute=product_get_meli_update, string='Login',help="Inicio de sesión requerida", compute_sudo=True )
    meli_status = fields.Char( compute=product_get_meli_update, size=128, string='Status', help="Estado del producto en ML", compute_sudo=True )
    meli_sub_status = fields.Char( compute=product_get_meli_update, size=128, string='Sub status',help="Sub Estado del producto en ML", compute_sudo=True )


    def x_match_variation_id( self, meli=None, meli_id=None, meli_id_variation=None, product_sku=None, product_barcode=None, target=None ):
        """
        Match variation id by SKU/barcode.
        Returns: (target_meli_id_variation, revision_matches)

        Priority:
        1. Barcode exact match (if both have barcodes)
        2. SKU exact match (if only one variation matches)
        3. If multiple SKU matches but different barcodes → needs revision
        """
        target_meli_id_variation = None
        revision_matches = ""

        productjson = self.env["mercadolibre.account"].fetch_meli_product( meli_id=meli_id, meli=meli )
        if not productjson or "variations" not in productjson or not len(productjson["variations"]):
            return target_meli_id_variation, revision_matches

        sku_matches = []  # Variations where SKU matches
        barcode_match = None  # Exact barcode match

        for vr in productjson["variations"]:
            var_id = vr.get("id")
            seller_sku = vr.get("seller_sku") or vr.get("seller_custom_field")
            meli_barcode = vr.get("barcode")

            # Priority 1: Exact barcode match
            if meli_barcode and product_barcode and meli_barcode == product_barcode:
                barcode_match = var_id
                break  # Barcode is definitive

            # Track SKU matches
            if seller_sku and product_sku and seller_sku == product_sku:
                sku_matches.append({
                    'id': var_id,
                    'sku': seller_sku,
                    'barcode': meli_barcode
                })

        # Use barcode match if found
        if barcode_match:
            target_meli_id_variation = barcode_match
        elif len(sku_matches) == 1:
            # Exactly one SKU match - use it
            match = sku_matches[0]
            target_meli_id_variation = match['id']

            # Auto-update the binding if provided
            if target and target_meli_id_variation:
                if str(target.conn_variation_id) != str(target_meli_id_variation):
                    # Preflight: verify that no OTHER binding already holds the
                    # target tuple (connection_account, conn_id, conn_variation_id,
                    # product_tmpl_id). If one exists, the unique constraint
                    # `mercadolibre_product_unique_conn_id_product_tmpl` will
                    # explode at flush time with a duplicate-key violation and
                    # poison the whole stock-post transaction (seen in prod
                    # kelebcenter, 20/04/2026 SKU PA-RO-RO-477 meli_id
                    # MLA1718187740). Skip the rename and surface the duplicate
                    # via stock_error so the UI flags it for manual merge.
                    _target_tmpl_id = target.product_tmpl_id and target.product_tmpl_id.id
                    _conflict = self.env['mercadolibre.product'].search([
                        ('connection_account', '=', target.connection_account.id),
                        ('conn_id', '=', target.conn_id),
                        ('conn_variation_id', '=', str(target_meli_id_variation)),
                        ('product_tmpl_id', '=', _target_tmpl_id),
                        ('id', '!=', target.id),
                    ], limit=1)
                    if _conflict:
                        _dup_tag = "revisar duplicados (binding %s vs %s)" % (target.id, _conflict.id)
                        _logger.warning(
                            "Auto-fix SKIPPED for SKU %s (meli_id %s): binding id:%s already "
                            "holds conn_variation_id=%s for tmpl=%s; marking both for manual "
                            "merge. target=id:%s (current var=%s)",
                            product_sku, meli_id, _conflict.id, target_meli_id_variation,
                            _target_tmpl_id, target.id, target.conn_variation_id,
                        )
                        try:
                            with self.env.cr.savepoint():
                                target.stock_error = _dup_tag
                                _conflict.stock_error = _dup_tag
                        except Exception:
                            pass
                    else:
                        _logger.info(
                            "Auto-fix: Updating variation_id for SKU %s: %s -> %s (meli_id: %s)",
                            product_sku, target.conn_variation_id, target_meli_id_variation, meli_id
                        )
                        target.conn_variation_id = str(target_meli_id_variation)
                        target.meli_id_variation = str(target_meli_id_variation)

            # Log if barcodes differ
            if match['barcode'] and product_barcode and match['barcode'] != product_barcode:
                _logger.info(
                    "SKU %s matched but barcode differs (odoo: %s, meli: %s). Using variation %s",
                    product_sku, product_barcode, match['barcode'], target_meli_id_variation
                )
        elif len(sku_matches) > 1:
            # Multiple SKU matches - needs manual revision
            revision_matches = "Multiple variations match SKU %s: %s. Check barcodes." % (
                product_sku,
                ', '.join([str(m['id']) for m in sku_matches])
            )

        return target_meli_id_variation, revision_matches

    def get_meli_from_target( self, target, meli=None ):
        meli_util = meli or None
        account = target and "connection_account" in target._fields and target.connection_account
        config = account and account.configuration
        company = account and account.company_id
        if target and not account:
            return False

        if not meli_util or meli_util.client_id != account.client_id:
            meli_util = None

        if not meli_util or not hasattr(meli_util, 'client_id'):
            meli_util = self.env['meli.util'].get_new_instance( account.company_id, account)
            if meli_util.need_login():
                return meli_util.redirect_login()

        return meli_util

    def get_meli_from_product( self, meli_id=None, meli=None ):
        meli_util = meli or None
        meli_id = meli_id or product.meli_id

        #debe al menos tener una vinculacion (sino tomamos la primera cuenta configurada??)

        #solo queremos la cuenta vinculada
        target = self.env["mercadolibre.product"].search([('conn_id','=',meli_id)], limit=1)

        if not target:
            return None

        meli_util = self.get_meli_from_target( target = target, meli=meli_util)

        return meli_util


    def x_product_post_stock( self, context=None, meli=False, config=None, meli_id=None, meli_id_variation=None, target=None, item_json=None ):
        import time
        _x_timing = {}
        _x_start = time.time()

        context = context or self.env.context

        # Get chatter_log flag from account config
        account = self._meli_resolve_account(config)
        chatter_log = account and account.meli_cron_log_chatter

        #_logger.info("meli_oerp product_post_stock x_product_post_stock context: " + str(context)+" meli:"+str(meli)
        if 1==2:
            _logger.info("x_product_post_stock "+str(self)+" default_code: "+str(self.default_code)+" meli: "+str(meli and meli.seller_id)
                        +" config: "+str(config and config.name)
                        +" meli_id: "+str(meli_id)
                        +" meli_id_variation: "+str(meli_id_variation)
                        +" target: "+str(target)
                        )

        revision_matches = ""

        company = self.env.user.company_id
        warningobj = self.env['meli.warning']

        product_obj = self.env['product.product']
        product = self
        product_tmpl = self.product_tmpl_id
        config = config or company
        account = self._meli_resolve_account(config)

        user_product_id_active = account and account.user_product_seller
        # Configurable stock update mode (replaces hardcoded default_active_user_product_id_multi_stock)
        _stock_update_mode = config.mercadolibre_stock_update_mode if hasattr(config, 'mercadolibre_stock_update_mode') and config.mercadolibre_stock_update_mode else 'standard'
        _stock_update_type = config.mercadolibre_stock_update_type if hasattr(config, 'mercadolibre_stock_update_type') and config.mercadolibre_stock_update_type else 'seller_warehouse'
        # Auto mode: will be resolved per-product in _resolve_auto_stock_mode()
        _auto_resolved_type = None  # set later by _resolve_auto_stock_mode
        _auto_resolved_location = None  # store_id / network_node_id from GET response
        active_multi_stock = (_stock_update_mode in ('auto', 'user_product', 'user_product_type')) and user_product_id_active
        active_multi_stock_mode = "user_product_id_variant"
        #_logger.info("active_multi_stock: "+str(active_multi_stock)+" mode: "+str(_stock_update_mode))
        
        meli_id = meli_id or product.meli_id
        is_fulfillment = False
        meli = self.get_meli_from_target( target, meli=meli )

        if "meli_update_stock_blocked" in product_tmpl._fields and product_tmpl.meli_update_stock_blocked:
            error = { "error": "Blocked by product template configuration." }
            product.meli_stock_error = str(error)
            product_tmpl.meli_stock_error = product.meli_stock_error
            meli_message_post(product, error["error"])
            meli_message_post(product_tmpl, error["error"])
            return error

        # Check if seller is multiwarehouse - warn only if still using standard mode
        is_multiwarehouse = account and account.multiwarehouse
        site_id = account.meli_user_site_id if account else None

        if is_multiwarehouse and _stock_update_mode == 'standard':
            warning = {
                "warning": "multiwarehouse_seller",
                "message": f"Seller multiwarehouse ({site_id}): configure 'Modo actualización de stock' a Automático o Multi-warehouse en la configuración de la cuenta.",
                "status": "multiwarehouse"
            }
            # Store in stock_error so _meli_stock_status detects it
            if target and "stock_error" in target._fields:
                target.stock_error = json.dumps(warning)
            product.meli_stock_error = json.dumps(warning)
            if chatter_log:
                _logger.warning("x_product_post_stock MULTIWAREHOUSE standard mode: %s - %s", product.default_code, warning["message"])
            return warning

        if "meli_update_stock_blocked" in product._fields and product.meli_update_stock_blocked:
            error = { "error": "Blocked by product configuration." }
            product.meli_stock_error = str(error)
            product_tmpl.meli_stock_error = product.meli_stock_error
            meli_message_post(product, error["error"])
            meli_message_post(product_tmpl, error["error"])
            return error

        if not meli or not hasattr(meli, 'client_id'):
            _logger.error("x_product_post_stock meli not set")
            meli = self.env['meli.util'].get_new_instance(company)
            if meli.need_login():
                return meli.redirect_login()

        def _resolve_auto_stock_mode():
            """
            Para modo 'auto': hace GET /user-products/{id}/stock para detectar el tipo de
            ubicación (seller_warehouse / selling_address) y el X-Version requerido por ML.
            Retorna (effective_mode, effective_type, location_list, headers_dict).

            location_list es una lista de dicts {store_id, network_node_id, existing_qty},
            uno por cada depósito del tipo detectado (multi-depósito soportado).

            --- NOTAS IMPORTANTES sobre el comportamiento de la API de ML ---

            1. GET /stock                        → 200, devuelve todas las ubicaciones + X-Version header
            2. GET /stock/type/seller_warehouse  → 404 SIEMPRE (endpoint de solo escritura, no existe GET)
            3. PUT /stock/type/seller_warehouse  → 200 OK con body {"locations": [{store_id, network_node_id, quantity}]}
               Requiere header X-Version obtenido del GET /stock. Sin él → 400. Version obsoleta → 409.
            4. PUT /user-products/{id}/stock     → 404 SIEMPRE (endpoint base no existe para ML multi-origen)
            5. PUT /items/{id}                   → funciona para la mayoría, pero algunos productos reciben
               403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES (PolicyAgent los bloquea). El body de ese 403
               NO tiene campo "error", solo {code, blocked_by, message, status} — hay que detectar via status==403.

            Por esto NO se hace probe GET antes de decidir el modo: el 404 en GET /stock/type/
            no significa que el PUT esté bloqueado, es simplemente el comportamiento esperado de ML.
            """
            nonlocal _auto_resolved_type, _auto_resolved_location

            if not (active_multi_stock and target and "meli_user_product_id" in target._fields and target.meli_user_product_id):
                return _stock_update_mode, _stock_update_type, None, {}

            # X-Version es obligatorio para PUT /stock/type/ — se obtiene del GET /stock
            _data, _x_version = meli.get_user_product_stock_with_version( target.meli_user_product_id, meli.access_token )
            _headers = { "X-Version": _x_version } if _x_version else {}

            if _stock_update_mode != 'auto':
                # Modo configurado explícitamente — solo aplica headers
                return _stock_update_mode, _stock_update_type, None, _headers

            # Recolectar TODOS los depósitos del tipo detectado (un producto puede tener
            # seller_warehouse en múltiples stores, ej: Guadalajara 66093017 + Tepatitlán 79214650)
            _detected_type = None
            _all_locs = []  # [{store_id, network_node_id, existing_qty}, ...]
            if isinstance(_data, dict) and "locations" in _data:
                for loc in _data["locations"]:
                    loc_type = loc.get("type")
                    # meli_facility es stock propio de ML (FULL/flex) — no se puede actualizar manualmente
                    if loc_type in ("seller_warehouse", "selling_address"):
                        if _detected_type is None:
                            _detected_type = loc_type
                        if loc_type == _detected_type:
                            _all_locs.append({
                                "store_id": loc.get("store_id"),
                                "network_node_id": loc.get("network_node_id"),
                                "existing_qty": loc.get("quantity", 0) or 0,
                            })

            # Detect if this specific product is fulfillment (logistic_type
            # contains "fulfillment"). Checked HERE because is_fulfillment
            # at the outer scope uses exact match which misses
            # "fulfillment_user_product_id".
            _target_logistic = (
                target and "meli_shipping_logistic_type" in target._fields
                and target.meli_shipping_logistic_type or ""
            )
            _is_fulfillment_product = bool(_target_logistic) and "fulfillment" in _target_logistic

            if _detected_type and _all_locs:
                if _detected_type == 'seller_warehouse':
                    # MX/CO multiwarehouse sellers: always use user_product_type
                    _auto_resolved_type = _detected_type
                    _auto_resolved_location = _all_locs
                    _logger.info("Auto stock: type=%s locs=%d → user_product_type mode",
                                 _detected_type, len(_all_locs))
                    return 'user_product_type', _detected_type, _all_locs, _headers
                elif _detected_type == 'selling_address' and (is_multiwarehouse or _is_fulfillment_product):
                    # Multiwarehouse sellers OR fulfillment products: use
                    # selling_address via user_product_type. For fulfillment the
                    # seller may NOT be multiwarehouse but PUT /items/ returns
                    # item.available_quantity.not_modifiable — the ONLY working
                    # endpoint is /stock/type/selling_address (confirmed HTTP 204).
                    _auto_resolved_type = _detected_type
                    _auto_resolved_location = _all_locs
                    _logger.info("Auto stock: type=%s (multiwarehouse=%s fulfillment=%s) → user_product_type mode",
                                 _detected_type, is_multiwarehouse, _is_fulfillment_product)
                    return 'user_product_type', _detected_type, _all_locs, _headers
                else:
                    # Non-multiwarehouse, non-fulfillment seller with
                    # selling_address → standard PUT /items/{id} (works for
                    # simple sellers in AR, UY, etc.)
                    _logger.info("Auto stock: type=%s but non-multiwarehouse non-fulfillment → standard mode",
                                 _detected_type)
                    return 'standard', _stock_update_type, None, _headers

            # Sin ubicaciones reconocidas → modo estándar PUT /items/{id}
            return 'standard', _stock_update_type, None, _headers

        def put_url_stock( _meli_id, _meli_id_variation, _eff_mode=None, _eff_type=None ):

            _put_url_stock = "/items/"+str(_meli_id)

            if _meli_id_variation:
                _put_url_stock = _put_url_stock+"/variations/"+str(_meli_id_variation)

            if (active_multi_stock and target and "meli_user_product_id" in target._fields and target.meli_user_product_id):
                _user_product_id = str(target.meli_user_product_id)
                _mode = _eff_mode or _stock_update_mode
                _type = _eff_type or _stock_update_type
                if _mode == 'user_product_type':
                    _put_url_stock = "/user-products/"+_user_product_id+"/stock/type/"+_type
                elif _mode == 'user_product':
                    _put_url_stock = "/user-products/"+_user_product_id+"/stock"

            return _put_url_stock

        def put_var_stock( _meli_id, _meli_id_variation, _variation_stock, _eff_mode=None, _eff_type=None, _eff_loc=None ):

            _put_var_stock = _variation_stock

            if (active_multi_stock and target and "meli_user_product_id" in target._fields and target.meli_user_product_id):
                _qty = int(round(_variation_stock["available_quantity"]))
                _mode = _eff_mode or _stock_update_mode
                _type = _eff_type or _stock_update_type

                if _mode == 'user_product':
                    # PUT /user-products/{id}/stock — no decidimos la ubicación destino;
                    # enviamos {"quantity": N} sin location data y ML resuelve la distribución.
                    _put_var_stock = {"quantity": _qty}
                    if _meli_id_variation:
                        _put_var_stock["variation_id"] = _meli_id_variation

                elif _mode == 'user_product_type':
                    # PUT /user-products/{id}/stock/type/{tipo} con header X-Version (obligatorio).
                    # Body: {"locations": [{store_id, network_node_id, quantity}, ...]}
                    if _type == 'seller_warehouse':
                        # El body debe incluir TODOS los depósitos del vendedor.
                        # La cantidad se distribuye proporcionalmente usando las cantidades actuales
                        # de cada depósito obtenidas del GET /stock (preserva la distribución existente).
                        # Si todos los depósitos tienen 0, el total va al primer depósito.
                        _locs_list = (_eff_loc if isinstance(_eff_loc, list)
                                      else ([_eff_loc] if isinstance(_eff_loc, dict) and _eff_loc else []))
                        if _locs_list:
                            _existing_total = sum(l.get("existing_qty", 0) for l in _locs_list)
                            _sw_locations = []
                            for _i, _loc_entry in enumerate(_locs_list):
                                if _existing_total > 0:
                                    _loc_qty = int(round(_qty * _loc_entry.get("existing_qty", 0) / _existing_total))
                                elif _i == 0:
                                    _loc_qty = _qty
                                else:
                                    _loc_qty = 0
                                _sw_loc = {"quantity": _loc_qty}
                                if _loc_entry.get("store_id"):
                                    _sw_loc["store_id"] = _loc_entry["store_id"]
                                if _loc_entry.get("network_node_id"):
                                    _sw_loc["network_node_id"] = _loc_entry["network_node_id"]
                                _sw_locations.append(_sw_loc)
                            _put_var_stock = {"locations": _sw_locations}
                        else:
                            # No detected locations — fall back to account config
                            _sw_loc = {"quantity": _qty}
                            if account and hasattr(account, 'meli_stock_location_ids') and account.meli_stock_location_ids:
                                _active_locs = account.meli_stock_location_ids.filtered(lambda l: l.status == 'active')
                                if _active_locs:
                                    if _active_locs[0].meli_store_id:
                                        _sw_loc["store_id"] = _active_locs[0].meli_store_id
                                    if _active_locs[0].network_node_id:
                                        _sw_loc["network_node_id"] = _active_locs[0].network_node_id
                            _put_var_stock = {"locations": [_sw_loc]}
                    else:
                        # selling_address: body simple con quantity
                        _put_var_stock = { "quantity": _qty }
                    if _meli_id_variation:
                        if (active_multi_stock_mode == "user_product_id_root"):
                            _put_var_stock = {
                                "variations": [{
                                    "variation_id": _meli_id_variation,
                                    "quantity": _qty
                                }]
                            }

            return _put_var_stock
        
        try:
            #self.product_update_stock()
            product_fab = False
            if (1==2 and product.virtual_available<=0 and product.route_ids):
                for route in product.route_ids:
                    if (route.name in ['Fabricar','Manufacture']):
                        #_logger.info("Fabricar: "+str(product.meli_available_quantity))
                        product_fab = True

            base_meli_id = meli_id or (product_tmpl and product_tmpl.meli_pub_principal_variant and product_tmpl.meli_pub_principal_variant.meli_id)

            # OPTIMIZED: Use item_json if already fetched, avoid duplicate API call
            _t_fetch = time.time()
            productjson = item_json if item_json else self.env["mercadolibre.account"].fetch_meli_product( meli_id=base_meli_id, meli=meli )
            _x_timing['fetch_product'] = time.time() - _t_fetch            
            
            if target and productjson and target.binding_product_tmpl_id:
                target.binding_product_tmpl_id.meli_tags = 'tags' in productjson and str(productjson['tags'])
                target.binding_product_tmpl_id.meli_sale_terms = 'sale_terms' in productjson and str(productjson['sale_terms'])

            if (productjson and "user_product_id" in productjson and productjson["user_product_id"]):
                active_multi_stock_mode = "user_product_id_root"

            #_logger.info("Update master product stock:"+str(product.meli_id))
            _t1 = time.time()
            if (not product_fab):
                #_logger.info("Update meli_available_quantity from product:"+str(product)+" name:"+str(product.name))
                product.meli_available_quantity = product._meli_available_quantity( meli_id=meli_id, meli=meli, config=config )
                #_logger.info("Update meli_available_quantity from product:"+str(product.meli_available_quantity))
            _x_timing['first_avail_qty'] = time.time() - _t1

            if product.meli_available_quantity<0:
                product.meli_available_quantity = 0
            #_logger.info("Update master product stock:"+str(product.meli_available_quantity))

            #is_fulfillment based on target or product

            is_target_fulfillment = ( target and target.meli_shipping_logistic_type and "fulfillment"==target.meli_shipping_logistic_type )
            is_product_fulfillment = ( product.meli_shipping_logistic_type and "fulfillment"==product.meli_shipping_logistic_type )

            #if the target is fulfillment do not process the all thing
            #target null means the product is the target...
            is_fulfillment = is_target_fulfillment or (not target and is_product_fulfillment)
            if is_fulfillment:
                #_logger.info("is_fulfillment: "+str(is_fulfillment))
                return { "error": "fulfillment" }

            if product:
                qty = product.meli_available_quantity
            if target:
                target.meli_available_quantity = product.meli_available_quantity
                if (target.meli_available_quantity<0.0):
                    target.meli_available_quantity = 0.0
                qty = target.meli_available_quantity

            fields = {
                "available_quantity": int(round(qty or 0))
            }

            if fields['available_quantity'] < 0:
                fields['available_quantity'] = 0


            posted_try = False
            base_meli_id = False
            has_variations = False

            if 1==2:
                _logger.info("post stock available_quantity:"+str(fields['available_quantity']))
                _logger.info("product_tmpl.meli_pub_as_variant:"+str(product_tmpl.meli_pub_as_variant))
                _logger.info(product_tmpl.meli_pub_principal_variant.id)

            if ( product_tmpl.meli_pub_as_variant or (meli_id and not meli_id_variation) ):
                base_meli_id = meli_id or (product_tmpl.meli_pub_principal_variant and product_tmpl.meli_pub_principal_variant.meli_id)
                if (base_meli_id):
                    #response = meli.get("/items/%s" % base_meli_id, {'access_token':meli.access_token, 'include_attributes': 'all'})
                    #if (response):
                    #    productjson = response.json()
                    productjson = productjson or self.env["mercadolibre.account"].fetch_meli_product( meli_id=base_meli_id, meli=meli )
                    #_logger.info("productjson:"+str(productjson))
                    has_variations = productjson and "variations" in productjson and productjson["variations"] and len(productjson["variations"])>0
                    #_logger.info( "has_variations:"+str(has_variations) + str( "variations" in productjson and productjson["variations"] and len(productjson["variations"])>0 ) )

            if (product_tmpl.meli_pub_as_variant and has_variations):
                #_logger.info( "has_variations and odoo pub as variant")
                if (product_tmpl.meli_pub_principal_variant.id==False and len(product_tmpl.product_variant_ids)):
                    product_tmpl.meli_pub_principal_variant = product_tmpl.product_variant_ids[0]

                #chequeamos la variacion de este producto
                if ( has_variations ):
                    varias = {
                        "variations": []
                    }
                    #_logger.info("x_product_post_stock product_post_stock > Update variations stock")
                    found_comb = False
                    ningun_sku_coincide = True
                    ningun_barcode_coincide = True
                    pictures_v = []
                    same_price = False

                    #TODO: check combination now based on SKU and forget!!
                    _t_var_loop = time.time()
                    _var_count = len(productjson["variations"])
                    for ix in range(len(productjson["variations"]) ):
                        vr = productjson["variations"][ix]
                        seller_sku = ("seller_sku" in vr and vr["seller_sku"]) or ("seller_custom_field" in vr and vr["seller_custom_field"])
                        barcode = ("barcode" in vr and vr["barcode"])
                        target_meli_id_variation = vr["id"]

                        #check if combination is related to this product
                        if 'picture_ids' in productjson["variations"][ix]:
                            if (len(productjson["variations"][ix]["picture_ids"])>len(pictures_v)):
                                pictures_v = productjson["variations"][ix]["picture_ids"]
                        same_price = productjson["variations"][ix]["price"]

                        #_logger.info(vr)

                        #_logger.info("meli sku: "+str(seller_sku)+" vs. product.default_code: "+str(product.default_code))
                        #_logger.info("meli barcode: "+str(barcode)+" vs. product.barcode: "+str(product.barcode))

                        barcode_coincide = (barcode and product.barcode and barcode==product.barcode)
                        sin_barcode_en_ml_sku_ok = (not barcode and seller_sku==product.default_code)
                        combinacion_coincide = self._is_product_combination(productjson["variations"][ix])
                        sku_coincide = (product.default_code and seller_sku and seller_sku==product.default_code)

                        if sku_coincide:
                            ningun_sku_coincide = False

                        if barcode_coincide:
                            ningun_barcode_coincide = False

                        if 1==2:
                            _logger.info("barcode_coincide: "+str(barcode_coincide)+"")
                            _logger.info("sku_coincide: "+str(sku_coincide)+"")
                            _logger.info("combinacion_coincide: "+str(combinacion_coincide)+"")
                            _logger.info("sin_barcode_en_ml_sku_ok: "+str(sin_barcode_en_ml_sku_ok)+"")

                        variation_id_coincide = str((target and target.conn_variation_id) or meli_id_variation)==str(target_meli_id_variation)

                        if ( (barcode_coincide)
                            or (not barcode and sku_coincide)
                            or ( len(productjson["variations"])==1 and seller_sku==product.default_code)
                            or (sku_coincide)
                            or combinacion_coincide):

                            #_logger.info("x_product_post_stock _is_product_combination! Post stock to variation: "+str(target_meli_id_variation))

                            #_logger.info(productjson["variations"][ix])
                            found_comb = True
                            #reset meli_id_variation (TODO: resetting must be done outside)
                            target_meli_id_variation = productjson["variations"][ix]["id"]
                            if target:
                                #WARNING; will change the publication id variation?
                                reserror = None
                                if (not variation_id_coincide):
                                    if (sku_coincide):
                                        reserror =  { "warning": "Changing binding variant meli_id:"+str(target.conn_id)+" conn_id_variation: " + str(target.conn_variation_id) + " TO target_meli_id_variation: " + str(target_meli_id_variation)+" internal:"+str(product.default_code) }
                                        _logger.warning(reserror)
                                    else:
                                        # SKU mismatch - needs manual review, not a critical error
                                        reserror =  { "error": "Changing binding variant meli_id:"+str(target.conn_id)+" conn_id_variation: " + str(target.conn_variation_id) + " TO target_meli_id_variation: " + str(target_meli_id_variation)+" different seller_sku! Need to check! "+" internal:"+str(product.default_code)+" vs seller_sku:"+str(seller_sku) }
                                        _logger.info("SKU mismatch detected: %s", reserror)
                                        return reserror

                                    # Preflight: if another binding already holds the target
                                    # conn_variation_id for this (account, conn_id, product_tmpl),
                                    # the unique constraint mercadolibre_product_unique_conn_id_product_tmpl
                                    # will fail at flush time. Skip the rename instead of crashing —
                                    # the duplicate binding needs a manual merge.
                                    _conflict = self.env['mercadolibre.product'].search([
                                        ('connection_account', '=', target.connection_account.id),
                                        ('conn_id', '=', target.conn_id),
                                        ('conn_variation_id', '=', str(target_meli_id_variation)),
                                        ('product_tmpl_id', '=', target.product_tmpl_id.id),
                                        ('id', '!=', target.id),
                                    ], limit=1)
                                    if _conflict:
                                        reserror = {
                                            "warning": (
                                                "Skipping conn_variation_id change on binding id:%s "
                                                "(%s → %s) because binding id:%s already holds the target. "
                                                "Both bindings must be merged manually."
                                            ) % (target.id, target.conn_variation_id,
                                                 target_meli_id_variation, _conflict.id)
                                        }
                                        _logger.warning(reserror["warning"])
                                        return reserror
                                try:

                                    target.meli_id_variation = str(target_meli_id_variation)
                                    target.conn_variation_id = str(target_meli_id_variation)
                                except Exception as e:
                                    if reserror:
                                        _logger.error("Error updating conn_variation_id: "+str(e))
                                        _logger.error(reserror)
                                        return reserror
                                    else:
                                        reserror = { "error": str(e) }
                                        _logger.error("Error updating conn_variation_id: "+str(reserror))
                                        return reserror


                            #update base product qty
                            product.meli_available_quantity = product._meli_available_quantity( meli_id=product.meli_id, meli=meli, config=config )
                            meli_id_stock = product.meli_available_quantity

                            #update target binding qty (target!=product)
                            if (target and meli_id and meli_id!=product.meli_id):
                                meli_id_stock = product._meli_available_quantity( meli_id=meli_id, meli=meli, config=config )
                                if (meli_id_stock<0.0):
                                    meli_id_stock = 0.0
                                target.meli_available_quantity = meli_id_stock

                            var = {
                                #"id": str( product.meli_id_variation ),
                                "available_quantity": (meli_id_stock>0.0 and meli_id_stock) or 0.0,
                                #"picture_ids": ['806634-MLM28112717071_092018', '928808-MLM28112717068_092018', '643737-MLM28112717069_092018', '934652-MLM28112717070_092018']
                            }
                            varias["variations"].append(var)
                            #_logger.info(varias)
                            #_logger.info(var)
                            _t_hdrs_var = time.time()
                            _eff_mode, _eff_type, _eff_loc, put_headers = _resolve_auto_stock_mode()
                            _x_timing['var_get_headers'] = _x_timing.get('var_get_headers', 0) + (time.time() - _t_hdrs_var)
                            if _eff_mode == 'skip_fulfillment':
                                # Full product: ML handles stock in its facilities.
                                # Skip the PUT entirely to avoid the guaranteed
                                # 400 item.available_quantity.not_modifiable.
                                responsevar = None
                                posted_try = False
                                reserror = {
                                    "warning": "Stock no modificable en ML (producto Full: logistic_type=%s). "
                                               "MercadoLibre gestiona el stock en sus depósitos." % (
                                                   (target and target.meli_shipping_logistic_type) or "fulfillment"
                                               ),
                                    "fulfillment": True,
                                    "not_modifiable": True,
                                }
                                return reserror
                            put_url = put_url_stock( meli_id, target_meli_id_variation, _eff_mode, _eff_type )
                            put_var = put_var_stock( meli_id, target_meli_id_variation, var, _eff_mode, _eff_type, _eff_loc )
                            _t_put_var = time.time()
                            responsevar = meli.put_mini( put_url, put_var, { 'access_token':meli.access_token, 'headers': put_headers })
                            _x_timing['var_put_api'] = _x_timing.get('var_put_api', 0) + (time.time() - _t_put_var)
                            posted_try = True
                            #_logger.info("x_product_post_stock put_url : "+str(put_url)+" put_var:"+str(put_var)+" put_headers:"+str(put_headers))
                            if responsevar:
                                #_logger.info(responsevar.json())
                                rjson = responsevar.json()
                                if rjson:
                                    if "error" in rjson:
                                        rjson["put_url"] = put_url
                                        rjson_str = str(rjson).lower()
                                        # Lower log level for known non-critical errors and flag error type
                                        status_code = rjson.get("status")
                                        if status_code == 404 or "not_found" in rjson_str:
                                            _logger.debug("%s %s var:%s Item no encontrado (404)",
                                                         config and config.name, put_url, var)
                                            rjson["not_found"] = True
                                        elif "status:under_review" in rjson_str:
                                            _logger.debug("%s %s var:%s Item bajo revisión en ML",
                                                         config and config.name, put_url, var)
                                            rjson["under_review"] = True
                                        elif "status:closed" in rjson_str or "status:inactive" in rjson_str:
                                            _logger.debug("%s %s var:%s Item cerrado/inactivo en ML",
                                                         config and config.name, put_url, var)
                                            rjson["closed"] = True
                                        elif "not_modifiable" in rjson_str or "not modifiable" in rjson_str or "field_not_updatable" in rjson_str:
                                            _logger.debug("%s %s var:%s Stock no modificable",
                                                         config and config.name, put_url, var)
                                            rjson["not_modifiable"] = True
                                        else:
                                            _logger.error(str(config and config.name) + " "+ put_url+" var:"+str(var)+" result: "+str(rjson))
                                        return rjson
                                    #rjson["put_url"] = put_url
                                    #_logger.info("x_product_post_stock res: "+put_url+" "+str(rjson)+ " token: " + meli.access_token)
                                else:
                                    continue;
                        else:
                            no_es_variante_unica_o_sku_no_coincide = ( len(productjson["variations"])==1 and seller_sku==product.default_code )
                            revisar = (not barcode_coincide and "barcode_nocoincide ") or ""
                            revisar+= (not sin_barcode_en_ml_sku_ok and "con_barcode_en_ml ") or ""
                            revisar+= (not no_es_variante_unica_o_sku_no_coincide and "no_es_variante_unica_o_sku_no_coincide ") or ""
                            revisar+= (not combinacion_coincide and "combinacion_no_coincide") or ""
                            res = { 'error': 'verificar publicacion > '+str(revisar) }
                            # ATENCINON >>> NO BLOQUEAR!!!!

                    _x_timing['var_loop'] = time.time() - _t_var_loop
                    _x_timing['var_loop_count'] = _var_count
                    if found_comb:
                        res = {}

                    if found_comb==False:
                        status_error = { "error": "No recomendamos actualizar ya que no coincide correctamente el producto con la publicación. Revise la publicación skus y barcodes." }
                        _logger.error(status_error)
                        if (ningun_sku_coincide):
                            _logger.error("No coincide ningun SKU en la publicacion")
                            status_error["error"]+= str(" Meli SKU [")+str(target and target.sku)+str("] vs ")+str(" Odoo SKU [")+str(product and product.default_code)+str("].")

                        if (ningun_barcode_coincide):
                            _logger.error("No coincide ningun BARCODE en la publicacion")
                            status_error["error"]+= str(" Meli Barcode [")+str(target and target.barcode)+str("] vs ")+str(" Odoo Barcode [")+str(product and product.barcode)+str("].")

                        return status_error



                    if found_comb==False and 1==2:
                        #add combination!!
                        #_logger.info("add combination")
                        addvar = self._combination()
                        #_logger.info(addvar)
                        if addvar:
                            if ('picture_ids' in addvar):
                                if len(pictures_v)>=len(addvar["picture_ids"]):
                                    addvar["picture_ids"] = pictures_v
                            #if (config.mercadolibre_post_default_code): #TODO: fixing SKU must be specific parameter
                            #    addvar["seller_custom_field"] = product.default_code
                            addvar["price"] = same_price
                            #_logger.info("Add variation!")
                            #_logger.info(addvar)
                            post_url = "/items/"+str(meli_id)+"/variations"
                            responsevar = meli.post( post_url, addvar, {'access_token':meli.access_token})
                            #_logger.info("x_product_post_stock responsevar : "+str(post_url)+str(responsevar))
                            if responsevar:
                                rjson = responsevar.json()
                                #_logger.info(responsevar.json())
                                if rjson:
                                    if "error" in rjson:
                                        _logger.error( post_url+" "+str(rjson))
                                        return rjson
                            #_logger.info(responsevar.json())

                #_logger.info("Available:"+str(product_tmpl.virtual_available))
                best_available = 0

                #TEST AND PAUSE OR ACTIVATE (product)
                for vr in product_tmpl.product_variant_ids:
                    vr_qty = vr.meli_available_quantity
                    if (vr_qty<0):
                        vr_qty = 0
                    best_available+= vr_qty
                if (best_available>0 and product.meli_status=="paused"):
                    #_logger.info("x_product_post_stock > Active! product:"+str(product.meli_id))
                    product.product_meli_status_active(meli=meli)
                elif (best_available<=0 and product.meli_status=="active"):
                    #_logger.info("x_product_post_stock > Pause! product:"+str(product.meli_id))
                    pass;
                    #product.product_meli_status_pause(meli=meli)

                #TEST AND PAUSE OR ACTIVATE (target=binding)
                if target:
                    _t_vb = time.time()
                    _vb_count = 0
                    _vb_times = []  # Track individual variant times
                    for vr in target.binding_product_tmpl_id.variant_bindings:
                        pvr = vr.product_id
                        if pvr:
                            _t_vr_start = time.time()
                            vr.meli_available_quantity = pvr._meli_available_quantity( meli_id=vr.meli_id, meli=meli, config=config )
                            _vb_times.append(time.time() - _t_vr_start)
                            _vb_count += 1
                        vr_qty = vr.meli_available_quantity
                        if (vr_qty<0):
                            vr_qty = 0
                        best_available+= vr_qty
                    _x_timing['variant_bindings_loop'] = time.time() - _t_vb
                    _x_timing['variant_bindings_count'] = _vb_count
                    if _vb_times:
                        _x_timing['vb_min'] = min(_vb_times)
                        _x_timing['vb_max'] = max(_vb_times)
                        _x_timing['vb_avg'] = sum(_vb_times) / len(_vb_times)
                    if (best_available>0 and target.meli_status=="paused"):
                        #_logger.info("x_product_post_stock > Active! target:"+str(target.meli_id))
                        target.product_meli_status_active(meli=meli)
                    elif (best_available<=0 and target.meli_status=="active"):
                        #_logger.info("x_product_post_stock > Pause! target:"+str(target.meli_id))
                        pass;
                        #target.product_meli_status_pause(meli=meli)

            if (not has_variations or not product_tmpl.meli_pub_as_variant):
                _t_no_var_start = time.time()
                #_logger.info( "not has_variations or not odoo pub as variant")
                if (meli_id and not meli_id_variation and has_variations):
                    if (len(productjson["variations"])==1):
                        meli_id_variation = productjson["variations"][0]["id"]

                        if (target and target.conn_id==meli_id and target.meli_id==meli_id):
                            if chatter_log:
                                _logger.info("fix bind variant meli_id_variation: "+str(meli_id_variation))
                            target.conn_variation_id = meli_id_variation
                            target.meli_id_variation = meli_id_variation

                        if (product.meli_id==meli_id and product.meli_id_variation != meli_id_variation):
                            if chatter_log:
                                _logger.info("fix product meli_id_variation: "+str(meli_id_variation))
                            product.meli_id_variation = meli_id_variation

                if (meli_id_variation):
                    #_logger.info("Posting using product.meli_id_variation")
                    #check if variation id exists in target
                    get_url = "/items/"+str(meli_id)+"/variations/"+str(meli_id_variation)
                    #_logger.info("res:"+str(res)+" meli.access_token:"+str(meli.access_token))

                    _t_get_var = time.time()
                    response = meli.get( get_url, {'access_token':meli.access_token})
                    _x_timing['get_variation_api'] = time.time() - _t_get_var
                    is_not_meli_id_variation = True
                    if (response):
                        pjson = response.json()
                        if pjson and "error" in pjson:
                            #No existe ese id de variante, recorremos todas las variantes por las dudas...
                            #res = "/items/%s/variations" % (meli_id)
                            #response = meli.get( res, {'access_token':meli.access_token})
                            if (has_variations):
                                variations = productjson and "variations" in productjson and productjson["variations"]
                                #_logger.info("second:" )
                                for var in variations:
                                    if "id" in var and str(var["id"])==str(meli_id_variation):
                                        is_not_meli_id_variation = False
                        else:
                            #se encontro...
                            is_not_meli_id_variation = False

                        if (is_not_meli_id_variation):
                            # Try to match by SKU/barcode and auto-fix binding if found
                            _t_match = time.time()
                            fix_meli_id_variation, revision_matches = self.x_match_variation_id(
                                meli=meli, meli_id=meli_id, meli_id_variation=meli_id_variation,
                                product_sku=product.default_code, product_barcode=product.barcode,
                                target=target
                            )
                            _x_timing['x_match_variation_id'] = time.time() - _t_match
                            if not fix_meli_id_variation:
                                if revision_matches:
                                    verror = { "error": revision_matches }
                                else:
                                    verror = { "error": "Variation id not found for SKU %s in %s (old var_id: %s)" % (
                                        product.default_code, meli_id, meli_id_variation
                                    )}
                                _logger.warning(verror)
                                return verror

                            meli_id_variation = fix_meli_id_variation

                    meli_id_stock = product.meli_available_quantity

                    #update target binding qty (target!=product)
                    if (target and meli_id and meli_id!=product.meli_id):
                        _t_avail_qty2 = time.time()
                        meli_id_stock = product._meli_available_quantity( meli_id=meli_id, meli=meli, config=config )
                        _x_timing['second_avail_qty'] = time.time() - _t_avail_qty2
                        if (meli_id_stock<0.0):
                            meli_id_stock = 0.0
                        target.meli_available_quantity = meli_id_stock

                    var = {
                        #"id": str( product.meli_id_variation ),
                        "available_quantity": int(round( (meli_id_stock>0.0 and meli_id_stock) or 0 )),
                        #"picture_ids": ['806634-MLM28112717071_092018', '928808-MLM28112717068_092018', '643737-MLM28112717069_092018', '934652-MLM28112717070_092018']
                    }

                    _t_headers = time.time()
                    _eff_mode, _eff_type, _eff_loc, put_headers = _resolve_auto_stock_mode()
                    _x_timing['get_headers_stock'] = time.time() - _t_headers
                    if _eff_mode == 'skip_fulfillment':
                        # 100% Full product with no seller-owned location —
                        # ML handles the whole stock. Skip the PUT to avoid a
                        # known-to-fail 400 item.available_quantity.not_modifiable.
                        return {
                            "warning": "Stock no modificable en ML (producto Full: logistic_type=%s). "
                                       "MercadoLibre gestiona el stock en sus depósitos." % (
                                           (target and target.meli_shipping_logistic_type) or "fulfillment"
                                       ),
                            "fulfillment": True,
                            "not_modifiable": True,
                        }
                    put_url = put_url_stock( meli_id, meli_id_variation, _eff_mode, _eff_type )
                    put_var = put_var_stock( meli_id, meli_id_variation, var, _eff_mode, _eff_type, _eff_loc )
                    #_logger.info("x_product_post_stock put_url : "+str(put_url)+" put_var:"+str(put_var)+" put_headers:"+str(put_headers))
                    _t_put = time.time()
                    responsevar = meli.put_mini( put_url, put_var, { 'access_token':meli.access_token, 'headers': put_headers })
                    _x_timing['put_stock_api'] = time.time() - _t_put
                    posted_try = True
                    if (responsevar):
                        rjson = responsevar.json()
                        if rjson:
                            #_logger.info(rjson)
                            if "error" in rjson:
                                rjson["put_url"] = put_url
                                rjson["access_token"] = meli.access_token
                                rjson_str = str(rjson).lower()
                                # Lower log level for known non-critical errors and flag error type
                                status_code = rjson.get("status")
                                if status_code == 404 or "not_found" in rjson_str:
                                    _logger.debug("%s %s put_var:%s Item no encontrado (404)",
                                                 config and config.name, put_url, put_var)
                                    rjson["not_found"] = True
                                elif "status:under_review" in rjson_str:
                                    _logger.debug("%s %s put_var:%s Item bajo revisión en ML",
                                                 config and config.name, put_url, put_var)
                                    rjson["under_review"] = True
                                elif "status:closed" in rjson_str or "status:inactive" in rjson_str:
                                    _logger.debug("%s %s put_var:%s Item cerrado/inactivo en ML",
                                                 config and config.name, put_url, put_var)
                                    rjson["closed"] = True
                                elif "not_modifiable" in rjson_str or "not modifiable" in rjson_str or "field_not_updatable" in rjson_str or "not_updatable" in rjson_str:
                                    _logger.debug("%s %s put_var:%s Stock no modificable (multi-warehouse o item cerrado/fulfillment)",
                                                 config and config.name, put_url, put_var)
                                    rjson["not_modifiable"] = True
                                else:
                                    _logger.error(str(config and config.name) + " "+ put_url+" put_var:"+str(put_var)+" result: "+str(rjson)+ " token: " + meli.access_token)
                                return rjson
                            # ML 403 body has no "error" key — detect via status field
                            elif rjson.get("status") == 403:
                                rjson["put_url"] = put_url
                                _logger.warning("%s 403 PA_UNAUTHORIZED on %s (variation path) — marking not_modifiable",
                                                config and config.name, put_url)
                                rjson["not_modifiable"] = True
                                return rjson
                            #rjson["put_url"] = put_url
                            #if ('available_quantity' in rjson):
                            #    _logger.info( str(config and config.name) + " "+put_url +" Posted ok: " + str(rjson['available_quantity']) )
                            #    pass;
                else:
                    _t_headers2 = time.time()
                    _eff_mode, _eff_type, _eff_loc, put_headers = _resolve_auto_stock_mode()
                    _x_timing['get_headers_stock_alt'] = time.time() - _t_headers2
                    if _eff_mode == 'skip_fulfillment':
                        # 100% Full product with no seller-owned location —
                        # ML handles the whole stock. Skip the PUT to avoid a
                        # known-to-fail 400 item.available_quantity.not_modifiable.
                        return {
                            "warning": "Stock no modificable en ML (producto Full: logistic_type=%s). "
                                       "MercadoLibre gestiona el stock en sus depósitos." % (
                                           (target and target.meli_shipping_logistic_type) or "fulfillment"
                                       ),
                            "fulfillment": True,
                            "not_modifiable": True,
                        }
                    put_url = put_url_stock( meli_id, None, _eff_mode, _eff_type )
                    put_var = put_var_stock( meli_id, None, fields, _eff_mode, _eff_type, _eff_loc )
                    #_logger.info("x_product_post_stock put_url : "+str(put_url)+" put_var:"+str(put_var)+" put_headers:"+str(put_headers))
                    _t_put2 = time.time()
                    response = meli.put_mini( path=put_url, body=put_var, params={'access_token':meli.access_token, 'headers': put_headers })
                    _x_timing['put_stock_api_alt'] = time.time() - _t_put2
                    posted_try = True
                    #_logger.info("x_product_post_stock responsevar : "+str(put_url)+str(response))
                    if (response):
                        rjson = response.json()
                        if rjson and "error" in rjson:
                            rjson["put_url"] = put_url
                            rjson["access_token"] = meli.access_token
                            # Lower log level for known non-critical errors
                            rjson_str_alt = str(rjson).lower()
                            if "not_modifiable" in rjson_str_alt or "not_updatable" in rjson_str_alt:
                                _logger.debug("%s %s put_var:%s Stock no modificable (multi-warehouse o item cerrado/fulfillment)",
                                             config and config.name, put_url, put_var)
                                rjson["not_modifiable"] = True
                            else:
                                _logger.error(str(config and config.name) + " "+ put_url+" put_var:"+str(put_var)+" "+str(rjson)+ " token: " + meli.access_token)
                            return rjson
                        # ML 403 PA_UNAUTHORIZED: algunos productos son bloqueados por PolicyAgent
                        # al intentar PUT /items/{id}. El body de ese error NO tiene campo "error",
                        # solo {code: "PA_UNAUTHORIZED_RESULT_FROM_POLICIES", blocked_by, message, status: 403}.
                        # Detectar por status==403 y reintentar con el endpoint multi-origen correcto.
                        elif rjson and rjson.get("status") == 403:
                            _up_id = (target and "meli_user_product_id" in target._fields
                                      and target.meli_user_product_id)
                            if _up_id:
                                # Reintento via PUT /stock/type/seller_warehouse con X-Version.
                                # El X-Version ya está en put_headers (capturado en _resolve_auto_stock_mode).
                                # Body incluye TODOS los depósitos detectados con qty proporcional.
                                _retry_url = "/user-products/" + str(_up_id) + "/stock/type/seller_warehouse"
                                _target_qty = int(round(fields.get("available_quantity", 0)))
                                _locs_for_retry = (_eff_loc if isinstance(_eff_loc, list)
                                                   else ([_eff_loc] if isinstance(_eff_loc, dict) and _eff_loc else []))
                                if _locs_for_retry:
                                    _ex_total = sum(l.get("existing_qty", 0) for l in _locs_for_retry)
                                    _retry_locs = []
                                    for _ri, _rl in enumerate(_locs_for_retry):
                                        if _ex_total > 0:
                                            _rl_qty = int(round(_target_qty * _rl.get("existing_qty", 0) / _ex_total))
                                        elif _ri == 0:
                                            _rl_qty = _target_qty
                                        else:
                                            _rl_qty = 0
                                        _sw = {"quantity": _rl_qty}
                                        if _rl.get("store_id"):
                                            _sw["store_id"] = _rl["store_id"]
                                        if _rl.get("network_node_id"):
                                            _sw["network_node_id"] = _rl["network_node_id"]
                                        _retry_locs.append(_sw)
                                    _retry_body = {"locations": _retry_locs}
                                else:
                                    _retry_body = {"quantity": _target_qty}
                                _logger.info("403 PA_UNAUTHORIZED on %s, retrying via %s body=%s",
                                             put_url, _retry_url, _retry_body)
                                _t_retry = time.time()
                                _retry_resp = meli.put_mini(
                                    path=_retry_url, body=_retry_body,
                                    params={'access_token': meli.access_token, 'headers': put_headers})
                                _x_timing['put_stock_api_alt_retry'] = time.time() - _t_retry
                                _retry_rjson = _retry_resp.json() if _retry_resp else {}
                                if _retry_rjson and ("error" in _retry_rjson
                                                     or _retry_rjson.get("status", 0) >= 400):
                                    _retry_rjson["put_url"] = _retry_url
                                    _retry_rjson["not_modifiable"] = True
                                    _logger.warning("%s %s retry also failed: %s",
                                                    config and config.name, _retry_url, _retry_rjson)
                                    return _retry_rjson
                                # retry succeeded
                            else:
                                rjson["not_modifiable"] = True
                                rjson["put_url"] = put_url
                                _logger.warning("%s 403 PA_UNAUTHORIZED on %s, no user_product_id for retry",
                                                config and config.name, put_url)
                                return rjson
                        #rjson["put_url"] = put_url
                        #if (rjson and 'available_quantity' in rjson):
                        #    _logger.info( put_url +" Posted ok: "+ str(rjson['available_quantity']) )
                        #    pass;
                        #else:
                        #    _logger.info( put_url +" Posted response: "+ str(rjson) )

                if (product.meli_available_quantity<=0 and product.meli_status=="active"):
                    #product.product_meli_status_pause(meli=meli)
                    #_logger.info("Pause (not)")
                    pass;
                elif (product.meli_available_quantity>0 and product.meli_status=="paused"):
                    product.product_meli_status_active(meli=meli)

                if (target.meli_available_quantity<=0 and target.meli_status=="active"):
                    #target.product_meli_status_pause(meli=meli)
                    #_logger.info("Pause (not)")
                    pass;
                elif (target.meli_available_quantity>0 and target.meli_status=="paused"):
                    target.product_meli_status_active(meli=meli)

        except Exception as e:
            _logger.error("x_product_post_stock > exception error: %s", e, exc_info=True)
            pass;
         #_logger.info("x_product_post_stock > ended")

        # Always capture timing breakdown in result for caller to use
        _x_timing['total'] = time.time() - _x_start

        if not posted_try:
            _logger.error("NO posted stock try")
            return { "error": "no posted stock try", "_timing": _x_timing }

        if (revision_matches):
            return { "warning": str(revision_matches), "_timing": _x_timing }

        return { "_timing": _x_timing }

    def product_post_stock( self, context=None, meli=False, config=None ):

        context = context or self.env.context
        product = self
        company = self.env.user.company_id
        warningobj = self.env['meli.warning']
        product_obj = self.env['product.product']
        product_tmpl = self.product_tmpl_id

        #_logger.info("meli_oerp_multiple > product_post_stock product:"+str(product and product.name)+" context:"+str(context))


        if not config or not meli:
            _logger.debug("post bindings %s", product.mercadolibre_bindings)

            for bind in product.mercadolibre_bindings:
                bind.product_post_stock(meli=meli)
            return {}

        config = config or company

        if not meli or not hasattr(meli, 'client_id'):
            account = self._meli_resolve_account(config)
            meli = self.env['meli.util'].get_new_instance( account.company_id, account)
            if meli.need_login():
                return meli.redirect_login()

        if (config and config.mercadolibre_stock_sku_mapping):

            sku = product.default_code
            
            stock_rules = config.mercadolibre_stock_sku_mapping.filtered(
                lambda r: r.type == 'stock' and bool(r.sku and r.sku.strip())
            )
            
            if (stock_rules and stock_rules[0] and stock_rules[0].name.startswith("Filtro") ):
                
                founded = False

                for sr in stock_rules:
                    #check all rules if type filter... check sku in that
                    if (sku == sr.sku):
                        founded = True

                if not founded:
                    return { "error": "SKU filtered" }
                    

        meli_id = product.meli_id
        meli_id_variation = product.meli_id_variation

        return product.x_product_post_stock(context=context,meli=meli, config=config, meli_id=meli_id, meli_id_variation=meli_id_variation )

    def x_product_post_price( self, meli_price=None, meli_currency=None, context=None, meli=False, config=None, meli_id=None, meli_id_variation=None ):
        company = self.env.user.company_id
        warningobj = self.env['meli.warning']

        product_obj = self.env['product.product']
        product = self
        product_tmpl = self.product_tmpl_id

        if not config:
            return {}

        if not meli or not hasattr(meli, 'client_id'):
            account = self._meli_resolve_account(config)
            meli = self.env['meli.util'].get_new_instance( account.company_id, account)
            if meli.need_login():
                return meli.redirect_login()

        product.set_meli_price( config=config )

        meli_price = meli_price or product.meli_price
        meli_currency = meli_currency or product.meli_currency or product_tmpl.meli_currency
        #_logger.info("meli_currency:"+str(meli_currency))

        fields = {
            "price": meli_price
        }

        fields_cur = {}

        pjson = False

        if (meli_id):
            response = meli.get("/items/%s" % (str(meli_id)), {'access_token':meli.access_token})
            if (response):
                pjson = response.json()

        if pjson and "currency_id" in pjson:
            if meli_currency and str(pjson["currency_id"])!=str(meli_currency):
                fields_cur = {
                    "currency_id": meli_currency
                }
                fields.update(fields_cur)

        if (meli_id and not meli_id_variation and pjson):
            #_logger.info("meli:"+str(meli))
            if "variations" in pjson:
                if (len(pjson["variations"])==1):
                    meli_id_variation = pjson["variations"][0]["id"]

        if (meli_id_variation and pjson):
            if "variations" in pjson:
                vars = []
                for varx in pjson["variations"]:
                #_logger.info("Posting using product.meli_id_variation")
                    var = {
                        "id": varx["id"],
                        "price": meli_price,
                        #"picture_ids": ['806634-MLM28112717071_092018', '928808-MLM28112717068_092018', '643737-MLM28112717069_092018', '934652-MLM28112717070_092018']
                    }
                    vars.append(var)
                #_logger.info("product_post_price (variations):"+str(vars))

                fields = { "variations": vars }
                if fields_cur:
                    fields.update(fields_cur)
                
                #_logger.info("x_product_post_price > posting price > (mul) (variations) > fields: " + str(fields) )
                
                #responsevar = meli.put("/items/"+str(meli_id)+'/variations/'+str( meli_id_variation ), var, {'access_token':meli.access_token})
                responsevar = meli.put_mini("/items/"+str(meli_id), fields, {'access_token':meli.access_token})
                if (responsevar):
                    rjson = responsevar.json()
                    if rjson:
                        #_logger.info('rjson'+str(rjson))
                        if "error" in rjson:
                            _logger.error("Posted price not updated: /items/"+str(meli_id)+" "+str(rjson))
                            return rjson
                        if ('price' in rjson):
                            _logger.info( "Posted price ok (mul) (variations) > " + str(meli_id) + ": " + str(rjson['price']) )
                            pass;
                        else:
                            _logger.info( "Posted price ok (mul) (variations) > " + str(meli_id) + ": " + str('variations' in rjson and rjson['variations']))
                            pass;


        else:
            #_logger.info("product_post_price (single):"+str(fields))
            response = meli.put_mini("/items/"+str(meli_id), fields, {'access_token':meli.access_token})
            if response:
                rjson = response.json()
                #_logger.info('rjson'+str(rjson))
                if rjson and "error" in rjson:
                    _logger.error("Posted price not updated: /items/"+str(meli_id)+" "+str(rjson))
                    return rjson
                #_logger.info( "Posted price ok (single)" + str(rjson))
                if (rjson and len(rjson) and 'price' in rjson):
                    _logger.info( "Posted price ok (mul) (single)" + str(meli_id) + ": " + str(rjson['price']) )
                    pass;
        return {}

    def product_post_price( self, context=None, meli=False, config=None ):

        context = context or self.env.context
        #_logger.info("meli_oerp_multiple product_post_price context: " + str(context))
        company = self.env.user.company_id
        warningobj = self.env['meli.warning']

        product_obj = self.env['product.product']
        product = self
        product_tmpl = self.product_tmpl_id


        if not config or not meli:
            #from user interface in forms... no parameters
            for bind in product.mercadolibre_bindings:
                bind.product_post_price(meli=meli)
            return {}


        #standard version meli_oerp
        config = config or company


        if not meli or not hasattr(meli, 'client_id'):
            account = self._meli_resolve_account(config)
            meli = self.env['meli.util'].get_new_instance( account.company_id, account)
            if meli.need_login():
                return meli.redirect_login()

        meli_id = product.meli_id
        meli_id_variation = product.meli_id_variation

        return product.x_product_post_price(context=context,meli=meli, config=config, meli_id=meli_id, meli_id_variation=meli_id_variation )

    def product_post_title( self, context=None, meli=False, config=None ):
        # Override multi-cuenta de product_post_title. Desde el wizard (sin config)
        # itera las bindings del producto y delega el PUT del título en cada una.
        # Con config+meli (llamada interna) delega en el metodo base (single item).
        context = context or self.env.context
        product = self

        if not config or not meli:
            #from user interface / wizard: no config param -> iterar bindings
            for bind in product.mercadolibre_bindings:
                r = bind.product_post_title(meli=meli)
                if r and isinstance(r, dict) and 'error' in r:
                    return r
            return {}

        #standard version meli_oerp (single item, con meli+config resueltos)
        return super().product_post_title(context=context, meli=meli)

    def _fetch_meli_user_product_id( self, meli_id=None, meli_id_variation=None, meli=False, config=False, item_json=None ):
        #SUPPORT MULTIPLE ACCOUNTS
        #_logger.info("meli_oerp_multiple > _fetch_meli_user_product_id > meli_id:"+str(meli_id)+" meli_id_variation:"+str(meli_id_variation))
        
        upid = None      
        product = self
        meli_id = meli_id or product.meli_id
        
        if not meli_id:
            return upid
        
        if not item_json:
            if not config:
                return upid            
            
            account = config.connection_account

            if not account:
                return upid                    
            
            if not meli:
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            item_json = account and meli_id and meli and account.fetch_meli_product( meli_id=meli_id, meli=meli )

        return super( product_product, self)._fetch_meli_user_product_id( meli_id=meli_id, meli_id_variation=meli_id_variation, meli=meli, config=config, item_json=item_json )

    def _meli_update_logistic_type(self, meli_id=None, meli=False, config=False, rjson=None):

        company = self.env.user.company_id
        product = self
        config = config or company

        company = (config and 'company_id' in config._fields and config.company_id) or company
        account = self._meli_resolve_account(config)

        meli_id = meli_id or product.meli_id

        if not meli_id:
            return ""

        if not meli:
            meli = self.get_meli_from_product( meli_id=meli_id, meli=meli)

        if not meli:
            return ""

        try:
            if not rjson:
                rjson = account and meli_id and meli and account.fetch_meli_product( meli_id=meli_id, meli=meli )

        except IOError as ioe:
            #_logger.info( "I/O error({0}): {1}".format(e.errno, e.strerror) )
            return ""
        except Exception as E:
            #_logger.info( "Rare error" )
            return ""

        if (rjson and "shipping" in rjson and "logistic_type" in rjson["shipping"]):
            meli_shipping_logistic_type = rjson["shipping"]["logistic_type"] or ""
            
            #calling with meli_id_variation=None will bring any user_product_id in any variations
            has_user_product_id = product._fetch_meli_user_product_id( meli_id=meli_id, 
                                                                    meli_id_variation=None, 
                                                                    meli=meli, 
                                                                    config=config, 
                                                                    item_json=rjson )
            if ( has_user_product_id ):
                meli_shipping_logistic_type+="_user_product_id"

            if meli_id==product.meli_id:
                #update product meli_shipping_logistic_type if meli_id binding match the base product
                product.meli_shipping_logistic_type = meli_shipping_logistic_type

            #Update meli_shipping_logistic_type for all meli_id bindings and parent binding template
            bindings = self.env["mercadolibre.product"].search( [ ('product_id','=' ,product.id ), ('conn_id','=' ,str(meli_id) )] )
            for bind in bindings:
                bind.meli_shipping_logistic_type = meli_shipping_logistic_type
                bind.binding_product_tmpl_id.meli_shipping_logistic_type = meli_shipping_logistic_type

            return meli_shipping_logistic_type
        return ""

    # Threshold for switching to SQL-only mode (skip ORM for large batches)
    MELI_LARGE_BATCH_THRESHOLD = 100
    # Chunk size for processing large batches
    MELI_CHUNK_SIZE = 500

    def process_meli_stock_moves_update( self ):
        """
        OPTIMIZED for scale: handles from 1 to 10,000+ products efficiently.

        Strategy by scale:
        - Small batches (<100): Use ORM for accurate computed field updates
        - Large batches (>=100): Use SQL-only for speed, let cron handle status

        The key insight: during stock moves, we just need to mark products as
        "needs sync" with a timestamp. The actual MeLi API sync happens via cron.
        """
        import time
        t_start = time.time()

        if not self:
            return

        product_count = len(self)
        _logger.info("MELI_BENCHMARK process_meli_stock_moves_update START: %d products", product_count)

        # Choose strategy based on batch size
        if product_count < self.MELI_LARGE_BATCH_THRESHOLD:
            # Small batch: use ORM for full accuracy
            self._process_stock_update_orm()
        else:
            # Large batch: use SQL-only for speed
            self._process_stock_update_sql_only()

        t_total = time.time() - t_start
        _logger.info(
            "MELI_BENCHMARK process_meli_stock_moves_update END: %d products in %.3fs (%.1f products/sec)",
            product_count, t_total, product_count / t_total if t_total > 0 else 0
        )

    def _process_stock_update_orm(self):
        """
        ORM-based update for smaller batches. More accurate but slower.
        Used when product count < MELI_LARGE_BATCH_THRESHOLD.
        """
        import time
        t1 = time.time()

        # Step 1: Update all product stock move dates (from meli_oerp base)
        for var in self:
            var._meli_stock_moves_update()
        t1_end = time.time()

        # Step 2: Batch search for all bindings in one query
        t2 = time.time()
        pv_binds = self.env["mercadolibre.product"].sudo().search([
            ("product_id", "in", self.ids)
        ])
        t2_end = time.time()

        # Step 3: Process all bindings at once
        t3 = time.time()
        if pv_binds:
            pv_binds.process_meli_stock_moves_update()
        t3_end = time.time()

        _logger.info(
            "MELI_BENCHMARK _process_stock_update_orm: products=%d, bindings=%d, "
            "update_products=%.3fs, search_bindings=%.3fs, update_bindings=%.3fs",
            len(self), len(pv_binds), t1_end - t1, t2_end - t2, t3_end - t3
        )

    def _process_stock_update_sql_only(self):
        """
        SQL-only update for large batches (100+ products).
        MUCH faster but skips ORM computed fields.

        Strategy:
        1. Update product.meli_stock_moves_update via SQL
        2. Update binding.meli_stock_moves_update via SQL
        3. Update binding.meli_stock_status to 'update' via SQL
        4. Let the cron job handle the actual sync

        For 10,000 products, this runs in ~0.5s instead of 60+ seconds.
        """
        import time
        t_start = time.time()

        product_ids = self.ids
        product_count = len(product_ids)

        # Process in chunks to avoid memory issues and allow progress logging
        chunk_size = self.MELI_CHUNK_SIZE
        total_bindings_updated = 0

        for i in range(0, product_count, chunk_size):
            chunk_ids = product_ids[i:i + chunk_size]
            chunk_num = (i // chunk_size) + 1
            total_chunks = (product_count + chunk_size - 1) // chunk_size

            t_chunk = time.time()

            # Step 1: SQL UPDATE for products - set meli_stock_moves_update to NOW()
            self.env.cr.execute("""
                UPDATE product_product
                SET meli_stock_moves_update = NOW() AT TIME ZONE 'UTC'
                WHERE id IN %s
            """, (tuple(chunk_ids),))

            # Step 2: SQL UPDATE for bindings - sync dates from product
            self.env.cr.execute("""
                UPDATE mercadolibre_product mp
                SET meli_stock_moves_update = NOW() AT TIME ZONE 'UTC',
                    product_meli_stock_moves_update = NOW() AT TIME ZONE 'UTC'
                WHERE mp.product_id IN %s
            """, (tuple(chunk_ids),))
            bindings_in_chunk = self.env.cr.rowcount

            # Step 3: SQL UPDATE for binding status - mark as 'update' if stock needs sync
            # This ensures they'll be picked up by the cron
            # Update for any status that's not in an error state (revision_error, revision_blocked, etc)
            self.env.cr.execute("""
                UPDATE mercadolibre_product
                SET meli_stock_status = 'update'
                WHERE product_id IN %s
                AND meli_stock_status IN (
                    'updated', 'updated_with_warning', 'revision_unmoved', 'revision'
                )
            """, (tuple(chunk_ids),))

            total_bindings_updated += bindings_in_chunk

            t_chunk_end = time.time()
            _logger.info(
                "MELI_BENCHMARK _process_stock_update_sql_only chunk %d/%d: "
                "products=%d, bindings=%d, time=%.3fs",
                chunk_num, total_chunks, len(chunk_ids), bindings_in_chunk, t_chunk_end - t_chunk
            )

        # Invalidate ORM caches
        self.env['product.product'].invalidate_model(['meli_stock_moves_update'])
        self.env['mercadolibre.product'].invalidate_model([
            'meli_stock_moves_update', 'product_meli_stock_moves_update', 'meli_stock_status'
        ])

        t_total = time.time() - t_start
        _logger.info(
            "MELI_BENCHMARK _process_stock_update_sql_only COMPLETE: "
            "products=%d, bindings=%d, total_time=%.3fs, rate=%.0f products/sec",
            product_count, total_bindings_updated, t_total,
            product_count / t_total if t_total > 0 else 0
        )


class PricelistItem(models.Model):

    _inherit = "product.pricelist.item"

    @api.onchange('applied_on', 'product_id', 'product_tmpl_id', 'min_quantity','price')
    def _meli_onchange_pricelist_item(self):
        #set meli_price_update to False
        for pli in self:
            if pli.product_tmpl_id:
                pli.product_tmpl_id.meli_price_update = False
                for bind_tpl in pli.product_tmpl_id.mercadolibre_bindings:
                    bind_tpl.price_update = False

                for var in pli.product_tmpl_id.product_variant_ids:
                    var.meli_price_update = False
                    for bind in var.mercadolibre_bindings:
                        bind.price_update = False

            if pli.product_id:

                pli.product_id.meli_price_update = False
                pli.product_id.product_tmpl_id.meli_price_update = False

                for bind in pli.product_id.mercadolibre_bindings:
                    bind.price_update = False
