from odoo import  models, fields

class ResCompany(models.Model):
    _inherit = "res.company"


    agip_token = fields.Char(string="Token de AGIP")
    agip_sign = fields.Char(string="Firma de AGIP")

