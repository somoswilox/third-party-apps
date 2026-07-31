# -*- coding: utf-8 -*-
from odoo import api, fields, models
import json
import logging
_logger = logging.getLogger(__name__)


class OcapiConnectionAccountKPIs(models.Model):
    _inherit = "ocapi.connection.account"

    # ---- Period (manual range to “summarize”) ----
    kpi_from = fields.Date(string="KPI From")
    kpi_to = fields.Date(string="KPI To")

    # ---- SALES (counts) ----
    sales_total = fields.Integer(string="Sales (Total)", readonly=True)
    sales_paid = fields.Integer(string="Sales Paid", readonly=True)
    sales_delivered = fields.Integer(string="Sales Delivered", readonly=True)
    sales_cancelled = fields.Integer(string="Sales Cancelled", readonly=True)
    sales_returned = fields.Integer(string="Sales Returned", readonly=True)
    sales_missing = fields.Integer(string="Missing Sales", readonly=True)

    # ---- SALES (%) ----
    sales_paid_pct = fields.Float(string="% Paid", readonly=True)
    sales_delivered_pct = fields.Float(string="% Delivered", readonly=True)
    sales_cancelled_pct = fields.Float(string="% Cancelled", readonly=True)
    sales_returned_pct = fields.Float(string="% Returned", readonly=True)
    sales_missing_pct = fields.Float(string="% Missing", readonly=True)

    # ---- INVOICES (counts) ----
    inv_total = fields.Integer(string="Invoices (Total)", readonly=True)
    inv_conciled = fields.Integer(string="Conciled", readonly=True)
    inv_not_conciled = fields.Integer(string="Invoiced not conciled", readonly=True)
    inv_not_invoiced = fields.Integer(string="Not invoiced", readonly=True)

    # ---- INVOICES (%) ----
    inv_conciled_pct = fields.Float(string="% Conciled", readonly=True)
    inv_not_conciled_pct = fields.Float(string="% Invoiced not conciled", readonly=True)
    inv_not_invoiced_pct = fields.Float(string="% Not invoiced", readonly=True)

    # ---- PUBLICATIONS / STOCK (counts) ----
    pub_total = fields.Integer(string="Publications (Total)", readonly=True)
    pub_synced_active = fields.Integer(string="Synced & Active", readonly=True)
    pub_synced_pause = fields.Integer(string="Synced & Pause", readonly=True)
    pub_synced_updating = fields.Integer(string="Synced Updating", readonly=True)
    pub_synced_updated_problems = fields.Integer(string="Synced Updated w/ Problems", readonly=True)
    pub_error = fields.Integer(string="Error", readonly=True)
    pub_unsynced = fields.Integer(string="Unsynced (missing binding)", readonly=True)

    # ---- PUBLICATIONS (%) ----
    pub_synced_active_pct = fields.Float(string="% Synced & Active", readonly=True)
    pub_synced_pause_pct = fields.Float(string="% Synced & Pause", readonly=True)
    pub_synced_updating_pct = fields.Float(string="% Synced Updating", readonly=True)
    pub_synced_updated_problems_pct = fields.Float(string="% Synced Updated w/ Problems", readonly=True)
    pub_error_pct = fields.Float(string="% Error", readonly=True)
    pub_unsynced_pct = fields.Float(string="% Unsynced", readonly=True)

    # ---- Team splits (JSON) ----
    sales_by_team_json = fields.Text(string="Sales by Team (JSON)", readonly=True)
    invoices_by_team_json = fields.Text(string="Invoices by Team (JSON)", readonly=True)
    publications_by_team_json = fields.Text(string="Publications by Team (JSON)", readonly=True)

    # ---- Connection refresh count in window ----
    refresh_count_period = fields.Integer(string="Refreshes in Period", readonly=True)
    last_kpi_refresh_at = fields.Datetime(string="Last KPI Refresh", readonly=True)

    # ---------------- Public button ----------------
    def action_refresh_kpis(self):
        for acc in self:
            try:
                acc._kpi_refresh_all()
                acc.last_kpi_refresh_at = fields.Datetime.now()
            except Exception:
                _logger.exception("KPI refresh failed for account %s", acc.display_name)
        return True

    # ---------------- Orchestrator ----------------
    def _kpi_refresh_all(self):
        """Orchestrate KPI refresh by calling provider-specific hooks."""
        self.ensure_one()

        period = []
        if self.kpi_from:
            period.append(('create_date', '>=', self.kpi_from))
        if self.kpi_to:
            period.append(('create_date', '<=', self.kpi_to))

        # SALES
        sale_counts, sales_by_team = self._kpi_get_sales_counts(period)
        self._kpi_assign_counts('sales', sale_counts)
        self.sales_by_team_json = json.dumps(sales_by_team or {})
        self._kpi_assign_pcts('sales', sale_counts)

        # INVOICES
        inv_counts, inv_by_team = self._kpi_get_invoice_counts(period)
        self._kpi_assign_counts('inv', inv_counts)
        self.invoices_by_team_json = json.dumps(inv_by_team or {})
        self._kpi_assign_pcts('inv', inv_counts)

        # PUBLICATIONS
        pub_counts, pub_by_team = self._kpi_get_publication_counts(period)
        self._kpi_assign_counts('pub', pub_counts)
        self.publications_by_team_json = json.dumps(pub_by_team or {})
        self._kpi_assign_pcts('pub', pub_counts)

        # Refreshes
        self.refresh_count_period = self._kpi_get_refresh_count(period) or 0

    # ---------------- Helpers (base) ----------------
    def _kpi_assign_counts(self, prefix, counts):
        # counts is a dict of raw numbers
        counts = counts or {}
        if prefix == 'sales':
            self.sales_total = sum(counts.values() or [])
            self.sales_paid = counts.get('paid', 0)
            self.sales_delivered = counts.get('delivered', 0)
            self.sales_cancelled = counts.get('cancelled', 0)
            self.sales_returned = counts.get('returned', 0)
            self.sales_missing = counts.get('missing', 0)
        elif prefix == 'inv':
            self.inv_total = sum(counts.values() or [])
            self.inv_conciled = counts.get('conciled', 0)
            self.inv_not_conciled = counts.get('not_conciled', 0)
            self.inv_not_invoiced = counts.get('not_invoiced', 0)
        elif prefix == 'pub':
            self.pub_total = sum(counts.values() or [])
            self.pub_synced_active = counts.get('synced_active', 0)
            self.pub_synced_pause = counts.get('synced_pause', 0)
            self.pub_synced_updating = counts.get('synced_updating', 0)
            self.pub_synced_updated_problems = counts.get('synced_updated_problems', 0)
            self.pub_error = counts.get('error', 0)
            self.pub_unsynced = counts.get('unsynced', 0)

    def _kpi_assign_pcts(self, prefix, counts):
        total = float(sum((counts or {}).values()) or 0.0)
        def pct(v): return (100.0 * float(v) / total) if total else 0.0

        if prefix == 'sales':
            self.sales_paid_pct = pct(self.sales_paid)
            self.sales_delivered_pct = pct(self.sales_delivered)
            self.sales_cancelled_pct = pct(self.sales_cancelled)
            self.sales_returned_pct = pct(self.sales_returned)
            self.sales_missing_pct = pct(self.sales_missing)
        elif prefix == 'inv':
            self.inv_conciled_pct = pct(self.inv_conciled)
            self.inv_not_conciled_pct = pct(self.inv_not_conciled)
            self.inv_not_invoiced_pct = pct(self.inv_not_invoiced)
        elif prefix == 'pub':
            self.pub_synced_active_pct = pct(self.pub_synced_active)
            self.pub_synced_pause_pct = pct(self.pub_synced_pause)
            self.pub_synced_updating_pct = pct(self.pub_synced_updating)
            self.pub_synced_updated_problems_pct = pct(self.pub_synced_updated_problems)
            self.pub_error_pct = pct(self.pub_error)
            self.pub_unsynced_pct = pct(self.pub_unsynced)

    # ---------------- Provider-specific HOOKS (to override in connectors) ----------------
    def _kpi_get_sales_counts(self, period_domain):
        """Return (counts_dict, by_team_dict). Override in connector modules.
        counts_dict keys: paid, delivered, cancelled, returned, missing"""
        return {
            'paid': 0, 'delivered': 0, 'cancelled': 0, 'returned': 0, 'missing': 0
        }, {}

    def _kpi_get_invoice_counts(self, period_domain):
        """Return (counts_dict, by_team_dict).
        counts_dict keys: conciled, not_conciled, not_invoiced"""
        return {
            'conciled': 0, 'not_conciled': 0, 'not_invoiced': 0
        }, {}

    def _kpi_get_publication_counts(self, period_domain):
        """Return (counts_dict, by_team_dict).
        counts_dict keys: synced_active, synced_pause, synced_updating,
                          synced_updated_problems, error, unsynced"""
        return {
            'synced_active': 0, 'synced_pause': 0, 'synced_updating': 0,
            'synced_updated_problems': 0, 'error': 0, 'unsynced': 0
        }, {}

    def _kpi_get_refresh_count(self, period_domain):
        """Return integer refresh count in the window."""
        return 0
