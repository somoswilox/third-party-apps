from odoo import fields, models

class CodeAduana(models.Model):
    _name = 'code.aduana'
    _description = 'Customs Unit Code (Customs)'

    name = fields.Char(
        string='Descripción',
        required=True
    )
    code = fields.Char(
        string='Código',
        required=True
    )