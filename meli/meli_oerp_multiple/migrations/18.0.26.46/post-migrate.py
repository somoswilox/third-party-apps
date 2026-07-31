# -*- coding: utf-8 -*-
"""Backfill: asegurar que los Vendedores ML / Equipos de ventas ML ya configurados
tengan el grupo MercadoLibre Manager (sin él, el cron de pedidos —que corre como ese
usuario— falla con AccessError sobre los modelos meli manager-only).

Reusa la lógica del mixin mercadolibre.seller.perms.mixin (DRY)."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    configs = env['mercadolibre.configuration'].search([])
    companies = env['res.company'].search([])
    if not (configs or companies):
        return

    groups = configs._meli_required_groups()
    if not groups:
        _logger.warning("meli 26.46 backfill: grupo MercadoLibre Manager no encontrado, skip.")
        return

    fld = configs._meli_groups_field()
    users = configs._meli_seller_users() | companies._meli_seller_users()
    to_add = users.filtered(lambda u: groups - u[fld])
    if to_add:
        to_add.sudo().write({fld: [(4, g.id) for g in groups]})
        _logger.info(
            "meli 26.46 backfill: agregado MercadoLibre Manager a Vendedor/Equipo ML: %s",
            ", ".join(to_add.mapped('login')),
        )
