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
###############################################*###############################

from odoo import fields, models, api
from odoo.tools.translate import _
from odoo.tools import html_escape
from datetime import timedelta
import logging
_logger = logging.getLogger(__name__)
import pdb
import re
import threading
#from .warning import warning
import requests
try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode
from . import versions
from .versions import *
from odoo.addons.meli_oerp.models.versions import *
import json
from odoo.tools import date_utils

try:
    json_default = date_utils.json_default
except:
    from odoo.tools import json_default
    pass;

import base64

import hashlib
from datetime import datetime
from markupsafe import Markup


class MercadoLibreBrand(models.Model):

    _name = 'mercadolibre.brand'
    _description = 'MercadoLibre Brand'

    name = fields.Char(string="Name",required=True,index=True)

    #https://api.mercadolibre.com/users/609389670/brands
    official_store_id = fields.Char(string="Official Store Id",required=True,index=True)
    site_id = fields.Char(string="Site Id",required=True,index=True)
    seller_id = fields.Char(string="Seller id",required=True,index=True)

    fantasy_name = fields.Char(string="Fantasy Name",required=True,index=True)
    status = fields.Char(string="Status",required=True,index=True)
    type = fields.Char(string="Type",required=True,index=True)

    permalink = fields.Char(string="Permalink",required=True,index=True)


class MercadoLibreMaestro(models.Model):

    _name = 'mercadolibre.product.maestro'
    _description = 'MercadoLibre Product Maestro'

    connection_account = fields.Many2one("mercadolibre.account",string="Account")
    company_id = fields.Many2one("res.company",related="connection_account.company_id",string="Company")

    name = fields.Char(string="Name",required=True, index=True)
    description = fields.Char(string="Description",index=True)

    brand = fields.Char(string="Brand", index=True)
    model = fields.Char(string="Model", index=True)

    length = fields.Char(string="Length", index=True)
    height = fields.Char(string="Height", index=True)
    width = fields.Char(string="Width", index=True)
    weight = fields.Char(string="Weight", index=True)

    attributes = fields.Char(string="Atributos",index=True)

    sku = fields.Char(string="Sku",help="Referencia interna / Seller SKU",index=True)
    barcode = fields.Char(string="Barcode", help="Codigo de barras", index=True)

    # SKU Post: buffer de SKU pendiente de empujar a ML.
    # Permite cargar SKUs desde planilla sin pisar el `sku` actual hasta que el
    # push contra ML sea exitoso. Es el reemplazo del flujo de planilla xlsx en
    # mercadolibre.com que rompe SKUs por auto-formato de Excel.
    sku_post = fields.Char(
        string="SKU a publicar",
        help="SKU pendiente de empujar a MercadoLibre. Se carga vía wizard o "
             "manualmente. Aplicar con la acción 'Aplicar SKU pendiente'. "
             "Vacío = sin pendiente.",
        index=True,
    )
    sku_post_state = fields.Selection(
        [
            ('draft',   'Pendiente'),
            ('pushed',  'Aplicado en ML'),
            ('failed',  'Falló'),
            ('skipped', 'Omitido (catálogo)'),
        ],
        string="Estado SKU Post",
        default='draft',
        index=True,
    )
    sku_post_log = fields.Char(
        string="Resultado SKU Post",
        help="Mensaje del último intento de push (ok / error / código HTTP)."
    )
    sku_post_date = fields.Datetime(string="Fecha SKU Post")

    barcode0 = fields.Char(string="Barcode0",help="LDM/Combo Barcode[0-10]",index=True)
    quantity0 = fields.Float(string="Quantity0")

    barcode1 = fields.Char(string="Barcode1",help="LDM/Combo Barcode[0-10]",index=True)
    quantity1 = fields.Float(string="Quantity1")

    barcode2 = fields.Char(string="Barcode2",help="LDM/Combo Barcode[0-10]",index=True)
    quantity2 = fields.Float(string="Quantity2")

    barcode3 = fields.Char(string="Barcode3",help="LDM/Combo Barcode[0-10]",index=True)
    quantity3 = fields.Float(string="Quantity3")

    barcode4 = fields.Char(string="Barcode4",help="LDM/Combo Barcode[0-10]",index=True)
    quantity4 = fields.Float(string="Quantity4")

    barcode5 = fields.Char(string="Barcode5",help="LDM/Combo Barcode[0-10]",index=True)
    quantity5 = fields.Float(string="Quantity5")

    barcode6 = fields.Char(string="Barcode6",help="LDM/Combo Barcode[0-10]",index=True)
    quantity6 = fields.Float(string="Quantity6")

    barcode7 = fields.Char(string="Barcode7",help="LDM/Combo Barcode[0-10]",index=True)
    quantity7 = fields.Float(string="Quantity7")

    barcode8 = fields.Char(string="Barcode8",help="LDM/Combo Barcode[0-10]",index=True)
    quantity8 = fields.Float(string="Quantity8")

    barcode9 = fields.Char(string="Barcode9",help="LDM/Combo Barcode[0-10]",index=True)
    quantity9 = fields.Float(string="Quantity9")

    barcode10 = fields.Char(string="Barcode10",help="LDM/Combo Barcode[0-10]",index=True)
    quantity10 = fields.Float(string="Quantity10")



    barcodes = fields.Char(string="Barcodes (ML)",help="Barcodes de la publicacione en ML",index=True)
    skus = fields.Char(string="Skus",index=True)
    stock = fields.Float(string="Stock",index=True)
    meli_id = fields.Char(string="Meli Id", index=True)
    meli_id_variation = fields.Char(string="Meli Id Variation", index=True)
    meli_status = fields.Char(string="Estado publicación ML", index=True,
                              help="Estado de la publicación en MercadoLibre (active, paused, closed, under_review, inactive, not_available)")
    meli_permalink = fields.Char(string="Permalink ML",
                                 help="URL de la publicación en MercadoLibre")
    last_updated = fields.Datetime(string="Última actualización maestro",
                                   help="Fecha y hora de la última vez que se actualizó este registro desde ML")

    is_valid = fields.Boolean(string="Validez",default=False,index=True)


    def calculate_variations_status( self, meli=None ):
        self.calculate_variations(meli=meli)

    #@api.depends('meli_id')
    def calculate_variations( self, meli=None ):
        account = None
        meli = meli
        for p in self:
            p.meli_id_variations = None
            p.meli_id_variations_number = 0
            meli_id = p.meli_id
            if ( not ( account == p.connection_account )):
                account = p.connection_account
                meli = None
                if not meli:
                    company = account.company_id or account.env.user.company_id
                    ac_official_store_id = account.official_store_id
                    seller_id = account.seller_id
                    meli = self.env['meli.util'].get_new_instance( company, account )

            rjson = account.fetch_meli_product( meli_id = meli_id, meli=meli )

            # Detectar publicación no disponible
            if not rjson or (isinstance(rjson, dict) and ('error' in rjson or rjson.get('status') in ('closed', 'inactive', 'under_review'))):
                p.meli_status = rjson.get('status', 'not_available') if rjson and isinstance(rjson, dict) else 'not_available'
                p.meli_permalink = ''
                p.last_updated = fields.Datetime.now()
                p.meli_id_variations = '[]'
                p.meli_id_variations_number = 0
                p.barcodes = False
                p.skus = False
                p.is_valid = False
                p.status = 'not_available'
                p.is_sku_odoo = False
                p.is_barcode_odoo = False
                continue

            # Actualizar estado y permalink desde ML
            p.meli_status = rjson.get('status', '')
            p.meli_permalink = rjson.get('permalink', '')
            p.last_updated = fields.Datetime.now()

            p.meli_id_variations = (rjson and "variation_ids" in rjson and rjson["variation_ids"]) or '[]'
            p.meli_id_variations_number = (rjson and "variations" in rjson and len(rjson["variations"])) or 0.0
            p.barcodes = (rjson and "barcodes" in rjson and rjson["barcodes"]!='[]' and rjson["barcodes"]) or (rjson and "barcode" in rjson and rjson["barcode"])
            p.skus = (rjson and "seller_skus" in rjson and rjson["seller_skus"])or (rjson and "seller_sku" in rjson and rjson["seller_sku"])

            # Self-heal sku/barcode on the maestro record itself.
            # If the stored sku/barcode is empty or the "--SIN SKU--" / "--SIN BARCODE--"
            # placeholder, try to extract the real value from rjson for THIS variation
            # (or the whole publication when meli_id_variation is not set).
            # This recovers maestros that were created before the publication had SKUs
            # loaded on ML, or when record_maestro_review ran with incomplete rjson.
            if rjson:
                _cur_sku = (p.sku or '').strip()
                _cur_barcode = (p.barcode or '').strip()
                _sku_missing = (not _cur_sku) or _cur_sku == "--SIN SKU--"
                _barcode_missing = (not _cur_barcode) or _cur_barcode == "--SIN BARCODE--"
                # Tambien re-curamos cuando el SKU/barcode almacenado ya NO coincide
                # con lo que ML reporta (p.skus / p.barcodes recien traidos). Esto cubre
                # el caso "el cliente cambio el SKU en ML": el maestro tenia un SKU valido
                # pero ahora obsoleto -> is_valid se cae y hay que traer el nuevo valor.
                _skus_live = p.skus or ''
                _barcodes_live = p.barcodes or ''
                _sku_stale = bool(_cur_sku) and not _sku_missing and bool(_skus_live) and (_cur_sku not in str(_skus_live))
                _barcode_stale = bool(_cur_barcode) and not _barcode_missing and bool(_barcodes_live) and (_cur_barcode not in str(_barcodes_live))
                _sku_missing = _sku_missing or _sku_stale
                _barcode_missing = _barcode_missing or _barcode_stale
                if _sku_missing or _barcode_missing:
                    if p.meli_id_variation:
                        _heal_sku = account.fetch_meli_sku(
                            meli_id=meli_id, meli_id_variation=p.meli_id_variation,
                            meli=meli, rjson=rjson
                        )
                        _heal_barcode = account.fetch_meli_barcode(
                            meli_id=meli_id, meli_id_variation=p.meli_id_variation,
                            meli=meli, rjson=rjson
                        )
                    else:
                        _heal_sku = account.fetch_meli_sku(
                            meli_id=meli_id, meli_id_variation=None,
                            meli=meli, rjson=rjson
                        )
                        _heal_barcode = account.fetch_meli_barcode(
                            meli_id=meli_id, meli_id_variation=None,
                            meli=meli, rjson=rjson
                        )
                        # For single products these should be strings, not lists
                        if isinstance(_heal_sku, list):
                            _heal_sku = _heal_sku[0] if _heal_sku else None
                        if isinstance(_heal_barcode, list):
                            _heal_barcode = _heal_barcode[0] if _heal_barcode else None
                    if _heal_sku and _sku_missing:
                        p.sku = _heal_sku
                        # Drop the <C><I> invalid marker if present in the name
                        if p.name and "<C><I>" in p.name:
                            p.name = p.name.replace("<C><I>", "<C>")
                    if _heal_barcode and _barcode_missing:
                        p.barcode = _heal_barcode
            #p.is_valid = (p.barcode and p.barcodes and p.barcode in p.barcodes)
            p.is_valid = True
            p.is_valid = p.is_valid and (p.sku and p.skus and p.sku in p.skus)
            #_logger.info("is_valid:"+str(p.is_valid)+" sku <"+str(p.sku)+"> skus <"+str(p.skus)+">")
            p.status = ( (p.is_valid == False and 'invalid') or
                         (p.is_valid and p.is_master and not p.is_combo and 'master_base') or
                         (p.is_valid and p.is_master and p.is_combo and 'master_combo') or
                         (p.is_valid and not p.is_master and not p.is_combo and 'clone_base') or
                         (p.is_valid and not p.is_master and p.is_combo and 'clone_combo') )
            p.is_sku_odoo = p.sku and self.env["product.product"].search([('default_code','=ilike',p.sku)],limit=1)
            p.is_barcode_odoo = p.barcode and self.env["product.product"].search([('barcode','=ilike',p.barcode)],limit=1)
            is_combo_valid = p.is_combo
            #Ya no pedimos el barcode para combos... solo sku... and p.barcode
            #ningun componente tiene el mismo barcode que el producto
            is_combo_valid = is_combo_valid and (p.barcode0 and p.barcode0 != p.barcode and p.quantity0>0 or not p.barcode0)
            is_combo_valid = is_combo_valid and (p.barcode1 and p.barcode1 != p.barcode and p.quantity1>0 or not p.barcode1)
            is_combo_valid = is_combo_valid and (p.barcode2 and p.barcode2 != p.barcode and p.quantity2>0 or not p.barcode2)
            is_combo_valid = is_combo_valid and (p.barcode3 and p.barcode3 != p.barcode and p.quantity3>0 or not p.barcode3)
            is_combo_valid = is_combo_valid and (p.barcode4 and p.barcode4 != p.barcode and p.quantity4>0 or not p.barcode4)
            is_combo_valid = is_combo_valid and (p.barcode5 and p.barcode5 != p.barcode and p.quantity5>0 or not p.barcode5)
            is_combo_valid = is_combo_valid and (p.barcode6 and p.barcode6 != p.barcode and p.quantity6>0 or not p.barcode6)
            is_combo_valid = is_combo_valid and (p.barcode7 and p.barcode7 != p.barcode and p.quantity7>0 or not p.barcode7)
            is_combo_valid = is_combo_valid and (p.barcode8 and p.barcode8 != p.barcode and p.quantity8>0 or not p.barcode8)
            is_combo_valid = is_combo_valid and (p.barcode9 and p.barcode9 != p.barcode and p.quantity9>0 or not p.barcode9)
            is_combo_valid = is_combo_valid and (p.barcode10 and p.barcode10 != p.barcode and p.quantity10>0 or not p.barcode10)
            is_combo_valid = is_combo_valid or not p.is_combo

            p.is_valid = p.is_valid and is_combo_valid
            #lista de materiales
            p.is_barcode0_odoo = p.barcode0 and self.env["product.product"].search([('barcode','=ilike',p.barcode0)],limit=1)
            p.is_barcode1_odoo = p.barcode1 and self.env["product.product"].search([('barcode','=ilike',p.barcode1)],limit=1)
            p.is_barcode2_odoo = p.barcode2 and self.env["product.product"].search([('barcode','=ilike',p.barcode2)],limit=1)
            p.is_barcode3_odoo = p.barcode3 and self.env["product.product"].search([('barcode','=ilike',p.barcode3)],limit=1)
            p.is_barcode4_odoo = p.barcode4 and self.env["product.product"].search([('barcode','=ilike',p.barcode4)],limit=1)
            p.is_barcode5_odoo = p.barcode5 and self.env["product.product"].search([('barcode','=ilike',p.barcode5)],limit=1)
            p.is_barcode6_odoo = p.barcode6 and self.env["product.product"].search([('barcode','=ilike',p.barcode6)],limit=1)
            p.is_barcode7_odoo = p.barcode7 and self.env["product.product"].search([('barcode','=ilike',p.barcode7)],limit=1)
            p.is_barcode8_odoo = p.barcode8 and self.env["product.product"].search([('barcode','=ilike',p.barcode8)],limit=1)
            p.is_barcode9_odoo = p.barcode9 and self.env["product.product"].search([('barcode','=ilike',p.barcode9)],limit=1)
            p.is_barcode10_odoo = p.barcode10 and self.env["product.product"].search([('barcode','=ilike',p.barcode10)],limit=1)


        for p in self:
            p.is_it_master()
            p._is_bom_created()
            p._is_bom_valid()

    status = fields.Selection( [('invalid','Invalido'),
                                    ('not_available','No Disponible'),
                                    ('master_base','Maestro Base'),
                                    ('master_combo','Maestro Combo'),
                                    ('clone_base','Clone Base'),
                                    ('clone_combo','Clone Combo')],
                                    string="Status",
                                    default='invalid',
                                    compute=calculate_variations_status,
                                    store=True
                                    )

    def action_open_ml_publication(self):
        """Abre la publicación de MercadoLibre en una nueva pestaña del navegador"""
        self.ensure_one()
        url = self.meli_permalink
        if not url and self.meli_id:
            url = 'https://articulo.mercadolibre.com.mx/%s' % self.meli_id
        if url:
            return {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new',
            }

    def action_open_ml_api(self):
        """Abre la vista API de la publicación en MercadoLibre con access_token"""
        self.ensure_one()
        if self.meli_id and self.connection_account:
            account = self.connection_account
            company = account.company_id or account.env.user.company_id
            meli = self.env['meli.util'].get_new_instance(company, account)
            access_token = meli.access_token if meli else ''
            url = 'https://api.mercadolibre.com/items/%s?access_token=%s' % (self.meli_id, access_token)
            return {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new',
            }

    def is_it_master( self ):
        for p in self:
            p.is_master = False;
            pobj = self.env["mercadolibre.product.maestro"]
            if p.barcode:
                #first: no combos
                pbases = pobj.search([('barcode','=',p.barcode),('is_combo','=',False)],order='id asc')
                if pbases:
                    max = 0
                    pbmax = None
                    for pb in pbases:
                        pbmax = (not pbmax and pb) or pbmax
                        #selecciona como master la publicacion con mas combinaciones de variantes en ML
                        if (pb.meli_id_variations_number>max):
                            max = pb.meli_id_variations_number
                            pbmax = pb
                        pb.is_master = False

                    #siempre que tenga SKUS y BARCODES para cada variante:
                    pbmax.is_master = True

                #second: combos
                pbasecombs = pobj.search([('barcode','like',p.barcode),('is_combo','=',True)],order='id asc')
                if pbasecombs:
                    max = 0
                    pbmax = None
                    for pb in pbasecombs:
                        pbmax = (not pbmax and pb) or pbmax
                        #selecciona como master la publicacion con mas combinaciones de variantes en ML
                        if (pb.meli_id_variations_number>max):
                            max = pb.meli_id_variations_number
                            pbmax = pb
                        pb.is_master = False

                    #siempre que tenga SKUS y BARCODES para cada variante:
                    pbmax.is_master = True
            elif p.sku:
                #first: no combos
                pbases = pobj.search([('sku','=',p.sku),('is_combo','=',False)],order='id asc')
                if pbases:
                    max = 0
                    pbmax = None
                    for pb in pbases:
                        pbmax = (not pbmax and pb) or pbmax
                        #selecciona como master la publicacion con mas combinaciones de variantes en ML
                        if (pb.meli_id_variations_number>max):
                            max = pb.meli_id_variations_number
                            pbmax = pb
                        pb.is_master = False


                    #siempre que tenga SKUS y BARCODES para cada variante:
                    pbmax.is_master = True

            p._is_sku_valid()

            if not p.barcode and p.is_combo and p.sku and p.is_sku_valid and p.barcodes and p.is_combo_valid:
                #no necesita barcode este combo?
                #si tiene barcodes definidos en ML al menos tendremos una LM valido
                #revisar si hay un combo maestro con la misma lista de materiales exacta

                #POR AHORA LO CREAMOS
                pbasecombs = pobj.search([('sku','=ilike',p.sku),('is_combo','=',True)],order='id asc')
                if pbasecombs:
                    max = 0
                    pbmax = None
                    for pb in pbasecombs:
                        pbmax = (not pbmax and pb) or pbmax
                        #selecciona como master la publicacion con mas combinaciones de variantes en ML
                        if (pb.meli_id_variations_number>max):
                            max = pb.meli_id_variations_number
                            pbmax = pb
                        pb.is_master = False
                    #
                    pbmax.is_master = True


            p._is_sku_valid()

    meli_id_variations = fields.Char(string="Variations", compute=calculate_variations, store=True, index=True)
    meli_id_variations_number = fields.Float(string="Number", compute=calculate_variations, store=True, default=0, index=True)

    is_combo = fields.Boolean(string="Combo/Kit",index=True)
    is_combo_valid = fields.Boolean(string="Combo Valido",help="El barcode del producto/publicacion no puede ser un componente, o sea existir en uno de los barcode[0-10] ",index=True)
    is_master = fields.Boolean(string="Master",index=True)

    def _is_sku_valid(self):
        for pm in self:
            pm.is_sku_valid = False
            pm.is_barcode_valid = False
            pm.is_sku_valid = pm.sku and pm.skus and pm.sku in pm.skus
            pm.is_barcode_valid = pm.barcode and pm.barcodes and pm.barcode in pm.barcodes

    is_sku_valid = fields.Boolean(string="Sku valido",help="El sku coincide con alguna publicacion",index=True)
    is_barcode_valid = fields.Boolean(string="Barcode valido",help="El barcode coincide con alguna publicacion",index=True)

    is_sku_odoo = fields.Boolean(string="Is Sku Odoo",index=True)
    is_barcode_odoo = fields.Boolean(string="Is Barcode Odoo",index=True)
    is_meli_odoo = fields.Boolean(string="Is Meli Id in Odoo",index=True)

    is_barcode0_odoo = fields.Boolean(string="Is Barcode0 Odoo",default=False,index=True)
    is_barcode1_odoo = fields.Boolean(string="Is Barcode1 Odoo",default=False,index=True)
    is_barcode2_odoo = fields.Boolean(string="Is Barcode2 Odoo",default=False,index=True)
    is_barcode3_odoo = fields.Boolean(string="Is Barcode3 Odoo",default=False,index=True)
    is_barcode4_odoo = fields.Boolean(string="Is Barcode4 Odoo",default=False,index=True)
    is_barcode5_odoo = fields.Boolean(string="Is Barcode5 Odoo",default=False,index=True)
    is_barcode6_odoo = fields.Boolean(string="Is Barcode6 Odoo",default=False,index=True)
    is_barcode7_odoo = fields.Boolean(string="Is Barcode7 Odoo",default=False,index=True)
    is_barcode8_odoo = fields.Boolean(string="Is Barcode8 Odoo",default=False,index=True)
    is_barcode9_odoo = fields.Boolean(string="Is Barcode9 Odoo",default=False,index=True)
    is_barcode10_odoo = fields.Boolean(string="Is Barcode10 Odoo",default=False,index=True)


    #@api.model
    #def write(self, vals):
    #    Maestro = self
    #    ret = None
    #    if (Maestro):
    #        ret = Maestro.write(vals)
    #        Maestro.calculate_variations()
    #    return ret

    @api.model_create_multi
    def create(self, vals_list):
        Maestro = super(MercadoLibreMaestro, self).create(vals_list)
        if (Maestro):
            Maestro.calculate_variations()
        return Maestro

    def _is_bom_created(self):

        bom = self.env["mrp.bom"]
        bom_l = self.env["mrp.bom.line"]

        for mas in self:

            mas.is_bom_created = False

            product_id = mas.barcode and self.env["product.product"].search([('barcode','=ilike',mas.barcode),('company_id','=',mas.company_id.id)])

            if not product_id:
                #_logger.info("barcode not founded for base product, search sku")
                product_id = mas.sku and self.env["product.product"].search([('default_code','=ilike',mas.sku),('company_id','=',mas.company_id.id)])

            if (not product_id):
                #_logger.info("default_code or barcode not founded for base product")
                continue;

            if (not mas.is_combo):
                continue;

            bom_obj = bom.search([('product_tmpl_id','=',product_id.product_tmpl_id.id),('product_id','=',product_id.id)])

            if not bom_obj:
                continue;

            mas.is_bom_created = True


    is_bom_created = fields.Boolean(string="Is LDM/Bom Created",compute=_is_bom_created,default=False,store=True,index=True)

    def _is_bom_valid(self):

        bom = self.env["mrp.bom"]
        bom_l = self.env["mrp.bom.line"]

        for mas in self:

            mas.is_bom_valid = False

            product_id = mas.barcode and self.env["product.product"].search([('barcode','=ilike',mas.barcode),('company_id','=',mas.company_id.id)])

            if not product_id:
                #_logger.info("barcode not founded for base product, search sku")
                product_id = mas.sku and self.env["product.product"].search([('default_code','=ilike',mas.sku),('company_id','=',mas.company_id.id)])

            if (not product_id):
                #_logger.info("default_code or barcode not founded for base product")
                continue;

            if (not mas.is_combo):
                continue;

            bom_obj = bom.search([('product_tmpl_id','=',product_id.product_tmpl_id.id),('product_id','=',product_id.id)])

            if not bom_obj:
                continue;

            #search for same product target bom as component product
            bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_id.id)])

            if bom_obj_l:
                mas.is_bom_valid = False
                continue;

            mas.is_bom_valid = True

    is_bom_valid = fields.Boolean(string="Is LDM/Bom Valid",compute=_is_bom_valid,default=False,store=True,index=True)

    def _product_by_sku(self):
        for mas in self:
            mas.product_by_sku = None
            mas.product_by_sku = self.env["product.product"].search([('default_code','=ilike', mas.sku)], limit=1)
            mas.product_template_by_sku = (mas.product_by_sku and mas.product_by_sku.product_tmpl_id) or None


    product_by_sku = fields.Many2one("product.product",string="Product por Sku",compute=_product_by_sku)
    product_template_by_sku = fields.Many2one("product.template",string="Product template por Sku",compute=_product_by_sku)

    def create_bom( self, product_id=None ):

        bom = self.env["mrp.bom"]
        bom_l = self.env["mrp.bom.line"]

        for mas in self:
            if (product_id==None):
                product_id = mas.barcode and self.env["product.product"].search([('barcode','=ilike',mas.barcode),('company_id','=',mas.company_id.id)])
                if not product_id:
                    #_logger.info("barcode not founded for base product, search sku")
                    product_id = mas.sku and self.env["product.product"].search([('default_code','=ilike',mas.sku),('company_id','=',mas.company_id.id)])

            if (not product_id):
                #_logger.info("default_code or barcode not founded for base product")
                continue;

            if (not mas.is_combo):
                continue;

            uomobj = self.env[uom_model]
            uomcatobj = self.env["uom.category"]
            product_uom_id = uomobj.search([('name','=ilike','Uni%')],limit=1)
            product_uom_category_id = uomcatobj.search([('name','=ilike','Uni%')],limit=1)
            if not product_uom_id:
                #_logger.info("no product_uom_id")
                continue;
            if not product_uom_category_id:
                #_logger.info("no product_uom_category_id")
                continue;

            bom_rec =  {
                'product_tmpl_id': product_id.product_tmpl_id.id,
                'product_id': product_id.id,
                "type": "phantom",
                "product_qty": 1,
                "product_uom_id": product_uom_id.id,
                "product_uom_category_id": product_uom_category_id.id
            }
            #_logger.info("sku: "+str(mas.sku))
            #_logger.info("barcode: "+str(mas.barcode))
            #_logger.info("bom_rec: "+str(bom_rec))
            bom_obj = bom.search([('product_tmpl_id','=',product_id.product_tmpl_id.id),('product_id','=',product_id.id)])
            if not bom_obj:
                bom_obj = bom.create(bom_rec)

            if not bom_obj:
                continue;


            if (mas.barcode0 and mas.quantity0>0):

                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode0)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        #_logger.info("Error! component is also the product! "+str(mas.barcode0))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity0
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )
                else:
                    _logger.info("Not found! "+str(mas.barcode0))
                    pass;

            if (mas.barcode1 and mas.quantity1>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode1)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        #_logger.info("Error! component is also the product! "+str(mas.barcode1))
                        continue;

                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity1
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )
                else:
                    _logger.info("Not found! "+str(mas.barcode1))
                    pass;

            if (mas.barcode2 and mas.quantity2>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode2)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        #_logger.info("Error! component is also the product! "+str(mas.barcode2))
                        continue;

                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity2
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )
                else:
                    _logger.info("Not found! "+str(mas.barcode2))
                    pass;

            if (mas.barcode3 and mas.quantity3>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode3)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        #_logger.info("Error! component is also the product! "+str(mas.barcode3))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity3
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )
                else:
                    _logger.info("Not found! "+str(mas.barcode3))
                    pass;

            if (mas.barcode4 and mas.quantity4>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode4)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        #_logger.info("Error! component is also the product! "+str(mas.barcode4))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity4
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )

            if (mas.barcode5 and mas.quantity5>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode5)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        _logger.error("Error! component is also the product! "+str(mas.barcode5))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity5
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )


            if (mas.barcode6 and mas.quantity6>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode6)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        _logger.error("Error! component is also the product! "+str(mas.barcode6))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity6
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )



            if (mas.barcode7 and mas.quantity7>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode7)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        _logger.error("Error! component is also the product! "+str(mas.barcode7))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity7
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )


            if (mas.barcode8 and mas.quantity8>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode8)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        _logger.error("Error! component is also the product! "+str(mas.barcode8))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity8
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )


            if (mas.barcode9 and mas.quantity9>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode9)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        _logger.error("Error! component is also the product! "+str(mas.barcode9))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity9
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )


            if (mas.barcode10 and mas.quantity10>0):
                product_bom_id = product_id.search([('barcode','=ilike',mas.barcode10)])
                if product_bom_id:
                    if (product_bom_id.id==product_id.id):
                        _logger.error("Error! component is also the product! "+str(mas.barcode10))
                        continue;
                    bom_obj_l = bom_l.search([('bom_id','=',bom_obj.id),('product_id','=',product_bom_id.id)])

                    bomline_fields = {
                        'bom_id': bom_obj.id,
                        'product_id': product_bom_id.id,
                        'product_uom_id': product_uom_id.id,
                        'product_qty': mas.quantity10
                    }
                    if (bom_obj_l):
                        bom_obj_l.write(bomline_fields)
                    else:
                        bom_l.create( bomline_fields )

        self._is_bom_created()
        self._is_bom_valid()

    def _meli_extract_effective_sku(self, item_json, variation_id=None):
        """Extrae el SKU efectivo del JSON del ítem (o variación) de ML.

        ML expone el SKU en varios lados según el tipo de ítem:
        - seller_custom_field (legacy, item level)
        - attributes[SELLER_SKU].value_name (moderno, item level)
        - variations[i].seller_sku (variación con SKU propio)
        - variations[i].attributes[SELLER_SKU].value_name
        """
        if not isinstance(item_json, dict):
            return None

        def _get_sku_from_attrs(attrs):
            for a in (attrs or []):
                if isinstance(a, dict) and a.get('id') == 'SELLER_SKU':
                    return a.get('value_name') or a.get('value_id')
            return None

        if variation_id:
            for v in (item_json.get('variations') or []):
                if str(v.get('id')) == str(variation_id):
                    if v.get('seller_sku'):
                        return v['seller_sku']
                    s = _get_sku_from_attrs(v.get('attributes'))
                    if s:
                        return s
                    break

        if item_json.get('seller_custom_field'):
            return item_json['seller_custom_field']

        s = _get_sku_from_attrs(item_json.get('attributes'))
        if s:
            return s

        if item_json.get('seller_sku'):
            return item_json['seller_sku']

        return None

    def _meli_push_sku_strategies(self, meli, sku_value):
        """Genera lista de (descripcion, path, body) a intentar en orden.

        Cubre los 3 casos conocidos:
        1. Item simple regular: PUT /items/{id} con seller_custom_field + attribute.
        2. Item con variación: PUT /items/{id} con variations[].attributes.
        3. Item con user_product_id: PUT /user-products/{up_id} con attribute.
        """
        self.ensure_one()
        item_attr_body = {
            "seller_custom_field": str(sku_value),
            "attributes": [{"id": "SELLER_SKU", "value_name": str(sku_value)}],
        }
        strategies = []

        if self.meli_id_variation:
            var_body = {
                "variations": [{
                    "id": str(self.meli_id_variation),
                    "attributes": [{"id": "SELLER_SKU", "value_name": str(sku_value)}],
                }]
            }
            strategies.append(("variation_attr", "/items/%s" % self.meli_id, var_body))
        else:
            strategies.append(("item_combo", "/items/%s" % self.meli_id, item_attr_body))

        return strategies

    def _meli_get_item(self, meli, meli_id):
        """GET /items/{meli_id} fresco (sin cache). Devuelve dict o {}."""
        try:
            resp = meli.get("/items/%s" % meli_id,
                            {'access_token': meli.access_token})
            return (resp and resp.rjson) or {}
        except Exception as e:
            _logger.warning("get_item %s failed: %s", meli_id, e)
            return {}

    def action_apply_sku_post(self):
        """Aplica el SKU pendiente (sku_post) contra MercadoLibre.

        Estrategia:
        1. PUT al item (o variación) con seller_custom_field + attribute SELLER_SKU.
        2. GET para VERIFICAR que el SKU efectivo quedó seteado.
        3. Si no quedó y el ítem tiene user_product_id: PUT a
           /user-products/{up_id} con el atributo SELLER_SKU y re-verifica.
        4. Solo se marca 'pushed' si el GET confirma. Cualquier otra cosa va
           a 'failed' con el cuerpo de la respuesta y el SKU efectivo actual
           guardado en sku_post_log para diagnóstico.
        """
        import time as _time
        BATCH = 50

        records = self.filtered(
            lambda r: r.sku_post and r.sku_post_state == 'draft' and r.meli_id
        )
        if not records:
            return True

        meli_by_account = {}

        def _get_meli(account):
            if account.id in meli_by_account:
                return meli_by_account[account.id]
            company = account.company_id or self.env.user.company_id
            meli = self.env['meli.util'].get_new_instance(company, account)
            if meli and meli.need_login():
                meli_by_account[account.id] = None
                return None
            meli_by_account[account.id] = meli
            return meli

        processed = 0
        for rec in records:
            account = rec.connection_account
            if not account:
                rec.write({
                    'sku_post_state': 'failed',
                    'sku_post_log': 'Sin connection_account',
                    'sku_post_date': fields.Datetime.now(),
                })
                continue

            meli = _get_meli(account)
            if not meli:
                rec.write({
                    'sku_post_state': 'failed',
                    'sku_post_log': 'Cuenta requiere login en ML',
                    'sku_post_date': fields.Datetime.now(),
                })
                continue

            sku_target = str(rec.sku_post).strip()
            log_parts = []
            verified = False
            fresh = {}

            try:
                # Estrategia 1: PUT al item (o variación)
                for label, path, body in rec._meli_push_sku_strategies(meli, sku_target):
                    resp = meli.put(path, body, {'access_token': meli.access_token})
                    rjson = (resp and resp.rjson) or {}
                    log_parts.append("%s -> %s" % (label, str(rjson)[:120]))
                    # ML a veces responde 200 sin error pero sin persistir.
                    # Verificamos con GET.
                    _time.sleep(0.15)
                    fresh = rec._meli_get_item(meli, rec.meli_id)
                    effective = rec._meli_extract_effective_sku(
                        fresh, variation_id=rec.meli_id_variation
                    )
                    log_parts.append("verify item -> %s" % str(effective))
                    if effective and str(effective).strip() == sku_target:
                        verified = True
                        break

                # Estrategia 2 (fallback): si el ítem tiene user_product_id,
                # empujar contra /user-products/{up_id}.
                if not verified:
                    if not fresh:
                        fresh = rec._meli_get_item(meli, rec.meli_id)
                    up_id = fresh.get('user_product_id') if isinstance(fresh, dict) else None
                    if up_id:
                        up_body = {
                            "attributes": [{"id": "SELLER_SKU", "value_name": sku_target}]
                        }
                        up_path = "/user-products/%s" % up_id
                        resp = meli.put(up_path, up_body, {'access_token': meli.access_token})
                        rjson = (resp and resp.rjson) or {}
                        log_parts.append("user_product %s -> %s" % (up_id, str(rjson)[:120]))
                        _time.sleep(0.15)
                        fresh2 = rec._meli_get_item(meli, rec.meli_id)
                        effective2 = rec._meli_extract_effective_sku(
                            fresh2, variation_id=rec.meli_id_variation
                        )
                        log_parts.append("verify after user_product -> %s" % str(effective2))
                        if effective2 and str(effective2).strip() == sku_target:
                            verified = True

                if verified:
                    rec.write({
                        'sku': sku_target,
                        'sku_post_state': 'pushed',
                        'sku_post_log': 'OK (verificado en ML)',
                        'sku_post_date': fields.Datetime.now(),
                    })
                else:
                    rec.write({
                        'sku_post_state': 'failed',
                        'sku_post_log': (' | '.join(log_parts))[:240],
                        'sku_post_date': fields.Datetime.now(),
                    })

            except Exception as e:
                _logger.error("action_apply_sku_post error meli_id=%s: %s",
                              rec.meli_id, e)
                rec.write({
                    'sku_post_state': 'failed',
                    'sku_post_log': str(e)[:240],
                    'sku_post_date': fields.Datetime.now(),
                })

            processed += 1
            _time.sleep(0.1)
            if processed % BATCH == 0:
                self.env.cr.commit()

        return True

    def action_reset_sku_post(self):
        """Resetea el estado a 'draft' para reintentar (sin tocar sku_post)."""
        for rec in self:
            if rec.sku_post:
                rec.sku_post_state = 'draft'
                rec.sku_post_log = False
        return True

    def action_verify_sku_post(self):
        """Verifica contra ML el SKU efectivo de registros pushed o pendientes.

        Útil para auditar 'pushed' que en realidad no quedaron seteados (caso
        clásico: ML responde 200 pero ignora el cambio en ítems con
        user_product_id). Si el SKU efectivo NO coincide con sku_post, vuelve
        a 'draft' con el log explicando qué encontró.
        """
        meli_by_account = {}

        def _get_meli(account):
            if account.id in meli_by_account:
                return meli_by_account[account.id]
            company = account.company_id or self.env.user.company_id
            meli = self.env['meli.util'].get_new_instance(company, account)
            if meli and meli.need_login():
                meli_by_account[account.id] = None
                return None
            meli_by_account[account.id] = meli
            return meli

        for rec in self.filtered(lambda r: r.meli_id and r.sku_post):
            account = rec.connection_account
            if not account:
                continue
            meli = _get_meli(account)
            if not meli:
                continue
            fresh = rec._meli_get_item(meli, rec.meli_id)
            effective = rec._meli_extract_effective_sku(
                fresh, variation_id=rec.meli_id_variation
            )
            target = str(rec.sku_post).strip()
            if effective and str(effective).strip() == target:
                if rec.sku_post_state != 'pushed':
                    rec.write({
                        'sku': target,
                        'sku_post_state': 'pushed',
                        'sku_post_log': 'OK (verificado por re-fetch)',
                        'sku_post_date': fields.Datetime.now(),
                    })
            else:
                rec.write({
                    'sku_post_state': 'draft',
                    'sku_post_log': "ML reporta sku=%s (esperado %s)" % (
                        str(effective)[:60], target[:60]
                    ),
                    'sku_post_date': fields.Datetime.now(),
                })
        return True

    def action_clear_sku_post(self):
        """Limpia sku_post y resetea estado. Usar para descartar pendientes."""
        self.write({
            'sku_post': False,
            'sku_post_state': 'draft',
            'sku_post_log': False,
            'sku_post_date': False,
        })
        return True


class MercadoLibreConnectionAccount(models.Model):

    _name = "mercadolibre.account"
    _description = "MercadoLibre Account"
    _inherit = "ocapi.connection.account"

    def get_connector_version(self):
        for acc in self:
            acc.connector_version = ''
            version_module_query = """select name, latest_version from ir_module_module where name like '%s'""" % (str("meli_oerp_multiple"))
            cr = MeliCr( self )
            resquery = cr.execute(version_module_query)
            version_module_res = cr.fetchall()
            if version_module_res:
                acc.connector_version = str(version_module_res[0][1])

    connector_version = fields.Char( compute=get_connector_version, string='Connector Version', help="Versión de este conector", store=False )

    configuration = fields.Many2one( "mercadolibre.configuration", string="Connection Parameters Configuration", help="Connection Parameters Configuration", required=True  )
    #type = fields.Selection([("custom","Custom"),("mercadolibre","MercadoLibre")],string='Connector',index=True)
    type = fields.Selection(selection_add=[("mercadolibre","MercadoLibre")],
				string='Connector Type',
				default="mercadolibre",
				ondelete={'mercadolibre': 'set default'},
				index=True,
				required=True)
    country_id = fields.Many2one("res.country",string="Country",index=True, required=True)

    refresh_token = fields.Char(string='Refresh Token', help='Refresh Token',size=128)
    access_token_expires_at = fields.Datetime(
        string='Access Token Expires At',
        help='Momento en que vence el access_token actual (ML informa expires_in=21600s = 6h). Se usa para refresh proactivo 15 min antes del vencimiento.'
    )
    meli_login_id = fields.Char( string="Meli Login Id", help="https://compania.odoo.com/meli_login/{Meli Login Id}  Por ejemplo, si el Redirect Uri es: https://compania.odoo.com/meli_login/micanaluno el Meli Login Id es: micanaluno", index=True, required=True)
    redirect_uri = fields.Char( string='Redirect Uri', help='Redirect uri (https://myodoodomain.com/meli_login/[meli_login_id])',size=1024, index=True, required=True)
    http_proxy = fields.Char(
        string='Host API ML (rescate)',
        help='Reemplaza api.mercadolibre.com por un reverse proxy externo para esta cuenta. '
             'Tiene prioridad sobre el campo de empresa. '
             'Formato: http://proxy.example.com',
        size=512,
    )
    cron_refresh = fields.Boolean(string="Cron Refresh", index=True)
    code = fields.Char( string="Code", index=True)
    official_store_id = fields.Char(string="Official Store Id",related="configuration.mercadolibre_official_store_id")

    user_product_seller = fields.Boolean( string='User Product Seller', index=True)
    multiwarehouse = fields.Boolean( string='Multi Warehouse Seller', index=True,
        help='Usa múltiples depósitos en ML')
    meli_stock_location_ids = fields.One2many(
        'mercadolibre.account.stock_location',
        'account_id',
        string='Depósitos ML (stock_location)',
        help='Depósitos/stores de ML con tag stock_location, sincronizados desde la API.',
    )

    meli_additional_seller_ids = fields.Char(
        string="Sellers adicionales",
        help="IDs separados por coma (multi-seller)"
    )

    meli_cron_log_chatter = fields.Boolean(
        string="Log CRON en Chatter",
        default=False,
        help="Ver logs del CRON en chatter"
    )

    meli_cron_stock_top_commit = fields.Integer(
        string="Top Commit (Stock)",
        default=40,
        help="Máx productos por ejecución (default: 40)"
    )

    meli_cron_price_top_commit = fields.Integer(
        string="Batch Size (Price)",
        default=80,
        help="Cantidad de productos a procesar por lote en el batch de precios"
    )

    meli_cron_price_batch_hour = fields.Selection(
        [(str(i), '%02d hs' % i) for i in range(24)] + [('-1', 'Deshabilitado')],
        string="Hora batch precio",
        default='-1',
        help="Hora del día para iniciar el batch diario de precios. Deshabilitado = no usa batch"
    )

    meli_cron_price_batch_minute = fields.Selection(
        [(str(i), '%02d min' % i) for i in range(60)],
        string="Minuto batch precio",
        default='0',
        help="Minuto de la hora para iniciar el batch diario de precios"
    )

    meli_cron_price_batch_running = fields.Boolean(
        string="Batch de precio en curso",
        default=False,
    )

    meli_cron_price_batch_date = fields.Datetime(
        string="Fin del último batch",
        help="Fecha/hora del último batch de precio completado"
    )

    meli_cron_price_batch_started = fields.Datetime(
        string="Inicio del batch actual",
        help="Fecha/hora exacta de inicio del batch en curso"
    )

    meli_cron_price_batch_last_display = fields.Char(
        string="Último batch",
        compute="_compute_batch_last_display",
        store=False,
    )

    meli_cron_price_batch_total = fields.Integer(
        string="Total items en batch",
        default=0,
    )

    meli_cron_price_batch_processed = fields.Integer(
        string="Items procesados en batch",
        default=0,
    )

    @api.depends('meli_cron_price_batch_started', 'meli_cron_price_batch_date',
                 'meli_cron_price_batch_running', 'meli_cron_price_batch_processed',
                 'meli_cron_price_batch_total')
    def _compute_batch_last_display(self):
        for acc in self:
            if acc.meli_cron_price_batch_running and acc.meli_cron_price_batch_started:
                started = acc.meli_cron_price_batch_started.strftime('%d/%m %H:%M')
                prog = '%d/%d' % (acc.meli_cron_price_batch_processed, acc.meli_cron_price_batch_total)
                acc.meli_cron_price_batch_last_display = 'En curso desde %s (%s)' % (started, prog)
            elif acc.meli_cron_price_batch_date and acc.meli_cron_price_batch_started:
                started = acc.meli_cron_price_batch_started.strftime('%d/%m %H:%M')
                ended = acc.meli_cron_price_batch_date.strftime('%H:%M')
                acc.meli_cron_price_batch_last_display = '%s → %s' % (started, ended)
            elif acc.meli_cron_price_batch_date:
                acc.meli_cron_price_batch_last_display = acc.meli_cron_price_batch_date.strftime('%d/%m/%Y %H:%M')
            else:
                acc.meli_cron_price_batch_last_display = ''

    def action_reset_price_batch(self):
        """Reset the price batch state (stop a runaway batch)."""
        self.write({
            'meli_cron_price_batch_running': False,
            'meli_cron_price_batch_date': fields.Datetime.now(),
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Batch reseteado',
                'message': 'El batch de precios fue detenido. El próximo batch iniciará a la hora configurada.',
                'type': 'success',
                'sticky': False,
            }
        }

    meli_cron_stock_minutes = fields.Char(
        string="Minutos de ejecución",
        default="",
        help="Ej: 0,15,30,45 (vacío=default)"
    )

    meli_cron_stock_timeout = fields.Float(
        string="Timeout POST (seg)",
        default=10.0,
        help="Timeout por POST (default: 10s)"
    )

    # CRON timing statistics - per publication average
    meli_cron_stock_avg_min = fields.Float(
        string="Prom. mín (seg)",
        readonly=True,
        help="Mín histórico por publicación"
    )

    meli_cron_stock_avg_max = fields.Float(
        string="Prom. máx (seg)",
        readonly=True,
        help="Máx histórico por publicación"
    )

    meli_cron_stock_last_avg = fields.Float(
        string="Último prom. (seg)",
        readonly=True,
        help="Promedio última ejecución"
    )

    # CRON timing statistics - total duration
    meli_cron_stock_duration_min = fields.Float(
        string="Duración mín (seg)",
        readonly=True,
        help="Mín histórico del CRON"
    )

    meli_cron_stock_duration_max = fields.Float(
        string="Duración máx (seg)",
        readonly=True,
        help="Máx histórico del CRON"
    )

    meli_cron_stock_last_duration = fields.Float(
        string="Última duración (seg)",
        readonly=True,
        help="Duración última ejecución"
    )

    meli_cron_last_diagnostic = fields.Datetime(
        string="Último diagnóstico automático",
        readonly=True,
        help="Última vez que el cron ejecutó el diagnóstico de stock automáticamente"
    )

    def action_reset_cron_stats(self):
        """Reset all CRON timing statistics to zero."""
        self.write({
            'meli_cron_stock_avg_min': 0,
            'meli_cron_stock_avg_max': 0,
            'meli_cron_stock_last_avg': 0,
            'meli_cron_stock_duration_min': 0,
            'meli_cron_stock_duration_max': 0,
            'meli_cron_stock_last_duration': 0,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Estadísticas reseteadas',
                'message': 'Los tiempos de CRON han sido reiniciados a cero.',
                'type': 'success',
            }
        }

    def write(self, vals):
        res = super().write(vals)
        # Auto-toggle price cron status when batch mode changes
        if 'meli_cron_price_batch_hour' in vals:
            batch_active = vals['meli_cron_price_batch_hour'] and vals['meli_cron_price_batch_hour'] != '-1'
            for account in self:
                price_cron = account.cron_status_ids.filtered(lambda c: c.cron_type == 'price')
                if price_cron:
                    if batch_active:
                        # Batch mode ON → disable price cron (managed by Internal Jobs)
                        price_cron.write({'is_enabled': False})
                    else:
                        # Batch mode OFF → re-enable price cron
                        price_cron.write({'is_enabled': True})
                        # Also reset batch state if it was running
                        account.meli_cron_price_batch_running = False
        return res

    # Fields from /users/me API
    meli_user_nickname = fields.Char(string="Nickname ML", readonly=True)
    meli_user_first_name = fields.Char(string="Nombre", readonly=True)
    meli_user_last_name = fields.Char(string="Apellido", readonly=True)
    meli_user_email = fields.Char(string="Email ML", readonly=True)
    meli_user_phone = fields.Char(string="Teléfono", readonly=True)
    meli_user_type = fields.Char(string="Tipo de usuario", readonly=True)
    meli_user_site_id = fields.Char(string="Site ID", readonly=True)
    meli_user_status = fields.Char(string="Status en ML", readonly=True)
    meli_user_permalink = fields.Char(string="Permalink", readonly=True)
    meli_user_address = fields.Text(string="Dirección", readonly=True)
    meli_user_reputation_level = fields.Char(string="Nivel reputación", readonly=True)
    meli_user_reputation_power_seller = fields.Char(string="Power Seller", readonly=True)
    meli_user_transactions_completed = fields.Integer(string="Ventas completadas", readonly=True)
    meli_user_transactions_canceled = fields.Integer(string="Ventas canceladas", readonly=True)
    meli_user_ratings_positive = fields.Float(string="Calificaciones positivas %", readonly=True)
    meli_user_ratings_negative = fields.Float(string="Calificaciones negativas %", readonly=True)
    meli_user_ratings_neutral = fields.Float(string="Calificaciones neutrales %", readonly=True)
    meli_user_last_sync = fields.Datetime(string="Última sincronización", readonly=True)
    meli_user_raw_json = fields.Text(string="JSON completo", readonly=True)
    connection_monitor = fields.Boolean(string="Monitoreo", help="Monitoreo remoto de status de conexión", default=True)
    show_meli_user_raw_json = fields.Boolean(
        string="Mostrar JSON",
        default=False,
        store=False,
        help="Mostrar u ocultar el JSON completo del usuario ML"
    )

    summary_header_html = fields.Html(
        string="Resumen Dashboard",
        compute="_compute_summary_header_html",
        sanitize=False
    )

    @api.depends('cron_status_ids', 'cron_status_ids.last_run_state', 'cron_status_ids.is_enabled',
                 'status', 'meli_user_last_sync', 'products_count', 'orders_count', 'orders_pending_count')
    def _compute_summary_header_html(self):
        """Compute HTML summary with purple header + 3 pie charts (Option A layout)."""
        for record in self:
            if not record.id:
                record.summary_header_html = ""
                continue

            # ---- Account header (purple gradient) ----
            config_html = record._generate_account_header_html()

            # ---- Configuration object ----
            cfg = record.configuration

            # ---- 1. Orders chart with config header ----
            orders_total = record.orders_count or 0
            orders_pending = record.orders_pending_count or 0
            orders_completed = orders_total - orders_pending if orders_total > orders_pending else 0

            orders_config = record._generate_chart_config_header(
                settings=[
                    ('Importar pedidos', cfg.mercadolibre_cron_get_orders if cfg else None),
                    ('Importar envíos', cfg.mercadolibre_cron_get_orders_shipment if cfg else None),
                    ('Importar clientes', cfg.mercadolibre_cron_get_orders_shipment_client if cfg else None),
                ],
                extra_info=f"Confirmación: {cfg.mercadolibre_order_confirmation or 'N/A'}" if cfg else None
            )
            orders_chart = record._generate_donut_svg(
                data=[
                    (orders_completed, '#228B22', 'Completadas'),
                    (orders_pending, '#FFD700', 'Pendientes'),
                ],
                team_data={},
                title='Ordenes',
                config_header=orders_config
            )

            # ---- 2. Publications & Stock chart with config header ----
            products_total = record.products_count or 0

            publications_config = record._generate_chart_config_header(
                settings=[
                    ('Publicar stock', cfg.mercadolibre_cron_post_update_stock if cfg else None),
                    ('Publicar precios', cfg.mercadolibre_cron_post_update_price if cfg else None),
                    ('Publicar productos', cfg.mercadolibre_cron_post_update_products if cfg else None),
                ]
            )
            publications_chart = record._generate_donut_svg(
                data=[
                    (products_total, '#228B22', 'Publicados'),
                ],
                team_data={},
                title='Publicaciones & Stock',
                config_header=publications_config
            )

            # ---- 3. CRON status chart with config header ----
            crons_ok = len(record.cron_status_ids.filtered(lambda c: c.last_run_state == 'success'))
            crons_error = len(record.cron_status_ids.filtered(lambda c: c.last_run_state == 'error'))
            crons_warning = len(record.cron_status_ids.filtered(lambda c: c.last_run_state == 'warning'))
            crons_running = len(record.cron_status_ids.filtered(lambda c: c.last_run_state == 'running'))
            crons_never = len(record.cron_status_ids.filtered(lambda c: c.last_run_state == 'never'))
            crons_enabled = len(record.cron_status_ids.filtered(lambda c: c.is_enabled))
            crons_total = len(record.cron_status_ids)

            crons_config = record._generate_chart_config_header(
                settings=[
                    ('Auto-refresh', record.cron_refresh if hasattr(record, 'cron_refresh') else None),
                    ('Log chatter', record.meli_cron_log_chatter if hasattr(record, 'meli_cron_log_chatter') else None),
                ],
                extra_info=f"Activos: {crons_enabled} / {crons_total}"
            )
            cron_chart = record._generate_donut_svg(
                data=[
                    (crons_ok, '#228B22', 'OK'),
                    (crons_error, '#DC143C', 'Error'),
                    (crons_warning, '#FFD700', 'Warning'),
                    (crons_running, '#17a2b8', 'Ejecutando'),
                    (crons_never, '#6c757d', 'Sin ejecutar'),
                ],
                team_data={},
                title='Estado CRONs',
                config_header=crons_config
            )

            # ---- Assemble full dashboard ----
            last_sync_str = record.meli_user_last_sync.strftime('%d/%m/%Y %H:%M') if record.meli_user_last_sync else "Nunca"

            # Detect dark mode from Odoo's color_scheme cookie
            _is_dark = False
            try:
                from odoo.http import request as _http_request
                if _http_request and hasattr(_http_request, 'httprequest'):
                    _is_dark = _http_request.httprequest.cookies.get('color_scheme') == 'dark'
            except Exception:
                pass
            _dark_cls = ' kpi-dark' if _is_dark else ''

            html = f'''
            <style>
                body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; background: transparent; }}
                .kpi-dashboard {{ padding: 10px; }}
                .kpi-charts {{ display: flex; justify-content: space-around; flex-wrap: wrap; gap: 5px; }}
                .kpi-chart-card {{
                    display: inline-block; width: 280px; vertical-align: top;
                    text-align: center; padding: 10px; border-radius: 8px; margin: 5px;
                    background: #fafafa; border: 1px solid #e0e0e0;
                }}
                .kpi-chart-title {{ font-size: 15px; font-weight: bold; margin-bottom: 6px; color: #333; }}
                .kpi-config-header {{
                    background: #f0f0f0; padding: 5px 8px; border-radius: 6px;
                    margin-bottom: 6px; font-size: 12px; color: #666; text-align: left;
                }}
                .kpi-donut-hole {{ fill: #fafafa; }}
                .kpi-donut-total {{ fill: #333; }}
                .kpi-legend {{ text-align: left; padding: 6px 8px; max-height: 150px; overflow-y: auto; }}
                .kpi-legend-item {{ display: flex; align-items: center; margin: 2px 0; font-size: 13px; color: #333; }}
                .kpi-legend-dot {{ width: 12px; height: 12px; border-radius: 2px; margin-right: 6px; flex-shrink: 0; }}
                .kpi-legend-label {{ flex: 1; }}
                .kpi-legend-value {{ font-weight: bold; margin-left: 8px; }}
                .kpi-legend-divider {{ border-top: 1px solid #ddd; margin: 4px 0; padding-top: 4px; font-size: 12px; color: #666; }}
                .kpi-legend-team {{ display: flex; align-items: center; margin: 2px 0; font-size: 12px; color: #333; }}
                .kpi-legend-team .kpi-legend-dot {{ width: 10px; height: 10px; margin-right: 5px; }}
                .kpi-sync-footer {{ margin-top: 10px; text-align: center; color: #999; font-size: 12px; }}
                .kpi-chart-card svg path {{ stroke: #fafafa; }}

                /* Dark mode */
                .kpi-dark .kpi-chart-card {{ background: #262A36; border-color: #3e4452; }}
                .kpi-dark .kpi-chart-title {{ color: #dee2e6; }}
                .kpi-dark .kpi-config-header {{ background: #2f3340; color: #adb5bd; }}
                .kpi-dark .kpi-donut-hole {{ fill: #262A36; }}
                .kpi-dark .kpi-donut-total {{ fill: #dee2e6; }}
                .kpi-dark .kpi-legend-item,
                .kpi-dark .kpi-legend-team {{ color: #dee2e6; }}
                .kpi-dark .kpi-legend-divider {{ border-color: #3e4452; color: #adb5bd; }}
                .kpi-dark .kpi-sync-footer {{ color: #adb5bd; }}
                .kpi-dark .kpi-chart-card svg path {{ stroke: #262A36; }}
            </style>
            <div class="kpi-dashboard{_dark_cls}">
                {config_html}
                <div class="kpi-charts">
                    {orders_chart}
                    {publications_chart}
                    {cron_chart}
                </div>
                <div class="kpi-sync-footer">
                    Ultima sincronización ML: {last_sync_str}
                </div>
            </div>
            '''
            record.summary_header_html = html

    def _generate_account_header_html(self):
        """Generate purple gradient header with account info and KPI counters.
        Same style as FulfillmentAccountKPIs._generate_account_header_html."""
        status_color = '#28a745' if self.status == 'connected' else '#dc3545'
        status_text = 'Conectado' if self.status == 'connected' else 'Desconectado'
        company_name = self.company_id.name if self.company_id else 'N/A'
        country_name = self.country_id.name if self.country_id else 'N/A'
        seller = self.seller_id or 'N/A'
        crons_enabled = len(self.cron_status_ids.filtered(lambda c: c.is_enabled))
        crons_total = len(self.cron_status_ids)

        return f'''
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 10px 16px; border-radius: 8px; margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 16px; font-weight: bold;">{self.name or 'Cuenta'}</span>
                    <span style="background: {status_color}; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 10px;">{status_text}</span>
                    <div style="font-size: 12px; opacity: 0.9; margin-top: 3px;">
                        {company_name} | {country_name} | Seller: {seller}
                    </div>
                </div>
                <div style="display: flex; gap: 8px;">
                    <div style="text-align: center; background: rgba(255,255,255,0.2); padding: 4px 10px; border-radius: 6px;">
                        <div style="font-size: 15px; font-weight: bold;">{self.orders_count or 0:,}</div>
                        <div style="font-size: 11px;">Ordenes</div>
                    </div>
                    <div style="text-align: center; background: rgba(255,255,255,0.2); padding: 4px 10px; border-radius: 6px;">
                        <div style="font-size: 15px; font-weight: bold;">{self.products_count or 0:,}</div>
                        <div style="font-size: 11px;">Productos</div>
                    </div>
                    <div style="text-align: center; background: rgba(255,255,255,0.2); padding: 4px 10px; border-radius: 6px;">
                        <div style="font-size: 15px; font-weight: bold;">{crons_enabled}/{crons_total}</div>
                        <div style="font-size: 11px;">CRONs</div>
                    </div>
                </div>
            </div>
        </div>
        '''

    def _generate_chart_config_header(self, settings, extra_info=None):
        """Generate a small config header for each chart column.
        Same as FulfillmentAccountKPIs._generate_chart_config_header."""
        items = []
        for label, value in settings:
            if value is None:
                continue
            icon = '&#9989;' if value else '&#10060;'
            items.append(f'<span style="margin-right: 8px;">{icon} {label}</span>')

        extra_html = f'<div style="margin-top: 3px; font-size: 12px; opacity: 0.8;">{extra_info}</div>' if extra_info else ''

        if not items and not extra_info:
            return ''

        return f'''
        <div class="kpi-config-header">
            <div style="display: flex; flex-wrap: wrap;">{"".join(items)}</div>
            {extra_html}
        </div>
        '''

    def _generate_donut_svg(self, data, team_data, title, size=150, config_header=''):
        """
        Generate an SVG donut chart with inner ring (data) and outer ring (teams).
        Same implementation as FulfillmentAccountKPIs._generate_donut_svg

        Args:
            data: List of tuples (value, color, label)
            team_data: Dict {status: {team_name: count}} - for outer ring
            title: Chart title
            size: SVG size in pixels
            config_header: Optional HTML header for config settings
        """
        import math

        center = size / 2
        outer_radius = size / 2 - 10
        inner_radius = outer_radius * 0.65
        hole_radius = inner_radius * 0.55

        # Filter out zero values for inner ring
        inner_data = [(v, c, l) for v, c, l in data if v > 0]
        total = sum(v for v, c, l in inner_data) or 1

        # Calculate team totals for outer ring
        team_totals = {}
        for status_data in team_data.values():
            if isinstance(status_data, dict):
                for team, count in status_data.items():
                    team_totals[team] = team_totals.get(team, 0) + count

        team_colors = ['#3d3d3d', '#a0a0a0', '#5a5a5a', '#c0c0c0', '#7a7a7a']
        team_list = list(team_totals.items())
        team_total = sum(team_totals.values()) or 1

        svg_paths = []

        # Generate inner ring paths (status data)
        current_angle = -90  # Start from top
        for value, color, label in inner_data:
            if value <= 0:
                continue
            sweep_angle = (value / total) * 360
            end_angle = current_angle + sweep_angle

            path = self._create_arc_path(
                center, center,
                inner_radius, hole_radius,
                current_angle, end_angle
            )
            svg_paths.append(f'<path d="{path}" fill="{color}" stroke="white" stroke-width="1"/>')
            current_angle = end_angle

        # Generate outer ring paths (team data)
        if team_list:
            current_angle = -90
            for i, (team, count) in enumerate(team_list):
                if count <= 0:
                    continue
                sweep_angle = (count / team_total) * 360
                end_angle = current_angle + sweep_angle
                color = team_colors[i % len(team_colors)]

                path = self._create_arc_path(
                    center, center,
                    outer_radius, inner_radius + 2,
                    current_angle, end_angle
                )
                svg_paths.append(f'<path d="{path}" fill="{color}" stroke="white" stroke-width="1"/>')
                current_angle = end_angle

        paths_str = '\n'.join(svg_paths)

        # Generate legend items
        legend_items = []
        for value, color, label in data:
            legend_items.append(f'''
                <div class="kpi-legend-item">
                    <span class="kpi-legend-dot" style="background: {color};"></span>
                    <span class="kpi-legend-label">{label}</span>
                    <span class="kpi-legend-value">{value:,}</span>
                </div>
            ''')

        # Add team legend if exists
        if team_list:
            legend_items.append('<div class="kpi-legend-divider">Equipos:</div>')
            for i, (team, count) in enumerate(team_list):
                color = team_colors[i % len(team_colors)]
                legend_items.append(f'''
                    <div class="kpi-legend-team">
                        <span class="kpi-legend-dot" style="background: {color};"></span>
                        <span class="kpi-legend-label">{team}</span>
                        <span class="kpi-legend-value">{count:,}</span>
                    </div>
                ''')

        legend_str = '\n'.join(legend_items)

        return f'''
        <div class="kpi-chart-card">
            <div class="kpi-chart-title">{title}</div>
            {config_header}
            <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="display: block; margin: 0 auto;">
                {paths_str}
                <circle cx="{center}" cy="{center}" r="{hole_radius}" class="kpi-donut-hole"/>
                <text x="{center}" y="{center}" text-anchor="middle" dominant-baseline="middle" font-size="14" font-weight="bold" class="kpi-donut-total">{total:,}</text>
            </svg>
            <div class="kpi-legend">
                {legend_str}
            </div>
        </div>
        '''

    def _create_arc_path(self, cx, cy, outer_r, inner_r, start_angle, end_angle):
        """Create SVG arc path for donut segment. Same as FulfillmentAccountKPIs."""
        import math

        # Handle full circle case
        if abs(end_angle - start_angle) >= 359.9:
            end_angle = start_angle + 359.9

        start_rad = math.radians(start_angle)
        end_rad = math.radians(end_angle)

        # Outer arc points
        x1 = cx + outer_r * math.cos(start_rad)
        y1 = cy + outer_r * math.sin(start_rad)
        x2 = cx + outer_r * math.cos(end_rad)
        y2 = cy + outer_r * math.sin(end_rad)

        # Inner arc points
        x3 = cx + inner_r * math.cos(end_rad)
        y3 = cy + inner_r * math.sin(end_rad)
        x4 = cx + inner_r * math.cos(start_rad)
        y4 = cy + inner_r * math.sin(start_rad)

        large_arc = 1 if (end_angle - start_angle) > 180 else 0

        # Path: Move to outer start, arc to outer end, line to inner end, arc back to inner start, close
        return f"M {x1:.2f} {y1:.2f} A {outer_r:.2f} {outer_r:.2f} 0 {large_arc} 1 {x2:.2f} {y2:.2f} L {x3:.2f} {y3:.2f} A {inner_r:.2f} {inner_r:.2f} 0 {large_arc} 0 {x4:.2f} {y4:.2f} Z"

    def action_toggle_raw_json(self):
        """Toggle visibility of raw JSON field."""
        for rec in self:
            rec.show_meli_user_raw_json = not rec.show_meli_user_raw_json

    def action_view_raw_json_popup(self):
        """Open raw JSON in a popup window."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'JSON Usuario ML',
            'res_model': 'mercadolibre.account',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('meli_oerp_multiple.view_mercadolibre_account_json_popup').id,
            'target': 'new',
            'context': {'form_view_initial_mode': 'readonly'},
        }

    maestro_products = fields.One2many("mercadolibre.product.maestro","connection_account",string="Productos maestros")

    def action_fetch_user_me(self):
        """Fetch user info from /users/me API endpoint."""
        for acc in self:
            company = acc.company_id or self.env.user.company_id
            meli = self.env['meli.util'].get_new_instance(company, acc)

            if meli.need_login():
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Necesita iniciar sesión primero',
                        'type': 'warning',
                    }
                }

            response = meli.get("/users/me", {'access_token': meli.access_token})
            rjson = response.json() if response else {}

            if rjson and 'id' in rjson:
                # Extract address
                address_parts = []
                if rjson.get('address'):
                    addr = rjson['address']
                    if addr.get('address'):
                        address_parts.append(addr.get('address'))
                    if addr.get('city'):
                        address_parts.append(addr.get('city'))
                    if addr.get('state'):
                        address_parts.append(addr.get('state'))
                    if addr.get('zip_code'):
                        address_parts.append(f"CP: {addr.get('zip_code')}")

                # Extract reputation data
                reputation = rjson.get('seller_reputation', {})
                transactions = reputation.get('transactions', {})
                ratings = transactions.get('ratings', {})

                # Detect seller tags
                tags = rjson.get('tags', [])
                is_user_product_seller = 'user_product_seller' in tags
                is_multiwarehouse = 'multiwarehouse' in tags

                acc.write({
                    'meli_user_nickname': rjson.get('nickname'),
                    'meli_user_first_name': rjson.get('first_name'),
                    'meli_user_last_name': rjson.get('last_name'),
                    'meli_user_email': rjson.get('email'),
                    'meli_user_phone': rjson.get('phone', {}).get('number') if isinstance(rjson.get('phone'), dict) else None,
                    'meli_user_type': rjson.get('user_type'),
                    'meli_user_site_id': rjson.get('site_id'),
                    'meli_user_status': rjson.get('status', {}).get('site_status') if isinstance(rjson.get('status'), dict) else rjson.get('status'),
                    'meli_user_permalink': rjson.get('permalink'),
                    'meli_user_address': ', '.join(address_parts) if address_parts else None,
                    'meli_user_reputation_level': reputation.get('level_id'),
                    'meli_user_reputation_power_seller': reputation.get('power_seller_status'),
                    'meli_user_transactions_completed': transactions.get('completed'),
                    'meli_user_transactions_canceled': transactions.get('canceled'),
                    'meli_user_ratings_positive': ratings.get('positive', 0) * 100 if ratings.get('positive') else 0,
                    'meli_user_ratings_negative': ratings.get('negative', 0) * 100 if ratings.get('negative') else 0,
                    'meli_user_ratings_neutral': ratings.get('neutral', 0) * 100 if ratings.get('neutral') else 0,
                    'meli_user_last_sync': fields.Datetime.now(),
                    'meli_user_raw_json': json.dumps(rjson, indent=2, default=str),
                    'user_product_seller': is_user_product_seller,
                    'multiwarehouse': is_multiwarehouse,
                })

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Éxito',
                        'message': f'Info actualizada para {rjson.get("nickname")}',
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Error al obtener datos: {rjson}',
                        'type': 'danger',
                    }
                }

    def action_refresh_multiwarehouse_info(self):
        """
        Actualiza el estado multiwarehouse desde /users/me y sincroniza
        meli_user_product_id para los productos vinculados que no lo tengan.
        """
        self.ensure_one()
        company = self.company_id or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, self)

        if meli.need_login():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Necesita iniciar sesión primero',
                    'type': 'warning',
                }
            }

        # 1. Actualizar flag multiwarehouse desde /users/me
        response = meli.get("/users/me", {'access_token': meli.access_token})
        rjson = response.json() if response else {}
        tags = rjson.get('tags', [])
        is_mw = 'multiwarehouse' in tags
        self.write({'multiwarehouse': is_mw})

        if not is_mw:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info Multiwarehouse',
                    'message': 'Esta cuenta NO es multiwarehouse (tag no presente en /users/me).',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # 2. Consultar stores con tag stock_location y sincronizar registros
        seller_id = self.seller_id
        stores_full_url = "https://api.mercadolibre.com/users/%s/stores/search?tags=stock_location" % str(seller_id)
        stores_count = 0
        stores_names = []
        try:
            stores_resp = requests.get(stores_full_url, headers={'Authorization': 'Bearer %s' % meli.access_token}, timeout=15)
            stores_json = stores_resp.json() if stores_resp else {}
            stores_results = stores_json.get('results', [])
            stores_count = len(stores_results)
            StockLoc = self.env['mercadolibre.account.stock_location']
            synced_meli_ids = []
            for s in stores_results:
                meli_store_id = str(s.get('id', ''))
                loc = s.get('location') or {}
                svcs = s.get('services', {})
                sl_types = svcs.get('stock_location', [])
                vals = {
                    'account_id': self.id,
                    'meli_store_id': meli_store_id,
                    'name': s.get('description', meli_store_id),
                    'status': s.get('status', 'active'),
                    'network_node_id': s.get('network_node_id', ''),
                    'services_stock_location': ', '.join(sl_types),
                    'address_line': loc.get('address_line', ''),
                    'city': loc.get('city', ''),
                    'state_name': loc.get('state', ''),
                    'zip_code': loc.get('zip_code', ''),
                    'latitude': loc.get('latitude', 0.0),
                    'longitude': loc.get('longitude', 0.0),
                }
                existing = StockLoc.search([('account_id', '=', self.id), ('meli_store_id', '=', meli_store_id)], limit=1)
                if existing:
                    existing.write(vals)
                    synced_meli_ids.append(existing.id)
                else:
                    new_rec = StockLoc.create(vals)
                    synced_meli_ids.append(new_rec.id)
                stores_names.append(s.get('description', meli_store_id))
            # Archivar (o eliminar) stores que ya no existen en ML
            obsolete = StockLoc.search([('account_id', '=', self.id), ('id', 'not in', synced_meli_ids)])
            if obsolete:
                obsolete.write({'status': 'inactive'})
        except Exception as E:
            _logger.error("action_refresh_multiwarehouse_info: error consultando/sincronizando stores: %s", str(E))

        # 3. Actualizar meli_user_product_id para bindings que no lo tengan
        MeliProduct = self.env['mercadolibre.product']
        bindings = MeliProduct.search([
            ('connection_account', '=', self.id),
            ('conn_id', '!=', False),
            ('meli_user_product_id', '=', False),
        ], limit=50)

        updated = 0
        errors = 0
        for binding in bindings:
            meli_id = binding.conn_id
            try:
                item_response = meli.get("/items/" + str(meli_id), {'access_token': meli.access_token})
                item_json = item_response.json() if item_response else {}
                user_product_id = item_json.get('user_product_id')
                if user_product_id:
                    binding.write({'meli_user_product_id': str(user_product_id)})
                    updated += 1
            except Exception as E:
                _logger.error("action_refresh_multiwarehouse_info: error en %s: %s", meli_id, str(E))
                errors += 1

        stores_msg = "Stock Locations ML: %d (%s). " % (stores_count, ", ".join(stores_names) or "ninguna") if stores_count else "Stock Locations ML: 0. "
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Multiwarehouse actualizado',
                'message': '%suser_product_id actualizado: %d productos (errores: %d).' % (stores_msg, updated, errors),
                'type': 'success',
                'sticky': False,
            }
        }

    def _refresh_unread_messages(self):
        """Refresh the post-sale UNREAD buyer-message count on this account's
        orders from GET /messages/unread (role=seller, tag=post_sale). Returns
        (total, touched). Scoped to the account so it never touches another
        seller's orders. [#499 Deco/KPI]"""
        self.ensure_one()
        company = self.company_id or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, self)
        if not meli or meli.need_login():
            _logger.warning("unread: cuenta %s sin login, se omite", self.display_name)
            return (0, 0)
        try:
            resp = meli.get("/messages/unread",
                            {'access_token': meli.access_token, 'role': 'seller', 'tag': 'post_sale'})
            rjson = resp.json() if resp else {}
        except Exception as e:
            _logger.warning("unread: fallo /messages/unread cuenta %s: %s", self.display_name, e)
            return (0, 0)
        if not isinstance(rjson, dict) or rjson.get('error'):
            return (0, 0)
        results = rjson.get('results') or []
        orders_domain = [('connection_account', '=', self.id)]
        touched = self.env['mercadolibre.orders']._meli_apply_unread_results(results, orders_domain)
        total = rjson.get('total') or 0
        _logger.info("unread cuenta %s: total=%s, ordenes actualizadas=%s", self.display_name, total, touched)
        return (total, touched)

    def action_refresh_unread_messages(self):
        """Botón manual: refresca los mensajes sin leer de esta cuenta. [#499]"""
        grand_total = 0
        for acc in self:
            total, _touched = acc._refresh_unread_messages()
            grand_total += total
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Mensajes de MercadoLibre',
                'message': ('Hay %s venta(s) con mensajes del comprador sin responder.' % grand_total)
                           if grand_total else 'No hay mensajes del comprador sin responder.',
                'type': 'warning' if grand_total else 'success',
                'sticky': False,
            },
        }

    @api.model
    def cron_meli_refresh_unread(self):
        """Cron: refresca los mensajes sin leer de todas las cuentas ML. [#499]"""
        accounts = self.search([])
        for acc in accounts:
            try:
                acc._refresh_unread_messages()
            except Exception as e:
                _logger.error("cron unread: fallo cuenta %s: %s", acc.display_name, e, exc_info=True)
        return True

    def action_check_multiwarehouse(self):
        """
        Diagnóstico completo de los endpoints multiwarehouse.
        Prueba /users/me, /items/{id} y /user-products/{id}/stock
        y muestra los resultados en un popup.
        """
        import time as _time
        self.ensure_one()
        company = self.company_id or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, self)

        if meli.need_login():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Necesita iniciar sesión primero',
                    'type': 'warning',
                }
            }

        lines = []
        lines.append("=== Check & Test Multiwarehouse ===")
        lines.append("Cuenta: %s" % self.name)
        lines.append("")

        # --- TEST 1: /users/me ---
        lines.append("[1] GET /users/me")
        t0 = _time.time()
        try:
            resp = meli.get("/users/me", {'access_token': meli.access_token})
            rjson = resp.json() if resp else {}
            elapsed = _time.time() - t0
            if 'id' in rjson:
                tags = rjson.get('tags', [])
                is_mw = 'multiwarehouse' in tags
                is_up = 'user_product_seller' in tags
                site_id = rjson.get('site_id', '?')
                self.write({'multiwarehouse': is_mw, 'user_product_seller': is_up})
                lines.append("    OK (%.2fs)" % elapsed)
                lines.append("    nickname: %s | site: %s" % (rjson.get('nickname', '?'), site_id))
                lines.append("    multiwarehouse:       %s" % ("SI ✓" if is_mw else "NO ✗"))
                lines.append("    user_product_seller:  %s" % ("SI ✓" if is_up else "NO ✗"))
                lines.append("    tags: %s" % (", ".join(tags) or "(ninguno)"))

                # Paises soportados por API multiwarehouse
                SUPPORTED_SITES = ['MLA', 'MLM', 'MLC', 'MCO']
                if is_mw and site_id in SUPPORTED_SITES:
                    lines.append("    API /user-products: DISPONIBLE para %s ✓" % site_id)
                elif is_mw:
                    lines.append("    API /user-products: NO disponible para %s (solo %s)" % (site_id, "/".join(SUPPORTED_SITES)))
            else:
                lines.append("    ERROR: %s" % str(rjson))
        except Exception as E:
            lines.append("    EXCEPTION: %s" % str(E))

        lines.append("")

        # --- TEST 2: Muestra de productos y sus user_product_id ---
        MeliProduct = self.env['mercadolibre.product']
        bindings = MeliProduct.search([
            ('connection_account', '=', self.id),
            ('conn_id', '!=', False),
        ], limit=5)

        lines.append("[2] Muestra de bindings (%d de %d total):" % (
            len(bindings),
            MeliProduct.search_count([('connection_account', '=', self.id), ('conn_id', '!=', False)])
        ))

        for binding in bindings:
            meli_id = binding.conn_id
            meli_var_id = binding.conn_variation_id
            sku = (binding.product_id and binding.product_id.default_code) or '?'
            cached_upid = binding.meli_user_product_id or None

            lines.append("")
            lines.append("  SKU: %s | ML ID: %s%s" % (
                sku, meli_id, ("/" + str(meli_var_id)) if meli_var_id else ""
            ))
            lines.append("  meli_user_product_id (local): %s" % (cached_upid or "(vacío)"))

            # GET /items/{meli_id}
            item_url = "/items/" + str(meli_id)
            t0 = _time.time()
            try:
                item_resp = meli.get(item_url, {'access_token': meli.access_token})
                item_json = item_resp.json() if item_resp else {}
                elapsed = _time.time() - t0
                user_product_id = item_json.get('user_product_id')
                logistic_type = (item_json.get('shipping') or {}).get('logistic_type', '?')
                lines.append("  GET %s (%.2fs)" % (item_url, elapsed))
                lines.append("    status: %s | logistic_type: %s" % (item_json.get('status', '?'), logistic_type))
                lines.append("    user_product_id: %s" % (str(user_product_id) if user_product_id else "(no tiene)"))

                # GET /user-products/{user_product_id}/stock
                if user_product_id:
                    stock_url = "/user-products/%s/stock" % str(user_product_id)
                    t0 = _time.time()
                    try:
                        stock_resp = meli.get(stock_url, {'access_token': meli.access_token})
                        stock_json = stock_resp.json() if stock_resp else {}
                        elapsed = _time.time() - t0
                        lines.append("  GET %s (%.2fs)" % (stock_url, elapsed))
                        locations = stock_json.get('locations', [])
                        if locations:
                            for loc in locations:
                                lines.append("    %s: %s uds" % (loc.get('type', '?'), loc.get('quantity', '?')))
                        elif 'variations' in stock_json:
                            lines.append("    (variantes: %d)" % len(stock_json['variations']))
                        else:
                            lines.append("    Respuesta: %s" % str(stock_json)[:200])
                    except Exception as E:
                        lines.append("    GET %s ERROR: %s" % (stock_url, str(E)[:100]))

                    # GET /user-products/{id}/stock/type/selling_address
                    sa_url = "/user-products/%s/stock/type/selling_address" % str(user_product_id)
                    t0 = _time.time()
                    try:
                        sa_resp = meli.get(sa_url, {'access_token': meli.access_token})
                        sa_json = sa_resp.json() if sa_resp else {}
                        elapsed = _time.time() - t0
                        if 'error' not in sa_json:
                            qty = sa_json.get('quantity', '?')
                            lines.append("  GET %s (%.2fs) → qty: %s" % (sa_url, elapsed, qty))
                        else:
                            lines.append("  GET %s (%.2fs) → %s" % (sa_url, elapsed, sa_json.get('error', '?')))
                    except Exception as E:
                        lines.append("  GET %s ERROR: %s" % (sa_url, str(E)[:100]))

            except Exception as E:
                lines.append("    GET %s ERROR: %s" % (item_url, str(E)[:100]))

        if not bindings:
            lines.append("  (No se encontraron productos vinculados en esta cuenta)")

        lines.append("")

        # --- TEST 3: /users/{seller_id}/stores/search?tags=stock_location ---
        seller_id = self.seller_id
        stores_full_url = "https://api.mercadolibre.com/users/%s/stores/search?tags=stock_location" % str(seller_id)
        lines.append("[3] GET /users/%s/stores/search?tags=stock_location" % str(seller_id))
        lines.append("    (Authorization: Bearer token)")
        t0 = _time.time()
        try:
            stores_resp = requests.get(stores_full_url, headers={'Authorization': 'Bearer %s' % meli.access_token}, timeout=15)
            stores_json = stores_resp.json() if stores_resp else {}
            elapsed = _time.time() - t0

            if stores_resp.status_code != 200 or 'error' in stores_json:
                lines.append("    ERROR %s (%.2fs): %s — %s" % (
                    stores_resp.status_code, elapsed,
                    stores_json.get('error', ''), stores_json.get('message', '')))
            else:
                results = stores_json.get('results', [])
                paging = stores_json.get('paging', {})
                total = paging.get('total', len(results))
                lines.append("    OK (%.2fs) — %d store(s) con tag stock_location" % (elapsed, total))

                if results:
                    lines.append("")
                    lines.append("    ID         | Descripcion                    | Ciudad              | Estado")
                    lines.append("    " + "-" * 75)
                    for store in results:
                        s_id     = str(store.get('id', '?')).ljust(10)
                        s_desc   = str(store.get('description', '?'))[:30].ljust(30)
                        loc      = store.get('location') or {}
                        s_city   = str(loc.get('city', '?'))[:20].ljust(20)
                        s_status = store.get('status', '?')
                        lines.append("    %s | %s | %s | %s" % (s_id, s_desc, s_city, s_status))

                        # Detalles adicionales
                        s_state   = loc.get('state', '')
                        s_address = loc.get('address_line', '')
                        s_zip     = loc.get('zip_code', '')
                        s_node    = store.get('network_node_id', '')
                        s_services = store.get('services', {})
                        s_sl_types = s_services.get('stock_location', [])

                        if s_address:
                            lines.append("      direccion: %s, %s %s" % (s_address, s_state, s_zip))
                        if s_node:
                            lines.append("      network_node_id: %s" % s_node)
                        if s_sl_types:
                            lines.append("      services.stock_location: %s" % ", ".join(s_sl_types))
                else:
                    lines.append("    (No se encontraron stores con tag stock_location)")
        except Exception as E:
            lines.append("    EXCEPTION: %s" % str(E)[:150])

        lines.append("")

        # --- TEST 4: Stock completo por ubicación y pruebas PUT ---
        import json as _json

        # Buscar un binding ACTIVO primero, si no hay, usar cualquiera
        test_binding = MeliProduct.search([
            ('connection_account', '=', self.id),
            ('conn_id', '!=', False),
            ('meli_user_product_id', '!=', False),
            ('meli_last_status', '=', 'active'),
        ], limit=1)
        if not test_binding:
            test_binding = MeliProduct.search([
                ('connection_account', '=', self.id),
                ('conn_id', '!=', False),
                ('meli_user_product_id', '!=', False),
                ('meli_last_status', 'in', ['paused', 'active']),
            ], limit=1)
        if not test_binding:
            test_binding = MeliProduct.search([
                ('connection_account', '=', self.id),
                ('conn_id', '!=', False),
                ('meli_user_product_id', '!=', False),
            ], limit=1)

        _working_put_types = []  # track which PUT /stock/type/{type} endpoints work

        lines.append("[4] TEST stock por ubicación y PUT")
        if not test_binding:
            lines.append("  (No se encontraron bindings con user_product_id para probar)")
        else:
            up_id = test_binding.meli_user_product_id
            meli_id = test_binding.conn_id
            sku = (test_binding.product_id and test_binding.product_id.default_code) or '?'
            meli_status = test_binding.meli_last_status or '?'
            lines.append("  Producto: SKU %s | ML ID: %s | UP: %s | status: %s" % (sku, meli_id, up_id, meli_status))

            auth_headers = {
                'Authorization': 'Bearer %s' % meli.access_token,
                'Accept': 'application/json',
            }

            # 4a) GET /user-products/{id}/stock (general)
            stock_url = "https://api.mercadolibre.com/user-products/%s/stock" % str(up_id)
            t0 = _time.time()
            # A3 fix (ticket #425): initialize before the request so the non-200
            # (no-exception) branch below cannot leave these unbound -> the later
            # 4b/4c sections reference found_types/found_all_locs unconditionally.
            found_types = {}      # type -> {qty, store_id, network_node_id}
            found_all_locs = []   # all root locations with their data
            try:
                stock_resp = requests.get(stock_url, headers=auth_headers, timeout=15)
                stock_json = stock_resp.json() if stock_resp.status_code == 200 else {}
                elapsed = _time.time() - t0
                x_version = stock_resp.headers.get('x-version') or stock_resp.headers.get('X-Version')

                lines.append("")
                lines.append("  [4a] GET /user-products/%s/stock → HTTP %s (%.2fs)" % (up_id, stock_resp.status_code, elapsed))
                lines.append("    X-Version: %s" % (str(x_version) if x_version else "(no encontrado)"))

                if stock_resp.status_code != 200:
                    err = stock_resp.json() if stock_resp.text else {}
                    lines.append("    ERROR: %s — %s" % (err.get('error', ''), err.get('message', '')))
                else:
                    # Parsear ubicaciones (root o por variante)
                    locations = stock_json.get('locations', [])
                    variations = stock_json.get('variations', [])

                    # Recopilar tipos de ubicación encontrados y datos para PUT tests
                    found_types = {}  # type -> {qty, store_id, network_node_id} (first of each type)
                    found_all_locs = []  # all root locations with their data

                    if locations:
                        lines.append("    Ubicaciones (root):")
                        for loc in locations:
                            lt = loc.get('type', '?')
                            lq = loc.get('quantity', 0)
                            extra = ""
                            if loc.get('store_id'):
                                extra += " store_id: %s" % loc['store_id']
                            if loc.get('network_node_id'):
                                extra += " node: %s" % loc['network_node_id']
                            lines.append("      %s: %s uds%s" % (lt, lq, extra))
                            _loc_entry = {
                                'type': lt,
                                'quantity': lq,
                                'store_id': loc.get('store_id'),
                                'network_node_id': loc.get('network_node_id'),
                            }
                            found_all_locs.append(_loc_entry)
                            if lt not in found_types:
                                found_types[lt] = _loc_entry

                    if variations:
                        lines.append("    Variantes con stock: %d" % len(variations))
                        for var in variations[:3]:
                            var_id = var.get('variation_id', '?')
                            var_locs = var.get('locations', [])
                            lines.append("      variation %s:" % var_id)
                            for vl in var_locs:
                                vlt = vl.get('type', '?')
                                vlq = vl.get('quantity', 0)
                                extra = ""
                                if vl.get('store_id'):
                                    extra += " store_id: %s" % vl['store_id']
                                if vl.get('network_node_id'):
                                    extra += " node: %s" % vl['network_node_id']
                                lines.append("        %s: %s uds%s" % (vlt, vlq, extra))
                                if vlt not in found_types:
                                    found_types[vlt] = {
                                        'quantity': vlq,
                                        'store_id': vl.get('store_id'),
                                        'network_node_id': vl.get('network_node_id'),
                                    }
                        if len(variations) > 3:
                            lines.append("      ... y %d variantes más" % (len(variations) - 3))

                    if not locations and not variations:
                        lines.append("    Respuesta completa: %s" % str(stock_json)[:400])

                    # Resumen de tipologías
                    lines.append("")
                    lines.append("    Tipologías de stock encontradas: %s" % (", ".join(found_types.keys()) if found_types else "(ninguna)"))

            except Exception as E:
                stock_json = {}
                x_version = None
                found_types = {}
                found_all_locs = []
                lines.append("    EXCEPTION: %s" % str(E)[:150])

            # 4b) GET y PUT por cada tipo de ubicación encontrado
            put_headers_base = dict(auth_headers)
            put_headers_base['Content-Type'] = 'application/json'
            if x_version:
                put_headers_base['X-Version'] = str(x_version)

            for loc_type in ['selling_address', 'seller_warehouse']:
                lines.append("")
                lines.append("  [4b] TEST /user-products/%s/stock/type/%s" % (up_id, loc_type))

                # GET específico por tipo
                type_url = "https://api.mercadolibre.com/user-products/%s/stock/type/%s" % (str(up_id), loc_type)
                t0 = _time.time()
                try:
                    type_resp = requests.get(type_url, headers=auth_headers, timeout=15)
                    elapsed = _time.time() - t0
                    type_json = type_resp.json() if type_resp.text else {}

                    lines.append("    GET → HTTP %s (%.2fs)" % (type_resp.status_code, elapsed))

                    if type_resp.status_code >= 400:
                        lines.append("    error: %s" % type_json.get('error', ''))
                        lines.append("    message: %s" % type_json.get('message', ''))
                        # NOTE: GET on /stock/type/ may return 404 even when PUT works (write-only endpoint).
                        # Do NOT skip the PUT test — proceed regardless.
                        lines.append("    → GET '%s' devuelve 404 — probando PUT de todas formas (endpoint puede ser solo escritura)" % loc_type)
                    else:
                        lines.append("    → Tipo '%s' DISPONIBLE en GET ✓" % loc_type)
                        lines.append("    respuesta: %s" % str(type_json)[:300])

                    # Prefer X-Version from this GET, fall back to the one from /stock
                    type_xver = type_resp.headers.get('x-version') or type_resp.headers.get('X-Version') or x_version

                except Exception as E:
                    lines.append("    GET EXCEPTION: %s" % str(E)[:150])
                    type_xver = x_version

                # PUT test — safe: usa cantidades actuales del GET /stock
                # Importante: probar siempre aunque GET haya devuelto 404 (el endpoint puede ser write-only)
                loc_data = found_types.get(loc_type, {})
                current_qty = int(loc_data.get('quantity') or 0)
                store_id = loc_data.get('store_id')
                node_id = loc_data.get('network_node_id')

                # Si no tenemos qty del GET general, intentar parsear del GET específico
                if current_qty is None:
                    if isinstance(type_json, dict):
                        current_qty = type_json.get('quantity')
                        if current_qty is None and 'locations' in type_json:
                            for tl in type_json['locations']:
                                if tl.get('type') == loc_type:
                                    current_qty = tl.get('quantity', 0)
                                    store_id = store_id or tl.get('store_id')
                                    node_id = node_id or tl.get('network_node_id')
                                    break

                if current_qty is None:
                    lines.append("    (No se pudo obtener cantidad actual para probar PUT)")
                    continue

                # Construir body según tipo
                if loc_type == 'selling_address':
                    put_body = {"quantity": int(current_qty)}
                elif loc_type == 'seller_warehouse':
                    # Incluir TODAS las ubicaciones de tipo seller_warehouse (multi-depósito)
                    _all_sw = [l for l in found_all_locs if l.get('type') == 'seller_warehouse']
                    if _all_sw:
                        _sw_locs_body = []
                        for _asl in _all_sw:
                            _entry = {"quantity": int(_asl.get('quantity', 0) or 0)}
                            if _asl.get('store_id'):
                                _entry["store_id"] = _asl["store_id"]
                            if _asl.get('network_node_id'):
                                _entry["network_node_id"] = _asl["network_node_id"]
                            _sw_locs_body.append(_entry)
                        put_body = {"locations": _sw_locs_body}
                    else:
                        sw_loc = {"quantity": current_qty}
                        if store_id:
                            sw_loc["store_id"] = store_id
                        if node_id:
                            sw_loc["network_node_id"] = node_id
                        put_body = {"locations": [sw_loc]}
                else:
                    put_body = {"quantity": current_qty}

                put_url = "https://api.mercadolibre.com/user-products/%s/stock/type/%s" % (str(up_id), loc_type)
                put_hdrs = dict(put_headers_base)
                if type_xver:
                    put_hdrs['X-Version'] = str(type_xver)

                lines.append("")
                lines.append("    PUT /user-products/%s/stock/type/%s" % (up_id, loc_type))
                lines.append("      body: %s" % str(put_body))
                lines.append("      X-Version: %s" % (str(put_hdrs.get('X-Version', '')) or "(sin header)"))

                t0 = _time.time()
                try:
                    put_resp = requests.put(put_url, headers=put_hdrs, data=_json.dumps(put_body), timeout=15)
                    elapsed = _time.time() - t0
                    put_json = put_resp.json() if put_resp.text else {}

                    if put_resp.status_code >= 400 or (isinstance(put_json, dict) and 'error' in put_json):
                        lines.append("      RESULTADO: ERROR HTTP %s (%.2fs)" % (put_resp.status_code, elapsed))
                        if isinstance(put_json, dict):
                            lines.append("      error: %s" % put_json.get('error', ''))
                            lines.append("      message: %s" % put_json.get('message', ''))
                            lines.append("      cause: %s" % str(put_json.get('cause', '')))
                        lines.append("      → PUT %s NO funciona" % loc_type)
                    else:
                        lines.append("      RESULTADO: OK HTTP %s (%.2fs) ✓" % (put_resp.status_code, elapsed))
                        lines.append("      → PUT %s FUNCIONA ✓" % loc_type)
                        lines.append("      respuesta: %s" % str(put_json)[:200])
                        if loc_type not in _working_put_types:
                            _working_put_types.append(loc_type)
                except Exception as E:
                    lines.append("      PUT EXCEPTION: %s" % str(E)[:150])

            # 4c) PUT directo a /user-products/{id}/stock (sin /type/)
            lines.append("")
            lines.append("  [4c] PUT /user-products/%s/stock (sin /type/)" % up_id)
            if found_types.get('seller_warehouse'):
                sw = found_types['seller_warehouse']
                put_body_direct = {
                    "locations": [{
                        "type": "seller_warehouse",
                        "store_id": sw.get('store_id', ''),
                        "network_node_id": sw.get('network_node_id', ''),
                        "quantity": int(sw.get('quantity', 0)),
                    }]
                }
            elif found_types.get('selling_address'):
                put_body_direct = {"quantity": int(found_types['selling_address'].get('quantity', 0))}
            else:
                put_body_direct = None

            if put_body_direct:
                direct_url = "https://api.mercadolibre.com/user-products/%s/stock" % str(up_id)
                put_hdrs_d = dict(auth_headers)
                put_hdrs_d['Content-Type'] = 'application/json'
                if x_version:
                    put_hdrs_d['X-Version'] = str(x_version)
                lines.append("    body: %s" % str(put_body_direct))
                lines.append("    X-Version: %s" % (str(x_version) if x_version else "(sin header)"))
                t0 = _time.time()
                try:
                    put_d_resp = requests.put(direct_url, headers=put_hdrs_d, data=_json.dumps(put_body_direct), timeout=15)
                    elapsed = _time.time() - t0
                    put_d_json = put_d_resp.json() if put_d_resp.text else {}
                    if put_d_resp.status_code >= 400:
                        lines.append("    RESULTADO: ERROR HTTP %s (%.2fs)" % (put_d_resp.status_code, elapsed))
                        if isinstance(put_d_json, dict):
                            lines.append("    error: %s" % put_d_json.get('error', ''))
                            lines.append("    message: %s" % put_d_json.get('message', ''))
                        lines.append("    → PUT directo a /stock NO funciona")
                    else:
                        lines.append("    RESULTADO: OK HTTP %s (%.2fs) ✓" % (put_d_resp.status_code, elapsed))
                        lines.append("    → PUT directo a /stock FUNCIONA ✓")
                        lines.append("    respuesta: %s" % str(put_d_json)[:200])
                except Exception as E:
                    lines.append("    EXCEPTION: %s" % str(E)[:150])
            else:
                lines.append("    (No hay datos de ubicación para construir body)")

            # 4d) PUT legacy a /items/{id} con available_quantity
            lines.append("")
            lines.append("  [4d] PUT /items/%s (legacy available_quantity)" % meli_id)
            # Obtener stock actual del item
            item_url = "https://api.mercadolibre.com/items/%s" % str(meli_id)
            t0 = _time.time()
            try:
                item_resp = requests.get(item_url, headers=auth_headers, timeout=15)
                item_json = item_resp.json() if item_resp.status_code == 200 else {}
                current_avail = item_json.get('available_quantity', 0)
                item_status = item_json.get('status', '?')
                lines.append("    item status: %s | available_quantity actual: %s" % (item_status, current_avail))

                # PUT con misma cantidad (safe)
                legacy_put_url = "https://api.mercadolibre.com/items/%s" % str(meli_id)
                legacy_body = {"available_quantity": int(current_avail)}
                legacy_hdrs = dict(auth_headers)
                legacy_hdrs['Content-Type'] = 'application/json'

                lines.append("    body: %s" % str(legacy_body))
                t0 = _time.time()
                legacy_resp = requests.put(legacy_put_url, headers=legacy_hdrs, data=_json.dumps(legacy_body), timeout=15)
                elapsed = _time.time() - t0
                legacy_json = legacy_resp.json() if legacy_resp.text else {}

                if legacy_resp.status_code >= 400 or (isinstance(legacy_json, dict) and 'error' in legacy_json):
                    lines.append("    RESULTADO: ERROR HTTP %s (%.2fs)" % (legacy_resp.status_code, elapsed))
                    if isinstance(legacy_json, dict):
                        lines.append("    error: %s" % legacy_json.get('error', ''))
                        lines.append("    message: %s" % legacy_json.get('message', ''))
                        # Buscar causes (detalle adicional de ML)
                        causes = legacy_json.get('cause', legacy_json.get('causes', []))
                        if causes:
                            lines.append("    causes: %s" % str(causes)[:300])
                    lines.append("    → PUT legacy /items NO funciona")
                else:
                    new_avail = legacy_json.get('available_quantity', '?') if isinstance(legacy_json, dict) else '?'
                    lines.append("    RESULTADO: OK HTTP %s (%.2fs) ✓" % (legacy_resp.status_code, elapsed))
                    lines.append("    → PUT legacy /items FUNCIONA ✓")
                    lines.append("    available_quantity resultante: %s" % new_avail)
            except Exception as E:
                lines.append("    EXCEPTION: %s" % str(E)[:150])

            # 4e) PUT a /items/{id}/stock (endpoint alternativo documentado)
            lines.append("")
            lines.append("  [4e] PUT /items/%s/stock (endpoint alternativo)" % meli_id)
            if found_types.get('seller_warehouse'):
                sw = found_types['seller_warehouse']
                items_stock_body = {
                    "locations": [{
                        "type": "seller_warehouse",
                        "store_id": sw.get('store_id', ''),
                        "network_node_id": sw.get('network_node_id', ''),
                        "quantity": int(sw.get('quantity', 0)),
                    }]
                }
            else:
                items_stock_body = {"available_quantity": int(current_avail) if 'current_avail' in dir() else 0}

            items_stock_url = "https://api.mercadolibre.com/items/%s/stock" % str(meli_id)
            items_stock_hdrs = dict(auth_headers)
            items_stock_hdrs['Content-Type'] = 'application/json'
            lines.append("    body: %s" % str(items_stock_body))
            t0 = _time.time()
            try:
                is_resp = requests.put(items_stock_url, headers=items_stock_hdrs, data=_json.dumps(items_stock_body), timeout=15)
                elapsed = _time.time() - t0
                is_json = is_resp.json() if is_resp.text else {}
                if is_resp.status_code >= 400:
                    lines.append("    RESULTADO: ERROR HTTP %s (%.2fs)" % (is_resp.status_code, elapsed))
                    if isinstance(is_json, dict):
                        lines.append("    error: %s" % is_json.get('error', ''))
                        lines.append("    message: %s" % is_json.get('message', ''))
                    lines.append("    → PUT /items/{id}/stock NO funciona")
                else:
                    lines.append("    RESULTADO: OK HTTP %s (%.2fs) ✓" % (is_resp.status_code, elapsed))
                    lines.append("    → PUT /items/{id}/stock FUNCIONA ✓")
                    lines.append("    respuesta: %s" % str(is_json)[:200])
            except Exception as E:
                lines.append("    EXCEPTION: %s" % str(E)[:150])

            # 4d) PUT /user-products/{id}/stock — probar varios formatos de body
            # para descubrir cuál acepta ML para este seller (algunos dan 404 con un
            # formato y aceptan otro).
            lines.append("")
            lines.append("  [4d] TEST PUT /user-products/%s/stock (sin tipo) — múltiples formatos" % up_id)

            put_d_url = "https://api.mercadolibre.com/user-products/%s/stock" % str(up_id)
            put_d_hdrs_base = dict(auth_headers)
            put_d_hdrs_base['Content-Type'] = 'application/json'

            # Extraer datos de la primera ubicación detectada en [4a]
            _first_loc_data = next(iter(found_types.values()), {}) if found_types else {}
            _sw_qty = int(_first_loc_data.get('quantity', 0))
            _sw_store = _first_loc_data.get('store_id')
            _sw_node = _first_loc_data.get('network_node_id')
            _first_loc_type = next(iter(found_types.keys()), 'seller_warehouse') if found_types else 'seller_warehouse'

            # Todas las ubicaciones del tipo detectado (multi-depósito)
            _primary_type = _first_loc_type
            _all_same_type = [l for l in found_all_locs if l.get('type') == _primary_type]
            lines.append("  [4d] Ubicaciones detectadas tipo '%s': %d (depósitos: %s)" % (
                _primary_type, len(_all_same_type),
                ", ".join(str(l.get('store_id', '?')) for l in _all_same_type) if _all_same_type else "(ninguno)"
            ))

            # Los formatos a probar
            _bodies_to_test = []
            if _sw_store:
                _bodies_to_test.append(
                    ("locations+store_id", {"locations": [{"quantity": _sw_qty, "store_id": _sw_store}]})
                )
                _bodies_to_test.append(
                    ("locations+type+store_id", {"locations": [{"type": _first_loc_type, "quantity": _sw_qty, "store_id": _sw_store}]})
                )
                if _sw_node:
                    _bodies_to_test.append(
                        ("locations+store+node", {"locations": [{"quantity": _sw_qty, "store_id": _sw_store, "network_node_id": _sw_node}]})
                    )
            # Multi-depósito: incluir TODAS las ubicaciones detectadas del mismo tipo
            if len(_all_same_type) > 1:
                _multi_locs_body = []
                _total_existing = sum(l.get('quantity', 0) for l in _all_same_type)
                for _ml in _all_same_type:
                    _ml_entry = {"quantity": _ml.get('quantity', 0) or 0}
                    if _ml.get('store_id'):
                        _ml_entry["store_id"] = _ml["store_id"]
                    if _ml.get('network_node_id'):
                        _ml_entry["network_node_id"] = _ml["network_node_id"]
                    _multi_locs_body.append(_ml_entry)
                _bodies_to_test.append(("locations+all_deposits", {"locations": _multi_locs_body}))
            _bodies_to_test.append(("simple_quantity", {"quantity": _sw_qty}))
            _bodies_to_test.append(("available_quantity", {"available_quantity": _sw_qty}))

            _found_working_format = False
            for _fmt_name, _put_d_body in _bodies_to_test:
                if _found_working_format:
                    break
                for _use_xver in ([True, False] if x_version else [False]):
                    put_d_hdrs = dict(put_d_hdrs_base)
                    if _use_xver and x_version:
                        put_d_hdrs['X-Version'] = str(x_version)
                    _xver_label = ("X-Version: " + str(x_version)) if _use_xver and x_version else "sin X-Version"
                    lines.append("")
                    lines.append("    Formato: %s | %s" % (_fmt_name, _xver_label))
                    lines.append("    body: %s" % str(_put_d_body))
                    t0 = _time.time()
                    try:
                        put_d_resp = requests.put(put_d_url, headers=put_d_hdrs,
                                                  data=_json.dumps(_put_d_body), timeout=15)
                        elapsed = _time.time() - t0
                        put_d_json = put_d_resp.json() if put_d_resp.text else {}
                        if put_d_resp.status_code >= 400:
                            lines.append("    → HTTP %s (%.2fs): error=%s msg=%s" % (
                                put_d_resp.status_code, elapsed,
                                put_d_json.get('error', put_d_json.get('code', '?')),
                                str(put_d_json.get('message', ''))[:100]))
                        else:
                            lines.append("    → HTTP %s (%.2fs) ✓ FUNCIONA con formato '%s'" % (
                                put_d_resp.status_code, elapsed, _fmt_name))
                            lines.append("      respuesta: %s" % str(put_d_json)[:200])
                            _found_working_format = True
                            break
                    except Exception as E:
                        lines.append("    → EXCEPTION: %s" % str(E)[:100])

            if not _found_working_format:
                lines.append("")
                lines.append("    ⚠ Ningún formato funcionó para PUT /user-products/{id}/stock")

        # --- AUTO-CONFIGURACIÓN basada en resultados del diagnóstico ---
        lines.append("")
        lines.append("=== Auto-configuración ===")
        config = self.configuration
        _config_changed = False
        if _working_put_types and config:
            _preferred_type = 'seller_warehouse' if 'seller_warehouse' in _working_put_types else _working_put_types[0]
            _current_mode = config.mercadolibre_stock_update_mode
            _current_type = config.mercadolibre_stock_update_type

            if _current_mode in (False, None, '', 'standard', 'user_product'):
                config.write({'mercadolibre_stock_update_mode': 'auto'})
                _config_changed = True
                lines.append("  mercadolibre_stock_update_mode: '%s' → 'auto'" % (_current_mode or 'standard'))
            else:
                lines.append("  mercadolibre_stock_update_mode: '%s' (sin cambios)" % _current_mode)

            if _current_type != _preferred_type:
                config.write({'mercadolibre_stock_update_type': _preferred_type})
                _config_changed = True
                lines.append("  mercadolibre_stock_update_type: '%s' → '%s'" % (_current_type or '(vacío)', _preferred_type))
            else:
                lines.append("  mercadolibre_stock_update_type: '%s' (sin cambios)" % _current_type)
        elif not _working_put_types and config:
            _current_mode = config.mercadolibre_stock_update_mode
            if _current_mode in ('auto', 'user_product', 'user_product_type'):
                config.write({'mercadolibre_stock_update_mode': 'standard'})
                _config_changed = True
                lines.append("  Ningún endpoint user-products funciona → mercadolibre_stock_update_mode: '%s' → 'standard'" % _current_mode)
                lines.append("  El stock se actualizará via PUT /items/{id} (modo legacy).")
            else:
                lines.append("  No se detectaron endpoints PUT funcionales — modo '%s' (sin cambios)." % (_current_mode or 'standard'))
        else:
            lines.append("  Sin configuración asociada — no se pudo auto-configurar.")

        if _config_changed:
            lines.append("  ✓ Configuración actualizada. Los productos multiwarehouse se sincronizarán automáticamente.")
        lines.append("  Endpoints PUT funcionales: %s" % (", ".join(_working_put_types) if _working_put_types else "(ninguno)"))

        lines.append("")
        lines.append("=== Fin del diagnóstico ===")

        result_text = "\n".join(lines)

        wizard = self.env['meli.multiwarehouse.diagnostic'].create({'result_text': result_text})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Check & Test Multiwarehouse',
            'res_model': 'meli.multiwarehouse.diagnostic',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _run_stock_diagnostic_for_cron(self):
        """
        Wrapper to call the stock diagnostic from the stock cron.
        Records the last run time and swallows exceptions so the cron is never broken.
        """
        try:
            self.action_diagnose_stock_config()
            self.write({'meli_cron_last_diagnostic': fields.Datetime.now()})
            if not getattr(threading.current_thread(), 'testing', False):
                MeliCommit(self)
        except Exception as _e:
            _logger.warning("_run_stock_diagnostic_for_cron: diagnostic failed: %s", _e)

    def action_diagnose_stock_config(self):
        """
        Diagnóstico de configuración de stock de la cuenta ML.
        Verifica almacén, ubicaciones activas, modo de actualización,
        consistencia y publicaciones pausadas/sin movimiento.
        Postea el reporte en el chatter de la cuenta como nota interna.
        """
        import time as _time
        t_diag_start = _time.time()

        self.ensure_one()
        account = self
        config = account.configuration
        if not config:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Diagnóstico de Stock',
                    'message': '❌ Esta cuenta no tiene configuración asociada.',
                    'type': 'danger',
                    'sticky': True,
                },
            }
        company = account.company_id or self.env.user.company_id

        OK   = "✅"
        WARN = "⚠️"
        ERR  = "❌"
        issues = []
        infos  = []

        # ── 1. Modo de actualización ──────────────────────────────────────────
        mode       = (hasattr(config, 'mercadolibre_stock_update_mode') and config.mercadolibre_stock_update_mode) or 'standard'
        qty_method = (hasattr(config, 'mercadolibre_stock_virtual_available') and config.mercadolibre_stock_virtual_available) or 'virtual'
        _MODE_LABELS = {
            'standard':          'Estándar (PUT /items/{id})',
            'auto':              'Automático (detecta por publicación)',
            'user_product':      'Multi-warehouse (PUT /user-products/{id}/stock)',
            'user_product_type': 'Multi-warehouse por tipo',
        }
        _QTY_LABELS = {
            'virtual':           'Virtual disponible (reservas descontadas)',
            'virtual_absoluto':  'Virtual absoluto (sin negativos)',
            'theoretical':       'Teórico (stock real sin movimientos)',
            'qty_reserved':      'Stock - reservado',
        }
        infos.append((OK, "Modo: <b>%s</b>" % html_escape(_MODE_LABELS.get(mode, mode))))
        infos.append((OK, "Método cantidad: <b>%s</b>" % html_escape(_QTY_LABELS.get(qty_method, qty_method))))

        # ── 2. Almacén estándar ───────────────────────────────────────────────
        wh          = config.mercadolibre_stock_warehouse
        loc_to_post = config.mercadolibre_stock_location_to_post
        if wh:
            infos.append((OK, "Almacén configurado: <b>%s</b> → ubicación stock: %s"
                          % (html_escape(wh.name), html_escape(wh.lot_stock_id.complete_name))))
        else:
            infos.append((WARN, "No hay almacén configurado (<i>mercadolibre_stock_warehouse</i> vacío)"))
        if loc_to_post:
            infos.append((OK, "Ubicación directa (override): <b>%s</b>" % html_escape(loc_to_post.complete_name)))

        # ── 3. Ubicaciones con mercadolibre_active=True ───────────────────────
        active_locs = self.env['stock.location'].search([
            ('mercadolibre_active', '=', True),
            ('company_id', '=', company.id),
        ])
        non_full_active = active_locs.filtered(
            lambda l: not l.mercadolibre_logistic_type or 'fulfillment' not in (l.mercadolibre_logistic_type or '')
        )
        full_active = active_locs - non_full_active

        if not active_locs:
            if not wh and not loc_to_post:
                issues.append((ERR, "Sin ubicaciones activas ni almacén configurado — el stock <b>no se enviará</b> a ML"))
            else:
                infos.append((OK, "Sin ubicaciones con <i>mercadolibre_active</i> — se usará el almacén/ubicación directa configurada"))
        else:
            infos.append((OK, "Ubicaciones con <i>mercadolibre_active=True</i>: <b>%d</b>" % len(active_locs)))
            if wh and non_full_active:
                wh_lot = wh.lot_stock_id
                wh_descendants = self.env['stock.location'].search([('id', 'child_of', wh_lot.id)])
                wh_ids = set(wh_descendants.ids) | {wh_lot.id}
                in_wh  = non_full_active.filtered(lambda l: l.id in wh_ids)
                out_wh = non_full_active.filtered(lambda l: l.id not in wh_ids)
                if in_wh:
                    infos.append((OK, "Dentro del almacén '<b>%s</b>': %s"
                                  % (html_escape(wh.name), ", ".join(html_escape(l.complete_name) for l in in_wh))))
                if out_wh:
                    _psl = config.publish_stock_locations if ("publish_stock_locations" in config._fields and config.publish_stock) else self.env['stock.location']
                    _psl_ids = set(_psl.ids) if _psl else set()
                    out_covered = out_wh.filtered(lambda l: l.id in _psl_ids)
                    out_excluded = out_wh - out_covered
                    if out_covered:
                        infos.append((WARN,
                            "<b>%d ubicación(es) activa(s) FUERA del almacén '%s'</b> pero incluidas en "
                            "<i>Publish Stock location</i> — se usarán en el cálculo:<br/>%s"
                            % (len(out_covered), html_escape(wh.name),
                               "<br/>".join("&nbsp;&nbsp;• " + html_escape(l.complete_name) for l in out_covered))))
                    if out_excluded:
                        issues.append((WARN,
                            "<b>%d ubicación(es) activa(s) FUERA del almacén '%s'</b> y NO en "
                            "<i>Publish Stock location</i> — se excluirán del cálculo:<br/>%s"
                            % (len(out_excluded), html_escape(wh.name),
                               "<br/>".join("&nbsp;&nbsp;• " + html_escape(l.complete_name) for l in out_excluded))))
            elif non_full_active and not wh and not loc_to_post:
                issues.append((WARN,
                    "Hay <b>%d ubicación(es)</b> activa(s) sin almacén configurado — "
                    "el stock se suma de todas (posible sobrestock en ML):<br/>%s"
                    % (len(non_full_active),
                       "<br/>".join("&nbsp;&nbsp;• " + html_escape(l.complete_name) for l in non_full_active))))
            else:
                for l in non_full_active:
                    infos.append((OK, "&nbsp;&nbsp;• %s" % html_escape(l.complete_name)))

        # ── 4. Configuración FULL ─────────────────────────────────────────────
        wh_full  = config.mercadolibre_stock_warehouse_full
        loc_full = config.mercadolibre_stock_location_to_post_full
        if wh_full:
            infos.append((OK, "Almacén FULL: <b>%s</b>" % html_escape(wh_full.name)))
        if loc_full:
            infos.append((OK, "Ubicación FULL directa: <b>%s</b>" % html_escape(loc_full.complete_name)))
        if full_active:
            infos.append((OK, "Ubicaciones FULL activas: %s" % ", ".join(html_escape(l.complete_name) for l in full_active)))
        if not wh_full and not loc_full and not full_active:
            infos.append((OK, "Sin configuración FULL (normal si no hay publicaciones fulfillment)"))

        # ── 5. Multi-ubicación explícita ──────────────────────────────────────
        multi_locs = hasattr(config, 'mercadolibre_stock_location_to_post_many') and config.mercadolibre_stock_location_to_post_many
        if multi_locs:
            infos.append((OK, "Multi-ubicación: <b>%d</b> ubicación(es) configuradas" % len(multi_locs)))

        # ── 6. Consistencia modo multi-warehouse ──────────────────────────────
        if mode in ('auto', 'user_product', 'user_product_type'):
            is_mw = getattr(account, 'multiwarehouse', False)
            if not is_mw:
                issues.append((WARN,
                    "Modo '<b>%s</b>' configurado pero el vendedor no está marcado como "
                    "multi-almacén en ML. Verificar con 'Check &amp; Test Multiwarehouse'." % html_escape(mode)))
            else:
                infos.append((OK, "Vendedor confirmado como multi-warehouse en ML"))

        # ── 7. Config vacía ───────────────────────────────────────────────────
        if not wh and not loc_to_post and not active_locs and not multi_locs:
            issues.append((ERR, "Configuración vacía — el stock <b>no se actualizará</b> en ML."))

        # ── 8. Publicaciones pausadas / sin movimiento ────────────────────────
        MeliProd = self.env['mercadolibre.product']
        threshold_days = 30
        threshold_date = fields.Datetime.now() - timedelta(days=threshold_days)

        groups = MeliProd.read_group(
            domain=[('connection_account', '=', account.id)],
            fields=['meli_last_status'],
            groupby=['meli_last_status'],
        )
        status_counts = {(g['meli_last_status'] or 'desconocido'): g['meli_last_status_count'] for g in groups}
        total_pubs = sum(status_counts.values())

        if total_pubs > 0:
            status_str = ", ".join(
                "<b>%s</b>: %d" % (html_escape(s), c)
                for s, c in sorted(status_counts.items(), key=lambda x: -x[1])
            )
            infos.append((OK, "Publicaciones: <b>%d</b> — %s" % (total_pubs, status_str)))

            paused_with_stock = MeliProd.search([
                ('connection_account', '=', account.id),
                ('meli_last_status', '=', 'paused'),
                ('meli_available_quantity', '>', 0),
            ], limit=11)
            if paused_with_stock:
                shown = paused_with_stock[:10]
                detail = "<br/>".join(
                    "&nbsp;&nbsp;• <b>%s</b> — %s — stock: %d uds" % (
                        html_escape(p.meli_id or p.conn_id or '?'),
                        html_escape((p.product_id.display_name if p.product_id else p.name or '')[:60]),
                        p.meli_available_quantity,
                    ) for p in shown
                )
                if len(paused_with_stock) > 10:
                    detail += "<br/>&nbsp;&nbsp;<i>... y más.</i>"
                issues.append((ERR,
                    "<b>%d publicación(es) PAUSADA(S) con stock en Odoo</b> — posible pérdida de ventas:<br/>%s"
                    % (len(shown), detail)))

            stale_paused = MeliProd.search_count([
                ('connection_account', '=', account.id),
                ('meli_last_status', '=', 'paused'),
                '|', ('meli_stock_moves_update', '=', False),
                     ('meli_stock_moves_update', '<', threshold_date),
            ])
            if stale_paused:
                issues.append((WARN, "<b>%d pausada(s)</b> sin movimiento de stock en +%d días — revisar si reactivar" % (stale_paused, threshold_days)))

            stale_active = MeliProd.search_count([
                ('connection_account', '=', account.id),
                ('meli_last_status', '=', 'active'),
                ('meli_stock_moves_update', '!=', False),
                ('meli_stock_moves_update', '<', threshold_date),
            ])
            if stale_active:
                infos.append((WARN, "<b>%d activa(s)</b> sin movimiento en +%d días — stock podría estar desincronizado" % (stale_active, threshold_days)))

            active_zero = MeliProd.search_count([
                ('connection_account', '=', account.id),
                ('meli_last_status', '=', 'active'),
                ('meli_available_quantity', '=', 0),
            ])
            if active_zero:
                issues.append((WARN, "<b>%d activa(s) con stock = 0</b> en Odoo — ML puede pausarlas en próximo cron" % active_zero))
        else:
            infos.append((OK, "Sin publicaciones registradas para esta cuenta"))

        # ── Build HTML report ─────────────────────────────────────────────────
        elapsed = _time.time() - t_diag_start
        n_issues = len(issues)
        status_icon = OK if n_issues == 0 else WARN
        status_text = "Sin problemas detectados" if n_issues == 0 else "%d problema(s) detectado(s)" % n_issues
        notif_type  = "success" if n_issues == 0 else "warning"

        lines = [
            "<div style='font-family:monospace;font-size:13px'>",
            "<h3>%s Diagnóstico de Stock — %s</h3>" % (status_icon, html_escape(status_text)),
            "<b>Cuenta:</b> %s &nbsp;|&nbsp; <b>Config:</b> %s &nbsp;|&nbsp; <b>Tiempo:</b> %.2fs<br/><br/>"
            % (html_escape(account.name or str(account.id)), html_escape(config.name or str(config.id)), elapsed),
            "<b>Información:</b><ul>",
        ]
        for icon, text in infos:
            lines.append("<li>%s %s</li>" % (icon, text))
        lines.append("</ul>")
        if issues:
            lines.append("<b>Problemas / Advertencias:</b><ul>")
            for icon, text in issues:
                lines.append("<li>%s %s</li>" % (icon, text))
            lines.append("</ul>")
        lines.append("</div>")

        self.message_post(body=Markup("".join(lines)), message_type='comment', subtype_xmlid='mail.mt_note')
        _logger.info("action_diagnose_stock_config: account=%s elapsed=%.2fs issues=%d", account.name, elapsed, n_issues)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Diagnóstico de Stock',
                'message': "%s %s — Ver chatter para el reporte completo." % (status_icon, status_text),
                'type': notif_type,
                'sticky': n_issues > 0,
            },
        }

    def is_seller_allowed(self, user_id):
        """Check if a user_id (seller) is allowed for this account."""
        self.ensure_one()
        user_id_str = str(user_id) if user_id else ""

        # Check main seller_id
        if self.seller_id and str(self.seller_id) == user_id_str:
            return True

        # Check additional sellers
        if self.meli_additional_seller_ids:
            additional_ids = [s.strip() for s in self.meli_additional_seller_ids.split(',') if s.strip()]
            if user_id_str in additional_ids:
                return True

        return False

    def get_fields_credentials( self ):

        fields_credentials = []

        for acc in self:
            if (acc.type == "mercadolibre"):
                fields_credentials+= [ 'redirect_uri','meli_login_id','official_store_id','brand']
                fields_credentials+= [ 'client_id', 'secret_key', 'seller_id','access_token', 'refresh_token']
                fields_credentials+= [ 'cron_refresh']

        return fields_credentials

    def get_fields_status( self ):
        fields_status = []

        for acc in self:
            fields_credentials = acc.get_fields_credentials()
            fields_status+= [
                'name', 'status', 'company_id',  'country_id',
                'type', 'connector_version','ocapi_version'
            ]+fields_credentials

        return fields_status

    def fetch_status( self, **post ):
        _logger.info("mercadolibre.account > fetch_status")
        result = []
        for acc in self:
            
            if "connection_monitor" in acc._fields and not acc.connection_monitor:
                json_status = {
                    "status": "monitor down"
                }
                result.append(json_status)
                continue;

            json_status = {
                "status": "connected"
            }

            fields_status = acc.get_fields_status()

            _logger.info("mercadolibre.account > fetch_status fields_status: "+str(fields_status))

            raw_data = acc and acc.read(fields_status)

            _logger.info("mercadolibre.account > fetch_status raw_data: "+str(raw_data))

            if raw_data and raw_data[0]:
                json_status = json.loads( json.dumps( raw_data[0], default=json_default) )
                json_status["status"] = (acc.access_token and "connected") or "disconnected"
                #PERF: contar con search_count, no con len() de un one2many —
                #len() materializa TODO el recordset (decenas de miles de bindings).
                json_status["mercadolibre_product_template_bindings"] = self.env['mercadolibre.product_template'].search_count([('connection_account', '=', acc.id)])
                json_status["mercadolibre_product_bindings"] = self.env['mercadolibre.product'].search_count([('connection_account', '=', acc.id)])
                json_status["mercadolibre_orders"] = self.env['mercadolibre.orders'].search_count([('connection_account', '=', acc.id)])

                #buscar notifications
                json_status["mercadolibre_notifications"] = self.env["mercadolibre.notification"].search_count([('connection_account','=',acc.id)])
                #json_status["mercadolibre_notifications_errors"] = self.env["mercadolibre.notification"].search_count([('connection_account','=',acc.id)])

            result.append(json_status)

        _logger.info(result)
        return result

    def _mercadolibre_brands( self ):
        brands = []
        for ac in self:
            company = ac.company_id or ac.env.user.company_id
            ac_official_store_id = ac.official_store_id
            seller_id = ac.seller_id

            br = ac_official_store_id and self.env["mercadolibre.brand"].search([('official_store_id','=',str(ac_official_store_id) )],limit=1)
            if br and br.id:
                brands.append(br)
                continue;

            meli = self.env['meli.util'].get_new_instance( company, ac )
            #ac.mercadolibre_brands = [(5)]
            if meli:
                response = meli.get("/users/"+str(seller_id)+"/brands", {'access_token':meli.access_token })
                rjson = response and response.json()
                #_logger.info("_mercadolibre_brands rjson: "+str(rjson))
                if rjson and not "error" in rjson and "brands" in rjson:
                    #search and create
                    for bra in rjson["brands"]:
                        #_logger.info("_mercadolibre_brands bra: "+str(bra))

                        brand = {
                            "name": "name" in bra and bra["name"],
                            "site_id": "site_id" in bra and bra["site_id"],
                            "official_store_id": "official_store_id" in bra and bra["official_store_id"],
                            "seller_id": seller_id,

                            "fantasy_name": "fantasy_name" in bra and bra["fantasy_name"],
                            "status": "status" in bra and bra["status"],
                            "type": "type" in bra and bra["type"],
                            "permalink": "permalink" in bra and bra["permalink"],
                        }

                        official_store_id = 'official_store_id' in bra and bra['official_store_id']
                        if not br or not br.id:
                            #skip

                            br = self.env["mercadolibre.brand"].create(brand)
                            #if br:
                            #    #_logger.info("Created mercadolibre.brand: "+str(brand)+" id:"+str(br))
                        else:
                            #br.write(brand)
                            pass;

                        brands.append(br)


        return brands
                        #    ac.mercadolibre_brands = [(4,0,[br.id])]

    #mercadolibre_brands = fields.Many2many("mercadolibre.brand",relation='mercadolibre_account_brands_rel',string="Brands")


    def _meli_brand( self ):
        for ac in self:
            ac.brand = None
            #if not ac.mercadolibre_brands:
            try:
                mercadolibre_brands = ac._mercadolibre_brands()
                #_logger.info("mercadolibre_brands: "+str(mercadolibre_brands))
                if mercadolibre_brands:
                    for br in mercadolibre_brands:
                        if br.official_store_id and str(br.official_store_id)==str(ac.official_store_id):
                            ac.brand = br
            except:
                pass;

    brand = fields.Many2one("mercadolibre.brand",compute=_meli_brand,string="Brand" )

    def create_credentials(self, context=None):
        context = context or self.env.context
        #_logger.info("create_credentials: " + str(context))

        now = datetime.now()
        date_time = now.strftime("%m/%d/%Y, %H:%M:%S")
        base_str = str(self.name) + str(date_time)

        hash = hashlib.md5(base_str.encode())
        hexhash = hash.hexdigest()

        self.client_id = hexhash

        base_str = str(self.name) +str(self.client_id) + str(date_time)

        hash = hashlib.md5(base_str.encode())
        hexhash = hash.hexdigest()

        self.secret_key = hexhash

    def authorize_token(self, client_id, secret_key ):

        if not secret_key or not client_id or self.client_id != client_id or self.secret_key != secret_key:
            return { "error": "Bad credentials", "message": "Bad credentials, values does not match with any configuration" }

        now = datetime.now()
        date_time = now.strftime("%m/%d/%Y, %H:%M:%S")
        base_str = str(client_id) + str(secret_key) + str(date_time)

        hash = hashlib.blake2b()
        hash.update( base_str.encode() )
        hexhash = hash.hexdigest()

        access_token = hexhash
        self.access_token = access_token

        return access_token

    def get_connector_state(self):

        for connacc in self:
            connacc.status = "disconnected"
            #_logger.info( 'meli_oerp_multiple account get_connector_state() ' + str(connacc and connacc.name) )

            # Refresh proactivo: si el access_token vence en menos de 15 minutos,
            # forzar el refresh ahora (misma ruta que el botón manual "Refrescar Token")
            # en vez de esperar a que ML nos devuelva un error. Esto evita la ventana
            # de desconexión que ocurre entre el vencimiento real y la próxima corrida
            # del cron que detecte el error.
            if connacc.access_token and connacc.refresh_token and connacc.access_token_expires_at:
                threshold = connacc.access_token_expires_at - timedelta(minutes=15)
                if fields.Datetime.now() >= threshold:
                    _logger.info(
                        "Proactive refresh for %s (expires at %s)",
                        connacc.name, connacc.access_token_expires_at
                    )
                    try:
                        self.env['meli.util'].get_new_instance(
                            connacc.company_id, connacc, refresh_force=True
                        )
                    except Exception as e:
                        _logger.error(
                            "Proactive refresh failed for %s: %s", connacc.name, e
                        )

            #PERF: el estado se deduce del token local (presente y no vencido), sin
            #round-trip a ML. get_new_instance() incondicional costaba ~375 ms cada vez
            #que se abría el form de la cuenta (get_connector_state computa status+state,
            #ambos visibles en el form) y empeoraba con 429. El chequeo real contra ML lo
            #hacen los crones y las operaciones, que además refrescan el token; arriba
            #ya está el refresh proactivo.
            exp = connacc.access_token_expires_at
            connected = bool(connacc.access_token) and (not exp or exp > fields.Datetime.now())
            connacc.status = "connected" if connected else "disconnected"
            connacc.state = connected

    status = fields.Selection([("disconnected","Disconnected"),("connected","Connected")],
                                string="Status",
                                compute='get_connector_state')
    state = fields.Boolean( compute='get_connector_state', string="State", help="Estado de la conexión", readonly=False )

    mercadolibre_product_template_bindings = fields.One2many( "mercadolibre.product_template", "connection_account", string="Product Bindings" )
    mercadolibre_product_bindings = fields.One2many( "mercadolibre.product", "connection_account", string="Product Variant Bindings" )
    mercadolibre_orders = fields.One2many( "mercadolibre.orders", "connection_account", string="Orders" )

    # Campos para vista Kanban y estadísticas
    account_state = fields.Selection([
        ("new", "Nuevo"),
        ("configuring", "Configurando"),
        ("active", "Activo"),
        ("paused", "Pausado"),
        ("error", "Error"),
        ("disconnected", "Desconectado")
    ], string="Estado Cuenta", default="active", tracking=True,
       help="Estado operacional de la cuenta de MercadoLibre")

    # Campo relacionado para ver/editar modo de configuración directamente
    configuration_mode = fields.Selection(
        related='configuration.mode',
        string="Modo Configuración",
        readonly=False,
        help="Modo de la configuración asociada (Production/Test/Disabled)"
    )

    kanban_color = fields.Integer(string="Color", compute="_compute_kanban_color", store=False)

    products_count = fields.Integer(
        string="Productos",
        compute="_compute_products_count",
        help="Cantidad de productos publicados en esta cuenta"
    )

    orders_count = fields.Integer(
        string="Órdenes",
        compute="_compute_orders_count",
        help="Cantidad de órdenes importadas en esta cuenta"
    )

    orders_pending_count = fields.Integer(
        string="Órdenes Pendientes",
        compute="_compute_orders_pending_count",
        help="Cantidad de órdenes pendientes de procesar"
    )

    publications_count = fields.Integer(
        string="Publicaciones",
        compute="_compute_publications_count",
        help="Cantidad de publicaciones con ML ID en esta cuenta"
    )

    last_order_date = fields.Datetime(
        string="Última Orden",
        compute="_compute_last_order_date",
        help="Fecha de la última orden importada"
    )

    last_sync_products = fields.Datetime(
        string="Última Sync Productos",
        help="Fecha de la última sincronización de productos"
    )

    last_sync_orders = fields.Datetime(
        string="Última Sync Órdenes",
        help="Fecha de la última sincronización de órdenes"
    )

    @api.depends('account_state', 'status')
    def _compute_kanban_color(self):
        """Compute color for kanban view based on account state."""
        color_map = {
            'new': 4,        # Azul claro
            'configuring': 3, # Amarillo
            'active': 10,     # Verde
            'paused': 2,      # Naranja
            'error': 1,       # Rojo
            'disconnected': 0 # Gris
        }
        for rec in self:
            if rec.status == 'disconnected':
                rec.kanban_color = 0  # Gris si está desconectado
            else:
                rec.kanban_color = color_map.get(rec.account_state, 0)

    def _compute_products_count(self):
        """Compute total products count for this account."""
        for rec in self:
            rec.products_count = self.env['mercadolibre.product_template'].search_count([('connection_account', '=', rec.id)]) if rec.id else 0  # PERF: search_count, no len(o2m)

    def _compute_orders_count(self):
        """Compute total orders count for this account."""
        for rec in self:
            rec.orders_count = self.env['mercadolibre.orders'].search_count([('connection_account', '=', rec.id)]) if rec.id else 0  # PERF: search_count, no len(o2m)

    def _compute_orders_pending_count(self):
        """Compute pending orders count."""
        for rec in self:
            rec.orders_pending_count = self.env['mercadolibre.orders'].search_count([
                ('connection_account', '=', rec.id),
                ('status', 'in', ['pending', 'confirmed', 'payment_required'])
            ])

    def _compute_publications_count(self):
        """Compute count of product variants with ML ID (conn_id) for this account."""
        for rec in self:
            rec.publications_count = self.env['mercadolibre.product_template'].search_count([
                ('connection_account', '=', rec.id),
                ('conn_id', '!=', False),
                ('conn_id', '!=', ''),
            ])

    def _compute_last_order_date(self):
        """Compute last order date."""
        for rec in self:
            last_order = self.env['mercadolibre.orders'].search([
                ('connection_account', '=', rec.id)
            ], order='date_created desc', limit=1)
            rec.last_order_date = last_order.date_created if last_order else False

    def action_set_active(self):
        """Set account state to active and configuration mode to production."""
        for acc in self:
            acc.write({'account_state': 'active'})
            if acc.configuration:
                acc.configuration.write({'mode': 'production'})

    def action_set_paused(self):
        """Set account state to paused and configuration mode to disabled."""
        for acc in self:
            acc.write({'account_state': 'paused'})
            if acc.configuration:
                acc.configuration.write({'mode': 'disabled'})

    def action_set_configuring(self):
        """Set account state to configuring and configuration mode to test."""
        for acc in self:
            acc.write({'account_state': 'configuring'})
            if acc.configuration:
                acc.configuration.write({'mode': 'test'})

    # Campos para CRON tracking
    cron_status_ids = fields.One2many(
        "mercadolibre.cron.status",
        "connection_account",
        string="Estado de CRONs"
    )

    cron_execution_ids = fields.One2many(
        "mercadolibre.cron.execution",
        "connection_account",
        string="Historial de Ejecuciones"
    )

    cron_company_warning = fields.Html(
        string="Aviso compañía del cron",
        compute="_compute_cron_company_warning",
        sanitize=False,
        help="Avisa si el Vendedor ML configurado para operar las ventas de esta "
             "cuenta no tiene la compañía de la cuenta en sus Compañías permitidas "
             "(en ese caso el cron no podría procesar/asignar sus ventas).",
    )

    @api.depends("company_id", "configuration")
    def _compute_cron_company_warning(self):
        # El dispatcher corre cada cuenta COMO su Vendedor ML (si está configurado),
        # en la compañía de la cuenta. Si el vendedor no tiene esa compañía permitida,
        # el cron no podrá operar sus ventas. (OdooBot, fallback sin vendedor, es
        # superusuario y ve todas las compañías → no genera aviso.)
        for acc in self:
            warn = ""
            config = acc.configuration or acc.company_id
            seller = config.mercadolibre_seller_user if (config and 'mercadolibre_seller_user' in config._fields) else False
            comp = acc.company_id
            if seller and seller.active and comp and comp.id not in seller.company_ids.ids:
                warn = (
                    "<div style=\"background:#fdecea;border:1px solid #f5c6cb;"
                    "border-left:6px solid #dc3545;padding:12px 16px;border-radius:4px;"
                    "color:#842029;font-size:14px;\">"
                    "<strong style=\"font-size:16px;\">&#9888; El CRON no podr&aacute; procesar esta cuenta</strong><br/>"
                    "El cron opera las ventas COMO el Vendedor ML <strong>%s</strong>, pero ese usuario "
                    "NO tiene la compa&#241;&iacute;a <strong>%s</strong> en sus <em>Compa&#241;&iacute;as "
                    "permitidas</em>. As&iacute; no puede crear/asignar las ventas de esta cuenta.<br/>"
                    "<strong>Soluci&oacute;n:</strong> agreg&aacute; <strong>%s</strong> a las Compa&#241;&iacute;as "
                    "permitidas de <strong>%s</strong> (Ajustes &rarr; Usuarios &rarr; %s &rarr; Permisos de acceso "
                    "&rarr; Multi-compa&#241;&iacute;a), o configur&aacute; un Vendedor ML que tenga esa compa&#241;&iacute;a."
                    "</div>"
                ) % (seller.name, comp.name, comp.name, seller.name, seller.name)
            acc.cron_company_warning = warn

    # Estado persistente del batch import cron
    cron_import_offset = fields.Integer(
        string='Cron Import Offset',
        default=0,
        help='Offset actual del batch import cron. Se resetea al completar un ciclo.'
    )
    cron_import_total = fields.Integer(
        string='Cron Import Total',
        default=0,
        help='Total de publicaciones no sincronizadas detectadas en el ultimo ciclo.'
    )
    cron_import_last_cycle = fields.Datetime(
        string='Ultimo ciclo completo',
        help='Fecha/hora del ultimo ciclo completo de importacion.'
    )
    cron_import_product_lines_json = fields.Text(
        string='Cron Import Cache',
        help='Cache JSON de product_lines para el ciclo actual del cron.'
    )

    def _ensure_cron_status(self):
        """Ensure all CRON status records exist for this account."""
        cron_types = [
            'orders', 'stock', 'stock_rt', 'products_post',
            'products_get', 'price', 'internal_jobs', 'questions', 'process',
            'batch_update', 'stock_diagnostic',
        ]
        # sudo: bookkeeping de sistema (modelo manager-only); create() de cuentas puede
        # correr en contexto no-manager → sin sudo da AccessError al leer/crear cron.status.
        CronStatus = self.env['mercadolibre.cron.status'].sudo()

        for acc in self.sudo():
            existing = acc.cron_status_ids.mapped('cron_type')
            for cron_type in cron_types:
                if cron_type not in existing:
                    CronStatus.create({
                        'connection_account': acc.id,
                        'cron_type': cron_type,
                        'is_enabled': True,
                    })

    def action_init_cron_status(self):
        """Initialize CRON status records for this account."""
        self._ensure_cron_status()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'CRONs Inicializados',
                'message': 'Se han creado los registros de estado de CRONs',
                'type': 'success',
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to automatically initialize CRON status records."""
        records = super(MercadoLibreConnectionAccount, self).create(vals_list)
        # Crear registros de CRON status para cada cuenta nueva
        records._ensure_cron_status()
        return records

    def _start_cron_execution(self, cron_type):
        """Start tracking a CRON execution.
        Any stale 'running' records for this account+type (orphaned by a
        previous hard crash) are marked as error before creating the new one.
        """
        from datetime import timedelta
        stale_threshold = fields.Datetime.now() - timedelta(hours=2)
        # sudo: el tracking de cron es bookkeeping de sistema; los crons corren como
        # __system__ (su=False) y el modelo es manager-only → sin sudo da AccessError.
        stale = self.env['mercadolibre.cron.execution'].sudo().search([
            ('connection_account', '=', self.id),
            ('cron_type', '=', cron_type),
            ('state', '=', 'running'),
            ('date_start', '<', stale_threshold),
        ])
        if stale:
            stale.write({
                'state': 'error',
                'date_end': fields.Datetime.now(),
                'error_message': 'Interrumpido (proceso terminado sin cierre)',
            })
            _logger.warning(
                "_start_cron_execution [%s/%s]: marcando %d ejecución(es) huérfana(s) como error",
                self.name, cron_type, len(stale)
            )
        return self.env['mercadolibre.cron.execution'].sudo().create({
            'connection_account': self.id,
            'cron_type': cron_type,
            'state': 'running',
            'date_start': fields.Datetime.now(),
        })

    def _fix_stuck_nextcall(self, cron_type):
        """Advance nextcall if it's stuck in the past.
        Utility method for manual use (e.g., post_init_hook, admin action).
        NOTE: calling this from within a cron execution has no effect because
        Odoo's own cron runner overwrites nextcall after the method returns.
        """
        from datetime import timedelta
        cron_status = self.env['mercadolibre.cron.status'].search([
            ('connection_account', '=', self.id),
            ('cron_type', '=', cron_type),
        ], limit=1)
        if not cron_status:
            return
        cron = (cron_status.individual_cron_id or cron_status.ir_cron_id)
        if not cron or not cron.active:
            return
        now = fields.Datetime.now()
        if cron.nextcall >= now:
            return
        interval_map = {
            'minutes': lambda n: timedelta(minutes=n),
            'hours':   lambda n: timedelta(hours=n),
            'days':    lambda n: timedelta(days=n),
            'weeks':   lambda n: timedelta(weeks=n),
            'months':  lambda n: timedelta(days=n * 30),
        }
        make_delta = interval_map.get(cron.interval_type, lambda n: timedelta(minutes=n))
        next_call = now + make_delta(cron.interval_number or 1)
        cron.sudo().write({'nextcall': next_call})
        _logger.info(
            "_fix_stuck_nextcall [%s/%s]: nextcall avanzado a %s",
            self.name, cron_type, next_call
        )

    def _end_cron_execution(self, execution, state='success', items_processed=0,
                            items_success=0, items_error=0, error_message=None, log_summary=None,
                            orders_by_notification=0, orders_new=0, orders_by_query=0,
                            orders_avg_time=0, orders_max_time=0, orders_min_time=0):
        """End tracking a CRON execution."""
        if execution:
            execution.sudo().write({
                'date_end': fields.Datetime.now(),
                'state': state,
                'items_processed': items_processed,
                'items_success': items_success,
                'items_error': items_error,
                'error_message': error_message,
                'log_summary': log_summary,
                'orders_by_notification': orders_by_notification,
                'orders_new': orders_new,
                'orders_by_query': orders_by_query,
                'orders_avg_time': orders_avg_time,
                'orders_max_time': orders_max_time,
                'orders_min_time': orders_min_time,
            })

    def action_view_cron_executions(self):
        """Open CRON execution history for this account."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Historial de Ejecuciones CRON',
            'res_model': 'mercadolibre.cron.execution',
            'view_mode': f'{view_mode_tree},form',
            'domain': [('connection_account', '=', self.id)],
            'context': {'default_connection_account': self.id},
        }

    def meli_refresh_token(self):
        _logger.info("meli_refresh_token: "+str(self and self.name))
        self.ensure_one()
        company = self.company_id or self.env.user.company_id
        #_logger.info(self.name)
        #_logger.info(self.company_id.name)
        meli = self.env['meli.util'].get_new_instance( company, self, refresh_force=True )

        #_logger.info("meli_refresh_token:"+str(meli))

    def meli_login(self):
        #_logger.info("meli_login")
        #_logger.info('company.meli_login() ')
        self.ensure_one()
        company = self.company_id or self.env.user.company_id
        #_logger.info(self)
        #_logger.info(self.company_id)
        meli = self.env['meli.util'].get_new_instance(company,self)

        return meli.redirect_login()

    def meli_logout(self):
        #_logger.info("meli_logout")
        self.ensure_one()
        company = (self and self.company_id) or self.env.user.company_id
        self.status = "disconnected"
        #self.state = True
        company.write({'mercadolibre_access_token': '', 'mercadolibre_refresh_token': '', 'mercadolibre_code': '' } )
        self.write({'access_token': '', 'refresh_token': '', 'code': '' } )
        return ""

    def meli_notifications(self, data=False, meli=None):

        account = self
        company = (account and account.company_id) or self.env.user.company_id
        config = (account and account.configuration) or company

        #_logger.info("account >> meli_notifications "+str(account.name))

        if (config.mercadolibre_process_notifications):
            return self.env['mercadolibre.notification'].fetch_lasts( data=data, company=company, account=account, meli=meli )
        return {}

#MELI CRON

    def cron_meli_process_internal_jobs(self):
        #_logger.info('account cron_meli_process_internal_jobs() ')
        for connacc in self:

            company = connacc.company_id or self.env.user.company_id
            config = connacc.configuration or company

            apistate = self.env['meli.util'].get_new_instance( company, connacc)
            if apistate.needlogin_state:
                return True

            execution = connacc._start_cron_execution('internal_jobs')
            connacc.env.cr.commit()
            try:
                if (config.mercadolibre_cron_post_update_stock):
                    #_logger.info("config.mercadolibre_cron_post_update_stock True "+str(config.name))
                    connacc.meli_update_remote_stock_injobs( meli=apistate )
                    connacc.meli_process_component_stock_updates( meli=apistate )

                # Price batch: check if we should start or continue a price batch
                connacc._check_price_batch(config=config, meli=apistate)

                connacc._end_cron_execution(execution, state='success')
            except Exception as e:
                connacc._end_cron_execution(execution, state='error', error_message=str(e))
                raise


    def meli_process_component_stock_updates(self, meli=None):
        """
        Process pending component_stock_update notifications.

        These are created by the stock optimization system when a component
        affects many BOMs (> threshold). Instead of updating all BOM parents
        immediately, a notification is created for deferred processing.
        """
        account = self
        company = account.company_id or self.env.user.company_id
        config = account.configuration or company

        if not config.mercadolibre_cron_post_update_stock:
            return {}

        # Find pending component_stock_update notifications
        notifs = self.env["mercadolibre.notification"].search([
            ('topic', '=', 'component_stock_update'),
            ('state', 'in', ['RECEIVED', 'PROCESSING']),
            ('connection_account', '=', account.id)
        ], limit=10, order='create_date asc')

        if not notifs:
            return {}

        _logger.info(f"meli_process_component_stock_updates: Processing {len(notifs)} notifications")

        for noti in notifs:
            try:
                noti._process_notification_component_stock_update(meli=meli)
            except Exception as e:
                _logger.error(f"Error processing component_stock_update {noti.id}: {e}")
                noti.state = 'FAILED'
                noti.processing_errors = str(e)

        return {}

    def cron_meli_orders(self):
        #_logger.info('account cron_meli_orders() ')

        for connacc in self:
            company = connacc.company_id or self.env.user.company_id
            config = (connacc and connacc.configuration) or company

            apistate = self.env['meli.util'].get_new_instance( company, connacc)
            if apistate.needlogin_state:
                # OJO: este `return` corta el cron para TODAS las cuentas restantes.
                # Se loguea para poder detectarlo en odoo.log (causa típica: token vencido).
                _logger.warning("cron_meli_orders [%s]: cuenta SIN LOGIN (token vencido / needlogin) — se omite y se CORTA el cron para el resto de las cuentas.", connacc.name)
                return True

            if (config.mercadolibre_cron_get_orders):
                #_logger.info("account config mercadolibre_cron_get_orders")
                # Get orders limit from config (default 10)
                orders_limit = config.mercadolibre_cron_orders_limit or 10
                _logger.info("cron_meli_orders [%s]: INICIO (limit=%s).", connacc.name, orders_limit)

                execution = connacc._start_cron_execution('orders')
                connacc.env.cr.commit()
                try:
                    # 1. Process pending order notifications (orders_v2)
                    notif_result = connacc.cron_process_order_notifications(meli=apistate, limit=orders_limit)
                    orders_notif = notif_result.get('processed', 0) if isinstance(notif_result, dict) else 0
                    errors_notif = notif_result.get('failed', 0) if isinstance(notif_result, dict) else 0
                    times_notif = notif_result.get('times', []) if isinstance(notif_result, dict) else []

                    # 2. Query unprocessed orders from last day
                    unproc_result = connacc.cron_process_unprocessed_orders(meli=apistate, limit=orders_limit)
                    orders_new = unproc_result.get('processed', 0) if isinstance(unproc_result, dict) else 0
                    errors_unproc = unproc_result.get('failed', 0) if isinstance(unproc_result, dict) else 0
                    times_unproc = unproc_result.get('times', []) if isinstance(unproc_result, dict) else []

                    # 3. Original order query as additional safety layer
                    query_result = connacc.meli_query_orders()
                    orders_query = len(query_result) if isinstance(query_result, list) else 0

                    # Aggregate timing across notification + unprocessed sources
                    all_times = times_notif + times_unproc
                    avg_time = sum(all_times) / len(all_times) if all_times else 0
                    max_time = max(all_times) if all_times else 0
                    min_time = min(all_times) if all_times else 0

                    total_errors = errors_notif + errors_unproc
                    total_success = orders_notif + orders_new
                    total = total_success + orders_query
                    summary = "Notif:%d | Nuevas:%d | Query:%d | Err:%d" % (
                        orders_notif, orders_new, orders_query, total_errors)
                    if avg_time:
                        summary += " | t/orden: prom=%.2fs máx=%.2fs mín=%.2fs" % (avg_time, max_time, min_time)
                    _logger.info("cron_meli_orders [%s]: %s", connacc.name, summary)
                    connacc._end_cron_execution(
                        execution, state='success',
                        items_processed=total,
                        items_success=total_success,
                        items_error=total_errors,
                        orders_by_notification=orders_notif,
                        orders_new=orders_new,
                        orders_by_query=orders_query,
                        orders_avg_time=avg_time,
                        orders_max_time=max_time,
                        orders_min_time=min_time,
                        log_summary=summary,
                    )
                except Exception as e:
                    _logger.error("cron_meli_orders [%s]: FALLÓ — %s", connacc.name, e, exc_info=True)
                    connacc._end_cron_execution(execution, state='error', error_message=str(e))
                    raise
            else:
                _logger.info("cron_meli_orders [%s]: SALTEADA (config 'Obtener pedidos por cron' apagado).", connacc.name)

            #if (config.mercadolibre_cron_get_questions):
            #    #_logger.info("account config mercadolibre_cron_get_questions")
            #    connacc.meli_query_get_questions()

    def cron_process_order_notifications(self, meli=None, limit=10):
        """
        Process pending order notifications (orders_v2) that were registered but not processed.

        This replaces the async processing that was killing the system.
        Notifications are grouped by resource (order ID), and only the latest notification
        per order is processed. Older notifications for the same order are marked as duplicates.

        Args:
            limit: Maximum number of unique ORDERS to process (not notifications)
        """
        account = self
        company = account.company_id or self.env.user.company_id
        config = account.configuration or company

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        # Find all pending order notifications for this account
        # Order by received DESC to get the most recent first
        notif_domain = [
            ('connection_account', '=', account.id),
            ('topic', '=', 'orders_v2'),
            ('state', 'in', ['RECEIVED', 'FAILED']),
        ]
        all_notifications = self.env['mercadolibre.notification'].search(notif_domain, order='received desc')
        _logger.info("CRON_ORDER_NOTIFICATIONS: cuenta %s — búsqueda local domain=%s, limit_órdenes=%s → encontradas=%d.",
                     account.name, notif_domain, limit, len(all_notifications))

        if not all_notifications:
            _logger.info("CRON_ORDER_NOTIFICATIONS: cuenta %s — sin notificaciones orders_v2 pendientes (estados RECEIVED/FAILED). El cron solo procesa órdenes con notificación viva por esta vía.", account.name)
            return {}

        # Group notifications by resource (order ID)
        # Structure: {resource: [notifications ordered by received desc]}
        notifications_by_order = {}
        for noti in all_notifications:
            resource = noti.resource
            if resource not in notifications_by_order:
                notifications_by_order[resource] = []
            notifications_by_order[resource].append(noti)

        # Get the N most recent unique orders (by their latest notification)
        # Sort orders by their most recent notification
        unique_orders = sorted(
            notifications_by_order.keys(),
            key=lambda r: notifications_by_order[r][0].received,
            reverse=True
        )[:limit]

        _logger.info("CRON_ORDER_NOTIFICATIONS: Found %d unique orders from %d notifications, processing %d for account %s",
                    len(notifications_by_order), len(all_notifications), len(unique_orders), account.name)

        import time as _time
        processed_count = 0
        failed_count = 0
        duplicates_count = 0
        order_times = []

        for resource in unique_orders:
            notis_for_order = notifications_by_order[resource]
            latest_noti = notis_for_order[0]  # Most recent notification for this order
            older_notis = notis_for_order[1:]  # Older notifications (duplicates)

            sp_name = 'sp_noti_%d' % latest_noti.id
            self.env.cr.execute('SAVEPOINT "%s"' % sp_name)
            try:
                # Intentar bloquear la fila exclusivamente; si otro worker la tiene, saltamos
                self.env.cr.execute(
                    'SELECT id FROM mercadolibre_notification WHERE id = %s FOR UPDATE NOWAIT',
                    (latest_noti.id,)
                )

                # Process only the latest notification for this order
                _logger.info("CRON_ORDER_NOTIFICATIONS: Processing order %s (latest of %d notifications)",
                            resource, len(notis_for_order))
                _t0 = _time.time()
                latest_noti._process_notification_order(meli=meli)
                order_times.append(_time.time() - _t0)
                processed_count += 1

                # _process_notification_order() puede hacer cr.commit() internamente
                # (crear partner, validar factura, etc.). Un commit libera TODOS los
                # savepoints de la transaccion, asi que nuestro RELEASE puede fallar
                # con "savepoint does not exist". Importante: una query fallida deja
                # la transaccion PG en estado 'aborted' — el try/except atrapa la
                # excepcion Python pero NO recupera PG. Hay que hacer cr.rollback()
                # explicito para poder seguir ejecutando queries (incluyendo el flush
                # del ORM en el proximo commit). Pasamos log_exceptions=False para
                # no ensuciar el log con un ERROR "bad query: RELEASE SAVEPOINT..."
                # que es esperado cuando el commit interno ya consumio el savepoint.
                try:
                    self.env.cr.execute(
                        'RELEASE SAVEPOINT "%s"' % sp_name,
                        log_exceptions=False,
                    )
                except Exception:
                    # Savepoint consumido por commit interno; limpiar estado aborted.
                    # El trabajo hecho antes del commit interno ya esta persistido.
                    self.env.cr.rollback()

                # Mark older notifications as SUCCESS (processed via latest).
                # Aplicamos DESPUES del cleanup del savepoint para que las escrituras
                # se flusheen en una transaccion sana (no abortada).
                if older_notis:
                    for old_noti in older_notis:
                        old_noti.state = 'SUCCESS'
                        old_noti.processing_errors = 'Processed via latest notification'
                    duplicates_count += len(older_notis)

                # Commit after each order.
                # NOTE: do NOT re-issue RELEASE SAVEPOINT here. The block above
                # (lines starting with `try: cr.execute('RELEASE SAVEPOINT ...')`)
                # already handles the case where the savepoint was consumed by
                # an internal commit (it rolls back to leave the transaction
                # clean). A second RELEASE always fails — either the savepoint
                # was already released by us, or it was already released by the
                # internal commit and we already rolled back. Either way,
                # `RELEASE SAVEPOINT "x"` on a non-existent savepoint raises
                # and leaves the PG transaction in `aborted` state, which makes
                # the next cr.commit() blow up while flushing the older_notis
                # writes ("current transaction is aborted, commands ignored").
                self.env.cr.commit()

            except Exception as e:
                import psycopg2
                try:
                    self.env.cr.execute('ROLLBACK TO SAVEPOINT "%s"' % sp_name)
                except Exception:
                    self.env.cr.rollback()
                if isinstance(e, (psycopg2.errors.SerializationFailure,
                                  psycopg2.errors.LockNotAvailable)):
                    # Otro worker ya está procesando esta notificación — no es un error real
                    _logger.info("CRON_ORDER_NOTIFICATIONS: Skipping order %s (locked by another worker)",
                                resource)
                else:
                    _logger.error("CRON_ORDER_NOTIFICATIONS: Error processing order %s: %s",
                                resource, str(e))
                    try:
                        latest_noti.state = 'FAILED'
                        latest_noti.processing_errors = str(e)
                        self.env.cr.commit()
                    except Exception:
                        self.env.cr.rollback()
                    failed_count += 1

        _logger.info("CRON_ORDER_NOTIFICATIONS: Processed %d orders, failed %d, marked %d duplicates for account %s",
                    processed_count, failed_count, duplicates_count, account.name)

        return {
            'processed': processed_count,
            'failed': failed_count,
            'duplicates': duplicates_count,
            'times': order_times,
        }

    def cron_process_unprocessed_orders(self, meli=None, days=1, limit=10):
        """
        Query and process orders from the last N days that haven't been processed yet.

        This ensures orders that may have been missed by notifications are still imported.
        Algorithm is similar to the Import Orders wizard.
        """
        from datetime import datetime, timedelta, timezone

        account = self
        company = account.company_id or self.env.user.company_id
        config = account.configuration or company

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        if meli.need_login():
            return {}

        # Calculate date range (last N days)
        now_utc = datetime.now(timezone.utc)
        to_dt = now_utc
        from_dt = now_utc - timedelta(days=days)

        from_str = from_dt.strftime('%Y-%m-%dT%H:%M:%S.000-00:00')
        to_str = to_dt.strftime('%Y-%m-%dT%H:%M:%S.000-00:00')

        _logger.info("CRON_UNPROCESSED_ORDERS: Checking orders from %s to %s for account %s",
                    from_str, to_str, account.name)

        # Query orders from MercadoLibre API
        orders_to_process = []
        offset = 0
        ml_total = 0          # total que reporta ML en la ventana (status=paid + date_closed)
        existing_count = 0    # ya tienen registro mercadolibre.orders en Odoo (el cron las saltea)

        while len(orders_to_process) < limit:
            orders_query = (
                "/orders/search?seller=" + meli.seller_id +
                "&sort=date_desc&order.status=paid" +
                "&order.date_closed.from=" + from_str +
                "&order.date_closed.to=" + to_str +
                ("&offset=" + str(offset) if offset else "")
            )

            # Log de la búsqueda EXACTA que se manda a ML (sin token), para ver en
            # odoo.log qué está filtrando el cron: vendedor, estado, ventana date_closed.
            _logger.info("CRON_UNPROCESSED_ORDERS: cuenta %s — GET ML %s  [filtros: seller=%s, order.status=paid, date_closed.from=%s, date_closed.to=%s, offset=%s, límite_objetivo=%s]",
                         account.name, orders_query, meli.seller_id, from_str, to_str, offset or 0, limit)

            try:
                response = meli.get(orders_query, {'access_token': meli.access_token})
                orders_json = response and response.json() or {}
            except Exception as e:
                _logger.error("CRON_UNPROCESSED_ORDERS: API error: %s", str(e))
                break

            if isinstance(orders_json, dict) and "error" in orders_json:
                _logger.error("CRON_UNPROCESSED_ORDERS: API error: %s", orders_json.get("error"))
                break

            paging = orders_json.get("paging") or {}
            total = paging.get("total", 0)
            ml_total = total
            page_limit = paging.get("limit", 50)
            results = orders_json.get("results") or []

            if not results:
                break

            # Check which orders don't exist in Odoo
            for order_json in results:
                order_id = order_json.get("id")
                if not order_id:
                    continue

                # Check if order exists in Odoo
                meli_order = self.env["mercadolibre.orders"].search([
                    ('order_id', '=', str(order_id)),
                    ('connection_account', '=', account.id)
                ], limit=1)

                if not meli_order:
                    orders_to_process.append(order_json)
                    if len(orders_to_process) >= limit:
                        break
                else:
                    existing_count += 1

            # Check if there's more pages
            if (offset + page_limit) < total:
                offset += page_limit
            else:
                break

        if not orders_to_process:
            _logger.info(
                "CRON_UNPROCESSED_ORDERS: cuenta %s — ventana %s..%s (order.status=paid, por date_closed, %dd): "
                "ML reportó total=%d, ya existían en Odoo=%d, nuevas=0. "
                "Lectura: si total=0 NO hay órdenes pagadas/cerradas en esa ventana (un backlog más viejo, "
                "o pagadas sin date_closed, no se capturan acá → import manual). Si ya_existían>0, esas órdenes "
                "YA tienen registro mercadolibre.orders y el cron NO las reimporta aunque les falte el sale.order.",
                account.name, from_str, to_str, days, ml_total, existing_count)
            return {}

        _logger.info("CRON_UNPROCESSED_ORDERS: cuenta %s — ventana %s..%s: ML total=%d, ya existían=%d, NUEVAS a procesar=%d",
                    account.name, from_str, to_str, ml_total, existing_count, len(orders_to_process))

        # Process orders
        import time as _time
        processed_count = 0
        failed_count = 0
        order_times = []

        for order_json in orders_to_process:
            order_id = order_json.get("id")
            try:
                # Import the order (mail_notrack: evita escrituras de chatter/tracking por orden)
                _t0 = _time.time()
                ret = self.env["mercadolibre.orders"].with_context(
                    mail_notrack=True,
                    tracking_disable=True,
                    mail_auto_subscribe_no_notify=True,
                ).orders_import_order(
                    order_id=order_id,
                    meli=meli,
                    config=config
                )
                _elapsed = _time.time() - _t0

                if ret and "error" in ret:
                    _logger.error("CRON_UNPROCESSED_ORDERS: Error importing order %s: %s",
                                order_id, ret["error"])
                    failed_count += 1
                else:
                    order_times.append(_elapsed)
                    processed_count += 1
                    self.env.cr.commit()

            except Exception as e:
                _logger.error("CRON_UNPROCESSED_ORDERS: Exception importing order %s: %s",
                            order_id, str(e))
                failed_count += 1

        _logger.info("CRON_UNPROCESSED_ORDERS: Imported %d, failed %d for account %s",
                    processed_count, failed_count, account.name)

        return {'processed': processed_count, 'failed': failed_count, 'times': order_times}

    def fix_inconsistent_stock_status(self):
        """
        Safety check: Find and fix bindings where meli_stock_status is incorrect.

        This catches any bindings where status implies "synced" but the dates
        say otherwise:
        - Case 1: meli_stock_moves_update > stock_update (stock moved after last sync)
        - Case 2: meli_stock_moves_update is set but stock_update is NULL (never synced)

        Status filter covers four states:
        - 'updated' / 'updated_with_warning' — system thinks the binding is in sync
        - 'revision_unmoved' — was tagged as never-moved but has a moves_update now
        - 'revision' — generic non-error pending state; if dates say "needs sync",
                       prefer 'update' over leaving it in revision indefinitely

        Can be run manually or via cron as a safety net.
        """
        account = self

        # Status values that should be flipped to 'update' when the dates
        # indicate a pending sync. Error states (revision_error, revision_blocked,
        # revision_closed, etc.) and multiwarehouse are intentionally excluded —
        # those need manual intervention.
        repairable_statuses = ('updated', 'updated_with_warning', 'revision_unmoved', 'revision')

        # SQL query to find inconsistent bindings
        # Case 1: Both dates set, but moves > stock_update
        # Case 2: moves is set but stock_update is NULL (never synced to ML)
        self.env.cr.execute("""
            SELECT id, conn_id, meli_stock_moves_update, stock_update, meli_stock_status
            FROM mercadolibre_product
            WHERE connection_account = %s
            AND meli_stock_moves_update IS NOT NULL
            AND (
                (stock_update IS NOT NULL AND meli_stock_moves_update > stock_update)
                OR stock_update IS NULL
            )
            AND meli_stock_status IN %s
        """, (account.id, repairable_statuses))

        inconsistent = self.env.cr.fetchall()

        if not inconsistent:
            _logger.info("FIX_STOCK_STATUS: No inconsistent bindings found for account %s", account.name)
            return {'fixed': 0}

        _logger.info("FIX_STOCK_STATUS: Found %d inconsistent bindings for account %s",
                    len(inconsistent), account.name)

        # Log details for debugging
        for row in inconsistent[:10]:  # Log first 10
            bind_id, conn_id, moves_update, stock_update, status = row
            _logger.info("  - %s: moves=%s, stock=%s, status=%s",
                        conn_id, moves_update, stock_update or 'NULL', status)

        if len(inconsistent) > 10:
            _logger.info("  - ... and %d more", len(inconsistent) - 10)

        # Fix them via SQL
        self.env.cr.execute("""
            UPDATE mercadolibre_product
            SET meli_stock_status = 'update'
            WHERE connection_account = %s
            AND meli_stock_moves_update IS NOT NULL
            AND (
                (stock_update IS NOT NULL AND meli_stock_moves_update > stock_update)
                OR stock_update IS NULL
            )
            AND meli_stock_status IN %s
        """, (account.id, repairable_statuses))

        fixed_count = self.env.cr.rowcount

        # Invalidate cache
        self.env['mercadolibre.product'].invalidate_model(['meli_stock_status'])

        _logger.info("FIX_STOCK_STATUS: Fixed %d bindings for account %s", fixed_count, account.name)

        return {'fixed': fixed_count}

    def _cron_recompute_masters(self):
        """Recalcula is_master sobre toda la maestra de la cuenta (FASE 1 → IMPORT).

        Tras relevar la maestra con record_maestro_review (FETCH), seleccionamos el
        master por SKU/barcode (el de mas variantes) recorriendo los registros y
        llamando is_it_master(). NO hace fetch a ML: usa meli_id_variations_number
        ya stampado desde el rjson del multiget durante la fase FETCH. Commit por
        lotes para no inflar la transaccion.
        """
        account = self
        maestros = self.env["mercadolibre.product.maestro"].search([
            ('connection_account', '=', account.id),
        ])
        total = len(maestros)
        _logger.info("cron_batch_import: recomputando masters sobre %s maestros (cuenta %s)",
                     total, account.name)
        n = 0
        for m in maestros:
            try:
                m.is_it_master()
            except Exception as e:
                _logger.warning("cron_batch_import recompute master meli_id=%s: %s",
                                m.meli_id, str(e))
            n += 1
            if n % 200 == 0:
                MeliCommit(self)
        MeliCommit(self)
        n_masters = self.env["mercadolibre.product.maestro"].search_count([
            ('connection_account', '=', account.id),
            ('is_master', '=', True),
        ])
        _logger.info("cron_batch_import: recompute de masters terminado — %s masters de %s maestros",
                     n_masters, total)
        return n_masters

    @staticmethod
    def _meli_is_serialization_error(exc):
        """True si `exc` es un serialization failure / deadlock de Postgres.

        SQLSTATE 40001 ('could not serialize access due to concurrent update') o
        40P01 ('deadlock detected'), o el 'current transaction is aborted' que deja
        una 40001 previa ya swallowed. Bajo transaction_isolation='repeatable read'
        (default Odoo) estos errores NO se recuperan reintentando en la MISMA
        transaccion: el snapshot esta congelado para toda la tx, asi que el reintento
        vuelve a chocar siempre. El unico recovery valido es un snapshot FRESCO ->
        por eso se deja PROPAGAR (ver _cron_import_write_retry).
        """
        pgcode = getattr(exc, 'pgcode', None)
        if pgcode in ('40001', '40P01'):
            return True
        msg = (str(exc) or '').lower()
        return (
            'could not serialize' in msg or
            'concurrent update' in msg or
            'deadlock detected' in msg or
            'transaction is aborted' in msg
        )

    def _cron_import_write_retry(self, vals, retries=2):
        """Write de progreso del batch import — recovery de 40001 por PROPAGACION.

        REGRESION QUE ARREGLA (RPM Motos #532): el cron de import se solapa con los
        otros ~9 crones meli que escriben la MISMA fila de mercadolibre.account (el
        JSON cache de ~640KB + el offset), disparando serialization failures 40001.
        La version previa envolvia el write en `with cr.savepoint()` + reintentos EN
        LA MISMA transaccion; pero bajo transaction_isolation='repeatable read' el
        snapshot esta congelado para toda la tx -> el retry vuelve a chocar SIEMPRE ->
        "se pierde este avance" en muchas corridas -> el offset/cache no avanzan -> el
        cron re-procesa el mismo lote = import "a cuentagotas, nunca completa".

        Por que NO se usa un cursor/tx nueva (registry.cursor()+commit) para el offset:
        MeliCommit()=env.flush_all() (NO cr.commit()) en las 4 versiones, asi que TODO
        el batch (productos creados + este write de progreso) vive en UNA sola
        transaccion que el framework de ir.cron commitea atomicamente al final
        (ir_cron._callback -> cr.commit). Commitear el offset en un cursor aparte lo
        DESACOPLARIA de los productos: si la tx externa revierte, el offset quedaria
        adelantado -> items salteados para siempre (mismo sintoma, peor). Ademas un
        cursor nuevo que UPDATEa la fila account arriesga auto-deadlock de misma sesion
        si la tx externa ya la tuviera lockeada.

        Recovery correcto: DEJAR PROPAGAR el 40001. El framework hace rollback del
        batch entero (atomico, nada committeado a medias) y rehace el job en el proximo
        tick con un cursor/snapshot FRESCO, que es lo unico que resuelve un 40001 bajo
        repeatable read. El savepoint se conserva SOLO para que un error no-serializacion
        (impensado con estos vals escalares) no aborte la tx y mantenga el comportamiento
        previo (log + return False). El parametro `retries` queda por compat de firma.
        """
        try:
            with self.env.cr.savepoint():
                self.write(vals)
            return True
        except Exception as e:
            if self._meli_is_serialization_error(e):
                _logger.warning(
                    "cron_batch_import: serialization conflict (40001) en write de "
                    "progreso -> se PROPAGA para que el cron rehaga el job con snapshot "
                    "fresco (el batch es atomico, no se pierde avance): %s", str(e)[:200]
                )
                raise
            # Error NO-serializacion: comportamiento previo (no romper la corrida).
            _logger.error(
                "cron_batch_import: write de progreso fallo (no-serializacion): %s",
                str(e)[:300]
            )
            return False

    def cron_batch_import_products(self):
        """
        Batch import de productos ML via cron, MAESTRO-AWARE en dos fases.

        Modo explicito en config.mercadolibre_cron_get_new_products_mode:
          - 'fetch'  : recorre TODAS las publicaciones (fetch_list_meli_ids) y por
                       cada una llama record_maestro_review (multiget rapido) para
                       poblar la maestra. NO crea productos. Al cubrir toda la lista
                       recalcula los masters (is_it_master via calculate_variations),
                       resetea el offset y deja listo para IMPORT (no auto-crea).
          - 'import' : la lista a procesar = solo masters (fetch_list_meli_ids_maestro)
                       y los crea via _process_meli_item_direct(force_dont_create=False).

        Cada ejecucion procesa N publicaciones (batch_size desde config).
        Mantiene offset persistente en self.cron_import_offset.
        Al completar todas las publicaciones, resetea el offset.
        """
        import time as _time
        import json

        for account in self:
            config = account.configuration or account.company_id
            if not config.mercadolibre_cron_get_new_products:
                continue

            batch_size = config.mercadolibre_cron_get_new_products_batch_size or 100
            post_state = config.mercadolibre_cron_get_new_products_post_state or 'active'
            import_mode = config.mercadolibre_cron_get_new_products_mode or 'fetch'

            company = account.company_id or self.env.user.company_id
            meli = self.env['meli.util'].get_new_instance(company, account)
            if meli.needlogin_state:
                _logger.warning("cron_batch_import: account %s needs login, skipping", account.name)
                continue

            # Crear registro de ejecucion cron (sudo: modelo manager-only, cron como __system__)
            CronExec = self.env['mercadolibre.cron.execution'].sudo()
            exec_rec = CronExec.create({
                'connection_account': account.id,
                'cron_type': 'products_get',
                'state': 'running',
            })
            MeliCommit(self)

            t_start = _time.time()
            items_processed = 0
            items_success = 0
            items_error = 0
            items_skipped = 0
            log_lines = []

            try:
                # --- PASO 1: Obtener o usar cache de product_lines ---
                # El cache guarda el modo (_mode) con el que se construyo: si el
                # operador alterna FETCH<->IMPORT, descartamos el cache y arrancamos
                # un ciclo nuevo con la lista correcta (full vs solo masters).
                product_lines = []
                cached_json = account.cron_import_product_lines_json
                cached_mode = None

                if cached_json and account.cron_import_offset > 0:
                    try:
                        _cached = json.loads(cached_json)
                        if isinstance(_cached, dict):
                            cached_mode = _cached.get('_mode')
                            product_lines = _cached.get('lines', [])
                        else:
                            # cache legacy (lista pelada) -> tratar como modo 'import'
                            # historico; si no coincide con el modo actual se rehace.
                            cached_mode = 'import'
                            product_lines = _cached
                    except Exception:
                        product_lines = []

                if cached_mode and cached_mode != import_mode:
                    _logger.info(
                        "cron_batch_import: %s - cambio de modo %s->%s, reiniciando ciclo",
                        account.name, cached_mode, import_mode)
                    product_lines = []

                # Si no hay cache o offset es 0 (nuevo ciclo), consultar ML
                if not product_lines:
                    _logger.info("cron_batch_import: %s - consultando ML (nuevo ciclo, modo=%s)",
                                 account.name, import_mode)

                    if import_mode == 'import':
                        # FASE 2: la lista a procesar = SOLO masters de la maestra.
                        # is_master=True elegido por is_it_master (mas variantes por SKU).
                        # NOTA: fetch_list_meli_ids_maestro() devuelve TAMBIEN no-masters
                        # (concatena los 4 grupos), por eso filtramos is_master=True aca
                        # para no crear duplicados desde las publicaciones clon.
                        master_recs = self.env["mercadolibre.product.maestro"].search([
                            ('connection_account', '=', account.id),
                            ('is_master', '=', True),
                        ])
                        master_ids = [m for m in master_recs.mapped('meli_id') if m]
                        # de-dup preservando orden (varias variantes comparten meli_id)
                        _seen = set()
                        master_ids = [m for m in master_ids if not (m in _seen or _seen.add(m))]
                        odoo_meli_ids = set(account.list_meli_ids() or [])
                        for mli in master_ids:
                            is_synced = mli in odoo_meli_ids
                            product_lines.append({
                                'meli_id': mli,
                                'import_status': 'synced' if is_synced else 'pending',
                                'meli_status': post_state,
                            })
                    else:
                        # FASE 1 (fetch): recorrer TODAS las publicaciones para poblar
                        # la maestra. NO filtramos por "ya sincronizado": record_maestro_review
                        # es idempotente (search-before-create) y necesitamos relevar todo.
                        params = {}
                        if post_state and post_state != 'all':
                            params['status'] = post_state
                        fetched_ids = account.fetch_list_meli_ids(params=params)
                        for mli in (fetched_ids or []):
                            product_lines.append({
                                'meli_id': mli,
                                'import_status': 'pending',
                                'meli_status': params.get('status', 'active'),
                            })

                    # Guardar cache (con marca de modo) y total
                    account._cron_import_write_retry({
                        'cron_import_product_lines_json': json.dumps(
                            {'_mode': import_mode, 'lines': product_lines}),
                        'cron_import_total': len([pl for pl in product_lines if pl.get('import_status') != 'synced']),
                        'cron_import_offset': 0,
                    })
                    MeliCommit(self)

                # --- PASO 2: Filtrar solo pendientes ---
                pending = [pl for pl in product_lines if pl.get('import_status') not in ('synced', 'imported', 'error', 'duplicate', 'skipped')]

                if not pending:
                    # Ciclo completo.
                    _logger.info("cron_batch_import: %s - ciclo completo (modo=%s), no quedan pendientes",
                                 account.name, import_mode)

                    # En FASE 1, al cubrir toda la lista recalculamos los masters
                    # para dejar la maestra lista para IMPORT (no auto-creamos: el
                    # operador cambia el modo a 'import' a proposito).
                    if import_mode == 'fetch':
                        try:
                            account._cron_recompute_masters()
                        except Exception as e_rm:
                            _logger.error("cron_batch_import: error recalculando masters: %s", str(e_rm))

                    account._cron_import_write_retry({
                        'cron_import_offset': 0,
                        'cron_import_total': 0,
                        'cron_import_product_lines_json': '',
                        'cron_import_last_cycle': fields.Datetime.now(),
                    })
                    _summary = ('Ciclo FETCH completo: maestra relevada y masters recalculados. '
                                'Cambie el modo a IMPORT para crear los productos.'
                                if import_mode == 'fetch'
                                else 'Ciclo IMPORT completo, no quedan masters pendientes.')
                    exec_rec.write({
                        'state': 'success',
                        'date_end': fields.Datetime.now(),
                        'items_processed': 0,
                        'log_summary': _summary,
                    })
                    MeliCommit(self)
                    continue

                _logger.info("cron_batch_import: %s - procesando lote de %s (pendientes=%s, offset=%s)",
                             account.name, batch_size, len(pending), account.cron_import_offset)

                # --- PASO 3: Procesar batch ---
                # MULTIGET (TASK-001 ext): Tres optimizaciones simultáneas:
                # A) Multiget paralelo: 5 threads × 20 items = 100 items por ciclo de API
                # B) Pre-carga en RAM: bindings, SKUs y barcodes de Odoo en dicts locales
                # C) Commit cada 50 items en lugar de cada 1
                # Resultado: de ~3-5 días → ~2-4 horas para 200k publicaciones
                # Ver .roots/refatodo/debug/fixes-log.md

                # Contexto base para product_meli_get_products
                custom_context = {
                    "post_state": post_state,
                    "force_meli_pub": config.mercadolibre_cron_get_new_products_force_meli_pub,
                    "force_import_images": config.mercadolibre_cron_get_new_products_force_import_images,
                    "force_dont_create": config.mercadolibre_cron_get_new_products_force_dont_create,
                    "force_create_variants": False,
                    "force_meli_website_published": False,
                    "force_meli_website_category_create_and_assign": False,
                    "batch_processing_unit": 1,
                    "batch_processing_unit_offset": 0,
                    "batch_actives_to_sync": post_state == 'active',
                    "batch_paused_to_sync": post_state == 'paused',
                    "batch_left_to_sync": False,
                }

                batch_items = pending[:batch_size]
                MULTIGET_SIZE = 20
                PARALLEL_THREADS = 5
                COMMIT_EVERY = 50

                # --- PRE-CARGA EN RAM: bindings existentes de esta cuenta ---
                _logger.info("REFATODO cron_batch_import: pre-cargando bindings en RAM...")
                t_preload = _time.time()

                # Cargar todos los conn_id ya vinculados a esta cuenta en un set
                self.env.cr.execute("""
                    SELECT conn_id FROM mercadolibre_product
                    WHERE connection_account = %s AND conn_id IS NOT NULL AND conn_id != ''
                    UNION
                    SELECT conn_id FROM mercadolibre_product_template
                    WHERE connection_account = %s AND conn_id IS NOT NULL AND conn_id != ''
                """, (account.id, account.id))
                existing_bindings = set(r[0] for r in self.env.cr.fetchall())

                # Cargar SKUs de Odoo en RAM: {default_code_lower: product_id}
                self.env.cr.execute("""
                    SELECT default_code, id FROM product_product
                    WHERE default_code IS NOT NULL AND default_code != ''
                    AND active = TRUE
                """)
                sku_to_product = {r[0].lower(): r[1] for r in self.env.cr.fetchall()}

                # Cargar barcodes de Odoo en RAM: {barcode_lower: product_id}
                self.env.cr.execute("""
                    SELECT barcode, id FROM product_product
                    WHERE barcode IS NOT NULL AND barcode != ''
                    AND active = TRUE
                """)
                barcode_to_product = {r[0].lower(): r[1] for r in self.env.cr.fetchall()}

                # Cargar el espejo maestro de esta cuenta en RAM:
                #   {(meli_id, meli_id_variation): {id, sku, barcode, nvar}}
                # La fase FETCH (record_maestro_review) lo consulta para SALTEAR los
                # items ya relevados sin cambios sin pegarle a la DB por variación
                # (antes: search+write ORM por variación con =ilike -> seq-scan, ~0.65s/item).
                maestro_ram = {}
                self.env.cr.execute("""
                    SELECT id, meli_id, COALESCE(meli_id_variation, ''),
                           sku, barcode, meli_id_variations_number
                    FROM mercadolibre_product_maestro
                    WHERE connection_account = %s
                """, (account.id,))
                for _mr in self.env.cr.fetchall():
                    maestro_ram[(str(_mr[1]), str(_mr[2]))] = {
                        'id': _mr[0], 'sku': _mr[3], 'barcode': _mr[4], 'nvar': _mr[5],
                    }

                _logger.info(
                    "REFATODO cron_batch_import: pre-carga completada en %.1fs — "
                    "%d bindings, %d SKUs, %d barcodes, %d maestros en RAM",
                    _time.time() - t_preload,
                    len(existing_bindings), len(sku_to_product), len(barcode_to_product),
                    len(maestro_ram)
                )

                # --- MULTIGET PARALELO: fetch 100 items por ronda (5 threads × 20) ---
                import concurrent.futures as _futures

                def _fetch_multiget_batch(ids_batch):
                    """Descarga un lote de 20 items via Multiget. Seguro para threading."""
                    try:
                        return account.fetch_meli_products_multiget(ids=ids_batch, meli=meli)
                    except Exception as e:
                        _logger.warning("REFATODO multiget batch error: %s", str(e))
                        return {}

                # Pre-cargar cache multiget para el batch completo en paralelo
                all_meli_ids = [item.get('meli_id') for item in batch_items if item.get('meli_id')]
                multiget_cache = {}

                # Dividir en sub-lotes de 20 y ejecutar PARALLEL_THREADS a la vez
                sublotes = [all_meli_ids[i:i+MULTIGET_SIZE]
                            for i in range(0, len(all_meli_ids), MULTIGET_SIZE)]

                _logger.info(
                    "REFATODO cron_batch_import: %d items → %d sublotes × %d paralelos",
                    len(all_meli_ids), len(sublotes), PARALLEL_THREADS
                )

                with _futures.ThreadPoolExecutor(max_workers=PARALLEL_THREADS) as executor:
                    futures = {executor.submit(_fetch_multiget_batch, sl): sl for sl in sublotes}
                    for future in _futures.as_completed(futures):
                        try:
                            result = future.result(timeout=30)
                            multiget_cache.update(result)
                        except Exception as e:
                            _logger.warning("REFATODO parallel future error: %s", str(e))

                _logger.info(
                    "REFATODO cron_batch_import: multiget completado — %d/%d items en cache",
                    len(multiget_cache), len(all_meli_ids)
                )

                # --- LOOP PRINCIPAL: procesar con datos de RAM ---
                items_since_commit = 0
                DIRECT_BATCH = 50  # commit cada N items nuevos

                for item in batch_items:
                    meli_id = item.get('meli_id')
                    if not meli_id:
                        continue

                    item_start = _time.time()
                    try:
                        rjson = multiget_cache.get(meli_id)

                        if import_mode == 'fetch':
                            # --- FASE 1: poblar maestra, NO crear productos ---
                            # record_maestro_review es idempotente (search-before-create);
                            # corre para TODAS las publicaciones (no salteamos por binding
                            # existente: queremos relevar la maestra completa).
                            _t_before = _time.time()
                            if not rjson:
                                # multiget no trajo el item (error/no disponible): skip
                                item['import_status'] = 'skipped'
                                items_skipped += 1
                            else:
                                # nvar (cantidad de variaciones) desde el rjson del multiget
                                # (sin red). Se estampa DENTRO de record_maestro_review (fold
                                # del search+write que antes hacía el caller por item) para que
                                # is_it_master pueda elegir master en el recompute final sin fetch.
                                _nvar = len(rjson.get("variations") or [])
                                account.record_maestro_review(
                                    meli_id=meli_id, meli=meli, rjson=rjson,
                                    maestro_ram=maestro_ram, variations_number=_nvar)
                                item['import_status'] = 'imported'  # 'relevado' en fase 1
                                items_success += 1
                            _t1 = _time.time()
                            if items_processed <= 10 or items_processed % 50 == 0:
                                _logger.debug("REFATODO PROFILING(fetch) item %d (%s): maestro=%.3fs",
                                              items_processed, meli_id, _t1 - _t_before)
                        else:
                            # --- FASE 2: crear producto desde master ---
                            # Si el binding ya existe en RAM, marcar synced sin queries.
                            if meli_id in existing_bindings:
                                item['import_status'] = 'synced'
                                items_success += 1
                                items_processed += 1
                                items_since_commit += 1
                                log_lines.append("%s: synced_ram (0.0s)" % meli_id)
                                if items_since_commit >= COMMIT_EVERY:
                                    MeliCommit(self)
                                    items_since_commit = 0
                                continue

                            # REFATODO: usar _process_meli_item_direct para evitar
                            # el commit automático de product_meli_get_products por item.
                            # force_dont_create=False: estos SON masters → crear el producto.
                            _t_before = _time.time()
                            status = account._process_meli_item_direct(
                                meli_id=meli_id,
                                rjson=rjson,
                                meli=meli,
                                sku_to_product=sku_to_product,
                                barcode_to_product=barcode_to_product,
                                force_dont_create=False,
                            )
                            _t1 = _time.time()
                            if items_processed <= 10 or items_processed % 50 == 0:
                                _logger.info("REFATODO PROFILING(import) item %d (%s): direct=%.3fs total=%.3fs",
                                             items_processed, meli_id,
                                             _t1 - _t_before,
                                             _t1 - item_start)

                            if status == 'imported':
                                item['import_status'] = 'imported'
                                items_success += 1
                                existing_bindings.add(meli_id)
                            elif status == 'skipped':
                                # Skip esperado (no matchea y no se crea): NO es error.
                                item['import_status'] = 'skipped'
                                items_skipped += 1
                            else:
                                item['import_status'] = 'error'
                                items_error += 1

                        # Commit cada DIRECT_BATCH items nuevos
                        items_since_commit += 1
                        if items_since_commit >= DIRECT_BATCH:
                            MeliCommit(self)
                            items_since_commit = 0

                    except Exception as E:
                        if self._meli_is_serialization_error(E):
                            # 40001/deadlock a nivel item: NO tragar (abortaria la tx y
                            # el resto del lote cascadearia en InFailedSqlTransaction).
                            # Propagar -> rollback atomico + retry del cron con snapshot fresco.
                            raise
                        _logger.error("cron_batch_import: error %s: %s", meli_id, str(E))
                        item['import_status'] = 'error'
                        items_error += 1

                    items_processed += 1
                    elapsed = _time.time() - item_start
                    log_lines.append("%s: %s (%.1fs)" % (meli_id, item['import_status'], elapsed))

                # Commit final del lote
                if items_since_commit > 0:
                    MeliCommit(self)

                # --- PASO 4: Guardar progreso ---
                # Write de progreso con savepoint+retry: un serialization failure
                # (40001) por solape con otros crones meli no debe perder el avance.
                account._cron_import_write_retry({
                    'cron_import_product_lines_json': json.dumps(
                        {'_mode': import_mode, 'lines': product_lines}),
                    'cron_import_offset': account.cron_import_offset + items_processed,
                })

                remaining_pending = len([pl for pl in product_lines if pl.get('import_status') not in ('synced', 'imported', 'error', 'duplicate', 'skipped')])
                if remaining_pending == 0:
                    # Fin de ciclo. En FETCH, recalcular masters antes de resetear.
                    if import_mode == 'fetch':
                        try:
                            account._cron_recompute_masters()
                        except Exception as e_rm:
                            _logger.error("cron_batch_import: error recalculando masters: %s", str(e_rm))
                    account._cron_import_write_retry({
                        'cron_import_offset': 0,
                        'cron_import_total': 0,
                        'cron_import_product_lines_json': '',
                        'cron_import_last_cycle': fields.Datetime.now(),
                    })

                total_elapsed = _time.time() - t_start
                # 'skipped' NO marca error: estado = success salvo errores reales.
                state = 'success' if items_error == 0 else ('warning' if (items_success > 0 or items_skipped > 0) else 'error')

                exec_rec.write({
                    'state': state,
                    'date_end': fields.Datetime.now(),
                    'items_processed': items_processed,
                    'items_success': items_success,
                    'items_error': items_error,
                    'items_skipped': items_skipped,
                    'log_summary': "Batch[%s]: %s/%s ok, %s skip, %s err (%.1fs)\nPendientes: %s\n%s" % (
                        import_mode, items_success, items_processed, items_skipped, items_error, total_elapsed,
                        remaining_pending,
                        "\n".join(log_lines[-20:])
                    ),
                })
                MeliCommit(self)

                _logger.info("cron_batch_import: %s [%s] - lote completado: %s/%s ok, %s skip, %s err, pendientes=%s (%.1fs)",
                             account.name, import_mode, items_success, items_processed, items_skipped, items_error, remaining_pending, total_elapsed)

            except Exception as E:
                if self._meli_is_serialization_error(E):
                    # 40001/deadlock: PROPAGAR (rollback atomico del batch + retry del
                    # cron con snapshot fresco). NO escribimos exec_rec: la tx esta
                    # abortada y el write fallaria; ademas el registro de esta corrida
                    # se revierte junto con el batch. Ver _cron_import_write_retry.
                    raise
                _logger.error("cron_batch_import: %s - error fatal: %s", account.name, str(E))
                exec_rec.write({
                    'state': 'error',
                    'date_end': fields.Datetime.now(),
                    'items_processed': items_processed,
                    'items_success': items_success,
                    'items_error': items_error,
                    'items_skipped': items_skipped,
                    'error_message': str(E)[:500],
                })
                MeliCommit(self)

    def cron_meli_process( self ):

        #_logger.info( 'account cron_meli_process() STARTED ' + str( datetime.now() ) )

        for connacc in self:

            company = connacc.company_id or self.env.user.company_id
            config = connacc.configuration or company

            apistate = self.env['meli.util'].get_new_instance( company, connacc)
            if apistate.needlogin_state:
                return True

            execution = connacc._start_cron_execution('process')
            connacc.env.cr.commit()
            try:
                if (config.mercadolibre_cron_get_update_products):
                    #_logger.info("config.mercadolibre_cron_get_update_products")
                    connacc.meli_update_local_products()

                if (config.mercadolibre_cron_get_new_products):
                    #_logger.info("config.mercadolibre_cron_get_new_products cron_batch_import_products")
                    connacc.cron_batch_import_products()

                if (config.mercadolibre_cron_post_update_products or config.mercadolibre_cron_post_new_products):
                    #_logger.info("config.mercadolibre_cron_post_update_products")
                    connacc.meli_update_remote_products(post_new=connacc.configuration.mercadolibre_cron_post_new_products)

                if (config.mercadolibre_cron_post_update_stock):
                    #_logger.info("config.mercadolibre_cron_post_update_stock")
                    # Safety check: fix any inconsistent stock statuses before syncing.
                    # Wrapped in savepoint: a SerializationFailure on concurrent UPDATE
                    # must not abort the outer transaction (which would break _end_cron_execution).
                    try:
                        with self.env.cr.savepoint():
                            connacc.fix_inconsistent_stock_status()
                    except Exception as e_fix:
                        _logger.warning("fix_inconsistent_stock_status skipped (concurrent update): %s", e_fix)
                    connacc.meli_update_remote_stock(meli=apistate)

                if (config.mercadolibre_cron_post_update_price):
                    #_logger.info("config.mercadolibre_cron_post_update_price")
                    connacc.meli_update_remote_price(meli=apistate)

                connacc._end_cron_execution(execution, state='success')
            except Exception as e:
                connacc._end_cron_execution(execution, state='error', error_message=str(e))
                raise

        #_logger.info( 'account cron_meli_process() ENDED ' + str( datetime.now() ) )
    #TODO: {
    #  "id": "GTIN",
    #  "name": "Código universal de producto",
    #  "value_id": null,
    #  "value_name": "758475398510",
    #  "value_struct": null,
    #  "values": []
    #}
    #{
    #  "id": "SELLER_SKU",
    #  "name": "SKU",
    #  "value_id": null,
    #  "value_name": "ELEF60_ROSA",
    #  "value_struct": null,
    #  "values": []
    #}
    def fetch_meli_product( self, meli_id, meli=None ):

        rjson = {}
        account = self
        seller_sku = None

        #_logger.info("Fetch Meli Product: "+str(meli_id)+" account: "+str(account))

        if not meli:
            meli = self.env['meli.util'].get_new_instance( account.company_id, account )

        if not meli_id or not meli:
            return None

        #search full item data from ML
        #import pdb;pdb.set_trace()
        response = meli.get("/items/"+meli_id, {'access_token':meli.access_token, 'include_attributes': 'all' })
        rjson = response.json()

        #single item SKU
        if rjson and "attributes" in rjson:
            for att in rjson['attributes']:
                if ("id" in att and att["id"] == "SELLER_SKU"):
                    seller_sku = att["value_name"]
                    rjson['seller_sku'] = seller_sku
                if ("id" in att and att["id"] == "GTIN"):
                    rjson["barcode"] =  att["value_name"]

        if (not seller_sku and 'seller_custom_field' in rjson and rjson['seller_custom_field'] and len(rjson['seller_custom_field'])):
            seller_sku = rjson['seller_custom_field']
            rjson['seller_sku'] = seller_sku

        #we have description
        #if rjson and 'descriptions' in rjson and rjson['descriptions']:
        if rjson and 'descriptions' in rjson and not rjson['descriptions']:
            dresponse = meli.get("/items/"+str(meli_id)+"/description", {'access_token':meli.access_token })
            djson = dresponse.json()
            des = ""
            desplain = ""
            if 'text' in djson:
               des = djson['text']
            if 'plain_text' in djson:
               desplain = djson['plain_text']
            if (len(des)>0):
                desplain = des
            rjson["description"] = desplain

        #we have variants
        if "variations" in rjson and len(rjson["variations"]):
            vindex = -1
            rjson['seller_skus'] = '['
            rjson['barcodes'] = '['
            rjson['variation_ids'] = '['
            comai = ''
            comas = ''
            comab = ''
            for var in rjson['variations']:
                vindex = vindex+1
                vjson = rjson['variations'][vindex]
                meli_id_variation = ("id" in var and var["id"])
                #_logger.info(meli_id_variation)
                if meli_id_variation:
                    if not ("attributes" in vjson):
                        varget = "/items/"+str(meli_id)+"/variations/"+str(meli_id_variation)
                        #_logger.info("https://api.mercadolibre.com"+varget+"?access_token="+str(meli.access_token))
                        resvar = meli.get( varget, { 'access_token': meli.access_token } )
                        if ( "error" in resvar.json() ):
                            _logger.error(resvar.json())
                            #continue;
                        else:
                            vjson = resvar.json()
                            rjson['variations'][vindex] = vjson

                    if "attributes" in vjson:
                        for att in vjson["attributes"]:
                            if ("id" in att and att["id"] == "SELLER_SKU"):
                                rjson['variations'][vindex]["seller_sku"] = att["value_name"]
                                rjson['seller_skus']+= comas+str(att["value_name"])
                                comas = ','
                                if (len(rjson["variations"])==1):
                                    rjson['seller_sku'] = att["value_name"]


                            if ("id" in att and att["id"] == "GTIN"):
                                rjson['variations'][vindex]["barcode"] = att["value_name"]
                                rjson['barcodes']+= comab+str(att["value_name"])
                                comab = ','

                    rjson['variation_ids']+= comai+str(meli_id_variation)
                    comai = ','

            rjson['seller_skus']+= ']'
            rjson['barcodes']+= ']'
            rjson['variation_ids']+= ']'

        #_logger.info("Fetch Meli Product, rjson: " +str(rjson))

        return rjson

    def fetch_meli_sku(self, meli_id=None, meli_id_variation=None, meli=None, rjson=None):
        """
        Obtiene el/los SKU(s) de una publicación de MercadoLibre.

        IMPORTANTE: Esta función depende de que fetch_meli_product() ya haya procesado
        las variaciones y extraído el seller_sku del array 'attributes' de cada variación.
        fetch_meli_product() hace esto en las líneas donde busca SELLER_SKU en attributes
        y lo asigna a rjson['variations'][i]['seller_sku'].

        Parámetros:
            meli_id (str): ID de la publicación ML (ej: "MLA2034726558")
            meli_id_variation (str|int): ID de variación específica (opcional).
                Si se pasa, retorna solo el SKU de esa variación.
                Si no se pasa, retorna todos los SKUs.
            meli (object): Instancia de meli.util ya inicializada (opcional).
                Si no se pasa, se crea una nueva.
            rjson (dict): Datos del producto ya obtenidos de fetch_meli_product (opcional).
                Pasar esto evita una llamada adicional a la API.

        Retorna:
            - None: si no hay meli_id o hubo error
            - str: SKU único si es producto simple o si se pidió una variación específica
            - list[str]: Lista de SKUs si tiene variaciones y no se pidió una específica

        Prioridad de búsqueda del SKU:
            1. seller_sku (extraído de attributes por fetch_meli_product)
            2. inventory_id (campo legacy de ML)
            3. seller_custom_field (campo personalizado del vendedor)

        Estructura esperada del rjson (después de fetch_meli_product):
            - Producto simple: rjson['seller_sku'] = "SKU123"
            - Con variaciones: rjson['variations'][i]['seller_sku'] = "SKU-VAR-i"

        El SKU en la API de ML viene en variations[].attributes[] donde id="SELLER_SKU":
            {"id": "SELLER_SKU", "value_name": "MI-SKU-001"}
        """
        account = self
        seller_sku = None

        if not meli:
            meli = self.env['meli.util'].get_new_instance(account.company_id, account)

        if not meli_id or not meli:
            return None

        # Obtener datos del producto (fetch_meli_product ya procesa variaciones)
        rjson = rjson or account.fetch_meli_product(meli_id=meli_id, meli=meli)
        if not rjson:
            return None

        rjson_has_variations = rjson and "variations" in rjson and len(rjson["variations"])

        # Helper para extraer SKU de un dict (variación o producto principal)
        def _extract_sku(data):
            """Extrae SKU de un dict, buscando en orden de prioridad."""
            if not data:
                return None
            # 1. seller_sku (ya procesado por fetch_meli_product)
            if data.get('seller_sku'):
                return data['seller_sku']
            # 2. Buscar en attributes array (fallback si fetch_meli_product no lo procesó)
            if 'attributes' in data:
                for att in data['attributes']:
                    if att.get('id') == 'SELLER_SKU' and att.get('value_name'):
                        return att['value_name']
            # 3. inventory_id (campo legacy)
            if data.get('inventory_id'):
                return data['inventory_id']
            # 4. seller_custom_field
            if data.get('seller_custom_field'):
                return data['seller_custom_field']
            return None

        # Producto simple (sin variaciones)
        if not rjson_has_variations:
            seller_sku = _extract_sku(rjson)
            return seller_sku

        # Producto con variaciones
        if meli_id_variation:
            # Buscar SKU de una variación específica
            for var in rjson['variations']:
                if str(var.get("id")) == str(meli_id_variation):
                    seller_sku = _extract_sku(var)
                    break
        else:
            # Retornar lista de todos los SKUs
            seller_sku = []
            for var in rjson['variations']:
                var_sku = _extract_sku(var)
                if var_sku:
                    seller_sku.append(var_sku)

        return seller_sku

    def fetch_meli_barcode(self, meli_id=None, meli_id_variation=None, meli=None, rjson=None):
        """
        Obtiene el/los código(s) de barra de una publicación de MercadoLibre.

        IMPORTANTE: Esta función depende de que fetch_meli_product() ya haya procesado
        las variaciones y extraído el barcode del array 'attributes' de cada variación.
        fetch_meli_product() hace esto buscando GTIN en attributes y asignándolo a
        rjson['variations'][i]['barcode'].

        Parámetros:
            meli_id (str): ID de la publicación ML (ej: "MLA2034726558")
            meli_id_variation (str|int): ID de variación específica (opcional).
                Si se pasa, retorna solo el barcode de esa variación.
                Si no se pasa, retorna todos los barcodes.
            meli (object): Instancia de meli.util ya inicializada (opcional).
            rjson (dict): Datos del producto ya obtenidos de fetch_meli_product (opcional).

        Retorna:
            - None: si no hay meli_id o hubo error
            - str: Barcode único si es producto simple o si se pidió una variación específica
            - list[str]: Lista de barcodes si tiene variaciones y no se pidió una específica

        El barcode en la API de ML viene en variations[].attributes[] donde id="GTIN":
            {"id": "GTIN", "value_name": "7790001234567"}
        """
        account = self
        barcode = None

        if not meli:
            meli = self.env['meli.util'].get_new_instance(account.company_id, account)

        if not meli_id or not meli:
            return None

        # Obtener datos del producto (fetch_meli_product ya procesa variaciones)
        rjson = rjson or account.fetch_meli_product(meli_id=meli_id, meli=meli)
        if not rjson:
            return None

        rjson_has_variations = rjson and "variations" in rjson and len(rjson["variations"])

        # Helper para extraer barcode de un dict (variación o producto principal)
        def _extract_barcode(data):
            """Extrae barcode de un dict, buscando en orden de prioridad."""
            if not data:
                return None
            # 1. barcode (ya procesado por fetch_meli_product)
            if data.get('barcode'):
                return data['barcode']
            # 2. Buscar en attributes array (fallback si fetch_meli_product no lo procesó)
            if 'attributes' in data:
                for att in data['attributes']:
                    if att.get('id') == 'GTIN' and att.get('value_name'):
                        return att['value_name']
            return None

        # Producto simple (sin variaciones)
        if not rjson_has_variations:
            barcode = _extract_barcode(rjson)
            return barcode

        # Producto con variaciones
        if meli_id_variation:
            # Buscar barcode de una variación específica
            for var in rjson['variations']:
                if str(var.get("id")) == str(meli_id_variation):
                    barcode = _extract_barcode(var)
                    break
        else:
            # Retornar lista de todos los barcodes
            barcode = []
            for var in rjson['variations']:
                var_barcode = _extract_barcode(var)
                if var_barcode:
                    barcode.append(var_barcode)

        return barcode

    def set_meli_sku( self, seller_sku=None ):
        if (seller_sku):
            posting_id = self.env['product.product'].search([('default_code','=ilike',seller_sku)])
            if (not posting_id or len(posting_id)==0):
                posting_id = self.env['product.template'].search([('default_code','=ilike',seller_sku)])
                #_logger.info("Founded template with default code, dont know how to handle it.")
            else:
                posting_id.meli_id = item_id

        #search variations in ml rjson item, and updates odoo product meli_id_variation if founded default_code
        #if ('variations' in rjson3):
        #    for var in rjson3['variations']:
        #        if ('seller_custom_field' in var and var['seller_custom_field'] and len(var['seller_custom_field'])):
        #            posting_id = self.env['product.product'].search([('default_code','=ilike',var['seller_custom_field'])])
        #            if (posting_id):
        #                posting_id.meli_id = item_id
        #                if (len(posting_id.product_tmpl_id.product_variant_ids)>1):
        #                    posting_id.meli_id_variation = var['id']

    def search_meli_product( self, meli_id = None, meli_id_variation = None, seller_sku=None, barcode=None, meli=None, rjson=None,
                              _sku_to_product=None, _barcode_to_product=None, _existing_bindings=None ):
        # MULTIGET: Parámetros opcionales de RAM pre-cargados por el cron.
        # Cuando están presentes eliminan las queries a BD por item.
        # _sku_to_product: dict {default_code_lower: product_id}
        # _barcode_to_product: dict {barcode_lower: product_id}
        # _existing_bindings: set {conn_id} de bindings ya existentes

        account = self
        
        search_status = {
            "meli_id": meli_id,
            "meli_id_variation": meli_id_variation,
            "seller_sku": seller_sku,
            "barcode": barcode,
            
            "has_duplicates": False,
            
            "has_duplicates_sku": False,
            "duplicates_sku": [],
            
            "has_duplicates_barcode": False,
            "duplicates_barcode": [],
            
            "missing": False,
            "conflict": False,

            "sku_product_ids": False,
            "sku_found": False,
            "barcode_product_ids": False,
            "barcode_found": False,

            "old_posting_id": False,
            "bindings": []
        }

        old_posting_id = None #product search by model.meli_id
        
        sku_product_id = None #product search by sku
        sku_product_ids = False

        barcode_product_id = None #product search by barcode
        barcode_product_ids = False

        ml_bind_product_id = None #product search by account binding and model.conn_id/conn_variation_id

        rjson = rjson or account.fetch_meli_product( meli_id = meli_id, meli=meli )
        rjson_has_variations = rjson and "variations" in rjson and len(rjson["variations"])
        nvariants = (rjson_has_variations and len(rjson["variations"])) or 1
        
        _logger.debug("search_meli_product > meli_id:"+str(meli_id)
                        + " meli_id_variation:" + str(meli_id_variation)
                        + " seller_sku:" + str(seller_sku)
                        + " barcode:" + str(barcode)
                        + " nvariants: " + str(nvariants))

        #old meli_oerp association
        #old_posting_id = self.env['product.product'].search([('meli_id','=',meli_id)])
        

        if old_posting_id:

            search_status["old_posting_id"] = old_posting_id

            if len(old_posting_id)>1:
                #_logger.info("Duplicates old associations, maybe variants #"+str(len(old_posting_id)))
                #check rjson for variations
                if rjson_has_variations:
                    for vjson in rjson["variations"]:
                        #_logger.info(vjson)
                        pass;

            for old_prod in old_posting_id:
                #_logger.info("Product in database, check his bindings: " + str(old_prod.display_name)+str(" #")+str(len(old_prod.mercadolibre_bindings)) )

                if old_prod.mercadolibre_bindings:
                    #_logger.info("Has ML binding connections: " + str(old_posting_id.mercadolibre_bindings) )
                    pass;

                for bind in old_prod.mercadolibre_bindings:
                    #_logger.info( bind.name )
                    pass;

        #SEARCH ANY binding to meli_id
        ml_bind_product_id = account.search_meli_binding_product(meli_id = meli_id)        
        search_status["bindings"] = ml_bind_product_id

        if ml_bind_product_id:

            _logger.debug("search_meli_product > Binding Product Id found: "+str(ml_bind_product_id))
            #TODO: chequear si coinciden cantidad de variantes y revincular
            if (len(ml_bind_product_id) == nvariants):
                _logger.debug("search_meli_product > Ok variants count bindings match")
                #for pid in ml_bind_product_id.product_id:
                #    if (pid.deafult_code==seller_sku):                
                for bind in ml_bind_product_id:
                    if (not bind.binding_product_tmpl_id):
                        search_status["conflict"] = "Rebinding: template binding no existe!"

                    if ("seller_sku" in rjson and "barcode" in rjson):

                        _logger.debug("search_meli_product > Ok bind code:"+str(bind.product_id.default_code)+" barcode:"+str(bind.product_id.barcode) )

                        sku = bind.product_id.default_code
                        bcode = bind.product_id.barcode
                        if (sku and not sku in rjson["seller_sku"]):
                            search_status["conflict"] = "Rebinding: sku not matching!"
                            ml_bind_product_id = False
                            break;
                        if (bcode and rjson.get("barcode") and not bcode in rjson["barcode"]):
                            search_status["conflict"] = "Rebinding: barcode not matching!"
                            ml_bind_product_id = False
                            break;
            else:
                 _logger.info("search_meli_product > NO variant count bindings match Odoo: "+str(len(ml_bind_product_id))+"vs. Meli:"+str(nvariants))
                 for bind in ml_bind_product_id:
                    if (not bind.binding_product_tmpl_id):
                        search_status["conflict"] = "Rebinding: template binding no existe!"
                 search_status["conflict"] = "Rebinding: variant count not matching"
                 search_status["bindings"] = ml_bind_product_id
                 ml_bind_product_id = False


        #No binding and no posting, or binding but no more product deep search
        if not ml_bind_product_id or (ml_bind_product_id and not ml_bind_product_id.product_id):
            #_logger.info("Binding Product Id NOT FOUND or NOT SET: "+str(ml_bind_product_id))
            ml_bind_product_id = False
            if not old_posting_id:
                #_logger.info("Deep search of the product! : fetch sku: ")
                # Desambiguación por compañía del account (multi-company): cuando un
                # SKU/barcode matchea varios productos, muchos "duplicados" son el mismo
                # código en OTRA empresa. Si al filtrar por la empresa del account queda
                # uno, ese es el que corresponde a la cuenta.
                _acc_company = account.company_id
                def _company_dedup(prods):
                    if _acc_company and prods and len(prods) > 1:
                        _co = prods.filtered(lambda p: (not p.company_id) or p.company_id.id == _acc_company.id)
                        if _co and len(_co) < len(prods):
                            _logger.info("search_meli_product > %d producto(s) con mismo código desambiguados a %d por compañía '%s'",
                                         len(prods), len(_co), _acc_company.name)
                            return _co
                    return prods
                seller_sku = seller_sku or self.fetch_meli_sku(meli_id=meli_id, meli_id_variation = meli_id_variation, meli=meli, rjson=rjson)
                if seller_sku:
                    search_status["seller_sku"] = seller_sku
                    if type(seller_sku) in (tuple, list):                        
                        for sku in seller_sku:
                            # MULTIGET: Lookup en RAM si está disponible, evita query BD
                            if _sku_to_product is not None:
                                pid = _sku_to_product.get(sku.lower()) or _sku_to_product.get(sku)
                                sku_product_id = self.env['product.product'].browse(pid) if pid else self.env['product.product']
                            else:
                                sku_product_id = _company_dedup(self.env['product.product'].search([ ('default_code','=ilike',sku) ]))
                            if sku_product_id:
                                if not sku_product_ids:
                                    sku_product_ids = sku_product_id
                                else:
                                    sku_product_ids+= sku_product_id
                            if (sku_product_id and len(sku_product_id)>1):
                                search_status["has_duplicates"] = True
                                search_status["has_duplicates_sku"] = True
                                search_status["duplicates_sku"].append(sku_product_id)
                        sku_product_id = sku_product_ids and sku_product_ids[0]
                    else:
                        # MULTIGET: Lookup en RAM si está disponible
                        if _sku_to_product is not None:
                            pid = _sku_to_product.get(seller_sku.lower()) or _sku_to_product.get(seller_sku)
                            sku_product_id = self.env['product.product'].browse(pid) if pid else self.env['product.product']
                            if pid:
                                sku_product_ids = sku_product_id
                        else:
                            sku_product_id = _company_dedup(self.env['product.product'].search([ ('default_code','=ilike',seller_sku) ]))
                            if sku_product_id:
                                if not sku_product_ids:
                                    sku_product_ids = sku_product_id
                                else:
                                    sku_product_ids+= sku_product_id

                        if sku_product_id and len(sku_product_id)>1:
                            search_status["has_duplicates"] = True
                            search_status["has_duplicates_sku"] = True
                            search_status["duplicates_sku"].append(sku_product_id)

                else:
                    _logger.info("search_meli_product > NO seller_sku (warning!!!! must define a seller sku in ML, or activate mercadolibre_import_search_sku)")

                #_logger.info("Deep search of the product! : fetch barcode: ")
                barcode = barcode or self.fetch_meli_barcode(meli_id=meli_id, meli_id_variation = meli_id_variation, meli=meli, rjson=rjson)
                if barcode:
                    search_status["barcode"] = barcode

                    if type(barcode) in (tuple, list):                        
                        for bcode in barcode:
                            # MULTIGET: Lookup en RAM si está disponible
                            if _barcode_to_product is not None:
                                pid = _barcode_to_product.get(bcode.lower()) or _barcode_to_product.get(bcode)
                                barcode_product_id = self.env['product.product'].browse(pid) if pid else self.env['product.product']
                            else:
                                barcode_product_id = _company_dedup(self.env['product.product'].search([ ('barcode','=ilike',bcode) ]))
                            if barcode_product_id:
                                if not barcode_product_ids:
                                    barcode_product_ids = barcode_product_id
                                else:
                                    barcode_product_ids+= barcode_product_id

                            if (barcode_product_id and len(barcode_product_id)>1):
                                search_status["has_duplicates"] = True
                                search_status["has_duplicates_barcode"] = True
                                search_status["duplicates_barcode"].append(barcode_product_id)
                                
                        barcode_product_id = barcode_product_ids and barcode_product_ids[0]
                    else:
                        # MULTIGET: Lookup en RAM si está disponible
                        if _barcode_to_product is not None:
                            pid = _barcode_to_product.get(barcode.lower()) or _barcode_to_product.get(barcode)
                            barcode_product_id = self.env['product.product'].browse(pid) if pid else self.env['product.product']
                            if pid:
                                barcode_product_ids = barcode_product_id
                        else:
                            barcode_product_id = _company_dedup(self.env['product.product'].search([ ('barcode','=ilike',barcode) ]))
                            if barcode_product_id:
                                if not barcode_product_ids:
                                    barcode_product_ids = barcode_product_id
                                else:
                                    barcode_product_ids+= barcode_product_id

                        if barcode_product_id and len(barcode_product_id)>1:
                            search_status["has_duplicates"] = True
                            search_status["has_duplicates_barcode"] = True
                            search_status["duplicates_barcode"].append(barcode_product_id)


                    #_logger.info("barcode(s) fetched: barcode_product_id: "+str(barcode_product_id))

                else:
                    _logger.info("search_meli_product > NO barcode (warning!!!! must define a seller barcode in ML, or activate mercadolibre_import_search_sku)")

            else:
                #bind! update bind!
                #old_posting_id.mercadolibre_bind_to( account, )
                _logger.info("search_meli_product > Product need binding: "+str(old_posting_id[0].product_tmpl_id.display_name))

        #new_posting_tpl_id = self.env['mercadolibre.product_template'].search([('conn_id','=',meli_id)]) #('conn_variation_id','=','meli_id_variation'
        #_logger.info("new_posting_tpl_id: "+str(new_posting_tpl_id))

        #prioritize binding (so we do not duplicate article nor binded)
        if (not sku_product_id and not barcode_product_id):
            search_status["missing"] = True

        if (search_status["has_duplicates"]):
            barcode_product_id = None
            sku_product_id = None    

        search_status["sku_product_ids"] = sku_product_ids
        search_status["barcode_product_ids"] = barcode_product_ids
        dcodes = []
        if sku_product_ids:
            for p in sku_product_ids:
                dcodes.append(p.default_code)
        bcodes = []
        if barcode_product_ids:
            for p in barcode_product_ids:
                bcodes.append(p.barcode)
        search_status["sku_found"] = dcodes
        search_status["barcode_found"] = bcodes

        _logger.debug("search_meli_product > ml_bind_product_id.product_id: "+str(ml_bind_product_id and ml_bind_product_id.product_id)+" old_posting_id:"+str(old_posting_id)+" sku_product_id:"+str(sku_product_id)+" barcode_product_id:"+str(barcode_product_id))

        product_id = (search_status["conflict"]==False and ml_bind_product_id and ml_bind_product_id.product_id) or old_posting_id or sku_product_id or barcode_product_id

        _logger.debug("search_meli_product > result: search_status"+str(search_status))

        return product_id, ml_bind_product_id, search_status

    def search_meli_binding_product( self, meli_id = None, meli_id_variation=None ):
        account = self
        #new
        ml_bind_product_id = self.env['mercadolibre.product'].search([('conn_id','=',meli_id),
                                                                      #('conn_variation_id','=',meli_id_variation),
                                                                      ("connection_account","=",account.id)])
        if meli_id_variation:
            ml_bind_product_id_var = self.env['mercadolibre.product'].search([('conn_id','=',meli_id),
                                                                      ('conn_variation_id','=',meli_id_variation),
                                                                      ("connection_account","=",account.id)])
            ml_bind_product_id = ml_bind_product_id_var

        if ml_bind_product_id:
            _logger.debug("search_meli_binding_product > Found binding Product Id: "+str(ml_bind_product_id))
            pass;
        else:
            #_logger.info("NO Binding variant, search for template binding")
            ml_bind_product_template_id = self.env['mercadolibre.product_template'].search([('conn_id','=',meli_id),("connection_account","=",account.id)]) #('conn_variation_id','=','meli_id_variation'
            if ml_bind_product_template_id:
                _logger.debug("search_meli_binding_product > Found binding template found")
            else:
                _logger.debug("search_meli_binding_product > NO Found Binding at all for this account.")

        #new_posting_tpl_id = self.env['mercadolibre.product_template'].search([('conn_id','=',meli_id)]) #('conn_variation_id','=','meli_id_variation'
        #_logger.info("new_posting_tpl_id: "+str(new_posting_tpl_id))


        return ml_bind_product_id

    def create_meli_product_boms( self, meli_id, product_template ):



        return True

    #create missing product
    def _process_meli_item_direct(self, meli_id, rjson, meli,
                                   sku_to_product, barcode_to_product,
                                   force_dont_create=False):
        """
        MULTIGET: Procesa un item de ML SIN hacer commit.
        Extrae la lógica esencial de product_meli_get_products para
        permitir procesar lotes con un solo commit al final.
        Retorna: 'imported' | 'error' | 'skipped'

        'skipped' = no se creó/bindeó, esperado (NO es error: el caller no
        marca la corrida como 'error' por estos items). Dos casos:
          (a) no se encontró producto por SKU/barcode y force_dont_create=True;
          (b) el item no trae seller_sku NI seller_barcode → no se crea para
              no generar productos sin default_code (aunque force_dont_create=False).
        """
        account = self
        try:
            if not rjson or 'title' not in rjson:
                return 'error'

            rjson_has_variations = "variations" in rjson and len(rjson["variations"])

            # RPM #532: si el item trae variaciones, el SKU vive a nivel VARIACIÓN
            # (variations[].attributes SELLER_SKU o variations[].seller_custom_field),
            # NO a nivel item. Delegar en el path variation-aware que bindea/crea
            # producto por cada variación. El path item-level de abajo se conserva
            # tal cual para items SIN variaciones (SKU a nivel item).
            if rjson_has_variations:
                return account._process_meli_item_variations(
                    meli_id, rjson, meli, sku_to_product, barcode_to_product,
                    force_dont_create=force_dont_create)

            seller_sku = account.fetch_meli_sku(meli_id=meli_id, meli_id_variation=None, meli=meli, rjson=rjson)
            seller_barcode = account.fetch_meli_barcode(meli_id=meli_id, meli_id_variation=None, meli=meli, rjson=rjson)

            # Buscar producto Odoo por SKU/barcode usando dicts RAM
            product_id = None
            if seller_sku:
                sku_key = seller_sku.lower() if isinstance(seller_sku, str) else None
                if sku_key and sku_to_product:
                    product_id = sku_to_product.get(sku_key)
            if not product_id and seller_barcode:
                bc_key = seller_barcode.lower() if isinstance(seller_barcode, str) else None
                if bc_key and barcode_to_product:
                    product_id = barcode_to_product.get(bc_key)

            if product_id:
                # Producto encontrado — hacer binding
                product = self.env['product.product'].browse(product_id)
                if product.exists():
                    product.mercadolibre_bind_to(
                        account=account,
                        meli_id=meli_id,
                        meli=meli,
                        rjson=rjson,
                        bind_only=True,
                        fast_create=True
                    )
                    return 'imported'
            elif not force_dont_create:
                # BUG2: no crear productos sin identificador. Si el item no trae
                # seller_sku NI seller_barcode, se saltea (aunque force_dont_create
                # sea False) para garantizar que TODO lo importado tenga default_code.
                if not seller_sku and not seller_barcode:
                    _logger.info(
                        "_process_meli_item_direct: skip %s (sin seller_sku ni seller_barcode; no se crea producto sin identificador)",
                        meli_id)
                    return 'skipped'
                # Sin producto — crear desde ML
                productcreated = account.create_meli_product(meli_id=meli_id, meli=meli, rjson=rjson, import_images=False)
                # BUG1 (dup intra-lote): registrar el producto recién creado en los
                # dicts RAM (mutados por referencia desde el loop del lote) para que
                # un item POSTERIOR con el MISMO SKU/barcode en este mismo lote BINDEE
                # en vez de crear un duplicado. Se usan las mismas claves que el lookup
                # de arriba (seller_sku.lower() / seller_barcode.lower(), sin strip).
                if productcreated and productcreated.exists():
                    if sku_to_product is not None:
                        if isinstance(seller_sku, str) and seller_sku:
                            sku_to_product[seller_sku.lower()] = productcreated.id
                        if isinstance(productcreated.default_code, str) and productcreated.default_code:
                            sku_to_product[productcreated.default_code.lower()] = productcreated.id
                    if barcode_to_product is not None:
                        if isinstance(seller_barcode, str) and seller_barcode:
                            barcode_to_product[seller_barcode.lower()] = productcreated.id
                        if isinstance(productcreated.barcode, str) and productcreated.barcode:
                            barcode_to_product[productcreated.barcode.lower()] = productcreated.id
                return 'imported'
            else:
                # No matchea por SKU/barcode y no se permite crear: skip esperado.
                return 'skipped'

        except Exception as e:
            _logger.error("_process_meli_item_direct error %s: %s", meli_id, str(e))
            return 'error'

    def _process_meli_item_variations(self, meli_id, rjson, meli,
                                      sku_to_product, barcode_to_product,
                                      force_dont_create=False):
        """
        MULTIGET variation-aware (RPM #532): procesa un item ML CON variaciones.
        Cada variación puede tener su propio SKU (variations[].attributes SELLER_SKU
        o variations[].seller_custom_field) y su propio barcode (GTIN). Por cada
        variación:
          - busca el product.product por SKU/barcode en los dicts RAM,
          - si existe -> BINDEA la variación (meli_id + meli_id_variation),
          - si no existe y se permite crear -> crea un product.product con ese
            default_code (catálogo plano: un producto por SKU de variación, como
            modela mercadolibre.product.maestro) y lo bindea.
        Mantiene el anti-dup intra-lote (actualiza sku_to_product/barcode_to_product
        en RAM tras crear).

        Retorna:
          'imported' = al menos una variación bindeó o creó producto.
          'skipped'  = ninguna variación traía SKU/barcode (o no se pudo bindear
                       ni crear ninguna) -> esperado, NO cuenta como error.
          'error'    = excepción.
        """
        account = self
        any_bound = False
        try:
            for var in (rjson.get('variations') or []):
                var_id = var.get('id')

                # SKU/barcode de ESTA variación. fetch_meli_sku/barcode con
                # meli_id_variation devuelven el valor de la variación puntual.
                var_sku = account.fetch_meli_sku(meli_id=meli_id, meli_id_variation=var_id, meli=meli, rjson=rjson)
                var_barcode = account.fetch_meli_barcode(meli_id=meli_id, meli_id_variation=var_id, meli=meli, rjson=rjson)
                if isinstance(var_sku, (list, tuple)):
                    var_sku = var_sku[0] if var_sku else None
                if isinstance(var_barcode, (list, tuple)):
                    var_barcode = var_barcode[0] if var_barcode else None

                # Variación REALMENTE sin identificador -> no se puede bindear/crear.
                if not var_sku and not var_barcode:
                    continue

                # Lookup por SKU/barcode en los dicts RAM (mismas claves que el
                # path item-level: lower(), sin strip).
                product_id = None
                if var_sku:
                    sku_key = var_sku.lower() if isinstance(var_sku, str) else None
                    if sku_key and sku_to_product:
                        product_id = sku_to_product.get(sku_key)
                if not product_id and var_barcode:
                    bc_key = var_barcode.lower() if isinstance(var_barcode, str) else None
                    if bc_key and barcode_to_product:
                        product_id = barcode_to_product.get(bc_key)

                product = None
                if product_id:
                    product = self.env['product.product'].browse(product_id)
                    if not product.exists():
                        product = None

                if not product:
                    if force_dont_create:
                        # existe SKU pero no hay producto y no se permite crear: skip.
                        continue
                    # Crear el product.product de esta variación (catálogo plano).
                    meli_title = rjson.get('title') or str(meli_id)
                    prod_fields = {
                        'name': str(meli_title),
                        'description': str(meli_title),
                        'meli_pub': True,
                        'meli_id': meli_id,
                    }
                    if isinstance(var_sku, str) and var_sku:
                        prod_fields['default_code'] = var_sku
                    if isinstance(var_barcode, str) and var_barcode:
                        prod_fields['barcode'] = var_barcode
                    prod_fields.update(ProductType())
                    product = self.env['product.product'].create(prod_fields)
                    if product:
                        product_template = product.product_tmpl_id
                        if product_template:
                            product_template.meli_pub = True

                if not product or not product.exists():
                    continue

                # BIND de la variación: pasar meli_id_variation explícito para que
                # el binding NO tenga que auto-detectar (reusa mercadolibre_bind_to
                # de product.product, mismo path fast_create que el item-level).
                product.mercadolibre_bind_to(
                    account=account,
                    meli_id=meli_id,
                    meli_id_variation=var_id,
                    meli=meli,
                    rjson=rjson,
                    bind_only=True,
                    fast_create=True,
                )
                any_bound = True

                # Anti-dup intra-lote (BUG1): registrar el producto en los dicts RAM
                # para que una variación/item POSTERIOR con el MISMO SKU/barcode en
                # este lote BINDEE en vez de crear un duplicado.
                if sku_to_product is not None:
                    if isinstance(var_sku, str) and var_sku:
                        sku_to_product[var_sku.lower()] = product.id
                    if isinstance(product.default_code, str) and product.default_code:
                        sku_to_product[product.default_code.lower()] = product.id
                if barcode_to_product is not None:
                    if isinstance(var_barcode, str) and var_barcode:
                        barcode_to_product[var_barcode.lower()] = product.id
                    if isinstance(product.barcode, str) and product.barcode:
                        barcode_to_product[product.barcode.lower()] = product.id

            return 'imported' if any_bound else 'skipped'

        except Exception as e:
            _logger.error("_process_meli_item_variations error %s: %s", meli_id, str(e))
            return 'error'

    def create_meli_product( self, meli_id = None, meli=None, rjson=None, import_images=True ):

        account = self
        seller_sku = None
        productcreated = None

        if not meli:
            meli = self.env['meli.util'].get_new_instance( account.company_id, account )

        if not meli_id or not meli:
            return None

        #search full item data from ML
        #response = meli.get("/items/"+meli_id, {'access_token':meli.access_token})
        rjson = rjson or account.fetch_meli_product(meli_id=meli_id,meli=meli)

        if "id" in rjson and str(rjson["id"])==str(meli_id):
            meli_title = rjson['title']
            prod_fields = {
                'name': str(meli_title),
                'description': str(meli_title),
                'meli_id': meli_id,
                'meli_pub': True,
            }
            prod_fields.update(ProductType())
            #prod_fields['default_code'] = rjson3['id']
            productcreated = self.env['product.product'].create((prod_fields))
            if (productcreated):
                product_template = productcreated.product_tmpl_id
                if (product_template):
                    product_template.meli_pub = True
                #_logger.info( "Product created: " + str(productcreated) + " >> meli_id:" + str(meli_id) + "-" + str( meli_title.encode("utf-8")) )
                #pdb.set_trace()

                #_logger.info(productcreated)
                result = productcreated.product_meli_get_product( meli_id=meli_id, account=account, meli=meli, rjson=rjson, import_images=import_images )
                if result and "error" in result:
                    _logger.error("ERROR Creating Odoo product from Meli product: "+str(result))
                    return productcreated
                if (product_template):
                    bindT = product_template.mercadolibre_bind_to( account=account, meli_id=meli_id, bind_variants=True, meli=meli, rjson=rjson )
                    if bindT:
                        # from_meli_oerp = True copy form recent imported
                        bindT.fetch_meli_product( meli=meli, from_meli_oerp=True, fetch_variants=True )
            else:
                _logger.error( "ERROR Creating Odoo product: "+str(prod_fields))
        else:
            _logger.error( "ERROR: Meli product not fetched: " + str(rjson) )

        return productcreated

#MELI


    def meli_query_orders(self):
        #_logger.info("account >> meli_query_orders")
        account = self
        company = account.company_id or self.env.user.company_id

        orders_obj = self.env['mercadolibre.sale_order']
        result = orders_obj.orders_query_recent( account=account )
        return result

    def meli_query_get_questions(self):

        #_logger.info("account >> meli_query_get_questions")
        for account in self:
            company = account.company_id or self.env.user.company_id
            config = account.configuration

            #_logger.info("account >> meli_query_get_questions >> "+str(account.name))

            meli = self.env['meli.util'].get_new_instance( company, account )
            if meli.need_login():
                return meli.redirect_login()

            productT_bind_ids = self.env['mercadolibre.product_template'].search([
                ('connection_account', '=', account.id ),
            ], order='id asc')

            #_logger.info("productT_bind_ids:"+str(productT_bind_ids))

            if productT_bind_ids:
                for bindT in productT_bind_ids:
                    #_logger.info("account >> meli_query_get_questions >> "+str(bindT.name))
                    bindT.query_questions( meli=meli, config=config )


        return {}

    def meli_query_products(self):
        #_logger.info("meli_query_products")
        #same as always...
        #iterate over products
        #bind if account not binded and product found with SKU or BINDING... remember to associate connector id (ml id)
        self.product_meli_get_products()

    def meli_update_local_products(self):
        #_logger.info("meli_update_local_products")
        #_logger.info(self)
        for account in self:
            account.product_meli_update_local_products()
        pass;

    def meli_import_categories(self):
        _logger.info("meli_import_categories")
        pass;


    def meli_pause_all(self):
        _logger.info("meli_pause_all")
        pass;


#MELI internal

    def product_meli_update_local_products( self, meli=None ):

        account = self
        #_logger.info('account.product_meli_update_local_products() '+str(account.name))
        company = account.company_id or self.env.user.company_id
        product_obj = self.env['product.product']

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )
            if meli.need_login():
                url_login_meli = meli.auth_url()

        #product_ids = self.env['product.product'].search([('meli_id','!=',False),
        #                                                  '|',('company_id','=',False),('company_id','=',company.id)])

        #product_ids = self.env['product.template'].search([
        #    ('meli_pub','!=',False),
        #    ('mercadolibre_bindings','!=',False),
        #    ('default_code','=',False)
        #    ] )

        product_ids = self.env['mercadolibre.product_template'].search([
            #('meli_pub','!=',False),
            #('mercadolibre_bindings','!=',False),
            ('product_tmpl_id','!=',False),
            ('sku', 'like', '%False%')
            ] )

        #_logger.info(product_ids)

        if product_ids:
            cn = 0
            ct = len(product_ids)
            Autocommit(self)
            try:
                for obj in product_ids:
                    cn = cn + 1
                    #_logger.info( "Product Bind Template to update: [" + str(obj.product_tmpl_id.display_name) + "] " + str(cn)+"/"+str(ct))
                    try:
                        #obj.product_meli_get_product()
                        obj.product_template_update()
                        MeliCommit( self )
                    except Exception as e:
                        #_logger.info("updating product > Exception error.")
                        _logger.error(e, exc_info=True)
                        pass;

            except Exception as e:
                #_logger.info("product_meli_update_products > Exception error.")
                _logger.error(e, exc_info=True)
                MeliRollback( self )

        return {}


    def filter_meli_ids( self, results, store_id=None ):

        account = self

        company = account.company_id or self.env.user.company_id


        meli = self.env['meli.util'].get_new_instance( company, account )
        if meli.need_login():
            return meli.redirect_login()

        official_store_id = store_id
        if not official_store_id:
            return results

        c = 0
        n20 = 0
        rresults = []
        #_logger.info("results:"+str(results))
        if not results:
            return rresults

        ids = ""
        coma = ""
        maxc = (results and len(results)) or 0
        for meli_id in results:
            c+=1
            n20+=1

            #read id and official_store_id to check
            #hacer paquetes de 20 !!!!!! /items?ids=$ITEM_ID1,$ITEM_ID2&attributes=$ATTRIBUTE1,$ATTRIBUTE2,$ATTRIBUTE3

            #armamos el paquete
            ids+= coma+str(meli_id)
            coma = ","

            if n20==20 or c==maxc:
                item_params = {
                    "ids": str(ids),
                    "attributes": "id,official_store_id"
                }
                #_logger.info("item_params:"+str(item_params))
                responseItem = meli.get("/items"+str('?ids='+str(ids)+'&attributes='+str('id,official_store_id')), {'access_token':meli.access_token } )
                #[ { "code": 200, "body": { "id": "MLM863472529", "official_store_id": 3476 } },
                #_logger.info("responseItem:"+str(responseItem and responseItem.json()))
                if responseItem.json():
                    for rr in responseItem.json():
                        #_logger.info("rr:"+str(rr))
                        if ("code" in rr and rr["code"]==200):
                            if ("body" in rr and rr["body"]):
                                st_id = "official_store_id" in rr["body"] and rr["body"]["official_store_id"]
                                ml_id = "id" in rr["body"] and rr["body"]["id"]
                                if (st_id and official_store_id and str(st_id)==str(official_store_id) ):
                                    rresults.append(ml_id)
                ids = ""
                n20 = 0
        #_logger.info("rresults:"+str(rresults))

        return rresults



    # MULTIGET (TASK-001): Multiget — descarga hasta 20 items en 1 solo request
    # en lugar de 1 request por item. Reduce el tiempo de importación de horas a minutos.
    # API ML: GET /items?ids=ID1,ID2,...,ID20&attributes=campo1,campo2,...
    # Retorna: dict {meli_id: rjson} con los datos básicos de cada item.
    # Para items con variaciones, rjson incluye el array "variations" completo.
    # El caller (product_meli_get_products) usa este cache y solo hace GET individual
    # cuando necesita datos que el multiget no devuelve (fetch_meli_product fallback).
    # Ver .roots/refatodo/debug/errors-log.md → ERROR-001 y ERROR-002
    # Ver .roots/refatodo/design/decisions.md → ADR-001 y ADR-003
    MULTIGET_BATCH_SIZE = 20  # Límite oficial de la API de MercadoLibre
    MULTIGET_ATTRIBUTES = (
        "id,title,price,available_quantity,status,"
        "seller_id,seller_custom_field,category_id,"
        "buying_mode,condition,currency_id,listing_type_id,"
        "permalink,thumbnail,warranty,shipping,"
        "official_store_id,tags,sale_terms,"
        "variations,attributes,pictures"
    )

    def fetch_meli_products_multiget(self, ids, meli=None):
        """
        MULTIGET (TASK-001): Descarga datos básicos de hasta 20 publicaciones
        en un solo request usando el endpoint multiget de MercadoLibre.

        Args:
            ids (list): Lista de meli_ids a descargar (máximo 20 por llamada).
            meli: Instancia de la API. Si no se pasa, se crea una nueva.

        Returns:
            dict: {meli_id: rjson} con datos básicos. Items con error se omiten
                  y se loguean como warning para que el caller haga fallback.
        """
        account = self
        company = account.company_id or self.env.user.company_id

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        if not ids:
            return {}

        # Limitar al máximo permitido por la API
        ids_batch = ids[:account.MULTIGET_BATCH_SIZE]
        ids_str = ','.join(str(i) for i in ids_batch)

        result = {}
        try:
            # RPM #532: include_attributes=all es OBLIGATORIO para que la API
            # devuelva los SELLER_SKU/GTIN a nivel VARIACIÓN (variations[].attributes).
            # Sin él, variations[].attributes SELLER_SKU vuelve None y las
            # publicaciones con variaciones se saltean por "sin SKU". Verificado
            # contra la cuenta 532: sin el flag los SKU de variación vienen vacíos.
            url = '/items?ids=%s&attributes=%s&include_attributes=all' % (ids_str, account.MULTIGET_ATTRIBUTES)
            response = meli.get(url, {'access_token': meli.access_token})
            items = response.json()

            if not isinstance(items, list):
                # Respuesta inesperada (ej. error de autenticación global)
                _logger.warning(
                    "MULTIGET fetch_meli_products_multiget: respuesta inesperada para %s: %s",
                    ids_str[:100], str(items)[:200]
                )
                return {}

            for item_result in items:
                code = item_result.get('code', 0)
                body = item_result.get('body', {})
                item_id = body.get('id') if body else None

                if code == 200 and item_id and body.get('title'):
                    # Procesar atributos igual que fetch_meli_product para
                    # extraer seller_sku y barcode en el mismo formato
                    if 'attributes' in body:
                        for att in body.get('attributes', []):
                            if att.get('id') == 'SELLER_SKU':
                                body['seller_sku'] = att.get('value_name')
                            if att.get('id') == 'GTIN':
                                body['barcode'] = att.get('value_name')
                    if not body.get('seller_sku') and body.get('seller_custom_field'):
                        body['seller_sku'] = body['seller_custom_field']
                    # RPM #532: pre-procesar el SKU/barcode de CADA variación igual
                    # que el nivel item. Con include_attributes=all la API trae
                    # variations[].attributes SELLER_SKU/GTIN; los volcamos a
                    # variations[].seller_sku / variations[].barcode para que
                    # fetch_meli_sku y el binding por variación los encuentren.
                    for var in (body.get('variations') or []):
                        if 'attributes' in var:
                            for att in var.get('attributes', []):
                                if att.get('id') == 'SELLER_SKU' and not var.get('seller_sku'):
                                    var['seller_sku'] = att.get('value_name')
                                if att.get('id') == 'GTIN' and not var.get('barcode'):
                                    var['barcode'] = att.get('value_name')
                        if not var.get('seller_sku') and var.get('seller_custom_field'):
                            var['seller_sku'] = var['seller_custom_field']
                    result[item_id] = body
                else:
                    # Loguear para diagnóstico pero no fallar — el caller
                    # hará fallback a fetch_meli_product individual si es necesario
                    _logger.warning(
                        "MULTIGET fetch_meli_products_multiget: item con error "
                        "code=%s id=%s — se usará fallback individual",
                        code, item_id or '?'
                    )

        except Exception as e:
            _logger.error(
                "MULTIGET fetch_meli_products_multiget: excepción para ids=%s: %s",
                ids_str[:100], str(e)
            )

        return result

    #Toma y lista los ids de las publicaciones del sitio de MercadoLibre, filtrados por official_store_id
    def fetch_list_meli_ids( self, params=None, meli=None ):

        account = self

        #_logger.info("fetch_list_meli_ids: account: "+str(account))

        if not params:
            params = {}

        company = account.company_id or self.env.user.company_id

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )
            if meli.need_login():
                return meli.redirect_login()

        config = account.configuration
        official_store_id = config.mercadolibre_official_store_id or None

        response = meli.get("/users/"+str(account.seller_id)+"/items/search",
                            {'access_token':meli.access_token,
                            'search_type': 'scan',
                            'limit': 100, #max paging limit is always 100
                            **params })

        rjson = response.json()
        scroll_id = ""
        results = []
        ofresults = (rjson and "results" in rjson and rjson["results"]) or []
        filt_results = self.filter_meli_ids(  ofresults, store_id=official_store_id  )
        results+= filt_results or []
        condition_last_off = True
        total = (rjson and "paging" in rjson and "total" in rjson["paging"] and rjson["paging"]["total"]) or 0
        #_logger.info("fetch_list_meli_ids: params:"+str(params)+" total:"+str(total))

        #_logger.info("rjson:"+str(rjson))
        if (rjson and 'scroll_id' in rjson and rjson["scroll_id"]):
            scroll_id = rjson['scroll_id']
            condition_last_off = False

        max_iterations = 1000
        ite = 0
        while (condition_last_off!=True):

            ite+= 1;

            if (ite>max_iterations):
                condition_last_off = True

            search_params = {
                'access_token': meli.access_token,
                'search_type': 'scan',
                'limit': 100,
                'scroll_id': scroll_id,
                **params
            }
            #_logger.info("/users/"+str(account.seller_id)+"/items/search")
            #_logger.info("search_params: "+str(search_params))
            response = meli.get("/users/"+str(account.seller_id)+"/items/search", search_params )
            rjson2 = response.json()
            if (rjson2 and 'error' in rjson2):
                _logger.error(rjson2)
                if rjson2['message']=='invalid_token' or rjson2['message']=='expired_token':
                    ACCESS_TOKEN = ''
                    REFRESH_TOKEN = ''
                    account.write({'access_token': ACCESS_TOKEN, 'refresh_token': REFRESH_TOKEN, 'code': '' } )
                    condition = True
                    url_login_meli = meli.auth_url()
                    return {
                        "type": "ir.actions.act_url",
                        "url": url_login_meli,
                        "target": "new",}
                condition_last_off = True
            else:
                #results+= (rjson2 and "results" in rjson2 and rjson2["results"]) or []

                ofresults = (rjson2 and "results" in rjson2 and rjson2["results"]) or None
                scroll_id = rjson2 and 'scroll_id' in rjson2 and rjson2["scroll_id"] or ""
                filt_results = self.filter_meli_ids(  ofresults, store_id=official_store_id  )
                results+= filt_results or []
                condition_last_off = (total>0 and len(results)>=total)

        return results


    def fetch_list_meli_ids_maestro( self, params = None ):

        account = self
        maestros = self.env["mercadolibre.product.maestro"]
        meli_ids_maestros = []

        if not account:
            return []

        # If a specific meli_id is requested, filter maestro directly
        if params and params.get('meli_id'):
            target_id = params['meli_id']
            found = maestros.search([
                ('connection_account', '=', account.id),
                ('meli_id', '=', target_id),
            ], limit=1)
            if found:
                return [target_id]
            return []

        domain_account = [('connection_account','=',account.id)]
        domain_is_master = [('is_master','=',True)]
        domain_is_not_master = [('is_master','=',False)]
        domain_is_combo = [('is_combo','=',True)]
        domain_is_not_combo = [('is_combo','=',False)]

        domain_master_nocombos = domain_account + domain_is_master + domain_is_not_combo
        domain_master_combos = domain_account + domain_is_master + domain_is_combo
        domain_no_master_nocombos = domain_account + domain_is_not_master + domain_is_not_combo
        domain_no_master_combos = domain_account + domain_is_not_master + domain_is_combo

        melis_nocombos = maestros.search(domain_master_nocombos)
        melis_combos = maestros.search(domain_master_combos)
        melis_no_master_nocombos = maestros.search(domain_no_master_nocombos)
        melis_no_master_combos = maestros.search(domain_no_master_combos)

        if (melis_nocombos):
            meli_ids_maestros+= melis_nocombos.mapped('meli_id')

        if (melis_combos):
            meli_ids_maestros+= melis_combos.mapped('meli_id')

        if (melis_no_master_nocombos):
            meli_ids_maestros+= melis_no_master_nocombos.mapped('meli_id')

        if (melis_no_master_combos):
            meli_ids_maestros+= melis_no_master_combos.mapped('meli_id')

        #_logger.info(" fetch_list_meli_ids_maestro > " + str(meli_ids_maestros))

        return meli_ids_maestros


    def record_maestro_review( self, meli_id, meli = None, rjson = None, maestro_ram = None, variations_number = None ):
        # PERF (batch import maestro-aware): dos optimizaciones que NO cambian el
        # resultado de datos del espejo maestro, solo cómo se llega a él:
        #  - search por meli_id/meli_id_variation con `=` (índice btree) en vez de
        #    `=ilike` (que forzaba seq-scan de la tabla maestro por variación).
        #  - `maestro_ram` (dict {(meli_id,var): {id,sku,barcode,nvar}}) pre-cargado
        #    por el cron: si la variación ya está relevada y NO cambió sku/barcode/nvar,
        #    se saltea sin search ni write (mata el ~0.65s/item del hot-loop FETCH).
        #  - `variations_number` (nvar) se estampa acá mismo (fold del search+write
        #    extra que antes hacía el caller por item).
        # No se toca la lógica de dedup por sku/barcode (fallback sigue con =ilike).
        recorded = None
        maestros = self.env["mercadolibre.product.maestro"]
        domainaccount = [('connection_account','=',self.id)]

        _logger.debug("record_maestro_review: meli_id=%s, has_rjson=%s", meli_id, bool(rjson))

        if (not rjson):
            _logger.error("record_maestro_review: rjson is None for meli_id=%s", meli_id)
            return recorded

        # nvar a estampar en el/los maestro(s) de esta publicación.
        _nvar = variations_number
        if _nvar is None:
            try:
                _nvar = len(rjson.get("variations") or [])
            except Exception:
                _nvar = None

        def _inject_nvar(vals):
            if _nvar is not None:
                vals["meli_id_variations_number"] = _nvar
            return vals

        def _ram_skip(mid, mvar, exp_sku, exp_barcode):
            # True SOLO si el maestro ya existe en RAM con sku+barcode poblados que
            # coinciden y nvar igual -> nada que actualizar (ni search ni write).
            if maestro_ram is None or not exp_sku or not exp_barcode:
                return False
            e = maestro_ram.get((str(mid), str(mvar) if mvar not in (None, False, '') else ''))
            if not e:
                return False
            if str(e.get('sku')) != str(exp_sku):
                return False
            if str(e.get('barcode')) != str(exp_barcode):
                return False
            if _nvar is not None and float(e.get('nvar') or 0) != float(_nvar or 0):
                return False
            return True

        def _changed(rec, new_sku, new_barcode):
            # ¿cambió sku/barcode (misma condición histórica) o nvar respecto al rec?
            if str(rec.sku) != str(new_sku):
                return True
            if rec.barcode and new_barcode and str(rec.barcode) != str(new_barcode):
                return True
            if _nvar is not None and float(rec.meli_id_variations_number or 0) != float(_nvar or 0):
                return True
            return False

        if (rjson):
            if ("variations" in rjson and rjson["variations"]):
                for var in rjson["variations"]:
                    meli_id_variation = var.get("id")
                    # Use robust helpers that consider the SELLER_SKU attribute,
                    # seller_custom_field, inventory_id and top-level seller_sku.
                    var_seller_sku = self.fetch_meli_sku(
                        meli_id=meli_id, meli_id_variation=meli_id_variation,
                        meli=meli, rjson=rjson
                    ) or ""
                    var_seller_barcode = self.fetch_meli_barcode(
                        meli_id=meli_id, meli_id_variation=meli_id_variation,
                        meli=meli, rjson=rjson
                    ) or ""
                    if (var_seller_sku or var_seller_barcode):
                        record = {
                            "connection_account": self.id,
                            "name":  rjson["title"]+str(" <C>"),
                            "meli_id": meli_id,
                            "meli_id_variation": meli_id_variation,
                            "sku": var_seller_sku or False,
                            "barcode": var_seller_barcode or None
                        }
                        # RAM fast-path: ya relevado y sin cambios -> ni search ni write.
                        if _ram_skip(meli_id, meli_id_variation, record["sku"], record["barcode"]):
                            continue
                        _inject_nvar(record)
                        rec = maestros.search( [('meli_id','=',str(record["meli_id"])),('meli_id_variation','=',str(record["meli_id_variation"]))], limit=1)
                        if rec:
                            _logger.debug("record_maestro_review: FOUND existing maestro id=%s meli_id=%s var=%s",
                                          rec.id, record.get("meli_id"), record.get("meli_id_variation"))
                            record["name"] = rec.name
                            rec.barcode = rec.barcode or None
                            # PULL ML -> maestro: el SKU/barcode en ML es la fuente de
                            # verdad. Solo escribimos si cambió algo (antes reescribía en
                            # vano en el else -> flush por variación sin necesidad).
                            if _changed(rec, record["sku"], record["barcode"]):
                                _logger.debug("record_maestro_review: SKU/barcode cambiaron en ML, actualizando maestro id=%s meli_id=%s var=%s",
                                              rec.id, rec.meli_id, rec.meli_id_variation)
                                _new_sku = record.get("sku")
                                _new_barcode = record.get("barcode")
                                if not _new_sku or str(_new_sku) in ("--SIN SKU--", "False", "None"):
                                    record["sku"] = rec.sku
                                if not _new_barcode or str(_new_barcode) in ("--SIN BARCODE--", "False", "None"):
                                    record["barcode"] = rec.barcode
                                rec.write(record)
                        else:
                            # Build fallback domain: match by meli_id + sku/barcode (only include non-empty values)
                            fallback_domain = [('meli_id','=',str(record["meli_id"]))]
                            _sku_val = record.get("sku") or ''
                            _barcode_val = record.get("barcode") or ''
                            if _sku_val and _barcode_val:
                                fallback_domain += ['|', ('sku','=ilike',str(_sku_val)), ('barcode','=ilike',str(_barcode_val))]
                            elif _sku_val:
                                fallback_domain += [('sku','=ilike',str(_sku_val))]
                            elif _barcode_val:
                                fallback_domain += [('barcode','=ilike',str(_barcode_val))]
                            else:
                                fallback_domain += [('meli_id_variation','=',str(record.get("meli_id_variation") or ''))]
                            rec = maestros.search(fallback_domain, limit=1)
                            if not rec:
                                _logger.debug("record_maestro_review: CREATING maestro meli_id=%s var=%s sku=%s barcode=%s",
                                              record.get("meli_id"), record.get("meli_id_variation"),
                                              record.get("sku"), record.get("barcode"))
                                recorded = maestros.create( record )
                            else:
                                _logger.debug("record_maestro_review: FOUND existing maestro id=%s meli_id=%s var=%s",
                                              rec.id, record.get("meli_id"), record.get("meli_id_variation"))
                                record["name"] = rec.name
                                if _changed(rec, record["sku"], record["barcode"]):
                                    _logger.debug("record_maestro_review: SKU/barcode cambiaron en ML (fallback), actualizando maestro id=%s meli_id=%s",
                                                  rec.id, record.get("meli_id"))
                                    _new_sku = record.get("sku")
                                    _new_barcode = record.get("barcode")
                                    if not _new_sku or str(_new_sku) in ("--SIN SKU--", "False", "None"):
                                        record["sku"] = rec.sku
                                    if not _new_barcode or str(_new_barcode) in ("--SIN BARCODE--", "False", "None"):
                                        record["barcode"] = rec.barcode
                                    rec.write(record)
                    else:
                        record = {
                            "connection_account": self.id,
                            "name":  rjson["title"]+str(" <C><I>"),
                            "meli_id": meli_id,
                            "meli_id_variation": meli_id_variation,
                            "sku": "--SIN SKU--",
                            "barcode": "--SIN BARCODE--",
                        }
                        if _ram_skip(meli_id, meli_id_variation, record["sku"], record["barcode"]):
                            continue
                        _inject_nvar(record)
                        rec = maestros.search( [('meli_id','=',str(record["meli_id"])),('meli_id_variation','=',str(record["meli_id_variation"]))], limit=1)
                        if not rec:
                            _logger.debug("record_maestro_review: CREATING maestro (no SKU) meli_id=%s var=%s",
                                          record.get("meli_id"), record.get("meli_id_variation"))
                            recorded = maestros.create( record )
                        else:
                            _logger.debug("record_maestro_review: FOUND existing maestro id=%s meli_id=%s var=%s",
                                          rec.id, record.get("meli_id"), record.get("meli_id_variation"))
                            # placeholder sin sku/barcode: solo refrescar nvar si cambió.
                            if _nvar is not None and float(rec.meli_id_variations_number or 0) != float(_nvar or 0):
                                rec.write({"meli_id_variations_number": _nvar})

            else:
                # Use robust helpers (attributes, seller_custom_field, inventory_id fallbacks)
                single_sku = self.fetch_meli_sku(
                    meli_id=meli_id, meli_id_variation=None,
                    meli=meli, rjson=rjson
                )
                single_barcode = self.fetch_meli_barcode(
                    meli_id=meli_id, meli_id_variation=None,
                    meli=meli, rjson=rjson
                )
                # For non-variation products these should be strings, not lists
                if isinstance(single_sku, list):
                    single_sku = single_sku[0] if single_sku else None
                if isinstance(single_barcode, list):
                    single_barcode = single_barcode[0] if single_barcode else None
                if (single_sku or single_barcode):
                    seller_sku = single_sku or False
                    barcode = single_barcode or False
                    record = {
                        "connection_account": self.id,
                        "name":  rjson["title"]+str(" <C>"),
                        "meli_id": meli_id,
                        "meli_id_variation": None,
                        "sku": seller_sku,
                        "barcode": barcode
                    }
                    if not _ram_skip(meli_id, None, record["sku"], record["barcode"]):
                        _inject_nvar(record)
                        # Build fallback domain: match by meli_id + sku/barcode (only include non-empty values)
                        fallback_domain = [('meli_id','=',str(record["meli_id"]))]
                        _sku_val = record.get("sku") or ''
                        _barcode_val = record.get("barcode") or ''
                        if _sku_val and _barcode_val:
                            fallback_domain += ['|', ('sku','=ilike',str(_sku_val)), ('barcode','=ilike',str(_barcode_val))]
                        elif _sku_val:
                            fallback_domain += [('sku','=ilike',str(_sku_val))]
                        elif _barcode_val:
                            fallback_domain += [('barcode','=ilike',str(_barcode_val))]
                        rec = maestros.search(fallback_domain, limit=1)
                        if not rec:
                            _logger.debug("record_maestro_review: CREATING maestro (single) meli_id=%s sku=%s barcode=%s",
                                          record.get("meli_id"), record.get("sku"), record.get("barcode"))
                            recorded = maestros.create( record )
                        else:
                            # PULL ML -> maestro: refrescar el single existente. Conservamos el
                            # name editado y no pisamos con vacios. Solo write si cambió.
                            record["name"] = rec.name
                            _new_sku = record.get("sku")
                            _new_barcode = record.get("barcode")
                            if not _new_sku or str(_new_sku) in ("--SIN SKU--", "False", "None"):
                                record["sku"] = rec.sku
                            if not _new_barcode or str(_new_barcode) in ("--SIN BARCODE--", "False", "None"):
                                record["barcode"] = rec.barcode
                            if _changed(rec, record.get("sku"), record.get("barcode")):
                                _logger.debug("record_maestro_review: refrescando single maestro id=%s meli_id=%s sku %s->%s barcode %s->%s",
                                              rec.id, record.get("meli_id"), rec.sku, record.get("sku"), rec.barcode, record.get("barcode"))
                                rec.write(record)
                else:
                    record = {
                        "connection_account": self.id,
                        "name":  rjson["title"]+str(" <C><I>"),
                        "meli_id": meli_id,
                        "meli_id_variation": None,
                        "sku": "--SIN SKU--",
                        "barcode": "--SIN BARCODE--"
                    }
                    if not _ram_skip(meli_id, None, record["sku"], record["barcode"]):
                        _inject_nvar(record)
                        # Build fallback domain: match by meli_id + sku/barcode (only include non-empty values)
                        fallback_domain = [('meli_id','=',str(record["meli_id"]))]
                        _sku_val = record.get("sku") or ''
                        _barcode_val = record.get("barcode") or ''
                        if _sku_val and _barcode_val:
                            fallback_domain += ['|', ('sku','=ilike',str(_sku_val)), ('barcode','=ilike',str(_barcode_val))]
                        elif _sku_val:
                            fallback_domain += [('sku','=ilike',str(_sku_val))]
                        elif _barcode_val:
                            fallback_domain += [('barcode','=ilike',str(_barcode_val))]
                        rec = maestros.search(fallback_domain, limit=1)
                        if not rec:
                            _logger.debug("record_maestro_review: CREATING maestro (single, no SKU) meli_id=%s",
                                          record.get("meli_id"))
                            recorded = maestros.create( record )
                        else:
                            _logger.debug("record_maestro_review: FOUND existing maestro id=%s meli_id=%s",
                                          rec.id, record.get("meli_id"))
                            # placeholder single: solo refrescar nvar si cambió.
                            if _nvar is not None and float(rec.meli_id_variations_number or 0) != float(_nvar or 0):
                                rec.write({"meli_id_variations_number": _nvar})
        #MeliCommit( self )

        return recorded

    def get_maestro( self, meli_id, meli = None, rjson = None  ):
        mas = None
        maestros = self.env["mercadolibre.product.maestro"]
        mas = maestros.search( [('meli_id','=',meli_id),('is_master','=',True)], limit=1 )
        return mas

    #list all meli ids in odoo from this account, that are not in parameter filter_ids...
    def list_meli_ids( self, filter_ids=None ):
        meli_ids = []
        account = self
        if not filter_ids:
            bindings = self.env['mercadolibre.product_template'].search([ ('connection_account','=',account.id),
                                                                        ('product_tmpl_id','!=', False),
                                                                        ('conn_id','!=',False)
                                                                        ])
        else:
            bindings = self.env['mercadolibre.product_template'].search([ ('connection_account','=',account.id),
                                                                        ('product_tmpl_id','!=', False),
                                                                        ('conn_id','not in',filter_ids),
                                                                        ('conn_id','!=',False)
                                                                        ])
        if bindings:
            meli_ids = bindings.mapped('conn_id')

        return meli_ids

    def product_meli_get_products(self, context=None, limit=50):
        #
        account = self
        context = context or self.env.context
        #_logger.info('account.product_meli_get_products() '+str(account.name)+" context:"+str(context))
        company = account.company_id or self.env.user.company_id
        product_obj = self.env['product.product']
        warningobj = self.env['meli.warning']

        post_state = context and context.get("post_state")
        meli_id = context and context.get("meli_id")
        force_create_variants = context and context.get("force_create_variants")
        force_dont_create = context and context.get("force_dont_create")
        force_meli_pub =  context and context.get("force_meli_pub")
        force_import_images = context and context.get("force_import_images")
        force_meli_website_published = context and context.get("force_meli_website_published")
        force_meli_website_category_create_and_assign = context and context.get("force_meli_website_category_create_and_assign")
        batch_processing_unit = context and context.get("batch_processing_unit")
        batch_processing_unit_offset = context and context.get("batch_processing_unit_offset")
        batch_actives_to_sync = context and context.get("batch_actives_to_sync")
        batch_paused_to_sync = context and context.get("batch_paused_to_sync")
        batch_left_to_sync = context and context.get("batch_left_to_sync")
        # MULTIGET: rjson pre-cargado por el cron via multiget paralelo
        # Si viene en el context lo usamos directamente sin hacer fetch API
        _preloaded_rjson = context and context.get("_preloaded_rjson")
        # MULTIGET: flag para fast-path create en mercadolibre_bind_to
        _is_new_import = context and context.get("_is_new_import", False)
        search_limit = batch_processing_unit or 100
        search_offset = batch_processing_unit_offset or 0

        actives_to_sync = []
        odoo_meli_ids = []

        #Lets list all the already imported meli publications
        if (batch_actives_to_sync or batch_paused_to_sync or batch_left_to_sync):
            odoo_meli_ids = odoo_meli_ids or account.list_meli_ids()

        #_logger.info("batch_processing_unit:"+str(batch_processing_unit)+" search_offset:"+str(search_offset)+" search_limit:"+str(search_limit))

        meli = self.env['meli.util'].get_new_instance( company, account )
        if meli.need_login():
            return meli.redirect_login()

        import time as _pmg_time
        _pmg_t0 = _pmg_time.time()
        results = []

        post_state_filter = {}
        if post_state:
            if post_state=='active' or batch_actives_to_sync:
                post_state_filter = { 'status': 'active' }
            elif post_state=='paused' or batch_paused_to_sync:
                post_state_filter = { 'status': 'paused' }
            elif post_state=='closed':
                post_state_filter = { 'status': 'closed' }
        if meli_id:
            post_state_filter.update( { 'meli_id': meli_id } )

        official_store_id = (account.official_store_id) or None

        url_get = "/users/"+str(account.seller_id)+"/items/search"

        #_logger.info(meli.access_token)
        # When importing a specific meli_id, skip the full API scan
        if meli_id:
            meli_ids = [meli_id]
            # MULTIGET: en importación masiva nueva, los maestros no aplican — skip queries
            if _is_new_import:
                meli_ids_maestros = []
            else:
                meli_ids_maestros = self.fetch_list_meli_ids_maestro( params=post_state_filter )
        else:
            meli_ids = self.fetch_list_meli_ids( params=post_state_filter )
            meli_ids_maestros = self.fetch_list_meli_ids_maestro( params=post_state_filter )

        meli_ids_maestros_checked = []
        # MULTIGET: en importación masiva nueva, skip search_count de maestros
        if _is_new_import:
            meli_ids_maestros_active = False
        else:
            meli_ids_maestros_active = meli_ids_maestros and len(meli_ids_maestros)
            if not meli_ids_maestros_active and meli_id:
                meli_ids_maestros_active = self.env["mercadolibre.product.maestro"].search_count([
                    ('connection_account', '=', account.id)
                ]) > 0
        _logger.info("product_meli_get_products: meli_id=%s, maestros_active=%s, maestros_list=%s",
                     meli_id or 'bulk', meli_ids_maestros_active,
                     len(meli_ids_maestros) if meli_ids_maestros else 0)
        if (meli_ids_maestros_active):
            #nos aseguramos procesar en orden las publicaciones de los maestros:
            for mid in meli_ids_maestros:
                if mid in meli_ids:
                    if mid not in meli_ids_maestros_checked:
                        meli_ids_maestros_checked.append(mid)
            #agregamos los rezagados
            for mid in meli_ids:
                if mid not in meli_ids_maestros_checked:
                    meli_ids_maestros_checked.append(mid)

            meli_ids = meli_ids_maestros_checked
        #_logger.info("meli_ids_maestros_checked "+str(meli_ids_maestros_checked and len(meli_ids_maestros_checked) or 0)+" > "+str(meli_ids_maestros_checked))
        #_logger.info("meli_ids_maestros_active "+str(meli_ids_maestros_active))

        #download?
        totalmax = len(meli_ids)
        offset = search_offset
        results = list(meli_ids)  # default: process all ids

        if (totalmax>1):
            #USE SCAN METHOD.... ALWAYS
            condition_last_off = True
            ioff = 0
            cof = 0
            results = []

            for meli_id in meli_ids:
                ioff = cof
                if meli_id:
                    if ( cof>=offset and meli_id not in odoo_meli_ids ):
                        results.append( meli_id )
                    cof+= 1

                if (batch_processing_unit and batch_processing_unit>0 and results and len(results)>=batch_processing_unit):
                    break;

        #search for meli_ids not imported yet
        # MULTIGET: cuando batch_processing_unit>0 este resultado nunca se usa
        # (la condición de abajo requiere batch_processing_unit==0), así que lo saltamos
        if not batch_processing_unit or batch_processing_unit == 0:
            binding_meli_ids = account.list_meli_ids(filter_ids=results)
        else:
            binding_meli_ids = []

        #_logger.info( results )
        #_logger.info( "FULL RESULTS: " + str(len(results)) + " News: " + str(len(binding_meli_ids)) )
        #_logger.info( binding_meli_ids )
        #_logger.info( "("+str(totalmax)+") products to check...")


        if binding_meli_ids and (not batch_processing_unit or batch_processing_unit==0):
            #assigning missing meli ids, shapes, and colors
            #_logger.info( "results, not batch_processing_unit, assigning binding_meli_ids: "+str(binding_meli_ids))
            results = binding_meli_ids

        totalmax = len(results)
        iitem = 0
        icommit = 0
        micom = 5

        duplicates = []
        missing = []
        synced = []
        created = []
        res = {}
        if (results):
            Autocommit( self )
            try:
                # MULTIGET (TASK-001): Pre-cargar datos en lotes de 20 con Multiget.
                # 100k items = 100,000 requests → 5,000 requests (~20x más rápido).
                # Ver .roots/refatodo/debug/errors-log.md → ERROR-001 y ERROR-002
                multiget_cache = {}

                def _fill_multiget_cache(start_index):
                    batch = results[start_index:start_index + account.MULTIGET_BATCH_SIZE]
                    if batch:
                        fetched = account.fetch_meli_products_multiget(ids=batch, meli=meli)
                        multiget_cache.update(fetched)
                        _logger.info(
                            "MULTIGET multiget: bloque %d-%d → %d/%d items cargados",
                            start_index, start_index + len(batch) - 1,
                            len(fetched), len(batch)
                        )

                # MULTIGET: Si el cron ya pre-cargó todos los rjson via multiget paralelo,
                # usamos ese dict directamente y no necesitamos el multiget local
                if isinstance(_preloaded_rjson, dict) and _preloaded_rjson:
                    multiget_cache = _preloaded_rjson  # dict {meli_id: rjson} ya cargado
                else:
                    # Pre-cargar primer bloque
                    _fill_multiget_cache(0)

                for item_id in results:
                    iitem += 1
                    icommit += 1
                    if (icommit >= micom):
                        MeliCommit( self )
                        icommit = 0

                    _pt_start = _pmg_time.time()

                # MULTIGET: Pre-cargar el siguiente bloque a mitad del actual
                # Solo si NO tenemos un preloaded dict del cron
                    if not isinstance(_preloaded_rjson, dict) and iitem % account.MULTIGET_BATCH_SIZE == (account.MULTIGET_BATCH_SIZE // 2):
                        next_start = ((iitem // account.MULTIGET_BATCH_SIZE) + 1) * account.MULTIGET_BATCH_SIZE
                        if next_start < totalmax:
                            _fill_multiget_cache(next_start)

                    # MULTIGET: Prioridad de fuente del rjson:
                    # 1. _preloaded_rjson del context (cron pre-cargó via multiget paralelo)
                    #    _preloaded_rjson es un dict {meli_id: rjson}
                    # 2. multiget_cache (pre-fetch propio de product_meli_get_products)
                    # 3. fetch_meli_product individual (fallback)
                    if isinstance(_preloaded_rjson, dict):
                        rjson = _preloaded_rjson.get(item_id)
                    elif _preloaded_rjson and item_id == meli_id:
                        rjson = _preloaded_rjson
                    else:
                        rjson = None
                    if not rjson:
                        rjson = multiget_cache.pop(item_id, None)
                    if not rjson:
                        _logger.debug("MULTIGET multiget fallback para %s", item_id)
                        rjson = account.fetch_meli_product(meli_id=item_id, meli=meli)

                    # Guard: skip items where API returned error or incomplete data
                    if not rjson or 'title' not in rjson:
                        _logger.warning("product_meli_get_products: skipping %s - API response missing 'title': %s",
                                        item_id, str(rjson)[:200] if rjson else 'None')
                        missing.append({
                            'name': item_id,
                            'odoo default_code': '',
                            'odoo barcode': '',
                            'meli_sku': '',
                            'meli_barcode': '',
                            'meli_id': item_id,
                            'meli_id_variation': '',
                            'meli_status': str(rjson.get('error', 'unknown')) if rjson else 'no response',
                            'status': 'error'
                        })
                        continue

                    rjson_has_variations = rjson and "variations" in rjson and len(rjson["variations"])

                    #seller_sku = None

                    #if not seller_sku and "attributes" in rjson:
                    #    for att in rjson['attributes']:
                    #        if att["id"] == "SELLER_SKU":
                    #            seller_sku = att["values"][0]["name"]
                    #            break;

                    #if (not seller_sku and 'seller_custom_field' in rjson and rjson['seller_custom_field'] and len(rjson['seller_custom_field'])):
                    #    seller_sku = rjson['seller_custom_field']

                    seller_sku = account.fetch_meli_sku(meli_id=item_id, meli_id_variation = None, meli=meli, rjson=rjson)
                    seller_barcode = account.fetch_meli_barcode( meli_id=item_id, meli_id_variation=None, meli=meli, rjson=rjson)
                    _pt_sku = _pmg_time.time()

                    _logger.debug("product_get_meli_products > SKUS:"+str(seller_sku)+" BARCODES:"+str(seller_barcode)+" VARIATIONS:"+str(rjson_has_variations))
                    
                    product_ids = []
                    binding_ids = []                    
                    some_product_id_found = False
                    some_product_id_duplicate = False
                    search_statuses = []
                    
                    if (rjson_has_variations and len(rjson["variations"])>1):
                        for var in rjson["variations"]:
                            meli_id = item_id
                            meli_id_variation = ("id" in var and var["id"])
                            var_seller_sku = ("seller_sku" in var and var["seller_sku"])
                            var_seller_sku = var_seller_sku or ("inventory_id" in var and var["inventory_id"])
                            var_barcode = ("barcode" in var and var["barcode"])
                            product_id, binding_id, search_status  = account.search_meli_product( 
                                meli_id = item_id, 
                                meli_id_variation=meli_id_variation, 
                                seller_sku=var_seller_sku, 
                                barcode=var_barcode, 
                                meli=meli, 
                                rjson=rjson,
                                _sku_to_product=_preloaded_rjson and context and context.get('_sku_to_product'),
                                _barcode_to_product=_preloaded_rjson and context and context.get('_barcode_to_product') )

                            search_statuses.append(search_status)
                            
                            
                            if binding_id:
                                binding_ids.append(binding_id)

                            if (search_status["has_duplicates"]==True):
                                some_product_id_duplicate = True
                                some_product_id_found = True

                            if product_id:
                                product_ids.append(product_id)
                                UpdateProductType( product_id )
                                some_product_id_found = True                                

                    else:
                        product_id, binding_id, search_status  = account.search_meli_product(
                            meli_id = item_id, seller_sku=seller_sku, barcode=seller_barcode, meli=meli, rjson=rjson,
                            _sku_to_product=context and context.get('_sku_to_product'),
                            _barcode_to_product=context and context.get('_barcode_to_product') )
                        
                        if (product_id):                            
                            UpdateProductType( product_id )
                            some_product_id_found = True

                            product_ids.append(product_id)
                        
                        if binding_id:
                            binding_ids.append(binding_id)
                        
                        search_statuses.append(search_status)
                        
                        if (search_status["has_duplicates"]==True):
                            some_product_id_duplicate = True
                            some_product_id_found = True
                    #
                    _pt_search = _pmg_time.time()

                    #posting_id = self.env['product.product'].search([('meli_id','=',item_id)])
                    #_logger.info("search_meli_product for meli_id: "+str(meli_id)+" RESULT: product_id:"+str(product_id)+" binding_id:"+str(binding_id))                    

                    if (some_product_id_found or force_dont_create):
                        
                        if (some_product_id_found and some_product_id_duplicate):
                            
                            for s_status in search_statuses:
                                if (s_status["has_duplicates"]):                                
                                    duplicates.append({
                                        'name': str(rjson['title']),
                                        'odoo_default_code': str(s_status["duplicates_sku"]),
                                        'odoo_barcode': str(s_status["duplicates_barcode"]),
                                        'meli_sku': str(s_status["seller_sku"]),
                                        'meli_barcode': str(s_status["barcode"]),
                                        'meli_id': item_id,
                                        'meli_id_variation': str(s_status["meli_id_variation"]),
                                        'meli_status': rjson['status'],
                                        'status': 'duplicate'
                                    })
                                elif (s_status["missing"]):
                                    missing.append( {
                                        'name': str(rjson['title']),
                                        'odoo default_code': "",
                                        'odoo barcode': "",
                                        'meli_sku': str(s_status["seller_sku"]),
                                        'meli_barcode': str(s_status["barcode"]),
                                        'meli_id': item_id,
                                        'meli_id_variation': str(s_status["meli_id_variation"]),
                                        'meli_status': rjson['status'] ,
                                        'status': "missing"
                                    })
                                else:
                                    synced.append( {
                                        'name': str(rjson['title']),
                                        'odoo default_code': str(search_status["sku_found"]),
                                        'odoo barcode': str(search_status["barcode_found"]),
                                        'meli_sku': str(s_status["seller_sku"]),
                                        'meli_barcode': str(s_status["barcode"]),
                                        'meli_id': item_id,
                                        'meli_id_variation': str(s_status["meli_id_variation"]),
                                        'meli_status': rjson['status'] ,
                                        'status': "found"
                                    })

                                #_logger.error( "Item already in database but duplicated: " + str(product_id.mapped('name')) + " skus:" + str(product_id.mapped('default_code')) )

                        elif (some_product_id_found and not some_product_id_duplicate):

                            #_logger.info( "Item(s) already in database: " + str(product_id.mapped('display_name')) + str(" #")+str(len(product_id)) )

                            if force_meli_pub:
                                #for s_status in search_statuses:
                                if (product_ids):
                                    for p_id in product_ids:
                                        _logger.debug( "Item meli_pub set: " + str(p_id) )
                                        if p_id:
                                            for p in p_id:
                                                p.meli_pub = True
                                                p.product_tmpl_id.meli_pub = True

                                for s_status in search_statuses:
                                    if (s_status["missing"]):
                                        missing.append( {
                                            'name': str(rjson['title']),
                                            'odoo default_code': "",
                                            'odoo barcode': "",
                                            'meli_sku': str(s_status["seller_sku"]),
                                            'meli_barcode': str(s_status["barcode"]),
                                            'meli_id': item_id,
                                            'meli_id_variation': str(s_status["meli_id_variation"]),
                                            'meli_status': rjson['status'] ,
                                            'status': "missing"
                                        })
                                    else:
                                        synced.append( {
                                            'name': str(rjson['title']),
                                            'odoo default_code': str(search_status["sku_found"]),
                                            'odoo barcode': str(search_status["barcode_found"]),
                                            'meli_sku': str(s_status["seller_sku"]),
                                            'meli_barcode': str(s_status["barcode"]),
                                            'meli_id': item_id,
                                            'meli_id_variation': str(s_status["meli_id_variation"]),
                                            'meli_status': rjson['status'] ,
                                            'status': "synced"
                                        })

                            #TODO: fix bindings
                            #if not binding_id:
                                #auto bind
                            bind_only = False
                            if rjson_has_variations:
                                #_logger.info( "Binding variations: oldies: " + str(binding_id and binding_id.mapped('name')) + str(" binding_id:")+str(binding_id) )
                                if binding_id:
                                    #_logger.info( "Item(s) already binded: " + str(binding_id.mapped('name')) + str(" #")+str(len(binding_id)) )
                                    bind_only = True
                                for product in product_ids:
                                    try:
                                        pvbind = product.mercadolibre_bind_to( account=account, meli_id = item_id, meli=meli, rjson=rjson, bind_only=bind_only, fast_create=_is_new_import )
                                        _logger.info("pvbind: ", pvbind )
                                    except Exception as E:
                                        _logger.error("Error haciendo bindingitem_id:"+str(item_id)+" error:"+str(E))
                                        missing.append({
                                                        'name': str(product.name),
                                                        'odoo default_code': str(product.default_code),
                                                        'odoo barcode': str(product.barcode),
                                                        'meli_sku': str(seller_sku or ''),
                                                        'meli_barcode': str(seller_barcode or ''),
                                                        'meli_id': item_id,
                                                        'meli_id_variation': '',
                                                        'meli_status': str(E) ,
                                                        'status': 'error'
                                                    })
                                        pass;
                            else:
                                try:
                                    pvbind = product_ids[0].mercadolibre_bind_to( account=account, meli_id = item_id, meli=meli, rjson=rjson, bind_only=bind_only, fast_create=_is_new_import)
                                    #_logger.info("pvbind: ", pvbind )
                                except Exception as E:
                                    _logger.error("Error haciendo bindingitem_id:"+str(item_id)+" error:"+str(E))
                                    missing.append({
                                                    'name': rjson['title'],
                                                    'odoo default_code': str(product_id.default_code),
                                                    'odoo barcode': str(product_id.barcode),
                                                    'meli_sku': str(seller_sku or ''),
                                                    'meli_barcode': str(seller_barcode or ''),
                                                    'meli_id': item_id,
                                                    'meli_id_variation': '',
                                                    'meli_status': str(E) ,
                                                    'status': 'error'
                                                    })
                                    pass;

                        else:
                            missing.append({
                                'name': str(rjson['title']),
                                'odoo default_code': '',
                                'odoo barcode': '',
                                'meli_sku': str(seller_sku or ''),
                                'meli_barcode': str(seller_barcode or ''),
                                'meli_id': item_id,
                                'meli_id_variation': '',
                                'meli_status': rjson['status'] ,
                                'status': 'missing'
                            })
                            #_logger.info( "Item not in database, no sync founded for meli_id: "+str(item_id) + " seller_sku: " +str(seller_sku) )
                        #rewrite, maybe update data from rjson... not in template but in bindings...
                        #if binding_id:
                        #    product_id[0].mercadolibre_bind_to( account=account, meli_id = item_id)
                    #elif (not company.mercadolibre_import_search_sku):

                        #_logger.info("Product "+str(product_id))
                        #_logger.info("Binding "+str(binding_id))

                        if (meli_ids_maestros_active):
                            if (item_id in meli_ids_maestros):
                                #_logger.info("Product is in maestro already as a publication but checking if its complete: "+str(item_id) )
                                account.record_maestro_review( meli_id = item_id, meli=meli, rjson=rjson )
                            else:
                                #_logger.info("Product is NOT in maestro already, register it: "+str(item_id) )
                                #product_id, binding_id
                                account.record_maestro_review( meli_id = item_id, meli=meli, rjson=rjson )

                    else:
                        if (official_store_id and "official_store_id" in rjson and str(official_store_id)!=str(rjson["official_store_id"])):
                            continue;
                        #idcreated = self.pool.get('product.product').create(cr,uid,{ 'name': rjson3['title'], 'meli_id': rjson3['id'] })
                        try:
                            #solo crear productos si esta en el maestro
                            if (meli_ids_maestros_active):
                                if (item_id in meli_ids_maestros):
                                    #busca el que es is_master true
                                    el_maestro = account.get_maestro(item_id)
                                    #_logger.info("el_maestro: "+str(el_maestro))
                                    #_logger.info("el_maestro meli_id: "+str(item_id))
                                    #_logger.info("el_maestro.is_master: "+str(el_maestro.is_master))
                                    #_logger.info("el_maestro.is_valid: "+str(el_maestro.is_valid))

                                    if (el_maestro and el_maestro.is_master and el_maestro.is_valid):
                                        _logger.info("CREATING product from maestro: meli_id=%s, sku=%s, title=%s",
                                                     item_id, seller_sku or '', (rjson.get('title') or '')[:60])
                                        created_product = account.create_meli_product( meli_id = item_id, meli=meli, rjson=rjson, import_images=force_import_images )
                                        if created_product:
                                            _logger.info("CREATED OK: product.product id=%s, default_code=%s, meli_id=%s",
                                                         created_product.id, created_product.default_code or '', item_id)
                                            created.append({
                                                'name': str(rjson.get('title', '')),
                                                'odoo_id': created_product.id,
                                                'odoo_default_code': str(created_product.default_code or ''),
                                                'meli_sku': str(seller_sku or ''),
                                                'meli_id': item_id,
                                                'meli_status': rjson.get('status', ''),
                                                'status': 'created'
                                            })
                                        else:
                                            _logger.warning("CREATE FAILED: meli_id=%s returned None", item_id)
                                    else:
                                        _logger.info("SKIPPED create: maestro not valid or not master for meli_id=%s", item_id)
                                        #porque?


                                else:
                                    #_logger.info("Meli Id not in maestro, record it: "+str(item_id))
                                    account.record_maestro_review( meli_id = item_id, meli=meli, rjson=rjson )
                            else:
                                _logger.info("CREATING product (no maestros): meli_id=%s, sku=%s, title=%s",
                                             item_id, seller_sku or '', (rjson.get('title') or '')[:60])
                                created_product = account.create_meli_product( meli_id = item_id, meli=meli, rjson=rjson, import_images=force_import_images )
                                if created_product:
                                    _logger.info("CREATED OK: product.product id=%s, default_code=%s, meli_id=%s",
                                                 created_product.id, created_product.default_code or '', item_id)
                                    created.append({
                                        'name': str(rjson.get('title', '')),
                                        'odoo_id': created_product.id,
                                        'odoo_default_code': str(created_product.default_code or ''),
                                        'meli_sku': str(seller_sku or ''),
                                        'meli_id': item_id,
                                        'meli_status': rjson.get('status', ''),
                                        'status': 'created'
                                    })
                                else:
                                    _logger.warning("CREATE FAILED: meli_id=%s returned None", item_id)
                        except Exception as e:
                            _logger.error("product_meli_get_products create_meli_product Exception!")
                            _logger.error(e, exc_info=True)
                            #MeliRollback( self )
                    #_logger.info("##########")

                    # ALWAYS register/update maestro if system is active,
                    # regardless of whether product was synced, missing, or duplicate.
                    # record_maestro_review is idempotent (searches before creating).
                    if meli_ids_maestros_active and rjson:
                        _logger.info("maestro: registering/reviewing meli_id=%s (title=%s)",
                                     item_id, (rjson.get('title') or '')[:60])
                        try:
                            account.record_maestro_review(meli_id=item_id, meli=meli, rjson=rjson)
                        except Exception as maestro_err:
                            _logger.error("maestro: error registering %s: %s", item_id, str(maestro_err))

                    # MULTIGET PROFILING por item en product_meli_get_products
                    if iitem <= 10 or iitem % 100 == 0:
                        _pt_end = _pmg_time.time()
                        _logger.info("MULTIGET PROFILING inner item %d (%s): sku=%.3fs search=%.3fs bind=%.3fs total=%.3fs",
                                     iitem, item_id,
                                     _pt_sku - _pt_start,
                                     _pt_search - _pt_sku,
                                     _pt_end - _pt_search,
                                     _pt_end - _pt_start)

                #_logger.info("Synced: "+str(synced))
                #_logger.info("Duplicates: "+str(duplicates))
                #_logger.info("Missing: "+str(missing))
            except Exception as e:
                _logger.error("product_meli_get_products Exception!")
                _logger.error(e, exc_info=True)
                #_logger.info("Synced: "+str(synced))
                #_logger.info("Duplicates: "+str(duplicates))
                #_logger.info("Missing: "+str(missing))
                MeliRollback( self )

            # MULTIGET: cuando batch_processing_unit>0 (cron), saltarse el INSERT en meli.warning
            # ya que res se sobreescribe inmediatamente abajo y el create es ~0.35s desperdiciado
            _pt_post_loop = _pmg_time.time()
            if meli_id and _is_new_import:
                _logger.info("MULTIGET PROFILING post-loop (%s): %.3fs desde inicio función", meli_id, _pt_post_loop - _pmg_t0)
            if not batch_processing_unit or batch_processing_unit == 0:
                html_report = "<h2>Reporte Importación</h2>"

                html_report+= "<h4>Creados (%s)</h4>" % len(created)
                for pub in created:
                    html_report+= "<br/> meli_id: "+pub['meli_id']+" name:"+pub['name']+ " meli_sku:"+pub["meli_sku"]+" odoo_id:"+str(pub.get('odoo_id',''))

                html_report+= "<h4>Sincronizados (%s)</h4>" % len(synced)
                for pub in synced:
                    html_report+= "<br/> meli_id: "+pub['meli_id']+" name:"+pub['name']+ " meli_sku:"+pub["meli_sku"]

                html_report+= "<h4>Duplicados (%s)</h4>" % len(duplicates)
                for pub in duplicates:
                    html_report+= "<br/> meli_id: "+pub['meli_id']+" name:"+pub['name']+ " meli_sku:"+pub["meli_sku"]

                html_report+= "<h4>Faltantes (%s)</h4>" % len(missing)
                for pub in missing:
                    html_report+= "<br/> meli_id: "+pub['meli_id']+" name:"+pub['name']+ " meli_sku:"+pub["meli_sku"]

                _logger.info("=== IMPORT SUMMARY: created=%s, synced=%s, duplicates=%s, missing=%s ===",
                             len(created), len(synced), len(duplicates), len(missing))

                res = warningobj.info( title='MELI INFO IMPORT',
                                              message="Reporte de Importación",
                                              message_html=""+html_report )
            else:
                html_report = ""
                res = {}

            if batch_processing_unit and batch_processing_unit>0:
                res = {}
            res.update( {
                'html_report': html_report,
                'paging': {
                    'offset': search_offset,
                    'next_offset': search_offset+search_limit,
                    'limit': search_limit
                },
                'json_report': {
                    'created': created,
                    'synced': synced,
                    'duplicates': duplicates,
                    'missing': missing
                    }
                })
            #_logger.info(res)
        return res

    def meli_update_remote_products( self, post_new=False ):
        #
        _logger.info("meli_update_remote_products")
        pass;

    def diagnose_stock_queries(self):
        """
        Diagnostic method to identify bottlenecks in stock update queries.
        Run this from shell: account.diagnose_stock_queries()
        Returns a detailed report of:
        1. Missing indexes on mercadolibre_product table
        2. Execution time and plan for each query
        3. Table statistics
        """
        account = self
        results = []
        _logger.info("=" * 60)
        _logger.info("DIAGNOSE STOCK QUERIES START for account: %s", account.name)
        _logger.info("=" * 60)

        # 1. Check existing indexes on mercadolibre_product
        _logger.info("\n[1] CHECKING INDEXES on mercadolibre_product...")
        idx_query = """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'mercadolibre_product'
            ORDER BY indexname;
        """
        self.env.cr.execute(idx_query)
        indexes = self.env.cr.fetchall()
        _logger.info("Found %s indexes:", len(indexes))
        for idx in indexes:
            _logger.info("  - %s", idx[0])
        results.append({"indexes": indexes})

        # 2. Check indexes on product_product (for the JOIN)
        _logger.info("\n[2] CHECKING INDEXES on product_product...")
        pp_idx_query = """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'product_product'
            ORDER BY indexname;
        """
        self.env.cr.execute(pp_idx_query)
        pp_indexes = self.env.cr.fetchall()
        _logger.info("Found %s indexes on product_product:", len(pp_indexes))
        for idx in pp_indexes[:10]:  # Show first 10
            _logger.info("  - %s", idx[0])

        # 3. Table row counts
        _logger.info("\n[3] TABLE STATISTICS...")
        self.env.cr.execute("SELECT COUNT(*) FROM mercadolibre_product WHERE connection_account = %s", (account.id,))
        mp_count = self.env.cr.fetchone()[0]
        self.env.cr.execute("SELECT COUNT(*) FROM product_product WHERE active = TRUE")
        pp_count = self.env.cr.fetchone()[0]
        _logger.info("  mercadolibre_product (this account): %s rows", mp_count)
        _logger.info("  product_product (active): %s rows", pp_count)
        results.append({"mp_count": mp_count, "pp_count": pp_count})

        # 4. Check for recommended missing indexes
        _logger.info("\n[4] CHECKING RECOMMENDED INDEXES...")
        recommended = [
            ("mercadolibre_product", "connection_account"),
            ("mercadolibre_product", "product_id"),
            ("mercadolibre_product", "meli_stock_status"),
            ("mercadolibre_product", "meli_last_status"),
            ("mercadolibre_product", "meli_id"),
        ]
        missing_indexes = []
        for table, column in recommended:
            check_query = """
                SELECT 1 FROM pg_indexes
                WHERE tablename = %s AND indexdef LIKE %s
                LIMIT 1;
            """
            self.env.cr.execute(check_query, (table, f'%({column})%'))
            if not self.env.cr.fetchone():
                missing_indexes.append(f"{table}.{column}")
                _logger.info("  ❌ MISSING INDEX: %s.%s", table, column)
            else:
                _logger.info("  ✅ OK: %s.%s", table, column)
        results.append({"missing_indexes": missing_indexes})

        # 5. Test individual queries with timing
        _logger.info("\n[5] TESTING QUERY PERFORMANCE...")

        # Simple count query
        t0 = datetime.now()
        self.env.cr.execute("""
            SELECT COUNT(*) FROM mercadolibre_product
            WHERE connection_account = %s
        """, (account.id,))
        count1 = self.env.cr.fetchone()[0]
        t1 = datetime.now()
        _logger.info("  Q1 - Simple count (no join): %s rows in %.3fs", count1, (t1-t0).total_seconds())

        # Count with JOIN
        t0 = datetime.now()
        self.env.cr.execute("""
            SELECT COUNT(*) FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE AND melip.connection_account = %s
        """, (account.id,))
        count2 = self.env.cr.fetchone()[0]
        t1 = datetime.now()
        _logger.info("  Q2 - Count with JOIN on product_product: %s rows in %.3fs", count2, (t1-t0).total_seconds())

        # Count with full WHERE clause
        t0 = datetime.now()
        self.env.cr.execute("""
            SELECT COUNT(*) FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
        """, (account.id,))
        count3 = self.env.cr.fetchone()[0]
        t1 = datetime.now()
        _logger.info("  Q3 - Count with JOIN + meli_id filter: %s rows in %.3fs", count3, (t1-t0).total_seconds())

        # Count with stock_status filter
        t0 = datetime.now()
        self.env.cr.execute("""
            SELECT COUNT(*) FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
        """, (account.id,))
        count4 = self.env.cr.fetchone()[0]
        t1 = datetime.now()
        _logger.info("  Q4 - Count with stock_status filter: %s rows in %.3fs", count4, (t1-t0).total_seconds())

        # Full UNION ALL query
        t0 = datetime.now()
        self.env.cr.execute("""
            SELECT melip.id, 1 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status IS NULL

            UNION ALL

            SELECT melip.id, 2 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status = 'active'

            UNION ALL

            SELECT melip.id, 3 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status IS NOT NULL
            AND melip.meli_last_status != 'active'

            ORDER BY priority ASC
        """, (account.id, account.id, account.id))
        union_results = self.env.cr.fetchall()
        t1 = datetime.now()
        _logger.info("  Q5 - Full UNION ALL query: %s rows in %.3fs", len(union_results), (t1-t0).total_seconds())

        # 6. Get EXPLAIN ANALYZE for the slow query
        _logger.info("\n[6] EXPLAIN ANALYZE for UNION ALL query (first sub-query)...")
        try:
            self.env.cr.execute("""
                EXPLAIN ANALYZE
                SELECT melip.id FROM mercadolibre_product as melip
                INNER JOIN product_product as pp ON melip.product_id = pp.id
                WHERE pp.active IS TRUE
                AND melip.connection_account = %s
                AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
                AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
                AND melip.meli_last_status IS NULL
            """, (account.id,))
            explain_rows = self.env.cr.fetchall()
            for row in explain_rows:
                _logger.info("  %s", row[0])
        except Exception as e:
            _logger.warning("  EXPLAIN failed: %s", e)

        # 7. API LATENCY TEST - this is critical to identify slow API
        _logger.info("\n[7] TESTING MERCADOLIBRE API LATENCY...")
        api_results = {}
        try:
            company = account.company_id or self.env.user.company_id
            meli = self.env['meli.util'].get_new_instance(company, account)

            # Test 1: Simple /users/me endpoint (authentication check)
            _logger.info("  [7a] Testing /users/me (auth check)...")
            t0 = datetime.now()
            users_response = meli.get("/users/me")
            t1 = datetime.now()
            api_results['users_me'] = (t1 - t0).total_seconds()
            _logger.info("  /users/me: %.3fs - status: %s", api_results['users_me'],
                        users_response.get('id') if users_response else 'ERROR')

            # Test 2: Get first binding with meli_id to test item fetch
            first_binding = self.env['mercadolibre.product'].search([
                ('connection_account', '=', account.id),
                ('meli_id', '!=', False),
                ('meli_id', '!=', ''),
            ], limit=1)

            if first_binding:
                test_meli_id = first_binding.meli_id

                # Test 2a: GET /items/{id} (fetch item)
                _logger.info("  [7b] Testing GET /items/%s...", test_meli_id)
                t0 = datetime.now()
                item_response = meli.get(f"/items/{test_meli_id}")
                t1 = datetime.now()
                api_results['get_item'] = (t1 - t0).total_seconds()
                item_status = item_response.get('status') if item_response else 'ERROR'
                _logger.info("  GET /items: %.3fs - status: %s", api_results['get_item'], item_status)

                # Test 2b: GET /items/{id}?attributes=id,status (minimal)
                _logger.info("  [7c] Testing GET /items/%s?attributes=id,status (minimal)...", test_meli_id)
                t0 = datetime.now()
                mini_response = meli.get(f"/items/{test_meli_id}", {'attributes': 'id,status'})
                t1 = datetime.now()
                api_results['get_item_mini'] = (t1 - t0).total_seconds()
                _logger.info("  GET /items (mini): %.3fs", api_results['get_item_mini'])

                # Test 3: Simulate stock check without actual POST
                _logger.info("  [7d] Testing GET /items/%s/variations (if any)...", test_meli_id)
                t0 = datetime.now()
                variations_response = meli.get(f"/items/{test_meli_id}/variations")
                t1 = datetime.now()
                api_results['get_variations'] = (t1 - t0).total_seconds()
                var_count = len(variations_response) if isinstance(variations_response, list) else 'N/A'
                _logger.info("  GET /variations: %.3fs - count: %s", api_results['get_variations'], var_count)
            else:
                _logger.warning("  No bindings found to test item API endpoints")

        except Exception as e:
            _logger.error("  API TEST ERROR: %s", str(e))
            api_results['error'] = str(e)

        # API Latency Summary
        _logger.info("\n[7e] API LATENCY SUMMARY:")
        total_api_time = sum(v for v in api_results.values() if isinstance(v, (int, float)))
        for endpoint, duration in api_results.items():
            if isinstance(duration, (int, float)):
                status = "⚠️ SLOW" if duration > 2.0 else "✅ OK"
                _logger.info("  %s %s: %.3fs", status, endpoint, duration)
        _logger.info("  Total API test time: %.3fs", total_api_time)

        # WARN if API is slow
        slow_endpoints = [(k, v) for k, v in api_results.items() if isinstance(v, (int, float)) and v > 2.0]
        if slow_endpoints:
            _logger.warning("\n⚠️  SLOW API DETECTED! Endpoints taking >2s: %s", slow_endpoints)
            _logger.warning("This indicates MercadoLibre API is slow or network issues.")

        # 8. Summary and recommendations
        _logger.info("\n" + "=" * 60)
        _logger.info("DIAGNOSIS SUMMARY")
        _logger.info("=" * 60)
        if missing_indexes:
            _logger.info("\n⚠️  MISSING INDEXES DETECTED!")
            _logger.info("Run these SQL commands to create them:")
            for mi in missing_indexes:
                table, col = mi.split(".")
                idx_name = f"idx_{table}_{col}"
                _logger.info("  CREATE INDEX %s ON %s (%s);", idx_name, table, col)

        _logger.info("\n✅ Diagnostic complete. Check logs above for bottleneck identification.")
        _logger.info("=" * 60)

        return {
            "indexes": indexes,
            "missing_indexes": missing_indexes,
            "mp_count": mp_count,
            "pp_count": pp_count,
            "api_latency": api_results,
        }

    def create_stock_indexes(self):
        """
        Create recommended indexes for stock update queries.
        Run from shell: account.create_stock_indexes()
        """
        _logger.info("Creating recommended indexes for stock queries...")

        indexes_to_create = [
            ("idx_melip_connection_account", "mercadolibre_product", "connection_account"),
            ("idx_melip_product_id", "mercadolibre_product", "product_id"),
            ("idx_melip_stock_status", "mercadolibre_product", "meli_stock_status"),
            ("idx_melip_last_status", "mercadolibre_product", "meli_last_status"),
            ("idx_melip_meli_id", "mercadolibre_product", "meli_id"),
            # Composite index for the most common query pattern
            ("idx_melip_stock_composite", "mercadolibre_product", "connection_account, meli_stock_status, meli_last_status"),
        ]

        created = []
        for idx_name, table, columns in indexes_to_create:
            try:
                # Check if index exists
                self.env.cr.execute("""
                    SELECT 1 FROM pg_indexes WHERE indexname = %s LIMIT 1
                """, (idx_name,))
                if self.env.cr.fetchone():
                    _logger.info("  Index %s already exists, skipping", idx_name)
                    continue

                # Create the index
                sql = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} ON {table} ({columns})"
                _logger.info("  Creating: %s", sql)
                # Need to use a separate transaction for CONCURRENTLY
                self.env.cr.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({columns})")
                created.append(idx_name)
                _logger.info("  ✅ Created: %s", idx_name)
            except Exception as e:
                _logger.warning("  ❌ Failed to create %s: %s", idx_name, e)

        if created:
            _logger.info("Created %s new indexes: %s", len(created), created)
        else:
            _logger.info("No new indexes needed")

        return {"created": created}

    def test_multiget_skus(self, item_ids=None, limit=5):
        """
        Test the ML multiget API to fetch SKUs in bulk.

        Usage from shell:
            account = env['mercadolibre.account'].browse(1)
            account.test_multiget_skus()
            # or with specific IDs:
            account.test_multiget_skus(['MLA123', 'MLA456'])

        ML API: GET /items?ids=ID1,ID2,...&attributes=attr1,attr2,...
        - Max 20 IDs per request
        - Returns array of {code, body} objects
        """
        account = self
        print("=" * 60)
        print("=== TEST MULTIGET SKUs for account: %s ===" % account.name)

        company = account.company_id or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            _logger.error("Need login!")
            return meli.redirect_login()

        # Get item IDs to test
        if not item_ids:
            # Fetch some IDs from ML
            fetched = account.fetch_list_meli_ids(params={'status': 'active'})
            item_ids = fetched[:limit] if fetched else []

        if not item_ids:
            print("No item IDs to test")
            return {}

        print("Testing with %s items: %s" % (len(item_ids), item_ids))

        # Test different attribute combinations
        test_cases = [
            # Caso 1: Mínimo - solo id y title
            "id,title",
            # Caso 2: Con precio y stock
            "id,title,price,available_quantity",
            # Caso 3: Con variations (clave para SKUs)
            "id,title,variations",
            # Caso 4: Con seller_custom_field y attributes
            "id,title,seller_custom_field,attributes",
            # Caso 5: Completo - todo lo que necesitamos para SKUs
            "id,title,price,available_quantity,variations,seller_custom_field,attributes",
        ]

        results = {}
        ids_str = ",".join(item_ids)

        for attrs in test_cases:
            print("\n--- Testing attributes: %s ---" % attrs)
            try:
                url = "/items?ids=%s&attributes=%s" % (ids_str, attrs)
                print("  URL: %s" % url)

                from datetime import datetime
                t0 = datetime.now()
                response_raw = meli.get(url, {'access_token': meli.access_token})
                t1 = datetime.now()
                elapsed = (t1 - t0).total_seconds()

                print("  Response time: %.3fs" % elapsed)

                # Handle both Response object and direct dict/list
                if hasattr(response_raw, 'json'):
                    response = response_raw.json()
                else:
                    response = response_raw

                if response:
                    print("  Response type: %s" % type(response))

                    # Si es lista (array de items)
                    if isinstance(response, list):
                        print("  Got %s items in response" % len(response))
                        for idx, item in enumerate(response[:5]):  # Mostrar primeros 5
                            code = item.get('code', 'N/A')
                            body = item.get('body', {})
                            print("    [%s] code=%s" % (idx, code))
                            if body:
                                print("         id=%s" % body.get('id'))
                                print("         title=%s" % (body.get('title') or '')[:50])

                                # Buscar SKUs
                                variations = body.get('variations', [])
                                if variations:
                                    print("         variations=%s items" % len(variations))
                                    # Mostrar keys del primer variation para debug
                                    if variations:
                                        print("         variation[0] keys: %s" % list(variations[0].keys()))
                                    for vidx, var in enumerate(variations[:3]):
                                        var_sku = var.get('seller_sku') or ''
                                        var_id = var.get('id') or ''
                                        var_attrs = var.get('attributes', [])
                                        # Buscar SELLER_SKU en attributes
                                        for attr in var_attrs:
                                            if attr.get('id') == 'SELLER_SKU':
                                                var_sku = attr.get('value_name') or var_sku
                                        # También mostrar inventory_id y seller_custom_field
                                        inv_id = var.get('inventory_id') or ''
                                        scf = var.get('seller_custom_field') or ''
                                        print("           var[%s] id=%s inv='%s' scf='%s'" % (vidx, var_id, inv_id, scf))
                                else:
                                    print("         (sin variaciones)")

                                seller_custom = body.get('seller_custom_field')
                                if seller_custom:
                                    print("         seller_custom_field=%s" % seller_custom)

                                # Check attributes for SELLER_SKU
                                attributes = body.get('attributes', [])
                                for attr in attributes:
                                    if attr.get('id') == 'SELLER_SKU':
                                        print("         SELLER_SKU (attr)=%s" % attr.get('value_name'))
                    else:
                        print("  Response (not list): %s" % str(response)[:500])

                    results[attrs] = {
                        'time': elapsed,
                        'count': len(response) if isinstance(response, list) else 1,
                        'success': True
                    }
                else:
                    print("  Empty response!")
                    results[attrs] = {'success': False, 'error': 'Empty response'}

            except Exception as e:
                print("  ERROR: %s" % str(e))
                import traceback
                traceback.print_exc()
                results[attrs] = {'success': False, 'error': str(e)}

        print("\n" + "=" * 60)
        print("=== SUMMARY ===")
        for attrs, res in results.items():
            if res.get('success'):
                print("  %s: %.3fs (%s items)" % (attrs, res['time'], res['count']))
            else:
                print("  %s: FAILED - %s" % (attrs, res.get('error')))
        print("=" * 60)

        return results

    def cron_meli_stock_diagnostic(self):
        """
        Dedicated cron entry point for the stock diagnostic.
        Runs independently of the stock push cron so it cannot break it.
        Each account is wrapped in a savepoint so a SQL error in one never
        aborts the outer cron transaction or affects other accounts.
        Each account's execution is tracked as a 'stock_diagnostic' cron run
        so it shows in the account's CRONs page like the other monitored crons.
        Runs for all accounts whose company has stock posting enabled.
        Chatter logging is controlled separately by meli_cron_log_chatter on each account.
        """
        import time as _time_diag
        for account in self.env['mercadolibre.account'].sudo().search([]):
            company = account.company_id or self.env.user.company_id
            # REQUISITO #1 ("Publicar Stock"): never run the diagnostic for an account
            # whose stock posting is OFF. In meli_oerp_multiple the AUTHORITATIVE flag is the
            # per-configuration mercadolibre_cron_post_update_stock (mirrored to res.company via
            # MercadoLibreConnectionConfiguration._CRON_SYNC_FIELDS on write). With several
            # configs sharing one company the company mirror reflects whichever config was
            # written LAST, so gating on the company flag alone could let this (company-scoped)
            # diagnostic touch an account/config that has Publicar Stock OFF. Gate on BOTH the
            # company mirror AND the account's own configuration flag — same source of truth the
            # stock push itself uses (meli_update_remote_stock: config.mercadolibre_cron_post_update_stock).
            config = account.configuration or company
            if not company.mercadolibre_cron_post_update_stock:
                continue
            if not config.mercadolibre_cron_post_update_stock:
                continue

            execution = account._start_cron_execution('stock_diagnostic')
            try:
                account.env.cr.commit()
            except Exception:
                pass

            _sp = "meli_stock_diag_%d" % int(_time_diag.time())
            _diag_state = 'success'
            _diag_error = None
            try:
                self.env.cr.execute("SAVEPOINT %s" % _sp)
                company.meli_stock_diagnostic()
                try:
                    self.env.cr.execute("SELECT 1")
                    self.env.cr.execute("RELEASE SAVEPOINT %s" % _sp)
                except Exception:
                    self.env.cr.execute("ROLLBACK TO SAVEPOINT %s" % _sp)
                    self.env.cr.execute("RELEASE SAVEPOINT %s" % _sp)
                    _diag_state = 'warning'
                    _diag_error = 'tx aborted during diagnostic — rolled back'
                    _logger.warning("cron_meli_stock_diagnostic: tx aborted during diagnostic for %s — rolled back", account.name)
            except Exception as _e:
                try:
                    self.env.cr.execute("ROLLBACK TO SAVEPOINT %s" % _sp)
                    self.env.cr.execute("RELEASE SAVEPOINT %s" % _sp)
                except Exception:
                    pass
                _diag_state = 'error'
                _diag_error = str(_e)[:500]
                _logger.warning("cron_meli_stock_diagnostic: error for %s: %s", account.name, _e)

            try:
                account._end_cron_execution(execution, state=_diag_state, error_message=_diag_error)
            except Exception as _track_err:
                _logger.warning("cron_meli_stock_diagnostic: tracking _end_cron_execution failed for %s: %s",
                                account.name, _track_err)

    # ── N1 fix (ticket #425): auto re-queue of stranded RECOVERABLE stock bindings ──
    #
    # The stock cron (meli_update_remote_stock) only ever processes bindings whose
    # meli_stock_status is in ('update','update_rt', NULL). A binding that hit an error
    # once is parked in an error status, and the stock-move trigger
    # (_process_stock_update_sql_only, step 3) only re-queues HEALTHY states -> a single
    # transient failure strands the binding permanently, even as its Odoo stock keeps
    # changing. This classifies error statuses as recoverable vs terminal:
    #
    #   RECOVERABLE (auto re-queue when stale): the failure is transient or fixable by a
    #     retry — ML 5xx / KvsException, 400 validation, 409 X-Version, not_modifiable
    #     (our user-products retry can fix it), and multiwarehouse (manual-mode items the
    #     cron can push via user-products). These MUST return to the queue.
    #   TERMINAL (never auto re-queue): re-pushing cannot help — wrong seller / 403
    #     forbidden / item deleted or closed in ML / Full stock managed by ML / intentional
    #     block / variation unlinked / archived. These need human action (relink, relist,
    #     unblock) and are left in their status.
    #
    # Note: the generic 'revision_error' bucket can also hold TERMINAL failures (e.g.
    # "Item belongs to different seller", "archived", "not_found", "duplicados"), so we
    # additionally exclude those by stock_error text. A bounded retry counter
    # (meli_stock_retry_count) stops us from cycling forever on genuinely-broken items.
    _MELI_STOCK_RECOVERABLE_STATUS = ('revision_error', 'revision_not_modifiable', 'multiwarehouse')
    MELI_STOCK_MAX_REQUEUE_RETRIES = 8

    def _meli_requeue_stranded_stock(self):
        """Re-queue stranded RECOVERABLE bindings for this account (N1, ticket #425).

        Runs once per stock cron cycle (called from meli_update_remote_stock, before the
        UNION query, so re-queued items are picked up the same cycle). Staleness uses the
        same criterion as the classifier: meli_stock_moves_update > stock_update. Terminal
        statuses and terminal stock_error signatures are excluded; a per-binding retry
        counter caps how many times an item is auto re-queued.
        """
        account = self
        self.env.cr.execute("""
            UPDATE mercadolibre_product mp
            SET meli_stock_status = 'update',
                meli_stock_retry_count = COALESCE(mp.meli_stock_retry_count, 0) + 1
            FROM product_product pp
            WHERE mp.product_id = pp.id
              AND pp.active IS TRUE
              AND mp.connection_account = %s
              AND mp.meli_id IS NOT NULL AND mp.meli_id != ''
              AND mp.meli_stock_status IN %s
              AND (mp.meli_last_status IS NULL OR mp.meli_last_status IN ('active', 'paused'))
              AND mp.meli_stock_moves_update IS NOT NULL
              AND (mp.stock_update IS NULL OR mp.meli_stock_moves_update > mp.stock_update)
              AND COALESCE(mp.meli_stock_retry_count, 0) < %s
              AND (mp.stock_error IS NULL OR (
                       mp.stock_error NOT ILIKE '%%different seller%%'
                   AND mp.stock_error NOT ILIKE '%%forbidden%%'
                   AND mp.stock_error NOT ILIKE '%%archived%%'
                   AND mp.stock_error NOT ILIKE '%%not_found%%'
                   AND mp.stock_error NOT ILIKE '%%not found%%'
                   AND mp.stock_error NOT ILIKE '%%duplicad%%'
              ))
        """, (account.id, self._MELI_STOCK_RECOVERABLE_STATUS, self.MELI_STOCK_MAX_REQUEUE_RETRIES))
        n = self.env.cr.rowcount
        if n:
            self.env['mercadolibre.product'].invalidate_model(['meli_stock_status', 'meli_stock_retry_count'])
            _logger.info("CRON [stock] N1 re-queue: %d stranded recoverable bindings reset to 'update' for %s", n, account.name)
        return n

    def meli_update_remote_stock(self, meli=False):
        """
        OPTIMIZED version:
        - Uses single UNION ALL query instead of 3 separate SQL queries
        - Batch browse() for all bindings at once instead of individual browse() in loop
        - Uses list append + join instead of string concatenation for logs/errors
        - Optional detailed chatter logging when meli_cron_log_chatter is enabled
        """
        from odoo.addons.meli_oerp.models.meli_util import MeliApi
        from odoo.addons.meli_oerp_stock.models.product import product_product

        account = self
        started_at = datetime.now()
        topcommits = ("meli_cron_stock_top_commit" in account._fields and account.meli_cron_stock_top_commit) or 40
        _logger.info('CRON account.meli_update_remote_stock() STARTED '+str(account.name) + " " +str( started_at ) + " TOPCOMMIT: " +str(topcommits) )
        company = account.company_id or self.env.user.company_id
        config = account.configuration or company
        notilog = True
        chatter_log = account.meli_cron_log_chatter

        # Check if we should execute based on configured minutes
        if account.meli_cron_stock_minutes:
            current_minute = started_at.minute
            allowed_minutes = [int(m.strip()) for m in account.meli_cron_stock_minutes.split(',') if m.strip().isdigit()]
            if allowed_minutes and current_minute not in allowed_minutes:
                _logger.info('CRON account.meli_update_remote_stock() SKIPPED - minute %d not in allowed minutes %s', current_minute, allowed_minutes)
                return {}

        # Enable API benchmark if chatter_log is enabled (diagnostic mode)
        benchmark_enabled = chatter_log and hasattr(MeliApi, 'enable_benchmark')
        if benchmark_enabled:
            MeliApi.enable_benchmark(True, slow_threshold=2.0)
            # Clear logistic type cache if method exists (optional diagnostic feature)
            if hasattr(product_product, '_clear_logistic_type_cache'):
                product_product._clear_logistic_type_cache()

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )

        if not config.mercadolibre_cron_post_update_stock:
            return {}

        auto_commit = not getattr(threading.current_thread(), 'testing', False)

        # N1 fix (ticket #425): re-queue stranded RECOVERABLE bindings before building the
        # queue, so a transient failure no longer strands an item forever. Bounded by a
        # retry counter; terminal statuses/errors are excluded. Never break the cron.
        try:
            account._meli_requeue_stranded_stock()
            if auto_commit:
                MeliCommit(self)
        except Exception as _rq_err:
            _logger.warning("CRON [stock] N1 re-queue failed for %s: %s", account.name, _rq_err)
            if auto_commit:
                try:
                    self.env.cr.rollback()
                except Exception:
                    pass

        # TIMING: Track each step to identify bottleneck
        step_times = {}
        step_start = datetime.now()

        # Query to get counts by status for the plan log
        if chatter_log:
            # Count by meli_stock_status
            count_query = """
                SELECT
                    COALESCE(meli_stock_status, 'NULL') as status,
                    COUNT(*) as cnt
                FROM mercadolibre_product as melip
                INNER JOIN product_product as pp ON melip.product_id = pp.id
                WHERE pp.active IS TRUE
                AND melip.connection_account = %s
                AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
                GROUP BY meli_stock_status
                ORDER BY cnt DESC
            """
            self.env.cr.execute(count_query, (account.id,))
            stock_status_counts = self.env.cr.fetchall()
            step_times['count_query'] = (datetime.now() - step_start).total_seconds()
            step_start = datetime.now()

            # Count by meli_last_status (stored ML status)
            last_status_query = """
                SELECT
                    COALESCE(meli_last_status, 'NULL') as status,
                    COUNT(*) as cnt
                FROM mercadolibre_product as melip
                INNER JOIN product_product as pp ON melip.product_id = pp.id
                WHERE pp.active IS TRUE
                AND melip.connection_account = %s
                AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
                GROUP BY meli_last_status
                ORDER BY cnt DESC
            """
            self.env.cr.execute(last_status_query, (account.id,))
            last_status_counts = self.env.cr.fetchall()
            step_times['last_status_query'] = (datetime.now() - step_start).total_seconds()
            step_start = datetime.now()

        # OPTIMIZED: Single UNION ALL query instead of 3 separate queries
        # Priority order: 1) NULL status (to determine), 2) Active, 3) Non-active (lowest)
        query = """
            SELECT melip.id, 1 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status IS NULL

            UNION ALL

            SELECT melip.id, 2 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status = 'active'

            UNION ALL

            SELECT melip.id, 3 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update' OR melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status IS NOT NULL
            AND melip.meli_last_status != 'active'

            ORDER BY priority ASC
        """
        step_start = datetime.now()
        cr = MeliCr( self )
        cr.execute(query, (account.id, account.id, account.id))
        results = cr.fetchall()
        step_times['union_query'] = (datetime.now() - step_start).total_seconds()
        step_start = datetime.now()

        # FIXED: Use IDs directly instead of batch browse() to avoid ORM cache accumulation
        # The batch browse() was causing serialization failures when commit() tries to write
        # accumulated changes from all browsed records at once. Now we browse one at a time.
        bind_ids = [r[0] for r in results]
        bind_priorities = {r[0]: r[1] for r in results}  # Store priorities for logging
        # Do NOT browse all at once - this causes ORM to cache all records and accumulate writes
        step_times['ids_extract'] = (datetime.now() - step_start).total_seconds()
        step_start = datetime.now()

        icommit = 0
        icount = 0
        maxcommits = len(bind_ids)
        will_process = min(topcommits, maxcommits)

        # Always log diagnostic info
        diag_query = """
            SELECT
                COALESCE(meli_stock_status, 'NULL') as ss,
                COALESCE(meli_last_status, 'NULL') as ls,
                COUNT(*) as cnt
            FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            GROUP BY meli_stock_status, meli_last_status
            ORDER BY cnt DESC
            LIMIT 10
        """
        self.env.cr.execute(diag_query, (account.id,))
        diag_results = self.env.cr.fetchall()
        step_times['diag_query'] = (datetime.now() - step_start).total_seconds()

        # LOG ALL STEP TIMES - this helps identify which query is slow
        total_query_time = sum(step_times.values())
        _logger.info("CRON TIMING: %s - Total query time: %.3fs | Details: %s",
                     account.name, total_query_time,
                     " | ".join([f"{k}: {v:.3f}s" for k, v in step_times.items()]))
        _logger.info("CRON DIAG: found %s items to process. Status distribution: %s", maxcommits, diag_results)

        # WARN if any query took too long
        slow_queries = [(k, v) for k, v in step_times.items() if v > 1.0]
        if slow_queries:
            _logger.warning("CRON SLOW QUERIES DETECTED: %s", slow_queries)

        # Log plan to chatter if enabled
        if chatter_log:
            stock_summary = " | ".join([f"{s}: {c}" for s, c in stock_status_counts[:6]])
            last_summary = " | ".join([f"{s}: {c}" for s, c in last_status_counts[:6]])

            # Show first 10 items that will be processed with their priorities
            # Use raw SQL to get preview data without loading full ORM objects
            items_preview = []
            preview_ids = bind_ids[:10]
            if preview_ids:
                preview_query = """
                    SELECT id, sku, meli_stock_status, meli_last_status
                    FROM mercadolibre_product
                    WHERE id = ANY(%s)
                """
                self.env.cr.execute(preview_query, (preview_ids,))
                preview_data = {r[0]: r for r in self.env.cr.fetchall()}
                for bind_id in preview_ids:
                    if bind_id in preview_data:
                        _, sku, ss, ls = preview_data[bind_id]
                        priority = bind_priorities.get(bind_id, '?')
                        items_preview.append(f"P{priority}: {sku} [{ss or 'NULL'}|{ls or 'NULL'}]")
            items_str = "<br/>".join(items_preview) if items_preview else "ninguno"

            plan_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #f8f9fa; padding: 10px; border-radius: 5px;">
<b>🚀 CRON Stock INICIADO</b> - {started_at.strftime('%H:%M:%S')}<br/>
<b>Plan:</b> {will_process}/{maxcommits} (límite: {topcommits})<br/>
<b>meli_stock_status:</b> {stock_summary}<br/>
<b>meli_last_status:</b> {last_summary}<br/>
<b>Primeros items:</b><br/>{items_str}
</div>"""
            account.message_post(body=Markup(plan_msg), subtype_xmlid='mail.mt_note')

        internals = {
            "application_id": account.client_id,
            "user_id": account.seller_id,
            "topic": "internal",
            "resource": "meli_update_remote_stock #"+str(maxcommits),
            "state": "PROCESSING"
        }
        noti = False
        if notilog:
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals=internals, account=account )

        # OPTIMIZED: Use lists instead of string concatenation
        logs_list = []
        errors_list = []
        processed_count = 0
        error_count = 0
        slow_abort = False  # Flag to track if we aborted due to slow POST
        slow_skips = 0  # ticket #425: slow items skipped (a slow item no longer aborts the run)
        slow_abort_item = None
        slow_abort_duration = 0
        # Use configurable timeout from account settings (default: 10 seconds)
        post_timeout_threshold = account.meli_cron_stock_timeout if account.meli_cron_stock_timeout > 0 else 10.0

        _logger.info("CRON [stock] READY TO PROCESS %d items (limit: %d). Starting loop...", will_process, topcommits)

        # For slow_abort tracking we need to store SKU/meli_id separately since we invalidate cache
        slow_abort_sku = None
        slow_abort_meli_id = None

        try:
            if auto_commit:
                MeliCommit( self )

            # FIXED: Iterate over IDs, not pre-browsed objects
            # Browse one at a time and invalidate cache after each to prevent ORM accumulation
            for bind_id in bind_ids:
                if icount >= topcommits:
                    break

                # Browse single record - this loads only ONE record into ORM cache
                obj = self.env['mercadolibre.product'].browse(bind_id)

                if obj and obj.exists() and obj.meli_id:
                    icommit += 1
                    icount += 1
                    item_start = datetime.now()

                    # Store identifiers BEFORE any operation in case we need them for abort message
                    current_sku = obj.sku
                    current_meli_id = obj.meli_id
                    current_ss = obj.meli_stock_status or 'NULL'
                    current_ls = obj.meli_last_status or 'NULL'

                    # LOG BEFORE STARTING - critical to know where we're stuck if API hangs
                    _logger.info("CRON [stock] ITEM [%d/%d] >>> STARTING: %s (%s) ss=%s ls=%s",
                                 icount, will_process, current_sku, current_meli_id,
                                 current_ss, current_ls)

                    try:
                        resjson = obj.product_post_stock(meli=meli)
                        item_duration = (datetime.now() - item_start).total_seconds()
                        avail_qty = obj.meli_available_quantity
                        _logger.info("CRON [stock] ITEM [%d/%d] <<< COMPLETED: %s in %.2fs", icount, will_process, current_sku, item_duration)
                        logs_list.append(f"{current_sku} {current_meli_id}: {avail_qty} ({item_duration:.2f}s)")
                        processed_count += 1
                        if resjson and "error" in resjson:
                            errors_list.append(f"{current_sku} {current_meli_id} >> {resjson}")
                            error_count += 1

                        # Slow-abort fix (ticket #425): a single slow POST no longer aborts
                        # the whole run. The item already succeeded here, so persist progress
                        # (commit-every-5 honoured by committing now) and skip to the next one.
                        if item_duration > post_timeout_threshold:
                            _logger.warning("CRON SLOW POST DETECTED: %s took %.2fs > %.1fs threshold. Skipping item, continuing run.", current_sku, item_duration, post_timeout_threshold)
                            slow_skips += 1
                            slow_abort_sku = current_sku
                            slow_abort_meli_id = current_meli_id
                            slow_abort_duration = item_duration
                            icommit = 0
                            if auto_commit:
                                MeliCommit( self )
                                self.env.invalidate_all()
                            continue

                        # Commit every 5 items (more frequent than before) to reduce accumulation
                        if icommit >= 5 or icount == maxcommits or icount == topcommits:
                            if noti:
                                noti.processing_errors = "\n".join(errors_list)
                                noti.processing_logs = "\n".join(logs_list)
                                noti.resource = "meli_update_remote_stock #"+str(icount) +'/'+str(maxcommits)
                            icommit = 0
                            if auto_commit:
                                MeliCommit( self )
                                # CRITICAL: Invalidate ORM cache after commit to release memory
                                # and prevent accumulation of pending writes
                                self.env.invalidate_all()

                    except Exception as e:
                        item_duration = (datetime.now() - item_start).total_seconds()
                        logs_list.append(f"{current_sku} {current_meli_id}: ERROR ({item_duration:.2f}s)")
                        errors_list.append(f"{current_sku} {current_meli_id} >> {e}")
                        error_count += 1
                        # Slow-abort fix (ticket #425): a slow errored POST no longer aborts
                        # the whole run. Roll back this item's partial work (recovering the
                        # cursor if the error aborted the tx) and skip to the next one.
                        if item_duration > post_timeout_threshold:
                            _logger.warning("CRON SLOW POST (with error) DETECTED: %s took %.2fs. Skipping item, continuing run.", current_sku, item_duration)
                            slow_skips += 1
                            slow_abort_sku = current_sku
                            slow_abort_meli_id = current_meli_id
                            slow_abort_duration = item_duration
                            if auto_commit:
                                self.env.cr.rollback()
                                self.env.invalidate_all()
                            continue
                        if auto_commit:
                            self.env.cr.rollback()
                            self.env.invalidate_all()  # Invalidate after rollback too

            if notilog and noti:
                noti.resource = "meli_update_remote_stock #"+str(icount) +'/'+str(maxcommits)
                noti.stop_internal_notification(errors="\n".join(errors_list), logs="\n".join(logs_list))

        except Exception as e:
            if auto_commit:
                self.env.cr.rollback()
            if notilog and noti:
                noti.stop_internal_notification(errors="\n".join(errors_list), logs="\n".join(logs_list))
            if auto_commit:
                MeliCommit( self )

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()
        _logger.info('CRON account.meli_update_remote_stock() ENDED '+str(account.name) + " FROM "+str( started_at ) + " TO " +str( ended_at ) + " TOPCOMMIT: " +str(topcommits) + (" ABORTED:SLOW" if slow_abort else "") )

        # Log to chatter - informational note if some items were slow-skipped (ticket #425:
        # a slow item no longer aborts the run; it is skipped and the run continues).
        if slow_skips and chatter_log:
            slow_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #fff3cd; padding: 10px; border-radius: 5px; border: 1px solid #ffeeba;">
<b>⚠️ CRON Stock FIN (con items lentos salteados)</b> - {ended_at.strftime('%H:%M:%S')} ({duration:.1f}s)<br/>
<b>Items lentos salteados:</b> {slow_skips} (último: {slow_abort_sku} / {slow_abort_meli_id}, {slow_abort_duration:.2f}s > {post_timeout_threshold:.1f}s)<br/>
<b>Procesados:</b> {processed_count} OK, {error_count} errores<br/>
<br/>
<i>Los items lentos se saltearon y la corrida continuó. Los que sigan pendientes se retoman en el próximo ciclo del cron.</i>
</div>"""
            account.message_post(body=Markup(slow_msg), subtype_xmlid='mail.mt_note')
        elif chatter_log:
            # Normal summary - only when chatter_log enabled
            avg_time = f"{(duration/processed_count):.2f}s" if processed_count > 0 else "N/A"
            status_icon = "✅" if error_count == 0 else "⚠️"

            # Build error summary grouped by error type
            error_summary = ""
            if errors_list:
                # Count errors by type
                error_types = {}
                for err in errors_list:
                    err_lower = err.lower()
                    if 'fulfillment' in err_lower:
                        error_types['fulfillment'] = error_types.get('fulfillment', 0) + 1
                    elif 'not_found' in err_lower or '404' in err_lower:
                        error_types['not_found'] = error_types.get('not_found', 0) + 1
                    elif 'status:closed' in err_lower or 'status:inactive' in err_lower:
                        error_types['closed'] = error_types.get('closed', 0) + 1
                    elif 'under_review' in err_lower:
                        error_types['under_review'] = error_types.get('under_review', 0) + 1
                    elif 'not modifiable' in err_lower or 'not_modifiable' in err_lower or 'field_not_updatable' in err_lower:
                        error_types['not_modifiable'] = error_types.get('not_modifiable', 0) + 1
                    elif 'blocked' in err_lower:
                        error_types['blocked'] = error_types.get('blocked', 0) + 1
                    elif 'archived' in err_lower:
                        error_types['archived'] = error_types.get('archived', 0) + 1
                    elif 'seller_sku' in err_lower or 'different seller_sku' in err_lower:
                        error_types['sku_mismatch'] = error_types.get('sku_mismatch', 0) + 1
                    elif 'forbidden' in err_lower or '403' in err_lower:
                        error_types['forbidden'] = error_types.get('forbidden', 0) + 1
                    elif 'verificar publicacion' in err_lower or 'no recomendamos' in err_lower:
                        error_types['verificar'] = error_types.get('verificar', 0) + 1
                    else:
                        error_types['otros'] = error_types.get('otros', 0) + 1

                error_breakdown = " | ".join([f"{k}: {v}" for k, v in sorted(error_types.items(), key=lambda x: -x[1])])
                error_summary = f"<br/><b>Tipos:</b> {error_breakdown}"

            # Items actualizados
            items_summary = ""
            if logs_list:
                items_detail = "<br/>".join(logs_list[:20])
                if len(logs_list) > 20:
                    items_detail += f"<br/>... y {len(logs_list) - 20} más"
                items_summary = f"<br/><b>Publicaciones actualizadas ({processed_count}):</b><br/>{items_detail}"

            summary_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #f8f9fa; padding: 10px; border-radius: 5px;">
<b>{status_icon} CRON Stock FIN</b> - {ended_at.strftime('%H:%M:%S')} ({duration:.1f}s)<br/>
<b>Resultado:</b> {processed_count} OK, {error_count} errores | Prom: {avg_time}{items_summary}{error_summary}
</div>"""
            account.message_post(body=Markup(summary_msg), subtype_xmlid='mail.mt_note')

        # Update timing statistics — skip when transaction is aborted (slow_abort)
        if processed_count > 0 and not slow_abort:
            current_avg = duration / processed_count
            stats_update = {
                'meli_cron_stock_last_avg': current_avg,
                'meli_cron_stock_last_duration': duration,
            }

            # Update avg min/max
            if account.meli_cron_stock_avg_min == 0 or current_avg < account.meli_cron_stock_avg_min:
                stats_update['meli_cron_stock_avg_min'] = current_avg

            # Update max if current is higher or max is not set (0)
            if account.meli_cron_stock_avg_max == 0 or current_avg > account.meli_cron_stock_avg_max:
                stats_update['meli_cron_stock_avg_max'] = current_avg

            # Update duration min/max
            if account.meli_cron_stock_duration_min == 0 or duration < account.meli_cron_stock_duration_min:
                stats_update['meli_cron_stock_duration_min'] = duration
            if account.meli_cron_stock_duration_max == 0 or duration > account.meli_cron_stock_duration_max:
                stats_update['meli_cron_stock_duration_max'] = duration

            account.write(stats_update)

        if slow_abort:
            # Transaction is already aborted due to serialization error.
            # flush_all() inside MeliCommit would cascade-fail. Invalidate ORM cache
            # to drop pending dirty records and rollback so the cron returns cleanly.
            try:
                self.env.invalidate_all()
                self.env.cr.rollback()
            except Exception:
                pass
        elif auto_commit:
            MeliCommit(self)

        # Log and disable benchmark if it was enabled
        if benchmark_enabled:
            if hasattr(MeliApi, 'log_benchmark_stats'):
                MeliApi.log_benchmark_stats()
            # Clear logistic type cache if method exists (optional diagnostic feature)
            if hasattr(product_product, '_clear_logistic_type_cache'):
                product_product._clear_logistic_type_cache()
            if hasattr(MeliApi, 'enable_benchmark'):
                MeliApi.enable_benchmark(False)

        # Auto-diagnostic removed from stock cron — runs in its own dedicated cron
        # (ir_cron_meli_stock_diagnostic) to keep the stock cron fast and stable.

        return {}

    def meli_update_remote_stock_rt(self, meli=False):
        """
        OPTIMIZED real-time stock update version:
        - Uses single UNION ALL query instead of 3 separate SQL queries
        - Batch browse() for all bindings at once instead of individual browse() in loop
        - Uses list append + join instead of string concatenation for logs/errors
        - Prioritizes update_rt status bindings first
        - Optional detailed chatter logging when meli_cron_log_chatter is enabled
        """
        account = self
        started_at = datetime.now()
        topcommits = ("meli_cron_stock_top_commit" in account._fields and account.meli_cron_stock_top_commit) or 40
        _logger.info('CRON account.meli_update_remote_stock_rt() STARTED '+str(account.name) + " " +str( started_at ) + " TOPCOMMIT: " +str(topcommits) )
        company = account.company_id or self.env.user.company_id
        config = account.configuration or company
        notilog = True
        chatter_log = account.meli_cron_log_chatter

        # Check if we should execute based on configured minutes
        if account.meli_cron_stock_minutes:
            current_minute = started_at.minute
            allowed_minutes = [int(m.strip()) for m in account.meli_cron_stock_minutes.split(',') if m.strip().isdigit()]
            if allowed_minutes and current_minute not in allowed_minutes:
                _logger.info('CRON account.meli_update_remote_stock_rt() SKIPPED - minute %d not in allowed minutes %s', current_minute, allowed_minutes)
                return {}

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )

        if not config.mercadolibre_cron_post_update_stock:
            return {}

        auto_commit = not getattr(threading.current_thread(), 'testing', False)

        # Query to get counts by status for the plan log
        if chatter_log:
            count_query = """
                SELECT
                    COALESCE(meli_stock_status, 'NULL') as status,
                    COUNT(*) as cnt
                FROM mercadolibre_product as melip
                INNER JOIN product_product as pp ON melip.product_id = pp.id
                WHERE pp.active IS TRUE
                AND melip.connection_account = %s
                AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
                GROUP BY meli_stock_status
                ORDER BY cnt DESC
            """
            self.env.cr.execute(count_query, (account.id,))
            status_counts = self.env.cr.fetchall()

        # OPTIMIZED: Single UNION ALL query instead of 3 separate queries
        # Priority order: 1) NULL status (to determine), 2) Active, 3) Non-active (lowest)
        query = """
            SELECT melip.id, 1 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status IS NULL

            UNION ALL

            SELECT melip.id, 2 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status = 'active'

            UNION ALL

            SELECT melip.id, 3 as priority FROM mercadolibre_product as melip
            INNER JOIN product_product as pp ON melip.product_id = pp.id
            WHERE pp.active IS TRUE
            AND melip.connection_account = %s
            AND melip.meli_id != '' AND melip.meli_id IS NOT NULL
            AND (melip.meli_stock_status = 'update_rt' OR melip.meli_stock_status IS NULL)
            AND melip.meli_last_status IS NOT NULL
            AND melip.meli_last_status != 'active'

            ORDER BY priority ASC
        """
        cr = MeliCr( self )
        cr.execute(query, (account.id, account.id, account.id))
        results = cr.fetchall()

        # FIXED: Use IDs directly instead of batch browse() to avoid ORM cache accumulation
        bind_ids = [r[0] for r in results]
        # Do NOT browse all at once - this causes ORM to cache all records and accumulate writes

        icommit = 0
        icount = 0
        maxcommits = len(bind_ids)
        will_process = min(topcommits, maxcommits)

        # Log plan to chatter if enabled
        if chatter_log:
            status_summary = " | ".join([f"{s}: {c}" for s, c in status_counts[:5]])  # Top 5 statuses
            plan_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #fff3cd; padding: 10px; border-radius: 5px;">
<b>🚀 CRON Stock RT INICIADO</b> - {started_at.strftime('%H:%M:%S')}<br/>
<b>Plan:</b> {will_process}/{maxcommits} (límite: {topcommits})<br/>
<b>Status:</b> {status_summary}
</div>"""
            account.message_post(body=Markup(plan_msg), subtype_xmlid='mail.mt_note')

        internals = {
            "application_id": account.client_id,
            "user_id": account.seller_id,
            "topic": "internal",
            "resource": "meli_update_remote_stock_rt #"+str(maxcommits),
            "state": "PROCESSING"
        }
        noti = False
        if notilog:
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals=internals, account=account )

        # OPTIMIZED: Use lists instead of string concatenation
        logs_list = []
        errors_list = []
        processed_count = 0
        error_count = 0
        slow_abort = False  # Flag to track if we aborted due to slow POST
        slow_abort_item = None
        slow_abort_duration = 0
        # Use configurable timeout from account settings (default: 10 seconds)
        post_timeout_threshold = account.meli_cron_stock_timeout if account.meli_cron_stock_timeout > 0 else 10.0

        _logger.info("CRON [stock_rt] READY TO PROCESS %d items (limit: %d). Starting loop...", will_process, topcommits)

        # For slow_abort tracking we need to store SKU/meli_id separately since we invalidate cache
        slow_abort_sku = None
        slow_abort_meli_id = None

        try:
            if auto_commit:
                MeliCommit( self )

            # FIXED: Iterate over IDs, not pre-browsed objects
            for bind_id in bind_ids:
                if icount >= topcommits:
                    break

                # Browse single record - this loads only ONE record into ORM cache
                obj = self.env['mercadolibre.product'].browse(bind_id)

                if obj and obj.exists() and obj.meli_id:
                    icommit += 1
                    icount += 1
                    item_start = datetime.now()

                    # Store identifiers BEFORE any operation
                    current_sku = obj.sku
                    current_meli_id = obj.meli_id
                    current_ss = obj.meli_stock_status or 'NULL'
                    current_ls = obj.meli_last_status or 'NULL'

                    # LOG BEFORE STARTING - critical to know where we're stuck if API hangs
                    _logger.info("CRON [stock_rt] ITEM [%d/%d] >>> STARTING: %s (%s) ss=%s ls=%s",
                                 icount, will_process, current_sku, current_meli_id,
                                 current_ss, current_ls)

                    try:
                        resjson = obj.product_post_stock(meli=meli)
                        item_duration = (datetime.now() - item_start).total_seconds()
                        avail_qty = obj.meli_available_quantity
                        _logger.info("CRON [stock_rt] ITEM [%d/%d] <<< COMPLETED: %s in %.2fs", icount, will_process, current_sku, item_duration)
                        logs_list.append(f"{current_sku} {current_meli_id}: {avail_qty} ({item_duration:.2f}s)")
                        processed_count += 1
                        if resjson and "error" in resjson and not resjson.get("not_modifiable"):
                            errors_list.append(f"{current_sku} {current_meli_id} >> {resjson}")
                            error_count += 1

                        # CHECK: If POST took too long, abort CRON immediately
                        if item_duration > post_timeout_threshold:
                            _logger.warning("CRON RT SLOW POST DETECTED: %s took %.2fs > %.1fs threshold. Aborting.", current_sku, item_duration, post_timeout_threshold)
                            slow_abort = True
                            slow_abort_sku = current_sku
                            slow_abort_meli_id = current_meli_id
                            slow_abort_duration = item_duration
                            break  # Exit the loop immediately

                        # Commit every 5 items (more frequent) to reduce accumulation
                        if icommit >= 5 or icount == maxcommits or icount == topcommits:
                            if noti:
                                noti.processing_errors = "\n".join(errors_list)
                                noti.processing_logs = "\n".join(logs_list)
                                noti.resource = "meli_update_remote_stock_rt #"+str(icount) +'/'+str(maxcommits)
                            icommit = 0
                            if auto_commit:
                                MeliCommit( self )
                                # CRITICAL: Invalidate ORM cache after commit
                                self.env.invalidate_all()

                    except Exception as e:
                        item_duration = (datetime.now() - item_start).total_seconds()
                        logs_list.append(f"{current_sku} {current_meli_id}: ERROR ({item_duration:.2f}s)")
                        errors_list.append(f"{current_sku} {current_meli_id} >> {e}")
                        error_count += 1
                        # CHECK: If exception took too long, also abort
                        if item_duration > post_timeout_threshold:
                            _logger.warning("CRON RT SLOW POST (with error) DETECTED: %s took %.2fs. Aborting.", current_sku, item_duration)
                            slow_abort = True
                            slow_abort_sku = current_sku
                            slow_abort_meli_id = current_meli_id
                            slow_abort_duration = item_duration
                            break
                        if auto_commit:
                            self.env.cr.rollback()
                            self.env.invalidate_all()

            if notilog and noti:
                noti.resource = "meli_update_remote_stock_rt #"+str(icount) +'/'+str(maxcommits)
                noti.stop_internal_notification(errors="\n".join(errors_list), logs="\n".join(logs_list))

        except Exception as e:
            if auto_commit:
                self.env.cr.rollback()
            if notilog and noti:
                noti.stop_internal_notification(errors="\n".join(errors_list), logs="\n".join(logs_list))
            if auto_commit:
                MeliCommit( self )

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()
        _logger.info('CRON account.meli_update_remote_stock_rt() ENDED '+str(account.name) + " FROM "+str( started_at ) + " TO " +str( ended_at ) + " TOPCOMMIT: " +str(topcommits) + (" ABORTED:SLOW" if slow_abort else "") )

        # Log to chatter - different message if aborted due to slow POST
        if slow_abort:
            # ABORT message - always log, not just when chatter_log enabled
            remaining = maxcommits - processed_count
            abort_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #f8d7da; padding: 10px; border-radius: 5px; border: 1px solid #f5c6cb;">
<b>⚠️ CRON Stock RT ABORTADO</b> - {ended_at.strftime('%H:%M:%S')} ({duration:.1f}s)<br/>
<b>Motivo:</b> POST lento detectado - sistema/API sobrecargado<br/>
<b>Item lento:</b> {slow_abort_sku} ({slow_abort_meli_id})<br/>
<b>Tiempo POST:</b> {slow_abort_duration:.2f}s (límite: {post_timeout_threshold:.1f}s)<br/>
<b>Procesados:</b> {processed_count} OK, {error_count} errores<br/>
<b>Pendientes:</b> {remaining} items sin procesar<br/>
<br/>
<i>El CRON se abortó para evitar timeout de Odoo.sh. Verificar estado del sistema/API de MercadoLibre.</i>
</div>"""
            try:
                with self.env.registry.cursor() as _abort_cr:
                    _abort_env = self.env(cr=_abort_cr)
                    _abort_env['mercadolibre.account'].browse(account.id).message_post(
                        body=Markup(abort_msg), subtype_xmlid='mail.mt_note'
                    )
                    _abort_cr.commit()
            except Exception as _abort_chatter_err:
                _logger.warning("CRON: could not post abort chatter: %s", _abort_chatter_err)
        elif chatter_log:
            # Normal summary - only when chatter_log enabled
            avg_time = f"{(duration/processed_count):.2f}s" if processed_count > 0 else "N/A"
            status_icon = "✅" if error_count == 0 else "⚠️"

            # Build error summary grouped by error type
            error_summary = ""
            if errors_list:
                error_types = {}
                for err in errors_list:
                    err_lower = err.lower()
                    if 'fulfillment' in err_lower:
                        error_types['fulfillment'] = error_types.get('fulfillment', 0) + 1
                    elif 'not_found' in err_lower or '404' in err_lower:
                        error_types['not_found'] = error_types.get('not_found', 0) + 1
                    elif 'status:closed' in err_lower or 'status:inactive' in err_lower:
                        error_types['closed'] = error_types.get('closed', 0) + 1
                    elif 'under_review' in err_lower:
                        error_types['under_review'] = error_types.get('under_review', 0) + 1
                    elif 'not modifiable' in err_lower or 'not_modifiable' in err_lower or 'field_not_updatable' in err_lower:
                        error_types['not_modifiable'] = error_types.get('not_modifiable', 0) + 1
                    elif 'blocked' in err_lower:
                        error_types['blocked'] = error_types.get('blocked', 0) + 1
                    elif 'archived' in err_lower:
                        error_types['archived'] = error_types.get('archived', 0) + 1
                    elif 'seller_sku' in err_lower or 'different seller_sku' in err_lower:
                        error_types['sku_mismatch'] = error_types.get('sku_mismatch', 0) + 1
                    elif 'forbidden' in err_lower or '403' in err_lower:
                        error_types['forbidden'] = error_types.get('forbidden', 0) + 1
                    elif 'verificar publicacion' in err_lower or 'no recomendamos' in err_lower:
                        error_types['verificar'] = error_types.get('verificar', 0) + 1
                    else:
                        error_types['otros'] = error_types.get('otros', 0) + 1

                error_breakdown = " | ".join([f"{k}: {v}" for k, v in sorted(error_types.items(), key=lambda x: -x[1])])
                error_summary = f"<br/><b>Tipos:</b> {error_breakdown}"

            # Items actualizados
            items_summary = ""
            if logs_list:
                items_detail = "<br/>".join(logs_list[:20])
                if len(logs_list) > 20:
                    items_detail += f"<br/>... y {len(logs_list) - 20} más"
                items_summary = f"<br/><b>Publicaciones actualizadas ({processed_count}):</b><br/>{items_detail}"

            summary_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #fff3cd; padding: 10px; border-radius: 5px;">
<b>{status_icon} CRON Stock RT FIN</b> - {ended_at.strftime('%H:%M:%S')} ({duration:.1f}s)<br/>
<b>Resultado:</b> {processed_count} OK, {error_count} errores | Prom: {avg_time}{items_summary}{error_summary}
</div>"""
            account.message_post(body=Markup(summary_msg), subtype_xmlid='mail.mt_note')

        # Update timing statistics — skip when transaction is aborted (slow_abort)
        if processed_count > 0 and not slow_abort:
            current_avg = duration / processed_count
            stats_update = {
                'meli_cron_stock_last_avg': current_avg,
                'meli_cron_stock_last_duration': duration,
            }

            # Update avg min/max
            if account.meli_cron_stock_avg_min == 0 or current_avg < account.meli_cron_stock_avg_min:
                stats_update['meli_cron_stock_avg_min'] = current_avg

            # Update max if current is higher or max is not set (0)
            if account.meli_cron_stock_avg_max == 0 or current_avg > account.meli_cron_stock_avg_max:
                stats_update['meli_cron_stock_avg_max'] = current_avg

            # Update duration min/max
            if account.meli_cron_stock_duration_min == 0 or duration < account.meli_cron_stock_duration_min:
                stats_update['meli_cron_stock_duration_min'] = duration
            if account.meli_cron_stock_duration_max == 0 or duration > account.meli_cron_stock_duration_max:
                stats_update['meli_cron_stock_duration_max'] = duration

            account.write(stats_update)

        if slow_abort:
            try:
                self.env.invalidate_all()
                self.env.cr.rollback()
            except Exception:
                pass
        elif auto_commit:
            MeliCommit(self)

        return {}


    def meli_update_remote_stock_injobs(self, meli=False, notification=None):
        account = self
        #_logger.info('account.meli_update_remote_stock_injobs() '+str(account.name))
        company = account.company_id or self.env.user.company_id
        config = account.configuration or company

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )
            #if meli.need_login():
            #    return meli.redirect_login()

        noti_ids = (notification and [('id','=',notification.id)] ) or []
        #_logger.info('account.meli_update_remote_stock_injobs() mercadolibre_cron_post_update_stock: '+str(config.mercadolibre_cron_post_update_stock)+" noti_ids: "+str(noti_ids))
        if (config.mercadolibre_cron_post_update_stock):
            auto_commit = not getattr(threading.current_thread(), 'testing', False)

            icommit = 0
            icount = 0
            notifs = self.env["mercadolibre.notification"].search( noti_ids + [('topic','=','internal_job'),
                                                                ('resource','like','meli_update_remote_stock%'),
                                                                ('state','!=','SUCCESS'),
                                                                ('state','!=','FAILED'),
                                                                ('connection_account','=',account.id) ],
                                                                limit=40)

            #_logger.info("meli_update_remote_stock_injobs > internal_job meli_update_remote_stock: "+str(notifs)+" state:"+str(notifs.mapped('state')) )

            if not notifs:
                #_logger.info("meli_update_remote_stock_injobs > internal_job meli_update_remote_stock: NO stock internal_job.")
                return {}

            max_ustocks = 100
            actual_ustock = 0
            full_pids = []
            for noti in notifs:

                product_ids = (noti.model_ids and json.loads(noti.model_ids)) or []
                product_ids_processed = (noti.model_ids_processed and json.loads(noti.model_ids_processed)) or []
                notpids = (product_ids_processed and [('product_ids','not in', product_ids_processed)]) or []

                #filtering processed
                pids = []
                for p in product_ids:
                    if p not in product_ids_processed and p not in pids and p not in full_pids:
                        pids.append(p)
                        full_pids.append(p)

                product_ids = pids

                #_logger.info("Processing model_ids (product.product) : "+str(product_ids))
                product_bind_ids = self.env['mercadolibre.product'].search([
                    ##('connection_account', '=', account.id )
                    ##'|',('company_id','=',False),('company_id','=',company.id)
                    ('product_id', 'in', product_ids )],
                    order='stock_update asc, product_id asc')
                #_logger.info("product_bind_ids stock to update:" + str(product_bind_ids))
                #_logger.info("account updating stock #" + str(len(product_bind_ids)) + " on " + str(account.name))
                #_logger.info("product_ids: "+str(product_ids))
                #_logger.info("product_ids_processed: "+str(product_ids_processed))
                #_logger.info("notpids: "+str(notpids))
                #_logger.info("product_bind_ids: "+str(product_bind_ids))
                maxcommits = len(product_bind_ids)
                logs = noti.processing_logs or ""
                errors = noti.processing_errors or ""

                try:
                    if auto_commit:
                        MeliCommit( self )
                    pid = None
                    for bind in product_bind_ids:
                        obj = bind #.product_id
                        #_logger.info( "Product check if active: " + str(obj.id)+ ' meli_id:'+str(obj.meli_id)  )
                        if (obj and obj.meli_id):
                            icommit+= 1
                            icount+= 1
                            actual_ustock+= 1
                            try:
                                #_logger.info( "Update Stock: #" + str(icount) +'/'+str(maxcommits)+ ' meli_id:'+str(obj.meli_id)  )
                                resjson = obj.product_post_stock(meli=meli)
                                logs+= str(obj.sku)+" "+str(obj.meli_id)+": "+str(obj.meli_available_quantity)+"\n"
                                if resjson and "error" in resjson:
                                    errors+= str(obj.sku)+" "+str(obj.meli_id)+" >> "+str(resjson)+"\n"
                                #obj.stock_update = ml_datetime( str( datetime.now() ) )

                                #record product processed by bindings
                                if (pid==None):
                                    pid = obj.product_id.id
                                if (pid!=obj.product_id.id or icount==maxcommits) and obj.product_id.id not in product_ids_processed:
                                    product_ids_processed.append(obj.product_id.id)
                                    #_logger.info("product_ids_processed: #"+str(len(product_ids_processed)))
                                pid = obj.product_id.id

                                if ( (actual_ustock>=max_ustocks) or (icommit==40 or (icount==maxcommits) or (icount==noti.model_ids_step))  and 1==1):
                                    noti.processing_errors = errors
                                    noti.processing_logs = logs
                                    noti.model_ids_processed = str(product_ids_processed)
                                    noti.model_ids_count_processed = len(product_ids_processed)
                                    noti.resource = "meli_update_remote_stock #"+str(icount) +'/'+str(maxcommits)
                                    #_logger.info("meli_update_remote_stock_injobs commiting")
                                    icommit=0
                                    if auto_commit:
                                        MeliCommit( self )
                                    #max steps by iteration reached
                                    if (icount>=noti.model_ids_step and icount<maxcommits):
                                        return {}
                                    #max updates on cron iteration reached:
                                    if (actual_ustock>=max_ustocks):
                                        #_logger.info("meli_update_remote_stock_injobs max_ustocks reached:"+str(max_ustocks))
                                        return {}


                            except Exception as e:
                                #_logger.info("meli_update_remote_stock > Exception founded!")
                                #_logger.info(e, exc_info=True)
                                logs+= str(obj.sku)+" "+str(obj.meli_id)+": "+str(obj.meli_available_quantity)+", "
                                #errors+= str(obj.default_code)+" "+str(obj.meli_id)+" >> "+str(e.args[0])+str(", ")
                                errors+= str(obj.sku)+" "+str(obj.meli_id)+" >> "+str(e)+"\n"
                                if auto_commit:
                                    self.env.cr.rollback()

                    noti.resource = "meli_update_remote_stock_injobs #"+str(icount) +'/'+str(maxcommits)
                    noti.stop_internal_notification(errors=errors,logs=logs)

                except Exception as e:
                    #_logger.info("meli_update_remote_stock_injobs > Exception founded!")
                    #_logger.info(e, exc_info=True)
                    if auto_commit:
                        self.env.cr.rollback()
                    noti.stop_internal_notification( errors=errors , logs=logs )
                    if auto_commit:
                        MeliCommit( self )

        return {}

    def _check_price_batch(self, config=None, meli=None):
        """
        Check if a price batch should start or continue.
        Called from internal_jobs every 5 minutes.

        Flow:
        1. If batch_hour == -1 → disabled, skip
        2. If batch is not running and current_hour >= batch_hour and batch_date != today → START batch
        3. If batch is running → CONTINUE processing next chunk
        4. If batch is running but no more items → FINISH batch
        """
        account = self
        if not config:
            company = account.company_id or self.env.user.company_id
            config = account.configuration or company

        # Respect the existing config flag
        if not config.mercadolibre_cron_post_update_price:
            return

        batch_hour_str = account.meli_cron_price_batch_hour
        if not batch_hour_str or batch_hour_str == '-1':
            return

        batch_hour = int(batch_hour_str)
        batch_minute = int(account.meli_cron_price_batch_minute or '0')

        today = fields.Date.today()
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        batch_minutes = batch_hour * 60 + batch_minute

        if not account.meli_cron_price_batch_running:
            # Check if we should START a new batch
            last_batch_date = account.meli_cron_price_batch_date.date() if account.meli_cron_price_batch_date else False
            if current_minutes >= batch_minutes and last_batch_date != today:
                # Count total items to process
                total_items = self.env['mercadolibre.product'].search_count([
                    ('connection_account', '=', account.id),
                ])
                if total_items == 0:
                    return

                account.write({
                    'meli_cron_price_batch_running': True,
                    'meli_cron_price_batch_started': now,
                    'meli_cron_price_batch_total': total_items,
                    'meli_cron_price_batch_processed': 0,
                })

                _logger.info('Price Batch STARTED for %s - %d items to process', account.name, total_items)

                if account.meli_cron_log_chatter:
                    batch_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #d1ecf1; padding: 10px; border-radius: 5px;">
<b>BATCH Price INICIADO</b> - {now.strftime('%H:%M:%S')}<br/>
<b>Total:</b> {total_items} publicaciones a actualizar
</div>"""
                    account.message_post(body=Markup(batch_msg), subtype_xmlid='mail.mt_note')

                if not getattr(threading.current_thread(), 'testing', False):
                    MeliCommit(self)

                # Process first chunk
                account.meli_update_remote_price(meli=meli)
            return

        # Batch is running → continue processing
        # Safety: if batch_started is missing (pre-upgrade batch), force-complete it
        if not account.meli_cron_price_batch_started:
            _logger.info('Price Batch FORCE-COMPLETED for %s - missing batch_started (pre-upgrade batch)', account.name)
            account.write({
                'meli_cron_price_batch_running': False,
                'meli_cron_price_batch_date': fields.Datetime.now(),
            })
            if account.meli_cron_log_chatter:
                batch_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #fff3cd; padding: 10px; border-radius: 5px;">
<b>BATCH Price FINALIZADO</b> - {now.strftime('%H:%M:%S')}<br/>
Batch pre-actualización terminado automáticamente. El próximo batch iniciará normalmente.
</div>"""
                account.message_post(body=Markup(batch_msg), subtype_xmlid='mail.mt_note')
            return

        # Check if there are remaining items (price_update older than batch start or null)
        topcommits = ("meli_cron_price_top_commit" in account._fields and account.meli_cron_price_top_commit) or 80
        batch_start = account.meli_cron_price_batch_started
        remaining = self.env['mercadolibre.product'].search_count([
            ('connection_account', '=', account.id),
            '|',
            ('price_update', '=', False),
            ('price_update', '<', batch_start),
        ])

        if remaining == 0:
            # Batch complete
            account.write({
                'meli_cron_price_batch_running': False,
                'meli_cron_price_batch_date': fields.Datetime.now(),
            })

            _logger.info('Price Batch COMPLETED for %s - %d items processed', account.name, account.meli_cron_price_batch_processed)

            if account.meli_cron_log_chatter:
                batch_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #d4edda; padding: 10px; border-radius: 5px;">
<b>BATCH Price COMPLETADO</b> - {now.strftime('%H:%M:%S')}<br/>
<b>Procesados:</b> {account.meli_cron_price_batch_processed} / {account.meli_cron_price_batch_total}
</div>"""
                account.message_post(body=Markup(batch_msg), subtype_xmlid='mail.mt_note')
            return

        # Still items to process → run next chunk
        _logger.info('Price Batch CONTINUING for %s - %d remaining', account.name, remaining)
        account.meli_update_remote_price(meli=meli)

    def meli_update_remote_price(self, meli=None):

        account = self
        started_at = datetime.now()
        _logger.info('CRON account.meli_update_remote_price() STARTED '+str(account.name) + " " +str( started_at ))
        company = account.company_id or self.env.user.company_id
        config = account.configuration or company
        chatter_log = account.meli_cron_log_chatter

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )

        if (config.mercadolibre_cron_post_update_price):
            auto_commit = not getattr(threading.current_thread(), 'testing', False)
            topcommits = ("meli_cron_price_top_commit" in account._fields and account.meli_cron_price_top_commit) or 80
            product_bind_ids_null = self.env['mercadolibre.product'].search([
                ('connection_account', '=', account.id ),
                ('price_update','=',False),
                ], order='price_update asc', limit=topcommits)
            product_bind_ids_not_null = self.env['mercadolibre.product'].search([
                ('connection_account', '=', account.id ),
                ('price_update','!=',False)
                ], order='price_update asc', limit=topcommits)
            product_bind_ids = product_bind_ids_null + product_bind_ids_not_null
            icommit = 0
            icount = 0
            processed_count = 0
            error_count = 0
            maxcommits = len(product_bind_ids)
            internals = {
                "application_id": account.client_id,
                "user_id": account.seller_id,
                "topic": "internal",
                "resource": "meli_update_remote_price #"+str(maxcommits),
                "state": "PROCESSING"
            }
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals=internals, account=account )
            logs = ""
            errors = ""
            errors_list = []
            logs_list = []

            if chatter_log:
                batch_info = ""
                if account.meli_cron_price_batch_running:
                    batch_offset = account.meli_cron_price_batch_processed
                    batch_total = account.meli_cron_price_batch_total
                    batch_info = f" (batch {batch_offset}/{batch_total})"
                plan_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #f8f9fa; padding: 10px; border-radius: 5px;">
<b>CRON Price INICIADO</b> - {started_at.strftime('%H:%M:%S')} | {maxcommits} items a procesar{batch_info}
</div>"""
                account.message_post(body=Markup(plan_msg), subtype_xmlid='mail.mt_note')

            try:
                if auto_commit:
                    MeliCommit( self )
                for bind in product_bind_ids:
                    obj = bind
                    if (obj and obj.meli_id and icount<=topcommits):
                        icommit+= 1
                        icount+= 1
                        try:
                            resjson = obj.product_post_price(meli=meli)
                            logs+= str(obj.sku)+" "+str(obj.meli_id)+": "+str(obj.meli_price)+"\n"
                            if not resjson or (resjson and "error" in resjson):
                                errors+= str(obj.sku)+" "+str(obj.meli_id)+" >> "+str(resjson)+"\n"
                                errors_list.append(str(obj.sku)+" "+str(obj.meli_id)+" >> "+str(resjson))
                                error_count += 1
                                # In batch mode, mark errored items as attempted so batch can finish
                                if account.meli_cron_price_batch_running:
                                    obj.price_update = ml_datetime( str( datetime.now() ) )
                            else:
                                obj.price_update = ml_datetime( str( datetime.now() ) )
                                processed_count += 1
                                logs_list.append(f"{obj.sku} ({obj.meli_id}): ${obj.meli_price}")

                            if ((icommit==40 or (icount==maxcommits) or (icount==topcommits)) and 1==1):
                                noti.processing_errors = errors
                                noti.processing_logs = logs
                                noti.resource = "meli_update_remote_price #"+str(icount) +'/'+str(maxcommits)
                                icommit=0
                                if auto_commit:
                                    MeliCommit( self )

                        except Exception as e:
                            logs+= str(obj.sku)+" "+str(obj.meli_id)+": "+str(obj.meli_price)+", "
                            errors+= str(obj.sku)+" "+str(obj.meli_id)+" >> "+str(e)+"\n"
                            errors_list.append(str(obj.sku)+" "+str(obj.meli_id)+" >> "+str(e))
                            error_count += 1
                            if auto_commit:
                                self.env.cr.rollback()
                            # In batch mode, mark errored items as attempted so batch can finish
                            if account.meli_cron_price_batch_running:
                                try:
                                    obj.price_update = ml_datetime( str( datetime.now() ) )
                                    if auto_commit:
                                        MeliCommit( self )
                                except Exception:
                                    pass

                noti.resource = "meli_update_remote_price #"+str(icount) +'/'+str(maxcommits)
                noti.stop_internal_notification(errors=errors,logs=logs)

            except Exception as e:
                if auto_commit:
                    self.env.cr.rollback()
                noti.stop_internal_notification( errors=errors , logs=logs )
                if auto_commit:
                    MeliCommit( self )

            ended_at = datetime.now()
            duration = (ended_at - started_at).total_seconds()
            _logger.info('CRON account.meli_update_remote_price() ENDED '+str(account.name) + " FROM "+str( started_at ) + " TO " +str( ended_at ))

            if chatter_log:
                avg_time = f"{(duration/processed_count):.2f}s" if processed_count > 0 else "N/A"
                status_icon = "OK" if error_count == 0 else "WARN"

                # Items actualizados
                items_summary = ""
                if logs_list:
                    items_detail = "<br/>".join(logs_list[:20])
                    if len(logs_list) > 20:
                        items_detail += f"<br/>... y {len(logs_list) - 20} más"
                    items_summary = f"<br/><b>Publicaciones actualizadas ({processed_count}):</b><br/>{items_detail}"

                # Errores
                error_summary = ""
                if errors_list:
                    error_types = {}
                    for err in errors_list:
                        err_lower = err.lower()
                        if 'not_found' in err_lower or '404' in err_lower:
                            error_types['not_found'] = error_types.get('not_found', 0) + 1
                        elif 'status:closed' in err_lower or 'status:inactive' in err_lower:
                            error_types['closed'] = error_types.get('closed', 0) + 1
                        elif 'under_review' in err_lower:
                            error_types['under_review'] = error_types.get('under_review', 0) + 1
                        elif 'not modifiable' in err_lower or 'not_modifiable' in err_lower or 'field_not_updatable' in err_lower:
                            error_types['not_modifiable'] = error_types.get('not_modifiable', 0) + 1
                        elif 'blocked' in err_lower:
                            error_types['blocked'] = error_types.get('blocked', 0) + 1
                        elif 'forbidden' in err_lower or '403' in err_lower:
                            error_types['forbidden'] = error_types.get('forbidden', 0) + 1
                        else:
                            error_types['otros'] = error_types.get('otros', 0) + 1

                    error_breakdown = " | ".join([f"{k}: {v}" for k, v in sorted(error_types.items(), key=lambda x: -x[1])])
                    error_detail = "<br/>".join(errors_list[:10])
                    if len(errors_list) > 10:
                        error_detail += f"<br/>... y {len(errors_list) - 10} errores más"
                    error_summary = f"<br/><b>Tipos:</b> {error_breakdown}<br/><b>Detalle:</b><br/>{error_detail}"

                summary_msg = f"""
<div style="font-family: monospace; font-size: 12px; background: #f8f9fa; padding: 10px; border-radius: 5px;">
<b>{status_icon} CRON Price FIN</b> - {ended_at.strftime('%H:%M:%S')} ({duration:.1f}s)<br/>
<b>Resultado:</b> {processed_count} OK, {error_count} errores | Prom: {avg_time}{items_summary}{error_summary}
</div>"""
                account.message_post(body=Markup(summary_msg), subtype_xmlid='mail.mt_note')

            # Update batch progress if batch is running (count all attempted items)
            if account.meli_cron_price_batch_running:
                account.meli_cron_price_batch_processed += (processed_count + error_count)

        return {}



#STANDARD




    def list_catalog( self, **post ):

        result = []

        #_logger.info("list_catalog mercadolibre")
        #_logger.info(result)

        account = self
        company = account.company_id or self.env.user.company_id
        bindings = self.env["mercadolibre.product"].search([("connection_account","=",account.id)])

        #start notification
        noti = None
        logs = ""
        errors = ""
        try:
            internals = {
                "connection_account": account,
                "application_id": account.client_id or '',
                "user_id": account.seller_id or '',
                "topic": "catalog",
                "resource": "list_catalog",
                "state": "PROCESSING"
            }
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals )
        except Exception as e:
            _logger.error("list_catalog error creating notification: "+str(e))
            pass;

        for binding in bindings:

            product = binding.product_tmpl_id

            tpl = {
                "name": product.name or "",
                "code": product.default_code or "",
                "barcode": product.barcode or "",
                "brand": "Oneill",
                "variations": [],
                "category": product.categ_id.name or "",
                "notes": product.description_sale or "",
                "prices": [],
                "dimensions": {
                    "weight": 1,
                    "width": 1,
                    "length": 1,
                    "height": 1,
                    "pieces": 1
                },
                "attributes": []
            }

            prices = []
            #self.with_context(pricelist=pricelist.id).price
            #for plitem in product.item_ids:
            for pl in account.configuration.publish_price_lists:
                plprice = product.with_context(pricelist=pl.id).price
                price = {
                    "priceListId": pl.id,
                    "priceList": pl.name,
                    "amount": plprice,
                    "currency": pl.currency_id.name
                }
                prices.append(price)

            attributes = []
            attvariants = []
            for attline in product.attribute_line_ids:
                if len(attline.value_ids)>1:
                    attvariants.append(attline.attribute_id.id)
                else:
                    for val in attline.value_ids:
                        att = {
                            "key": attline.attribute_id.name,
                            "value": val.name
                        }
                        attributes.append(att)

            #tpl["variations"]
            for variant in product.product_variant_ids:

                var = {
                    "sku": variant.default_code or "",
                    #"color": "" or "",
                    #"size": "" or "",
                    "barcode": variant.barcode or "",
                    "code": variant.default_code or "",
                }

                for val in variant.attribute_value_ids:
                    if val.attribute_id.id in attvariants:
                        var[val.attribute_id.name] = val.name

                stocks = []
                #ss = variant._product_available()
                #_logger.info("account.configuration.publish_stock_locations")
                #_logger.info(account.configuration.publish_stock_locations.mapped("id"))
                _publish_stock_enabled = account.configuration.publish_stock if hasattr(account.configuration, 'publish_stock') else False
                _publish_stock_locids = account.configuration.publish_stock_locations.mapped("id") if (_publish_stock_enabled and account.configuration.publish_stock_locations) else []
                sq = self.env["stock.quant"].search([('product_id','=',variant.id)])
                if (sq):
                    #_logger.info( sq )
                    #_logger.info( sq.name )
                    for s in sq:
                        #TODO: filtrar por configuration.locations
                        #TODO: merge de stocks
                        #TODO: solo publicar available
                        if ( s.location_id.usage == "internal" and _publish_stock_locids and s.location_id.id in _publish_stock_locids):
                            #_logger.info( s )
                            sjson = {
                                "warehouseId": s.location_id.id,
                                "warehouse": s.location_id.display_name,
                                "quantity": s.quantity,
                                "reserved": s.reserved_quantity,
                                "available": s.quantity - s.reserved_quantity
                            }
                            stocks.append(sjson)

                #{
                #    "warehouseId": 61879,
                #    "warehouse": "Estoque Principal - Ecommerce",
                #    "quantity": 0,
                #    "reserved": 0,
                #    "available": 0
                #}

                pictures = []
                if "product_image_ids" in variant._fields:
                    if variant.image:
                        img = {
                            "url": variant.mercadolibre_image_url_principal(),
                            "id": variant.mercadolibre_image_id_principal()
                        }
                        pictures.append(img)
                    for image in variant.product_image_ids:
                        img = {
                            "url": variant.mercadolibre_image_url(image),
                            "id": variant.mercadolibre_image_id(image)
                        }
                        pictures.append(img)

                var["pictures"] = pictures
                var["stocks"] = stocks

                tpl["variations"].append(var)

            tpl["prices"] = prices
            tpl["attributes"] = attributes

            result.append(tpl)

        if noti:
            logs = str(result)
            noti.stop_internal_notification(errors=errors,logs=logs)

        return result

    def list_pricestock( self, **post ):
        #_logger.info("list_pricestock")
        result = []

        account = self
        company = account.company_id or self.env.user.company_id
        bindings = self.env["mercadolibre.product"].search([("connection_account","=",account.id)])

        #start notification
        noti = None
        logs = ""
        errors = ""
        try:
            internals = {
                "connection_account": account,
                "application_id": account.client_id or '',
                "user_id": account.seller_id or '',
                "topic": "catalog",
                "resource": "list_pricestock",
                "state": "PROCESSING"
            }
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals )
        except Exception as e:
            _logger.error("list_pricestock error creating notification: "+str(e))
            pass;

        for binding in bindings:

            variant = binding.product_id

            var = {
                "sku": variant.default_code or "",
                "barcode": variant.barcode or "",
            }

            stocks = []
            #ss = variant._product_available()
            _publish_stock_enabled = account.configuration.publish_stock if hasattr(account.configuration, 'publish_stock') else False
            _publish_stock_locids = account.configuration.publish_stock_locations.mapped("id") if (_publish_stock_enabled and account.configuration.publish_stock_locations) else []
            sq = self.env["stock.quant"].search([('product_id','=',variant.id)])
            if (sq):
                #_logger.info( sq )
                #_logger.info( sq.name )
                for s in sq:
                    if ( s.location_id.usage == "internal" and _publish_stock_locids and s.location_id.id in _publish_stock_locids):
                        #_logger.info( s )
                        sjson = {
                            "warehouseId": s.location_id.id,
                            "warehouse": s.location_id.display_name,
                            "quantity": s.quantity,
                            "reserved": s.reserved_quantity,
                            "available": s.quantity - s.reserved_quantity
                        }
                        stocks.append(sjson)

            var["stocks"] = stocks

            prices = []
            for pl in account.configuration.publish_price_lists:
                plprice = variant.with_context(pricelist=pl.id).price
                price = {
                    "priceListId": pl.id,
                    "priceList": pl.name,
                    "amount": plprice,
                    "currency": pl.currency_id.name
                }
                prices.append(price)
            var["prices"] = prices

            result.append(var)

        if noti:
            logs = str(result)
            noti.stop_internal_notification(errors=errors,logs=logs)

        return result

    def list_pricelist( self, **post ):
        #_logger.info("list_pricelist")
        result = []

        account = self
        company = account.company_id or self.env.user.company_id
        bindings = self.env["mercadolibre.product"].search([("connection_account","=",account.id)])

        #start notification
        noti = None
        logs = ""
        errors = ""
        try:
            internals = {
                "connection_account": account,
                "application_id": account.client_id or '',
                "user_id": account.seller_id or '',
                "topic": "catalog",
                "resource": "list_pricelist",
                "state": "PROCESSING"
            }
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals )
        except Exception as e:
            _logger.error("list_pricelist error creating notification: "+str(e))
            pass;

        for binding in bindings:

            variant = binding.product_id

            var = {
                "sku": variant.default_code or "",
                "barcode": variant.barcode or "",
            }

            prices = []
            for pl in account.configuration.publish_price_lists:
                plprice = product.with_context(pricelist=pl.id).price
                price = {
                    "priceListId": pl.id,
                    "priceList": pl.name,
                    "amount": plprice,
                    "currency": pl.currency_id.name
                }
                prices.append(price)
            var["prices"] = prices

            result.append(var)

        if noti:
            logs = str(result)
            noti.stop_internal_notification(errors=errors,logs=logs)

        return result

    def list_stock( self, **post ):
        #_logger.info("list_stock")
        result = []

        account = self
        company = account.company_id or self.env.user.company_id
        bindings = self.env["mercadolibre.product"].search([("connection_account","=",account.id)])

        #start notification
        noti = None
        logs = ""
        errors = ""
        try:
            internals = {
                "connection_account": account,
                "application_id": account.client_id or '',
                "user_id": account.seller_id or '',
                "topic": "catalog",
                "resource": "list_stock",
                "state": "PROCESSING"
            }
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals )
        except Exception as e:
            _logger.error("list_stock error creating notification: "+str(e))
            pass;

        for binding in bindings:

            variant = binding.product_id

            var = {
                "sku": variant.default_code or "",
                "barcode": variant.barcode or "",
            }


            stocks = []
            #ss = variant._product_available()
            _publish_stock_enabled = account.configuration.publish_stock if hasattr(account.configuration, 'publish_stock') else False
            _publish_stock_locids = account.configuration.publish_stock_locations.mapped("id") if (_publish_stock_enabled and account.configuration.publish_stock_locations) else []
            sq = self.env["stock.quant"].search([('product_id','=',variant.id)])
            if (sq):
                #_logger.info( sq )
                #_logger.info( sq.name )
                for s in sq:
                    if ( s.location_id.usage == "internal" and _publish_stock_locids and s.location_id.id in _publish_stock_locids):
                        #_logger.info( s )
                        sjson = {
                            "warehouseId": s.location_id.id,
                            "warehouse": s.location_id.display_name,
                            "quantity": s.quantity,
                            "reserved": s.reserved_quantity,
                            "available": s.quantity - s.reserved_quantity
                        }
                        stocks.append(sjson)

            var["stocks"] = stocks

            result.append(var)

        if noti:
            logs = str(result)
            noti.stop_internal_notification(errors=errors,logs=logs)

        return result

    def street(self, contact, billing=False ):
        if not billing and "location_streetName" in contact:
            return contact["location_streetName"]+" "+contact["location_streetNumber"]
        else:
            return contact["billingInfo_streetName"]+" "+contact["billingInfo_streetNumber"]

    def city(self, contact, billing=False ):
        if not billing and "location_city" in contact:
            return contact["location_city"]
        else:
            return contact["billingInfo_city"]


    #return odoo country id
    def country(self, contact, billing=False ):
        #MercadoLibre country has no country? ok
        #take country from account company if not available
        country = False
        if not billing and "country" in contact and len(contact["country"]):
            country = contact["country"]
        else:
            country = ("billingInfo_country" in contact and contact["billingInfo_country"])
            #do something
        if country:
            countries = self.env["res.country"].search([("name","like",country)])
            if countries and len(countries):
                return countries[0].id

        company = self.company_id or self.env.user.company_id
        country = self.country_id or company.country_id

        return country.id

    def dstate(self, country, contact, billing=False ):
        full_state = ''

        #parse from MercadoLibre contact
        Receiver = {}
        Receiver.update(contact)
        if not billing:
            Receiver["state"] = { "name": ("location_state" in contact and contact["location_state"]) or "" }
        else:
            Receiver["state"] = { "name": ("billingInfo_state" in contact and contact["billingInfo_state"]) or "" }
        country_id = country

        state_id = False
        if (Receiver and 'state' in Receiver):
            if ('id' in Receiver['state']):
                state = self.env['res.country.state'].search([('code','like',Receiver['state']['id']),('country_id','=',country_id)])
                if (len(state)):
                    state_id = state[0].id
                    return state_id
                id_ml = Receiver['state']['id'].split("-")
                #_logger.info(Receiver)
                #_logger.info(id_ml)
                if (len(id_ml)==2):
                    id = id_ml[1]
                    state = self.env['res.country.state'].search([('code','like',id),('country_id','=',country_id)])
                    if (len(state)):
                        state_id = state[0].id
                        return state_id
            if ('name' in Receiver['state']):
                full_state = Receiver['state']['name']
                state = self.env['res.country.state'].search(['&',('name','like',full_state),('country_id','=',country_id)])
                if (len(state)):
                    state_id = state[0].id
        return state_id

    def full_phone(self, contact, billing=False ):
        return contact["phoneNumber"]

    def doc_info(self, contactfields):
        dinfo = {}
        if "billingInfo_docNumber" in contactfields and 'billingInfo_docType' in contactfields:

            doc_number = contactfields["billingInfo_docNumber"]
            doc_type = contactfields['billingInfo_docType']

            if (doc_type and ('afip.responsability.type' in self.env)):
                doctypeid = self.env['res.partner.id_category'].search([('code','=',doc_type)]).id
                if (doctypeid):
                    dinfo['main_id_category_id'] = doctypeid
                    dinfo['main_id_number'] = doc_number
                    if (doc_type=="CUIT"):
                        #IVA Responsable Inscripto
                        afipid = self.env['afip.responsability.type'].search([('code','=',1)]).id
                        dinfo["afip_responsability_type_id"] = afipid
                    else:
                        #if (Buyer['billing_info']['doc_type']=="DNI"):
                        #Consumidor Final
                        afipid = self.env['afip.responsability.type'].search([('code','=',5)]).id
                        dinfo["afip_responsability_type_id"] = afipid
                else:
                    _logger.error("res.partner.id_category:" + str(doc_type))
        return dinfo


    def rebind( self, meli_id, **post):
        res = ""
        #_logger.info("rebind: "+str(meli_id)+" post:"+str(post))
        bp = self.search_meli_binding_product(meli_id=meli_id)
        if bp:
            bt = bp.binding_product_tmpl_id
            if bt:
                res = bt.product_template_rebind()
        return res

    def post_stock( self, meli_id, **post):
        #_logger.info("post_stock: "+str(meli_id)+" post:"+str(post))
        bp = self.search_meli_binding_product(meli_id=meli_id)
        if bp:
            bt = bp.binding_product_tmpl_id
            if bt:
                res = bt.product_template_post_stock()
        return res

    def post_price( self, meli_id, **post):
        #_logger.info("post_price: "+str(meli_id)+" post:"+str(post))
        bp = self.search_meli_binding_product(meli_id=meli_id)
        if bp:
            bt = bp.binding_product_tmpl_id
            if bt:
                res = bt.product_template_post_price()
        return res

    def post_stock_variant( self, meli_id, meli_id_variation, **post):
        #_logger.info("post_stock: "+str(meli_id)+" meli_id_variation:"+str(meli_id_variation)+" post:"+str(post))
        bp = self.search_meli_binding_product(meli_id=meli_id,meli_id_variation=meli_id_variation)
        if bp:
            res = bp.product_post_stock()
        return res


    def import_sales( self, **post ):

        #_logger.info("import_sales")
        account = self
        company = account.company_id or self.env.user.company_id
        noti = None
        logs = ""
        errors = ""

        #start notification
        try:
            internals = {
                "connection_account": self,
                "application_id": self.client_id or '',
                "user_id": self.seller_id or '',
                "topic": "sales",
                "resource": "import_sales",
                "state": "PROCESSING"
            }
            noti = self.env["mercadolibre.notification"].start_internal_notification( internals )
        except Exception as e:
            _logger.error("import_sales error creating notification: "+str(e))
            pass;

        result = []

        sales = post.get("sales")
        logs = str(sales)

        #_logger.info("Processing sales")
        for sale in sales:
            res = self.import_sale( sale, noti )
            for r in res:
                result.append(r)

        #close notifications
        if noti:
            errors = str(result)
            logs = str(logs)
            noti.stop_internal_notification(errors=errors,logs=logs)

        #_logger.info(result)
        return result

    def import_sale( self, sale, noti ):

        account = self
        company = account.company_id or self.env.user.company_id
        result = []
        pso = False
        psoid = False
        so = False

        #_logger.info(sale)
        return result


    def import_products( self ):
        #

        return ""



    def import_product( self ):
        #

        return ""



    def import_image( self ):
        #

        return ""



    def import_shipment( self ):
        #

        return ""



    def import_payment( self ):
        #

        return ""

    # ==================================================================
    # OCAPI Generic Publishing Protocol
    # ==================================================================

    def ocapi_get_capabilities(self):
        return {
            'can_publish_products': True,
            'can_publish_images': True,
            'can_publish_descriptions': True,
            'can_publish_prices': True,
            'can_publish_stock': True,
            'can_import_orders': True,
            'can_sync_categories': True,
            'supported_image_formats': ['jpg', 'png', 'webp'],
            'max_images_per_product': 10,
            'max_title_length': 60,
            'max_description_length': 50000,
            'requires_category': True,
            'supports_variants': True,
        }

    def ocapi_publish_product(self, product_data):
        self.ensure_one()
        try:
            source_model = product_data.get('source_model', '')
            source_id = product_data.get('source_id')
            if source_model == 'product.template' and source_id:
                product_tmpl = self.env['product.template'].browse(source_id)
                if product_tmpl.exists():
                    result = product_tmpl.product_post()
                    return {
                        'success': True,
                        'result': result,
                    }
            return {
                'success': False,
                'error': 'MercadoLibre publish requires source_model=product.template',
            }
        except Exception as e:
            _logger.error("ocapi_publish_product MeLi error: %s", str(e))
            return {'success': False, 'error': str(e)}

    def ocapi_get_product_status(self, external_id):
        self.ensure_one()
        try:
            meli = self.env['meli.util'].get_new_instance(self.company_id, self)
            if meli.need_login():
                return {'success': False, 'error': 'MercadoLibre login required'}
            response = meli.get('/items/%s' % external_id)
            if response and hasattr(response, 'json'):
                data = response.json()
                return {
                    'success': True,
                    'status': data.get('status', 'unknown'),
                    'external_url': data.get('permalink', ''),
                }
            return {'success': False, 'error': 'No response from MercadoLibre API'}
        except Exception as e:
            _logger.error("ocapi_get_product_status MeLi error: %s", str(e))
            return {'success': False, 'error': str(e)}
