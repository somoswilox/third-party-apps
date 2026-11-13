# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import fields, models, api
from odoo.exceptions import AccessError, UserError
from odoo.tools.translate import _
import logging
_logger = logging.getLogger(__name__)
import pdb
#from .warning import warning
import requests
from .versions import *
import os

# Nivel de seguridad de las integraciones (auditoría caso-K14 cliente W, #caso-K19).
# Predeterminado = el comportamiento de siempre. Bajo = sólo el estado de conexión desde afuera.
# Alto = ninguna consulta ni acción desde afuera: quedan sólo los webhooks y el login del canal.
OCAPI_SECURITY_LEVELS = [
    ('default', 'Predeterminado'),
    ('low', 'Bajo'),
    ('high', 'Alto'),
]
_OCAPI_SECURITY_RANK = {'default': 0, 'low': 1, 'high': 2}
# Funcionalidad -> nivel MÁS ALTO en el que todavía está permitida.
_OCAPI_FEATURE_MAX_LEVEL = {
    'status': 'low',            # estado de conexión de la cuenta (monitoreo)
    'data': 'default',          # KPIs, exportación, catálogo, stock, precios, ventas, conectores
    'actions': 'default',       # acciones remotas: rebind, publicar stock, publicar precio
    'token_copy': 'default',    # copia de token entre producción y testing
    'token_in_chatter': 'default',  # token ENMASCARADO en chatter/log (nunca completo)
    'proxy': 'low',             # host alternativo a la API oficial (reverse proxy)
}


def ocapi_can_see_secrets(env):
    """Sólo superusuario o Administrador ven secretos y tokens (pantalla, RPC, exportación)."""
    return env.su or env.user.has_group('base.group_system')


_OCAPI_SECRET_SUFFIXES = ('secret_key', 'access_token', 'refresh_token', 'client_secret')


def ocapi_secret_fields(records):
    """Campos con secretos/tokens del modelo, reconocidos por el nombre.

    Por nombre y no por una lista declarada en cada módulo: así cubre también los campos que
    agregan módulos que no dependen de este (meli_oerp en res.company), sin depender del orden
    de carga.
    """
    return [f for f in records._fields if f.endswith(_OCAPI_SECRET_SUFFIXES)]


def ocapi_strip_secret_export(records, fields_to_export):
    if ocapi_can_see_secrets(records.env):
        return fields_to_export
    secret = set(ocapi_secret_fields(records))
    return [f for f in fields_to_export if f.split('/')[0] not in secret]


def ocapi_hide_secrets(records, vals_list):
    """Vacía los campos secretos en el resultado de un read para quien no es Administrador."""
    if ocapi_can_see_secrets(records.env):
        return vals_list
    secret = ocapi_secret_fields(records)
    if not secret:
        return vals_list
    for vals in vals_list:
        for f in secret:
            if f in vals:
                vals[f] = False
    return vals_list


