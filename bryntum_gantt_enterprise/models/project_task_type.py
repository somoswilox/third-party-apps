from odoo import fields, models


class ProjectTaskType(models.Model):
    _inherit = "project.task.type"  # pylint: disable=R8180

    html_color_bryntum_id = fields.Many2one(
        "gantt.event.color", string="Color in Bryntum"
    )
