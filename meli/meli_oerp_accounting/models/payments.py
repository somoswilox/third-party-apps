from odoo import fields, models, api
from odoo.exceptions import ValidationError
from datetime import datetime
from odoo.addons.meli_oerp_accounting.models.versions import *
from odoo.addons.meli_oerp.models.versions import product_message_type
import logging
_logger = logging.getLogger(__name__)

class MeliPayment(models.Model):
    _inherit = 'mercadolibre.payments'

    def _get_config( self, config=None ):
        config = config or (self and self.order_id and self.order_id._get_config(config=config))
        #(self.order_id and self.order_id.company_id) or (self.order_id and self.order_id.sale_order and self.order_id.sale_order.company_id) or self.env.user.company_id
        return config

    def _get_ml_company_id( self, config=None ):
        #account_company_id = self.connection_account and self.connection_account.company_id and self.connection_account.company_id.id
        journal_id = self._get_ml_journal(config=config)
        journal_company_id = journal_id and journal_id.company_id and journal_id.company_id.id
        return journal_company_id

    def _get_ml_payment_company( self, config=None, journal_id=None ):
        """Compania del account.payment a crear.

        En multi-empresa el cron de importacion corre con su=True y SIN compania en el
        contexto -> account.payment.company_id quedaba NULL y violaba el NOT NULL de la
        tabla (las ordenes de las cuentas NO-principales -ECOMMARKET/DELTA- fallaban por
        completo, abortando la transaccion). La compania del pago DEBE coincidir con la
        del diario (account.payment._check_company). El diario se resuelve del config de
        la CUENTA (por-compania), por lo que su company es la correcta; ademas coincide
        con la de la orden. Fallbacks: compania de la orden, del config, del entorno.
        """
        so = self._get_ml_customer_order()
        company = (journal_id and journal_id.company_id) \
                  or (so and so.company_id) \
                  or (config and "company_id" in config._fields and config.company_id) \
                  or self.env.company
        return company

    def _get_ml_validate(self, config=None):
        if config and ("mercadolibre_payment_receipt_validation" in config._fields) and config.mercadolibre_payment_receipt_validation:
            if config.mercadolibre_payment_receipt_validation in ['validate','concile']:
                return True
        #default Borrador Draft
        return False


    def _get_ml_receiptbook( self, config=None, partner_type=None ):
        receiptbook_id = None
        company_id = self._get_ml_company_id(config=config)
        if partner_type=='supplier':
            receiptbook_id = config and "mercadolibre_account_payment_supplier_receiptbook_id" in config._fields and config.mercadolibre_account_payment_supplier_receiptbook_id
        else:
            partner_type='customer'
            receiptbook_id = config and "mercadolibre_account_payment_receiptbook_id" in config._fields and config.mercadolibre_account_payment_receiptbook_id

        if not receiptbook_id and partner_type:
            receiptbook_id = self.env["account.payment.receiptbook"].search([("partner_type",'=',partner_type),("company_id",'=',company_id)], limit=1)
        return receiptbook_id

    def _get_ml_journal(self, config=None):
        config = config or (self and self.order_id and self.order_id._get_config(config=config))
        journal_id = config and config.mercadolibre_process_payments_journal
        if not journal_id:
            journal_id = self.env['account.journal'].search([('code','=','ML')])
        if not journal_id:
            journal_id = self.env['account.journal'].search([('code','=','MP')])
        return journal_id

    def _get_ml_journal_shipment(self, config=None):
        config = config or (self and self.order_id and self.order_id._get_config(config=config))
        journal_id = config and "mercadolibre_process_payments_journal_shp" in config._fields and config.mercadolibre_process_payments_journal_shp
        #if not journal_id:
        #    journal_id = self.env['account.journal'].search([('code','=','ML')])
        #if not journal_id:
        #    journal_id = self.env['account.journal'].search([('code','=','MP')])
        return journal_id


    def _get_ml_partner(self, config=None):
        config = config or (self and self.order_id and self.order_id._get_config(config=config))
        partner_id = config and config.mercadolibre_process_payments_res_partner
        if not partner_id:
            partner_id = self.env['res.partner'].search([('ref','=','MELI')])
        if not partner_id:
            partner_id = self.env['res.partner'].search([('name','=','MercadoLibre')])
        return partner_id

    def _get_ml_partner_shipment(self, config=None):
        config = config or (self and self.order_id and self.order_id._get_config(config=config))
        partner_id = config and "mercadolibre_process_payments_res_partner_shp" in config._fields and config.mercadolibre_process_payments_res_partner_shp
        return partner_id

    def _get_ml_customer_partner(self):
        # Mode 3: pagos contra la entidad fiscal (partner_invoice_id),
        # no contra el buyer (partner_id). Esto permite que el pago
        # concilie con la factura emitida a la entidad fiscal.
        sale_order = self._get_ml_customer_order()
        return (sale_order and (sale_order.partner_invoice_id or sale_order.partner_id))

    def _get_ml_customer_order(self):
        mlorder = self.order_id
        mlshipment = mlorder.shipment
        return (mlorder and mlorder.sale_order) or (mlshipment and mlshipment.sale_order)

    def meli_amount_to_invoice(self, config=None, meli=None):
        total_config = (config and "mercadolibre_order_total_config" in config._fields) and config.mercadolibre_order_total_config
        including_shipping_cost = "mercadolibre_including_shipping_cost" in config._fields and config.mercadolibre_including_shipping_cost
        including_shipping_cost = including_shipping_cost or "always"

        if not config or not total_config:
            return self.transaction_amount;

        if total_config in ['manual']:
            #resolve always as conflict
            return 0

        if total_config in ['manual_conflict']:
            if abs(self.transaction_amount - self.total_paid_amount)<1.0:
                return self.total_paid_amount
            else:
                #conflict if do not match
                return 0

        if total_config in ['paid_amount']:
            #return self.total_paid_amount
            so = self._get_ml_customer_order()
            #return (so and so.meli_paid_amount) or (self.transaction_amount)
            if (self.total_paid_amount==self.transaction_amount):
                return self.total_paid_amount
            if (including_shipping_cost=="never"):
                return (self.transaction_amount)
            return self.total_paid_amount

        if total_config in ['transaction_amount']:
            return self.transaction_amount

        #without shipment amount
        if total_config in ['total_amount']:
            return self.transaction_amount

        return 0

    def create_payment( self, meli=None, config=None ):
        self.ensure_one()

        if not config:
            config = self._get_config(config=config)
            if not config:
                return None

        # Primera verificación rápida (ORM cache) antes de pedir el lock
        if self.account_payment_id:
            _logger.debug('create_payment: Ya esta creado el pago para %s', self.payment_id)
            return None
        if self.status != 'approved':
            return None

        # Lock a nivel DB para evitar pagos duplicados en ejecuciones concurrentes.
        # Si otro worker ya está creando el pago para este registro, NOWAIT lanza
        # una excepción que es capturada por el caller (confirm_ml) y loggeada.
        try:
            self.env.cr.execute(
                "SELECT account_payment_id FROM mercadolibre_payments WHERE id = %s FOR UPDATE NOWAIT",
                [self.id]
            )
            row = self.env.cr.fetchone()
            if row and row[0]:
                _logger.info(
                    'create_payment: Pago ya creado (verificado con lock DB) para %s — '
                    'account_payment_id=%s', self.payment_id, row[0]
                )
                # Sincronizar cache ORM con el valor real de DB
                self.invalidate_recordset(['account_payment_id'])
                return None
        except Exception as lock_err:
            _logger.warning(
                'create_payment: No se pudo adquirir lock para pago %s — '
                'otro proceso lo está creando concurrentemente: %s', self.payment_id, lock_err
            )
            return None

        # Anti-duplicación inter-pago: ML a veces genera dos operaciones de pago para la misma
        # meli.order (reintento, renegociación del pago). Solo crear account.payment para el
        # pago con el mayor payment_id numérico (el más reciente en ML).
        # IMPORTANTE: solo aplica cuando los montos son iguales (duplicado real).
        # Si los montos son diferentes, son pagos parciales legítimos y ambos deben crearse.
        if self.order_id:
            siblings_approved = self.order_id.payments.filtered(
                lambda p: p.id != self.id and p.status == 'approved'
            )
            if siblings_approved:
                try:
                    my_pid = int(self.payment_id or 0)
                    max_sibling_pid = max(int(p.payment_id or 0) for p in siblings_approved)
                except (ValueError, TypeError):
                    my_pid = max_sibling_pid = 0
                if my_pid < max_sibling_pid:
                    my_amount = self.transaction_amount or 0
                    sibling_max = next(
                        (p for p in siblings_approved
                         if int(p.payment_id or 0) == max_sibling_pid), None
                    )
                    sibling_amount = sibling_max.transaction_amount if sibling_max else 0
                    amounts_match = abs(my_amount - sibling_amount) < 1.0
                    if amounts_match:
                        _logger.warning(
                            'create_payment: ANTI-DUPLICADO — pago ML %s omitido para orden ML %s '
                            'porque existe un pago más reciente ML %s con mismo monto (%.2f ≈ %.2f).',
                            self.payment_id, self.order_id.name, max_sibling_pid,
                            my_amount, sibling_amount
                        )
                        return None
                    else:
                        _logger.info(
                            'create_payment: pagos parciales detectados — pago ML %s (%.2f) y '
                            'ML %s (%.2f) tienen montos diferentes, ambos se crean.',
                            self.payment_id, my_amount, max_sibling_pid, sibling_amount
                        )

        journal_id = self._get_ml_journal(config=config)
        payment_method_id = self.env['account.payment.method'].search([('code','=','inbound_online'),('payment_type','=','inbound')], limit=1)
        if not payment_method_id:
            payment_method_id = self.env['account.payment.method'].search([('code','=','electronic'),('payment_type','=','inbound')], limit=1)
        if not journal_id or not payment_method_id:
            _logger.warning('create_payment: Debe configurar el diario/metodo de pago para %s', self.payment_id)
            return None
        payment_company = self._get_ml_payment_company(config=config, journal_id=journal_id)
        partner_id = self._get_ml_customer_partner()
        currency_id = self.env['res.currency'].search([('name','=',self.currency_id)])
        if not currency_id:
            _logger.warning('create_payment: No se puede encontrar la moneda del pago %s', self.currency_id)
            return None

        communication = self.payment_id
        if self._get_ml_customer_order():
            communication = ""+str(self._get_ml_customer_order().name)+" OP "+str(self.payment_id)+str(" TOT")

        #total_amount = self.transaction_amount
        #TODO: using meli_amount_to_invoice to foreach item/order not from total
        #total_amount = self._get_ml_customer_order().meli_amount_to_invoice( meli=meli, config=config )
        total_amount = self.meli_amount_to_invoice( meli=meli, config=config )
        #self.total_paid_amount

        # Ajuste de monto: single-payment vs multi-payment
        # ─────────────────────────────────────────────────────────────────────
        # CASO ÚNICO: una sola meli.order por sale.order (o un solo pago aprobado).
        #   → Forzar total_amount = sale_order.amount_total para absorber cupones
        #     y diferencias de redondeo. Comportamiento original.
        #
        # CASO MÚLTIPLE: varias meli.orders agrupadas en la misma sale.order,
        #   cada una con su propio pago parcial.
        #   → Conservar el monto individual (transaction_amount) de cada pago.
        #   → Solo el ÚLTIMO pago en crearse se ajusta para que la SUMA de todos
        #     coincida exactamente con sale_order.amount_total.
        #   Esto evita que el segundo pago "parezca innecesario" porque el primero
        #   ya registró el monto total.
        # ─────────────────────────────────────────────────────────────────────
        rounding_adjusted = False
        rounding_difference = 0.0
        sale_order = self._get_ml_customer_order()

        # Configuracion de tolerancia de redondeo (por defecto 1.0)
        rounding_tolerance = 1.0
        if config and "mercadolibre_rounding_tolerance" in config._fields:
            rounding_tolerance = config.mercadolibre_rounding_tolerance or 1.0

        # Opcion de redondeo sin centavos (Argentina)
        round_to_integer = False
        if config and "mercadolibre_round_to_integer" in config._fields:
            round_to_integer = config.mercadolibre_round_to_integer

        if sale_order and sale_order.amount_total > 0:
            so_amount = sale_order.amount_total

            # IMPORTANTE: Si hay cupon, el pago del cliente debe ser igual al monto
            # de la orden de venta (no restar el cupon). El cupon se trata como fee.
            # Esto permite que el pago coincida con la factura para conciliacion.
            coupon_amount = sale_order.meli_discount_seller_amount or sale_order.meli_coupon_amount or 0

            # Detectar cuántos pagos aprobados existen para toda esta sale.order
            # (sumando todos sus meli.orders, no solo el order_id actual).
            all_approved_for_so = self.env['mercadolibre.payments']
            if sale_order.meli_orders:
                all_approved_for_so = self.search([
                    ('status', '=', 'approved'),
                    ('order_id', 'in', sale_order.meli_orders.ids),
                ])

            is_multi_payment = len(all_approved_for_so) > 1

            if not is_multi_payment:
                # ── Pago único: forzar al total de la orden ──────────────────
                # Maneja cupones (cupon_amount>0) y diferencias de redondeo
                # (abs(...)>0 cubre cualquier diferencia, no solo pequeñas).
                if coupon_amount > 0 or abs(total_amount - so_amount) > 0:
                    _logger.info(
                        "MELI single-payment adjustment: %.4f -> SO %.4f "
                        "(coupon: %.4f)",
                        total_amount, so_amount, coupon_amount
                    )
                    rounding_difference = total_amount - so_amount
                    total_amount = so_amount
                    rounding_adjusted = True
                else:
                    difference = abs(total_amount - so_amount)
                    if 0 < difference < rounding_tolerance:
                        _logger.info(
                            "MELI single-payment rounding: %.4f -> %.4f (diff: %.4f)",
                            total_amount, so_amount, difference
                        )
                        rounding_difference = total_amount - so_amount
                        total_amount = so_amount
                        rounding_adjusted = True

            else:
                # ── Múltiples pagos: conservar monto individual ───────────────
                # Calcular cuánto ya fue registrado por pagos anteriores
                # (que ya tienen account_payment_id creado).
                already_paid = sum(
                    p.account_payment_id.amount
                    for p in all_approved_for_so
                    if p.id != self.id
                    and p.account_payment_id
                    and p.account_payment_id.exists()
                )
                # ¿Quedan otros pagos pendientes de crear (además de este)?
                other_pending = all_approved_for_so.filtered(
                    lambda p: p.id != self.id
                    and (not p.account_payment_id or not p.account_payment_id.exists())
                )
                if not other_pending:
                    # Este es el ÚLTIMO pago: ajustarlo para cubrir el restante exacto.
                    remaining = so_amount - already_paid
                    if abs(remaining - total_amount) <= rounding_tolerance * 5 \
                            and abs(remaining - total_amount) > 0.001:
                        _logger.info(
                            "MELI multi-payment LAST adjustment: %.4f -> %.4f "
                            "(so_amount: %.4f, already_paid: %.4f)",
                            total_amount, remaining, so_amount, already_paid
                        )
                        rounding_difference = total_amount - remaining
                        total_amount = remaining
                        rounding_adjusted = True
                    else:
                        _logger.info(
                            "MELI multi-payment LAST (exact): payment %.4f, "
                            "remaining %.4f, so_amount %.4f",
                            total_amount, remaining, so_amount
                        )
                else:
                    # Hay más pagos pendientes: usar monto original sin ajustar.
                    _logger.info(
                        "MELI multi-payment: raw %.4f para pago ML %s "
                        "(SO total: %.4f, %d pagos más pendientes)",
                        total_amount, self.payment_id, so_amount, len(other_pending)
                    )

        # Redondear a entero si esta configurado (para Argentina donde no hay centavos)
        if round_to_integer:
            original = total_amount
            total_amount = round(total_amount)
            if original != total_amount:
                rounding_difference = original - total_amount
                rounding_adjusted = True
                _logger.info("MELI Integer rounding: %.4f -> %.0f", original, total_amount)

        vals_payment = {
                'company_id': payment_company.id,
                'partner_id': partner_id.id,
                'payment_type': 'inbound',
                'payment_method_id': payment_method_id.id,
                'journal_id': journal_id.id,
                'meli_payment_id': self.id,
                'currency_id': currency_id.id,
                'partner_type': 'customer',
                'amount': total_amount,
                'meli_rounding_adjusted': rounding_adjusted,
                'meli_rounding_difference': rounding_difference,
                }
        if "l10n_mx_edi.payment.method" in self.env:
            if "mercadolibre_customer_payment_method_id" in config._fields and config.mercadolibre_customer_payment_method_id:
                vals_payment["mercadolibre_customer_payment_method_id"] = config.mercadolibre_customer_payment_method_id.id

        # Setear la referencia/memo del pago en el campo que EXISTA en account.payment.
        # Standard Odoo 17 usa 'memo'; las instancias con Adhoc account_payment_pro (AR/CL/UY)
        # no tienen 'memo' → cae a 'ref'. Antes: escribir 'memo' inexistente abortaba el pago
        # (AR) y, al saltarlo, dejaba la referencia vacía en CL/UY. Ahora siempre va a un campo real.
        _pay_ref_field = next((f for f in (acc_pay_ref, 'memo', 'ref')
                               if f and f in self.env['account.payment']._fields), False)
        if _pay_ref_field:
            vals_payment[_pay_ref_field] = communication

        # Add withholding lines if l10n_account_withholding_tax is installed
        has_wth = 'is_withholding_tax_on_payment' in self.env['account.tax']._fields
        if has_wth and 'withholding_line_ids' in self.env['account.payment']._fields:
            wth_lines = self._prepare_withholding_lines(config=config)
            if wth_lines:
                vals_payment['should_withhold_tax'] = True
                vals_payment['withholding_line_ids'] = wth_lines
                _logger.info(
                    "MELI create_payment: %d withholding lines added for payment %s",
                    len(wth_lines), self.payment_id,
                )

        acct_payment_id = None

        if 'account.payment.group' in self.env:
            vals_group = {
                'company_id': payment_company.id,
                'receiptbook_id': (self._get_ml_receiptbook(config=config) and self._get_ml_receiptbook(config=config).id),
                'partner_id': partner_id.id,
                #'journal_id': journal_id.id,
                'currency_id': currency_id.id,
                'partner_type': 'customer',
                'payment_ids': [(0,0,vals_payment)]
            }
            if "payment_on_account_amount" in self.env['account.payment.group']._fields:
                vals_group["payment_on_account_amount"] = total_amount
            if acc_pay_group_ref in self.env['account.payment.group']._fields:
                vals_group[acc_pay_group_ref] = communication
            #_logger.info("create_payment group: "+str(vals_group))
            acct_payment_group_id = self.env['account.payment.group'].with_company(payment_company).create( vals_group )
            if acct_payment_group_id:
                acct_payment_id = acct_payment_group_id.payment_ids and acct_payment_group_id.payment_ids[0].id
                self.account_payment_id = acct_payment_id
                if "account_payment_group_id" in self._fields:
                    self.account_payment_group_id = acct_payment_group_id.id
                if (self._get_ml_validate(config=config)):
                    payment_group_post( acct_payment_group_id )

        else:
            #_logger.info("create_payment default: "+str(vals_payment))
            acct_payment_id = self.env['account.payment'].with_company(payment_company).create(vals_payment)
            self.account_payment_id = (acct_payment_id and acct_payment_id.id)
            if (self._get_ml_validate(config=config)):
                payment_post( acct_payment_id )

    def post_payment(self, config=None):
        config = config or self._get_config()
        if "account_payment_group_id" in self._fields and self.account_payment_group_id:
            if (self._get_ml_validate(config=config)):
                    payment_post_group( self.account_payment_group_id )

        if self.account_payment_id:
            if (self._get_ml_validate(config=config)):
                payment_post( self.account_payment_id )

    def create_supplier_payment(self, meli=None, config=None ):
        self.ensure_one()

        if not config:
            config = self._get_config(config=config)
            if not config:
                return None

        if self.status != 'approved':
            return None
        if self.account_supplier_payment_id:
            _logger.debug('create_supplier_payment: Ya esta creado el pago para %s', self.payment_id)
            return None
        journal_id = self._get_ml_journal(config=config)
        payment_method_id = self.env['account.payment.method'].search([('code','=','outbound_online'),('payment_type','=','outbound')], limit=1)
        if not payment_method_id:
            payment_method_id = self.env['account.payment.method'].search([('code','=','electronic'),('payment_type','=','outbound')], limit=1)

        if not journal_id or not payment_method_id:
            _logger.warning('create_supplier_payment: Debe configurar el diario/metodo de pago para %s', self.payment_id)
            return None
        payment_company = self._get_ml_payment_company(config=config, journal_id=journal_id)
        partner_id = self._get_ml_partner()
        if not partner_id:
            _logger.warning('create_supplier_payment: No esta dado de alta el proveedor MercadoLibre')
            return None
        currency_id = self.env['res.currency'].search([('name','=',self.currency_id)])
        if not currency_id:
            _logger.warning('create_supplier_payment: No se puede encontrar la moneda del pago %s', self.currency_id)
            return None

        communication = self.payment_id
        if self._get_ml_customer_order():
            communication = ""+str(self._get_ml_customer_order().name)+" OP "+str(self.payment_id)+str(" FEE")

        vals_payment = {
                'company_id': payment_company.id,
                'partner_id': partner_id.id,
                'payment_type': 'outbound',
                'payment_method_id': payment_method_id.id,
                'journal_id': journal_id.id,
                'meli_payment_id': self.id,
                'currency_id': currency_id.id,
                'partner_type': 'supplier',
                'amount': self.fee_amount,
                }

        if "l10n_mx_edi.payment.method" in self.env:
            if "mercadolibre_provider_payment_method_id" in config._fields and config.mercadolibre_provider_payment_method_id:
                vals_payment["mercadolibre_provider_payment_method_id"] = config.mercadolibre_provider_payment_method_id.id

        # Setear la referencia/memo del pago en el campo que EXISTA en account.payment.
        # Standard Odoo 17 usa 'memo'; las instancias con Adhoc account_payment_pro (AR/CL/UY)
        # no tienen 'memo' → cae a 'ref'. Antes: escribir 'memo' inexistente abortaba el pago
        # (AR) y, al saltarlo, dejaba la referencia vacía en CL/UY. Ahora siempre va a un campo real.
        _pay_ref_field = next((f for f in (acc_pay_ref, 'memo', 'ref')
                               if f and f in self.env['account.payment']._fields), False)
        if _pay_ref_field:
            vals_payment[_pay_ref_field] = communication
        acct_payment_id = None
        if 'account.payment.group' in self.env:
            vals_group = {
                'company_id': payment_company.id,
                'receiptbook_id': (self._get_ml_receiptbook(config=config,partner_type='supplier') and self._get_ml_receiptbook(config=config,partner_type='supplier').id),
                'partner_id': partner_id.id,
                #'journal_id': journal_id.id,
                'currency_id': currency_id.id,
                'partner_type': 'supplier',
                'payment_ids': [(0,0,vals_payment)]
            }
            if "payment_on_account_amount" in self.env['account.payment.group']._fields:
                vals_group["payment_on_account_amount"] = self.fee_amount
            if acc_pay_group_ref in self.env['account.payment.group']._fields:
                vals_group[acc_pay_group_ref] = communication
            #_logger.info("create_supplier_payment group: "+str(vals_group))
            acct_payment_group_id = self.env['account.payment.group'].with_company(payment_company).create( vals_group )
            if acct_payment_group_id:
                acct_payment_id = acct_payment_group_id.payment_ids and acct_payment_group_id.payment_ids[0].id
                self.account_supplier_payment_id = acct_payment_id
                if "account_supplier_group_payment_id" in self._fields:
                    self.account_supplier_group_payment_id = acct_payment_group_id.id
                if (self._get_ml_validate(config=config)):
                    payment_group_post( acct_payment_group_id )

        else:
            #_logger.info("create_supplier_payment default: "+str(vals_payment))
            acct_payment_id = self.env['account.payment'].with_company(payment_company).create(vals_payment)
            self.account_supplier_payment_id = (acct_payment_id and acct_payment_id.id)
            if (self._get_ml_validate(config=config)):
                payment_post( acct_payment_id )

    def post_supplier_payment(self, config=None):
        config = config or self._get_config()

        if "account_supplier_group_payment_id" in self._fields and self.account_supplier_group_payment_id:
            if (self._get_ml_validate(config=config)):
                    payment_post_group( self.account_supplier_group_payment_id )

        if self.account_supplier_payment_id:
            if (self._get_ml_validate(config=config)):
                payment_post( self.account_supplier_payment_id )

    def check_supplier_payment( self, config=None):
                            
        if self.account_supplier_payment_id:
            if (self._get_ml_validate(config=config)):
                if (self.fee_amount and self.account_supplier_payment_id.amount!=self.fee_amount):
                    if (self.account_supplier_payment_id.state in posted_statuses or
                       self.account_supplier_payment_id.state in cancel_statuses):
                        self.account_supplier_payment_id.action_draft()
                    self.account_supplier_payment_id.amount = self.fee_amount
                    payment_post( self.account_supplier_payment_id )

    def create_supplier_payment_shipment(self, meli=None, config=None ):
        self.ensure_one()
        #_logger.info("create_supplier_payment_shipment account_supplier_payment_shipment_id:"+str(self.account_supplier_payment_shipment_id))
        if not config:
            config = self._get_config(config=config)
            if not config:
                return None

        if self.status != 'approved':
            return None
        if self.account_supplier_payment_shipment_id:
            _logger.debug('create_supplier_payment_shipment: Ya esta creado el pago para %s', self.payment_id)
            return None
        journal_id = self._get_ml_journal_shipment(config=config)

        payment_method_out_id = self.env['account.payment.method'].search([('code','=','outbound_online'),('payment_type','=','outbound')], limit=1)
        if not payment_method_out_id:
            payment_method_out_id = self.env['account.payment.method'].search([('code','=','electronic'),('payment_type','=','outbound')], limit=1)
        if not payment_method_out_id:
            payment_method_out_id = self.env['account.payment.method'].search([('code','=','online'),('payment_type','=','outbound')], limit=1)

        if not journal_id or not payment_method_out_id:
            _logger.warning('create_supplier_payment_shipment: Debe configurar el diario/metodo de pago OUT para %s', self.payment_id)
            return None

        payment_method_in_id = self.env['account.payment.method'].search([('code','=','inbound_online'),('payment_type','=','inbound')], limit=1)
        if not payment_method_in_id:
            payment_method_in_id = self.env['account.payment.method'].search([('code','=','electronic'),('payment_type','=','inbound')], limit=1)
        if not journal_id or not payment_method_in_id:
            _logger.warning('create_supplier_payment_shipment: Debe configurar el diario/metodo de pago IN para %s', self.payment_id)
            return None

        payment_company = self._get_ml_payment_company(config=config, journal_id=journal_id)
        partner_id = self._get_ml_partner_shipment()
        if not partner_id:
            _logger.warning('create_supplier_payment_shipment: No esta dado de alta el proveedor de envio de MercadoLibre')
            return None

        customer_id = self._get_ml_customer_partner()
        if not customer_id:
            _logger.warning('create_supplier_payment_shipment: No esta dado de alta el cliente para %s', self.payment_id)
            return None

        currency_id = self.env['res.currency'].search([('name','=',self.currency_id)])
        if not currency_id:
            _logger.warning('create_supplier_payment_shipment: No se puede encontrar la moneda del pago %s', self.currency_id)
            return None
        if (not self.order_id or (not self.order_id.shipping_seller_cost>0.0 and not self.order_id.payments_shipment_amount>0.0)):
            # No shipping data is a normal case - return None instead of raising
            _logger.debug('create_supplier_payment_shipment: No hay datos de costo de envio para %s', self.payment_id)
            return None

        communication = self.payment_id
        so = self._get_ml_customer_order()
        mlorder = self.order_id
        mlshipment = mlorder and mlorder.shipment

        shipping_amount_out = False
        if so:
            communication = ""+str(self._get_ml_customer_order().name)+" OP "+str(self.payment_id)+str(" SHP")
            shipping_amount_out = self.shipping_amount or 0
            if (so.meli_shipping_seller_cost):
                shipping_amount_out = so.meli_shipping_seller_cost
        if not shipping_amount_out:
            # No shipping amount is a normal case - return None instead of raising
            _logger.debug('create_supplier_payment_shipment: No hay monto de costo de envio para %s', self.payment_id)
            return None
        vals_payment = {
                'company_id': payment_company.id,
                'partner_id': partner_id.id,
                'payment_type': 'outbound',
                #'payment_type': 'inbound',
                #'payment_method_id': payment_method_in_id.id,
                'payment_method_id': payment_method_out_id.id,
                'journal_id': journal_id.id,
                'meli_payment_id': self.id,
                'currency_id': currency_id.id,
                #'partner_type': 'customer',
                'partner_type': 'supplier',
                #'amount': self.order_id.shipping_list_cost,
                'amount': shipping_amount_out,
                }

        # Setear la referencia/memo del pago en el campo que EXISTA en account.payment.
        # Standard Odoo 17 usa 'memo'; las instancias con Adhoc account_payment_pro (AR/CL/UY)
        # no tienen 'memo' → cae a 'ref'. Antes: escribir 'memo' inexistente abortaba el pago
        # (AR) y, al saltarlo, dejaba la referencia vacía en CL/UY. Ahora siempre va a un campo real.
        _pay_ref_field = next((f for f in (acc_pay_ref, 'memo', 'ref')
                               if f and f in self.env['account.payment']._fields), False)
        if _pay_ref_field:
            vals_payment[_pay_ref_field] = communication
        acct_payment_id = None
        if 'account.payment.group' in self.env:
            vals_group = {
                'company_id': payment_company.id,
                'receiptbook_id': (self._get_ml_receiptbook(config=config) and self._get_ml_receiptbook(config=config).id),
                'partner_id': partner_id.id,
                #'journal_id': journal_id.id,
                'currency_id': currency_id.id,
                'partner_type': 'supplier',
                #'partner_type': 'customer',
                'payment_ids': [(0,0,vals_payment)]
            }
            if "payment_on_account_amount" in self.env['account.payment.group']._fields:
                vals_group["payment_on_account_amount"] = self.order_id.shipping_seller_cost
            if acc_pay_group_ref in self.env['account.payment.group']._fields:
                vals_group[acc_pay_group_ref] = communication
            #_logger.info("create_supplier_payment_shipment group: "+str(vals_group))
            acct_payment_group_id = self.env['account.payment.group'].with_company(payment_company).create( vals_group )
            if acct_payment_group_id:
                acct_payment_id = acct_payment_group_id.payment_ids and acct_payment_group_id.payment_ids[0].id
                self.account_supplier_payment_shipment_id = acct_payment_id
                if "account_supplier_group_payment_shipment_id" in self._fields:
                    self.account_supplier_group_payment_shipment_id = acct_payment_group_id.id
                if (self._get_ml_validate(config=config)):
                    payment_group_post( acct_payment_group_id )

        else:
            #_logger.info("create_supplier_payment_shipment default: "+str(vals_payment))
            acct_payment_id = self.env['account.payment'].with_company(payment_company).create(vals_payment)
            self.account_supplier_payment_shipment_id = (acct_payment_id and acct_payment_id.id)
            if (self._get_ml_validate(config=config)):
                payment_post( acct_payment_id )

    def post_supplier_payment_shipment(self, config=None):
        config = config or self._get_config()

        if "account_supplier_group_payment_shipment_id" in self._fields and self.account_supplier_group_payment_shipment_id:
            if (self._get_ml_validate(config=config)):
                    payment_post_group( self.account_supplier_group_payment_shipment_id )

        if self.account_supplier_payment_shipment_id:
            if (self._get_ml_validate(config=config)):
                payment_post( self.account_supplier_payment_shipment_id )

    def _cancel_one_payment(self, payment):
        """Cancelar un account.payment respetando posted/cancel statuses."""
        if not payment:
            return

        if payment.state in cancel_statuses:
            return

        _logger.info("MELI cancel payment: %s (state: %s)", payment.display_name, payment.state)

        # Intentar usar helper abstracto si existe
        try:
            payment_cancel(payment)
            return
        except Exception as e:
            _logger.warning("payment_cancel fallo, fallback a acciones nativas: %s", e)

        # Fallback genérico Odoo
        if payment.state in posted_statuses:
            # Odoo 19: Primero pasar move_id a borrador
            if hasattr(payment, 'move_id') and payment.move_id:
                try:
                    if payment.move_id.state == 'posted':
                        payment.move_id.button_draft()
                except Exception as e:
                    _logger.warning("button_draft en move_id fallo: %s", e)

            # Luego pasar el payment a borrador
            try:
                payment.action_draft()
            except Exception as e:
                _logger.warning("action_draft en payment fallo: %s", e)

        # Ahora intentar cancelar
        if hasattr(payment, 'action_cancel'):
            try:
                payment.action_cancel()
            except Exception as e:
                _logger.warning("action_cancel en payment fallo: %s", e)
                # Último recurso: intentar cancelar directamente el move
                if hasattr(payment, 'move_id') and payment.move_id:
                    try:
                        if payment.move_id.state == 'draft':
                            payment.move_id.button_cancel()
                    except Exception as e2:
                        _logger.warning("button_cancel en move_id fallo: %s", e2)
        else:
            # Último recurso, no ideal, pero evita que quede 'posted'
            payment.state = 'cancelled'

    def _cancel_one_payment_group(self, payment_group):
        """Cancelar un account.payment.group si está posteado."""
        if not payment_group:
            return

        if payment_group.state in cancel_statuses:
            return

        _logger.info(
            "MELI cancel payment group: %s (state: %s)",
            payment_group.display_name, payment_group.state
        )

        # Intentar helper abstracto
        try:
            payment_group_cancel(payment_group)
            return
        except Exception as e:
            _logger.warning("payment_group_cancel fallo, fallback a acciones nativas: %s", e)

        # Fallback genérico Odoo
        if payment_group.state in posted_statuses:
            # Odoo 19: Primero pasar move_ids de los payments a borrador
            if hasattr(payment_group, 'payment_ids'):
                for payment in payment_group.payment_ids:
                    if hasattr(payment, 'move_id') and payment.move_id:
                        try:
                            if payment.move_id.state == 'posted':
                                payment.move_id.button_draft()
                        except Exception as e:
                            _logger.warning("button_draft en move_id (group) fallo: %s", e)

            try:
                payment_group.action_draft()
            except Exception as e:
                _logger.warning("action_draft en payment_group fallo: %s", e)

        if hasattr(payment_group, 'action_cancel'):
            try:
                payment_group.action_cancel()
            except Exception as e:
                _logger.warning("action_cancel en payment_group fallo: %s", e)
        else:
            payment_group.state = 'cancelled'

    def republish_invoice_payments(self, meli=None, config=None):
        """
        Re-publicar pagos de cliente cuando la factura fue creada manualmente
        a una razón social (partner) diferente del partner original del pago.

        Solo actúa si:
        - Existe un pago de cliente (account_payment_id)
        - Existe al menos una factura posted/draft en la orden de venta
        - El partner de la factura difiere del partner del pago

        Proceso:
        1. Cancela el pago existente
        2. Limpia la referencia al pago
        3. Recrea el pago con el partner de la factura
        """
        for pay in self:
            if not pay.account_payment_id:
                continue

            if pay.status != 'approved':
                continue

            sale_order = pay._get_ml_customer_order()
            if not sale_order:
                continue

            # Buscar facturas de la orden de venta
            invoices = sale_order.invoice_ids.filtered(
                lambda i: i.move_type == 'out_invoice' and i.state not in cancel_statuses
            )
            if not invoices:
                continue

            # Tomar el partner de la primera factura válida
            invoice_partner = invoices[0].partner_id
            payment_partner = pay.account_payment_id.partner_id

            # Comparar usando commercial_partner_id para manejar hijos de facturación
            invoice_commercial = invoice_partner.commercial_partner_id or invoice_partner
            payment_commercial = payment_partner.commercial_partner_id or payment_partner

            if invoice_commercial.id == payment_commercial.id:
                # El pago ya está al partner correcto
                continue

            _logger.info(
                "MELI republish_invoice_payments: pago %s (partner %s [id:%s]) -> factura %s (partner %s [id:%s])",
                pay.payment_id,
                payment_partner.name, payment_partner.id,
                invoices[0].name,
                invoice_partner.name, invoice_partner.id
            )

            # Actualizar el partner_invoice_id de la orden de venta
            # para que futuros pagos/reconciliaciones usen el partner correcto
            if sale_order.partner_invoice_id != invoice_partner:
                sale_order.partner_invoice_id = invoice_partner
                _logger.info(
                    "MELI republish_invoice_payments: actualizado partner_invoice_id de SO %s a %s [id:%s]",
                    sale_order.name, invoice_partner.name, invoice_partner.id
                )

            # 1. Cancelar pago existente
            old_payment = pay.account_payment_id
            old_payment_group = None
            if 'account_payment_group_id' in pay._fields and pay.account_payment_group_id:
                old_payment_group = pay.account_payment_group_id

            if old_payment_group:
                pay._cancel_one_payment_group(old_payment_group)
                pay.account_payment_group_id = False
            else:
                pay._cancel_one_payment(old_payment)

            # 2. Limpiar referencia al pago viejo
            pay.account_payment_id = False

            # 3. Recrear pago con el partner correcto de la factura
            pay.create_payment(meli=meli, config=config)

            if pay.account_payment_id:
                _logger.info(
                    "MELI republish_invoice_payments: nuevo pago creado %s para partner %s [id:%s]",
                    pay.account_payment_id.id,
                    pay.account_payment_id.partner_id.name,
                    pay.account_payment_id.partner_id.id
                )
                so = pay._get_ml_customer_order()
                if so:
                    so.message_post(
                        body="Pago republicado: partner actualizado de '%s' a '%s' para coincidir con la factura %s" % (
                            payment_partner.name,
                            invoice_partner.name,
                            invoices[0].name or ''
                        ),
                        message_type=product_message_type
                    )
            else:
                _logger.warning(
                    "MELI republish_invoice_payments: no se pudo recrear el pago para %s",
                    pay.payment_id
                )

    def cancel_payments(self, config=None):
        """
        Cancelar TODOS los pagos relacionados (cliente, proveedor, envíos)
        aunque el pedido/factura de Odoo todavía no estén cancelados.
        Se asume que la orden/pago en MercadoLibre ya está cancelado/refundado.
        """
        config = config or self._get_config(config=config)

        for pay in self:
            _logger.info("MercadoLibre cancel_payments for MELI payment %s (status: %s)",
                         pay.payment_id, pay.status)

            # 1) Payment groups (cliente/proveedor/envío) si existen en el modelo
            if 'account_payment_group_id' in pay._fields and pay.account_payment_group_id:
                self._cancel_one_payment_group(pay.account_payment_group_id)

            if 'account_supplier_group_payment_id' in pay._fields and pay.account_supplier_group_payment_id:
                self._cancel_one_payment_group(pay.account_supplier_group_payment_id)

            if 'account_supplier_group_payment_shipment_id' in pay._fields and pay.account_supplier_group_payment_shipment_id:
                self._cancel_one_payment_group(pay.account_supplier_group_payment_shipment_id)

            # 2) Pagos individuales
            if pay.account_payment_id:
                self._cancel_one_payment(pay.account_payment_id)

            if pay.account_supplier_payment_id:
                self._cancel_one_payment(pay.account_supplier_payment_id)

            if pay.account_supplier_payment_shipment_id:
                self._cancel_one_payment(pay.account_supplier_payment_shipment_id)


    account_payment_id = fields.Many2one('account.payment',string='Pago')
    account_supplier_payment_id = fields.Many2one('account.payment',string='Pago a Proveedor')
    account_supplier_payment_shipment_id = fields.Many2one('account.payment',string='Pago Envio a Proveedor')

    # --- Cargos / retenciones de MercadoPago ---
    charge_ids = fields.One2many(
        'mercadolibre.payment.charge', 'payment_id',
        string='Cargos MercadoPago',
        help='Detalle de cargos (charges_details) del pago de MercadoPago: retenciones ISR/IVA, comisiones, envío, etc.',
    )
    tax_withholding_amount = fields.Float(
        string='Total retenciones',
        compute='_compute_tax_amounts',
        store=True,
        digits=(16, 2),
        help='Suma de cargos tipo tax (retenciones ISR, IVA, etc.)',
    )
    fee_charges_amount = fields.Float(
        string='Total comisiones (charges)',
        compute='_compute_tax_amounts',
        store=True,
        digits=(16, 2),
        help='Suma de cargos tipo fee desde charges_details',
    )
    shipping_charges_amount = fields.Float(
        string='Total envío (charges)',
        compute='_compute_tax_amounts',
        store=True,
        digits=(16, 2),
        help='Suma de cargos tipo shipping desde charges_details',
    )
    net_received_amount = fields.Float(
        string='Monto neto recibido',
        digits=(16, 2),
        help='transaction_details.net_received_amount del JSON de MercadoPago',
    )

    def _prepare_withholding_lines(self, config=None):
        """
        Prepare withholding_line_ids commands for account.payment creation.
        Uses charge_ids from MercadoPago to find retention taxes that have
        is_withholding_tax_on_payment=True on their mapped account.tax.
        Returns list of (0, 0, vals) commands or empty list.
        """
        commands = []
        company = self.env.company
        wth_account = company.withholding_tax_base_account_id if 'withholding_tax_base_account_id' in company._fields else None

        for charge in self.charge_ids:
            if charge.charge_type != 'tax':
                continue
            rule = charge.meli_tax_id
            if not rule or rule.state != 'confirmed' or not rule.account_tax_id:
                rule = self.env['mercadolibre.tax'].match_charge(
                    charge.charge_type, charge.name,
                    {'mov_financial_entity': charge.mov_financial_entity or '',
                     'source_detail': charge.source_detail or ''},
                )
            if not rule or rule.state != 'confirmed' or not rule.account_tax_id:
                continue
            tax = rule.account_tax_id
            if not tax.is_withholding_tax_on_payment:
                continue

            base = float(charge.base_amount or 0)
            amount = float(charge.amount_original or 0)
            if amount <= 0:
                continue

            line_account = wth_account
            if not line_account:
                tax_rep = tax.invoice_repartition_line_ids.filtered(
                    lambda l: l.repartition_type == 'tax' and l.account_id
                )
                line_account = tax_rep[0].account_id if tax_rep else None
            if not line_account:
                _logger.warning(
                    "MELI withholding: no account found for tax '%s' — configure "
                    "withholding_tax_base_account_id in company settings or set an "
                    "account on the tax repartition lines. Skipping.",
                    tax.name,
                )
                continue

            vals = {
                'tax_id': tax.id,
                'base_amount': base,
                'amount': amount,
                'account_id': line_account.id,
            }

            commands.append((0, 0, vals))
            _logger.info(
                "MELI withholding: tax=%s base=%.2f amount=%.2f account=%s for payment %s",
                tax.name, base, amount, line_account.display_name, self.payment_id,
            )

        return commands

    def _patch_withholding_on_existing_payment(self, config=None):
        """
        Patch withholding lines onto an existing account.payment that was
        created before the withholding integration.  Idempotent: skips if
        the payment already has withholding lines or if no lines are needed.
        Called from confirm_ml on every refresh so existing orders get fixed.
        """
        self.ensure_one()

        has_wth = 'is_withholding_tax_on_payment' in self.env['account.tax']._fields
        if not has_wth or 'withholding_line_ids' not in self.env['account.payment']._fields:
            return

        acct_pay = self.account_payment_id
        if not acct_pay or not acct_pay.exists():
            return

        if acct_pay.withholding_line_ids:
            return

        wth_lines = self._prepare_withholding_lines(config=config)
        if not wth_lines:
            return

        _logger.info(
            "MELI _patch_withholding: adding %d withholding lines to payment %s (state=%s)",
            len(wth_lines), acct_pay.name or acct_pay.id, acct_pay.state,
        )

        was_posted = acct_pay.state in posted_statuses

        try:
            if was_posted:
                if hasattr(acct_pay, 'move_id') and acct_pay.move_id:
                    reconciled_lines = acct_pay.move_id.line_ids.filtered(
                        lambda l: l.account_id.reconcile and l.reconciled
                    )
                    if reconciled_lines:
                        reconciled_lines.remove_move_reconcile()
                acct_pay.action_draft()

            acct_pay.write({
                'should_withhold_tax': True,
                'withholding_line_ids': wth_lines,
            })

            if was_posted:
                payment_post(acct_pay)

            _logger.info(
                "MELI _patch_withholding: patched payment %s with %d withholding lines",
                acct_pay.name or acct_pay.id, len(wth_lines),
            )
        except Exception as e:
            _logger.warning(
                "MELI _patch_withholding: failed to patch payment %s: %s",
                acct_pay.name or acct_pay.id, e, exc_info=True,
            )

    @api.depends('charge_ids', 'charge_ids.amount_original', 'charge_ids.charge_type')
    def _compute_tax_amounts(self):
        for rec in self:
            tax_total = 0.0
            fee_total = 0.0
            shp_total = 0.0
            for charge in rec.charge_ids:
                if charge.charge_type == 'tax':
                    tax_total += charge.amount_original
                elif charge.charge_type == 'fee':
                    fee_total += charge.amount_original
                elif charge.charge_type == 'shipping':
                    shp_total += charge.amount_original
            rec.tax_withholding_amount = tax_total
            rec.fee_charges_amount = fee_total
            rec.shipping_charges_amount = shp_total

    def sync_charges_from_json(self, full_payment=None):
        """
        Sincroniza charges_details del JSON de MercadoPago al modelo mercadolibre.payment.charge.
        Llama a este método después de obtener el full_payment de la API.

        :param full_payment: dict con el JSON completo del pago de MercadoPago
        """
        self.ensure_one()
        if not full_payment:
            # Intentar parsear desde el campo full_payment almacenado
            if self.full_payment:
                import json, ast
                raw = self.full_payment
                # El campo se guarda como str(dict) de Python, no como JSON válido
                try:
                    full_payment = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    try:
                        full_payment = ast.literal_eval(raw)
                    except (ValueError, SyntaxError) as e:
                        _logger.warning("MELI sync_charges: cannot parse full_payment for payment %s: %s", self.payment_id, e)
                        return

        if not full_payment:
            return

        charges_details = full_payment.get("charges_details") or []
        if not charges_details:
            return

        # Obtener IDs de cargos ya registrados para este pago
        existing_charge_ids = {c.charge_id for c in self.charge_ids if c.charge_id}

        ChargeModel = self.env["mercadolibre.payment.charge"]

        for charge_detail in charges_details:
            charge_id = charge_detail.get("id", "")
            if charge_id and charge_id in existing_charge_ids:
                continue
            ChargeModel.create_from_charge_detail(self, charge_detail)

        # Actualizar net_received_amount
        transaction_details = full_payment.get("transaction_details") or {}
        net_received = transaction_details.get("net_received_amount", 0)
        if net_received:
            self.net_received_amount = net_received

    def button_import_taxes(self):
        """Botón para importar/sincronizar cargos desde el JSON de MercadoPago almacenado."""
        for payment in self:
            payment.sync_charges_from_json()
        # Mostrar notificación
        if len(self) == 1 and self.charge_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Importación completada',
                    'message': '%d cargos importados para pago %s' % (len(self.charge_ids), self.payment_id),
                    'type': 'success',
                    'sticky': False,
                }
            }

    #account_payment_group_id = fields.Many2one('account.payment.group',string='Pago agrupado')
    #account_supplier_group_payment_id = fields.Many2one('account.payment.group',string='Pago agrupado a Proveedor')
    #account_supplier_group_payment_shipment_id = fields.Many2one('account.payment.group',string='Pago agrupado Envio a Proveedor')


class AccountPayment(models.Model):

    _inherit = 'account.payment'

    meli_payment_id = fields.Many2one('mercadolibre.payments',string='Pago de MP')
    meli_rounding_adjusted = fields.Boolean(
        string='Ajuste de Redondeo ML',
        default=False,
        help='Indica que este pago tuvo un ajuste de redondeo para coincidir con el monto de la orden de venta'
    )
    meli_rounding_difference = fields.Float(
        string='Diferencia de Redondeo',
        digits=(16, 4),
        default=0.0,
        help='Diferencia en centavos/decimales que se ajusto'
    )

class AccountPaymentMethod(models.Model):
    _inherit = 'account.payment.method'

    @api.model
    def _get_payment_method_information(self):
        res = super()._get_payment_method_information()
        res['outbound_online'] = {'mode': 'multi', 'domain': [('type', '=', 'bank')]}
        #res['electronic'] = {'mode': 'multi', 'domain': [('type', '=', 'bank')]}
        res['inbound_online'] = {'mode': 'multi', 'domain': [('type', '=', 'bank')]}
        return res
