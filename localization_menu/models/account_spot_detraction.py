from odoo import fields, models

class AccountSpotDetraction(models.Model):
    _name = 'account.spot.detraction'
    _description = 'SPOT Detraction'

    name = fields.Char(
        string='Nombre',
        required=True
    )
