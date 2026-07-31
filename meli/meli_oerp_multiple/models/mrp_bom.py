# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    # Minimum stock threshold for this BOM's kit
    # This is the minimum potential_kits across ALL components of the parent BOM
    # Used for fast bottleneck detection: if component's potential > this, skip update
    meli_min_stock_threshold = fields.Float(
        string='ML Min Stock Threshold',
        help='Minimum potential kits for this BOM (bottleneck value). '
             'If a component can produce more kits than this, it is not the bottleneck.',
        default=0,
        index=True
    )

    meli_threshold_updated = fields.Datetime(
        string='Threshold Updated',
        help='Last time the threshold was calculated'
    )

    meli_bottleneck_product_id = fields.Many2one(
        'product.product',
        string='Componente cuello de botella',
        help='El componente con menor stock disponible que limita la producción de kits'
    )

    def _compute_bom_min_threshold(self):
        """
        Calculate the minimum potential_kits for each BOM.

        For each BOM, finds the component with the LOWEST potential_kits
        (the bottleneck) and stores that value in all lines of the BOM.

        This allows fast comparison: if component.potential > threshold, skip.
        """
        if not self:
            return

        # Group lines by BOM
        bom_ids = set(line.bom_id.id for line in self if line.bom_id)

        if not bom_ids:
            return

        # Calculate minimum potential_kits per BOM AND find bottleneck component
        # NOTE: qty_available is computed, use stock_quant instead
        self.env.cr.execute("""
            WITH component_potential AS (
                SELECT
                    bl.bom_id,
                    bl.product_id,
                    pp.default_code,
                    COALESCE(sq.qty_sum, 0) as qty_available,
                    COALESCE(bl.product_qty, 1) as qty_needed,
                    COALESCE(sq.qty_sum, 0) / NULLIF(COALESCE(bl.product_qty, 1), 0) as potential_kits
                FROM mrp_bom_line bl
                JOIN mrp_bom b ON b.id = bl.bom_id AND b.active = True
                JOIN product_product pp ON pp.id = bl.product_id
                LEFT JOIN (
                    SELECT product_id, SUM(quantity) as qty_sum
                    FROM stock_quant
                    WHERE location_id IN (
                        SELECT id FROM stock_location WHERE usage = 'internal'
                    )
                    GROUP BY product_id
                ) sq ON sq.product_id = bl.product_id
                WHERE bl.bom_id IN %s
            ),
            bom_min AS (
                SELECT bom_id, MIN(potential_kits) as min_potential
                FROM component_potential
                GROUP BY bom_id
            )
            SELECT
                cp.bom_id,
                cp.product_id as bottleneck_product_id,
                cp.default_code as bottleneck_sku,
                cp.qty_available as bottleneck_qty,
                bm.min_potential as min_potential_kits
            FROM component_potential cp
            JOIN bom_min bm ON bm.bom_id = cp.bom_id
                AND cp.potential_kits = bm.min_potential
        """, (tuple(bom_ids),))

        bom_data = {}
        for row in self.env.cr.fetchall():
            bom_id, bottleneck_product_id, bottleneck_sku, bottleneck_qty, min_potential = row
            # Only keep first bottleneck if multiple components have same potential
            if bom_id not in bom_data:
                bom_data[bom_id] = {
                    'threshold': min_potential if min_potential is not None else 0,
                    'bottleneck_product_id': bottleneck_product_id,
                    'bottleneck_sku': bottleneck_sku or '',
                    'bottleneck_qty': bottleneck_qty or 0,
                }

        # Update all lines with their BOM's threshold and bottleneck
        now = fields.Datetime.now()
        for line in self:
            if line.bom_id and line.bom_id.id in bom_data:
                data = bom_data[line.bom_id.id]
                line.write({
                    'meli_min_stock_threshold': data['threshold'],
                    'meli_threshold_updated': now,
                    'meli_bottleneck_product_id': data['bottleneck_product_id'],
                })

        # Update BOM level fields (including stored threshold for filtering)
        bom_obj = self.env['mrp.bom']
        for bom_id, data in bom_data.items():
            bom_obj.browse(bom_id).write({
                'meli_bottleneck_product_id': data['bottleneck_product_id'],
                'meli_bottleneck_qty': data['bottleneck_qty'],
                'meli_threshold_stored': data['threshold'],
            })

        _logger.info(
            "MELI_THRESHOLD: Updated %d BOM lines across %d BOMs",
            len(self), len(bom_data)
        )

        return {bom_id: d['threshold'] for bom_id, d in bom_data.items()}


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    # Stored fields updated by _compute_bom_min_threshold
    meli_bottleneck_product_id = fields.Many2one(
        'product.product',
        string='Cuello de botella',
        help='El componente con menor stock disponible que limita la producción de kits'
    )

    meli_bottleneck_qty = fields.Float(
        string='Stock del cuello de botella',
        help='Cantidad disponible del componente cuello de botella'
    )

    # Stored threshold for filtering (updated by _compute_bom_min_threshold)
    meli_threshold_stored = fields.Float(
        string='ML Threshold (Stored)',
        help='Cantidad de kits posibles (almacenado para filtros)',
        default=0,
        index=True
    )

    # Computed field to show threshold in BOM list view (reads from lines or stored)
    meli_min_stock_threshold = fields.Float(
        string='ML Threshold',
        compute='_compute_meli_min_stock_threshold',
        store=False,
        help='Minimum potential kits for this BOM (bottleneck value from components)'
    )

    # Status field for badge coloring
    meli_stock_level = fields.Selection([
        ('sin_stock', 'Sin Stock'),
        ('stock_bajo', 'Stock Bajo'),
        ('stock_ok', 'Stock OK'),
    ], string='Nivel de Stock', compute='_compute_meli_stock_display', store=False)

    # Combined display field with descriptive text
    meli_stock_display = fields.Char(
        string='Estado de Stock ML',
        compute='_compute_meli_stock_display',
        store=False,
        help='Información combinada del threshold y cuello de botella'
    )

    @api.depends('bom_line_ids.meli_min_stock_threshold', 'meli_bottleneck_product_id', 'meli_bottleneck_qty')
    def _compute_meli_min_stock_threshold(self):
        """Get the threshold from BOM lines (all lines have the same value)."""
        for bom in self:
            if bom.bom_line_ids:
                # All lines should have the same threshold, take first
                threshold = 0
                for line in bom.bom_line_ids:
                    threshold = line.meli_min_stock_threshold
                    if threshold > 0:
                        break
                bom.meli_min_stock_threshold = threshold
            else:
                bom.meli_min_stock_threshold = 0

    @api.depends('meli_min_stock_threshold', 'meli_bottleneck_product_id', 'meli_bottleneck_qty')
    def _compute_meli_stock_display(self):
        """Compute the combined stock display and level for badge coloring."""
        for bom in self:
            threshold = bom.meli_min_stock_threshold
            bottleneck = bom.meli_bottleneck_product_id
            bottleneck_qty = bom.meli_bottleneck_qty

            if threshold == 0:
                # Sin stock - componente faltante
                bom.meli_stock_level = 'sin_stock'
                if bottleneck:
                    sku = bottleneck.default_code or bottleneck.name or 'N/A'
                    bom.meli_stock_display = f"SIN STOCK - Falta: {sku} (0 uds)"
                else:
                    bom.meli_stock_display = "SIN STOCK - Componente faltante"
            elif threshold < 5:
                # Stock bajo
                bom.meli_stock_level = 'stock_bajo'
                if bottleneck:
                    sku = bottleneck.default_code or bottleneck.name or 'N/A'
                    bom.meli_stock_display = f"{int(threshold)} kits - Limitado por: {sku} ({int(bottleneck_qty)} uds)"
                else:
                    bom.meli_stock_display = f"{int(threshold)} kits posibles (stock bajo)"
            else:
                # Stock OK
                bom.meli_stock_level = 'stock_ok'
                if bottleneck:
                    sku = bottleneck.default_code or bottleneck.name or 'N/A'
                    bom.meli_stock_display = f"{int(threshold)} kits - Mín: {sku} ({int(bottleneck_qty)} uds)"
                else:
                    bom.meli_stock_display = f"{int(threshold)} kits posibles"

    def action_update_meli_thresholds(self):
        """
        Action button to update ML thresholds for all lines in selected BOMs.
        """
        for bom in self:
            if bom.bom_line_ids:
                bom.bom_line_ids._compute_bom_min_threshold()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thresholds Updated',
                'message': f'Updated ML stock thresholds for {len(self)} BOM(s)',
                'type': 'success',
            }
        }

    @api.model
    def cron_update_meli_thresholds(self, limit=500):
        """
        Cron job to update ML thresholds for BOMs.

        Prioritizes BOMs that haven't been updated recently or have
        lines without threshold values.
        """
        # Find BOM lines that need updating (no threshold or old)
        lines_to_update = self.env['mrp.bom.line'].search([
            ('bom_id.active', '=', True),
            '|',
            ('meli_min_stock_threshold', '=', 0),
            ('meli_threshold_updated', '=', False)
        ], limit=limit)

        if lines_to_update:
            lines_to_update._compute_bom_min_threshold()
            _logger.info(
                "MELI_THRESHOLD CRON: Updated %d BOM lines",
                len(lines_to_update)
            )

        return True
