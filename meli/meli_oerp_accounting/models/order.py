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
from odoo.tools.translate import _
import logging
_logger = logging.getLogger(__name__)
import traceback
import pdb
import requests
from odoo.addons.meli_oerp.models.versions import *
from odoo.addons.meli_oerp_accounting.models.versions import *

import ssl
import base64

class SaleOrder(models.Model):

    _inherit = "sale.order"

    def action_invoice_create(self, grouped=False, final=False, date=None):

        return super(SaleOrder,self)._create_invoices(grouped=grouped, final=final, date=date)

    def _meli_invoice_conditions( self, meli=None, config=None ):
        _logger.info("meli_oerp_accounting _meli_invoice_conditions")
        so = self
        mo = so and so.meli_order
        config = config or (so.meli_order and so.meli_order._get_config())
        default_condition = True

        if hasattr(self, '_get_dc_ids'):
            _logger.info("_get_dc_ids")
            val = self._get_dc_ids()
            
        if hasattr(self, '_default_journal_document_class_id'):
            _logger.info("_default_journal_document_class_id")
            val = self._default_journal_document_class_id()

        if hasattr(self, '_default_use_documents'):
            _logger.info("_default_use_documents")
            val = self._default_use_documents()
        
        if (mo and mo.buyer and mo.shipment_logistic_type != "fulfillment" and mo.buyer.billing_info_economic_activity):
            #CHILE
            economic_activity = mo.buyer.billing_info_economic_activity
            invoice_type = mo.buyer.billing_info_invoice_type
            to_invoice = (invoice_type and invoice_type == 'Factura') and economic_activity
            to_invoice = to_invoice or ( (invoice_type != 'Boleta') and economic_activity)
            return to_invoice
        
        return default_condition

    def _meli_cancel_invoices(self, config=None):
        """Handle invoices when MeLi cancels the order, based on config mode."""
        config = config or self.env.user.company_id
        mode = 'manual'
        if 'mercadolibre_invoice_cancel_mode' in config._fields:
            mode = config.mercadolibre_invoice_cancel_mode or 'manual'

        if mode == 'manual':
            return

        invoices = self.invoice_ids.filtered(lambda inv: inv.state == 'posted' and inv.move_type == 'out_invoice')

        # Also warn about already-cancelled invoices that have a CAE (were cancelled in error —
        # cannot create a credit note from state='cancel', needs manual restoration to draft first).
        cancelled_with_cae = self.invoice_ids.filtered(
            lambda inv: inv.state == 'cancel' and inv.move_type == 'out_invoice'
            and (getattr(inv, 'l10n_ar_afip_auth_mode', False)
                 or getattr(inv, 'l10n_ar_afip_cae', False)
                 or getattr(inv, 'l10n_ar_afip_auth_code', False))
        )
        for _cinv in cancelled_with_cae:
            _logger.warning(
                "CAE_CANCEL_ERROR: factura %s está CANCELADA pero tiene CAE/auth AFIP. "
                "Debe revertirla a borrador manualmente y luego crear una Nota de Crédito.",
                _cinv.name,
            )
            meli_message_post(
                self,
                "⚠️ ACCIÓN REQUERIDA: Factura <b>%s</b> fue cancelada en Odoo pero ya tenía "
                "un CAE asignado por AFIP/ARCA. Odoo no puede crear Nota de Crédito desde una "
                "factura cancelada.<br/>"
                "Pasos: 1) Abrir la factura → 'Restablecer a borrador' → 'Confirmar' → "
                "'Nota de crédito'." % _cinv.name,
                config=config,
            )

        if not invoices:
            return

        for inv in invoices:
            try:
                _effective_mode = mode

                # Protección Argentina: facturas electrónicas con CAE/auth asignado
                # NO se pueden cancelar — AFIP ya las registró. Forzar NC.
                # Chequeamos múltiples nombres de campo según versión de l10n_ar_edi.
                if _effective_mode in ('cancel', 'draft'):
                    _has_cae = (
                        getattr(inv, 'l10n_ar_afip_auth_mode', False)
                        or getattr(inv, 'l10n_ar_afip_cae', False)
                        or getattr(inv, 'l10n_ar_afip_auth_code', False)
                    )
                    _is_electronic = (
                        'l10n_latam_use_documents' in inv.journal_id._fields
                        and inv.journal_id.l10n_latam_use_documents
                    )
                    if _has_cae and _is_electronic:
                        _cae_val = (getattr(inv, 'l10n_ar_afip_auth_code', None)
                                    or getattr(inv, 'l10n_ar_afip_cae', None)
                                    or getattr(inv, 'l10n_ar_afip_auth_mode', None))
                        _logger.warning(
                            "CAE_PROTECT: factura %s tiene CAE/auth '%s' en journal electrónico — "
                            "forzando modo credit_note en lugar de '%s'",
                            inv.name, _cae_val, _effective_mode,
                        )
                        meli_message_post(
                            self,
                            "Factura %s tiene CAE asignado por AFIP — no se puede %s. "
                            "Se genera Nota de Crédito automáticamente." % (
                                inv.name,
                                'cancelar' if _effective_mode == 'cancel' else 'revertir a borrador',
                            ),
                            config=config,
                        )
                        _effective_mode = 'credit_note'

                if _effective_mode == 'draft':
                    # Remove reconciliation first
                    reconciled_lines = inv.line_ids.filtered(lambda l: l.account_id.reconcile and l.reconciled)
                    if reconciled_lines:
                        reconciled_lines.remove_move_reconcile()
                    inv.button_draft()
                    meli_message_post(self, "Factura %s revertida a borrador (orden cancelada por MeLi)." % inv.name, config=config)

                elif _effective_mode == 'cancel':
                    reconciled_lines = inv.line_ids.filtered(lambda l: l.account_id.reconcile and l.reconciled)
                    if reconciled_lines:
                        reconciled_lines.remove_move_reconcile()
                    inv.button_draft()
                    inv.button_cancel()
                    meli_message_post(self, "Factura %s cancelada (orden cancelada por MeLi)." % inv.name, config=config)

                elif _effective_mode == 'credit_note':
                    # Create a credit note (reversal) - safest accounting option
                    move_reversal = self.env['account.move.reversal'].with_context(
                        active_model='account.move',
                        active_ids=inv.ids,
                    ).create({
                        'journal_id': inv.journal_id.id,
                        'reason': 'Orden cancelada por MercadoLibre',
                    })
                    reversal = move_reversal.refund_moves()
                    if reversal and isinstance(reversal, dict) and reversal.get('res_id'):
                        credit_note = self.env['account.move'].browse(reversal['res_id'])
                        credit_note.action_post()
                        meli_message_post(self, "Nota de crédito %s creada y validada (orden cancelada por MeLi)." % credit_note.name, config=config)
                    else:
                        meli_message_post(self, "Nota de crédito creada para factura %s (orden cancelada por MeLi)." % inv.name, config=config)

            except Exception as e:
                _logger.error("Error al procesar factura %s en modo '%s': %s", inv.name, mode, e, exc_info=True)
                meli_message_post(self, "Error al %s factura %s: %s. Gestionar manualmente." % (
                    {'draft': 'revertir', 'cancel': 'cancelar', 'credit_note': 'crear nota de crédito para'}.get(mode, mode),
                    inv.name, str(e)
                ), config=config)

    def _diagnose_afip_10016(self, inv, error_text=''):
        """When AFIP returns Code 10016 (sequence mismatch), try to call
        FECompUltimoAutorizado and return a human-readable diagnosis string
        showing the gap between what Odoo tried and what AFIP expects.

        Returns a Markup HTML string for the chatter, or '' if diagnosis failed.
        """
        try:
            from markupsafe import Markup
        except ImportError:
            Markup = str

        try:
            company = inv.company_id
            journal = inv.journal_id

            # Extract what Odoo was trying to send
            odoo_pto_vta = getattr(journal, 'l10n_ar_afip_pos_number', None)
            doc_type = inv.l10n_latam_document_type_id if 'l10n_latam_document_type_id' in inv._fields else None
            odoo_cbte_tipo = doc_type and getattr(doc_type, 'code', None)

            # The document number may not be assigned yet in draft. Try multiple sources:
            odoo_cbte_nro = None
            # 1) l10n_latam_document_number (set during _post if it got far enough)
            if 'l10n_latam_document_number' in inv._fields and inv.l10n_latam_document_number:
                odoo_cbte_nro = inv.l10n_latam_document_number
            # 2) inv.name (e.g. "FA-B 00002-00026389")
            if not odoo_cbte_nro and inv.name and inv.name not in ('/', ''):
                _name = inv.name
                if '-' in _name:
                    odoo_cbte_nro = _name
            # 3) Parse CbteDesde from the AFIP error/XML text
            if not odoo_cbte_nro and error_text:
                import re
                _cbte_match = re.search(r'CbteDesde[>\s:=]+(\d+)', error_text)
                if _cbte_match:
                    odoo_cbte_nro = _cbte_match.group(1)

            if not odoo_pto_vta or not odoo_cbte_tipo:
                return ""

            # Try to get AFIP's last authorized number via the l10n_ar_edi connection.
            # The connection object from company._l10n_ar_get_connection('wsfe') is an
            # Odoo record (l10n_ar.afipws.connection) — NOT a pyafipws instance. To call
            # FECompUltimoAutorizado we need to go through its _get_client() zeep wrapper
            # or find a nested ._ws attribute. Use the same multi-pattern helper that
            # the AFIP sync wizard uses.
            afip_last = None
            try:
                if hasattr(company, '_l10n_ar_get_connection'):
                    ws = company._l10n_ar_get_connection('wsfe')
                    if ws:
                        SyncWiz = self.env.get('meli.afip.sequence.sync.wizard')
                        if SyncWiz:
                            afip_last = SyncWiz._call_fe_comp_ultimo_autorizado(
                                ws, int(odoo_pto_vta), int(odoo_cbte_tipo),
                            )
                        else:
                            # Inline fallback if wizard model not loaded
                            if hasattr(ws, '_get_client'):
                                client_result = ws._get_client()
                                if isinstance(client_result, tuple) and len(client_result) >= 2:
                                    client, auth = client_result[0], client_result[1]
                                else:
                                    client, auth = client_result, {}
                                if hasattr(client, 'service'):
                                    response = client.service.FECompUltimoAutorizado(
                                        Auth=auth, PtoVta=int(odoo_pto_vta), CbteTipo=int(odoo_cbte_tipo),
                                    )
                                    afip_last = int(response.CbteNro or 0)
            except Exception as ws_err:
                _logger.warning("_diagnose_afip_10016: could not query FECompUltimoAutorizado: %s", ws_err)

            # Build the diagnosis message as plain text lines, then join with <br/>
            parts = []
            parts.append("<b>DIAGNÓSTICO AUTOMÁTICO (Error AFIP 10016 — secuencia desalineada)</b>")
            parts.append("Punto de Venta: <b>%s</b>" % odoo_pto_vta)
            parts.append("Tipo de Comprobante: <b>%s</b> (%s)" % (
                odoo_cbte_tipo, doc_type and doc_type.name or ''))
            parts.append("Número que Odoo intentó emitir: <b>%s</b>" % (odoo_cbte_nro or '(no asignado aún)'))

            if afip_last is not None:
                afip_next = int(afip_last) + 1
                parts.append("Último autorizado en ARCA/AFIP: <b>%s</b>" % afip_last)
                parts.append("Próximo esperado por ARCA: <b>%s</b>" % afip_next)
                try:
                    odoo_num = int(str(odoo_cbte_nro).split('-')[-1]) if odoo_cbte_nro else 0
                    gap = odoo_num - afip_next
                    if gap > 0:
                        parts.append("Odoo va <b>%d adelante</b> de AFIP → ajustar secuencia del diario a %s" % (gap, afip_next))
                    elif gap < 0:
                        parts.append("Odoo va <b>%d atrás</b> de AFIP → ajustar secuencia del diario a %s" % (abs(gap), afip_next))
                    else:
                        parts.append("Los números coinciden — el problema puede ser la <b>fecha</b> del comprobante.")
                except (ValueError, TypeError):
                    pass
                parts.append("")
                parts.append("<b>ACCIÓN:</b> Ir a Contabilidad → Configuración → Diarios → '%s' "
                             "→ Secuencia → Ajustar 'Siguiente número' a <b>%s</b>, "
                             "luego borrar esta factura borrador y reintentarla." % (
                                 journal.name, afip_next))
            else:
                parts.append("No se pudo consultar FECompUltimoAutorizado automáticamente (ARCA no disponible "
                             "o el módulo l10n_ar_edi no expone la conexión desde este contexto).")
                parts.append("")
                parts.append("<b>ACCIÓN MANUAL:</b> Abrir el diario '%s', consultar el último número "
                             "autorizado con ARCA para PtoVta=%s CbteTipo=%s, y ajustar la secuencia." % (
                                 journal.name, odoo_pto_vta, odoo_cbte_tipo))

            return Markup("<br/>".join(parts))

        except Exception as diag_err:
            _logger.warning("_diagnose_afip_10016 failed: %s", diag_err)
            return ""

    def meli_create_invoice( self, meli=None, config=None):
        _logger.info("meli_oerp_accounting meli_create_invoice started. SO=%s state=%s invoice_status=%s",
                     self.name,
                     getattr(self, 'state', '?'),
                     getattr(self, 'invoice_status', '?'))

        context = self.env.context
        invoice_force = context.get('invoice_force')
        source = context.get('source')

        so = self
        config = config or (so.meli_order and so.meli_order._get_config())
        _logger.info("meli_oerp_accounting > meli_create_invoice > config:"+str(config and config.name)
                        +" context:"+str(context))
        special_condition = self._meli_invoice_conditions(meli=meli, config=config)
        _logger.info("Verifying conditions: special_condition: "+str(special_condition) + " state: "+str(so.state ))
        #solo ordenes confirmadas o terminadas
        # TODO check meli_status_brief: if (self.meli_status_brief and "delivered" in self.meli_status_brief
        if special_condition and so.state in ['sale','done']:
            #cond = so.invoice_status not in ['invoiced','no','upselling']
            received_amount = so.meli_amount_to_invoice( meli=meli, config=config )
            # coupon_amount es costo de ML, no del vendedor — el SO tiene el precio completo.
            # Tolerancia extendida como safety-net para órdenes anteriores al fix
            # que todavía tengan el descuento incorrecto en líneas.
            _inv_tolerance = 1.0
            _inv_coupon = abs(so.meli_coupon_amount or 0.0) if hasattr(so, 'meli_coupon_amount') else 0.0
            if _inv_coupon > 0:
                _inv_tolerance = max(_inv_tolerance, _inv_coupon * 1.3)
            # Retention taxes (negative %) reduce amount_total below transaction_amount.
            # Add back their absolute value so the check compares like-for-like.
            # Skip withholding-on-payment taxes — they belong on the payment, not SO lines.
            tax_field = SaleOrderLineTaxField(so)
            _inv_has_wth = 'is_withholding_tax_on_payment' in self.env['account.tax']._fields
            _inv_retention_total = 0.0
            for line in so.order_line:
                if line.price_unit <= 0:
                    continue
                for tax in line[tax_field]:
                    if tax.amount < 0:
                        if _inv_has_wth and tax.is_withholding_tax_on_payment:
                            continue
                        _inv_retention_total += abs(line.price_subtotal * tax.amount / 100.0)
            _inv_amount_total = so.amount_total + _inv_retention_total
            _inv_diff_direct = abs( received_amount - _inv_amount_total )
            # For self_service logistics the SO has no shipping line but
            # meli_paid_amount includes the shipping amount. Accept if diff
            # is fully explained by shipping not included in the SO.
            _inv_shipping = (so.meli_shipping_amount or 0.0) if hasattr(so, 'meli_shipping_amount') else 0.0
            # For fulfillment orders, the shp_fulfillment charge is stored in
            # meli_shipping_seller_cost — not in meli_shipping_amount (which
            # is what the buyer pays). received_amount includes shp_fulfillment
            # so the diff equals seller_cost when the SO has no shipping line.
            _inv_ship_seller = (so.meli_shipping_seller_cost or 0.0) if hasattr(so, 'meli_shipping_seller_cost') else 0.0
            _inv_diff_no_ship = abs( received_amount - _inv_shipping - _inv_amount_total ) if _inv_shipping > 0 else _inv_diff_direct
            _inv_diff_no_ship_seller = abs( received_amount - _inv_ship_seller - _inv_amount_total ) if _inv_ship_seller > 0 else _inv_diff_direct
            _is_fulfillment = (
                hasattr(so, 'meli_shipment_logistic_type')
                and so.meli_shipment_logistic_type
                and 'fulfillment' in so.meli_shipment_logistic_type
            )
            # For fulfillment orders, meli_shipping_amount at SO level is 0 (ML doesn't expose
            # buyer's shipping at order level for fulfillment). The buyer's actual shipping amount
            # lives in the payment's shipping_amount field. Read it from there so the diff check
            # can correctly determine that (total_paid - buyer_shipping) == SO amount_total.
            if _is_fulfillment and _inv_shipping == 0 and so.meli_orders:
                for _mo in so.meli_orders:
                    for _pmt in (_mo.payments if hasattr(_mo, 'payments') else []):
                        _pmt_ship = getattr(_pmt, 'shipping_amount', 0.0) or 0.0
                        if _pmt_ship > 0:
                            _inv_shipping = _pmt_ship
                            _inv_diff_no_ship = abs(received_amount - _inv_shipping - _inv_amount_total)
                            _logger.info(
                                "FULFILLMENT_SHIP: SO %s shipping_amount %.2f from payment %s "
                                "→ diff_no_ship=%.2f",
                                so.name, _inv_shipping,
                                getattr(_pmt, 'payment_id', _pmt.id), _inv_diff_no_ship,
                            )
                            break
                    if _inv_shipping > 0:
                        break
            cond = True and (
                _inv_diff_direct < _inv_tolerance
                or (_inv_shipping > 0 and _inv_diff_no_ship < _inv_tolerance)
                or (_inv_ship_seller > 0 and _inv_diff_no_ship_seller < _inv_tolerance)
                or (_inv_shipping > 0 and _inv_diff_direct < _inv_shipping)
            )
            picking_dones = False
            picking_cancels = False
            picking_drafts = False
            if cond:
                if so.picking_ids:
                    for spick in so.picking_ids:
                        _logger.info(str(spick)+" state:"+str(spick.state))
                        if spick.state in ['done']:
                            picking_dones = True
                        elif spick.state in ['cancel']:
                            picking_cancels = True
                        else:
                            picking_drafts = True
                else:
                    picking_dones = False

                if picking_drafts:
                    #if a drafts then nothing is fully done
                    picking_dones = False

                _logger.info("Creating invoice... picking_dones:"+str(picking_dones))
                #invoices = self.env[acc_inv_model].search( [(invoice_origin,'=',so.name)] )
                invoices = self.invoice_ids
                _logger.info("Creating invoice... invoices:"+str(invoices))

                invoice_confirmation = config.mercadolibre_order_confirmation_invoice
                invoice_confirmation_full = config.mercadolibre_order_confirmation_invoice_full

                #si no esta definido factura...
                invoice_creation = not invoice_confirmation or ( invoice_confirmation and not "manual" in invoice_confirmation)
                invoice_creation_full = not invoice_confirmation_full or ( invoice_confirmation_full and not "manual" in invoice_confirmation_full)

                invoice_create = invoice_creation

                journal_id_invoice = "mercadolibre_invoice_journal_id" in config._fields and config.mercadolibre_invoice_journal_id
                journal_id_invoice_full = "mercadolibre_invoice_journal_id_full" in config._fields and config.mercadolibre_invoice_journal_id_full

                if (so.meli_shipment_logistic_type and "fulfillment" in so.meli_shipment_logistic_type):
                    invoice_create = invoice_creation_full
                    invoice_confirmation = invoice_confirmation_full
                    journal_id_invoice = journal_id_invoice_full or journal_id_invoice
                    _logger.info("Creating invoice... invoice_creation_full:"+str(invoice_creation_full))

                if (invoice_confirmation and "_delivered" in invoice_confirmation and not picking_dones):
                    invoice_create = False
                    _logger.info("Creating invoices not processed, shipment not complete: dones:"+str(picking_dones)+" drafts: "+str(picking_drafts)+" cancels:"+str(picking_cancels))

                if (invoice_force):
                    invoice_create = invoice_force
                _logger.info("Creating invoice... invoice_create:"+str(invoice_create)+" invoice_confirmation:"+str(invoice_confirmation))
                if not invoices and invoice_create:
                    _logger.info("Fixing order to invoice")
                    #if so.invoice_status in ['invoiced']:
                    #    so.invoice_status = 'to invoice'
                    #for oline in so.order_line:
                    #    oline.qty_invoiced = 0.0
                    #    oline.qty_to_invoice = oline.product_uom_qty
                    #    oline.invoice_status = 'to invoice'
                    default_journal_id = journal_id_invoice and journal_id_invoice.id
                    _logger.info("Creating invoices now... Journal Invoice:"+str(journal_id_invoice and journal_id_invoice.name))
                    result =  super(SaleOrder,self).with_context({'default_journal_id': default_journal_id })._create_invoices()
                    _logger.info("result:"+str(result))
                    #invoices = self.env[acc_inv_model].search([(invoice_origin,'=',so.name)])
                    invoices = self.invoice_ids
                    _logger.info("Created invoices: "+str(invoices))
                    #for inv in invoices:
                    #    if inv.journal_id and journal_id_invoice and inv.journal_id.id!=journal_id_invoice.id:
                    #        inv.journal_id = journal_id_invoice
                    #MeliCommit( self )
                    _logger.info("Commited: "+str(invoices))

                if invoices and invoice_create:
                    if len(invoices)>1:
                        _logger.error("meli_create_invoice > more than one invoice document do NOTHING! Wait for manual resolution!")
                        return {}

                    for inv in invoices:
                        if inv.state in ['cancel']:
                            _logger.error("meli_create_invoice > at least one cancelled invoice, do NOTHING! Wait for manual resolution!")
                            return {}

                    for inv in invoices:
                        #fix journal_id
                        if inv.journal_id and journal_id_invoice and inv.journal_id.id!=journal_id_invoice.id:
                            if (inv.state not in posted_statuses):
                                inv.journal_id = journal_id_invoice

                        # Auto-assign or correct l10n_latam_document_type_id on draft invoices.
                        # Fires when doc type is missing OR incompatible with partner's AFIP type.
                        # Typical cause: partner got fiscal data AFTER invoice creation (onchange
                        # never re-fired), OR billing_info updated AFIP type after doc type was set.
                        _early_partner = so.partner_invoice_id or inv.partner_id
                        _early_cur_doc = (inv.l10n_latam_document_type_id
                                          if 'l10n_latam_document_type_id' in inv._fields else None)
                        _early_afip_code = None
                        if _early_partner and hasattr(_early_partner, 'l10n_ar_afip_responsibility_type_id'):
                            _early_afip_r = _early_partner.l10n_ar_afip_responsibility_type_id
                            _early_afip_code = str(_early_afip_r.code) if _early_afip_r and _early_afip_r.code else None
                        _early_needs_fix = not _early_cur_doc or (
                            _early_cur_doc and _early_afip_code and (
                                (_early_cur_doc.code == '6' and _early_afip_code == '1')  # Factura B + IVA RI
                                or (_early_cur_doc.code == '1' and _early_afip_code not in ('1',))  # Factura A + non-RI (CF/MT/Exento/etc.)
                            )
                        )
                        if _early_needs_fix and _early_cur_doc:
                            _logger.info("Auto-correct doc_type: inv=%s has %s (%s) but partner afip=%s → will re-assign",
                                         inv.id, _early_cur_doc.code, _early_cur_doc.name, _early_afip_code)
                        if (inv.state in draft_statuses
                                and 'l10n_latam_document_type_id' in inv._fields
                                and _early_needs_fix):
                            try:
                                # Clear wrong doc type first so onchange can re-compute freely
                                if _early_cur_doc and _early_needs_fix:
                                    inv.l10n_latam_document_type_id = False
                                # Strategy 1: re-assign partner to trigger onchange
                                _partner_for_doctype = _early_partner
                                if _partner_for_doctype:
                                    inv.partner_id = _partner_for_doctype
                                # Strategy 2: explicit onchange call
                                if not inv.l10n_latam_document_type_id and hasattr(inv, '_onchange_partner_id'):
                                    inv._onchange_partner_id()
                                # Strategy 3: manual fallback from AFIP responsibility (string comparison)
                                if (not inv.l10n_latam_document_type_id
                                        and 'l10n_ar_afip_responsibility_type_id' in _partner_for_doctype._fields):
                                    _afip_resp = _partner_for_doctype.l10n_ar_afip_responsibility_type_id
                                    _afip_code_s = str(_afip_resp.code) if _afip_resp and _afip_resp.code else None
                                    _doc_code = None
                                    if _afip_code_s == '1':
                                        _doc_code = '1'  # Factura A — IVA Responsable Inscripto only
                                    else:
                                        _doc_code = '6'  # Factura B — CF, MT, Exento, or unknown
                                    if _doc_code and 'l10n_latam.document.type' in self.env:
                                        _doc_type = self.env['l10n_latam.document.type'].search([
                                            ('code', '=', _doc_code),
                                        ], limit=1)
                                        if _doc_type:
                                            inv.l10n_latam_document_type_id = _doc_type
                                if inv.l10n_latam_document_type_id:
                                    _logger.info("Auto-assigned document_type=%s (%s) on draft invoice %s",
                                                 inv.l10n_latam_document_type_id.code,
                                                 inv.l10n_latam_document_type_id.name, inv.id)
                                else:
                                    _logger.warning("Could not auto-assign document_type on draft invoice %s "
                                                    "(partner=%s afip_resp=%s)", inv.id,
                                                    _partner_for_doctype.name if _partner_for_doctype else 'None',
                                                    _partner_for_doctype.l10n_ar_afip_responsibility_type_id.name
                                                    if hasattr(_partner_for_doctype, 'l10n_ar_afip_responsibility_type_id')
                                                    and _partner_for_doctype.l10n_ar_afip_responsibility_type_id else 'None')
                            except Exception as _dt_err:
                                _logger.warning("Auto-assign document_type failed on invoice %s: %s", inv.id, _dt_err)

                        #try:
                        draft_validate = False
                        if inv.state in draft_statuses:
                            draft_validation = not config.mercadolibre_order_confirmation_invoice or ( config.mercadolibre_order_confirmation_invoice and not "_draft" in config.mercadolibre_order_confirmation_invoice)
                            draft_validation_full = not config.mercadolibre_order_confirmation_invoice_full or ( config.mercadolibre_order_confirmation_invoice_full and not "_draft" in config.mercadolibre_order_confirmation_invoice_full)
                            draft_validate = draft_validation
                            if (so.meli_shipment_logistic_type and "fulfillment" in so.meli_shipment_logistic_type):
                                draft_validate = draft_validation_full

                            # Skip AFIP validation if coming from notification (async) to avoid concurrent numbering issues
                            skip_invoice_validation = context.get('meli_skip_invoice_validation', False)
                            if skip_invoice_validation and draft_validate:
                                _logger.info("Skipping invoice validation (meli_skip_invoice_validation=True): %s", inv.name)
                                meli_message_post(so, "Factura creada en borrador (validación omitida por proceso async)", config=config)
                                draft_validate = False

                            # Sincronizar partner de factura con partner_invoice_id del pedido ANTES
                            # del chequeo fiscal. Si inv.partner_id es el contacto principal (sin datos
                            # fiscales) pero so.partner_invoice_id es el hijo de facturación (con datos),
                            # el chequeo fallaba en el principal y nunca llegaba al sync.
                            if draft_validate and so.partner_invoice_id and inv.partner_id != so.partner_invoice_id and inv.state in draft_statuses:
                                _logger.info("Pre-fiscal sync partner factura %s: %s (id:%s) -> %s (id:%s)",
                                             inv.name,
                                             inv.partner_id.name, inv.partner_id.id,
                                             so.partner_invoice_id.name, so.partner_invoice_id.id)
                                inv.partner_id = so.partner_invoice_id

                            # Verificar datos fiscales requeridos antes de validar (para factura electrónica)
                            if draft_validate:
                                partner = inv.partner_id
                                _logger.info("Fiscal check: inv.partner_id=%s (id:%s) so.partner_invoice_id=%s (id:%s)",
                                             partner.name, partner.id,
                                             so.partner_invoice_id.name if so.partner_invoice_id else 'None',
                                             so.partner_invoice_id.id if so.partner_invoice_id else 'None')
                                has_fiscal_data = True
                                # Para Argentina y LATAM, verificar tipo y número de documento
                                if 'l10n_latam_identification_type_id' in partner._fields:
                                    has_fiscal_data = bool(
                                        partner.l10n_latam_identification_type_id
                                        and partner.vat
                                    )
                                # Fallback: si el partner principal no tiene datos, buscar
                                # hijo de facturación (billing child) con datos fiscales.
                                # Caso: pack sub-order donde partner_invoice_id quedó como
                                # el parent sin datos por no haberse escrito meli_order_fields.
                                if not has_fiscal_data and 'l10n_latam_identification_type_id' in partner._fields:
                                    _commercial = partner.commercial_partner_id or partner
                                    _billing_child = self.env['res.partner'].search([
                                        ('parent_id', '=', _commercial.id),
                                        ('l10n_latam_identification_type_id', '!=', False),
                                        ('vat', '!=', False),
                                    ], limit=1)
                                    if _billing_child:
                                        _logger.info("Fiscal fallback: usando billing child id:%s (%s) para factura %s",
                                                     _billing_child.id, _billing_child.name, inv.name)
                                        if inv.state in draft_statuses:
                                            inv.partner_id = _billing_child
                                            so.partner_invoice_id = _billing_child
                                        partner = _billing_child
                                        has_fiscal_data = True
                                if not has_fiscal_data:
                                    _logger.warning("Factura %s no validada: cliente %s (id:%s) sin datos fiscales (tipo/numero documento)", inv.name, partner.name, partner.id)
                                    _fiscal_msg = "Factura creada en borrador - cliente sin datos fiscales completos (tipo y número de documento requeridos)"
                                    if not self.env['mail.message'].search([
                                        ('res_id', '=', so.id), ('model', '=', 'sale.order'),
                                        ('body', 'ilike', 'sin datos fiscales'),
                                    ], limit=1):
                                        so.message_post(body=_fiscal_msg, message_type=product_message_type)
                                    if not self.env['mail.message'].search([
                                        ('res_id', '=', inv.id), ('model', '=', 'account.move'),
                                        ('body', 'ilike', 'sin datos fiscales'),
                                    ], limit=1):
                                        meli_message_post(inv, _fiscal_msg, config=config)
                                    draft_validate = False

                            if draft_validate:
                                # Sincronizar partner de factura con partner_invoice_id del pedido
                                # (puede quedar desfasado si la factura se creó en un ciclo anterior)
                                if so.partner_invoice_id and inv.partner_id != so.partner_invoice_id and inv.state in draft_statuses:
                                    _logger.info("Actualizando partner de factura %s: %s (id:%s) -> %s (id:%s)",
                                                 inv.name,
                                                 inv.partner_id.name, inv.partner_id.id,
                                                 so.partner_invoice_id.name, so.partner_invoice_id.id)
                                    inv.partner_id = so.partner_invoice_id

                                # Invalidar cache ORM para leer datos frescos del partner
                                inv.partner_id.invalidate_recordset()
                                partner = inv.partner_id

                                # BUG-014: aplicar la posición fiscal del receptor (billing child) a la
                                # factura y RE-MAPEAR los impuestos de las líneas draft. Sin esto, las
                                # líneas conservan el IVA 21% heredado de la SO (armada contra el contacto
                                # principal, sin posición) → Factura B con IVA discriminado a un Exento.
                                # NO borra IVA a ciegas: aplica EXACTAMENTE el mapeo que define la posición
                                # fiscal del receptor (si mapea IVA21→exento, exime; si no hay mapeo, queda
                                # igual). Criterio AR: RI→Exento SÍ lleva IVA en la operación; lo que se
                                # corrige es que la posición fiscal del receptor mapee bien, no borrar IVA.
                                # Gateado a AR + posición presente + draft.
                                try:
                                    _co_ar = bool(inv.company_id and inv.company_id.country_id
                                                  and inv.company_id.country_id.code == 'AR')
                                    _fp = (partner.property_account_position_id
                                           if 'property_account_position_id' in partner._fields else False)
                                    if (_co_ar and _fp and inv.state in draft_statuses
                                            and 'fiscal_position_id' in inv._fields
                                            and inv.fiscal_position_id != _fp):
                                        inv.fiscal_position_id = _fp
                                        for _l in inv.invoice_line_ids:
                                            _mapped = map_tax_compat(_fp, _l.tax_ids, _l.product_id, partner)
                                            if _mapped is not None and set(_mapped.ids) != set(_l.tax_ids.ids):
                                                _l.tax_ids = [(6, 0, _mapped.ids)]
                                        _logger.info("BUG-014: posición fiscal '%s' aplicada + impuestos re-mapeados en factura %s (partner %s)",
                                                     _fp.name, inv.name, partner.name)
                                except Exception as _fp_err:
                                    _logger.warning("BUG-014: no se pudo aplicar posición fiscal/re-map en %s: %s", inv.name, _fp_err)

                                has_fiscal_data = True
                                # Para Argentina y LATAM (standard Odoo), verificar tipo y número de documento
                                if 'l10n_latam_identification_type_id' in partner._fields:
                                    has_fiscal_data = bool(
                                        partner.l10n_latam_identification_type_id
                                        and partner.vat
                                    )
                                # Para CER/BlueOrange, verificar partner_document_type_id
                                # Usar 'if not' en vez de 'elif' para cubrir bases con ambos campos
                                if not has_fiscal_data and 'partner_document_type_id' in partner._fields:
                                    has_fiscal_data = bool(
                                        partner.partner_document_type_id
                                        and partner.vat
                                    )
                                if not has_fiscal_data:
                                    _logger.warning("Factura %s no validada: cliente %s (id:%s) sin datos fiscales (tipo/numero documento). Fields: l10n_latam=%s partner_doc_type=%s vat=%s",
                                                    inv.name, partner.name, partner.id,
                                                    partner.l10n_latam_identification_type_id.id if 'l10n_latam_identification_type_id' in partner._fields and partner.l10n_latam_identification_type_id else 'N/A',
                                                    partner.partner_document_type_id.id if 'partner_document_type_id' in partner._fields and partner.partner_document_type_id else 'N/A',
                                                    partner.vat or 'N/A')
                                    _fiscal_msg = "Factura creada en borrador - cliente sin datos fiscales completos (tipo y número de documento requeridos)"
                                    if not self.env['mail.message'].search([
                                        ('res_id', '=', so.id), ('model', '=', 'sale.order'),
                                        ('body', 'ilike', 'sin datos fiscales'),
                                    ], limit=1):
                                        meli_message_post(so, _fiscal_msg, config=config)
                                    if not self.env['mail.message'].search([
                                        ('res_id', '=', inv.id), ('model', '=', 'account.move'),
                                        ('body', 'ilike', 'sin datos fiscales'),
                                    ], limit=1):
                                        meli_message_post(inv, _fiscal_msg, config=config)
                                    draft_validate = False

                            if draft_validate:
                                # Capturar datos fiscales ANTES del commit: el cache ORM aún
                                # tiene los valores correctos de la escritura al billing child.
                                # Después de cr.commit()+invalidate_all(), commercial_fields puede
                                # causar que se pierdan (ambos child y parent quedan NULL).
                                _partner = inv.partner_id
                                _pre_vat = _partner.vat
                                _pre_doc_field = None
                                _pre_doc_id = None
                                if 'partner_document_type_id' in _partner._fields and _partner.partner_document_type_id:
                                    _pre_doc_field = 'partner_document_type_id'
                                    _pre_doc_id = _partner.partner_document_type_id.id
                                elif 'l10n_latam_identification_type_id' in _partner._fields and _partner.l10n_latam_identification_type_id:
                                    _pre_doc_field = 'l10n_latam_identification_type_id'
                                    _pre_doc_id = _partner.l10n_latam_identification_type_id.id

                                # Blue Orange / CER: capture property_account_position_id (fiscal position)
                                _pre_fiscal_pos_id = None
                                if 'property_account_position_id' in _partner._fields and _partner.property_account_position_id:
                                    _pre_fiscal_pos_id = _partner.property_account_position_id.id

                                # Capture l10n_ar_afip_responsibility_type_id — flush_all() may flush
                                # ORM writes that override billing child values with parent's (NULL).
                                # Without this, CondicionIVAReceptorId reaches AFIP as NULL → error 10243.
                                _pre_afip_resp_id = None
                                if 'l10n_ar_afip_responsibility_type_id' in _partner._fields and _partner.l10n_ar_afip_responsibility_type_id:
                                    _pre_afip_resp_id = _partner.l10n_ar_afip_responsibility_type_id.id

                                _logger.info("Validate invoice: "+str(inv.name)+" (pre-commit: vat=%s doc=%s fiscal_pos=%s afip_resp=%s)",
                                             _pre_vat, _pre_doc_id, _pre_fiscal_pos_id, _pre_afip_resp_id)
                                MeliCommit( self )
                                self.env.invalidate_all()

                                # Safety net: verificar datos fiscales del billing child en DB
                                # post-commit. Si se perdieron (por commercial_fields sync),
                                # restaurar desde valores capturados pre-commit.
                                # Solo se escribe al CHILD — cada billing child tiene datos
                                # fiscales propios (multi-entidad por buyer).
                                _has_data_to_restore = _pre_doc_field and (_pre_vat or _pre_doc_id)
                                _has_fiscal_to_restore = _pre_fiscal_pos_id
                                if _has_data_to_restore or _has_fiscal_to_restore or _pre_afip_resp_id:
                                    # Build SELECT query dynamically based on available fields.
                                    # OJO: property_account_position_id es company_dependent (vive en
                                    # ir.property, NO es columna de res_partner) → leerlo por SQL crudo
                                    # rompe con "no existe la columna property_account_position_id" y
                                    # aborta confirm_ml. Se lee/escribe por ORM (abajo), no por SQL.
                                    _select_cols = ["vat"]
                                    if _pre_doc_field:
                                        _select_cols.append(_pre_doc_field)
                                    _has_afip_col = 'l10n_ar_afip_responsibility_type_id' in self.env['res.partner']._fields
                                    if _has_afip_col:
                                        _select_cols.append("l10n_ar_afip_responsibility_type_id")
                                    self.env.cr.execute(
                                        "SELECT %s FROM res_partner WHERE id = %%s" % ", ".join(_select_cols),
                                        (_partner.id,)
                                    )
                                    _row = self.env.cr.fetchone()
                                    _db_vat = _row[0] if _row else None
                                    _col_idx = 1
                                    _db_doc = None
                                    if _pre_doc_field:
                                        _db_doc = _row[_col_idx] if _row else None
                                        _col_idx += 1
                                    _db_afip_resp = _row[_col_idx] if (_row and _has_afip_col) else None
                                    # fiscal_pos por ORM (company_dependent). invalidate_all ya corrió
                                    # arriba, así que el ORM lee el valor fresco de ir.property.
                                    _db_fiscal_pos = _partner.property_account_position_id.id or None

                                    _needs_update = (
                                        (not _db_vat and _pre_vat)
                                        or (not _db_doc and _pre_doc_id)
                                        or (not _db_fiscal_pos and _pre_fiscal_pos_id)
                                        or (not _db_afip_resp and _pre_afip_resp_id)
                                    )
                                    if _needs_update:
                                        _upd_fields = []
                                        _upd_vals = []
                                        if not _db_vat and _pre_vat:
                                            _upd_fields.append("vat = %s")
                                            _upd_vals.append(_pre_vat)
                                        if not _db_doc and _pre_doc_id:
                                            _upd_fields.append(_pre_doc_field + " = %s")
                                            _upd_vals.append(_pre_doc_id)
                                        if not _db_afip_resp and _pre_afip_resp_id:
                                            _upd_fields.append("l10n_ar_afip_responsibility_type_id = %s")
                                            _upd_vals.append(_pre_afip_resp_id)
                                        # fiscal_pos (property_account_position_id) es company_dependent:
                                        # se restaura por ORM, NO por SQL crudo (no tiene columna real).
                                        if not _db_fiscal_pos and _pre_fiscal_pos_id:
                                            _partner.property_account_position_id = _pre_fiscal_pos_id
                                            self.env.invalidate_all()
                                            _logger.info("PRE-ACTION_POST: fiscal_pos restaurado por ORM (child id:%s -> %s)",
                                                         _partner.id, _pre_fiscal_pos_id)
                                        if _upd_fields:
                                            self.env.cr.execute(
                                                "UPDATE res_partner SET " + ", ".join(_upd_fields) + " WHERE id = %s",
                                                tuple(_upd_vals + [_partner.id])
                                            )
                                            self.env.invalidate_all()
                                            _logger.info("COMMERCIAL_FIELDS_FIX PRE-ACTION_POST: restaurado datos fiscales "
                                                         "billing child id:%s (vat:%s %s:%s fiscal_pos:%s afip_resp:%s)",
                                                         _partner.id, _pre_vat, _pre_doc_field, _pre_doc_id,
                                                         _pre_fiscal_pos_id, _pre_afip_resp_id)
                                        else:
                                            _logger.warning("PRE-ACTION_POST: datos fiscales NULL en DB y sin valores pre-commit "
                                                            "(child id:%s db_vat=%s db_doc=%s db_fiscal=%s db_afip_resp=%s "
                                                            "pre_vat=%s pre_doc=%s pre_fiscal=%s pre_afip_resp=%s)",
                                                            _partner.id, _db_vat, _db_doc, _db_fiscal_pos, _db_afip_resp,
                                                            _pre_vat, _pre_doc_id, _pre_fiscal_pos_id, _pre_afip_resp_id)
                                    else:
                                        _logger.info("PRE-ACTION_POST partner id:%s SQL OK: vat=%s %s=%s fiscal_pos=%s afip_resp=%s",
                                                     _partner.id, _db_vat, _pre_doc_field, _db_doc,
                                                     _db_fiscal_pos, _db_afip_resp)

                                # Guard: verify that account_move.partner_id in DB still points to
                                # the billing child we captured pre-flush. Odoo's account.move.write()
                                # can silently replace partner_id with commercial_partner_id during
                                # flush, which makes AFIP read NULL afip_responsibility_type and
                                # triggers error 10243 even though the billing child's fiscal fields
                                # were correctly restored by the SQL safety net above.
                                if _partner:
                                    _inv_partner_now = inv.partner_id  # reads from DB (after invalidate_all)
                                    if _inv_partner_now.id != _partner.id:
                                        _logger.warning(
                                            "PRE-ACTION_POST: account_move.partner_id=%s (id:%s) difiere del "
                                            "billing child capturado pre-flush id:%s — restaurando en account_move",
                                            _inv_partner_now.name, _inv_partner_now.id, _partner.id
                                        )
                                        self.env.cr.execute(
                                            "UPDATE account_move SET partner_id = %s WHERE id = %s",
                                            (_partner.id, inv.id)
                                        )
                                        self.env.invalidate_all()
                                        _logger.info(
                                            "PRE-ACTION_POST: partner_id restaurado a billing child id:%s "
                                            "en account_move id:%s",
                                            _partner.id, inv.id
                                        )
                                    else:
                                        _logger.info(
                                            "PRE-ACTION_POST: account_move.partner_id=id:%s OK (billing child correcto)",
                                            _inv_partner_now.id
                                        )

                                # Ensure draft invoice has a correct document type before posting.
                                # Fires when doc type is missing OR incompatible with AFIP type:
                                # - Factura B (code=6) + IVA Responsable Inscripto (code=1) → wrong
                                # - Factura A (code=1) + Consumidor Final/Monotributo → wrong
                                _pre_cur_doc = inv.l10n_latam_document_type_id if 'l10n_latam_document_type_id' in inv._fields else None
                                _pre_afip_r = inv.partner_id.l10n_ar_afip_responsibility_type_id if hasattr(inv.partner_id, 'l10n_ar_afip_responsibility_type_id') else None
                                _pre_afip_code = str(_pre_afip_r.code) if _pre_afip_r and _pre_afip_r.code else None
                                _pre_doc_needs_fix = not _pre_cur_doc or (
                                    _pre_cur_doc and _pre_afip_code and (
                                        (_pre_cur_doc.code == '6' and _pre_afip_code == '1')
                                        or (_pre_cur_doc.code == '1' and _pre_afip_code not in ('1',))  # Factura A + non-RI
                                    )
                                )
                                if ('l10n_latam_document_type_id' in inv._fields
                                        and _pre_doc_needs_fix
                                        and inv.state in draft_statuses):
                                    try:
                                        _logger.info("Pre-action_post: doc_type=%s afip=%s en factura %s — re-asignando",
                                                     _pre_cur_doc.code if _pre_cur_doc else 'vacío',
                                                     _pre_afip_code, inv.id)
                                        # Clear wrong type so onchange can re-compute freely
                                        if _pre_cur_doc and _pre_doc_needs_fix:
                                            inv.l10n_latam_document_type_id = False
                                        inv.partner_id = inv.partner_id
                                        if not inv.l10n_latam_document_type_id:
                                            inv._onchange_partner_id() if hasattr(inv, '_onchange_partner_id') else None
                                        # Manual fallback using string comparison (code is Char in Odoo)
                                        if not inv.l10n_latam_document_type_id and 'l10n_ar_afip_responsibility_type_id' in inv.partner_id._fields:
                                            _afip_resp = inv.partner_id.l10n_ar_afip_responsibility_type_id
                                            _afip_code_s = str(_afip_resp.code) if _afip_resp and _afip_resp.code else None
                                            _doc_code = None
                                            if _afip_code_s == '1':
                                                _doc_code = '1'  # Factura A — IVA Responsable Inscripto only
                                            else:
                                                _doc_code = '6'  # Factura B — CF, MT, Exento, or unknown
                                            if _doc_code and 'l10n_latam.document.type' in self.env:
                                                _doc_type = self.env['l10n_latam.document.type'].search([
                                                    ('code', '=', _doc_code),
                                                ], limit=1)
                                                if _doc_type:
                                                    inv.l10n_latam_document_type_id = _doc_type
                                                    _logger.info("Pre-action_post: asignado document_type=%s (%s) para factura %s",
                                                                 _doc_type.code, _doc_type.name, inv.id)
                                    except Exception as _dt_err:
                                        _logger.warning("Pre-action_post: no se pudo asignar document_type: %s", _dt_err)

                                # Fix C: ensure invoice_date is not in the past for AFIP journals.
                                # ARCA rejects Code 10016 when the invoice date is before the last
                                # authorized invoice. Draft invoices for ML orders may carry the
                                # order's date_order (weeks in the past) instead of today.
                                _is_afip_journal = False
                                try:
                                    _is_afip_journal = (
                                        inv.state in draft_statuses
                                        and hasattr(inv.journal_id, 'l10n_ar_afip_pos_number')
                                        and inv.journal_id.l10n_ar_afip_pos_number
                                    )
                                    if _is_afip_journal:
                                        from odoo.fields import Date as _FDate
                                        _today = _FDate.today()
                                        if not inv.invoice_date or inv.invoice_date < _today:
                                            _logger.info(
                                                "Pre-action_post: invoice_date %s < today %s en factura %s → actualizando a hoy",
                                                inv.invoice_date, _today, inv.id,
                                            )
                                            inv.invoice_date = _today

                                        # Fix C2: keep invoice_date_due in sync with invoice_date.
                                        # AFIP rejects with Code 10036 ("El campo FchVtoPago no puede
                                        # ser anterior a la fecha del comprobante") when the concept
                                        # is services/mixed (l10n_ar_afip_concept != '1') and
                                        # invoice_date_due (sent as FchVtoPago) is before invoice_date
                                        # (sent as CbteFch). invoice_date_due is computed once at
                                        # invoice creation from the payment term (usually "Pago
                                        # inmediato" == invoice_date at that moment) and is never
                                        # revisited when Fix C bumps invoice_date forward on a later
                                        # retry — leaving invoice_date_due stuck one or more days
                                        # behind forever (confirmed in prod: ~600 draft invoices
                                        # stuck this way, oldest since 2024-11). Bump it forward too,
                                        # never backward (a real future due date from the payment
                                        # term is left untouched).
                                        if inv.invoice_date and (
                                                not inv.invoice_date_due
                                                or inv.invoice_date_due < inv.invoice_date):
                                            _logger.info(
                                                "Pre-action_post Fix C2: invoice_date_due %s < invoice_date %s "
                                                "en factura %s → igualando a invoice_date",
                                                inv.invoice_date_due, inv.invoice_date, inv.id,
                                            )
                                            inv.invoice_date_due = inv.invoice_date
                                except Exception as _date_err:
                                    _logger.warning("Pre-action_post: no se pudo actualizar invoice_date: %s", _date_err)

                                # Fix D: reset stale sequence name on AFIP journal draft invoices.
                                # When action_post() fails due to an AFIP error, Odoo keeps the
                                # invoice in draft WITH the already-assigned sequence name (e.g.
                                # "FA-B 00002-00026389"). On the next retry the name is re-sent to
                                # AFIP, which is now thousands of numbers behind. Fix: if the draft
                                # invoice has a real sequence name but no AFIP authorization (no CAE),
                                # reset name to '/' so Odoo assigns the current correct next number.
                                try:
                                    if _is_afip_journal and inv.state in draft_statuses:
                                        _inv_name = inv.name or ''
                                        _has_real_name = (
                                            _inv_name
                                            and _inv_name != '/'
                                            and not _inv_name.startswith('*')
                                        )
                                        _afip_authorized = (
                                            getattr(inv, 'l10n_ar_afip_auth_mode', False)
                                            or getattr(inv, 'l10n_ar_afip_cae', False)
                                        )
                                        if _has_real_name and not _afip_authorized:
                                            _logger.info(
                                                "Pre-action_post: resetting stale name '%s' → '/' en factura %s "
                                                "(no fue autorizada por AFIP, secuencia puede estar desalineada)",
                                                _inv_name, inv.id,
                                            )
                                            inv.name = '/'
                                except Exception as _name_err:
                                    _logger.warning("Pre-action_post: no se pudo resetear nombre: %s", _name_err)

                                # Fix D2: SELF-HEALING — clean OTHER polluted drafts in same (journal, doc_type).
                                # Odoo's _get_last_sequence orders by sequence_number DESC across ALL named
                                # moves regardless of state. If OTHER drafts have stale names/sequence_numbers
                                # higher than the last truly posted invoice, Odoo computes a wrong "next"
                                # number for THIS invoice (e.g. 32782 when AFIP expects 32750). This pollution
                                # cascades: each cron iteration would send the wrong number to AFIP, get
                                # Code 10016, revert, repeat.
                                #
                                # Self-heal: before posting THIS invoice, scan and reset name='/' +
                                # sequence_number=0 on every other draft of the same (journal, doc_type)
                                # that has a stale name or sequence_number without CAE. Those drafts will
                                # get a fresh correct number when their own cron iteration picks them up.
                                try:
                                    if (_is_afip_journal and inv.state in draft_statuses
                                            and 'l10n_latam_document_type_id' in inv._fields):
                                        _doc_type = inv.l10n_latam_document_type_id
                                        if _doc_type:
                                            _polluting = self.env['account.move'].sudo().search([
                                                ('journal_id', '=', inv.journal_id.id),
                                                ('l10n_latam_document_type_id', '=', _doc_type.id),
                                                ('state', '=', 'draft'),
                                                ('id', '!=', inv.id),
                                                '|',
                                                '&', ('name', '!=', '/'), ('name', '!=', False),
                                                ('sequence_number', '>', 0),
                                            ])
                                            _cleaned = 0
                                            for _p in _polluting:
                                                _p_authorized = (
                                                    getattr(_p, 'l10n_ar_afip_auth_mode', False)
                                                    or getattr(_p, 'l10n_ar_afip_cae', False)
                                                )
                                                if _p_authorized:
                                                    continue
                                                _p_name = _p.name or ''
                                                if _p_name.startswith('*'):
                                                    continue
                                                _p_write_vals = {}
                                                if _p_name and _p_name != '/':
                                                    _p_write_vals['name'] = '/'
                                                if _p.sequence_number and _p.sequence_number > 0:
                                                    _p_write_vals['sequence_number'] = 0
                                                if not _p_write_vals:
                                                    continue
                                                try:
                                                    _p.sudo().write(_p_write_vals)
                                                    _cleaned += 1
                                                except Exception as _pe:
                                                    _logger.warning(
                                                        "Pre-action_post Fix D2: no se pudo limpiar draft %d: %s",
                                                        _p.id, _pe,
                                                    )
                                            if _cleaned:
                                                _logger.info(
                                                    "Pre-action_post Fix D2: %d borrador(es) polucionado(s) "
                                                    "limpiado(s) en (journal=%s, doc_type=%s) — self-healing "
                                                    "de _get_last_sequence antes de postear factura %d",
                                                    _cleaned, inv.journal_id.id, _doc_type.id, inv.id,
                                                )
                                except Exception as _poll_err:
                                    _logger.warning(
                                        "Pre-action_post Fix D2: pollution scan failed: %s", _poll_err,
                                    )

                                try:
                                    # Pass the billing child partner ID in context so that
                                    # wsfe_get_cae_request can recover it even if Odoo's base
                                    # _post() resets self.partner_id to commercial_partner_id.
                                    _meli_billing_child_id = inv.partner_id.id if inv.partner_id else None
                                    _post_ctx = {'l10n_ar_invoice_skip_commit': True}
                                    if _meli_billing_child_id:
                                        _post_ctx['meli_billing_child_id'] = _meli_billing_child_id
                                    inv_to_post = inv.with_context(**_post_ctx)
                                    inv_to_post.action_post()
                                    meli_message_post(so, "Created invoices and validated!", config=config)
                                    _logger.info("Created invoices and validated!")

                                    # CRITICAL: cr.commit() AFTER a successful AFIP post.
                                    # If a later order in this cron run fails with
                                    # serialization_failure (e.g. concurrent update from
                                    # meli_notify webhook), Odoo's service.model.retrying()
                                    # would normally ROLLBACK TO SAVEPOINT and re-run the
                                    # whole cron — undoing all the prior successful posts
                                    # in Odoo. But AFIP already issued CAEs for them, so
                                    # the retry creates duplicates in AFIP.
                                    #
                                    # Committing here makes each successful post durable
                                    # immediately. If a later one fails, the failure is
                                    # caught by the outer except below, the invoice is
                                    # reverted to draft, and the cron continues with the
                                    # next order. Previously-posted invoices stay safe.
                                    #
                                    # Trade-off: commit destroys outer savepoints, so
                                    # retrying() can't auto-retry serialization failures
                                    # for the orders cron — they'll surface as errors and
                                    # the next cron iteration handles them. For long-running
                                    # crons with AFIP communications this is the right
                                    # trade-off (preserving committed AFIP state > magic retry).
                                    try:
                                        self.env.cr.commit()
                                    except Exception as _commit_err:
                                        _logger.warning(
                                            "Post-success cr.commit() failed for invoice %s: %s",
                                            inv.name, _commit_err,
                                        )
                                except Exception as E:
                                    _error_str = str(E)
                                    _tb_str = traceback.format_exc()
                                    # Clear ORM cache after failed action_post: base _post() may have
                                    # written commercial_partner_id into the ORM cache (and possibly DB),
                                    # corrupting partner_id for subsequent retry cycles. Invalidating
                                    # forces ORM to re-read from DB on the next cycle.
                                    try:
                                        self.env.invalidate_all()
                                    except Exception:
                                        pass
                                    # Re-restore partner_id in DB: base _post() flushes ORM writes to DB
                                    # during action_post(), so even our pre-action_post SQL restore gets
                                    # overwritten. After the exception we must write it back again so the
                                    # next retry cycle reads the billing child (not the commercial partner).
                                    if _partner and _partner.id:
                                        try:
                                            _inv_pid_after = inv.partner_id.id  # reads from DB (after invalidate)
                                            if _inv_pid_after != _partner.id:
                                                self.env.cr.execute(
                                                    "UPDATE account_move SET partner_id = %s WHERE id = %s",
                                                    (_partner.id, inv.id)
                                                )
                                                self.env.invalidate_all()
                                                _logger.info(
                                                    "POST-FAIL restore: partner_id %s → billing child %s en factura %s",
                                                    _inv_pid_after, _partner.id, inv.id
                                                )
                                        except Exception as _pf_err:
                                            _logger.warning("POST-FAIL restore partner_id error: %s", _pf_err)

                                    # Initialize error-specific flags for use across both branches
                                    _afip_10243 = False
                                    _want_doc243 = None

                                    # ----- Fix B: AFIP transient errors (503 / timeout / connection) -----
                                    # When ARCA/AFIP is temporarily down, don't spam the chatter with a
                                    # full traceback — just post a clean user-friendly message and leave
                                    # the invoice in draft so it can be retried later.
                                    _afip_transient = any(kw in _error_str or kw in _tb_str for kw in [
                                        '503 Server Error', 'Service Unavailable',
                                        'ConnectionError', 'ConnectionRefusedError',
                                        'ReadTimeout', 'ConnectTimeout', 'Timeout',
                                        'WSDL', 'TransportError',
                                    ])
                                    if _afip_transient:
                                        _clean_msg = (
                                            "El webservice de facturación electrónica de ARCA no está disponible en este momento. "
                                            "La factura queda en borrador — intentar validarla de nuevo en unos minutos cuando el servicio se restablezca."
                                        )
                                        meli_message_post(so, _clean_msg, config=config)
                                        meli_message_post(inv, _clean_msg, config=config)
                                        _logger.warning("AFIP transient error for invoice %s (SO %s): %s",
                                                        inv.name, so.name, _error_str[:200])
                                    else:
                                        # ----- Fix A: AFIP 10016 auto-diagnosis -----
                                        # Error 10016 = "El numero o fecha del comprobante no se corresponde
                                        # con el proximo a autorizar". Auto-diagnose by calling
                                        # FECompUltimoAutorizado to show the exact gap.
                                        try:
                                            from markupsafe import Markup as _Markup
                                        except ImportError:
                                            _Markup = str

                                        _afip_10016 = '10016' in _error_str
                                        _diag_msg = ""
                                        if _afip_10016:
                                            _diag_msg = self._diagnose_afip_10016(inv, error_text=_error_str + _tb_str)

                                        # ----- Fix F: AFIP 10243 auto-correct -----
                                        # Error 10243 = "Condicion IVA receptor no es valido para la clase
                                        # de comprobante". Fires when CondicionIVAReceptorId is incompatible
                                        # with CbteTipo (e.g. Factura B sent for IVA RI, or Factura A for MT/Exento).
                                        # After reverting to draft below, correct doc_type so next retry works.
                                        _afip_10243 = '10243' in _error_str
                                        if _afip_10243:
                                            try:
                                                _p243 = inv.partner_id
                                                _afip_r243 = getattr(_p243, 'l10n_ar_afip_responsibility_type_id', False)
                                                _afip_c243 = str(_afip_r243.code) if _afip_r243 and _afip_r243.code else None
                                                _cur_doc243 = inv.l10n_latam_document_type_id if 'l10n_latam_document_type_id' in inv._fields else None
                                                _want_doc243 = None
                                                if _afip_c243 == '1':
                                                    _want_doc243 = '1'  # Factura A
                                                else:
                                                    _want_doc243 = '6'  # Factura B (CF/MT/Exento/unknown)
                                                _diag_msg = (
                                                    "⚠️ <b>AFIP Error 10243</b>: La condición IVA del receptor "
                                                    "(%s, código=%s) no es compatible con el tipo de comprobante "
                                                    "%s. Se corregirá automáticamente al tipo %s en el próximo reintento."
                                                ) % (
                                                    _afip_r243.name if _afip_r243 else 'desconocido',
                                                    _afip_c243 or 'N/A',
                                                    _cur_doc243.name if _cur_doc243 else 'sin tipo',
                                                    'Factura A' if _want_doc243 == '1' else 'Factura B',
                                                )
                                                _logger.warning(
                                                    "AFIP 10243 en factura %s: partner=%s afip_code=%s doc=%s → corregir a %s",
                                                    inv.id, _p243.name, _afip_c243,
                                                    _cur_doc243.code if _cur_doc243 else None,
                                                    _want_doc243,
                                                )
                                            except Exception as _e243:
                                                _logger.warning("AFIP 10243 diagnóstico fallido: %s", _e243)

                                        traceback_str = "<pre>%s</pre>" % _tb_str
                                        error_msg = str("ERROR VALIDANDO FACTURA > Revisar:") + traceback_str
                                        if _diag_msg:
                                            error_msg = _Markup(_diag_msg) + _Markup("<br/><br/>") + _Markup(error_msg)
                                        else:
                                            error_msg = _Markup(error_msg)
                                        meli_message_post(so, error_msg, config=config)
                                        meli_message_post(inv, error_msg, config=config)
                                        _logger.error("Error validando factura %s: %s", inv.name, _error_str)

                                    # In all cases: try to revert to draft
                                    try:
                                        if inv.state not in ['draft', 'cancel']:
                                            inv.button_draft()
                                            _logger.info("Factura %s revertida a borrador tras error", inv.name)
                                            meli_message_post(inv, "Factura revertida a borrador automaticamente tras error de validacion", config=config)
                                    except Exception as E2:
                                        _logger.error("No se pudo revertir factura %s a borrador: %s", inv.name, str(E2))

                                    # Fix E: after reverting to draft, reset the sequence name so
                                    # the next posting attempt gets the then-current next number.
                                    # Without this, retries keep sending the stale number to AFIP.
                                    try:
                                        _afip_authorized_now = (
                                            getattr(inv, 'l10n_ar_afip_auth_mode', False)
                                            or getattr(inv, 'l10n_ar_afip_cae', False)
                                        )
                                        _name_now = inv.name or ''
                                        if (
                                            _is_afip_journal
                                            and not _afip_authorized_now
                                            and _name_now
                                            and _name_now != '/'
                                            and not _name_now.startswith('*')
                                        ):
                                            inv.name = '/'
                                            _logger.info("Post-error: nombre '%s' reseteado a '/' en factura %s "
                                                         "para que el próximo reintento use la secuencia actual",
                                                         _name_now, inv.id)
                                    except Exception as _reset_err:
                                        _logger.warning("Post-error: no se pudo resetear nombre de factura %s: %s",
                                                        inv.id, _reset_err)

                                    # Fix F (post-draft): for error 10243, correct the document type
                                    # now that the invoice is back in draft, so the next retry uses
                                    # the right CbteTipo and CondicionIVAReceptorId.
                                    if _afip_10243 and _want_doc243 and inv.state in draft_statuses:
                                        try:
                                            _cur_doc_code_243 = None
                                            if 'l10n_latam_document_type_id' in inv._fields and inv.l10n_latam_document_type_id:
                                                _cur_doc_code_243 = inv.l10n_latam_document_type_id.code
                                            if _want_doc243 == _cur_doc_code_243:
                                                # Doc type is already correct — changing it won't fix 10243.
                                                # Likely cause: CondicionIVAReceptorId is NULL on partner.
                                                # The PRE-ACTION_POST SQL restore should fix it on next cycle.
                                                _logger.warning(
                                                    "Fix-10243: tipo de comprobante ya es %s (afip_code=%s) — "
                                                    "no se cambia para evitar loop infinito. Verificar "
                                                    "l10n_ar_afip_responsibility_type_id en partner %s.",
                                                    _cur_doc_code_243, _want_doc243, inv.partner_id.name)
                                            elif 'l10n_latam_document_type_id' in inv._fields:
                                                inv.l10n_latam_document_type_id = False
                                                _doc_type_243 = self.env['l10n_latam.document.type'].search(
                                                    [('code', '=', _want_doc243)], limit=1)
                                                if _doc_type_243:
                                                    inv.l10n_latam_document_type_id = _doc_type_243
                                                    _logger.info(
                                                        "Fix-10243: asignado document_type=%s (%s) a factura %s para próximo reintento",
                                                        _doc_type_243.code, _doc_type_243.name, inv.id)
                                        except Exception as _f243_err:
                                            _logger.warning("Fix-10243 post-draft fallido para factura %s: %s", inv.id, _f243_err)
                                    pass;
                                

                        if inv.state in ['posted'] and draft_validate:
                            so.meli_sign_invoice( invoice=inv )

                        if inv.state in posted_statuses and config and config.mercadolibre_post_invoice:
                            _logger.info("Send to MercadoLibre: "+str(inv.name))
                            mo = so and so.meli_orders and so.meli_orders[0]
                            if mo:
                                mo.invoice_created = True
                                try:
                                    mo.orders_post_invoice( meli=meli, config=config )
                                except Exception as e:
                                    _logger.info("Post To ML Invoice Exception")
                                    _logger.error(e, exc_info=True)
                                    pass;

                # -------------------------------------------------------
                # Issue 5: forzar recomputo de invoice_status / billing_status
                # Después del commit + invalidate_all(), los campos compute
                # de sale.order relacionados con facturas pueden quedar en
                # cache obsoleto. Forzamos la recomputación explícita para
                # que el pedido muestre "Totalmente Facturado" correctamente.
                # -------------------------------------------------------
                try:
                    so._get_invoiced()
                    _logger.info("INVOICE_STATUS: recomputo _get_invoiced() para SO %s -> invoice_status=%s",
                                 so.name,
                                 getattr(so, 'invoice_status', 'N/A'))
                except Exception as _inv_st_err:
                    _logger.warning("INVOICE_STATUS: error al recomputar _get_invoiced para SO %s: %s",
                                    so.name, str(_inv_st_err))

            else:
                _logger.error("meli_create_invoice > conditions not met. "
                              "so.state=%s special_condition=%s received_amount=%s so.amount_total=%s",
                              so.state,
                              self._meli_invoice_conditions(meli=meli, config=config),
                              getattr(so, 'meli_amount_to_invoice', lambda **kw: '?')(meli=meli, config=config)
                              if hasattr(so, 'meli_amount_to_invoice') else '?',
                              so.amount_total)
        #_logger.info("meli_oerp_accounting meli_create_invoice ended.")

    def meli_sign_invoice( self, invoice ):
        for so in self:
            if (not invoice):
                continue

            #MEXICO CFDI 17.0
            if ("l10n_mx_edi_cfdi_state" in invoice._fields):

                if invoice.l10n_mx_edi_cfdi_state == 'sent':
                    continue;

                _logger.info("Signin CFDI posted invoice")
                # invoice._l10n_mx_edi_cfdi_invoice_try_send()
                meli_message_post(so, "Meli mandando a firmar CFDI. Estado CFDI: "+str(invoice.l10n_mx_edi_cfdi_state), config=config)
                if 'account.move.send' in self.env:
                    with self.env.cr.savepoint():
                        self.env['account.move.send']\
                          .sudo().with_user(so.user_id and so.user_id.id)\
                          .with_context(active_model=invoice._name, active_ids=invoice.ids)\
                          .create({})\
                          .action_send_and_print()
                else:
                    _logger.warning("Modelo account.move.send no disponible, no se puede firmar la factura %s", invoice.name)

                # Check for error.
                errors = []
                for document in invoice.l10n_mx_edi_invoice_document_ids:
                    if document.state == 'invoice_sent_failed':
                        errors.append(document.message)
                        break
                if errors:
                    invoice_data['error'] = {
                        'error_title': _("Error when sending the CFDI to the PAC:"),
                        'errors': errors,
                    }
                    meli_message_post(so, "Factura firmada con ERRORES: "+str(invoice_data), config=config)

                # Check for success.
                if invoice.l10n_mx_edi_cfdi_state == 'sent':
                    meli_message_post(so, "Factura firmada con CFDI Ok! Meli", config=config)
                    continue;


    def _get_meli_target_total(self):
        """Obtiene el monto objetivo para la SO: transaction_amount menos descuento del vendedor.
        Solo resta la porción del descuento que absorbe el vendedor (amounts.seller del endpoint
        /orders/{id}/discounts). Si el descuento es 100% ML-funded (seller=0), devuelve
        transaction_amount íntegro."""
        so = self
        meli_total = 0
        for meli_order in so.meli_orders:
            for payment in meli_order.payments:
                if payment.status == 'approved':
                    ta = float(payment.transaction_amount or 0)
                    if ta > meli_total:
                        meli_total = ta
        seller_discount = float(so.meli_discount_seller_amount or 0)
        return meli_total - seller_discount

    def _apply_meli_taxes_to_order_lines(self, config=None):
        """
        Aplica impuestos de retenciones MeLi confirmadas a las lineas de la orden.
        Solo aplica reglas con state='confirmed' y account_tax_id asignado.
        No duplica impuestos que ya estén en la linea.
        No ajusta price_unit: las retenciones son deducciones del vendedor que reducen
        el total de la SO (reflejando el neto que recibe el vendedor).
        """
        so = self
        if not so.meli_orders:
            _logger.info("MELI _apply_meli_taxes: no meli_orders for SO %s", so.name)
            return

        taxes_to_apply = self.env['account.tax']
        for meli_order in so.meli_orders:
            for payment in meli_order.payments:
                _logger.info(
                    "MELI _apply_meli_taxes: payment %s has %d charges",
                    payment.payment_id, len(payment.charge_ids),
                )
                for charge in payment.charge_ids:
                    rule = charge.meli_tax_id
                    if not rule or rule.state != 'confirmed' or not rule.account_tax_id:
                        rule = self.env['mercadolibre.tax'].match_charge(
                            charge.charge_type, charge.name,
                            {'mov_financial_entity': charge.mov_financial_entity or '',
                             'source_detail': charge.source_detail or ''},
                        )
                    if rule and rule.state == 'confirmed' and rule.account_tax_id:
                        taxes_to_apply |= rule.account_tax_id
                        _logger.info(
                            "MELI _apply_meli_taxes: charge '%s' -> tax '%s' (rule '%s' confirmed)",
                            charge.name, rule.account_tax_id.name, rule.name,
                        )
                    else:
                        _logger.info(
                            "MELI _apply_meli_taxes: charge '%s' -> no confirmed rule found",
                            charge.name,
                        )

        if not taxes_to_apply:
            _logger.info("MELI _apply_meli_taxes: no confirmed taxes to apply for SO %s", so.name)
            return

        # If l10n_account_withholding_tax is installed, taxes marked as
        # withholding-on-payment should NOT go on SO lines — they will be
        # applied when the account.payment is created instead.
        has_wth_field = 'is_withholding_tax_on_payment' in self.env['account.tax']._fields
        if has_wth_field:
            withholding_taxes = taxes_to_apply.filtered(lambda t: t.is_withholding_tax_on_payment)
            so_taxes = taxes_to_apply - withholding_taxes
            if withholding_taxes:
                _logger.info(
                    "MELI _apply_meli_taxes: withholding-on-payment taxes %s deferred to payment for SO %s",
                    withholding_taxes.mapped('name'), so.name,
                )
            # Remove withholding-on-payment taxes from SO lines if they were
            # added by a previous version of the code.
            for line in so.order_line:
                _tf = 'tax_ids' if 'tax_ids' in line._fields else 'tax_id'
                wth_on_line = getattr(line, _tf).filtered(lambda t: t.is_withholding_tax_on_payment)
                if wth_on_line:
                    line.sudo().write({_tf: [(3, t.id) for t in wth_on_line]})
                    _logger.info(
                        "MELI: Removed withholding-on-payment taxes %s from SO line %s",
                        wth_on_line.mapped('name'), line.id,
                    )
        else:
            so_taxes = taxes_to_apply

        _logger.info(
            "MELI _apply_meli_taxes: will apply taxes %s to SO %s (%d lines)",
            so_taxes.mapped('name'), so.name, len(so.order_line),
        )

        if not so_taxes:
            return

        lines_updated = 0
        for line in so.order_line:
            if line.price_unit <= 0:
                continue

            tax_field = 'tax_ids' if 'tax_ids' in line._fields else 'tax_id'
            existing_taxes = getattr(line, tax_field)
            existing_tax_ids = set(existing_taxes.ids)
            new_taxes = so_taxes.filtered(lambda t: t.id not in existing_tax_ids)

            if new_taxes:
                line.sudo().write({tax_field: [(4, t.id) for t in new_taxes]})
                lines_updated += 1
                _logger.info(
                    "MELI: Applied taxes %s to SO line %s (product: %s)",
                    new_taxes.mapped('name'), line.id,
                    line.product_id.display_name,
                )

        if lines_updated:
            meli_message_post(
                so,
                "Retenciones MeLi aplicadas: %s en %d linea(s)." % (
                    ', '.join(taxes_to_apply.mapped('name')), lines_updated
                ),
                config=config,
            )



    def _cleanup_duplicate_customer_payments(self, meli_order, config=None):
        """Detecta y cancela account.payments de cliente duplicados en una meli.order.

        ML a veces genera dos payment_id distintos (ambos approved) para la misma orden,
        resultando en dos account.payment en Odoo. Este método conserva solo el pago
        con el mayor payment_id numérico (el más reciente de ML) y cancela los demás.
        Se llama desde confirm_ml después del loop de pagos.
        """
        if not meli_order:
            return
        approved_with_payment = meli_order.payments.filtered(
            lambda p: p.status == 'approved'
            and p.account_payment_id
            and p.account_payment_id.exists()
        )
        if len(approved_with_payment) <= 1:
            return

        try:
            sorted_pays = sorted(
                approved_with_payment,
                key=lambda p: int(p.payment_id or 0),
                reverse=True,  # más reciente primero
            )
        except (ValueError, TypeError):
            _logger.warning('_cleanup_duplicate_customer_payments: payment_id no numérico en orden %s', meli_order.name)
            return

        newest = sorted_pays[0]
        newest_amount = newest.account_payment_id.amount if newest.account_payment_id else 0

        for dup in sorted_pays[1:]:
            dup_ap = dup.account_payment_id

            # Pagos combinados: si los montos son diferentes, son métodos de pago
            # legítimos (ej: transferencia + dinero disponible) y NO deben cancelarse.
            if abs((dup_ap.amount or 0) - newest_amount) >= 1.0:
                _logger.info(
                    '_cleanup_duplicate_customer_payments: MONTOS DIFERENTES en orden ML %s — '
                    'conservando ambos pagos: ML %s ($%.2f) y ML %s ($%.2f) '
                    '(probable pago combinado).',
                    meli_order.name, dup.payment_id, dup_ap.amount,
                    newest.payment_id, newest_amount,
                )
                continue

            # ── Verificar si el pago duplicado ya está conciliado ────────────
            # Un pago conciliado tiene líneas de asiento emparejadas con una
            # factura. Cancelarlo automáticamente rompería la contabilidad.
            # En ese caso solo avisamos en el chatter para gestión manual.
            is_reconciled = False
            try:
                if dup_ap.move_id:
                    reconciled_lines = dup_ap.move_id.line_ids.filtered(
                        lambda l: l.account_id.reconcile and l.reconciled
                    )
                    is_reconciled = bool(reconciled_lines)
                # Fallback: campo disponible en Odoo 16+
                if not is_reconciled and hasattr(dup_ap, 'reconciled_invoice_ids'):
                    is_reconciled = bool(dup_ap.reconciled_invoice_ids)
            except Exception:
                pass  # si falla la verificación, proceder con cautela (is_reconciled=False)

            if is_reconciled:
                _logger.warning(
                    '_cleanup_duplicate_customer_payments: DUPLICADO CONCILIADO en orden ML %s — '
                    'NO se cancela automáticamente %s (pago ML %s, $%.2f). '
                    'Requiere gestión manual (desonciliar + nota de crédito o eliminar asiento).',
                    meli_order.name, dup_ap.name, dup.payment_id, dup_ap.amount,
                )
                self.message_post(
                    body=(
                        "⚠️ Pago duplicado de ML detectado — <b>requiere acción manual</b>:<br/>"
                        "• Duplicado: <b>%(dup_name)s</b> (OP %(dup_pid)s, $%(dup_amount).2f) "
                        "— ya está <b>conciliado</b> con una factura, no se puede cancelar automáticamente.<br/>"
                        "• Pago más reciente: <b>%(new_name)s</b> (OP %(new_pid)s)<br/>"
                        "<b>Pasos:</b> ir al pago %(dup_name)s → desonciliar → "
                        "cancelar o emitir nota de crédito según corresponda."
                    ) % {
                        'dup_name': dup_ap.name,
                        'dup_pid': dup.payment_id,
                        'dup_amount': dup_ap.amount,
                        'new_name': newest.account_payment_id.name,
                        'new_pid': newest.payment_id,
                    },
                    message_type='comment',
                )
                continue  # no cancelar — dejar para gestión manual

            # ── Pago duplicado SIN conciliar: cancelar automáticamente ───────
            _logger.warning(
                '_cleanup_duplicate_customer_payments: DUPLICADO en orden ML %s — '
                'cancelando account.payment %s (pago ML %s, importe %.2f, estado %s); '
                'conservando pago ML %s (%s)',
                meli_order.name,
                dup_ap.name, dup.payment_id, dup_ap.amount, dup_ap.state,
                newest.payment_id, newest.account_payment_id.name,
            )
            try:
                dup.cancel_payments(config=config)
                self.message_post(
                    body=(
                        "✅ Pago duplicado de ML cancelado automáticamente:<br/>"
                        "• Cancelado: <b>%s</b> (OP %s, $%.2f)<br/>"
                        "• Conservado: <b>%s</b> (OP %s)<br/>"
                        "Causa: MercadoLibre generó dos operaciones de pago para la misma orden."
                    ) % (
                        dup_ap.name, dup.payment_id, dup_ap.amount,
                        newest.account_payment_id.name, newest.payment_id,
                    ),
                    message_type='comment',
                )
            except Exception as e:
                _logger.error(
                    '_cleanup_duplicate_customer_payments: Error cancelando pago duplicado %s: %s',
                    dup_ap.name, e, exc_info=True
                )

    def confirm_ml( self, meli=None, config=None ):
        #_logger.info("meli_oerp_accounting confirm_ml: config:"+str(config and config.name))
        company = (config and 'company_id' in config._fields and config.company_id) or self.env.user.company_id
        config = config or company
        sorder = self
        so = sorder
        try:
            saleorderline_obj = self.env['sale.order.line']

            #cuenta analitica
            if (config and "mercadolibre_analytic_account_id" in config._fields and "analytic_account_id" in self.env["sale.order"]._fields):
                sorder.analytic_account_id = config.mercadolibre_analytic_account_id and config.mercadolibre_analytic_account_id.id

            #agregar ids
            if "mercadolibre_order_add_fea" in config._fields and config.mercadolibre_order_add_fea:

                if self.meli_orders and "per_item" in config.mercadolibre_order_add_fea:

                    for morder in sorder.meli_orders:
                        #_logger.info("meli_oerp_financial confirm_ml_financial morder:"+str(morder and morder.name))
                        order_item = morder.order_items and morder.order_items[0]
                        order_item_id = (order_item and order_item.order_item_id) or ""
                        order_item_variation_id = (order_item and order_item.order_item_variation_id) or ""

                        meli_order_item_id = str("FEA ")+str(order_item_id)
                        meli_order_item_variation_id = str("FEA ")+str(order_item_variation_id)
                        fea_amount = morder.fee_amount

                        product_fea = "mercadolibre_product_fea" in config._fields and config.mercadolibre_product_fea

                        if not product_fea:
                            product_fea = self.env["product.product"].search( ['|','|',('default_code','ilike','COMISION_ML'),('default_code','ilike','COMISIONML'),('default_code','ilike','COMISION ML')], limit=1 )

                        if not product_fea:
                            _logger.info("SIN COMISION ML - debe crear el servicio COMISION ML y asignarla al parámetro [Product Fea] dentro de la sección [PAYMENTS CONFIGURATION] en la configuración de ML")
                            continue;

                        com_name = ((product_fea and product_fea.display_name) or "COMISION ")
                        com_name+=  str(" ")+ str(meli_order_item_id)
                        if (order_item and order_item.product_id and order_item.product_id.default_code):
                            com_name+= str(" ") + str(order_item.product_id.default_code)

                        saleorderline_item_fields = {
                            'company_id': company.id,
                            'order_id': sorder.id,
                            'meli_order_item_id': meli_order_item_id,
                            'meli_order_item_variation_id': meli_order_item_variation_id,                            
                            'price_unit': float(0.0),
                            'product_id': (product_fea and product_fea.id),
                            'product_uom_qty': 1.0,
                            'name': com_name,
                        }
                        uom_field = SaleOrderLineUomField( self )
                        saleorderline_item_fields[uom_field] = (product_fea and product_fea.uom_id.id)
                        if "purchase_price" in saleorderline_obj._fields:
                            saleorderline_item_fields['purchase_price'] = sorder._ml_get_purchase_price_from_amount( 
                                product=product_fea,
                                amount=fea_amount,
                                amount_type="tax_included",  # or 'tax_excluded' depending on what fea_amount is
                                quantity=1.0 )
                        #saleorderline_item_fields.update( self._set_product_unit_price( product_related_obj=product_related_obj, Item=Item, config=config ) )

                        saleorderline_item_ids = saleorderline_obj.search( [('meli_order_item_id','=',meli_order_item_id),
                                                                            ('meli_order_item_variation_id','=',meli_order_item_variation_id),
                                                                            ('order_id','=',sorder.id)] )

                        if not saleorderline_item_ids:
                            saleorderline_item_ids = saleorderline_obj.sudo().create( ( saleorderline_item_fields ))
                            if saleorderline_item_ids:
                                # Explicitly write purchase_price after create because Odoo's
                                # _compute_purchase_price resets it to product.standard_price (0 for COMISION_ML)
                                write_vals = {'qty_to_invoice': 0}
                                if 'purchase_price' in saleorderline_item_fields:
                                    write_vals['purchase_price'] = saleorderline_item_fields['purchase_price']
                                saleorderline_item_ids.sudo().write(write_vals)
                                _logger.info("FEA line CREATED id:%s purchase_price:%s fea_amount:%s order:%s",
                                             saleorderline_item_ids.id, saleorderline_item_fields.get('purchase_price'), fea_amount, sorder.name)
                        else:
                            is_locked = (sorder and sorder.state in ["done"]) or ("locked" in sorder._fields and sorder.locked)
                            if not is_locked:
                                # Only write fields that actually changed (avoid unnecessary ORM triggers)
                                update_fields = {}
                                for field, value in saleorderline_item_fields.items():
                                    if field in saleorderline_item_ids._fields:
                                        current_val = getattr(saleorderline_item_ids, field, None)
                                        # Handle Many2one comparison
                                        if hasattr(current_val, 'id'):
                                            current_val = current_val.id
                                        if current_val != value:
                                            update_fields[field] = value
                                if update_fields:
                                    saleorderline_item_ids.sudo().write(update_fields)
                            # Always update purchase_price even on locked orders (cost field, not customer-facing)
                            # But only if value actually changed
                            if 'purchase_price' in saleorderline_item_fields and fea_amount:
                                new_pp = saleorderline_item_fields['purchase_price']
                                if saleorderline_item_ids.purchase_price != new_pp:
                                    saleorderline_item_ids.sudo().write({'purchase_price': new_pp})
                                    _logger.info("FEA line UPDATED purchase_price:%s fea_amount:%s locked:%s order:%s",
                                                 new_pp, fea_amount, is_locked, sorder.name)

                        # Only write qty_to_invoice if it actually needs to change
                        if saleorderline_item_ids and saleorderline_item_ids.qty_to_invoice != 0:
                            saleorderline_item_ids.sudo().write({'qty_to_invoice': 0 })

            # Sync charges BEFORE confirm so tax rules exist for later application
            if self.meli_orders:
                for meli_order in self.meli_orders:
                    for payment in meli_order.payments:
                        try:
                            payment.sync_charges_from_json()
                        except Exception as e:
                            _logger.info("Error pre-syncing charges: %s", e)

            super(SaleOrder, self).confirm_ml(meli=meli,config=config)

            if (self.meli_orders):

                #process payments
                for meli_order in self.meli_orders:

                    for payment in meli_order.payments:
                        try:
                            if config.mercadolibre_process_payments_customer:

                                if 1==2 and payment.account_payment_id:
                                    fix = payment.account_payment_id and (payment.transaction_amount!=payment.total_paid_amount)
                                    fix = fix and (payment.account_payment_id.amount!=payment.transaction_amount)
                                    fix = fix and str(payment.account_payment_id.payment_date) == '2021-07-05'

                                    if (fix):
                                        _logger.info("payment fixing: "+str(payment.account_payment_id))
                                        #self.account_payment_id.cancel()
                                        payment.account_payment_id.action_draft()
                                        payment.account_payment_id.unlink()
                                        payment.account_payment_id = False

                                # Limpiar referencia stale: si account_payment_id apunta a un registro
                                # eliminado, resetearlo para que el guard no bloquee la creación.
                                if payment.account_payment_id and not payment.account_payment_id.exists():
                                    _logger.warning(
                                        "confirm_ml: account_payment_id %s ya no existe — "
                                        "reseteando para orden %s / pago %s",
                                        payment.account_payment_id.id, so.name, payment.payment_id
                                    )
                                    payment.sudo().write({'account_payment_id': False})

                                # Recuperar pagos cancelados: si el account.payment existe pero
                                # está en estado cancelado y el pago ML sigue aprobado, limpiar
                                # la referencia para que se recree. Esto cubre el caso donde el
                                # pago se creó a un partner incorrecto y fue cancelado por
                                # republish_invoice_payments o cleanup_duplicate, pero nunca
                                # se recreó porque account_payment_id seguía seteado.
                                if (payment.account_payment_id
                                        and payment.account_payment_id.exists()
                                        and payment.account_payment_id.state in cancel_statuses
                                        and payment.status in ["approved"]):
                                    _logger.info(
                                        "confirm_ml: account_payment_id %s está cancelado — "
                                        "reseteando para recrear pago de orden %s / pago ML %s",
                                        payment.account_payment_id.name, so.name, payment.payment_id
                                    )
                                    payment.sudo().write({'account_payment_id': False})

                                if not payment.account_payment_id and payment.status in ["approved"]:
                                    payment.create_payment( meli=meli, config=config )
                                elif payment.account_payment_id and payment.status in ["approved"]:
                                    try:
                                        payment._patch_withholding_on_existing_payment(config=config)
                                    except Exception as e:
                                        _logger.info("Error patching withholding on payment %s: %s", payment.payment_id, e)
                                    if payment.account_payment_id.state in draft_payment_status:
                                        payment.post_payment(config=config)

                                # [ctmil #447] 'refunded' NO cancela el pago de ingreso original: el dinero entro y
                                # luego se devolvio. El ingreso queda posteado+conciliado a la FA; la devolucion es un
                                # movimiento OUTBOUND aparte contra la NC. Solo cancelar cuando nunca hubo ingreso real.
                                if (payment.status in ["cancelled","rejected"]):
                                    payment.cancel_payments(config=config)
                                    continue;
                                if (payment.status in ["refunded","partially_refunded"]):
                                    continue;

                            else:
                                # Config desactivada: loggear si hay pagos aprobados sin procesar
                                if payment.status in ["approved"] and not payment.account_payment_id:
                                    _logger.info(
                                        "confirm_ml: proceso de pagos al cliente DESACTIVADO "
                                        "(mercadolibre_process_payments_customer=False) — "
                                        "pago %s aprobado NO procesado en orden %s",
                                        payment.payment_id, so.name
                                    )

                        except Exception as e:
                            _logger.info("Error creating customer payment")
                            _logger.info(e, exc_info=True)
                            meli_message_post(so, "Error creando pago: "+str(e), config=config)
                            pass;

                        # Wrap supplier fee payment in savepoint to isolate ValidationErrors
                        try:
                            if config.mercadolibre_process_payments_supplier_fea and not payment.account_supplier_payment_id:
                                payment.create_supplier_payment( meli=meli, config=config )
                            elif payment.account_supplier_payment_id.state in draft_payment_status:
                                payment.post_supplier_payment(config=config)
                            else:
                                payment.check_supplier_payment(config=config)

                        except Exception as e:
                            _logger.info("Error creating supplier fee payment")
                            _logger.info(e, exc_info=True)
                            meli_message_post(so, "Error creando pago de comisión: "+str(e), config=config)
                            pass;

                        try:
                            #_logger.info("confirm_ml accounting > create_supplier_payment_shipment")
                            condition_pay_supplier_shipment = (config.mercadolibre_process_payments_supplier_shipment and not payment.account_supplier_payment_shipment_id 
                                and (payment.order_id and (payment.order_id.payments_shipment_amount>0.0 or payment.order_id.shipping_seller_cost>0.0)) )
                            #_logger.info("confirm_ml accounting > create_supplier_payment_shipment condition_pay_supplier_shipment:" +str(condition_pay_supplier_shipment) )
                            allcond = {
                                "config.mercadolibre_process_payments_supplier_shipment": config.mercadolibre_process_payments_supplier_shipment,
                                "payment.account_supplier_payment_shipment_id": payment.account_supplier_payment_shipment_id,
                                "payment.order_id": payment.order_id,
                                "payment.order_id.payments_shipment_amount": payment.order_id.payments_shipment_amount,
                                "payment.order_id.shipping_seller_cost": payment.order_id.shipping_seller_cost
                            }
                            #_logger.info("confirm_ml accounting > create_supplier_payment_shipment, allcond:"+str(allcond))

                            if ( condition_pay_supplier_shipment ):
                                payment.create_supplier_payment_shipment( meli=meli, config=config )
                            elif (payment.account_supplier_payment_shipment_id and payment.account_supplier_payment_shipment_id.state in draft_payment_status):
                                payment.post_supplier_payment_shipment(config=config)
                        except Exception as e:
                            _logger.info("Error creating supplier shipment payment")
                            _logger.info(e, exc_info=True)
                            meli_message_post(so, "Error creando pago de costo de envio: "+str(e), config=config)
                            pass;

                        # Sincronizar charges_details (retenciones ISR/IVA, etc.)
                        # Siempre importar los cargos - no requiere config flag
                        try:
                            payment.sync_charges_from_json()
                        except Exception as e:
                            _logger.info("Error syncing charges from payment JSON")
                            _logger.info(e, exc_info=True)
                            meli_message_post(so, "Error sincronizando retenciones/cargos: "+str(e), config=config)
                            pass;

                    # Cleanup de pagos de cliente duplicados para esta meli.order.
                    # ML puede generar múltiples payment_id aprobados para la misma orden;
                    # si ambos ya tienen account.payment, cancelamos el más antiguo.
                    if config.mercadolibre_process_payments_customer:
                        try:
                            self._cleanup_duplicate_customer_payments(meli_order, config=config)
                        except Exception as e:
                            _logger.error(
                                "confirm_ml: Error en cleanup de pagos duplicados para orden ML %s: %s",
                                meli_order.name, e, exc_info=True
                            )


                # Aplicar impuestos de retenciones confirmadas a las lineas de la orden
                # Siempre intentar - solo aplica reglas en estado 'confirmed'
                try:
                    self._apply_meli_taxes_to_order_lines(config=config)
                except Exception as e:
                    _logger.info("Error applying MeLi taxes to order lines")
                    _logger.info(e, exc_info=True)
                    meli_message_post(so, "Error aplicando impuestos MeLi a lineas: "+str(e), config=config)
                    pass;

        except Exception as e:
            _logger.info("Confirm Payment Exception")
            _logger.error(e, exc_info=True)
            meli_message_post(so, "Confirm Payment Exception: "+str(e), config=config)
            pass
        #_logger.info("meli_oerp_accounting confirm_ml registering payments ended.")


        if config and config.mercadolibre_order_confirmation and "_invoice" in config.mercadolibre_order_confirmation:
            mo = so and so.meli_orders and so.meli_orders[0]
            if not mo.invoice_posted:
                self.meli_create_invoice( meli=meli, config=config )


        # Usar so.invoice_ids en lugar de buscar por invoice_origin (mas confiable en Odoo 18)
        invoices = so.invoice_ids.filtered(lambda i: i.move_type == 'out_invoice')
        _logger.debug("confirm_ml > invoices from invoice_ids: %s", invoices.mapped('name') if invoices else 'None')
        if not invoices:
            # Fallback: buscar por invoice_origin si invoice_ids no tiene resultados
            invoices = self.env[acc_inv_model].search( [(invoice_origin,'=',so.name)] )
            _logger.debug("confirm_ml > invoices from search by origin: %s", invoices.mapped('name') if invoices else 'None')

        if invoices:
            # Republicar pagos si la factura fue creada a un partner diferente
            # (ej: factura manual a razón social específica vs partner genérico)
            if self.meli_orders and config and config.mercadolibre_process_payments_customer:
                for meli_order in self.meli_orders:
                    for payment in meli_order.payments:
                        try:
                            if payment.account_payment_id and payment.status in ['approved']:
                                payment.republish_invoice_payments(meli=meli, config=config)
                        except Exception as e:
                            _logger.info("Error republishing payment for invoice partner mismatch")
                            _logger.error(e, exc_info=True)
                            so.message_post(
                                body="Error republicando pago: %s" % str(e),
                                message_type=product_message_type
                            )

            for inv in invoices:
                if config and "mercadolibre_payment_receipt_validation" in config._fields and config.mercadolibre_payment_receipt_validation:
                    if (inv and config.mercadolibre_payment_receipt_validation in ['concile']):
                        _logger.info("Reconcile MercadoLibre Invoice: "+str(inv.name))
                        self.meli_reconcile(invoice=inv)

                if inv.state in posted_statuses and config and config.mercadolibre_post_invoice:
                    _logger.info("Send to MercadoLibre: "+str(inv.name))
                    mo = so and so.meli_orders and so.meli_orders[0]
                    if mo:
                        mo.invoice_created = True
                        try:
                            if not mo.invoice_posted:
                                mo.orders_post_invoice( meli=meli, config=config )
                        except Exception as e:
                            _logger.info("Post To ML Invoice Exception")
                            _logger.error(e, exc_info=True)
                            pass;

        #_logger.info("meli_oerp_accounting confirm_ml ended.")

    def meli_reconcile(self, invoice=None):
        move = invoice
        if not move:
            return

        pay_term_lines = move.line_ids\
            .filtered(lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable'))

        _logger.info("Conciliar factura mercadolibre pay_term_lines:"+str(pay_term_lines))

        if not pay_term_lines:
            return

        if move.state != 'posted' \
                    or move.payment_state not in ('not_paid', 'partial') \
                    or not move.is_invoice(include_receipts=True):
            return

        #TODO es que si la factura esta a nombre de un usuario generico, como se debita el pago, el pago tambien debe hacerse al usuario generico....
        # #447: el filtrado por referencia de orden/factura (PR-XXXXX-ML-YYYYY) se
        # aplica en el loop de conciliacion (ver _ref mas abajo).
        domain = [
                ('account_id', 'in', pay_term_lines.account_id.ids),
                ('parent_state', '=', 'posted'),
                ('partner_id', '=', move.commercial_partner_id.id),
                ('reconciled', '=', False),
                '|', ('amount_residual', '!=', 0.0), ('amount_residual_currency', '!=', 0.0),
            ]

        payments_widget_vals = {'outstanding': True, 'content': [], 'move_id': move.id}

        if move.is_inbound():
            domain.append(('balance', '<', 0.0))
            payments_widget_vals['title'] = _('Outstanding credits')
        else:
            domain.append(('balance', '>', 0.0))
            payments_widget_vals['title'] = _('Outstanding debits')

        for line in self.env['account.move.line'].search(domain):

            if line.currency_id == move.currency_id:
                # Same foreign currency.
                amount = abs(line.amount_residual_currency)
            else:
                # Different foreign currencies.
                amount = move.company_currency_id._convert(
                    abs(line.amount_residual),
                    move.currency_id,
                    move.company_id,
                    line.date,
                )

            if move.currency_id.is_zero(amount):
                continue

            payments_widget_vals['content'].append({
                'journal_name': line.ref or line.move_id.name,
                'amount': amount,
                'currency_id': move.currency_id.id,
                'id': line.id,
                'move_id': line.move_id.id,
                'date': fields.Date.to_string(line.date),
                'account_payment_id': line.payment_id.id,
            })


        _logger.info("Conciliar factura MercadoLibre payments_widget_vals:"+str(payments_widget_vals))
        if not payments_widget_vals['content']:
            return

        #based on def js_assign_outstanding_line(self, line_id):
        # #447: hardening defensivo del ping-pong de pagos (payment_receipt_validation='concile').
        # _ref = referencia de la orden ML (invoice_origin o nombre de la SO). Con ella:
        #  - cortamos en cuanto la factura deja de estar impaga (no sobre-conciliar), y
        #  - salteamos los creditos cuyo memo/journal NO contenga la referencia (no robar
        #    el pago a una factura hermana del mismo partner).
        _ref = move.invoice_origin or (move.line_ids.sale_line_ids.order_id[:1].name)
        for payments_val in payments_widget_vals['content']:
            move.invalidate_recordset(['payment_state', 'amount_residual'])
            if move.payment_state not in ('not_paid', 'partial'):
                break
            if _ref and _ref not in (payments_val.get('journal_name') or ''):
                continue
            line_id = payments_val['id']
            lines = self.env['account.move.line'].browse(line_id)
            lines += move.line_ids.filtered(lambda line: line.account_id == lines[0].account_id and not line.reconciled)
            lines.reconcile()


    def _compute_invoice_posted( self ):
        for ord in self:
            ord.invoice_posted = False
            #ord.invoice_type = 'unknown'
            if ord.meli_orders:
                ord.invoice_posted = ord.meli_orders[0].invoice_posted
                #ord.invoice_type = ord.meli_orders[0].invoice_type

    def search_invoice_posted(self, operator, value):
        _logger.info("search_invoice_posted")
        _logger.info(operator)
        _logger.info(value)
        if operator == '=':
            #name = self.env.context.get('name', False)
            #if name is not False:
            id_list = []
            _logger.info(self.env.context)
            #name = self.env.context.get('name', False)
            meli_orders = self.env['mercadolibre.orders'].search([('invoice_posted','=',value)], limit=10000)
            if (meli_orders):
                for mord in meli_orders:
                    if (mord.invoice_posted==value and mord.sale_order):
                        id_list.append(mord.sale_order.id)

            return [('id', 'in', id_list)]
        elif operator == '!=':
            id_list = []
            _logger.info(self.env.context)
            #name = self.env.context.get('name', False)
            meli_orders = self.env['mercadolibre.orders'].search([('invoice_posted','!=',value)], limit=10000)
            if (meli_orders):
                for mord in meli_orders:
                    if (mord.invoice_posted!=value and mord.sale_order):
                        id_list.append(mord.sale_order.id)

            return [('id', 'in', id_list)]
        else:
            _logger.error(
                'The field name is not searchable'
                ' with the operator: {}',format(operator)
            )


    invoice_posted = fields.Boolean( string="Factura enviada", compute=_compute_invoice_posted,search=search_invoice_posted )

    # ------------------------------------------------------------------ #
    #  Pipeline de procesamiento de la venta ML (diagnostico read-only)   #
    #  Resume si las acciones esperadas de una venta de MercadoLibre se   #
    #  completaron, en orden: sincronizacion -> factura -> conciliacion   #
    #  -> publicacion de la factura a ML. Devuelve el PRIMER paso que     #
    #  quedo incompleto. Es de SOLO LECTURA (no ejecuta ninguna accion);  #
    #  sirve para detectar de un vistazo (o por cron) las ventas que      #
    #  quedaron a medias (tipico: factura sin conciliar).                 #
    # ------------------------------------------------------------------ #
    meli_pipeline_status = fields.Selection([
        ('not_meli', 'No es venta ML'),
        ('cancelled', 'Cancelada en ML'),
        ('pending_invoice', 'Falta facturar'),
        ('pending_reconcile', 'Falta conciliar'),
        ('pending_publish', 'Falta publicar a ML'),
        ('complete', 'Completa'),
    ], string='Estado pipeline ML', compute='_compute_meli_pipeline_status',
       search='_search_meli_pipeline_status', store=False,
       help='Diagnostico read-only del workflow de la venta de MercadoLibre: '
            'sincronizacion -> factura -> conciliacion -> publicacion a ML. '
            'Muestra el primer paso que quedo incompleto.')

    @api.depends('meli_order_id', 'meli_status', 'state', 'invoice_status',
                 'invoice_ids.state', 'invoice_ids.payment_state', 'invoice_posted')
    def _compute_meli_pipeline_status(self):
        for order in self:
            order.meli_pipeline_status = order._meli_pipeline_status_value()

    def _meli_pipeline_status_value(self):
        """Calcula el estado del pipeline ML para UNA venta (sin efectos)."""
        self.ensure_one()
        # 1) Solo aplica a ventas de MercadoLibre
        if not self.meli_order_id:
            return 'not_meli'
        # 2) Cancelada en ML -> no se espera nada mas
        if self.meli_status == 'cancelled' or self.state == 'cancel':
            return 'cancelled'
        # 3) Factura: debe existir una factura de cliente posteada
        posted_invoices = self.invoice_ids.filtered(
            lambda inv: inv.move_type == 'out_invoice' and inv.state == 'posted')
        if not posted_invoices:
            return 'pending_invoice'
        # 4) Conciliacion: las facturas posteadas deben estar pagadas/conciliadas
        paid_states = ('paid', 'in_payment', 'reversed')
        if any(inv.payment_state not in paid_states for inv in posted_invoices):
            return 'pending_reconcile'
        # 5) Publicacion a ML: la factura debe estar enviada a MercadoLibre
        if not self.invoice_posted:
            return 'pending_publish'
        return 'complete'

    def _search_meli_pipeline_status(self, operator, value):
        """Busqueda del campo no almacenado: filtra ordenes ML por estado.
        Acotada a ventas de ML para no recorrer todo sale.order."""
        if operator not in ('=', '!='):
            return []
        ml_orders = self.search([('meli_order_id', '!=', False)])
        matched = ml_orders.filtered(
            lambda o: (o._meli_pipeline_status_value() == value) == (operator == '='))
        return [('id', 'in', matched.ids)]

    # ------------------------------------------------------------------ #
    #  Cron de diagnostico diario (READ-ONLY): cuenta las ventas ML de   #
    #  las ultimas 24h por estado de pipeline y deja el resumen en el    #
    #  log. NO ejecuta conciliaciones ni publicaciones; solo reporta.    #
    # ------------------------------------------------------------------ #
    @api.model
    def cron_meli_pipeline_diagnostic(self, hours=24):
        from datetime import timedelta
        since = fields.Datetime.now() - timedelta(hours=hours)
        orders = self.search([
            ('meli_order_id', '!=', False),
            ('date_order', '>=', fields.Datetime.to_string(since)),
        ])
        summary = {}
        incomplete = []
        for order in orders:
            st = order._meli_pipeline_status_value()
            summary[st] = summary.get(st, 0) + 1
            if st in ('pending_invoice', 'pending_reconcile', 'pending_publish'):
                incomplete.append((order.name, order.meli_order_id, st))
        _logger.info(
            "MELI pipeline diagnostic (%sh): %s ventas ML | por estado: %s",
            hours, len(orders), summary)
        if incomplete:
            _logger.warning(
                "MELI pipeline diagnostic: %s ventas ML incompletas: %s",
                len(incomplete),
                "; ".join("%s(%s)=%s" % (n, mid, st) for n, mid, st in incomplete[:50]))
        return {'total': len(orders), 'by_status': summary, 'incomplete': len(incomplete)}
