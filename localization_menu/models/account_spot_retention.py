from odoo import fields, models

class AccountSpotRetention(models.Model):
    _name = 'account.spot.retention'
    _description = 'SPOT Retention'

    name = fields.Char(
        string='Nombre',
        required=True
    )

