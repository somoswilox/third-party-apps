# -*- coding: utf-8 -*-
##############################################################################
#
#    MercadoLibre Orders Actions Wizard
#    Extended wizard for managing ML orders from multiple models
#
##############################################################################

from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError

import logging
_logger = logging.getLogger(__name__)
from odoo.addons.meli_oerp_accounting.models.versions import *

class MercadoLibreOrdersActionsWizard(models.TransientModel):
    """
    Wizard extendido para realizar acciones masivas sobre pedidos de MercadoLibre.
    Puede ser accedido desde: sale.order, account.move, stock.picking, mercadolibre.orders
    """
    _name = "mercadolibre.orders.actions.wiz"
    _description = "MercadoLibre Orders Actions Wizard"

    # =========================================================================
    # HELPER METHODS FOR ODOO VERSION COMPATIBILITY
    # =========================================================================
    def _get_payment_ref_field(self):
        """Get the correct reference field name for account.payment (ref or memo depending on Odoo version)"""
        payment_model = self.env['account.payment']
        if 'memo' in payment_model._fields:
            return 'memo'
        return 'ref'

    def _get_payment_ref(self, payment):
        """Get payment reference value, compatible with Odoo 17 (ref) and 18+ (memo)"""
        if hasattr(payment, 'memo') and payment.memo:
            return payment.memo
        if hasattr(payment, 'ref') and payment.ref:
            return payment.ref
        return ''

    # =========================================================================
    # CAMPOS DE ACCION
    # =========================================================================
    action_type = fields.Selection([
        ('update_orders', 'Actualizar Pedidos ML'),
        ('force_cancel_payments', 'Forzar Cancelacion de Pagos'),
        ('force_invoice', 'Forzar Facturacion'),
        ('force_reconcile', 'Forzar Conciliacion'),
        ('force_confirm_sales', 'Forzar Confirmacion de Ventas'),
        ('force_cancel_sales', 'Forzar Cancelacion de Ventas'),
        ('force_validate_delivery', 'Forzar Validacion de Entrega'),
        ('adjust_payment_rounding', 'Ajustar Redondeo de Pagos'),
        ('adjust_order_rounding', 'Ajustar Redondeo de Ordenes'),
        ('fix_coupon_payments', 'Corregir Pagos con Cupon'),
        ('fix_reconciliation_rounding', 'Corregir Conciliacion (centavos)'),
        ('verify_amounts', 'Verificar/Corregir Montos (SO vs MeLi)'),
        ('force_to_draft', 'Forzar a Borrador'),
        ('delete_invoice', 'Eliminar Factura'),
        ('republish_invoice_payments', 'Republicar Pagos (partner de factura)'),
        ('fix_invoice_status', 'Corregir Estado de Facturacion'),
        ('assign_lots_full', 'Auto-asignar Lotes FULL (FIFO) y Validar'),
        ('mark_for_batch_update', 'Marcar para Actualización Batch ML (Cron)'),
    ], string="Accion a Realizar", default='update_orders', required=True)

    # Opciones para assign_lots_full
    assign_lots_also_validate = fields.Boolean(
        string="Validar picking tras asignar lotes",
        default=True,
        help="Si está activo, después de asignar FIFO se intenta ejecutar "
             "button_validate() para cerrar la entrega."
    )

    # Opciones adicionales
    cancel_blocked = fields.Boolean(
        string="Desbloquear y Cancelar",
        default=True,
        help="Desbloquea ordenes bloqueadas antes de cancelar"
    )

    invoice_draft_only = fields.Boolean(
        string="Solo facturas en borrador",
        default=False,
        help="Solo cancelar pagos de facturas en borrador"
    )

    force_reconcile_after_invoice = fields.Boolean(
        string="Conciliar despues de facturar",
        default=True,
        help="Concilia automaticamente despues de crear la factura"
    )

    # Opciones para cancelacion de pagos
    cancel_payments_mode = fields.Selection([
        ('all', 'Cancelar TODOS los pagos'),
        ('duplicates_only', 'Solo cancelar DUPLICADOS (limpiar)'),
        ('draft_only', 'Solo cancelar pagos en BORRADOR'),
    ], string="Modo de Cancelacion", default='duplicates_only',
        help="Seleccione el modo de cancelacion de pagos")

    include_supplier_payments = fields.Boolean(
        string="Incluir pagos de proveedor (FEE/SHP)",
        default=True,
        help="Incluir pagos de comisiones y envios"
    )

    unlink_cancelled_payments = fields.Boolean(
        string="Eliminar pagos cancelados",
        default=False,
        help="Elimina los pagos despues de cancelarlos (solo draft/cancelled)"
    )

    # Opciones para ajuste de redondeo
    rounding_tolerance = fields.Float(
        string="Tolerancia de redondeo",
        default=1.0,
        help="Diferencia maxima en moneda (ej: 1.0 = un peso) para ajustar automaticamente"
    )

    ignore_tolerance = fields.Boolean(
        string="Ignorar tolerancia (forzar re-conciliacion)",
        default=False,
        help="Procesar cualquier factura con residual, sin importar el monto. Util para corregir conciliaciones incorrectas."
    )

    round_to_integer = fields.Boolean(
        string="Redondear a entero (sin centavos)",
        default=False,
        help="Para paises como Argentina donde ya no existen los centavos"
    )

    rounding_mode = fields.Selection([
        ('to_sale_order', 'Ajustar al monto de Orden de Venta'),
        ('to_invoice', 'Ajustar al monto de Factura'),
        ('round_integer', 'Solo redondear a entero'),
    ], string="Modo de Ajuste", default='to_sale_order',
        help="Seleccione como ajustar los montos de pago")

    # Informacion
    records_count = fields.Integer(
        string="Registros seleccionados",
        compute="_compute_records_count"
    )

    source_model = fields.Char(
        string="Modelo origen",
        compute="_compute_source_model"
    )

    @api.depends_context('active_model', 'active_ids')
    def _compute_records_count(self):
        for wiz in self:
            active_ids = self.env.context.get('active_ids', [])
            wiz.records_count = len(active_ids)

    @api.depends_context('active_model')
    def _compute_source_model(self):
        for wiz in self:
            wiz.source_model = self.env.context.get('active_model', '')

    # =========================================================================
    # METODOS AUXILIARES
    # =========================================================================
    def _get_sale_orders(self):
        """
        Obtiene los sale.order relacionados segun el modelo de origen.
        Soporta: sale.order, account.move, stock.picking, mercadolibre.orders
        """
        context = self.env.context
        active_model = context.get('active_model', '')
        active_ids = context.get('active_ids', [])

        sale_orders = self.env['sale.order']

        if active_model == 'sale.order':
            sale_orders = self.env['sale.order'].browse(active_ids)

        elif active_model == 'account.move':
            invoices = self.env['account.move'].browse(active_ids)
            for inv in invoices:
                # Buscar sale orders desde las lineas de factura
                if inv.invoice_line_ids:
                    for line in inv.invoice_line_ids:
                        if line.sale_line_ids:
                            sale_orders |= line.sale_line_ids.mapped('order_id')
                # Buscar por invoice_origin si existe
                if inv.invoice_origin:
                    origins = inv.invoice_origin.split(',')
                    for origin in origins:
                        so = self.env['sale.order'].search([('name', '=', origin.strip())], limit=1)
                        if so:
                            sale_orders |= so

        elif active_model == 'stock.picking':
            pickings = self.env['stock.picking'].browse(active_ids)
            for pick in pickings:
                if pick.sale_id:
                    sale_orders |= pick.sale_id

        elif active_model == 'mercadolibre.orders':
            meli_orders = self.env['mercadolibre.orders'].browse(active_ids)
            for morder in meli_orders:
                if morder.sale_order:
                    sale_orders |= morder.sale_order

        return sale_orders

    def _get_meli_orders(self):
        """
        Obtiene los mercadolibre.orders relacionados segun el modelo de origen.
        """
        context = self.env.context
        active_model = context.get('active_model', '')
        active_ids = context.get('active_ids', [])

        meli_orders = self.env['mercadolibre.orders']

        if active_model == 'mercadolibre.orders':
            meli_orders = self.env['mercadolibre.orders'].browse(active_ids)

        elif active_model == 'sale.order':
            sale_orders = self.env['sale.order'].browse(active_ids)
            for so in sale_orders:
                if so.meli_orders:
                    meli_orders |= so.meli_orders
                elif so.meli_order:
                    meli_orders |= so.meli_order

        elif active_model == 'account.move':
            sale_orders = self._get_sale_orders()
            for so in sale_orders:
                if so.meli_orders:
                    meli_orders |= so.meli_orders
                elif so.meli_order:
                    meli_orders |= so.meli_order

        elif active_model == 'stock.picking':
            sale_orders = self._get_sale_orders()
            for so in sale_orders:
                if so.meli_orders:
                    meli_orders |= so.meli_orders
                elif so.meli_order:
                    meli_orders |= so.meli_order

        return meli_orders

    # =========================================================================
    # METODOS DE ACCION
    # =========================================================================
    def action_execute(self):
        """
        Ejecuta la accion seleccionada
        """
        self.ensure_one()

        if self.action_type == 'update_orders':
            return self._action_update_orders()
        elif self.action_type == 'force_cancel_payments':
            return self._action_force_cancel_payments()
        elif self.action_type == 'force_invoice':
            return self._action_force_invoice()
        elif self.action_type == 'force_reconcile':
            return self._action_force_reconcile()
        elif self.action_type == 'force_confirm_sales':
            return self._action_force_confirm_sales()
        elif self.action_type == 'force_cancel_sales':
            return self._action_force_cancel_sales()
        elif self.action_type == 'force_validate_delivery':
            return self._action_force_validate_delivery()
        elif self.action_type == 'adjust_payment_rounding':
            return self._action_adjust_payment_rounding()
        elif self.action_type == 'adjust_order_rounding':
            return self._action_adjust_order_rounding()
        elif self.action_type == 'fix_coupon_payments':
            return self._action_fix_coupon_payments()
        elif self.action_type == 'fix_reconciliation_rounding':
            return self._action_fix_reconciliation_rounding()

        elif self.action_type == 'verify_amounts':
            return self._action_verify_amounts()
        elif self.action_type == 'force_to_draft':
            return self._action_force_to_draft()
        elif self.action_type == 'delete_invoice':
            return self._action_delete_invoice()
        elif self.action_type == 'fix_invoice_status':
            return self._action_fix_invoice_status()
        elif self.action_type == 'assign_lots_full':
            return self._action_assign_lots_full()
        elif self.action_type == 'mark_for_batch_update':
            return self._action_mark_for_batch_update()

        return {'type': 'ir.actions.act_window_close'}

    def _action_update_orders(self):
        """
        Actualiza los pedidos de ML
        """
        warningobj = self.env['meli.warning']
        meli_orders = self._get_meli_orders()

        if not meli_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de MercadoLibre para actualizar"
            )

        rets = []
        for order in meli_orders:
            try:
                with self.env.cr.savepoint():
                    ret = order.orders_update_order()
                if ret and isinstance(ret, dict) and 'name' in ret:
                    rets.append(ret)
                if ret and isinstance(ret, list) and ret[0] and "error" in ret[0]:
                    rets.append(ret[0])
            except Exception as e:
                _logger.error("Error actualizando orden %s: %s", order.name, str(e))
                rets.append({'error': str(e), 'order': order.name})

        if rets:
            return warningobj.info(
                title='MELI WARNING',
                message="Errores al actualizar ordenes: " + str(len(rets)),
                message_html=str(rets)
            )

        return warningobj.info(
            title='MELI INFO',
            message="Se actualizaron %d ordenes correctamente" % len(meli_orders)
        )

    def _action_force_cancel_payments(self):
        """
        Forzar la cancelacion de pagos (cancelados o en borrador)
        Incluye busqueda de pagos duplicados por memo/ref
        """
        warningobj = self.env['meli.warning']
        meli_orders = self._get_meli_orders()
        sale_orders = self._get_sale_orders()

        if not meli_orders and not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de MercadoLibre ni ordenes de venta"
            )

        cancelled_count = 0
        deleted_count = 0
        duplicates_found = 0
        errors = []
        report_lines = []

        # Recopilar todos los nombres de ordenes de venta para buscar duplicados
        so_names = sale_orders.mapped('name')

        # Buscar pagos duplicados por memo/ref
        # El formato del memo es: "{SO_NAME} OP {payment_id} TOT/FEE/SHP"
        duplicates_by_ref = {}

        for so_name in so_names:
            # Buscar todos los pagos que contengan el nombre de la orden en el ref/memo
            search_pattern = so_name
            ref_field = self._get_payment_ref_field()
            payments_found = self.env['account.payment'].search([
                (ref_field, 'ilike', search_pattern),
                ('state', 'in', ['draft', 'posted', 'cancelled'])
            ])

            if payments_found:
                # Agrupar por ref exacto para encontrar duplicados
                for pay in payments_found:
                    ref_key = self._get_payment_ref(pay)
                    if ref_key not in duplicates_by_ref:
                        duplicates_by_ref[ref_key] = []
                    duplicates_by_ref[ref_key].append(pay)

        # Procesar duplicados encontrados
        for ref_key, payments in duplicates_by_ref.items():
            if len(payments) > 1:
                duplicates_found += len(payments) - 1
                report_lines.append("DUPLICADO [%s]: %d pagos encontrados" % (ref_key, len(payments)))

                # Si el modo es solo duplicados, cancelar todos menos el primero posted
                if self.cancel_payments_mode == 'duplicates_only':
                    # Mantener el primer pago posted, cancelar el resto
                    posted_payments = [p for p in payments if p.state == 'posted']
                    draft_payments = [p for p in payments if p.state == 'draft']
                    cancelled_payments = [p for p in payments if p.state == 'cancelled']

                    # Determinar cual mantener (primer posted, o primer draft si no hay posted)
                    keep_payment = None
                    if posted_payments:
                        keep_payment = posted_payments[0]
                    elif draft_payments:
                        keep_payment = draft_payments[0]

                    payments_to_cancel = [p for p in payments if p.id != (keep_payment and keep_payment.id)]

                    for pay in payments_to_cancel:
                        try:
                            if pay.state == 'posted':
                                pay.action_draft()
                                pay.action_cancel()
                                cancelled_count += 1
                                report_lines.append("  - Cancelado (era posted): %s" % pay.name)
                            elif pay.state == 'draft':
                                pay.action_cancel()
                                cancelled_count += 1
                                report_lines.append("  - Cancelado (era draft): %s" % pay.name)

                            # Eliminar si esta habilitado
                            if self.unlink_cancelled_payments and pay.state in ['cancelled', 'draft']:
                                pay.unlink()
                                deleted_count += 1
                                report_lines.append("  - Eliminado: %s" % pay.name)

                        except Exception as e:
                            errors.append("Pago %s: %s" % (pay.name, str(e)))

        # Si el modo es cancelar todos o solo draft, procesar ordenes ML
        if self.cancel_payments_mode in ['all', 'draft_only']:
            for morder in meli_orders:
                try:
                    with self.env.cr.savepoint():
                        for payment in morder.payments:
                            # Pagos de cliente
                            if payment.account_payment_id:
                                pay = payment.account_payment_id
                                should_cancel = False

                                if self.cancel_payments_mode == 'all':
                                    should_cancel = pay.state in ['draft', 'posted']
                                elif self.cancel_payments_mode == 'draft_only':
                                    should_cancel = pay.state == 'draft'

                                if should_cancel:
                                    try:
                                        if pay.state == 'posted':
                                            pay.action_draft()
                                        if pay.state == 'draft':
                                            pay.action_cancel()
                                            cancelled_count += 1
                                            report_lines.append("Cancelado pago cliente: %s [%s]" % (pay.name, self._get_payment_ref(pay)))

                                        if self.unlink_cancelled_payments and pay.state in ['cancelled', 'draft']:
                                            pay.unlink()
                                            deleted_count += 1
                                            # Limpiar referencia en meli payment
                                            payment.account_payment_id = False

                                    except Exception as e:
                                        errors.append("Pago %s: %s" % (pay.name, str(e)))

                            # Pagos de proveedor (FEE)
                            if self.include_supplier_payments and payment.account_supplier_payment_id:
                                pay = payment.account_supplier_payment_id
                                should_cancel = False

                                if self.cancel_payments_mode == 'all':
                                    should_cancel = pay.state in ['draft', 'posted']
                                elif self.cancel_payments_mode == 'draft_only':
                                    should_cancel = pay.state == 'draft'

                                if should_cancel:
                                    try:
                                        if pay.state == 'posted':
                                            pay.action_draft()
                                        if pay.state == 'draft':
                                            pay.action_cancel()
                                            cancelled_count += 1
                                            report_lines.append("Cancelado pago FEE: %s [%s]" % (pay.name, self._get_payment_ref(pay)))

                                        if self.unlink_cancelled_payments and pay.state in ['cancelled', 'draft']:
                                            pay.unlink()
                                            deleted_count += 1
                                            payment.account_supplier_payment_id = False

                                    except Exception as e:
                                        errors.append("Pago FEE %s: %s" % (pay.name, str(e)))

                            # Pagos de envio (SHP)
                            if self.include_supplier_payments and hasattr(payment, 'account_supplier_payment_shipment_id') and payment.account_supplier_payment_shipment_id:
                                pay = payment.account_supplier_payment_shipment_id
                                should_cancel = False

                                if self.cancel_payments_mode == 'all':
                                    should_cancel = pay.state in ['draft', 'posted']
                                elif self.cancel_payments_mode == 'draft_only':
                                    should_cancel = pay.state == 'draft'

                                if should_cancel:
                                    try:
                                        if pay.state == 'posted':
                                            pay.action_draft()
                                        if pay.state == 'draft':
                                            pay.action_cancel()
                                            cancelled_count += 1
                                            report_lines.append("Cancelado pago SHP: %s [%s]" % (pay.name, self._get_payment_ref(pay)))

                                        if self.unlink_cancelled_payments and pay.state in ['cancelled', 'draft']:
                                            pay.unlink()
                                            deleted_count += 1
                                            payment.account_supplier_payment_shipment_id = False

                                    except Exception as e:
                                        errors.append("Pago SHP %s: %s" % (pay.name, str(e)))

                except Exception as e:
                    _logger.error("Error procesando pagos de orden %s: %s", morder.name, str(e))
                    errors.append("Orden %s: %s" % (morder.name, str(e)))

        # Construir mensaje de resultado
        message_parts = []
        message_parts.append("Modo: %s" % dict(self._fields['cancel_payments_mode'].selection).get(self.cancel_payments_mode))
        message_parts.append("Duplicados encontrados: %d" % duplicates_found)
        message_parts.append("Pagos cancelados: %d" % cancelled_count)
        if deleted_count:
            message_parts.append("Pagos eliminados: %d" % deleted_count)

        message = "\n".join(message_parts)

        if report_lines:
            message += "\n\n--- Detalle ---\n" + "\n".join(report_lines[:30])
            if len(report_lines) > 30:
                message += "\n... y %d lineas mas" % (len(report_lines) - 30)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Cancelacion/Limpieza de Pagos',
            message=message
        )

    def _action_force_invoice(self):
        """
        Forzar la facturacion de ventas
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        invoiced_count = 0
        errors = []

        for so in sale_orders:
            try:
                # Solo ordenes confirmadas pueden facturarse
                if so.state not in ['sale', 'done']:
                    errors.append("Orden %s no esta confirmada (estado: %s)" % (so.name, so.state))
                    continue

                # Verificar si ya tiene facturas
                if so.invoice_ids:
                    # Si tiene facturas en borrador, validarlas
                    for inv in so.invoice_ids:
                        if inv.state == 'draft':
                            try:
                                inv.action_post()
                                invoiced_count += 1
                            except Exception as e:
                                errors.append("Factura %s: %s" % (inv.name, str(e)))
                else:
                    # Crear factura
                    try:
                        so._create_invoices()
                        invoiced_count += 1

                        # Validar la factura creada
                        for inv in so.invoice_ids:
                            if inv.state == 'draft':
                                inv.action_post()

                        # Conciliar si esta habilitado
                        if self.force_reconcile_after_invoice:
                            for inv in so.invoice_ids:
                                if inv.state == 'posted':
                                    if hasattr(so, 'meli_reconcile'):
                                        so.meli_reconcile(invoice=inv)

                    except Exception as e:
                        errors.append("Orden %s: %s" % (so.name, str(e)))

            except Exception as e:
                _logger.error("Error facturando orden %s: %s", so.name, str(e))
                errors.append("Orden %s: %s" % (so.name, str(e)))

        message = "Se procesaron %d facturas" % invoiced_count
        if errors:
            message += "\n\nErrores:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Facturacion',
            message=message
        )

    def _action_force_reconcile(self):
        """
        Forzar la conciliacion de facturas
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        reconciled_count = 0
        errors = []

        for so in sale_orders:
            try:
                with self.env.cr.savepoint():
                    if so.invoice_ids:
                        for inv in so.invoice_ids:
                            if inv.state == 'posted' and inv.payment_state in ('not_paid', 'partial'):
                                try:
                                    if hasattr(so, 'meli_reconcile'):
                                        so.meli_reconcile(invoice=inv)
                                        reconciled_count += 1
                                    else:
                                        errors.append("Orden %s: metodo meli_reconcile no disponible" % so.name)
                                except Exception as e:
                                    errors.append("Factura %s: %s" % (inv.name, str(e)))
                    else:
                        errors.append("Orden %s no tiene facturas" % so.name)

            except Exception as e:
                _logger.error("Error conciliando orden %s: %s", so.name, str(e))
                errors.append("Orden %s: %s" % (so.name, str(e)))

        message = "Se conciliaron %d facturas" % reconciled_count
        if errors:
            message += "\n\nErrores:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Conciliacion',
            message=message
        )

    def _action_force_confirm_sales(self):
        """
        Forzar la confirmacion de ventas
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        confirmed_count = 0
        errors = []

        for so in sale_orders:
            try:
                with self.env.cr.savepoint():
                    if so.state == 'draft':
                        so.action_confirm()
                        confirmed_count += 1
                    elif so.state == 'sent':
                        so.action_confirm()
                        confirmed_count += 1
                    elif so.state in ['sale', 'done']:
                        _logger.info("Orden %s ya esta confirmada", so.name)
                    else:
                        errors.append("Orden %s no se puede confirmar (estado: %s)" % (so.name, so.state))

            except Exception as e:
                _logger.error("Error confirmando orden %s: %s", so.name, str(e))
                errors.append("Orden %s: %s" % (so.name, str(e)))

        message = "Se confirmaron %d ordenes" % confirmed_count
        if errors:
            message += "\n\nErrores:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Confirmacion de Ventas',
            message=message
        )

    def _action_force_cancel_sales(self):
        """
        Forzar la cancelacion de ventas
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        cancelled_count = 0
        errors = []

        for so in sale_orders:
            try:
                with self.env.cr.savepoint():
                    is_locked = (so.state in ["done"]) or ("locked" in so._fields and so.locked)

                    if is_locked and self.cancel_blocked:
                        # Desbloquear primero
                        if hasattr(so, 'action_unlock'):
                            so.action_unlock()
                        so.with_context(disable_cancel_warning=True).action_cancel()
                        cancelled_count += 1
                    elif so.state in ["draft", "sale", "sent"] and not is_locked:
                        so.with_context(disable_cancel_warning=True).action_cancel()
                        cancelled_count += 1
                    elif so.state == 'cancel':
                        _logger.info("Orden %s ya esta cancelada", so.name)
                    else:
                        errors.append("Orden %s no se puede cancelar (estado: %s, bloqueada: %s)" % (so.name, so.state, is_locked))

            except Exception as e:
                _logger.error("Error cancelando orden %s: %s", so.name, str(e))
                errors.append("Orden %s: %s" % (so.name, str(e)))

        message = "Se cancelaron %d ordenes" % cancelled_count
        if errors:
            message += "\n\nErrores:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Cancelacion de Ventas',
            message=message
        )

    def _action_force_validate_delivery(self):
        """
        Forzar la validacion de entregas (pickings)
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        validated_count = 0
        errors = []

        for so in sale_orders:
            try:
                if not so.picking_ids:
                    errors.append("Orden %s no tiene entregas" % so.name)
                    continue

                for pick in so.picking_ids:
                    try:
                        with self.env.cr.savepoint():
                            if pick.state in ['done', 'cancel']:
                                continue

                            # Confirmar si esta en draft
                            if pick.state == 'draft':
                                pick.action_confirm()

                            # Asignar si esta confirmado o en espera
                            if pick.state in ['confirmed', 'waiting']:
                                pick.action_assign()

                            # Establecer cantidades si hay move_line_ids
                            if pick.move_line_ids and pick.state not in ['done', 'cancel']:
                                for ml in pick.move_line_ids:
                                    if ml.quantity == 0:
                                        ml.quantity = ml.quantity_product_uom or ml.move_id.product_uom_qty

                            # Validar el picking
                            if pick.state not in ['done', 'cancel']:
                                pick.button_validate()
                                validated_count += 1

                    except Exception as e:
                        _logger.warning("Error validando picking %s: %s", pick.name, str(e))
                        errors.append("Picking %s: %s" % (pick.name, str(e)))

            except Exception as e:
                _logger.error("Error procesando entregas de orden %s: %s", so.name, str(e))
                errors.append("Orden %s: %s" % (so.name, str(e)))

        message = "Se validaron %d entregas" % validated_count
        if errors:
            message += "\n\nErrores:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Validacion de Entregas',
            message=message
        )

    def _action_assign_lots_full(self):
        """
        Auto-asigna lotes en FIFO para entregas MELI FULL y opcionalmente las valida.

        Flujo por picking:
          1. action_confirm() si está en draft.
          2. action_assign() (intento estándar de Odoo).
          3. _meli_auto_assign_lots_fifo() — helper del módulo meli_oerp_stock
             que divide el move en varios stock.move.line por lote (FIFO)
             cuando la reserva quedó incompleta por multi-lote.
          4. Si assign_lots_also_validate=True y el picking quedó "assigned" →
             button_validate() para cerrar la entrega.

        Solo se procesan pickings con meli_shipment_logistic_type == 'fulfillment'.
        Los pickings de otros tipos logísticos se reportan como "omitidos".
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        # Si el wizard fue abierto desde stock.picking directamente,
        # usamos los pickings activos en el contexto.
        pickings = self.env['stock.picking']
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        if active_model == 'stock.picking' and active_ids:
            pickings = self.env['stock.picking'].browse(active_ids)
        elif sale_orders:
            pickings = sale_orders.mapped('picking_ids')

        if not pickings:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron entregas (pickings) para procesar"
            )

        # Filtrar solo FULL no finalizados
        full_pickings = pickings.filtered(
            lambda p: (getattr(p, 'meli_shipment_logistic_type', '') or '') == 'fulfillment'
                      and p.state not in ('done', 'cancel')
        )
        skipped_non_full = len(pickings) - len(full_pickings)

        totals = {
            'pickings_ok': 0,
            'pickings_partial': 0,
            'pickings_skipped': 0,
            'moves_processed': 0,
            'lots_assigned': 0,
        }
        validated_count = 0
        errors = []

        for pick in full_pickings:
            try:
                with self.env.cr.savepoint():
                    # 1. Confirm + 2. assign estándar
                    if pick.state == 'draft':
                        pick.action_confirm()
                    if pick.state in ('confirmed', 'waiting', 'partially_available'):
                        pick.action_assign()

                    # 3. FIFO auto-assign
                    res = pick._meli_auto_assign_lots_fifo()
                    for k in totals:
                        totals[k] += res.get(k, 0)

                    # Sincronizar quantity_done con quantity reservada (Odoo 18)
                    if pick.move_line_ids:
                        for ml in pick.move_line_ids:
                            if ml.quantity == 0 and ml.quantity_product_uom:
                                ml.quantity = ml.quantity_product_uom

                    # 4. Validar si se pidió y el picking está listo
                    if self.assign_lots_also_validate and pick.state not in ('done', 'cancel'):
                        try:
                            pick.button_validate()
                            if pick.state == 'done':
                                validated_count += 1
                        except Exception as e:
                            # Típico: "se requiere lote para X" — reportar pero no romper
                            _logger.warning(
                                "assign_lots_full: validación falló para picking %s: %s",
                                pick.name, str(e)
                            )
                            errors.append("Picking %s (no validado): %s" % (pick.name, str(e)))

            except Exception as e:
                _logger.error("assign_lots_full: error procesando picking %s: %s",
                              pick.name, str(e))
                errors.append("Picking %s: %s" % (pick.name, str(e)))

        message_lines = [
            "Resultados FIFO para MELI FULL:",
            "  Pickings procesados: %d" % len(full_pickings),
            "  Pickings completos (auto-asignados): %d" % totals['pickings_ok'],
            "  Pickings parciales: %d" % totals['pickings_partial'],
            "  Moves procesados: %d" % totals['moves_processed'],
            "  Move.lines creadas: %d" % totals['lots_assigned'],
        ]
        if self.assign_lots_also_validate:
            message_lines.append("  Pickings validados (done): %d" % validated_count)
        if skipped_non_full:
            message_lines.append("  Omitidos (no FULL): %d" % skipped_non_full)

        message = "\n".join(message_lines)
        if errors:
            message += "\n\nIncidencias:\n" + "\n".join(errors[:15])
            if len(errors) > 15:
                message += "\n... y %d incidencias mas" % (len(errors) - 15)

        return warningobj.info(
            title='MELI INFO - Auto-asignacion FIFO (FULL)',
            message=message
        )

    def _action_adjust_payment_rounding(self):
        """
        Ajustar el redondeo de pagos existentes para que coincidan con
        el monto de la orden de venta o factura.
        Soporta Odoo 17, 18, 19 - maneja el caso de Argentina sin centavos.
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()
        meli_orders = self._get_meli_orders()

        if not sale_orders and not meli_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta ni ordenes de MercadoLibre"
            )

        adjusted_count = 0
        skipped_count = 0
        errors = []
        report_lines = []

        tolerance = self.rounding_tolerance or 1.0

        # Recopilar pagos de clientes relacionados con las ordenes
        for so in sale_orders:
            try:
                # Obtener el monto objetivo segun el modo
                if self.rounding_mode == 'to_sale_order':
                    target_amount = so.amount_total
                elif self.rounding_mode == 'to_invoice':
                    # Usar el monto de la primera factura posted
                    invoice = so.invoice_ids.filtered(lambda i: i.state == 'posted')[:1]
                    if invoice:
                        target_amount = invoice.amount_total
                    else:
                        report_lines.append("SO %s: no tiene factura posted, usando monto SO" % so.name)
                        target_amount = so.amount_total
                else:
                    # Solo redondear a entero
                    target_amount = None

                # Buscar pagos relacionados por referencia (ref en Odoo 17, memo en Odoo 18+)
                ref_field = self._get_payment_ref_field()
                payments = self.env['account.payment'].search([
                    (ref_field, 'ilike', so.name),
                    ('payment_type', '=', 'inbound'),
                    ('partner_type', '=', 'customer'),
                    ('state', 'in', ['draft', 'posted'])
                ])

                # Buscar por meli_order_id en memo (formato: "ML 2000010313988177 OP xxx TOT")
                if not payments and so.meli_order_id:
                    payments = self.env['account.payment'].search([
                        (ref_field, 'ilike', so.meli_order_id),
                        ('payment_type', '=', 'inbound'),
                        ('partner_type', '=', 'customer'),
                        ('state', 'in', ['draft', 'posted'])
                    ])

                # Tambien buscar pagos desde meli orders relacionadas
                for morder in meli_orders.filtered(lambda m: m.sale_order == so):
                    for meli_pay in morder.payments:
                        if meli_pay.account_payment_id and meli_pay.account_payment_id not in payments:
                            payments |= meli_pay.account_payment_id

                for pay in payments:
                    try:
                        original_amount = pay.amount
                        new_amount = original_amount
                        should_adjust = False

                        if self.rounding_mode == 'round_integer' or self.round_to_integer:
                            # Solo redondear a entero
                            rounded = round(original_amount)
                            if original_amount != rounded:
                                new_amount = rounded
                                should_adjust = True
                        elif target_amount:
                            # Ajustar al monto objetivo si la diferencia es pequenia
                            difference = abs(original_amount - target_amount)
                            if difference > 0 and difference < tolerance:
                                new_amount = target_amount
                                should_adjust = True

                            # Ademas redondear a entero si esta habilitado
                            if self.round_to_integer:
                                rounded = round(new_amount)
                                if new_amount != rounded:
                                    new_amount = rounded
                                    should_adjust = True

                        if should_adjust and new_amount != original_amount:
                            rounding_diff = original_amount - new_amount

                            # Si el pago esta posted, hay que pasarlo a draft primero
                            was_posted = pay.state == 'posted'
                            if was_posted:
                                try:
                                    pay.action_draft()
                                except Exception as e:
                                    errors.append("Pago %s: no se pudo pasar a draft: %s" % (pay.name, str(e)))
                                    continue

                            # Actualizar el monto
                            pay.write({
                                'amount': new_amount,
                                'meli_rounding_adjusted': True,
                                'meli_rounding_difference': rounding_diff,
                            })

                            # Re-postear si estaba posted
                            if was_posted:
                                try:
                                    pay.action_post()
                                except Exception as e:
                                    errors.append("Pago %s: ajustado pero no se pudo re-postear: %s" % (pay.name, str(e)))

                            adjusted_count += 1
                            report_lines.append("Ajustado %s: %.4f -> %.4f (diff: %.4f)" % (
                                pay.name, original_amount, new_amount, rounding_diff
                            ))
                        else:
                            skipped_count += 1

                    except Exception as e:
                        errors.append("Pago %s: %s" % (pay.name, str(e)))

            except Exception as e:
                _logger.error("Error ajustando pagos de SO %s: %s", so.name, str(e))
                errors.append("SO %s: %s" % (so.name, str(e)))

        # Construir mensaje de resultado
        message_parts = []
        message_parts.append("Modo: %s" % dict(self._fields['rounding_mode'].selection).get(self.rounding_mode))
        message_parts.append("Tolerancia: %.2f" % tolerance)
        message_parts.append("Redondear a entero: %s" % ("Si" if self.round_to_integer else "No"))
        message_parts.append("Pagos ajustados: %d" % adjusted_count)
        message_parts.append("Pagos sin cambios: %d" % skipped_count)

        message = "\n".join(message_parts)

        if report_lines:
            message += "\n\n--- Detalle ---\n" + "\n".join(report_lines[:30])
            if len(report_lines) > 30:
                message += "\n... y %d lineas mas" % (len(report_lines) - 30)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Ajuste de Redondeo de Pagos',
            message=message
        )

    def _action_adjust_order_rounding(self):
        """
        Ajustar el redondeo de ordenes de venta modificando el precio de una
        linea existente para que el total coincida con meli_paid_amount.
        Esto resuelve el problema de redondeo por calculo inverso de impuestos
        en Odoo con precision de 2 decimales.
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        adjusted_count = 0
        skipped_count = 0
        errors = []
        report_lines = []

        tolerance = self.rounding_tolerance or 1.0

        for so in sale_orders:
            try:
                # Skip if already adjusted
                if so.meli_rounding_adjusted:
                    skipped_count += 1
                    continue

                # Skip if no meli_paid_amount
                if not so.meli_paid_amount:
                    skipped_count += 1
                    report_lines.append("SO %s: sin meli_paid_amount" % so.name)
                    continue

                # Calculate expected amount
                expected_amount = so.meli_paid_amount - (so.meli_coupon_amount or 0.0)

                # Apply integer rounding if configured
                if self.round_to_integer:
                    expected_amount = round(expected_amount)

                # Calculate difference
                current_total = so.amount_total
                difference = expected_amount - current_total

                # Check if adjustment is needed
                if abs(difference) < 0.01:
                    skipped_count += 1
                    continue

                if abs(difference) >= tolerance:
                    report_lines.append(
                        "SO %s: diferencia %.4f excede tolerancia %.2f (esperado: %.2f, total: %.2f)" % (
                            so.name, difference, tolerance, expected_amount, current_total
                        )
                    )
                    skipped_count += 1
                    continue

                # Check if order state allows modification
                if so.state in ['done', 'cancel']:
                    report_lines.append("SO %s: estado %s no permite modificacion" % (so.name, so.state))
                    skipped_count += 1
                    continue

                # Find the first non-delivery product line to adjust
                line_to_adjust = None
                for line in so.order_line:
                    if not line.is_delivery and line.product_uom_qty > 0:
                        line_to_adjust = line
                        break

                if not line_to_adjust:
                    report_lines.append("SO %s: no hay linea de producto para ajustar" % so.name)
                    skipped_count += 1
                    continue

                # Calculate the tax multiplier for this line
                tax_multiplier = 1.0
                if line_to_adjust.tax_id:
                    for tax in line_to_adjust.tax_id:
                        if tax.amount_type == 'percent':
                            tax_multiplier += (tax.amount / 100.0)

                # Calculate price adjustment per unit
                qty = line_to_adjust.product_uom_qty
                price_adjustment = difference / (qty * tax_multiplier)

                # Store original price for logging
                original_price = line_to_adjust.price_unit
                new_price = original_price + price_adjustment

                # Update the line price
                line_to_adjust.write({
                    'price_unit': new_price,
                })

                # Mark as adjusted
                so.write({
                    'meli_rounding_adjusted': True,
                    'meli_rounding_difference': difference,
                })

                adjusted_count += 1
                report_lines.append(
                    "Ajustado SO %s [%s]: precio %.4f -> %.4f (diff total: %.4f)" % (
                        so.name, line_to_adjust.product_id.display_name,
                        original_price, new_price, difference
                    )
                )

            except Exception as e:
                _logger.error("Error ajustando redondeo de SO %s: %s", so.name, str(e))
                errors.append("SO %s: %s" % (so.name, str(e)))

        # Build result message
        message_parts = []
        message_parts.append("Tolerancia: %.2f" % tolerance)
        message_parts.append("Redondear a entero: %s" % ("Si" if self.round_to_integer else "No"))
        message_parts.append("Ordenes ajustadas: %d" % adjusted_count)
        message_parts.append("Ordenes sin cambios: %d" % skipped_count)

        message = "\n".join(message_parts)

        if report_lines:
            message += "\n\n--- Detalle ---\n" + "\n".join(report_lines[:30])
            if len(report_lines) > 30:
                message += "\n... y %d lineas mas" % (len(report_lines) - 30)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Ajuste de Redondeo de Ordenes',
            message=message
        )

    def _action_fix_coupon_payments(self):
        """
        Corregir pagos de ordenes con cupon.
        Cuando hay un cupon, el pago del cliente deberia ser igual al monto
        de la orden de venta (no restar el cupon). El cupon se trata como fee.

        Esta accion:
        1. Encuentra ordenes con cupon que tienen pagos con monto incorrecto
        2. Cancela el pago actual (revierte conciliacion si es necesario)
        3. Crea nuevo pago con el monto correcto (sale.order.amount_total)
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        fixed_count = 0
        skipped_count = 0
        errors = []
        report_lines = []

        for so in sale_orders:
            try:
                # Solo procesar ordenes con cupon
                coupon_amount = so.meli_coupon_amount or 0
                #diff = abs(total_amount - so.amount_total)>10
                #if coupon_amount <= 0:
                #    skipped_count += 1
                #    continue

                # El monto correcto es el total de la orden
                correct_amount = so.amount_total

                # Buscar pagos de cliente relacionados
                payments = self.env['account.payment'].search([
                    (acc_pay_ref, 'ilike', so.name),
                    ('payment_type', '=', 'inbound'),
                    ('partner_type', '=', 'customer'),
                    ('state', 'in', ['draft', 'posted'])
                ])
                _logger.info("_action_fix_coupon_payments > payments: "+str(payments))

                # Tambien buscar pagos desde meli orders
                for morder in so.meli_orders:
                    for meli_pay in morder.payments:
                        if meli_pay.account_payment_id and meli_pay.account_payment_id not in payments:
                            payments |= meli_pay.account_payment_id

                if not payments:
                    report_lines.append("SO %s: sin pagos encontrados (cupon: %.2f)" % (so.name, coupon_amount))
                    skipped_count += 1
                    continue

                for pay in payments:
                    try:
                        # Verificar si el pago tiene el monto incorrecto
                        # (el monto incorrecto seria sin el cupon, osea menor que el monto de la orden)
                        current_amount = pay.amount
                        difference = abs(current_amount - correct_amount)

                        # Si la diferencia es aproximadamente el monto del cupon, corregir
                        if difference <= 0.0:
                            # Ya tiene el monto correcto
                            report_lines.append("SO %s - Pago %s: ya tiene monto correcto %.2f" % (
                                so.name, pay.name, current_amount
                            ))
                            continue

                        #if abs(difference - coupon_amount) > 1.0:
                        #    # La diferencia no corresponde al cupon
                        #    report_lines.append("SO %s - Pago %s: diferencia %.2f no coincide con cupon %.2f" % (
                        #        so.name, pay.name, difference, coupon_amount
                        #    ))
                        #    continue

                        _logger.info("MELI: Fixing coupon payment %s: %.2f -> %.2f (coupon: %.2f)",
                                    pay.name, current_amount, correct_amount, coupon_amount)

                        # Guardar datos del pago original
                        original_ref = self._get_payment_ref(pay)
                        original_partner = pay.partner_id
                        original_journal = pay.journal_id
                        original_currency = pay.currency_id
                        original_date = pay.date
                        meli_payment_id = pay.meli_payment_id

                        # Si esta posted, revertir
                        if pay.state == 'posted':
                            try:
                                # Intentar revertir conciliacion primero
                                if hasattr(pay, 'reconciled_invoice_ids') and pay.reconciled_invoice_ids:
                                    # Buscar las lineas conciliadas y revertir
                                    for move_line in pay.line_ids.filtered(lambda l: l.account_id.reconcile):
                                        if move_line.matched_debit_ids or move_line.matched_credit_ids:
                                            move_line.remove_move_reconcile()

                                pay.action_draft()
                            except Exception as e:
                                errors.append("Pago %s: no se pudo pasar a draft: %s" % (pay.name, str(e)))
                                continue

                        # Cancelar el pago original
                        try:
                            pay.action_cancel()
                        except Exception as e:
                            errors.append("Pago %s: no se pudo cancelar: %s" % (pay.name, str(e)))
                            continue

                        # Crear nuevo pago con monto correcto
                        payment_method = self.env['account.payment.method'].search([
                            ('code', '=', 'inbound_online'),
                            ('payment_type', '=', 'inbound')
                        ], limit=1)
                        if not payment_method:
                            payment_method = self.env['account.payment.method'].search([
                                ('code', '=', 'electronic'),
                                ('payment_type', '=', 'inbound')
                            ], limit=1)
                        if not payment_method:
                            payment_method = self.env['account.payment.method'].search([
                                ('payment_type', '=', 'inbound')
                            ], limit=1)

                        new_ref = original_ref
                        if "(CORREGIDO)" not in new_ref:
                            new_ref = original_ref + " (CORREGIDO)"

                        # Usar el campo correcto para la referencia (ref en Odoo 17, memo en Odoo 18+)
                        ref_field_name = self._get_payment_ref_field()
                        # Compania del pago corregido = la del pago original (multi-empresa).
                        pay_company = pay.company_id or original_journal.company_id or self.env.company
                        new_pay_vals = {
                            'company_id': pay_company.id,
                            'partner_id': original_partner.id,
                            'payment_type': 'inbound',
                            'partner_type': 'customer',
                            'journal_id': original_journal.id,
                            'currency_id': original_currency.id,
                            'amount': correct_amount,
                            'date': original_date,
                            ref_field_name: new_ref,
                            'meli_rounding_adjusted': True,
                            'meli_rounding_difference': current_amount - correct_amount,
                        }

                        if payment_method:
                            new_pay_vals['payment_method_id'] = payment_method.id

                        if meli_payment_id:
                            new_pay_vals['meli_payment_id'] = meli_payment_id.id
                            # Actualizar referencia en mercadolibre.payments
                            meli_payment_id.write({'account_payment_id': False})

                        new_payment = self.env['account.payment'].with_company(pay_company).create(new_pay_vals)

                        # Vincular el nuevo pago al meli payment
                        if meli_payment_id:
                            meli_payment_id.write({'account_payment_id': new_payment.id})

                        # Validar el nuevo pago
                        try:
                            new_payment.action_post()
                        except Exception as e:
                            errors.append("Nuevo pago %s: no se pudo validar: %s" % (new_payment.name, str(e)))

                        fixed_count += 1
                        report_lines.append(
                            "SO %s: Pago %s (%.2f) -> %s (%.2f) [cupon: %.2f]" % (
                                so.name, pay.name, current_amount,
                                new_payment.name, correct_amount, coupon_amount
                            )
                        )

                    except Exception as e:
                        errors.append("Pago %s: %s" % (pay.name, str(e)))

            except Exception as e:
                _logger.error("Error corrigiendo pagos de SO %s: %s", so.name, str(e))
                errors.append("SO %s: %s" % (so.name, str(e)))

        # Build result message
        message_parts = []
        message_parts.append("Pagos corregidos: %d" % fixed_count)
        message_parts.append("Ordenes sin cupon o sin cambios: %d" % skipped_count)

        message = "\n".join(message_parts)

        if report_lines:
            message += "\n\n--- Detalle ---\n" + "\n".join(report_lines[:30])
            if len(report_lines) > 30:
                message += "\n... y %d lineas mas" % (len(report_lines) - 30)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Correccion de Pagos con Cupon',
            message=message
        )

    def _action_fix_reconciliation_rounding(self):
        """
        Corregir conciliaciones parciales por diferencia de centavos.

        Esta accion:
        1. Encuentra facturas con importe residual pequeno (< tolerancia)
        2. Rompe la conciliacion existente
        3. Si el pago tiene monto incorrecto, lo corrige
        4. Re-concilia usando meli_reconcile
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        fixed_count = 0
        skipped_count = 0
        errors = []
        report_lines = []

        tolerance = self.rounding_tolerance or 1.0
        ignore_tolerance = self.ignore_tolerance

        for so in sale_orders:
            try:
                # Buscar facturas posted de esta orden con residual
                if ignore_tolerance:
                    # Procesar cualquier factura con residual > 0
                    invoices = so.invoice_ids.filtered(
                        lambda i: i.state == 'posted'
                        and i.move_type == 'out_invoice'
                        and i.amount_residual > 0
                    )
                else:
                    # Solo facturas con residual pequeno (< tolerancia)
                    invoices = so.invoice_ids.filtered(
                        lambda i: i.state == 'posted'
                        and i.move_type == 'out_invoice'
                        and i.amount_residual > 0
                        and i.amount_residual < tolerance
                    )

                if not invoices:
                    skipped_count += 1
                    continue

                for invoice in invoices:
                    invoice_amount = invoice.amount_total
                    invoice_residual = invoice.amount_residual

                    _logger.info("MELI FIX: Procesando factura %s (total: %.2f, residual: %.2f)",
                                invoice.name, invoice_amount, invoice_residual)

                    try:
                        # PASO 1: Buscar el pago desde las lineas conciliadas
                        payment = None
                        invoice_receivable_lines = invoice.line_ids.filtered(
                            lambda l: l.account_id.reconcile
                        )

                        for inv_line in invoice_receivable_lines:
                            if hasattr(inv_line, 'matched_credit_ids'):
                                for partial in inv_line.matched_credit_ids:
                                    credit_line = getattr(partial, 'credit_move_id', None)
                                    if credit_line:
                                        # Intentar obtener payment_id del move
                                        if hasattr(credit_line.move_id, 'payment_id') and credit_line.move_id.payment_id:
                                            payment = credit_line.move_id.payment_id
                                            _logger.info("MELI FIX: Pago encontrado via move.payment_id: %s", payment.name)
                                            break
                                        # Si no, buscar account.payment que tenga este move_id
                                        else:
                                            payment = self.env['account.payment'].search([
                                                ('move_id', '=', credit_line.move_id.id)
                                            ], limit=1)
                                            if payment:
                                                _logger.info("MELI FIX: Pago encontrado via search move_id: %s", payment.name)
                                                break
                            if payment:
                                break

                        # PASO 2: Romper la conciliacion existente
                        _logger.info("MELI FIX: Rompiendo conciliacion de %d lineas de factura...", len(invoice_receivable_lines))
                        for inv_line in invoice_receivable_lines:
                            if inv_line.matched_credit_ids or inv_line.matched_debit_ids:
                                inv_line.remove_move_reconcile()

                        # Si ignore_tolerance, también romper TODAS las conciliaciones del pago
                        # (puede estar dividido entre varias facturas incorrectamente)
                        if ignore_tolerance and payment and payment.move_id:
                            payment_lines = payment.move_id.line_ids.filtered(lambda l: l.account_id.reconcile)
                            for pay_line in payment_lines:
                                if pay_line.matched_credit_ids or pay_line.matched_debit_ids:
                                    _logger.info("MELI FIX: Rompiendo conciliacion del pago %s...", payment.name)
                                    pay_line.remove_move_reconcile()

                        # PASO 3: Si encontramos el pago, verificar y corregir monto
                        payment_adjusted = False
                        if payment:
                            payment_amount = payment.amount
                            difference = abs(invoice_amount - payment_amount)
                            _logger.info("MELI FIX: Pago %s amount=%.2f, invoice=%.2f, diff=%.4f",
                                        payment.name, payment_amount, invoice_amount, difference)

                            # También verificar el monto en las líneas del asiento
                            move_amount = 0
                            if payment.move_id:
                                credit_line = payment.move_id.line_ids.filtered(
                                    lambda l: l.account_id.reconcile and l.credit > 0
                                )
                                if credit_line:
                                    move_amount = credit_line[0].credit
                                    _logger.info("MELI FIX: Monto en asiento (credit): %.2f", move_amount)

                            # Necesitamos ajustar si payment.amount o move_amount difieren de invoice
                            # Pero NO ajustar si ignore_tolerance=True (solo re-conciliar)
                            if ignore_tolerance:
                                needs_adjustment = False
                                _logger.info("MELI FIX: ignore_tolerance=True, no se ajusta el pago")
                            else:
                                needs_adjustment = (
                                    (difference > 0.001 and difference < tolerance) or
                                    (move_amount > 0 and abs(invoice_amount - move_amount) > 0.001 and abs(invoice_amount - move_amount) < tolerance)
                                )

                            if needs_adjustment:
                                _logger.info("MELI FIX: Ajustando pago %s: %.2f -> %.2f",
                                            payment.name, payment_amount, invoice_amount)

                                # Pasar a draft
                                payment.action_draft()

                                # Actualizar monto del pago
                                payment.write({'amount': invoice_amount})

                                # Si el asiento existe, actualizar sus líneas directamente
                                if payment.move_id:
                                    for line in payment.move_id.line_ids:
                                        if line.account_id.reconcile:
                                            if line.credit > 0:
                                                line.with_context(check_move_validity=False).write({
                                                    'credit': invoice_amount,
                                                    'amount_currency': -invoice_amount if line.amount_currency < 0 else invoice_amount
                                                })
                                            elif line.debit > 0:
                                                line.with_context(check_move_validity=False).write({
                                                    'debit': invoice_amount,
                                                    'amount_currency': invoice_amount if line.amount_currency > 0 else -invoice_amount
                                                })

                                # Re-postear
                                payment.action_post()
                                payment_adjusted = True

                        # PASO 4: Re-conciliar usando meli_reconcile
                        _logger.info("MELI FIX: Re-conciliando con meli_reconcile...")
                        if hasattr(so, 'meli_reconcile'):
                            so.meli_reconcile(invoice=invoice)

                        # Verificar resultado
                        invoice.invalidate_recordset(['amount_residual', 'payment_state'])
                        new_residual = invoice.amount_residual

                        # Si meli_reconcile no funciono, intentar conciliacion manual
                        if new_residual > 0 and payment:
                            _logger.info("MELI FIX: meli_reconcile no funciono, intentando conciliacion manual...")
                            payment.invalidate_recordset()

                            # En Odoo 18, las lineas estan en move_id.line_ids
                            payment_lines = payment.move_id.line_ids if payment.move_id else payment.line_ids if hasattr(payment, 'line_ids') else self.env['account.move.line']

                            # Buscar linea de credito del pago (cuenta por cobrar con credito)
                            payment_credit_line = payment_lines.filtered(
                                lambda l: l.account_id.reconcile and l.credit > 0 and not l.reconciled
                            )
                            # Buscar linea de debito de la factura (cuenta por cobrar con debito)
                            invoice_debit_line = invoice.line_ids.filtered(
                                lambda l: l.account_id.reconcile and l.debit > 0 and l.amount_residual > 0
                            )

                            _logger.info("MELI FIX: payment_credit_line=%s, invoice_debit_line=%s",
                                        payment_credit_line, invoice_debit_line)

                            if payment_credit_line and invoice_debit_line:
                                try:
                                    (payment_credit_line + invoice_debit_line).reconcile()
                                    invoice.invalidate_recordset(['amount_residual', 'payment_state'])
                                    new_residual = invoice.amount_residual
                                    _logger.info("MELI FIX: Conciliacion manual OK, nuevo residual: %.2f", new_residual)
                                except Exception as e:
                                    _logger.warning("MELI FIX: Error en conciliacion manual: %s", str(e))

                        if new_residual == 0:
                            msg = "Factura %s: Re-conciliada OK (residual: %.2f -> 0)" % (
                                invoice.name, invoice_residual
                            )
                            if payment_adjusted:
                                msg += " [Pago ajustado]"
                            report_lines.append(msg)
                            fixed_count += 1
                        else:
                            report_lines.append(
                                "Factura %s: Re-conciliada pero residual: %.2f" % (
                                    invoice.name, new_residual
                                )
                            )

                    except Exception as e:
                        _logger.error("Error procesando factura %s: %s", invoice.name, str(e))
                        errors.append("Factura %s: %s" % (invoice.name, str(e)))

            except Exception as e:
                _logger.error("Error procesando SO %s: %s", so.name, str(e))
                errors.append("SO %s: %s" % (so.name, str(e)))

        # Build result message
        message_parts = []
        if ignore_tolerance:
            message_parts.append("Modo: Forzar re-conciliacion (ignorar tolerancia)")
        else:
            message_parts.append("Tolerancia: %.2f" % tolerance)
        message_parts.append("Facturas corregidas y reconciliadas: %d" % fixed_count)
        message_parts.append("Facturas sin cambios: %d" % skipped_count)

        message = "\n".join(message_parts)

        if report_lines:
            message += "\n\n--- Detalle ---\n" + "\n".join(report_lines[:30])
            if len(report_lines) > 30:
                message += "\n... y %d lineas mas" % (len(report_lines) - 30)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... y %d errores mas" % (len(errors) - 10)

        return warningobj.info(
            title='MELI INFO - Correccion de Conciliacion (Centavos)',
            message=message
        )

    def _action_verify_amounts(self):
        """
        Verificar y corregir montos entre MercadoLibre, Orden de Venta y Factura.

        Compara:
        1. MeLi paid_amount vs SO amount_total
        2. SO amount_total vs Invoice amount_total

        Si hay diferencias, puede corregir la SO y/o la Factura.
        """
        warningobj = self.env['meli.warning']
        sale_orders = self._get_sale_orders()

        if not sale_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de venta"
            )

        report_lines = []
        errors = []
        mismatch_count = 0
        ok_count = 0

        tolerance = self.rounding_tolerance or 1.0

        for so in sale_orders:
            try:
                # Obtener la orden de MercadoLibre
                meli_orders = so.meli_orders if hasattr(so, 'meli_orders') else self.env['mercadolibre.orders']
                if not meli_orders and hasattr(so, 'meli_order_id') and so.meli_order_id:
                    meli_orders = so.meli_order_id

                if not meli_orders:
                    continue

                # Calcular el monto esperado de MeLi
                meli_expected = 0
                meli_paid = 0
                meli_coupon = 0
                meli_total = 0

                for morder in meli_orders:
                    # mercadolibre.orders usa paid_amount, coupon_amount, total_amount (sin prefijo meli_)
                    meli_paid += morder.paid_amount or 0
                    meli_coupon += morder.coupon_amount or 0
                    meli_total += morder.total_amount or 0

                    # Usar el metodo orders_update_sale_total si existe
                    if hasattr(morder, 'orders_update_sale_total'):
                        try:
                            meli_expected += morder.orders_update_sale_total() or 0
                        except:
                            meli_expected += (morder.paid_amount or 0) - (morder.coupon_amount or 0)
                    else:
                        meli_expected += (morder.paid_amount or 0) - (morder.coupon_amount or 0)

                so_total = so.amount_total

                # Comparar SO vs MeLi
                diff_so_meli = abs(so_total - meli_expected)

                # Obtener facturas
                invoices = so.invoice_ids.filtered(
                    lambda i: i.state == 'posted' and i.move_type == 'out_invoice'
                )
                invoice_total = sum(invoices.mapped('amount_total')) if invoices else 0

                # Comparar Invoice vs SO
                diff_inv_so = abs(invoice_total - so_total) if invoices else 0

                # Verificar diferencias
                has_mismatch = False
                details = []

                if diff_so_meli > tolerance:
                    has_mismatch = True
                    details.append("SO (%.2f) != MeLi (%.2f) [diff: %.2f]" % (so_total, meli_expected, diff_so_meli))

                if invoices and diff_inv_so > tolerance:
                    has_mismatch = True
                    details.append("Factura (%.2f) != SO (%.2f) [diff: %.2f]" % (invoice_total, so_total, diff_inv_so))

                if has_mismatch:
                    mismatch_count += 1
                    report_lines.append(
                        "%s: %s | MeLi paid=%.2f coupon=%.2f total=%.2f" % (
                            so.name,
                            " | ".join(details),
                            meli_paid, meli_coupon, meli_total
                        )
                    )
                else:
                    ok_count += 1

            except Exception as e:
                _logger.error("Error verificando SO %s: %s", so.name, str(e))
                errors.append("SO %s: %s" % (so.name, str(e)))

        # Build result message
        message_parts = []
        message_parts.append("Tolerancia: %.2f" % tolerance)
        message_parts.append("Ordenes OK: %d" % ok_count)
        message_parts.append("Ordenes con diferencias: %d" % mismatch_count)

        message = "\n".join(message_parts)

        if report_lines:
            message += "\n\n--- Diferencias Encontradas ---\n" + "\n".join(report_lines[:50])
            if len(report_lines) > 50:
                message += "\n... y %d lineas mas" % (len(report_lines) - 50)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors[:10])

        return warningobj.info(
            title='MELI INFO - Verificacion de Montos',
            message=message
        )

    def _action_force_to_draft(self):
        """
        Forzar facturas a estado borrador.

        Solo desconcilia las lineas de la factura y la pasa a borrador.
        NO cancela pagos automaticamente para evitar afectar otras conciliaciones.
        """
        warningobj = self.env['meli.warning']
        context = self.env.context
        active_model = context.get('active_model')
        active_ids = context.get('active_ids', [])

        # Solo funciona desde account.move
        if active_model != 'account.move':
            # Intentar obtener facturas desde sale.order
            sale_orders = self._get_sale_orders()
            if sale_orders:
                invoices = sale_orders.mapped('invoice_ids').filtered(
                    lambda i: i.state == 'posted'
                )
            else:
                return warningobj.info(
                    title='MELI WARNING',
                    message="Esta accion solo funciona desde facturas (account.move) o ordenes de venta con facturas"
                )
        else:
            invoices = self.env['account.move'].browse(active_ids).filtered(
                lambda i: i.state == 'posted'
            )

        if not invoices:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron facturas registradas (posted) para pasar a borrador"
            )

        results = []
        errors = []

        for invoice in invoices:
            invoice_name = invoice.name or str(invoice.id)
            try:
                with self.env.cr.savepoint():
                    # 1. Desconciliar SOLO las lineas de ESTA factura
                    # Filtramos solo las lineas de cuenta por cobrar/pagar que esten conciliadas
                    receivable_payable_lines = invoice.line_ids.filtered(
                        lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable') and l.reconciled
                    )
                    if receivable_payable_lines:
                        receivable_payable_lines.remove_move_reconcile()
                        results.append("%s: Desconciliado (%d lineas)" % (invoice_name, len(receivable_payable_lines)))

                    # 2. Pasar la factura a borrador
                    invoice.button_draft()
                    results.append("%s: Pasado a borrador OK" % invoice_name)

            except Exception as e:
                _logger.error("Error al pasar a borrador la factura %s: %s", invoice_name, str(e))
                errors.append("Factura %s: %s" % (invoice_name, str(e)))

        # Construir mensaje de resultado
        message = "Facturas procesadas: %d\n\n" % len(invoices)

        if results:
            message += "--- Acciones realizadas ---\n" + "\n".join(results)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors)

        return warningobj.info(
            title='MELI INFO - Forzar a Borrador',
            message=message
        )

    def _action_delete_invoice(self):
        """
        Eliminar facturas.

        Primero las pasa a borrador (desconciliando) y luego las elimina.
        ATENCION: Esta accion es irreversible.
        """
        warningobj = self.env['meli.warning']
        context = self.env.context
        active_model = context.get('active_model')
        active_ids = context.get('active_ids', [])

        # Solo funciona desde account.move
        if active_model != 'account.move':
            sale_orders = self._get_sale_orders()
            if sale_orders:
                invoices = sale_orders.mapped('invoice_ids')
            else:
                return warningobj.info(
                    title='MELI WARNING',
                    message="Esta accion solo funciona desde facturas (account.move) o ordenes de venta con facturas"
                )
        else:
            invoices = self.env['account.move'].browse(active_ids)

        if not invoices:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron facturas para eliminar"
            )

        results = []
        errors = []

        for invoice in invoices:
            invoice_name = invoice.name or str(invoice.id)
            try:
                with self.env.cr.savepoint():
                    # 1. Si esta posted, primero pasar a borrador
                    if invoice.state == 'posted':
                        # Desconciliar solo las lineas de cuenta por cobrar/pagar
                        receivable_payable_lines = invoice.line_ids.filtered(
                            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable') and l.reconciled
                        )
                        if receivable_payable_lines:
                            receivable_payable_lines.remove_move_reconcile()

                        invoice.button_draft()
                        results.append("%s: Pasado a borrador" % invoice_name)

                    # 2. Cancelar la factura (requerido antes de eliminar en algunos casos)
                    if invoice.state == 'draft':
                        invoice.button_cancel()
                        results.append("%s: Cancelado" % invoice_name)

                    # 3. Eliminar la factura
                    invoice.unlink()
                    results.append("%s: ELIMINADO" % invoice_name)

            except Exception as e:
                _logger.error("Error al eliminar la factura %s: %s", invoice_name, str(e))
                errors.append("Factura %s: %s" % (invoice_name, str(e)))

        # Construir mensaje de resultado
        message = "Facturas procesadas: %d\n\n" % len(invoices)

        if results:
            message += "--- Acciones realizadas ---\n" + "\n".join(results)

        if errors:
            message += "\n\n--- Errores ---\n" + "\n".join(errors)

        return warningobj.info(
            title='MELI INFO - Eliminar Factura',
            message=message
        )

    def _action_fix_invoice_status(self):
        """
        Corrige el estado de facturacion de las ordenes ML.
        Para cada factura asociada, fuerza qty_invoiced y invoice_status en las lineas de la orden.
        """
        warningobj = self.env['meli.warning']
        meli_orders = self._get_meli_orders()

        if not meli_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron ordenes de MercadoLibre para procesar"
            )

        fixed = 0
        errors = []

        for order in meli_orders:
            try:
                sale_order = order.sale_order
                if not sale_order:
                    continue

                invoices = sale_order.invoice_ids
                if not invoices:
                    continue

                for inv in invoices:
                    for iline in inv.invoice_line_ids:
                        so = iline.sale_line_ids.mapped('order_id')
                        if so:
                            for oli in so.order_line:
                                oli.qty_invoiced = oli.qty_to_invoice
                                oli.invoice_status = "invoiced"
                            so.invoice_status = "invoiced"

                fixed += 1
            except Exception as e:
                _logger.error("Error fix invoice status orden %s: %s", str(order.order_id), str(e))
                errors.append("Orden %s: %s" % (str(order.order_id), str(e)))

        message = "Ordenes procesadas: %d de %d\n" % (fixed, len(meli_orders))
        if errors:
            message += "\n--- Errores ---\n" + "\n".join(errors)

        return warningobj.info(
            title='MELI INFO - Fix Estado Facturacion',
            message=message
        )

    def _action_mark_for_batch_update(self):
        """Marca las órdenes ML seleccionadas para ser procesadas por el cron de batch update."""
        warningobj = self.env['meli.warning']
        meli_orders = self._get_meli_orders()

        if not meli_orders:
            return warningobj.info(
                title='MELI INFO',
                message="No se encontraron órdenes de MercadoLibre para marcar."
            )

        to_mark = meli_orders.filtered(lambda o: not o.meli_pending_batch_update)
        already = len(meli_orders) - len(to_mark)

        if to_mark:
            to_mark.write({'meli_pending_batch_update': True})

        total_pending = self.env['mercadolibre.orders'].search_count(
            [('meli_pending_batch_update', '=', True)]
        )

        msg = "Marcadas para actualización batch: %d órdenes" % len(to_mark)
        if already:
            msg += "\nYa estaban marcadas: %d" % already
        msg += "\n\nTotal en cola de cron: %d" % total_pending
        msg += "\n\nEl cron 'Meli Batch Update Marked Orders' procesará 20 por corrida."

        return warningobj.info(
            title='MELI INFO - Batch Update',
            message=msg
        )
