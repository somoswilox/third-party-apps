import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class GanttEventColor(models.Model):
    _name = "gantt.event.color"
    _description = "Color in Gantt"

    name = fields.Char(string="Color Name", required=True)
    color = fields.Char(string="Color", required=True, help="Hex Color of Gantt task")
    task_ids = fields.One2many(
        "project.task", inverse_name="html_color_bryntum_id", string="Tasks"
    )

    @api.constrains("color")
    def _check_html_color_bryntum_id(self):
        hex_pattern = re.compile(r"^#(?:[0-9a-fA-F]{6})$")
        for record in self:
            if record.color and not hex_pattern.match(record.color):
                raise ValidationError(
                    f"""'{record.color}' is not a valid HEX color.
                Expected format: #RRGGBB"""
                )
