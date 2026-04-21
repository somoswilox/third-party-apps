import json

from odoo import SUPERUSER_ID, api
from odoo.tools.safe_eval import safe_eval


def migrate(cr, version):

    env = api.Environment(cr, SUPERUSER_ID, {})
    # Get the current default calendar
    custom_calendar = (
        env["ir.config_parameter"].sudo().get_param("bryntum.default_calendar")
    )

    if custom_calendar:
        # If json.loads succeeds, it is already JSON
        try:
            json.loads(custom_calendar)
        except (json.JSONDecodeError, TypeError):
            try:
                calendar_eval = safe_eval(custom_calendar)
            except Exception:
                # If invalid Asteval in config, just wipe it out
                calendar_eval = {}
            json_default_calendar = json.dumps(calendar_eval)
            env["ir.config_parameter"].sudo().set_param(
                "bryntum.default_calendar", json_default_calendar
            )
