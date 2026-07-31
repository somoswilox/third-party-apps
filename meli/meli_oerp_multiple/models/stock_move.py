# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.tools.translate import _
import logging
import time
import json
_logger = logging.getLogger(__name__)

# Benchmark threshold in seconds - only log detailed benchmarks if total time exceeds this
MELI_BENCHMARK_THRESHOLD = 0.5

# Module-level cache for log setting (cleared on each new request via _meli_log_cache_clear)
_meli_log_cache = {}

# Threshold for deferring updates to internal_job notification (avoids lock contention)
# Above this threshold, we create a notification instead of updating directly
MELI_DEFERRED_UPDATE_THRESHOLD = 50

# Component-level coalescing thresholds
# Components affecting >= this many BOMs are considered "significant" and tracked separately
MELI_SIGNIFICANT_BOM_COUNT = 10
# Time window for coalescing (seconds) - combine updates within this window
MELI_COALESCE_WINDOW_SECONDS = 60
# Quantity delta threshold - if cumulative change exceeds this %, force immediate processing
MELI_QTY_DELTA_FORCE_PERCENT = 20

# Bottleneck detection threshold
# If component can produce > this many kits, it's probably NOT the bottleneck
# and we skip updating those BOMs (no real impact on kit availability)
# Example: B-700 with 1296 stock, used 1 per kit = 1296 potential kits
#          If threshold=100, we skip updating those 415 BOMs
#          because B-700 is clearly not limiting kit production
MELI_BOTTLENECK_POTENTIAL_KITS = 100

# Intelligent bottleneck detection: compare with actual BOM minimum
# If True: calculates real minimum potential_kits across ALL components per BOM
# If False: uses static MELI_BOTTLENECK_POTENTIAL_KITS threshold
MELI_USE_INTELLIGENT_BOTTLENECK = True

# Buffer for near-bottleneck detection (percentage)
# If component's potential_kits is within this % of the BOM's minimum,
# consider it "near bottleneck" and include for update
# Example: min=36, buffer=20% → include if potential_kits < 36 * 1.2 = 43.2
MELI_BOTTLENECK_BUFFER_PERCENT = 20


