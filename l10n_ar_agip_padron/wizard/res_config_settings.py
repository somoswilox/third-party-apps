import logging
import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"
    
    agip_token = fields.Char(
        string="Token de AGIP",
        related="company_id.agip_token",
        readonly=False,
    )

    agip_sign = fields.Char(
        string="Firma de AGIP",
        related="company_id.agip_sign",
        readonly=False,
    )

    
    def l10n_ar_agip_test_connection(self):
        self.ensure_one()
        token = self.company_id.agip_token
        sign = self.company_id.agip_sign
        cuit = self.company_id.partner_id.ensure_vat()

        if not token or not sign:
            raise UserError(_("Debe configurar el Token y la Firma de AGIP."))

        url = "https://hml.agip.gob.ar/padron/webservice/ISIBWS"
        body = {
        "token": token,
        "sign": sign,
        "cuit": cuit,  # o podés usar un CUIT fijo de prueba
        }

        try:
            response = requests.post(url, json=body, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            _logger.error("Error al conectar a AGIP: %s", str(e))
            raise UserError(_("No se pudo conectar al servicio AGIP: %s") % str(e))

        if data.get("statusCode") == 0:
            raise UserError(_("La conexión a AGIP fue exitosa."))
        else:
            raise UserError(
            _("Error en la respuesta de AGIP.\nCódigo: %s\nMensaje: %s")
            % (data.get("statusCode"), data.get("status"))
        )

