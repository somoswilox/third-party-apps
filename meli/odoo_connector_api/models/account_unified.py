# -*- coding: utf-8 -*-

from odoo import fields, models, tools, api
import logging

_logger = logging.getLogger(__name__)


class OcapiAccountUnified(models.Model):
    """
    SQL view that aggregates accounts from all connector tables into a single
    read-only model. Since each connector uses prototype inheritance
    (_inherit with a different _name), their records live in separate tables.
    This view UNIONs them so 'Todas las Cuentas' can show all accounts.

    New connectors are auto-discovered via ocapi.connector.registry at init time.
    """

    _name = "ocapi.account.unified"
    _description = "All Connector Accounts"
    _auto = False
    _order = "type, name"

    name = fields.Char(string="Name", readonly=True)
    type = fields.Char(string="Connector", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)
    country_id = fields.Many2one("res.country", string="Country", readonly=True)
    client_id = fields.Char(string="Client Id/App Id", readonly=True)
    image_128 = fields.Binary(string="Image", readonly=True)
    connection_monitor = fields.Boolean(string="Monitored", readonly=True)
    source_model = fields.Char(string="Model", readonly=True)
    source_id = fields.Integer(string="Record ID", readonly=True)
    create_date = fields.Datetime(string="Created", readonly=True)
    write_date = fields.Datetime(string="Updated", readonly=True)

    # Optional columns that may not exist in all tables.
    # If missing, NULL is used as fallback.
    # Note: image.mixin stores in image_1920; image_128 is computed (not stored).
    # We fetch image_1920 aliased as image_128 for the view.
    _OPTIONAL_COLS = ("image_1920", "country_id", "connection_monitor")

    def _get_table_columns(self, table_name):
        """Return set of column names that exist in a given table."""
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
        """, (table_name,))
        return {row[0] for row in self.env.cr.fetchall()}

    def _build_select(self, table_name, model_name, offset, columns):
        """Build a SELECT statement for one connector table."""
        parts = [
            f"(id + {offset}) as id",
            "name",
            "type",
            "company_id",
        ]
        # Optional columns: use real column if exists, NULL otherwise
        if "country_id" in columns:
            parts.append("country_id")
        else:
            parts.append("NULL::integer as country_id")

        parts.append("client_id")

        # image.mixin stores image in image_1920; image_128 is computed.
        # Use image_1920 aliased as image_128 for the view.
        if "image_1920" in columns:
            parts.append("image_1920 as image_128")
        else:
            parts.append("NULL::bytea as image_128")

        if "connection_monitor" in columns:
            parts.append("connection_monitor")
        else:
            parts.append("NULL::boolean as connection_monitor")

        parts.append(f"'{model_name}' as source_model")
        parts.append("id as source_id")
        parts.append("create_date")
        parts.append("write_date")

        return f"SELECT {', '.join(parts)} FROM {table_name}"

    def init(self):
        """Build the SQL view by discovering all connector account tables."""
        tools.drop_view_if_exists(self.env.cr, self._table)

        # Known connector account tables and their model names.
        # We detect which ones actually exist in the database so the module
        # loads cleanly regardless of which connectors are installed.
        known_tables = [
            ("ocapi_connection_account", "ocapi.connection.account"),
            ("mercadolibre_account", "mercadolibre.account"),
            ("producteca_account", "producteca.account"),
            ("fulfillment_account", "fulfillment.account"),
            ("ldps_account", "ldps.account"),
        ]

        # Check which tables exist
        self.env.cr.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ANY(%s)
        """, ([t[0] for t in known_tables],))
        existing = {row[0] for row in self.env.cr.fetchall()}

        unions = []
        for idx, (table_name, model_name) in enumerate(known_tables):
            if table_name in existing:
                offset = idx * 10000000
                columns = self._get_table_columns(table_name)
                unions.append(
                   self._build_select(table_name, model_name, offset, columns)
                )

        if not unions:
            # Fallback if no tables found
            unions.append(
                "SELECT 1 as id, "
                "NULL::varchar as name, NULL::varchar as type, "
                "NULL::integer as company_id, NULL::integer as country_id, "
                "NULL::varchar as client_id, "
                "NULL::bytea as image_128, NULL::boolean as connection_monitor, "
                "NULL::varchar as source_model, NULL::integer as source_id, "
                "NULL::timestamp as create_date, NULL::timestamp as write_date "
                "WHERE false"
            )

        query = " UNION ALL ".join(unions)

        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS ({query})
        """)

    def action_open_source_record(self):
        """Open the original connector account record."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self.source_model,
            "res_id": self.source_id,
            "view_mode": "form",
            "target": "current",
        }
