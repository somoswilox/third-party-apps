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
import logging
import re
import json

import logging
_logger = logging.getLogger(__name__)

from dateutil.parser import *
from datetime import *
from urllib.request import urlopen
import requests
try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode


import base64
from odoo.addons.meli_oerp.models.versions import *
from odoo.addons.meli_oerp_accounting.models.versions import *



class Invoice(models.Model):

    _inherit = acc_inv_model

    #@api.multi
    def __firmar_factura_electronica(self):
        #_logger.info("meli_oerp: firmar_factura_electronica")
        try:
            for inv in self:
                res = super( Invoice, inv ).firmar_factura_electronica()
                origin = "origin" in inv._fields and inv.origin
                origin = "invoice_origin" in inv._fields and inv.invoice_origin
                sorder = self.env['sale.order'].search([('name','=',origin)], limit=1)
                if sorder:
                    if sorder and sorder.meli_orders:
                        sorder.meli_orders[0].orders_post_invoice()

        except Exception as e:
            raise e;

    def wsfe_get_cae_request(self, client=None):
        """Override to use billing child's fiscal data for DocTipo/DocNro and CondicionIVAReceptorId.

        l10n_ar_edi reads DocTipo/DocNro from self.commercial_partner_id and CondicionIVAReceptorId
        from self.partner_id. MeLi billing children hold fiscal data (CUIT, identification_type,
        afip_responsibility_type) on the child, not on commercial_partner_id (buyer parent).

        Problem: base Odoo _post() resets self.partner_id to commercial_partner_id BEFORE calling
        AFIP, so by the time this method is called self.partner_id may already equal
        commercial_partner_id — losing the billing child's fiscal data.

        Fix: capture the billing child ID in context (meli_billing_child_id) BEFORE action_post()
        is called (in order.py) and use that as primary source here for all three fields.
        """
        res = super().wsfe_get_cae_request(client=client)

        # Primary source: billing child captured in context before base _post() could reset it.
        # Fallback: current self.partner_id if it differs from commercial_partner_id.
        _ctx_child_id = self.env.context.get('meli_billing_child_id')
        if _ctx_child_id:
            bp = self.env['res.partner'].browse(_ctx_child_id)
            if not bp.exists():
                bp = None
        else:
            bp = self.partner_id if (self.partner_id and self.partner_id != self.commercial_partner_id) else None

        if (bp
                and 'l10n_latam_identification_type_id' in bp._fields
                and bp.l10n_latam_identification_type_id
                and bp.vat):
            _afip_id_code = bp.l10n_latam_identification_type_id.l10n_ar_afip_code
            if _afip_id_code:
                try:
                    _vat_sanitized = (
                        bp._get_id_number_sanitize()
                        if hasattr(bp, '_get_id_number_sanitize')
                        else bp.vat
                    )
                    _detail = (res.get('FeDetReq') or [{}])[0].get('FECAEDetRequest', {})
                    _old_doc_tipo = _detail.get('DocTipo')
                    _old_doc_nro = _detail.get('DocNro')
                    _detail['DocTipo'] = _afip_id_code
                    _detail['DocNro'] = int(_vat_sanitized) if _vat_sanitized else 0
                    _logger.info(
                        "wsfe_get_cae_request: billing child id:%s (vat=%s) → "
                        "DocTipo %s→%s DocNro %s→%s",
                        bp.id, bp.vat, _old_doc_tipo, _afip_id_code,
                        _old_doc_nro, _detail['DocNro']
                    )
                except Exception as _e:
                    _logger.warning(
                        "wsfe_get_cae_request: no se pudo sobreescribir DocTipo/DocNro "
                        "desde billing child id:%s: %s", bp.id, _e
                    )

        # Fix CondicionIVAReceptorId:
        # base l10n_ar_edi sets it from self.partner_id.l10n_ar_afip_responsibility_type_id.code
        # which is a Char (Python string). AFIP expects xsd:short (integer). Zeep may or may not
        # coerce the string correctly. More critically: when billing child data is available
        # (from context), we should always prefer it over whatever the base code set.
        _detail = (res.get('FeDetReq') or [{}])[0].get('FECAEDetRequest', {})
        _cur_cond_iva = _detail.get('CondicionIVAReceptorId')
        _cond_iva_source = 'base'

        if (bp
                and 'l10n_ar_afip_responsibility_type_id' in bp._fields
                and bp.l10n_ar_afip_responsibility_type_id
                and bp.l10n_ar_afip_responsibility_type_id.code):
            try:
                _new_cond_iva = int(bp.l10n_ar_afip_responsibility_type_id.code)
                _detail['CondicionIVAReceptorId'] = _new_cond_iva
                _cond_iva_source = 'billing_child:%s' % bp.id
            except Exception as _e:
                _logger.warning(
                    "wsfe_get_cae_request: no se pudo convertir CondicionIVAReceptorId "
                    "desde billing child id:%s code=%s: %s",
                    bp.id, bp.l10n_ar_afip_responsibility_type_id.code, _e
                )
        elif _cur_cond_iva is not None and _cur_cond_iva is not False:
            # Ensure int even when we don't have a billing child override
            try:
                _detail['CondicionIVAReceptorId'] = int(_cur_cond_iva)
            except (TypeError, ValueError):
                pass

        _logger.info(
            "wsfe_get_cae_request: invoice=%s partner=%s CbteTipo=%s DocTipo=%s DocNro=%s "
            "CondicionIVAReceptorId=%s (was=%r, source=%s)",
            self.id,
            self.partner_id.id,
            (res.get('FeCabReq') or {}).get('CbteTipo'),
            _detail.get('DocTipo'),
            _detail.get('DocNro'),
            _detail.get('CondicionIVAReceptorId'),
            _cur_cond_iva,
            _cond_iva_source,
        )

        # AFIP CbteTipo/CondicionIVAReceptorId compatibility mapping (RG5616).
        # FEParamGetCondicionIvaReceptor defines valid combinations per CbteTipo class:
        #   Clase B (CbteTipo 6,7,8 = Factura/Nota B): valid = {4 (Exento), 5 (CF), 7 (NC), 12-14}
        #     → 6 (Monotributista) is NOT valid for Clase B
        #   Clase A (CbteTipo 1,2,3): valid = {1 (RI), 4 (Exento), 10, 11}
        #   Clase C (CbteTipo 11,12,13): valid = {1,4,5,6,7,...}
        # When a Responsable Inscripto issues Factura B to a Monotributista, Argentine tax law
        # treats the recipient as "consumidor final" (code=5) for IVA purposes. Use 5 instead of 6.
        _cbte_tipo_str = str((res.get('FeCabReq') or {}).get('CbteTipo', ''))
        _final_cond_iva = _detail.get('CondicionIVAReceptorId')
        if _cbte_tipo_str in ('6', '7', '8') and _final_cond_iva == 6:
            _detail['CondicionIVAReceptorId'] = 5  # Consumidor Final
            _logger.info(
                "wsfe_get_cae_request: CondicionIVAReceptorId corregido Monotributista(6) → CF(5) "
                "para CbteTipo=%s (Factura/Nota B solo acepta CF/Exento/NC como receptor IVA)",
                _cbte_tipo_str,
            )

        return res

    def action_post(self):
        res = super(Invoice, self).action_post()
        for inv in self:
            if inv.move_type != 'out_invoice':
                continue
            # Buscar la orden de venta asociada
            sale_orders = self.env['sale.order']
            if inv.invoice_line_ids:
                for line in inv.invoice_line_ids:
                    if line.sale_line_ids:
                        sale_orders |= line.sale_line_ids.mapped('order_id')
            if not sale_orders and inv.invoice_origin:
                sale_orders = self.env['sale.order'].search(
                    [('name', '=', inv.invoice_origin.strip())], limit=1
                )
            for so in sale_orders:
                if not so.meli_orders:
                    continue
                for mo in so.meli_orders:
                    for payment in mo.payments:
                        if payment.account_payment_id and payment.status == 'approved':
                            try:
                                config = ("connection_account" in mo._fields and mo.connection_account and mo.connection_account.configuration)
                                config = config or so.company_id or self.env.user.company_id
                                payment.republish_invoice_payments(config=config)
                            except Exception as e:
                                _logger.warning(
                                    "action_post republish_invoice_payments error para pago %s: %s",
                                    payment.payment_id, str(e)
                                )
        return res

    def crear_facturas( self, config=None ):
        #
        #_logger.info("Crear Facturas "+str(config and config.name))

        XMLname = None
        XMLbytes = None

        PDFName = None
        PDFbytes = None
        #zip_content = BytesIO()
        #zip_content.write(base64.b64decode(self.attachment_file))

        #zip_file.writestr(, zip_content.getvalue())

        #XMLbytes = base64.b64decode(self.attachment_file)

        template = self.env.ref(report_invoices)
        if (report_invoices_name):
            #template = self.env["ir.actions.report"].search(('report_name','=ilike',''+str(report_invoices_name)))
            #_logger.info("report_invoices_name:"+str(report_invoices_name)+" founded in ir.actions.report > "+str(template))
            pass;

        report_id = (config and "mercadolibre_invoice_journal_report_id" in config._fields and config.mercadolibre_invoice_journal_report_id and config.mercadolibre_invoice_journal_report_id.id)
        if (report_id):
            template = self.env["ir.actions.report"].browse(report_id)
        else:
            if (report_invoices_id):
                template = self.env["ir.actions.report"].browse(report_invoices_id)
                #_logger.info("report_invoices_id: "+str(report_invoices_id)+" founded in ir.actions.report > "+str(template))
                pass;


        try:
            if self.env.ref('l10n_co_cei.account_invoices_fe'):

                if "attachment_file" in self._fields:
                    XMLbytes = self.attachment_file
                    XMLname = self.filename.replace('fv', 'ad').replace('nc', 'ad').replace('nd', 'ad') + '.xml'
                    PDFName = self.filename.replace('fv', 'ad').replace('nc', 'ad').replace('nd', 'ad') + '.pdf'
                    #_logger.info(XMLbytes)
                    #_logger.info(XMLname)

                template = self.env.ref('l10n_co_cei.account_invoices_fe')
        except:
            pass;

        # ----------------------------------------------------------------
        # BRASIL: extraer XML de NFe desde adjuntos del account.move
        # Los modulos brasileros (l10n_br_nfe, fokus, etc.) guardan el XML
        # como ir.attachment del tipo 'application/xml' o 'text/xml'
        # vinculado a la factura.
        # ----------------------------------------------------------------
        if not XMLbytes:
            try:
                company = self.company_id or self.env.user.company_id
                if company and company.country_id and company.country_id.code == 'BR':
                    # Buscar adjunto XML vinculado a esta factura
                    _xml_att = self.env['ir.attachment'].search([
                        ('res_model', '=', self._name),
                        ('res_id', '=', self.id),
                        '|', ('mimetype', 'in', ['application/xml', 'text/xml']),
                             ('name', 'ilike', '.xml'),
                    ], limit=1, order='id desc')
                    if _xml_att:
                        XMLbytes = _xml_att.datas
                        XMLname = _xml_att.name if _xml_att.name.endswith('.xml') else (_xml_att.name + '.xml')
                        _logger.info("BR_NFe_XML: encontrado adjunto XML id=%s nombre=%s factura=%s",
                                     _xml_att.id, XMLname, self.name)
                    else:
                        # Intentar campos propios de algunos modulos l10n_br
                        _br_xml_fields = ['nfe_xml', 'xml_file', 'l10n_br_xml_file',
                                          'nfce_xml', 'nfe_xml_file', 'xml_enviado']
                        for _fld in _br_xml_fields:
                            if _fld in self._fields and getattr(self, _fld, None):
                                _raw = getattr(self, _fld)
                                if isinstance(_raw, str):
                                    XMLbytes = base64.b64encode(_raw.encode('utf-8'))
                                else:
                                    XMLbytes = _raw
                                XMLname = re.sub(r'\W+', '', self.name or '') + '_nfe.xml'
                                _logger.info("BR_NFe_XML: campo %s = encontrado para factura %s", _fld, self.name)
                                break
                        if not XMLbytes:
                            _logger.warning("BR_NFe_XML: XML de NFe no encontrado para factura %s "
                                            "(ni adjuntos XML ni campos l10n_br). "
                                            "Verificar que la NFe este autorizada por SEFAZ antes de enviar a ML.",
                                            self.name)
            except Exception as _br_err:
                _logger.warning("BR_NFe_XML: error buscando XML de NFe para factura %s: %s",
                                self.name, str(_br_err))

        if (template):

            render_template = report_render( template, res_ids=[self.id])

            #_logger.info(render_template)
            #PDFbytes = base64.b64decode(base64.b64encode(render_template[0]))

            if not PDFbytes:
                PDFbytes = base64.b64encode(render_template[0])

            if not PDFName:
                PDFName = re.sub(r'\W+', '', self.name or self.number) + '.pdf'

            if ( 'sii_xml_dte' in self.env[acc_inv_model]._fields and self.sii_xml_dte ):
                #XMLbytes = base64.b64encode( bytes(self.sii_xml_dte, "ascii") )
                XMLbytes = base64.b64encode( bytes(self.sii_xml_dte, 'utf-8') )
                XMLname = re.sub( r'\W+', '', self.name or self.number ) + '.xml'

            #_logger.info(PDFbytes)
            #_logger.info(PDFName)
            #_logger.info(XMLname)

        return XMLname, XMLbytes, PDFName, PDFbytes

