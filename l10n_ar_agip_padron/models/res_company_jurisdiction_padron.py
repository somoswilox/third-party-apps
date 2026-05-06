from odoo import models

class ResCompanyJurisdictionPadron(models.Model):
    _inherit = "res.company.jurisdiction.padron"

    def check_state_id(self):
        # Sobreescribimos el método para desactivar la validación del código de jurisdicción
        pass
