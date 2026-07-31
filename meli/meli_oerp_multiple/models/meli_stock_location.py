# -*- coding: utf-8 -*-
from odoo import fields, models, api
from . import versions
import logging
_logger = logging.getLogger(__name__)


class MercadolibreAccountStockLocation(models.Model):
    """
    Representa un depósito (store) de MercadoLibre con tag stock_location.
    Sirve como tabla pivote entre mercadolibre.account y stock.location de Odoo,
    permitiendo mapear cada nodo logístico de ML a una ubicación interna de Odoo.
    """
    _name = 'mercadolibre.account.stock_location'
    _description = 'Depósito ML (stock_location)'
    _rec_name = 'name'
    _order = 'account_id, name'

    account_id = fields.Many2one(
        'mercadolibre.account',
        string='Cuenta ML',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # Datos del store en ML
    meli_store_id = fields.Char(string='ML Store ID', index=True, readonly=True)
    name = fields.Char(string='Nombre / Descripción', required=True)
    status = fields.Selection(
        [('active', 'Activo'), ('inactive', 'Inactivo')],
        string='Estado ML',
        default='active',
        readonly=True,
    )
    network_node_id = fields.Char(string='Network Node ID', readonly=True,
        help='Identificador de nodo en la red logística de ML, ej: MXP13767317941')
    services_stock_location = fields.Char(
        string='Servicios ML',
        readonly=True,
        help='Tipos de servicio del nodo (ej: xd_drop_off)',
    )

    # Ubicación geográfica (del store en ML)
    address_line = fields.Char(string='Dirección', readonly=True)
    city = fields.Char(string='Ciudad', readonly=True)
    state_name = fields.Char(string='Estado/Provincia', readonly=True)
    zip_code = fields.Char(string='CP', readonly=True)
    latitude = fields.Float(string='Latitud', digits=(10, 6), readonly=True)
    longitude = fields.Float(string='Longitud', digits=(10, 6), readonly=True)

    # Mapeo a Odoo
    odoo_location_id = fields.Many2one(
        'stock.location',
        string='Ubicación Odoo',
        domain=[('usage', '=', 'internal')],
        help='Ubicación interna de Odoo que corresponde a este depósito de ML. '
             'Este mapeo define qué stock de Odoo se publica en este nodo logístico.',
    )

    _unique_store_per_account = versions.UniqueIndex(
        'account_id, meli_store_id',
        message='Ya existe un registro para este store en esta cuenta ML.',
    )

    def name_get(self):
        result = []
        for rec in self:
            city = (' — ' + rec.city) if rec.city else ''
            result.append((rec.id, '%s%s' % (rec.name, city)))
        return result


class StockLocationMeli(models.Model):
    """Extiende stock.location para agregar referencia a depósitos ML vinculados."""
    _inherit = 'stock.location'

    meli_stock_location_ids = fields.One2many(
        'mercadolibre.account.stock_location',
        'odoo_location_id',
        string='Depósitos ML vinculados',
        help='Nodos logísticos de MercadoLibre que usan esta ubicación como fuente de stock.',
    )
