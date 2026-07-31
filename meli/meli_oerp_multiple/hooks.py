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

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Post-init hook to create CRON status records for existing accounts.
    This runs after module installation/update to ensure all accounts
    have their CRON status records properly initialized.

    Args:
        env: Odoo Environment object
    """
    _logger.info("meli_oerp_multiple: Running post_init_hook to initialize CRON status records")

    # Get all existing MercadoLibre accounts
    accounts = env['mercadolibre.account'].search([])

    if not accounts:
        _logger.info("meli_oerp_multiple: No existing accounts found, skipping CRON status initialization")
        return

    _logger.info(f"meli_oerp_multiple: Found {len(accounts)} accounts, initializing CRON status records")

    # Define all CRON types
    cron_types = [
        'orders', 'stock', 'stock_rt', 'products_post',
        'products_get', 'price', 'internal_jobs', 'questions', 'process',
        'batch_update', 'stock_diagnostic',
    ]

    CronStatus = env['mercadolibre.cron.status']
    created_count = 0

    for account in accounts:
        # Get existing CRON status types for this account
        existing_types = account.cron_status_ids.mapped('cron_type')

        for cron_type in cron_types:
            if cron_type not in existing_types:
                try:
                    CronStatus.create({
                        'connection_account': account.id,
                        'cron_type': cron_type,
                        'is_enabled': True,
                    })
                    created_count += 1
                except Exception as e:
                    _logger.warning(
                        f"meli_oerp_multiple: Could not create CRON status {cron_type} "
                        f"for account {account.name}: {e}"
                    )

    _logger.info(f"meli_oerp_multiple: Created {created_count} CRON status records")

    # Fix individual crons stuck at numbercall=0 or with a past nextcall that never advanced
    from odoo import fields as odoo_fields
    broken_crons = env['ir.cron'].sudo().search([
        ('name', 'like', '[MELI-'),
        ('active', '=', True),
        ('numbercall', '=', 0),
    ])
    if broken_crons:
        broken_crons.write({'numbercall': -1})
        _logger.info(
            "meli_oerp_multiple: Fixed %d individual Meli crons stuck at numbercall=0",
            len(broken_crons)
        )

    # Reset nextcall to now for stuck individual crons so they run on the next scheduler tick
    stuck_crons = env['ir.cron'].sudo().search([
        ('name', 'like', '[MELI-'),
        ('active', '=', True),
        ('nextcall', '<', odoo_fields.Datetime.now()),
    ])
    if stuck_crons:
        stuck_crons.write({'nextcall': odoo_fields.Datetime.now()})
        _logger.info(
            "meli_oerp_multiple: Reset nextcall for %d stuck individual Meli crons",
            len(stuck_crons)
        )
