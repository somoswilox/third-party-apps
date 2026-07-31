# -*- coding: utf-8 -*-
from odoo import api, fields, models
import json
import logging
_logger = logging.getLogger(__name__)


class MercadoLibreAccountKPIsImpl(models.Model):
    _inherit = "mercadolibre.account"

    # ---- SALES ----
    def _kpi_get_sales_counts(self, period_domain):
        self.ensure_one()
        counts = {
            'paid': 0,
            'delivered': 0,
            'cancelled': 0,
            'returned': 0,
            'missing': 0,
            'to_cancel': 0,
        }
        by_team = {}

        if 'mercadolibre.orders' not in self.env:
            return counts, by_team

        dom = [('connection_account', '=', self.id)] + (period_domain or [])
        ml_orders = self.env['mercadolibre.orders'].sudo()

        # Get all orders in period
        all_orders = ml_orders.search(dom)

        # Count by ML status
        counts['paid'] = len(all_orders.filtered(lambda o: o.status == 'paid'))
        counts['delivered'] = len(all_orders.filtered(lambda o: o.status == 'delivered'))
        counts['cancelled'] = len(all_orders.filtered(lambda o: o.status == 'cancelled'))
        counts['returned'] = len(all_orders.filtered(lambda o: o.status == 'returned'))

        # Missing: Orders without sale.order OR sale.order not confirmed (draft/sent)
        counts['missing'] = self._kpi_count_missing_orders(all_orders)

        # To cancel: Orders cancelled in ML but sale.order NOT cancelled in Odoo
        counts['to_cancel'] = self._kpi_count_to_cancel_orders(all_orders)

        by_team = self._kpi_group_by_team(
            model='mercadolibre.orders', key_field='status', dom=dom
        )
        return counts, by_team

    def _kpi_count_missing_orders(self, orders):
        """
        Count orders that are missing proper sale.order:
        - No sale.order linked
        - sale.order in draft or sent state (not confirmed)
        Only count non-cancelled ML orders (cancelled orders don't need a sale.order)
        """
        missing_count = 0
        for order in orders:
            # Skip cancelled/returned orders - they don't need a sale.order
            if order.status in ('cancelled', 'returned', 'invalid'):
                continue

            sale_order = order.sale_order
            if not sale_order:
                # No sale.order linked
                missing_count += 1
            elif sale_order.state in ('draft', 'sent'):
                # sale.order exists but not confirmed (still quotation)
                missing_count += 1

        return missing_count

    def _kpi_count_to_cancel_orders(self, orders):
        """
        Count orders that need to be cancelled in Odoo:
        - ML order status is 'cancelled'
        - But sale.order exists and is NOT cancelled
        """
        to_cancel_count = 0
        for order in orders:
            if order.status == 'cancelled':
                sale_order = order.sale_order
                if sale_order and sale_order.state != 'cancel':
                    to_cancel_count += 1

        return to_cancel_count

    # ---- INVOICES ----
    def _kpi_get_invoice_counts(self, period_domain):
        self.ensure_one()
        counts = {'conciled': 0, 'not_conciled': 0, 'not_invoiced': 0}
        by_team = {}

        # account.move (customer invoices) - convert date_created to invoice_date
        move = self.env['account.move'].sudo()
        inv_dom = [('move_type', '=', 'out_invoice'), ('company_id', '=', self.company_id.id)]
        # Convert date_created to invoice_date for account.move
        for d in (period_domain or []):
            if len(d) == 3 and d[0] == 'date_created':
                inv_dom.append(('invoice_date', d[1], d[2]))
        invs = move.search(inv_dom)
        counts['conciled'] = len(invs.filtered(lambda m: m.payment_state in ('paid', 'in_payment') and m.amount_residual == 0))
        counts['not_conciled'] = len(invs.filtered(lambda m: m.payment_state in ('not_paid', 'partial') or m.amount_residual > 0))

        # Not invoiced: ML orders' sale_orders with no invoice (or to invoice)
        if 'mercadolibre.orders' in self.env:
            ml_orders = self.env['mercadolibre.orders'].sudo().search([('connection_account', '=', self.id)] + (period_domain or []))
            sos = ml_orders.mapped('sale_order').sudo()
            counts['not_invoiced'] = len(sos.filtered(lambda s: not s.invoice_ids or s.invoice_status in ('no', 'to invoice')))

        by_team = self._kpi_group_by_team(
            model='account.move', key_field='payment_state', dom=inv_dom
        )
        return counts, by_team

    # ---- PUBLICATIONS / STOCK ----
    def _kpi_get_publication_counts(self, period_domain):
        self.ensure_one()
        counts = {
            'synced_active': 0,
            'synced_pause': 0,
            'synced_updating': 0,
            'synced_updated_problems': 0,
            'error': 0,
            'unsynced': 0,
        }
        by_team = {}  # Not meaningful for products; keep empty

        if 'mercadolibre.product' not in self.env:
            return counts, by_team

        ml_prod = self.env['mercadolibre.product'].sudo()
        base_dom = [('connection_account', '=', self.id)]  # period not applied: stock status is current snapshot

        # Always reliable (stored)
        counts['synced_updating'] = ml_prod.search_count(base_dom + [('meli_stock_status', '=', 'update')])
        counts['synced_updated_problems'] = ml_prod.search_count(base_dom + [('meli_stock_status', '=', 'updated_with_warning')])
        counts['error'] = ml_prod.search_count(base_dom + [
            ('meli_stock_status', 'in', [
                'revision_error', 'revision_blocked', 'revision_fulfillment',
                'revision_has_bids', 'revision_under_review',
                'revision_closed', 'revision_inactive'
            ])
        ])

        # “Updated” split into Active vs Pause:
        updated_q = base_dom + [('meli_stock_status', '=', 'updated')]

        if 'meli_last_status' in ml_prod._fields:
            # Use the last stored status if maintained by your flows
            counts['synced_active'] = ml_prod.search_count(updated_q + [('meli_last_status', '=', 'active')])
            counts['synced_pause'] = ml_prod.search_count(updated_q + [('meli_last_status', '=', 'paused')])

            # If neither active nor paused caught all “updated”, put the remainder into "active"
            updated_total = ml_prod.search_count(updated_q)
            split_total = counts['synced_active'] + counts['synced_pause']
            if split_total < updated_total:
                counts['synced_active'] += (updated_total - split_total)
        else:
            # Fallback: no reliable last-status → count all “updated” as Active
            counts['synced_active'] = ml_prod.search_count(updated_q)

        # Unsynced: keep your existing method (binding missing)
        counts['unsynced'] = self._kpi_count_unsynced_products()

        return counts, by_team

    def _kpi_count_unsynced_products(self):
        if 'mercadolibre.product' in self.env:
            ml_prod = self.env['mercadolibre.product'].sudo()
            if 'is_unsynced' in ml_prod._fields:
                return ml_prod.search_count([('connection_account', '=', self.id), ('is_unsynced', '=', True)])
        return 0

    # ---- Refreshes in period ----
    def _kpi_get_refresh_count(self, period_domain):
        if 'mercadolibre.notification' in self.env:
            dom = [('connection_account', '=', self.id), ('resource', 'in', ['cron', 'token', 'refresh'])]
            dom += (period_domain or [])
            return self.env['mercadolibre.notification'].sudo().search_count(dom)
        return 0

    # ---- Shared grouping helper ----
    def _kpi_group_by_team(self, model, key_field, dom):
        """Return {key_value: {team_name: count}} using common relations (sale_order.team_id or record.team_id)."""
        data = {}
        try:
            recs = self.env[model].sudo().search(dom, limit=5000)
            for r in recs:
                key = getattr(r, key_field, 'unknown') or 'unknown'
                if hasattr(r, 'sale_order') and getattr(r.sale_order, 'team_id', False):
                    team = r.sale_order.team_id.name or 'Unassigned'
                elif hasattr(r, 'team_id') and r.team_id:
                    team = r.team_id.name or 'Unassigned'
                else:
                    team = 'Unassigned'
                data.setdefault(str(key), {})
                data[str(key)][team] = data[str(key)].get(team, 0) + 1
        except Exception:
            _logger.debug("kpi_group_by_team failed for %s", model)
        return data

    # ========== PUBLIC KPI METHODS FOR REMOTE QUERIES ==========

    def get_orders_kpi_data(self, date_from=None, date_to=None, filters=None):
        """
        Public method to get KPI data for remote queries.
        Returns a dictionary with all KPI metrics.

        Args:
            date_from: Start date for the query (YYYY-MM-DD)
            date_to: End date for the query (YYYY-MM-DD)
            filters: Additional filter dict (optional)

        Returns:
            dict with KPI data
        """
        self.ensure_one()

        try:
            period_domain = self._build_period_domain(date_from, date_to)

            # Add custom filters if provided
            if filters:
                for key, value in filters.items():
                    if value is not None:
                        period_domain.append((key, '=', value))

            # Collect all KPI data
            order_counts = self._kpi_get_order_counts_extended(period_domain)
            order_amounts = self._kpi_get_order_amounts(period_domain)
            shipment_counts = self._kpi_get_shipment_counts(period_domain)

            orders_by_status = self._kpi_aggregate_orders_by_status(period_domain)
            orders_by_date = self._kpi_aggregate_orders_by_date(period_domain)
            orders_by_logistic = self._kpi_aggregate_orders_by_logistic(period_domain)

            return {
                'success': True,
                'account_id': self.id,
                'account_name': self.name,
                'period': {
                    'from': str(date_from) if date_from else None,
                    'to': str(date_to) if date_to else None,
                },
                'orders': {
                    'counts': order_counts,
                    'amounts': order_amounts,
                },
                'shipments': shipment_counts,
                'aggregations': {
                    'by_status': orders_by_status,
                    'by_date': orders_by_date,
                    'by_logistic_type': orders_by_logistic,
                },
                'timestamp': fields.Datetime.now().isoformat(),
            }

        except Exception as e:
            _logger.exception("Error getting KPI data: %s", str(e))
            return {
                'success': False,
                'error': str(e),
            }

    def get_orders_summary(self, date_from=None, date_to=None, group_by='status'):
        """
        Get a summary of orders grouped by a specific field.

        Args:
            date_from: Start date
            date_to: End date
            group_by: Field to group by ('status', 'shipment_status', 'shipment_logistic_type')

        Returns:
            dict with grouped summary
        """
        valid_group_fields = ['status', 'shipment_status', 'shipment_logistic_type']
        if group_by not in valid_group_fields:
            return {'success': False, 'error': f'Invalid group_by field. Valid: {valid_group_fields}'}

        query = f"""
            SELECT COALESCE({group_by}, 'unknown') as group_key,
                   COUNT(*) as order_count,
                   COALESCE(SUM(total_amount), 0) as total_amount,
                   COALESCE(SUM(paid_amount), 0) as paid_amount
            FROM mercadolibre_orders
            WHERE 1=1
        """
        params = []

        if date_from:
            query += " AND date_created >= %s"
            params.append(date_from)
        if date_to:
            query += " AND date_created <= %s"
            params.append(date_to)

        query += f" GROUP BY {group_by} ORDER BY order_count DESC"

        try:
            self._cr.execute(query, tuple(params))
            results = []
            for row in self._cr.fetchall():
                results.append({
                    'group': row[0],
                    'order_count': row[1],
                    'total_amount': float(row[2]),
                    'paid_amount': float(row[3]),
                })

            return {
                'success': True,
                'group_by': group_by,
                'data': results,
                'timestamp': fields.Datetime.now().isoformat(),
            }

        except Exception as e:
            _logger.exception("Error getting orders summary: %s", str(e))
            return {'success': False, 'error': str(e)}

    def get_orders_timeline(self, date_from=None, date_to=None, interval='day'):
        """
        Get orders timeline for charts.

        Args:
            date_from: Start date
            date_to: End date
            interval: 'day', 'week', 'month'

        Returns:
            dict with timeline data
        """
        interval_map = {
            'day': "DATE(date_created)",
            'week': "DATE_TRUNC('week', date_created)",
            'month': "DATE_TRUNC('month', date_created)",
        }

        date_expr = interval_map.get(interval, interval_map['day'])

        query = f"""
            SELECT {date_expr} as period,
                   COUNT(*) as order_count,
                   COALESCE(SUM(total_amount), 0) as total_amount,
                   COALESCE(SUM(paid_amount), 0) as paid_amount,
                   COUNT(CASE WHEN status IN ('paid', 'partially_paid') THEN 1 END) as paid_count,
                   COUNT(CASE WHEN status IN ('cancelled', 'invalid') THEN 1 END) as cancelled_count
            FROM mercadolibre_orders
            WHERE date_created IS NOT NULL
        """
        params = []

        if date_from:
            query += " AND date_created >= %s"
            params.append(date_from)
        if date_to:
            query += " AND date_created <= %s"
            params.append(date_to)

        query += f" GROUP BY {date_expr} ORDER BY period"

        try:
            self._cr.execute(query, tuple(params))
            results = []
            for row in self._cr.fetchall():
                results.append({
                    'period': str(row[0]) if row[0] else None,
                    'order_count': row[1],
                    'total_amount': float(row[2]),
                    'paid_amount': float(row[3]),
                    'paid_count': row[4],
                    'cancelled_count': row[5],
                })

            return {
                'success': True,
                'interval': interval,
                'data': results,
                'timestamp': fields.Datetime.now().isoformat(),
            }

        except Exception as e:
            _logger.exception("Error getting orders timeline: %s", str(e))
            return {'success': False, 'error': str(e)}

    # ========== HELPER METHODS ==========

    def _build_period_domain(self, date_from=None, date_to=None):
        """Build domain filter for the period."""
        domain = []
        if date_from:
            domain.append(('date_created', '>=', date_from))
        if date_to:
            domain.append(('date_created', '<=', date_to))
        return domain

    def _kpi_get_order_counts_extended(self, period_domain):
        """Get order counts by status."""
        counts = {
            'total': 0,
            'paid': 0,
            'cancelled': 0,
            'pending': 0,
        }

        if 'mercadolibre.orders' not in self.env:
            return counts

        ml_orders = self.env['mercadolibre.orders'].sudo()
        base_domain = period_domain.copy()

        counts['total'] = ml_orders.search_count(base_domain)
        counts['paid'] = ml_orders.search_count(
            base_domain + [('status', 'in', ['paid', 'partially_paid'])]
        )
        counts['cancelled'] = ml_orders.search_count(
            base_domain + [('status', 'in', ['cancelled', 'invalid', 'pending_cancel'])]
        )
        counts['pending'] = ml_orders.search_count(
            base_domain + [('status', 'in', ['payment_required', 'payment_in_process', 'confirmed'])]
        )

        return counts

    def _kpi_get_order_amounts(self, period_domain):
        """Get order amounts aggregated."""
        amounts = {
            'total_amount': 0.0,
            'paid_amount': 0.0,
            'fee_amount': 0.0,
            'shipping_cost': 0.0,
        }

        query = """
            SELECT
                COALESCE(SUM(total_amount), 0) as total_amount,
                COALESCE(SUM(paid_amount), 0) as paid_amount,
                COALESCE(SUM(fee_amount), 0) as fee_amount,
                COALESCE(SUM(shipping_cost), 0) as shipping_cost
            FROM mercadolibre_orders
            WHERE 1=1
        """
        params = []

        for domain_tuple in period_domain:
            if domain_tuple[0] == 'date_created' and domain_tuple[1] == '>=':
                query += " AND date_created >= %s"
                params.append(domain_tuple[2])
            elif domain_tuple[0] == 'date_created' and domain_tuple[1] == '<=':
                query += " AND date_created <= %s"
                params.append(domain_tuple[2])

        try:
            self._cr.execute(query, tuple(params))
            result = self._cr.fetchone()
            if result:
                amounts['total_amount'] = float(result[0] or 0)
                amounts['paid_amount'] = float(result[1] or 0)
                amounts['fee_amount'] = float(result[2] or 0)
                amounts['shipping_cost'] = float(result[3] or 0)
        except Exception as e:
            _logger.error("Error getting order amounts: %s", str(e))

        return amounts

    def _kpi_get_shipment_counts(self, period_domain):
        """Get shipment-related counts."""
        counts = {
            'delivered': 0,
            'pending': 0,
            'cancelled': 0,
            'fulfillment': 0,
        }

        if 'mercadolibre.orders' not in self.env:
            return counts

        ml_orders = self.env['mercadolibre.orders'].sudo()
        base_domain = period_domain.copy()

        counts['delivered'] = ml_orders.search_count(
            base_domain + [('shipment_status', 'in', ['delivered', 'shipped'])]
        )
        counts['pending'] = ml_orders.search_count(
            base_domain + [('shipment_status', 'in', ['pending', 'ready_to_ship', 'handling'])]
        )
        counts['cancelled'] = ml_orders.search_count(
            base_domain + [('shipment_status', 'in', ['cancelled', 'not_delivered'])]
        )
        counts['fulfillment'] = ml_orders.search_count(
            base_domain + [('shipment_logistic_type', '=', 'fulfillment')]
        )

        return counts

    def _kpi_aggregate_orders_by_status(self, period_domain):
        """Aggregate orders by status."""
        result = {}

        query = """
            SELECT status, COUNT(*) as count
            FROM mercadolibre_orders
            WHERE 1=1
        """
        params = []

        for domain_tuple in period_domain:
            if domain_tuple[0] == 'date_created' and domain_tuple[1] == '>=':
                query += " AND date_created >= %s"
                params.append(domain_tuple[2])
            elif domain_tuple[0] == 'date_created' and domain_tuple[1] == '<=':
                query += " AND date_created <= %s"
                params.append(domain_tuple[2])

        query += " GROUP BY status ORDER BY count DESC"

        try:
            self._cr.execute(query, tuple(params))
            for row in self._cr.fetchall():
                status = row[0] or 'unknown'
                result[status] = row[1]
        except Exception as e:
            _logger.error("Error aggregating orders by status: %s", str(e))

        return result

    def _kpi_aggregate_orders_by_date(self, period_domain):
        """Aggregate orders by date (daily counts)."""
        result = {}

        query = """
            SELECT DATE(date_created) as order_date, COUNT(*) as count
            FROM mercadolibre_orders
            WHERE date_created IS NOT NULL
        """
        params = []

        for domain_tuple in period_domain:
            if domain_tuple[0] == 'date_created' and domain_tuple[1] == '>=':
                query += " AND date_created >= %s"
                params.append(domain_tuple[2])
            elif domain_tuple[0] == 'date_created' and domain_tuple[1] == '<=':
                query += " AND date_created <= %s"
                params.append(domain_tuple[2])

        query += " GROUP BY DATE(date_created) ORDER BY order_date"

        try:
            self._cr.execute(query, tuple(params))
            for row in self._cr.fetchall():
                date_str = str(row[0]) if row[0] else 'unknown'
                result[date_str] = row[1]
        except Exception as e:
            _logger.error("Error aggregating orders by date: %s", str(e))

        return result

    def _kpi_aggregate_orders_by_logistic(self, period_domain):
        """Aggregate orders by logistic type."""
        result = {}

        query = """
            SELECT COALESCE(shipment_logistic_type, 'other') as logistic_type, COUNT(*) as count
            FROM mercadolibre_orders
            WHERE 1=1
        """
        params = []

        for domain_tuple in period_domain:
            if domain_tuple[0] == 'date_created' and domain_tuple[1] == '>=':
                query += " AND date_created >= %s"
                params.append(domain_tuple[2])
            elif domain_tuple[0] == 'date_created' and domain_tuple[1] == '<=':
                query += " AND date_created <= %s"
                params.append(domain_tuple[2])

        query += " GROUP BY shipment_logistic_type ORDER BY count DESC"

        try:
            self._cr.execute(query, tuple(params))
            for row in self._cr.fetchall():
                logistic_type = row[0] or 'other'
                result[logistic_type] = row[1]
        except Exception as e:
            _logger.error("Error aggregating orders by logistic: %s", str(e))

        return result

    # ========== CONFIGURATION FOR KPI REPORT ==========

    def get_kpi_config(self):
        """
        Return configuration data relevant for KPI reports.
        This helps the fulfillment module understand how the remote account is configured.
        """
        self.ensure_one()
        config = self.configuration

        if not config:
            return {'success': False, 'error': 'No configuration found'}

        # Import settings
        import_settings = {
            'cron_get_orders': config.mercadolibre_cron_get_orders if hasattr(config, 'mercadolibre_cron_get_orders') else False,
            'cron_get_orders_shipment': config.mercadolibre_cron_get_orders_shipment if hasattr(config, 'mercadolibre_cron_get_orders_shipment') else False,
            'cron_get_orders_shipment_client': config.mercadolibre_cron_get_orders_shipment_client if hasattr(config, 'mercadolibre_cron_get_orders_shipment_client') else False,
            'cron_get_questions': config.mercadolibre_cron_get_questions if hasattr(config, 'mercadolibre_cron_get_questions') else False,
            'cron_get_update_products': config.mercadolibre_cron_get_update_products if hasattr(config, 'mercadolibre_cron_get_update_products') else False,
            'including_shipping_cost': config.mercadolibre_including_shipping_cost if hasattr(config, 'mercadolibre_including_shipping_cost') else None,
        }

        # Export/Publish settings
        export_settings = {
            'cron_post_update_products': config.mercadolibre_cron_post_update_products if hasattr(config, 'mercadolibre_cron_post_update_products') else False,
            'cron_post_update_stock': config.mercadolibre_cron_post_update_stock if hasattr(config, 'mercadolibre_cron_post_update_stock') else False,
            'cron_post_update_price': config.mercadolibre_cron_post_update_price if hasattr(config, 'mercadolibre_cron_post_update_price') else False,
        }

        # Order processing settings
        order_settings = {
            'order_confirmation': config.mercadolibre_order_confirmation if hasattr(config, 'mercadolibre_order_confirmation') else None,
            'order_confirmation_full': config.mercadolibre_order_confirmation_full if hasattr(config, 'mercadolibre_order_confirmation_full') else None,
            'order_total_config': config.mercadolibre_order_total_config if hasattr(config, 'mercadolibre_order_total_config') else None,
        }

        # Product settings
        product_settings = {
            'buying_mode': config.mercadolibre_buying_mode if hasattr(config, 'mercadolibre_buying_mode') else None,
            'currency': config.mercadolibre_currency if hasattr(config, 'mercadolibre_currency') else None,
            'condition': config.mercadolibre_condition if hasattr(config, 'mercadolibre_condition') else None,
            'listing_type': config.mercadolibre_listing_type if hasattr(config, 'mercadolibre_listing_type') else None,
            'warranty': config.mercadolibre_warranty if hasattr(config, 'mercadolibre_warranty') else None,
            'attributes': config.mercadolibre_attributes if hasattr(config, 'mercadolibre_attributes') else False,
        }

        # Account info
        account_info = {
            'name': self.name,
            'seller_id': self.seller_id,
            'type': self.type,
            'country': self.country_id.name if self.country_id else None,
            'company': self.company_id.name if self.company_id else None,
            'status': 'connected' if self.access_token else 'disconnected',
        }

        # Counts
        counts = {
            'product_templates': len(self.mercadolibre_product_template_bindings) if hasattr(self, 'mercadolibre_product_template_bindings') else 0,
            'product_variants': len(self.mercadolibre_product_bindings) if hasattr(self, 'mercadolibre_product_bindings') else 0,
            'orders': len(self.mercadolibre_orders) if hasattr(self, 'mercadolibre_orders') else 0,
            'notifications': self.env["mercadolibre.notification"].search_count([('connection_account', '=', self.id)]) if 'mercadolibre.notification' in self.env else 0,
        }

        return {
            'success': True,
            'account': account_info,
            'configuration': {
                'name': config.name,
                'import': import_settings,
                'export': export_settings,
                'orders': order_settings,
                'products': product_settings,
            },
            'counts': counts,
            'timestamp': fields.Datetime.now().isoformat(),
        }

