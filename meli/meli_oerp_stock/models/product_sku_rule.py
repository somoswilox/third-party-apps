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

import pdb

import requests
from odoo.addons.meli_oerp.models.versions import *

mapping_meli_sku_regex = {
    #"alephcrm": [
    #    {
    #        "regex": r"([a-zA-Z0-9]+[\-]+)([A-Z0-9]+[^x])",
    #        "group": 1,
    #        "test": "A12-848ERZEREx10"
    #    },
    #    {
    #        "regex": r"([A-Z0-9]+[^-x]$)",
    #        "group": 0,
    #        "test": "DF848ERZERE"
    #    }
    #]
}

# Mapping table
# "Cód SKU Propio Mercado Libre": "SKU ODOO"
mapping_meli_sku_defaut_code = {
    #"904254AX50": "Y051",
}

class meli_oerp_sku_rule(models.Model):

    _name = "meli_oerp.sku.rule"
    _description = "Meli Sku Rule"

    name = fields.Char(string="Name",help="Sku Name received",required=True,index=True)
    type = fields.Selection([('map','Map'),('regex','Formula'),('stock','Stock Rule')],string="Rule type", index=True, default='map')

    sku = fields.Char(string="Sku",help="Sku Map in Odoo",required=False,index=True)
    barcode = fields.Char(string="Barcode",help="Barcode Map in Odoo",required=False,index=True)

    formula = fields.Char(string="Formula",help="Sku Regex Formula",required=False,index=True)
    group = fields.Char(string="Group",help="Sku Regex Group",required=False)
    test = fields.Char(string="Test",help="Sku Regex Test",required=False)

    security_virtual_stock_to_pause = fields.Float(string="Virtual Stock", default=False )
    security_quantity_stock_to_pause = fields.Float(string="Quantity Stock", default=False )
    # 26.375 (#caso-K69): modo de la regla de stock. 'resguardo' = comportamiento de siempre (publica
    # max(0, disponible - N)); 'umbral' = si el disponible es menor que K publica 0 (ML pausa por falta de
    # stock), si no publica el disponible entero. N/K = "Quantity Stock" (security_quantity_stock_to_pause).
    meli_stock_rule_mode = fields.Selection(
        [('resguardo', 'Resguardo (publica disponible - N)'),
         ('umbral', 'Umbral (con menos de K publica 0)')],
        string="Modo stock", default='resguardo',
        help="Sólo reglas de tipo Stock. Resguardo: se publica el disponible menos «Quantity Stock». "
             "Umbral: si el disponible es menor que «Quantity Stock» se publica 0 (Mercado Libre pausa por "
             "falta de stock); si no, se publica el disponible entero.")

    _unique_meli_oerp_sku_rule = UniqueIndex('name', message='Rule name already exists!')

    def map_to_sku(self, name ):

        sku = None
        maps = self.search([('name','=',str(name)),('type','=','map')])

        if len(maps)==1:
            sku = maps[0].sku
        #else:
        #    _logger.error("Sku Map duplicates:"+str(name))

        return sku

    def resolve_to_sku(self, name ):
        sku = None
        return sku

    # ------------------------------------------------------------------
    # Stock de seguridad (un cliente, 13-oct-2026)
    # La regla de stock (type='stock') ya existia en la configuracion del conector con el
    # campo `security_quantity_stock_to_pause` ("Quantity Stock"), que nadie leia desde 2021.
    # Es ESE campo el que expresa "unidades que Odoo se reserva y no publica en ML":
    # se publica max(0, disponible - N).
    #   - sku = SKU exacto (default_code de la variante) o '*' (todos los productos).
    #   - Gana el SKU exacto sobre '*'. Si hay varias del mismo nivel, la MAYOR.
    #   - Se ignoran las reglas formula='update_rt' (son de prioridad de cola, otro uso).
    # Reemplaza al campo `mercadolibre_stock_safety_qty` (26.208), que deja de leerse.
    # La logica vive SOLO aca: _meli_available_quantity y el diagnostico de meli_oerp la llaman.
    # ------------------------------------------------------------------
    MELI_SAFETY_IGNORED_FORMULAS = ('update_rt',)

    def _meli_stock_safety_rules(self, mode=None):
        """Reglas de `self` que definen stock de seguridad. `mode` (26.375): 'resguardo' | 'umbral' | None (ambos).
        Una regla sin modo (creada antes de 26.375) es 'resguardo'."""
        return self.filtered(
            lambda r: r.type == 'stock'
            and (r.formula or '').strip() not in self.MELI_SAFETY_IGNORED_FORMULAS
            and (r.security_quantity_stock_to_pause or 0) > 0
            and (r.sku or '').strip()
            and (mode is None or (r.meli_stock_rule_mode or 'resguardo') == mode)
        )

    def _meli_stock_rules_in_scope(self):
        """26.375 (#caso-K69): hook de ALCANCE. Devuelve los grupos de reglas aplicables, del más específico al
        más general; gana el primer grupo que tenga una regla para el SKU. Acá (sin depósitos) hay un solo
        grupo. meli_oerp_multiple lo extiende con «depósito ML específico» > «todos los depósitos»."""
        return [self]

    def _meli_stock_rule_value_for_sku(self, sku, mode):
        """N (resguardo) o K (umbral) para `sku`: alcance más específico primero; dentro, SKU exacto > '*';
        si hay varias del mismo nivel, la MAYOR."""
        rules = self._meli_stock_safety_rules(mode=mode)
        if not rules:
            return 0.0
        sku = (sku or '').strip()
        for scope in rules._meli_stock_rules_in_scope():
            if not scope:
                continue
            exact = sku and sku != '*' and scope.filtered(lambda r: r.sku.strip() == sku)
            if exact:
                return max(exact.mapped('security_quantity_stock_to_pause'))
            star = scope.filtered(lambda r: r.sku.strip() == '*')
            if star:
                return max(star.mapped('security_quantity_stock_to_pause'))
        return 0.0

    def _meli_stock_safety_qty_for_sku(self, sku):
        """`self` = reglas de UNA configuracion. Devuelve N (>= 0) de RESGUARDO para ese SKU (las reglas
        'umbral' no restan: ver _meli_stock_rule_qty_for_sku)."""
        return self._meli_stock_rule_value_for_sku(sku, 'resguardo')

    def _meli_stock_rule_qty_for_sku(self, sku, qty):
        """26.375 (#caso-K69): cantidad a publicar tras las reglas de stock.
        Umbral K y resguardo N se resuelven por separado (cada modo con su precedencia) y se combinan:
          1) disponible < K  ⇒ 0;   2) si no, max(0, disponible - N)."""
        qty = qty or 0
        if qty <= 0:
            return qty
        k = self._meli_stock_rule_value_for_sku(sku, 'umbral')
        if k > 0 and qty < k:
            return 0.0
        n = self._meli_stock_rule_value_for_sku(sku, 'resguardo')
        if n > 0:
            return max(0, qty - n)
        return qty

    @api.model
    def _meli_stock_rules_from_config(self, config):
        """Reglas de `config` en el env de `self` (conserva el contexto del llamador: el depósito ML que se está
        publicando viaja por contexto). sudo: el stock se publica tambien desde movimientos de usuarios sin
        permiso sobre las reglas."""
        if not config or 'mercadolibre_stock_sku_mapping' not in config._fields:
            return self.browse()
        return self.sudo().browse(config.sudo().mercadolibre_stock_sku_mapping.ids)

    @api.model
    def _meli_stock_safety_qty_from_config(self, config, sku):
        """N (resguardo) para `sku` segun las reglas de `config` (res.company o mercadolibre.configuration)."""
        return self._meli_stock_rules_from_config(config)._meli_stock_safety_qty_for_sku(sku)

    @api.model
    def _meli_stock_rule_qty_from_config(self, config, sku, qty):
        """26.375: cantidad a publicar para `sku` tras las reglas de stock (umbral + resguardo) de `config`."""
        rules = self._meli_stock_rules_from_config(config)
        if not rules:
            return qty
        return rules._meli_stock_rule_qty_for_sku(sku, qty)
