# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from . import versions
from .versions import *

_logger = logging.getLogger(__name__)


class OcapiConnectorRegistry(models.Model):
    """
    Registro central de conectores del ecosistema OCAPI.

    Cada conector (propio o nativo via bridge) se registra aqui
    al instalarse, permitiendo a OCAPI descubrir y listar todos
    los conectores disponibles y sus cuentas.

    Los conectores propios (MercadoLibre, Producteca, etc.) se
    auto-registran via XML data al instalarse.
    Los bridges nativos (Amazon, Shopee) hacen lo mismo.
    """
    _name = "ocapi.connector.registry"
    _description = "OCAPI Connector Registry"
    _order = "sequence, name"

    name = fields.Char(
        string="Nombre del Conector",
        required=True,
        index=True,
    )
    connector_type = fields.Char(
        string="Tipo",
        required=True,
        index=True,
        help="Identificador unico del tipo de conector. "
             "Coincide con el valor del campo 'type' en ocapi.connection.account "
             "para conectores propios.",
    )
    account_model = fields.Char(
        string="Modelo de Cuenta",
        required=True,
        help="Nombre tecnico del modelo de cuenta (ej: mercadolibre.account, amazon.account, shopee.shop)",
    )
    binding_model = fields.Char(
        string="Modelo de Binding",
        help="Nombre tecnico del modelo de binding/offer (ej: amazon.offer, shopee.item)",
    )
    configuration_model = fields.Char(
        string="Modelo de Configuracion",
        help="Nombre tecnico del modelo de configuracion si existe",
    )
    module_name = fields.Char(
        string="Modulo Principal",
        required=True,
        help="Nombre tecnico del modulo de Odoo (ej: meli_oerp_multiple, sale_amazon)",
    )
    bridge_module = fields.Char(
        string="Modulo Bridge",
        help="Nombre del modulo bridge OCAPI si es un conector nativo (ej: ocapi_sale_amazon)",
    )
    is_native_odoo = fields.Boolean(
        string="Conector Nativo Odoo",
        default=False,
        help="True si es un conector nativo de Odoo Enterprise integrado via bridge",
    )
    is_installed = fields.Boolean(
        string="Instalado",
        compute="_compute_is_installed",
        store=False,
        help="Indica si el modulo del conector esta instalado en esta instancia",
    )
    account_count = fields.Integer(
        string="Cuentas",
        compute="_compute_account_count",
        store=False,
    )
    icon = fields.Char(
        string="Icono",
        help="Clase CSS del icono (fa-*) o ruta al icono",
        default="fa-plug",
    )
    color = fields.Integer(
        string="Color",
        default=0,
    )
    sequence = fields.Integer(
        string="Secuencia",
        default=100,
    )
    notes = fields.Text(
        string="Notas",
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
    )

    _unique_connector_type = versions.UniqueIndex('connector_type', message='El tipo de conector debe ser unico.')

    @api.depends('module_name')
    def _compute_is_installed(self):
        from . import versions
        for reg in self:
            reg.is_installed = versions._check_module_installed(self.env, reg.module_name)

    @api.depends('account_model')
    def _compute_account_count(self):
        for reg in self:
            if reg.account_model and reg.account_model in self.env:
                try:
                    reg.account_count = self.env[reg.account_model].sudo().search_count([])
                except Exception:
                    reg.account_count = 0
            else:
                reg.account_count = 0

    # -----------------------------------------------------------------
    # Discovery Methods
    # -----------------------------------------------------------------

    @api.model
    def get_all_connector_accounts(self):
        """
        Retorna un dict con todos los conectores registrados y sus cuentas.
        {
            'mercadolibre': [{'id': 1, 'name': '...', 'model': 'mercadolibre.account'}, ...],
            'amazon': [{'id': 5, 'name': '...', 'model': 'amazon.account'}, ...],
        }
        """
        result = {}
        for reg in self.search([]):
            if not reg.is_installed:
                continue
            if reg.account_model not in self.env:
                continue
            try:
                accounts = self.env[reg.account_model].sudo().search([])
                result[reg.connector_type] = [{
                    'id': acc.id,
                    'name': acc.name if hasattr(acc, 'name') else str(acc.id),
                    'model': reg.account_model,
                    'connector_type': reg.connector_type,
                    'connector_name': reg.name,
                } for acc in accounts]
            except Exception as e:
                _logger.warning("Error listing accounts for %s: %s", reg.connector_type, e)
                result[reg.connector_type] = []
        return result

    @api.model
    def get_all_accounts_flat(self):
        """
        Retorna una lista plana de todas las cuentas de todos los conectores.
        Util para vistas unificadas.
        """
        all_accounts = []
        connector_accounts = self.get_all_connector_accounts()
        for connector_type, accounts in connector_accounts.items():
            all_accounts.extend(accounts)
        return all_accounts

    @api.model
    def get_connector_summary(self):
        """
        Retorna un resumen de todos los conectores registrados.
        [{
            'name': 'MercadoLibre',
            'type': 'mercadolibre',
            'installed': True,
            'account_count': 3,
            'is_native': False,
        }, ...]
        """
        summary = []
        for reg in self.search([]):
            summary.append({
                'name': reg.name,
                'type': reg.connector_type,
                'installed': reg.is_installed,
                'account_count': reg.account_count,
                'is_native': reg.is_native_odoo,
                'module': reg.module_name,
                'bridge': reg.bridge_module or False,
            })
        return summary

    @api.model
    def get_publishing_connectors(self):
        """Return connectors that support product publishing, with capabilities.

        Returns list of dicts with connector info + accounts that can publish:
        [{
            'connector_type': 'mercadolibre',
            'connector_name': 'MercadoLibre',
            'accounts': [{
                'id': 1,
                'name': 'ML Argentina',
                'model': 'mercadolibre.account',
                'capabilities': { ... },
            }],
        }, ...]
        """
        result = []
        for reg in self.search([]):
            if not reg.is_installed or reg.account_model not in self.env:
                continue
            try:
                accounts = self.env[reg.account_model].sudo().search([])
                pub_accounts = []
                for acc in accounts:
                    if hasattr(acc, 'ocapi_get_capabilities'):
                        caps = acc.ocapi_get_capabilities()
                        if caps.get('can_publish_products'):
                            pub_accounts.append({
                                'id': acc.id,
                                'name': acc.name if hasattr(acc, 'name') else str(acc.id),
                                'model': reg.account_model,
                                'capabilities': caps,
                            })
                if pub_accounts:
                    result.append({
                        'connector_type': reg.connector_type,
                        'connector_name': reg.name,
                        'accounts': pub_accounts,
                    })
            except Exception as e:
                _logger.warning("Error checking publishing for %s: %s", reg.connector_type, e)
        return result

    def action_open_accounts(self):
        """Abre la vista de cuentas del conector seleccionado."""
        self.ensure_one()
        if not self.is_installed or self.account_model not in self.env:
            return {'type': 'ir.actions.act_window_close'}

        return {
            'type': 'ir.actions.act_window',
            'name': 'Cuentas - %s' % self.name,
            'res_model': self.account_model,
            'view_mode': f'{view_mode_tree},form',
            'target': 'current',
        }
