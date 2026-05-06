
import base64
import io
import zipfile
from datetime import datetime

from dateutil.relativedelta import relativedelta
from odoo import _, api, fields, models
from odoo.exceptions import RedirectWarning, UserError, ValidationError

class L10nArAgipPadron(models.Model):
    _name = "l10n_ar.agip.padron"
    _description = "Padrón AGIP Importado"

    nombre_archivo = fields.Char("Nombre del archivo")
    archivo_txt = fields.Binary("Archivo Padrón .txt", required=True)
    fecha_desde = fields.Date(string="Vigencia Desde", required=True)
    fecha_hasta = fields.Date(string="Vigencia Hasta", required=True)
    fecha_proceso = fields.Datetime(string="Fecha de Importación", default=fields.Datetime.now)


    
class AgipPadronImportWizard(models.TransientModel):
    _name = 'agip.padron.import.wizard'
    _description = 'Importador de Padrón AGIP'

    archivo = fields.Binary(string="Archivo RAR o ZIP", required=True)
    nombre_archivo = fields.Char("Nombre del archivo")
    fecha_desde = fields.Date(string="Vigencia Desde", required=True)
    fecha_hasta = fields.Date(string="Vigencia Hasta", required=True)

    def action_importar(self):
        self.ensure_one()

        if not self.nombre_archivo.lower().endswith(('.zip', '.rar', '.txt')):
            raise UserError(_("Solo se permiten archivos .zip, .rar o .txt"))

        datos_binarios = base64.b64decode(self.archivo)
        buffer = io.BytesIO(datos_binarios)

        if self.nombre_archivo.lower().endswith('.zip'):
            archivo = zipfile.ZipFile(buffer)
            nombres_txt = [f for f in archivo.namelist() if f.lower().endswith('.txt')]
            if not nombres_txt:
                raise UserError(_("El ZIP no contiene archivos .txt"))
            contenido = archivo.read(nombres_txt[0])
            nombre_txt = nombres_txt[0]

        elif self.nombre_archivo.lower().endswith('.rar'):
            try:
                archivo_rar = rarfile.RarFile(buffer)
                nombres_txt = [f for f in archivo_rar.namelist() if f.lower().endswith('.txt')]
                if not nombres_txt:
                    raise UserError(_("El RAR no contiene archivos .txt"))
                contenido = archivo_rar.read(nombres_txt[0])
                nombre_txt = nombres_txt[0]

                # 💡 Aquí lo reenvasamos como ZIP por si más adelante se quiere guardar así
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w') as zipf:
                    zipf.writestr(nombre_txt, contenido)
                zip_buffer.seek(0)
                # Si necesitás seguir trabajando como ZIP, podés usar `zip_buffer`

            except rarfile.Error as e:
                raise UserError(_("No se pudo procesar el archivo RAR: %s") % str(e))

        else:
            contenido = datos_binarios
            nombre_txt = self.nombre_archivo

        # Guardamos el archivo TXT extraído
        self.env['l10n_ar.agip.padron'].create({
            'nombre_archivo': nombre_txt,
            'archivo_txt': base64.b64encode(contenido),
            'fecha_desde': self.fecha_desde,
            'fecha_hasta': self.fecha_hasta,
        })