class stock_move(models.Model):

    _inherit = "stock.move"

    def _meli_log_enabled(self):
        """
        Check if MELI debug logging is enabled via meli_cron_log_chatter.
        Uses module-level cache to avoid repeated DB lookups within the same request.
        Returns True if any account for this company has logging enabled.
        """
        global _meli_log_cache
        company_id = self.env.company.id
        cache_key = f"log_enabled_{company_id}"

        if cache_key not in _meli_log_cache:
            account = self.env['mercadolibre.account'].sudo().search([
                ('company_id', '=', company_id),
                ('meli_cron_log_chatter', '=', True)
            ], limit=1)
            _meli_log_cache[cache_key] = bool(account)

        return _meli_log_cache[cache_key]

    def _get_meli_products_to_update(self):
        """
        Helper method to collect product IDs affected by stock moves.
        Returns tuple: (products_to_update set, benchmark_data dict)
        BENCHMARKED: Tracks timing and counts for analysis.
        """
        t_start = time.time()
        benchmark_data = {
            'moves_count': len(self),
            'move_products': 0,
            'bomlines_found': 0,
            'bom_parent_products': 0,
        }

        products_to_update = set()
        move_product_ids = set()

        # STEP 1: Collect direct products from moves
        t1 = time.time()
        for st in self:
            if st.product_id:
                move_product_ids.add(st.product_id.id)
                products_to_update.add(st.product_id.id)
        benchmark_data['move_products'] = len(move_product_ids)
        benchmark_data['t_collect_moves'] = time.time() - t1

        # STEP 2: BOM SECTION - batch query for all parent KITs
        t2 = time.time()
        bom_parents_added = 0
        if move_product_ids and "mrp.bom" in self.env:
            # Only include active (non-archived) BOMs
            bomlines = self.env['mrp.bom.line'].sudo().search([
                ('product_id', 'in', list(move_product_ids)),
                ('bom_id.active', '=', True)
            ])
            benchmark_data['bomlines_found'] = len(bomlines)

            if self._meli_log_enabled():
                _logger.info(
                    "MELI_DEBUG _get_meli_products_to_update BOM search: "
                    "move_products=%s, bomlines_found=%d",
                    list(move_product_ids)[:5], len(bomlines)
                )

            for bomline in bomlines:
                if not bomline.bom_id:
                    continue

                bm_product_id = bomline.bom_id.product_id
                bm_product_tmpl_id = bomline.bom_id.product_tmpl_id

                if bm_product_id:
                    if bm_product_id.id not in products_to_update:
                        bom_parents_added += 1
                    products_to_update.add(bm_product_id.id)
                elif bm_product_tmpl_id:
                    for variant in bm_product_tmpl_id.product_variant_ids:
                        if variant.id not in products_to_update:
                            bom_parents_added += 1
                        products_to_update.add(variant.id)

        benchmark_data['bom_parent_products'] = bom_parents_added
        benchmark_data['t_bom_search'] = time.time() - t2
        benchmark_data['total_products'] = len(products_to_update)
        benchmark_data['t_total'] = time.time() - t_start

        return products_to_update, benchmark_data

    def _get_component_update_threshold(self, component_id, bom_ids):
        """
        Calculate the UPDATE THRESHOLD for a component based on its BOMs.

        The threshold = MAX of all BOM minimums (principal component stocks).

        Logic:
          - Each BOM has a "bottleneck" (component with lowest potential_kits)
          - If component's stock > MAX(all bottlenecks), it can't be limiting ANY kit
          - Only when component stock drops below this MAX does it become relevant

        Example for B-700 used in 3 kits:
          - KIT1: Principal Screen1 = 36 → BOM min = 36
          - KIT2: Principal Screen2 = 45 → BOM min = 45
          - KIT3: Principal Screen3 = 21 → BOM min = 21

          THRESHOLD = MAX(36, 45, 21) = 45

          B-700 stock 1296 > 45 → SKIP ALL (not bottleneck anywhere)
          B-700 stock 40 <= 45 → COULD be bottleneck → update

        Returns: (threshold, bom_details dict)
        """
        if not bom_ids:
            return 0, {}

        # SQL to get minimum potential_kits per BOM, excluding the component itself
        # We want to know what the bottleneck is WITHOUT this component
        # NOTE: qty_available is a computed field, we need to get it from stock_quant
        self.env.cr.execute("""
            SELECT
                bl.bom_id,
                MIN(
                    COALESCE(sq.qty_sum, 0) /
                    NULLIF(COALESCE(bl.product_qty, 1), 0)
                ) as min_potential_kits
            FROM mrp_bom_line bl
            LEFT JOIN (
                SELECT product_id, SUM(quantity) as qty_sum
                FROM stock_quant
                WHERE location_id IN (
                    SELECT id FROM stock_location WHERE usage = 'internal'
                )
                GROUP BY product_id
            ) sq ON sq.product_id = bl.product_id
            WHERE bl.bom_id IN %s
              AND bl.product_id != %s
            GROUP BY bl.bom_id
        """, (tuple(bom_ids), component_id))

        bom_details = {}
        max_threshold = 0
        for row in self.env.cr.fetchall():
            bom_id, min_potential = row
            min_val = min_potential if min_potential is not None else 0
            bom_details[bom_id] = min_val
            if min_val > max_threshold:
                max_threshold = min_val

        return max_threshold, bom_details

    def _get_bom_minimum_potential_kits(self, bom_ids):
        """
        Calculate the ACTUAL minimum potential_kits for each BOM.

        This queries ALL components of each BOM and finds the true bottleneck.
        Returns dict: {bom_id: min_potential_kits}

        Example for BOM A01:
          - Screen: 36 stock / 1 needed = 36 potential
          - B-700: 1296 stock / 1 needed = 1296 potential
          - Screws: 5000 stock / 4 needed = 1250 potential
          → Returns {bom_a01_id: 36}  (Screen is bottleneck)
        """
        if not bom_ids:
            return {}

        # SQL to get minimum potential_kits per BOM across all components
        # NOTE: qty_available is a computed field, we need to get it from stock_quant
        self.env.cr.execute("""
            SELECT
                bl.bom_id,
                MIN(
                    COALESCE(sq.qty_sum, 0) /
                    NULLIF(COALESCE(bl.product_qty, 1), 0)
                ) as min_potential_kits
            FROM mrp_bom_line bl
            LEFT JOIN (
                SELECT product_id, SUM(quantity) as qty_sum
                FROM stock_quant
                WHERE location_id IN (
                    SELECT id FROM stock_location WHERE usage = 'internal'
                )
                GROUP BY product_id
            ) sq ON sq.product_id = bl.product_id
            WHERE bl.bom_id IN %s
            GROUP BY bl.bom_id
        """, (tuple(bom_ids),))

        result = {}
        for row in self.env.cr.fetchall():
            bom_id, min_potential = row
            result[bom_id] = min_potential if min_potential is not None else 0

        return result

    def _get_significant_components(self, move_product_ids):
        """
        Identify "significant" components - those used in many BOMs.

        A component like B-700 used in 415 BOMs is "significant" because:
        - One sale triggers 415 product updates
        - Multiple concurrent sales cause massive lock contention
        - These are the primary candidates for coalescing

        THRESHOLD-BASED BOTTLENECK DETECTION:
        For each component, calculates a single threshold = MAX of all principal
        component stocks across its BOMs. If component stock > threshold,
        it cannot be the bottleneck for ANY kit.

        Example for B-700 in 3 kits:
          - KIT1: Principal Screen1 = 36 stock
          - KIT2: Principal Screen2 = 45 stock
          - KIT3: Principal Screen3 = 21 stock
          THRESHOLD = MAX(36, 45, 21) = 45

          B-700 stock 1296 > 45 → SKIP ALL (not bottleneck anywhere)
          B-700 stock 40 <= 45 → UPDATE (could be bottleneck)

        Returns:
            dict: {component_id: {
                'bom_count': N,
                'bom_parent_ids': set() - all BOM parents (if below threshold),
                'bom_parent_ids_skipped': set() - all BOM parents (if above threshold),
                'qty_on_hand': X,
                'is_bottleneck_anywhere': bool,
                'threshold': calculated threshold for this component
            }}
        """
        significant = {}

        if not move_product_ids or "mrp.bom" not in self.env:
            return significant

        # Query all BOM lines for these components (only active BOMs)
        bomlines = self.env['mrp.bom.line'].sudo().search([
            ('product_id', 'in', list(move_product_ids)),
            ('bom_id.active', '=', True)
        ])

        # Group by component, tracking BOM details
        component_boms = {}
        for bomline in bomlines:
            comp_id = bomline.product_id.id
            if comp_id not in component_boms:
                component_boms[comp_id] = {
                    'bomlines': [],
                    'bom_details': {},  # bom_id -> {parent_ids, qty_needed}
                    'product': bomline.product_id
                }
            component_boms[comp_id]['bomlines'].append(bomline)

            # Track BOM details including qty needed and precalculated threshold
            if bomline.bom_id:
                bom_id = bomline.bom_id.id
                if bom_id not in component_boms[comp_id]['bom_details']:
                    parent_ids = set()
                    if bomline.bom_id.product_id:
                        parent_ids.add(bomline.bom_id.product_id.id)
                    elif bomline.bom_id.product_tmpl_id:
                        for variant in bomline.bom_id.product_tmpl_id.product_variant_ids:
                            parent_ids.add(variant.id)

                    # Get precalculated threshold from bomline (if available)
                    precalc_threshold = getattr(bomline, 'meli_min_stock_threshold', 0) or 0

                    component_boms[comp_id]['bom_details'][bom_id] = {
                        'parent_ids': parent_ids,
                        'qty_needed': bomline.product_qty or 1,
                        'bom': bomline.bom_id,
                        'precalc_threshold': precalc_threshold,
                    }

        # Calculate buffer multiplier (e.g., 20% buffer = 1.2x)
        buffer_multiplier = 1 + (MELI_BOTTLENECK_BUFFER_PERCENT / 100)

        # Process each significant component
        for comp_id, data in component_boms.items():
            bom_count = len(data['bom_details'])
            if bom_count < MELI_SIGNIFICANT_BOM_COUNT:
                continue

            product = data['product']
            qty_on_hand = product.qty_available or 0
            default_code = product.default_code or ''

            # Collect all BOM parent IDs
            all_bom_parents = set()
            all_bom_ids = list(data['bom_details'].keys())
            for bom_info in data['bom_details'].values():
                all_bom_parents.update(bom_info['parent_ids'])

            # Calculate component potential (average across BOMs)
            total_qty_needed = sum(b['qty_needed'] for b in data['bom_details'].values())
            avg_qty_needed = total_qty_needed / bom_count if bom_count > 0 else 1
            component_potential = qty_on_hand / avg_qty_needed if avg_qty_needed > 0 else float('inf')

            # INTELLIGENT BOTTLENECK DETECTION
            # Strategy:
            # 1. Try to use precalculated thresholds from meli_min_stock_threshold field
            # 2. If not available, fallback to SQL calculation
            # 3. Per-BOM decision: if component's potential > BOM's threshold, skip that BOM

            impacted_parents = set()
            skipped_parents = set()
            is_bottleneck = False

            # Check if we have precalculated thresholds for most BOMs
            precalc_available = sum(1 for b in data['bom_details'].values() if b.get('precalc_threshold', 0) > 0)
            use_precalc = precalc_available >= len(data['bom_details']) * 0.5  # Use if >50% have it

            if use_precalc and MELI_USE_INTELLIGENT_BOTTLENECK:
                # FAST PATH: Use precalculated thresholds per BOM
                for bom_id, bom_info in data['bom_details'].items():
                    bom_threshold = bom_info.get('precalc_threshold', 0)
                    if bom_threshold > 0:
                        threshold_with_buffer = bom_threshold * buffer_multiplier
                        if component_potential <= threshold_with_buffer:
                            # Component IS bottleneck for this BOM
                            impacted_parents.update(bom_info['parent_ids'])
                            is_bottleneck = True
                        else:
                            # Component is NOT bottleneck for this BOM
                            skipped_parents.update(bom_info['parent_ids'])
                    else:
                        # No threshold, be conservative: include it
                        impacted_parents.update(bom_info['parent_ids'])
                        is_bottleneck = True

                threshold = max(b.get('precalc_threshold', 0) for b in data['bom_details'].values())
                decision = "PRECALC"

            elif MELI_USE_INTELLIGENT_BOTTLENECK:
                # FALLBACK: Calculate threshold dynamically via SQL
                threshold, bom_mins = self._get_component_update_threshold(comp_id, all_bom_ids)
                threshold_with_buffer = threshold * buffer_multiplier

                # Single comparison: is component above the threshold?
                is_bottleneck = component_potential <= threshold_with_buffer

                if is_bottleneck:
                    impacted_parents = all_bom_parents
                else:
                    skipped_parents = all_bom_parents

                decision = "SQL_CALC"
            else:
                # SIMPLE: Use static threshold
                threshold = MELI_BOTTLENECK_POTENTIAL_KITS
                threshold_with_buffer = threshold
                is_bottleneck = component_potential <= threshold

                if is_bottleneck:
                    impacted_parents = all_bom_parents
                else:
                    skipped_parents = all_bom_parents

                decision = "STATIC"

            significant[comp_id] = {
                'bom_count': bom_count,
                'bom_parent_ids': impacted_parents,
                'bom_parent_ids_skipped': skipped_parents,
                'qty_on_hand': qty_on_hand,
                'default_code': default_code,
                'is_bottleneck_anywhere': is_bottleneck,
                'potential_kits_avg': component_potential,
                'threshold': threshold,
                'threshold_with_buffer': threshold_with_buffer,
                'decision_method': decision,
            }

            # Log decision only if logging is enabled
            if self._meli_log_enabled():
                action = "UPDATE" if is_bottleneck else "SKIP"
                _logger.info(
                    "MELI_BOTTLENECK_%s %s: stock=%d, potential=%.0f, threshold=%.0f | "
                    "%d BOMs → %s (%d impacted, %d skipped)",
                    decision, default_code, qty_on_hand,
                    component_potential, threshold_with_buffer,
                    bom_count, action,
                    len(impacted_parents), len(skipped_parents)
                )

        return significant

    def _coalesce_component_notification(self, component_ids, account):
        """
        Find and update existing pending notification for these components.

        COALESCING LOGIC:
        - Look for recent RECEIVED notification with topic='component_stock_update'
        - If found within MELI_COALESCE_WINDOW_SECONDS, merge component_ids into it
        - Return the notification (new or updated)

        This is the key to avoiding 10 notifications for 10 B-700 sales.
        Instead: 1 notification tracks all components, processed once.
        """
        from datetime import datetime, timedelta

        # Search for recent pending notifications for component stock updates
        cutoff_time = datetime.utcnow() - timedelta(seconds=MELI_COALESCE_WINDOW_SECONDS)

        existing_noti = self.env['mercadolibre.notification'].sudo().search([
            ('connection_account', '=', account.id),
            ('topic', '=', 'component_stock_update'),
            ('state', '=', 'RECEIVED'),
            ('create_date', '>=', cutoff_time.strftime('%Y-%m-%d %H:%M:%S')),
        ], limit=1, order='create_date desc')

        if existing_noti:
            # Merge into existing notification
            try:
                existing_comp_ids = set(json.loads(existing_noti.model_ids or '[]'))
                merged_comp_ids = existing_comp_ids | component_ids

                if merged_comp_ids != existing_comp_ids:
                    existing_noti.sudo().write({
                        'model_ids': json.dumps(list(merged_comp_ids)),
                        'model_ids_count': len(merged_comp_ids),
                        'resource': f"component_stock_update #{len(merged_comp_ids)} components (coalesced)",
                    })
                    if self._meli_log_enabled():
                        _logger.info(
                            "MELI_COALESCE: Merged %d components into existing notification %s "
                            "(now %d components, window=%ds)",
                            len(component_ids), existing_noti.id,
                            len(merged_comp_ids), MELI_COALESCE_WINDOW_SECONDS
                        )
                return existing_noti
            except (json.JSONDecodeError, Exception) as e:
                _logger.warning("MELI_COALESCE: Failed to parse existing notification: %s", e)

        return None

    def _create_component_stock_notification(self, component_ids, significant_data, benchmark_data):
        """
        Create notification for component-based stock update.

        DIFFERENCE FROM _create_deferred_stock_update_notification:
        - Stores COMPONENT IDs, not all affected product IDs
        - Topic is 'component_stock_update' for separate processing
        - Cron expands components → BOM parents at process time

        For B-700 (415 BOMs):
        - OLD: Store [415 product IDs] per sale
        - NEW: Store [B-700 component ID], expand later

        10 sales of B-700:
        - OLD: 10 notifications × 415 products = 4150 potential updates
        - NEW: 1 coalesced notification with [B-700], expand once = 415 updates
        """
        t_start = time.time()

        # Get account
        accounts = self.env['mercadolibre.account'].sudo().search([
            ('company_id', '=', self.env.company.id)
        ], limit=1)
        if not accounts:
            accounts = self.env['mercadolibre.account'].sudo().search([], limit=1)
        if not accounts:
            return False

        account = accounts[0]

        # Try to coalesce with existing notification
        existing = self._coalesce_component_notification(component_ids, account)
        if existing:
            return existing

        # Build component summary for logging
        comp_summary = []
        for comp_id in component_ids:
            if comp_id in significant_data:
                d = significant_data[comp_id]
                comp_summary.append(f"{d['default_code']}:{d['bom_count']}boms")

        # Create new notification
        internals = {
            "application_id": account.client_id or "stock_move",
            "user_id": account.seller_id or "system",
            "topic": "component_stock_update",
            "resource": f"component_stock_update #{len(component_ids)} components: {','.join(comp_summary[:5])}",
            "state": "RECEIVED",
            "model_ids": json.dumps(list(component_ids)),
            "model_ids_count": len(component_ids),
            "model_ids_count_processed": 0,
        }

        try:
            noti = self.env["mercadolibre.notification"].sudo().start_internal_notification(
                internals=internals,
                account=account
            )

            if self._meli_log_enabled():
                t_total = time.time() - t_start
                total_boms = sum(significant_data.get(c, {}).get('bom_count', 0) for c in component_ids)
                _logger.info(
                    "MELI_BENCHMARK _create_component_stock_notification: "
                    "notification=%s, components=%d, total_affected_boms=%d, time=%.3fs | "
                    "components: %s",
                    noti.id if noti else "FAILED",
                    len(component_ids),
                    total_boms,
                    t_total,
                    comp_summary
                )

            return noti

        except Exception as e:
            _logger.error(
                "MELI_BENCHMARK _create_component_stock_notification FAILED: %s",
                e, exc_info=True
            )
            return False

    def _create_deferred_stock_update_notification(self, product_ids, benchmark_data):
        """
        Create an internal_job notification for deferred stock update processing.

        This is used when the number of products to update exceeds MELI_DEFERRED_UPDATE_THRESHOLD.
        Instead of updating products directly (which causes lock contention with concurrent sales),
        we create a notification that will be processed by the cron job.

        Benefits:
        - Stock move completes instantly (single INSERT vs thousands of UPDATEs)
        - No lock contention between concurrent sales
        - Cron processes updates serially, avoiding serialization errors
        - Natural deduplication: same product in multiple notifications gets updated once

        The cron job (cron_meli_process_internal_jobs) will process these notifications
        via meli_update_remote_stock_injobs().
        """
        t_start = time.time()

        # Find the connection account(s) for these products
        # We need at least one account to create the notification
        accounts = self.env['mercadolibre.account'].sudo().search([
            ('company_id', '=', self.env.company.id)
        ], limit=1)

        if not accounts:
            # Fallback: try to find any account
            accounts = self.env['mercadolibre.account'].sudo().search([], limit=1)

        if not accounts:
            _logger.warning(
                "MELI_BENCHMARK _create_deferred_stock_update_notification: "
                "No MercadoLibre account found, falling back to direct update"
            )
            return False

        account = accounts[0]

        # Create the internal_job notification
        internals = {
            "application_id": account.client_id or "stock_move",
            "user_id": account.seller_id or "system",
            "topic": "internal_job",
            "resource": f"meli_update_remote_stock_deferred #{len(product_ids)} products",
            "state": "RECEIVED",
            "model_ids": json.dumps(list(product_ids)),
            "model_ids_count": len(product_ids),
            "model_ids_count_processed": 0,
        }

        try:
            noti = self.env["mercadolibre.notification"].sudo().start_internal_notification(
                internals=internals,
                account=account
            )

            if self._meli_log_enabled():
                t_total = time.time() - t_start
                _logger.info(
                    "MELI_BENCHMARK _create_deferred_stock_update_notification: "
                    "created notification %s for %d products in %.3fs | "
                    "moves=%d, direct=%d, bom_parents=%d, bomlines=%d",
                    noti.id if noti else "FAILED",
                    len(product_ids),
                    t_total,
                    benchmark_data['moves_count'],
                    benchmark_data['move_products'],
                    benchmark_data['bom_parent_products'],
                    benchmark_data['bomlines_found']
                )

            return noti

        except Exception as e:
            _logger.error(
                "MELI_BENCHMARK _create_deferred_stock_update_notification FAILED: %s",
                e, exc_info=True
            )
            return False

    def _update_meli_bindings(self):
        """
        Helper method to update MeLi bindings for products affected by stock moves.
        Called by _action_assign and _action_done.

        MULTI-SCALE STRATEGY:
        1. Significant components (>= 10 BOMs): Component-level coalescing
           - B-700 used in 415 BOMs → track B-700, expand later
           - 10 B-700 sales in 1 min → 1 coalesced notification instead of 10

        2. Large batches (>= 50 products): Deferred product-based notification
           - Products not related to significant components

        3. Small batches (< 50 products): Update directly

        OPTIMIZED & BENCHMARKED: Uses batch queries and tracks performance.
        """
        if self.env.context.get('meli_skip_stock_update'):
            return

        t_start = time.time()
        try:
            # STEP 1: Collect direct products from moves
            move_product_ids = set()
            for st in self:
                if st.product_id:
                    move_product_ids.add(st.product_id.id)

            if not move_product_ids:
                return

            # STEP 2: Check for significant components (many BOMs)
            t_sig = time.time()
            significant = self._get_significant_components(move_product_ids)
            t_sig_end = time.time()

            # STEP 3: Handle significant components via coalescing
            if significant:
                # These components affect many BOMs - use component-level coalescing
                component_ids = set(significant.keys())
                sig_bom_parents = set()  # BOMs where component IS bottleneck
                sig_bom_skipped = set()  # BOMs where component is NOT bottleneck
                any_bottleneck = False

                for comp_data in significant.values():
                    sig_bom_parents.update(comp_data['bom_parent_ids'])
                    sig_bom_skipped.update(comp_data.get('bom_parent_ids_skipped', set()))
                    if comp_data.get('is_bottleneck_anywhere', False):
                        any_bottleneck = True

                # If NO BOMs are impacted (all skipped due to bottleneck filtering),
                # we can skip the notification entirely!
                if not any_bottleneck and not sig_bom_parents:
                    if self._meli_log_enabled():
                        _logger.info(
                            "MELI_BENCHMARK _update_meli_bindings BOTTLENECK_SKIP: "
                            "components=%d, all %d BOMs skipped (not bottleneck, threshold=%d kits) | "
                            "No update needed!",
                            len(component_ids), len(sig_bom_skipped),
                            MELI_BOTTLENECK_POTENTIAL_KITS
                        )
                    # Still update the component product itself (direct sale)
                    if move_product_ids:
                        products = self.env['product.product'].browse(list(move_product_ids))
                        try:
                            products.process_meli_stock_moves_update()
                        except Exception as e:
                            _logger.debug("Error updating component products: %s", e)
                    return

                # Create coalesced notification for significant components
                benchmark_data = {
                    'moves_count': len(self),
                    'move_products': len(move_product_ids),
                    'significant_components': len(significant),
                    'significant_bom_parents': len(sig_bom_parents),
                    'significant_bom_skipped': len(sig_bom_skipped),
                }

                noti = self._create_component_stock_notification(
                    component_ids, significant, benchmark_data
                )

                if noti:
                    # Also need to update direct products that aren't in BOM hierarchy
                    # These are products sold directly, not just as kit components
                    direct_only = move_product_ids - sig_bom_parents - component_ids - sig_bom_skipped

                    if self._meli_log_enabled():
                        _logger.info(
                            "MELI_BENCHMARK _update_meli_bindings COMPONENT_COALESCE: "
                            "components=%d | impacted=%d BOMs, SKIPPED=%d BOMs (not bottleneck) | "
                            "notification=%s, direct_only=%d",
                            len(component_ids), len(sig_bom_parents), len(sig_bom_skipped),
                            noti.id, len(direct_only)
                        )

                    # Update direct-only products immediately (small set)
                    if direct_only and len(direct_only) < MELI_DEFERRED_UPDATE_THRESHOLD:
                        products = self.env['product.product'].browse(list(direct_only))
                        try:
                            products.process_meli_stock_moves_update()
                        except Exception as e:
                            _logger.debug("Error updating direct-only products: %s", e)

                    return

            # STEP 4: No significant components - use standard product-based approach
            products_to_update, benchmark_data = self._get_meli_products_to_update()
            benchmark_data['t_significant_check'] = t_sig_end - t_sig

            if not products_to_update:
                return

            product_count = len(products_to_update)

            # Large batch: defer to notification
            if product_count >= MELI_DEFERRED_UPDATE_THRESHOLD:
                noti = self._create_deferred_stock_update_notification(
                    products_to_update, benchmark_data
                )
                if noti:
                    if self._meli_log_enabled():
                        _logger.info(
                            "MELI_BENCHMARK _update_meli_bindings DEFERRED: "
                            "%d products queued via notification (threshold=%d)",
                            product_count, MELI_DEFERRED_UPDATE_THRESHOLD
                        )
                    return
                _logger.warning(
                    "MELI_BENCHMARK _update_meli_bindings: "
                    "Deferred notification failed, falling back to direct update"
                )

            # Small batch: update directly
            t_update = time.time()
            products = self.env['product.product'].browse(list(products_to_update))
            try:
                products.process_meli_stock_moves_update()
            except Exception as e:
                _logger.debug("Error in batch meli_stock_moves_update: %s", e)
            t_update_end = time.time()

            t_total = time.time() - t_start

            if self._meli_log_enabled():
                _logger.info(
                    "MELI_BENCHMARK _update_meli_bindings DIRECT: moves=%d, products=%d "
                    "(direct=%d, bom_parents=%d), bomlines=%d, total_time=%.3fs",
                    benchmark_data['moves_count'],
                    benchmark_data['total_products'],
                    benchmark_data['move_products'],
                    benchmark_data['bom_parent_products'],
                    benchmark_data['bomlines_found'],
                    t_total
                )

                if t_total > MELI_BENCHMARK_THRESHOLD:
                    _logger.warning(
                        "MELI_BENCHMARK_DETAIL _update_meli_bindings SLOW (%.3fs): "
                        "sig_check=%.3fs, collect=%.3fs, bom_search=%.3fs, update=%.3fs | Data: %s",
                        t_total,
                        benchmark_data.get('t_significant_check', 0),
                        benchmark_data['t_collect_moves'],
                        benchmark_data['t_bom_search'],
                        t_update_end - t_update,
                        benchmark_data
                    )

        except Exception as e:
            _logger.error(e, exc_info=True)

    def _force_meli_stock_update(self):
        """
        Force meli_stock_moves_update to NOW() for cancel/unreserve operations.

        When a move is cancelled, the MAX(create_date) would go back to an older date,
        which could cause the product to never be picked up by the sync cron.
        By setting the date to NOW(), we ensure the product will be synced.

        MULTI-SCALE STRATEGY (same as _update_meli_bindings):
        1. Significant components (>= 10 BOMs): Component-level coalescing
        2. Large batches (>= 50 products): Deferred notification
        3. Small batches: SQL UPDATE directly

        Uses SQL UPDATE to avoid serialization errors during concurrent access.
        BENCHMARKED: Tracks performance for analysis.
        """
        if self.env.context.get('meli_skip_stock_update'):
            return

        t_start = time.time()
        try:
            # STEP 1: Collect direct products from moves
            move_product_ids = set()
            for st in self:
                if st.product_id:
                    move_product_ids.add(st.product_id.id)

            if not move_product_ids:
                return

            # STEP 2: Check for significant components
            t_sig = time.time()
            significant = self._get_significant_components(move_product_ids)
            t_sig_end = time.time()

            # STEP 3: Handle significant components via coalescing
            if significant:
                component_ids = set(significant.keys())
                sig_bom_parents = set()
                sig_bom_skipped = set()
                any_bottleneck = False

                for comp_data in significant.values():
                    sig_bom_parents.update(comp_data['bom_parent_ids'])
                    sig_bom_skipped.update(comp_data.get('bom_parent_ids_skipped', set()))
                    if comp_data.get('is_bottleneck_anywhere', False):
                        any_bottleneck = True

                # If NO BOMs are impacted, skip notification
                if not any_bottleneck and not sig_bom_parents:
                    if self._meli_log_enabled():
                        _logger.info(
                            "MELI_BENCHMARK _force_meli_stock_update BOTTLENECK_SKIP: "
                            "components=%d, all %d BOMs skipped (not bottleneck)",
                            len(component_ids), len(sig_bom_skipped)
                        )
                    # Still update the component product itself AND its bindings
                    if move_product_ids:
                        self.env.cr.execute("""
                            UPDATE product_product
                            SET meli_stock_moves_update = NOW() AT TIME ZONE 'UTC'
                            WHERE id IN %s
                        """, (tuple(move_product_ids),))
                        self.env['product.product'].invalidate_model(['meli_stock_moves_update'])

                        # Also update bindings for these products
                        self.env.cr.execute("""
                            UPDATE mercadolibre_product mp
                            SET meli_stock_moves_update = NOW() AT TIME ZONE 'UTC',
                                product_meli_stock_moves_update = NOW() AT TIME ZONE 'UTC'
                            WHERE mp.product_id IN %s
                        """, (tuple(move_product_ids),))
                        self.env['mercadolibre.product'].invalidate_model(
                            ['meli_stock_moves_update', 'product_meli_stock_moves_update']
                        )
                    return

                benchmark_data = {
                    'moves_count': len(self),
                    'move_products': len(move_product_ids),
                    'significant_components': len(significant),
                    'significant_bom_parents': len(sig_bom_parents),
                    'significant_bom_skipped': len(sig_bom_skipped),
                }

                noti = self._create_component_stock_notification(
                    component_ids, significant, benchmark_data
                )

                if noti:
                    direct_only = move_product_ids - sig_bom_parents - component_ids - sig_bom_skipped

                    if self._meli_log_enabled():
                        _logger.info(
                            "MELI_BENCHMARK _force_meli_stock_update COMPONENT_COALESCE: "
                            "components=%d | impacted=%d BOMs, SKIPPED=%d | notification=%s",
                            len(component_ids), len(sig_bom_parents), len(sig_bom_skipped),
                            noti.id
                        )

                    # SQL update for direct-only products
                    if direct_only:
                        self.env.cr.execute("""
                            UPDATE product_product
                            SET meli_stock_moves_update = NOW() AT TIME ZONE 'UTC'
                            WHERE id IN %s
                        """, (tuple(direct_only),))
                        self.env['product.product'].invalidate_model(['meli_stock_moves_update'])

                    return

            # STEP 4: Standard approach for non-significant components
            products_to_update, benchmark_data = self._get_meli_products_to_update()
            benchmark_data['t_significant_check'] = t_sig_end - t_sig

            if not products_to_update:
                return

            product_count = len(products_to_update)

            # Large batch: defer to notification
            if product_count >= MELI_DEFERRED_UPDATE_THRESHOLD:
                noti = self._create_deferred_stock_update_notification(
                    products_to_update, benchmark_data
                )
                if noti:
                    if self._meli_log_enabled():
                        _logger.info(
                            "MELI_BENCHMARK _force_meli_stock_update DEFERRED: "
                            "%d products queued via notification (threshold=%d)",
                            product_count, MELI_DEFERRED_UPDATE_THRESHOLD
                        )
                    return

            # Small batch: SQL UPDATE directly
            t_sql1 = time.time()
            self.env.cr.execute("""
                UPDATE product_product
                SET meli_stock_moves_update = NOW() AT TIME ZONE 'UTC'
                WHERE id IN %s
            """, (tuple(products_to_update),))
            self.env['product.product'].invalidate_model(['meli_stock_moves_update'])
            t_sql1_end = time.time()

            t_sql2 = time.time()
            updated_bindings = self.env.cr.execute("""
                UPDATE mercadolibre_product mp
                SET meli_stock_moves_update = NOW() AT TIME ZONE 'UTC',
                    product_meli_stock_moves_update = NOW() AT TIME ZONE 'UTC'
                WHERE mp.product_id IN %s
                RETURNING mp.id, mp.product_id
            """, (tuple(products_to_update),))
            binding_rows = self.env.cr.fetchall()
            self.env['mercadolibre.product'].invalidate_model(
                ['meli_stock_moves_update', 'product_meli_stock_moves_update']
            )
            t_sql2_end = time.time()

            t_total = time.time() - t_start

            if self._meli_log_enabled():
                _logger.info(
                    "MELI_BENCHMARK _force_meli_stock_update DIRECT: moves=%d, products=%d "
                    "(direct=%d, bom_parents=%d), bomlines=%d, total_time=%.3fs",
                    benchmark_data['moves_count'],
                    benchmark_data['total_products'],
                    benchmark_data['move_products'],
                    benchmark_data['bom_parent_products'],
                    benchmark_data['bomlines_found'],
                    t_total
                )

                if t_total > MELI_BENCHMARK_THRESHOLD:
                    _logger.warning(
                        "MELI_BENCHMARK_DETAIL _force_meli_stock_update SLOW (%.3fs): "
                        "sig_check=%.3fs, collect=%.3fs, bom_search=%.3fs, sql=%.3fs | Data: %s",
                        t_total,
                        benchmark_data.get('t_significant_check', 0),
                        benchmark_data['t_collect_moves'],
                        benchmark_data['t_bom_search'],
                        (t_sql1_end - t_sql1) + (t_sql2_end - t_sql2),
                        benchmark_data
                    )

        except Exception as e:
            _logger.error(e, exc_info=True)

    def _action_assign(self):
        """Override to update MeLi bindings on stock reservation.
        Uses _force_meli_stock_update() to set date to NOW() since reservations
        don't create new moves (they just change state from confirmed to assigned).
        BENCHMARKED: Tracks total operation time."""
        if self.env.context.get('meli_skip_stock_update'):
            return super(stock_move, self)._action_assign()

        t_start = time.time()

        t_super = time.time()
        ret = super(stock_move, self.with_context(meli_skip_stock_update=True))._action_assign()
        t_super_end = time.time()

        t_meli = time.time()
        # Use _force_meli_stock_update (sets NOW()) instead of _update_meli_bindings
        # because reservations don't create new stock.move records - they only change
        # the state of existing moves, so create_date doesn't change
        self._force_meli_stock_update()
        t_meli_end = time.time()

        t_total = time.time() - t_start
        if self._meli_log_enabled() and t_total > MELI_BENCHMARK_THRESHOLD:
            _logger.warning(
                "MELI_BENCHMARK _action_assign SLOW: moves=%d, total=%.3fs (super=%.3fs, meli=%.3fs)",
                len(self), t_total, t_super_end - t_super, t_meli_end - t_meli
            )
        return ret

    def _action_done(self, cancel_backorder=None):
        """Override to update MeLi bindings on delivery confirmation.
        Uses context flag to skip meli_oerp's meli_update_boms() and avoid duplicate processing.
        BENCHMARKED: Tracks total operation time."""
        if self.env.context.get('meli_skip_stock_update'):
            return super(stock_move, self)._action_done(cancel_backorder=cancel_backorder)

        t_start = time.time()
        ret = super(stock_move, self.with_context(meli_skip_stock_update=True))._action_done(cancel_backorder=cancel_backorder)
        t_super_end = time.time()

        self._update_meli_bindings()
        t_meli_end = time.time()

        t_total = time.time() - t_start
        if self._meli_log_enabled() and t_total > MELI_BENCHMARK_THRESHOLD:
            _logger.warning(
                "MELI_BENCHMARK _action_done SLOW: moves=%d, total=%.3fs (super=%.3fs, meli=%.3fs)",
                len(self), t_total, t_super_end - t_start, t_meli_end - t_super_end
            )
        return ret

    def _action_cancel(self):
        """Override to update MeLi bindings on stock move cancellation.
        Uses _force_meli_stock_update() to set date to NOW() instead of recalculating.
        BENCHMARKED: Tracks total operation time."""
        if self.env.context.get('meli_skip_stock_update'):
            return super(stock_move, self)._action_cancel()

        t_start = time.time()
        ret = super(stock_move, self.with_context(meli_skip_stock_update=True))._action_cancel()
        t_super_end = time.time()

        self._force_meli_stock_update()
        t_meli_end = time.time()

        t_total = time.time() - t_start
        if self._meli_log_enabled() and t_total > MELI_BENCHMARK_THRESHOLD:
            _logger.warning(
                "MELI_BENCHMARK _action_cancel SLOW: moves=%d, total=%.3fs (super=%.3fs, meli=%.3fs)",
                len(self), t_total, t_super_end - t_start, t_meli_end - t_super_end
            )
        return ret

    def _do_unreserve(self):
        """Override to update MeLi bindings on stock unreservation.
        Uses _force_meli_stock_update() to set date to NOW() instead of recalculating.
        BENCHMARKED: Tracks total operation time."""
        if self.env.context.get('meli_skip_stock_update'):
            return super(stock_move, self)._do_unreserve()

        t_start = time.time()
        ret = super(stock_move, self.with_context(meli_skip_stock_update=True))._do_unreserve()
        t_super_end = time.time()

        self._force_meli_stock_update()
        t_meli_end = time.time()

        t_total = time.time() - t_start
        if self._meli_log_enabled() and t_total > MELI_BENCHMARK_THRESHOLD:
            _logger.warning(
                "MELI_BENCHMARK _do_unreserve SLOW: moves=%d, total=%.3fs (super=%.3fs, meli=%.3fs)",
                len(self), t_total, t_super_end - t_start, t_meli_end - t_super_end
            )
        return ret


class stock_quant(models.Model):

    _inherit = "stock.quant"

    product_default_code = fields.Char(string="SKU", related="product_id.default_code")
    product_barcode = fields.Char(string="BARCODE", related="product_id.barcode")