class ResCompany(models.Model):

    _name = "res.company"
    _inherit = "res.company"

    ocapi_connections = fields.One2many( "ocapi.connection.account", "company_id", string="Connection Accounts", help="Odoo Connector Api Connection Accounts" )

    ocapi_security_level = fields.Selection(
        OCAPI_SECURITY_LEVELS, string="Nivel de seguridad", default='default', required=True,
        help="Qué se puede consultar o hacer desde afuera de Odoo en las integraciones.\n"
             "Predeterminado: como hasta ahora: estado de conexión (en las cuentas con Monitoreo), "
             "indicadores, acciones remotas y copia de token entre producción y testing.\n"
             "Bajo: sólo el estado de conexión (sin datos de ventas, clientes ni acciones); sin copia de "
             "token; los tokens no se registran en el chatter.\n"
             "Alto: ninguna consulta ni acción desde afuera; quedan sólo las notificaciones y el login del "
             "canal. La casilla Monitoreo queda apagada y sólo se usa la dirección oficial de la API.\n"
             "En todos los niveles: los tokens nunca se muestran completos y los secretos sólo los ve un "
             "Administrador.")

    @api.model
    def _ocapi_security_level_effective(self):
        """El nivel MÁS restrictivo entre las compañías (para rutas que no saben de qué compañía son)."""
        levels = self.sudo().search([]).mapped('ocapi_security_level') or ['default']
        return max(levels, key=lambda l: _OCAPI_SECURITY_RANK.get(l, 0))

    def _ocapi_security_allows(self, feature):
        """True si `feature` está permitida en el nivel de esta compañía (o el global si no hay compañía)."""
        level = (self and self.sudo()[:1].ocapi_security_level) or self._ocapi_security_level_effective()
        max_level = _OCAPI_FEATURE_MAX_LEVEL.get(feature, 'default')
        return _OCAPI_SECURITY_RANK.get(level, 0) <= _OCAPI_SECURITY_RANK[max_level]

    def _read_format(self, fnames, load='_classic_read'):
        return ocapi_hide_secrets(self, super()._read_format(fnames, load=load))

    def export_data(self, fields_to_export):
        return super().export_data(ocapi_strip_secret_export(self, fields_to_export))

    def write(self, vals):
        if 'ocapi_security_level' in vals:
            if not ocapi_can_see_secrets(self.env):
                raise AccessError(_("Sólo un Administrador puede cambiar el Nivel de seguridad."))
            for company in self:
                if company.ocapi_security_level != vals['ocapi_security_level']:
                    _logger.warning("OCAPI nivel de seguridad: compañía %s %s -> %s (usuario %s)",
                                    company.id, company.ocapi_security_level,
                                    vals['ocapi_security_level'], self.env.user.login)
        res = super().write(vals)
        if vals.get('ocapi_security_level') == 'high':
            accounts = self.env['ocapi.connection.account'].sudo().search(
                [('company_id', 'in', self.ids), ('connection_monitor', '=', True)])
            if accounts:
                accounts.write({'connection_monitor': False})
        return res


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    @api.model
    def ocapi_cleanup_filestore(self, options=None ):

        _logger.info("ocapi_cleanup_filestore > options:" +str(options) )

        offset =(options and "offset" in options and options["offset"]) or 0
        limit = (options and "limit" in options and options["limit"]) or 500
        delete_files = (options and "delete_files" in options and options["delete_files"]) or False
        create_date = (options and "create_date" in options and options["create_date"]) or False
        list_files_to_delete = []


        _logger.info("ocapi_cleanup_filestore > offset: " + str(offset) + " limit:" + str(limit)+ " delete_files:" + str(delete_files) )

        # Get all attachments in the filestore
        #filestore_path = self.env['ir.config_parameter'].get_param('ir_attachment.location')
        filestore_path = self.env['ir.attachment']._filestore()
        _logger.info("ocapi_cleanup_filestore > filestore_path: " + str(filestore_path) )

        sql_attachments_pimage_non_active = """SELECT ira.id, store_fname, res_model, res_id, file_size, res.name, pp.active FROM ir_attachment ira, product_image res, product_template pp WHERE store_fname IS NOT NULL AND res_model = 'product.image' and res.id = res_id AND res.product_tmpl_id = pp.id AND pp.active = False;"""
        cr = MeliCr( self )
        cr.execute(sql_attachments_pimage_non_active)
        att_results = cr.fetchall()
        if att_results and att_results[0]:
            _logger.info("ocapi_cleanup_filestore > attachments pimage non active query result[0]: "+str(att_results and att_results[0]))
        _logger.info("ocapi_cleanup_filestore > attachments pimage non active query results: "+str(att_results and len(att_results)))

        sql_attachments = """SELECT id, store_fname, res_model, res_id, file_size FROM ir_attachment WHERE store_fname IS NOT NULL"""
        cr = MeliCr( self )
        cr.execute(sql_attachments)
        att_results = cr.fetchall()
        if att_results and att_results[0]:
            _logger.info("ocapi_cleanup_filestore > attachments query result[0]: "+str(att_results and att_results[0]))
        _logger.info("ocapi_cleanup_filestore > attachments query results: "+str(att_results and len(att_results)))


        filestore_files = os.listdir(filestore_path)
        filestore_files_sub = []
        for subdir in filestore_files:
            subdir_list = os.listdir(filestore_path+"/"+subdir)
            for subdir_file in subdir_list:
                file_store_fname = str(subdir+"/"+subdir_file)
                filestore_files_sub+= [file_store_fname]

        _logger.info("ocapi_cleanup_filestore > filestore_files: " + str(len(filestore_files_sub)) )

        attachment_in_storage = []
        attachment_not_in_storage = []
        storage_not_in_attachments = []

        _logger.info("ocapi_cleanup_filestore > attachments: "+str(self.sudo().search_count([])) )

        domain = []
        domain_date = (create_date and [('create_date','<',create_date)]) or []
        domain+= domain_date
        _logger.info("ocapi_cleanup_filestore > domain: "+str(domain))

        # Iterate over all attachments in the database
        att_results_index = {}
        if att_results:
          for attachment in att_results:
              # Check if the attachment's file is in the filestore
              #store_fname_sub = attachment.store_fname[3:]
              store_fname_sub = attachment[1]
              att_results_index[store_fname_sub] = {
                'count': (store_fname_sub in att_results_index and (att_results_index[store_fname_sub]['count']+1)) or 1
                ,
                'attachment': attachment
              }
              if store_fname_sub and store_fname_sub in filestore_files_sub:
                  attachment_in_storage.append(attachment)
              else:
                  if store_fname_sub:
                      attachment_not_in_storage.append(attachment)

        _logger.info("ocapi_cleanup_filestore > attachment_in_storage > "+str(len(attachment_in_storage)) )
        _logger.info("ocapi_cleanup_filestore > attachment_not_in_storage > "+str(len(attachment_not_in_storage)) )

        storage_not_in_attachments = []

        file_count = 0
        file_count_to_delete = 0
        for store_fname in filestore_files_sub:
            file_count+= 1
            #if not self.sudo().search([('store_fname', '=', store_fname)]):
            #    storage_not_in_attachments.append(store_fname)
            if store_fname and not (store_fname in att_results_index):
                file_count_to_delete+= 1
                storage_not_in_attachments.append(store_fname)
                list_files_to_delete.append(store_fname)

            if (file_count>=limit):
                break;

        _logger.info("ocapi_cleanup_filestore > storage_not_in_attachments > "+str(len(storage_not_in_attachments)) )
        _logger.info("ocapi_cleanup_filestore > storage_not_in_attachments > "+str(storage_not_in_attachments) )

                # Check if the attachment is referenced in the database
        #        if not self.search([('store_fname', '=', attachment.store_fname)]):
                    # The attachment is not referenced in the database, so delete the file
        #            _logger.info("ocapi_cleanup_filestore > file to unlink: " + str(attachment.store_fname) )
        #            list_files_to_delete.append(attachment)
                    #os.unlink(os.path.join(filestore_path, attachment.store_fname))
        _logger.info("ocapi_cleanup_filestore > list_files_to_delete: "+str(len(list_files_to_delete)) )

        if delete_files and list_files_to_delete:
            for attachment_fname in list_files_to_delete:
                os.unlink(os.path.join(filestore_path, attachment_fname))
