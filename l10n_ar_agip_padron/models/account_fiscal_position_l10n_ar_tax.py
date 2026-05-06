import base64
import logging
import requests
import io
import zipfile
from datetime import datetime
import tempfile
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AccountFiscalPositionL10nArTax(models.Model):
    _inherit = "account.fiscal.position.l10n_ar_tax"



    def _get_agip_data(self, partner, date, to_date):
        self.ensure_one()
        cuit = partner.ensure_vat().replace("-", "").strip()

        padron = self.env['l10n_ar.agip.padron'].search([
        ('fecha_desde', '<=', date),
        ('fecha_hasta', '>=', date),
        ], order='create_date desc', limit=1)

        if padron:
            try:
                decoded_file = base64.b64decode(padron.archivo_txt)
                tmp_dir = tempfile.mkdtemp()
                zip_path = os.path.join(tmp_dir, 'padron_agip.zip')
                with open(zip_path, 'wb') as f:
                    f.write(decoded_file)

                with zipfile.ZipFile(zip_path, 'r') as zip_file:
                    txt_files = [f for f in zip_file.namelist() if f.lower().endswith('.txt')]
                    if not txt_files:
                        _logger.warning("El ZIP del padrón AGIP no contiene archivos .txt")
                        return None, "ZIP sin TXT"
                    txt_name = txt_files[0]
                    zip_file.extract(txt_name, path=tmp_dir)

                    txt_path = os.path.join(tmp_dir, txt_name)
                    with open(txt_path, 'r', encoding='latin1') as txt_file:
                        for line in txt_file:
                            partes = line.strip().split(';')
                            if len(partes) < 9:
                                continue
                            cuit_linea = partes[3].replace("-", "").strip()
                            if cuit_linea == cuit:
                                aliquot = float(partes[8].replace(",", ".")) if self.tax_type == 'withholding' else float(partes[7].replace(",", "."))
                                razon_social = partes[12].strip() if len(partes) > 12 else (partes[11].strip() if len(partes) > 11 else None)
                                return aliquot, razon_social or "Padrón AGIP ZIP"
            except Exception as e:
                _logger.warning("Error procesando ZIP del padrón AGIP: %s", str(e))

        _logger.info("CUIT %s no encontrado en padrón AGIP local ni adjuntos", cuit)

        # WebService fallback
        token = self.env['ir.config_parameter'].sudo().get_param('agip_token')
        sign = self.env['ir.config_parameter'].sudo().get_param('agip_sign')
        if not token or not sign:
            _logger.warning("CUIT %s no está en padrón local y no hay credenciales AGIP", cuit)
            return None, "Sin padrón y sin WS"

        url = "https://hml.agip.gob.ar/padron/webservice/ISIBWS"
        body = {"token": token, "sign": sign, "cuit": cuit}
        try:
            response = requests.post(url, json=body, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            raise UserError(_("Error al conectar con el servicio AGIP: %s") % str(e))

        if data.get("statusCode") == 0:
            aliquot = float(data["result"]["alicRetencion"]) if self.tax_type == "withholding" else float(data["result"]["alicPercepcion"])
            return aliquot, data["result"]["razonSocialSalida"]
        else:
            return None, "No inscripto WS: %s - %s" % (data.get("statusCode"), data.get("status"))