class OrdersInvoice(models.Model):

    _inherit = "mercadolibre.orders"

    invoice_pdf = fields.Binary(string='Invoice PDF')
    invoice_pdf_filename = fields.Char(string="PDF Filename")
    invoice_xml = fields.Binary(string='Invoice XML')
    invoice_xml_filename = fields.Char(string="XML Filename")

    invoice_fiscal_documents = fields.Char(string='Invoice Fiscal Documents',index=True)
    invoice_created = fields.Boolean(string='Invoice Created',index=True)
    invoice_posted = fields.Boolean(string='Invoice Posted',index=True)

    invoice_type = fields.Selection(string="Tipo de factura", selection=[('unknown','Indefinido'),('ticket','Boleta'),('invoice','Factura')],default='unknown',index=True)

    def button_import_payment_taxes(self):
        """Importar cargos/retenciones desde los pagos de esta orden."""
        for order in self:
            for payment in order.payments:
                payment.button_import_taxes()

    def orders_create_invoice(self, context=None, meli=None, config=None):
        #_logger.info("orders_create_invoice:"+str(context))
        self.invoice_created = True
        so = self and self.sale_order
        config = config or ("connection_account" in self._fields and self.connection_account and self.connection_account.configuration)
        config = config or so.company_id or self.env.user.company_id
        if (so):
            so.meli_create_invoice( meli=meli, config=config )


    def orders_post_invoice(self, context=None, meli=None, config=None):
        context = context or self.env.context
        _logger.info("orders_post_invoice: order=%s pack=%s invoice_posted=%s",
                     self.order_id, self.pack_id, self.invoice_posted)

        #self.invoice_posted = False
        if self.invoice_posted:
            _logger.info("orders_post_invoice: ya enviado, saltando order=%s", self.order_id)
            return;

        #_logger.info("Create binary PDF and XML for attach files")

        config = config or ("connection_account" in self._fields and self.connection_account and self.connection_account.configuration)
        company = (config and 'company_id' in config._fields and config.company_id)

        so = self.sale_order
        if so:
            config = config or so.company_id or self.env.user.company_id
            if not meli:
                if ("connection_account" in self._fields and self.connection_account):
                    account = self.connection_account
                    meli = self.env['meli.util'].get_new_instance(config, account)
                else:
                    meli = self.env['meli.util'].get_new_instance(config)

            invoices = self.env[acc_inv_model].search([(invoice_origin,'=',so.name)])
            #'estado_validacion': record['fe_approved'],
            respost = ""
            for inv in invoices:

                #chequear inv validacion
                #estado_dian = fields.Text(
                #    related="envio_fe_id.respuesta_validacion",
                #    copy=False
                #)
                files = []

                if ('estado_dian' in inv._fields and ( inv.estado_dian and 'Procesado Correctamente' in inv.estado_dian) and inv.zipped_file):
                    #_logger.info("Factura validada, generando.... para envio.")

                    XMLname, XMLbytes, PDFName, PDFbytes = inv.crear_facturas(config=config)

                    if PDFbytes:

                        self.invoice_pdf = PDFbytes
                        self.invoice_pdf_filename = PDFName
                    if XMLbytes:
                        self.invoice_xml = XMLbytes
                        self.invoice_xml_filename = XMLname
                else:
                    XMLname, XMLbytes, PDFName, PDFbytes = inv.crear_facturas()

                    if PDFbytes:
                        self.invoice_pdf = PDFbytes
                        self.invoice_pdf_filename = PDFName
                    if XMLbytes:
                        self.invoice_xml = XMLbytes
                        self.invoice_xml_filename = XMLname

                #TODO: reemplazar por opcion PDF, XML, o PDF+XML

                #XMLname = False
                #XMLbytes = False
                if PDFName and PDFbytes and XMLname and XMLbytes:
                    files = [ ('fiscal_document', ( PDFName, base64.b64decode(PDFbytes), 'application/pdf')),
                              ('fiscal_document', ( XMLname, base64.b64decode(XMLbytes), 'application/xml')) ]
                elif PDFName and PDFbytes:
                    files = [ ('fiscal_document', ( PDFName, base64.b64decode(PDFbytes), 'application/pdf'))]
                elif XMLname and XMLbytes:
                    files = [ ('fiscal_document', ( XMLName, base64.b64decode(XMLbytes), 'application/xml'))]

                    #files = [ ('fiscal_document', ( PDFName, base64.b64decode(PDFbytes), 'application/pdf')) ]
                    #files = [ ('fiscal_document', ( XMLname, base64.b64decode(XMLbytes), 'application/xml') ]

                do_not_send = ("mercadolibre_post_invoice_dont_send" in config._fields and config.mercadolibre_post_invoice_dont_send)

                _logger.info("orders_post_invoice: inv=%s PDFName=%s XMLname=%s files_count=%d do_not_send=%s meli=%s",
                             inv.name, PDFName, XMLname, len(files), do_not_send, bool(meli))
                if not files:
                    _logger.warning("orders_post_invoice: SIN ARCHIVOS para enviar a ML (order=%s inv=%s). "
                                    "Verificar que PDFbytes y/o XMLbytes no esten vacios. "
                                    "Para Brasil: el XML de NFe debe estar autorizado por SEFAZ antes de enviar.",
                                    self.order_id, inv.name)

                if meli and files and ( do_not_send == False ):
                    puri = "/packs/"+str(self.pack_id or self.order_id)+"/fiscal_documents"
                    _logger.info("order_post_invoice puri=%s files=%s", puri, [f[1][0] for f in files])
                    res = meli.uploadfiles(puri, files=files, params={ "access_token": meli.access_token } )
                    #_logger.info(res)
                    if res:
                        #_logger.info("order_post_invoice:"+str(res))
                        rjson = res.json()
                        respost += str(rjson)
                        #{'statusCode': 409, 'code': 'conflict', 'message': 'File Not allowed, the max amount of files already exist for the pack: 4433064137 and seller: 115266467', 'requestId': '557c88de-160f-4de9-a36d-2c01cb277ec6'}
                        #{'error': 'conflict', 'status': 409, 'message': 'File Not allowed, a file already exists for the pack: 2000013946902833 and seller: 51743280 of the type: application/pdf', 'cause': ['[]']}
                        if 'error' in rjson:
                            # GUARD idempotente: ML devuelve 409 conflict "File Not allowed ... already exist(s)"
                            # cuando el documento fiscal YA fue subido a ese pack (reintento del cron). No es un
                            # fallo: el archivo ya está en ML. Lo tratamos como ÉXITO para que el cron NO reintente
                            # el mismo pack y no ensucie el log con ERROR. Se distingue de otros 409 por el mensaje.
                            _status = rjson.get('status') or rjson.get('statusCode')
                            _code = str(rjson.get('code') or rjson.get('error') or "")
                            _msg = str(rjson.get('message') or "")
                            if ('already exist' in _msg.lower()) and (_status == 409 or 'conflict' in _code.lower()):
                                _logger.info("orders_post_invoice: documento fiscal ya presente en ML "
                                             "(409 idempotente, no se reintenta) order=%s pack=%s inv=%s: %s",
                                             self.order_id, self.pack_id, inv.name, _msg)
                            else:
                                _logger.error(rjson)
                                self.invoice_posted = False
                                self.invoice_fiscal_documents = respost
                                return res
                    self.invoice_posted = True

            self.invoice_fiscal_documents = respost
            self.invoice_type = ("boleta" in respost and "ticket") or ("factura" in respost and "invoice") or "unknown"


        #self.invoice_posted = False


    def orders_get_invoice(self, context=None, meli=None, config=None):
        #_logger.info("orders_get_invoice")

        context = context or self.env.context
        #_logger.info("orders_get_invoice: context: "+str(context))

        self.invoice_fiscal_documents = ""

        config = config or ("connection_account" in self._fields and self.connection_account and self.connection_account.configuration)
        company = (config and 'company_id' in config._fields and config.company_id)

        so = self.sale_order
        if so:
            config = config or so.company_id or self.env.user.company_id

            if "mercadolibre_post_invoice" in config._fields and not config.mercadolibre_post_invoice:
                return

            if not meli:
                if ("connection_account" in self._fields and self.connection_account):
                    account = self.connection_account
                    meli = self.env['meli.util'].get_new_instance(config, account)
                else:
                    meli = self.env['meli.util'].get_new_instance(config)

            #xxxx
            #res = meli.uploadfiles("/packs/"+str(self.pack_id or self.order_id)+"/fiscal_documents", files=files, params={ "access_token": meli.access_token } )
            respost = ""
            res = meli.get("/packs/"+str(self.pack_id or self.order_id)+"/fiscal_documents", params={ "access_token": meli.access_token } )
            if res:
                #_logger.info(res.json())
                respost += str(res.json())

                if 'error' in res.json():
                    _logger.error("orders_get_invoice > " + str(self.name) + " > " + str(res.json()) )
                    self.invoice_posted = False
                    self.invoice_fiscal_documents = respost
                    return res

            self.invoice_posted = True
            self.invoice_fiscal_documents = respost
            self.invoice_type = ("boleta" in respost and "ticket") or ("factura" in respost and "invoice") or "unknown"


