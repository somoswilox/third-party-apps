from odoo import models

class ResCity(models.Model):
    _inherit = 'res.city'

    _sql_constraints = [
        ('unique_city_id', 'unique (name, country_id, state_id)', 'The city name allready exists!')
    ]