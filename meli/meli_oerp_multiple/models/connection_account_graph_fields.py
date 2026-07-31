# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MercadoLibreAccountGraphs(models.Model):
    _inherit = "mercadolibre.account"

# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MercadoLibreProductKPI(models.Model):
    _inherit = "mercadolibre.product"

    # Buckets for the Publications pie (exact labels you defined)
    kpi_sync_bucket = fields.Selection([
        ('synced_active', "Synced & Active"),
        ('synced_pause', "Synced & Pause"),
        ('synced_updating', "Synced Updating"),
        ('synced_updated_problems', "Synced Updated w/ Problems"),
        ('error', "Error"),
        ('unsynced', "Unsynced"),
    ], compute='_compute_kpi_sync_bucket', store=True, index=True)

    @api.depends('meli_stock_status', 'meli_last_status')
    def _compute_kpi_sync_bucket(self):
        """Map stored ML fields to the dashboard buckets.

        Uses only stored fields (searchable). If meli_last_status isn't maintained,
        'updated' entries fall back to Synced & Active.
        """
        error_states = {
            'revision_error', 'revision_blocked', 'revision_fulfillment',
            'revision_has_bids', 'revision_under_review',
            'revision_closed', 'revision_inactive',
        }
        for rec in self:
            bucket = False
            mss = rec.meli_stock_status  # stored selection
            if mss == 'update':
                bucket = 'synced_updating'
            elif mss == 'updated_with_warning':
                bucket = 'synced_updated_problems'
            elif mss in error_states:
                bucket = 'error'
            elif mss == 'updated':
                # Split updated into Active/Pause using last known status if present
                if hasattr(rec, 'meli_last_status') and rec.meli_last_status:
                    if rec.meli_last_status == 'active':
                        bucket = 'synced_active'
                    elif rec.meli_last_status == 'paused':
                        bucket = 'synced_pause'
                    else:
                        bucket = 'synced_active'
                else:
                    bucket = 'synced_active'
            else:
                # If you have a proper unsynced flag/logic, map it here.
                # Fallback: leave False (won't show) or mark as 'unsynced' if you prefer.
                bucket = False

            # If you track explicit unsynced flags, override here:
            if not bucket and hasattr(rec, 'is_unsynced') and rec.is_unsynced:
                bucket = 'unsynced'

            rec.kpi_sync_bucket = bucket


    # Feeds the SALES pie (group by: status)
    ml_order_ids = fields.One2many(
        'mercadolibre.orders', 'connection_account', string='ML Orders'
    )

    # Feeds the PUBLICATIONS pie (group by: kpi_sync_bucket)
    ml_product_ids = fields.One2many(
        'mercadolibre.product', 'connection_account', string='ML Publications'
    )

    # Feeds the INVOICES pie (group by: payment_state)
    invoice_ids = fields.Many2many(
        'account.move', string='Invoices (customer)',
        compute='_compute_invoice_ids', compute_sudo=True
    )

    @api.depends('ml_order_ids')
    def _compute_invoice_ids(self):
        """Collect customer invoices tied to sale orders created from this account’s ML orders."""
        for acc in self:
            moves = self.env['account.move'].sudo().browse([])
            # From ML orders -> sale orders -> invoices
            sos = acc.ml_order_ids.mapped('sale_order')
            if sos:
                # Use the relation directly to avoid fragile origin matching
                moves = sos.mapped('invoice_ids').filtered(lambda m: m.move_type == 'out_invoice' and m.state != 'cancel')
            acc.invoice_ids = [(6, 0, moves.ids)]
