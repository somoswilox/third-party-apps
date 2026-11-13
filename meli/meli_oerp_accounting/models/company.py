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

    meli_supplier_fee_mode = fields.Selection(
        selection=[
            ("fee_amount", "Como lo informa MercadoPago (comisión + cupón)"),
            ("charges_only", "Sólo la comisión (cargos de tipo 'fee')"),
        ],
        string="Importe del pago de comisión a MercadoLibre",
        default="fee_amount",
        help="Con qué importe se crea el pago de comisión a MercadoLibre S.R.L. "
             "(el 'PMERCP … FEE').\n\n"
             "• Como lo informa MercadoPago (por defecto): usa el 'fee_amount' del pago, "
             "que viene con la comisión Y el cupón sumados. Es el comportamiento de "
             "siempre; no cambia nada de lo que ya funciona.\n"
             "• Sólo la comisión: usa únicamente los cargos de tipo 'fee'. El cupón queda "
             "afuera (tiene su propio tipo de cargo).\n\n"
             "Cuándo conviene la segunda opción: al conciliar el diario de Mercado Pago, "
             "la línea de comisión del extracto es 'comisión + envío' y NO incluye el "
             "cupón. Si el pago se crea con el cupón adentro, esa línea no cierra nunca y "
             "hay que ajustarla a mano. Para que el cruce cierre del todo suele además "
             "hacer falta activar 'Process payments shipping list cost to Supplier ML', "
             "que genera el pago del envío.\n\n"
             "Sólo afecta a los pagos que se creen (o se corrijan) de aquí en adelante: "
             "los ya conciliados no se tocan."
    )

    meli_supplier_fee_exclude_charges = fields.Char(
        string="Cargos que NO son comisión",
        default="financing_fee,financing_add_on_fee",
        help="Nombres de cargo que NO se suman al pago de comisión a MercadoLibre S.R.L. "
             "cuando el importe se calcula con 'Sólo la comisión'. Separados por comas.\n\n"
             "Por defecto quedan afuera 'financing_fee' y 'financing_add_on_fee' (el costo "
             "de la financiación en cuotas): MercadoPago no los incluye en la línea de "
             "comisión del extracto, así que sumarlos al pago volvería a dejar el cruce sin "
             "cerrar.\n\n"
             "La comisión real son los cargos 'meli_percentage_fee' y 'flat_fee'. Si en su "
             "operación aparece algún otro cargo de tipo 'fee' que tampoco viaja en la "
             "línea de comisión del extracto, agréguelo acá.\n\n"
             "Vacío = se suman todos los cargos de tipo 'fee'."
    )

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

    # #caso-K72 (caso-K21 cliente F): retenciones que MercadoPago aplica al cobro, registradas con
    # l10n_ar_withholding (Odoo 17/18/19, AR). Opt-in: apagado = el cobro se crea como siempre.
    mercadolibre_ar_withholding_on_payment = fields.Boolean(
        string="Registrar retenciones de MercadoPago en el cobro (AR)",
        default=False,
        help="Requiere el modulo 'Argentina - Payment Withholdings' (l10n_ar_withholding). "
             "Cuando el cobro de MercadoPago trae retenciones (Impuesto a los Debitos y Creditos, "
             "SIRTAC, IIBB...), el pago del cliente se registra por el NETO y cada retencion queda "
             "como linea de retencion del pago, igual que al registrarla a mano. La factura queda "
             "pagada por el total. Cada retencion necesita una regla en MercadoLibre > Impuestos "
             "confirmada, con un impuesto de tipo 'Retencion en pago de cliente', y la compania "
             "necesita la 'Cuenta base de impuestos' de retenciones configurada.",
    )

    #mercadolibre_account_payment_receiptbook_id = fields.Many2one( "account.payment.receiptbook", string="Recibos")
    #mercadolibre_account_payment_supplier_receiptbook_id = fields.Many2one( "account.payment.receiptbook", string="Ordenes de pago")
    #mercadolibre_customer_payment_method_id = fields.Many2one( "l10n_mx_edi.payment.method", string="Customer Payment Method")
    #mercadolibre_provider_payment_method_id = fields.Many2one( "l10n_mx_edi.payment.method", string="Provider Payment Method")


    # ------------------------------------------------------------------ #
    #  un caso — Red de seguridad de re-facturacion (ver sale.order          #
    #  _meli_requeue_uninvoiced en models/order.py).                      #
    #  OJO multi-cuenta: en instancias con meli_oerp_multiple la config   #
    #  EFECTIVA es `mercadolibre.configuration`, NO res.company. Los      #
    #  campos gemelos de alla DEBEN tener los MISMOS defaults que estos   #
    #  (fue el bug del un caso: defaults distintos = opcion apagada sin que  #
    #  se note).                                                          #
    # ------------------------------------------------------------------ #
    mercadolibre_invoice_requeue = fields.Boolean(
        string="Reintentar facturas que fallaron",
        default=True,
        help="Barrido periodico que vuelve a intentar emitir la factura de las ventas de "
             "MercadoLibre pagadas que quedaron sin factura posteada (rechazo de ARCA, "
             "webservice caido, tipo de documento faltante...). Requiere ademas que el cron "
             "'MELI: reintentar facturas que quedaron sin emitir' este activo.")
    mercadolibre_invoice_requeue_days = fields.Integer(
        string="Dias hacia atras (reintento de factura)",
        default=30,
        help="Ventana en dias (por fecha del pedido) de ventas a considerar en el barrido "
             "de re-facturacion.")
    mercadolibre_invoice_requeue_limit = fields.Integer(
        string="Max ventas por ciclo (reintento de factura)",
        default=20,
        help="Tope de ventas a re-facturar por ciclo del cron, para acotar el uso del "
             "webservice fiscal y el tiempo del cron.")
    mercadolibre_invoice_requeue_max_retries = fields.Integer(
        string="Max reintentos por venta (factura)",
        default=8,
        help="Cuantas veces se reintenta emitir la factura de una misma venta antes de "
             "marcarla como TRABADA, avisar por actividad y dejar de tocarla.")

    def cron_meli_invoice_requeue(self):
        """un caso - Cron de re-facturacion (mono-cuenta). `meli_oerp_multiple` lo override
        para iterar todas las mercadolibre.account con su token y su compania."""
        company = self.env.user.company_id
        if not company.mercadolibre_invoice_requeue:
            return True
        apistate = self.env['meli.util'].get_new_instance(company)
        if apistate and apistate.needlogin_state:
            _logger.warning("cron_meli_invoice_requeue: cuenta SIN LOGIN (token vencido) — se omite.")
            return True
        return self.env['sale.order']._meli_requeue_uninvoiced(meli=apistate, config=company)

    def hi(self):
        return True
