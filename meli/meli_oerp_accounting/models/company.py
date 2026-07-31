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

import pdb
import requests

class ResCompany(models.Model):
    _name = "res.company"
    _inherit = "res.company"

    mercadolibre_process_payments_customer = fields.Boolean(string="Process payments from Customer")
    mercadolibre_process_payments_supplier_fea = fields.Boolean(string="Process payments fea to Supplier ML")
    mercadolibre_process_payments_supplier_shipment = fields.Boolean(string="Process payments shipping list cost to Supplier ML")

    mercadolibre_payment_receipt_validation = fields.Selection([('draft','Borrador'),('validate','Autovalidación'),('concile','Conciliar')], string="Payment validation",default='draft')

    mercadolibre_process_payments_journal = fields.Many2one("account.journal",string="Account Journal for MercadoLibre")
    mercadolibre_process_payments_res_partner = fields.Many2one("res.partner",string="MercadoLibre Partner")

    mercadolibre_process_payments_journal_shp = fields.Many2one("account.journal",string="Account Journal for MercadoLibre (SHP)")
    mercadolibre_process_payments_res_partner_shp = fields.Many2one("res.partner",string="MercadoLibre Partner (SHP)")

    mercadolibre_order_confirmation = fields.Selection(selection_add=[("paid_confirm_with_invoice", "Pagado>Facturado"),
                                                ("paid_delivered_with_invoice", "Pagado>Facturado y Entregado")],
                                                ondelete={"paid_confirm_with_invoice": "set default"},
                                                string='Acción al recibir un pedido',
                                                help='Acción al confirmar una orden o pedido de venta')

    mercadolibre_order_confirmation_invoice = fields.Selection([ ("manual", "No facturar"),
                                                ("paid_confirm_invoice", "Pagado > Facturar"),
                                                ("paid_confirm_delivered_invoice", "Entregado > Facturar"),

                                                ("paid_confirm_invoice_draft", "Pagado > Factura borrador"),
                                                ("paid_confirm_delivered_invoice_draft", "Entregado > Factura borrador"),
                                                #("paid_confirm_invoice_deliver", "Pagado > Facturar > Entregar")
                                                ],
                                                string='Acción sobre la factura al confirmar un pedido',
                                                help='Acción sobre la factura al confirmar una orden o pedido de venta')

    mercadolibre_order_confirmation_invoice_full = fields.Selection([ ("manual", "No facturar"),
                                                ("paid_confirm_invoice", "Pagado > Facturar"),
                                                ("paid_confirm_delivered_invoice", "Entregado > Facturar"),

                                                ("paid_confirm_invoice_draft", "Pagado > Factura borrador"),
                                                ("paid_confirm_delivered_invoice_draft", "Entregado > Factura borrador"),
                                                #("paid_confirm_invoice_deliver", "Pagado > Facturar > Entregar")
                                                ],
                                                string='(FULL) Acción sobre la factura al confirmar un pedido',
                                                help='(FULL) Acción sobre la factura al confirmar una orden o pedido de venta')

    meli_coupon_invoice_mode = fields.Selection(
        selection=[
            ("full", "Precio pleno (sin descuento de cupón)"),
            ("product_discount", "Descuento en producto"),
            ("separate_line", "Línea de descuento separada (avanzado)"),
        ],
        string="Tratamiento del cupón ML en la factura",
        default="full",
        help="Cómo se refleja el 'coupon_amount' que MercadoLibre financia de su propio costo "
             "(no es un descuento del vendedor):\n\n"
             "• Precio pleno (por defecto): la factura se emite por el precio de venta completo. "
             "Correcto cuando ML reembolsa el cupón al vendedor (su ingreso gravado es el precio "
             "pleno). Ni el producto ni el envío llevan el descuento.\n"
             "• Descuento en producto: el cupón se aplica como % de descuento sobre las líneas de "
             "producto (la factura coincide con lo que pagó el comprador).\n"
             "• Línea de descuento separada (avanzado): el cupón se imputa como línea(s) de "
             "descuento aparte, una por grupo de impuesto, sin tocar producto ni envío. Requiere "
             "validación fiscal previa (facturación electrónica AFIP/CL).\n\n"
             "Reemplaza a la antigua casilla 'Facturar con descuento de cupón'.",
    )

    meli_coupon_discount_on_invoice = fields.Boolean(
        string="Facturar con descuento de cupón financiado por ML",
        default=False,
        help="Controla cómo se trata el 'coupon_amount' que MercadoLibre financia de su "
             "propio costo (no es un descuento del vendedor).\n\n"
             "☐ Desactivado (por defecto): factura por el precio de venta completo.\n"
             "☑ Activado: aplica el cupón ML como % de descuento en líneas.\n\n"
             "No afecta descuentos del vendedor ni descuentos manuales.",
    )

    mercadolibre_invoice_cancel_mode = fields.Selection([
        ("manual", "Manual (no hacer nada)"),
        ("draft", "Revertir factura a borrador"),
        ("cancel", "Cancelar factura"),
        ("credit_note", "Crear nota de crédito"),
    ], string="Acción sobre factura al cancelar pedido",
       default="manual",
       help="Qué hacer con las facturas cuando MercadoLibre cancela un pedido:\n"
            "- Manual: no toca las facturas, gestionar a mano\n"
            "- Revertir a borrador: pasa la factura a borrador (solo si no tiene pagos conciliados)\n"
            "- Cancelar: cancela la factura directamente\n"
            "- Nota de crédito: crea una nota de crédito de reverso (opción más segura contablemente)")

    mercadolibre_post_invoice = fields.Boolean(string="Send Invoice",help="Try to post invoice, when order is revisited or refreshed.")
    mercadolibre_post_invoice_dont_send = fields.Boolean(string="Dont really send, just prepare to post invoice.")

    mercadolibre_set_fully_invoice = fields.Boolean( string="Set Fully Invoice", help="Marcar como completamente facturado la orden correspondiente (incluido linea de envio)" )

    mercadolibre_invoice_journal_id = fields.Many2one( "account.journal", string="Diario Facturacion" )
    mercadolibre_invoice_journal_id_full = fields.Many2one( "account.journal", string="Diario Facturacion Full" )
    mercadolibre_invoice_journal_report_id = fields.Many2one( "ir.actions.report", string="Reporte de factura" )

    mercadolibre_analytic_account_id = fields.Many2one( "account.analytic.account", string="Cuenta Analítica" )



    mercadolibre_process_charges = fields.Boolean(
        string="Procesar retenciones/cargos",
        default=False,
        help="Sincronizar charges_details de MercadoPago (retenciones ISR/IVA, comisiones detalladas, etc.)",
    )

    #mercadolibre_account_payment_receiptbook_id = fields.Many2one( "account.payment.receiptbook", string="Recibos")
    #mercadolibre_account_payment_supplier_receiptbook_id = fields.Many2one( "account.payment.receiptbook", string="Ordenes de pago")
    #mercadolibre_customer_payment_method_id = fields.Many2one( "l10n_mx_edi.payment.method", string="Customer Payment Method")
    #mercadolibre_provider_payment_method_id = fields.Many2one( "l10n_mx_edi.payment.method", string="Provider Payment Method")

    def hi(self):
        return True
