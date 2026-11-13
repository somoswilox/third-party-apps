from odoo import fields, models, api
from odoo.exceptions import ValidationError, UserError
import re
from odoo.tools import float_compare
from datetime import datetime
from odoo.addons.meli_oerp_accounting.models.versions import *
from odoo.addons.meli_oerp.models.versions import product_message_type, meli_message_post, meli_payment_method_line_for, meli_money_block_post
try:  # [26.361] viaja en el mismo release de meli_oerp; si falta, sin fallback desde el JSON
    from odoo.addons.meli_oerp.models.versions import meli_payment_commission_from_json
except ImportError:  # pragma: no cover
    meli_payment_commission_from_json = None
from odoo.addons.meli_oerp_accounting.models import meli_receipt
import logging
_logger = logging.getLogger(__name__)


class MeliRepublishPaymentError(Exception):
    """Corta la republicacion de un cobro para que el savepoint revierta el cancelado.

    No es un error de usuario: nunca sale a la interfaz. Existe porque create_payment()
    puede volver sin crear nada y sin lanzar, y sin excepcion el savepoint confirmaria
    el borrado del recibo anterior (un cliente).
    """

class MeliPayment(models.Model):
    _inherit = 'mercadolibre.payments'

    @api.model
    def _meli_payment_recency_key(self, payments):
        """Clave para ordenar pagos ML del mas viejo al mas reciente (anti-duplicado).

        Brasil D (26.314): si TODOS los payment_id son numericos se usa int(payment_id), igual que
        siempre (AR/MX no cambian). Si alguno no es numerico (Mercado Livre Brasil ya devuelve IDs
        alfanumericos), int() fallaba y el anti-duplicado quedaba apagado en silencio: ahi se ordena
        por date_created y se desempata por el ID como texto.
        """
        try:
            for p in payments:
                int(p.payment_id or 0)
            return lambda p: int(p.payment_id or 0)
        except (ValueError, TypeError):
            return lambda p: (p.date_created or datetime.min, str(p.payment_id or ''))

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

    # ------------------------------------------------------------------ #
    #  [#caso-K15 26.305] Monto del cobro de cada pago ML, relativo a la venta   #
    # ------------------------------------------------------------------ #
    def _meli_payment_tolerance(self, config=None):
        tol = 1.0
        if config and "mercadolibre_rounding_tolerance" in config._fields:
            tol = config.mercadolibre_rounding_tolerance or 1.0
        return tol

    def _meli_so_approved_payments(self, sale_order):
        """Pagos ML aprobados de TODAS las ordenes ML de la venta (pack incluido)."""
        Pay = self.env['mercadolibre.payments']
        if not sale_order or not sale_order.meli_orders:
            return Pay
        return Pay.search([('status', '=', 'approved'), ('order_id', 'in', sale_order.meli_orders.ids)])

    def _meli_payment_amount_plan(self, sale_order, config=None, meli=None):
        """(lectura, {id pago ML: monto}) si alguna lectura de los pagos ML aprobados de la venta
        SUMA el total de la venta (+-tolerancia); None si ninguna cierra.

        [#caso-K15 cliente E, 25-oct-2026] Antes cada pago se registraba por `meli_amount_to_invoice`
        (con 'paid_amount' = total_paid_amount, lo que puso el COMPRADOR) y solo el pago
        UNICO se forzaba al total de la venta. Con un cupon financiado por ML y un segundo
        pago (payment_addition del envio) la venta queda facturada por lo cobrado en ML
        (transaction_amount, que incluye el cupon) y los cobros sumaban total_paid: la
        factura quedaba con saldo = cupon (ML 2000515085472444: 227.200 + 6.000 contra
        258.200). Lecturas, en orden:
          1. el monto base de cada pago (meli_amount_to_invoice): lo de siempre;
          2. transaction_amount: incluye el cupon que paga ML (el vendedor lo cobra igual,
             net_received_amount no lo descuenta).
        La que cierra contra la venta es la que se registra. Sin red."""
        if not sale_order or not (sale_order.amount_total or 0.0) > 0:
            return None
        approved = self._meli_so_approved_payments(sale_order)
        if not approved:
            return None
        tol = self._meli_payment_tolerance(config)
        so_amount = sale_order.amount_total
        readings = []
        try:
            readings.append(('base', {p.id: float(p.meli_amount_to_invoice(meli=meli, config=config) or 0.0)
                                      for p in approved}))
        except Exception as e:
            _logger.info("create_payment plan: lectura base no disponible (%s)", e)
        readings.append(('transaction_amount', {p.id: float(p.transaction_amount or 0.0) for p in approved}))
        for name, amounts in readings:
            if abs(sum(amounts.values()) - so_amount) <= tol:
                return name, amounts
        return None

    def _meli_payment_amount_for_so(self, sale_order, total_amount, plan=None, config=None):
        """(monto, ajustado, diferencia) del cobro de ESTE pago ML.

        - Si hay plan (la suma de los pagos ML cierra contra la venta): el monto del plan; el
          ULTIMO pago pendiente absorbe la diferencia de redondeo (<= tolerancia).
        - Sin plan, pago UNICO: se iguala al total de la venta SOLO si la diferencia es redondeo
          o cupon/descuento del vendedor (<= cupon + tolerancia). [#caso-K15] Antes se forzaba ante
          CUALQUIER diferencia: una venta en $1,21 (precio pisado por una automatizacion del
          cliente) se "cobraba" por $1,21 contra $171.925 cobrados en ML, y la factura quedaba
          pagada escondiendo el error. Ahora se registra lo cobrado y se avisa en la venta.
        - Sin plan, varios pagos: comportamiento de siempre (monto individual; el ultimo se
          ajusta si la diferencia es chica)."""
        self.ensure_one()
        tol = self._meli_payment_tolerance(config)
        if not sale_order or not (sale_order.amount_total or 0.0) > 0:
            return total_amount, False, 0.0
        so_amount = sale_order.amount_total
        approved = self._meli_so_approved_payments(sale_order)
        # #caso-K72: en BRUTO (amount + retenciones l10n_ar del cobro); sin retenciones = amount.
        already_paid = sum(
            p._meli_account_payment_gross() for p in approved
            if p.id != self.id and p.account_payment_id and p.account_payment_id.exists())
        other_pending = approved.filtered(
            lambda p: p.id != self.id and not (p.account_payment_id and p.account_payment_id.exists()))

        if plan and self.id in plan[1]:
            amount = plan[1][self.id]
            if not other_pending:
                remaining = so_amount - already_paid
                if 0.001 < abs(remaining - amount) <= tol:
                    _logger.info("MELI plan (%s) LAST adjustment: %.4f -> %.4f", plan[0], amount, remaining)
                    return remaining, True, amount - remaining
            _logger.info("MELI plan (%s): pago ML %s por %.4f (SO %.4f)", plan[0], self.payment_id, amount, so_amount)
            return amount, False, 0.0

        coupon_amount = sale_order.meli_discount_seller_amount or sale_order.meli_coupon_amount or 0
        if len(approved) <= 1:
            diff = total_amount - so_amount
            if abs(diff) <= 0.001:
                return total_amount, False, 0.0
            if abs(diff) <= tol + abs(coupon_amount or 0.0):
                _logger.info("MELI single-payment adjustment: %.4f -> SO %.4f (coupon: %.4f)",
                             total_amount, so_amount, coupon_amount)
                return so_amount, True, diff
            msg = ("El cobro de MercadoLibre %s ($ %.2f) no coincide con el total de la venta ($ %.2f): "
                   "se registra lo cobrado en MercadoLibre. Revisar el precio de la venta/factura."
                   % (self.payment_id, total_amount, so_amount))
            _logger.warning("create_payment: %s %s", sale_order.name, msg)
            try:
                meli_money_block_post(sale_order, msg, config=config,
                                      once_key="meli-pay-nomatch-%s" % self.payment_id)
            except Exception as e:
                _logger.info("create_payment: no se pudo avisar en %s: %s", sale_order.name, e)
            return total_amount, False, 0.0

        if not other_pending:
            # [#caso-K60 F5b, 26.369] Ademas del redondeo, el ULTIMO recibo cierra al total cuando lo que
            # falta lo explica el envio del carrito que pago el comprador (pago MP aparte, no viene en
            # ningun pago de las ordenes) o el cupon que pago ML. Nunca supera el total: si la
            # diferencia es otra cosa, monto crudo. Ver meli_receipt.py.
            _uncovered = meli_receipt.uncovered_by_payments(
                sale_order.meli_shipping_amount,
                [(p.transaction_amount, p.total_paid_amount, p.shipping_amount) for p in approved])
            _new_amount, _adjusted, _why = meli_receipt.last_payment_amount(
                so_amount, already_paid, total_amount, _uncovered, tolerance=tol)
            if _adjusted:
                _logger.info("MELI multi-payment LAST adjustment (%s): %.4f -> %.4f (so_amount: %.4f, "
                             "already_paid: %.4f, uncovered: %.4f)",
                             _why, total_amount, _new_amount, so_amount, already_paid, _uncovered)
                return _new_amount, True, total_amount - _new_amount
        return total_amount, False, 0.0

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
        # Volcar a la base el vinculo ANTES del SQL crudo: si el caller (republish_invoice_payments,
        # confirm_ml) acaba de poner account_payment_id=False, sin flush el SELECT ve todavia el pago
        # viejo, sale con 'Pago ya creado' y no crea nada (cliente T caso-K23, 8-oct-2026).
        self.flush_recordset(['account_payment_id'])
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
        _so_for_plan = self._get_ml_customer_order()
        _plan = self._meli_payment_amount_plan(_so_for_plan, config=config, meli=meli)
        if self.order_id:
            siblings_approved = self.order_id.payments.filtered(
                lambda p: p.id != self.id and p.status == 'approved'
            )
            # [#caso-K15] Dos payment_addition del mismo monto (envio cobrado en dos partes) NO son un
            # duplicado si la suma de TODOS los pagos ML cierra contra la venta: ML los cuenta a los
            # dos (ML 2000884850625538: 77.675 + 8.000 + 8.000 = 93.675; se descartaba un 8.000).
            if siblings_approved and _plan and self.id in _plan[1]:
                _logger.info("create_payment: pago ML %s cuenta en el total de la venta (%s): no es duplicado",
                             self.payment_id, _plan[0])
                siblings_approved = self.env['mercadolibre.payments']
            if siblings_approved:
                # Brasil D (26.314): IDs numericos => mismo criterio de siempre (int); con alguno
                # alfanumerico => date_created + ID como texto (antes el anti-duplicado se apagaba).
                _rkey = self._meli_payment_recency_key(self | siblings_approved)
                sibling_max = max(siblings_approved, key=_rkey)
                my_pid = _rkey(self)
                max_sibling_pid = _rkey(sibling_max)
                if my_pid < max_sibling_pid:
                    my_amount = self.transaction_amount or 0
                    sibling_amount = sibling_max.transaction_amount if sibling_max else 0
                    amounts_match = abs(my_amount - sibling_amount) < 1.0
                    if amounts_match:
                        _logger.warning(
                            'create_payment: ANTI-DUPLICADO — pago ML %s omitido para orden ML %s '
                            'porque existe un pago más reciente ML %s con mismo monto (%.2f ≈ %.2f).',
                            self.payment_id, self.order_id.name, sibling_max.payment_id,
                            my_amount, sibling_amount
                        )
                        return None
                    else:
                        _logger.info(
                            'create_payment: pagos parciales detectados — pago ML %s (%.2f) y '
                            'ML %s (%.2f) tienen montos diferentes, ambos se crean.',
                            self.payment_id, my_amount, sibling_max.payment_id, sibling_amount
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

        # [26.269] Linea de metodo EXPLICITA, con cuenta de pagos pendientes: sin ella
        # Odoo 18/19 toma la primera linea entrante y, si no tiene cuenta, el cobro
        # queda sin asiento. Si ninguna linea sirve, no se crea y se avisa en la venta.
        payment_method_line, pml_reason = meli_payment_method_line_for(journal_id, 'inbound', partner=partner_id)
        if not payment_method_line:
            msg = "No se registro el cobro de MercadoLibre %s: %s" % (self.payment_id, pml_reason)
            _logger.warning('create_payment: %s', msg)
            so_noline = self._get_ml_customer_order()
            if so_noline:
                meli_money_block_post(so_noline, msg, config=config,
                                      once_key="meli-pay-noline-%s" % self.payment_id)
            return None

        communication = self.payment_id
        if self._get_ml_customer_order():
            communication = ""+str(self._get_ml_customer_order().name)+" OP "+str(self.payment_id)+str(" TOT")

        #total_amount = self.transaction_amount
        #TODO: using meli_amount_to_invoice to foreach item/order not from total
        #total_amount = self._get_ml_customer_order().meli_amount_to_invoice( meli=meli, config=config )
        total_amount = self.meli_amount_to_invoice( meli=meli, config=config )
        #self.total_paid_amount

        # Ajuste de monto [#caso-K15 26.305]: ver _meli_payment_amount_for_so / _meli_payment_amount_plan.
        rounding_adjusted = False
        rounding_difference = 0.0
        sale_order = self._get_ml_customer_order()

        # Opcion de redondeo sin centavos (Argentina)
        round_to_integer = False
        if config and "mercadolibre_round_to_integer" in config._fields:
            round_to_integer = config.mercadolibre_round_to_integer

        if sale_order and sale_order.amount_total > 0:
            total_amount, rounding_adjusted, rounding_difference = self._meli_payment_amount_for_so(
                sale_order, total_amount, plan=_plan, config=config)

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
                'payment_method_id': payment_method_line.payment_method_id.id,
                'payment_method_line_id': payment_method_line.id,
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

        # #caso-K72: retenciones de MP con l10n_ar_withholding (opt-in por compania). Si falta
        # configuracion el cobro se crea como siempre (bruto, sin retenciones) y se avisa
        # una sola vez en la venta: nunca se frena un cobro por esto.
        ar_wth_applied = False
        if self._meli_ar_wth_enabled(config=config):
            wo_lines, wo_total, why = self._meli_ar_withholding_write_off(payment_company, currency_id)
            if wo_lines and currency_id.compare_amounts(wo_total, total_amount) < 0:
                vals_payment['amount'] = currency_id.round(total_amount - wo_total)
                vals_payment['write_off_line_vals'] = wo_lines
                ar_wth_applied = True
                _logger.info("MELI #caso-K72: cobro %s neto %.2f + retenciones %.2f = %.2f",
                             self.payment_id, vals_payment['amount'], wo_total, total_amount)
            elif wo_lines or why:
                why = why or ("las retenciones (%.2f) no son menores al total del cobro (%.2f)"
                              % (wo_total, total_amount))
                so_wth = self._get_ml_customer_order()
                if so_wth:
                    meli_money_block_post(
                        so_wth,
                        "Cobro de MercadoLibre %s registrado SIN retenciones: %s" % (self.payment_id, why),
                        config=config, once_key="meli-pay-arwth-%s" % self.payment_id)

        # Add withholding lines if l10n_account_withholding_tax is installed
        has_wth = 'is_withholding_tax_on_payment' in self.env['account.tax']._fields
        if not ar_wth_applied and has_wth and 'withholding_line_ids' in self.env['account.payment']._fields:
            wth_lines = self._prepare_withholding_lines(config=config)
            if wth_lines:
                vals_payment['should_withhold_tax'] = True
                vals_payment['withholding_line_ids'] = wth_lines
                _logger.info(
                    "MELI create_payment: %d withholding lines added for payment %s",
                    len(wth_lines), self.payment_id,
                )

        def _wth_a_borrador(pay):
            # #caso-K72: con write_off_line_vals Odoo 18 crea el pago ya en 'in_process' con el
            # asiento en borrador. Los grupos de pago (account_payment_group_pro._do_post) solo
            # postean pagos en 'draft' => sin esto el grupo queda 'posted' y el asiento del
            # cobro en borrador (medido en banco 462, 29-oct). Se lo deja en 'draft' ANTES de
            # validar: la validacion (grupo o pago) lo postea por el camino normal.
            if vals_pay_wth[0] and pay and pay.state == 'in_process' and pay.move_id \
                    and pay.move_id.state == 'draft':
                pay.state = 'draft'

        vals_pay_wth = [False]

        def _crear_cobro(vals_pay):
            acct_payment_id = None
            vals_pay_wth[0] = bool(vals_pay.get('write_off_line_vals'))
            if 'account.payment.group' in self.env:
                vals_group = {
                    'company_id': payment_company.id,
                    'receiptbook_id': (self._get_ml_receiptbook(config=config) and self._get_ml_receiptbook(config=config).id),
                    'partner_id': partner_id.id,
                    #'journal_id': journal_id.id,
                    'currency_id': currency_id.id,
                    'partner_type': 'customer',
                    'payment_ids': [(0,0,vals_pay)]
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
                    _wth_a_borrador(acct_payment_group_id.payment_ids[:1])
                    if (self._get_ml_validate(config=config)):
                        payment_group_post( acct_payment_group_id )

            else:
                #_logger.info("create_payment default: "+str(vals_pay))
                acct_payment_id = self.env['account.payment'].with_company(payment_company).create(vals_pay)
                self.account_payment_id = (acct_payment_id and acct_payment_id.id)
                _wth_a_borrador(acct_payment_id)
                if (self._get_ml_validate(config=config)):
                    payment_post( acct_payment_id )

        if not ar_wth_applied:
            _crear_cobro(vals_payment)
        else:
            # #caso-K72: red de seguridad. Con retenciones el alta (y la validacion) van en un
            # savepoint y se VERIFICA el asiento: si algo las rechaza o las descarta en silencio
            # (p.ej. un modulo de grupos de pago que no pasa write_off_line_vals), el cobro se
            # crea como siempre (bruto, sin retenciones) y queda el motivo en la venta. Nunca
            # se pierde un cobro por esto.
            n_wth = len([l for l in vals_payment['write_off_line_vals'] if l.get('tax_repartition_line_id')])
            try:
                with self.env.cr.savepoint():
                    _crear_cobro(dict(vals_payment))
                    ap = self.account_payment_id
                    got = ap and ap.move_id and len(ap.move_id.line_ids.filtered(
                        lambda l: l.tax_line_id
                        and l.tax_line_id.l10n_ar_withholding_payment_type == 'customer')) or 0
                    if got != n_wth:
                        raise UserError("el asiento del cobro quedo con %s de %s lineas de retencion" % (got, n_wth))
                    if self._get_ml_validate(config=config) and ap.move_id.state != 'posted':
                        raise UserError("el asiento del cobro con retenciones quedo en estado '%s' (se esperaba publicado)"
                                        % ap.move_id.state)
            except Exception as e:
                self.env.invalidate_all()
                _logger.warning("MELI #caso-K72: cobro %s con retenciones fallo (%s); se crea sin retenciones",
                                self.payment_id, e)
                ar_wth_applied = False
                vals_payment.pop('write_off_line_vals', None)
                vals_payment['amount'] = total_amount
                _crear_cobro(vals_payment)
                so_wth = self._get_ml_customer_order()
                if so_wth:
                    meli_money_block_post(
                        so_wth,
                        "Cobro de MercadoLibre %s registrado SIN retenciones: no se pudieron registrar (%s)"
                        % (self.payment_id, e),
                        config=config, once_key="meli-pay-arwth-%s" % self.payment_id)

        # #caso-K72: sin autovalidacion el cobro con retenciones queda en borrador como cualquier
        # otro (_wth_a_borrador); confirmarlo despues postea ese mismo asiento.

    def post_payment(self, config=None):
        config = config or self._get_config()
        if "account_payment_group_id" in self._fields and self.account_payment_group_id:
            if (self._get_ml_validate(config=config)):
                    payment_post_group( self.account_payment_group_id )

        if self.account_payment_id:
            if (self._get_ml_validate(config=config)):
                payment_post( self.account_payment_id )

    def _meli_fee_setting(self, field, default=None, config=None):
        """Lee un ajuste del pago de comision de DONDE ESTE CONFIGURADO en esta instancia.

        [caso de un cliente] El selector se agrego solo en `res.company`, pero cuando la instancia
        tiene cuentas de conexion (`meli_oerp_multiple`) `_get_config()` devuelve la
        `mercadolibre.configuration` de la cuenta ML -otro modelo, con sus propios campos-.
        Ahi el campo no existia, el chequeo `in _fields` daba False y el calculo caia al
        criterio viejo EN SILENCIO: el interruptor estaba puesto y no movia nada.
        Lo midio el cliente con `ir.model.fields`, no nosotros.

        Orden de resolucion, del mas especifico al mas general:
          1. la configuracion que recibio el flujo (la de la CUENTA si hay cuenta),
          2. la compania de esa configuracion,
          3. la compania del entorno.
        Asi funciona con `meli_oerp_multiple` y sin el, y quien configura por cuenta no
        depende de que ademas alguien toque la ficha de la compania.
        """
        for source in (config,
                       config and "company_id" in config._fields and config.company_id,
                       self.env.company):
            if source and field in source._fields:
                value = source[field]
                if value:
                    return value
        return default

    def _get_supplier_fee_amount(self, config=None):
        """Importe del pago de comision a MercadoLibre S.R.L. (el `PMERCP ... FEE`).

        Dos criterios, elegidos por la compania en `meli_supplier_fee_mode`:

        - `fee_amount` (default, comportamiento historico): el `fee_amount` que informa
          MercadoPago, que trae la comision Y el cupon sumados.
        - `charges_only`: solo los cargos de tipo `fee`, y de esos, solo los que son
          comision real. El cupon queda afuera porque tiene su propio `charge_type`
          ('coupon'); los demas se excluyen POR NOMBRE con
          `meli_supplier_fee_exclude_charges` (por defecto `financing_fee`).

        Por que existe la opcion (un cliente): en el extracto de MercadoPago la linea de
        comision es `fee + shipping` y NO incluye el cupon, mientras que el pago que se
        creaba era `fee + cupon`. Con dos criterios distintos el extracto no concilia nunca.

        Por que la exclusion por NOMBRE y no solo por tipo (punto 3 del un caso): el costo de
        la financiacion en cuotas (`financing_fee`) llega entre los cargos y, si MercadoPago
        lo informa con `type='fee'`, cae dentro de `fee_charges_amount`. Tampoco viaja en la
        linea de comision del extracto, asi que sumarlo dejaria el cruce sin cerrar igual que
        antes, solo que por otro motivo. El cliente lo midio en su caso 8: comision 9.071,37
        y ademas un `financing_fee` de 15.189 que no esta ni en el extracto ni en el FEE.
        Por eso NO se usa `fee_charges_amount` directo: ese campo alimenta el mapeo de
        impuestos y tiene que seguir sumando todos los cargos de tipo `fee`.

        IMPORTANTE: este helper es el UNICO lugar donde se decide ese importe. Lo usan
        `create_supplier_payment` (el alta) y `check_supplier_payment` (la correccion
        posterior). Si se cambiara solo el alta, el check reescribiria el pago al criterio
        viejo en la corrida siguiente y el arreglo quedaria muerto.
        """
        self.ensure_one()
        fee_amount = self._meli_fee_amount_resolved()  # [26.361] fee_amount, o el JSON si quedo en 0
        config = self._get_config(config=config)
        mode = self._meli_fee_setting("meli_supplier_fee_mode", "fee_amount", config=config)
        if mode != "charges_only":
            return fee_amount
        if not self.charge_ids:
            # Sin charges sincronizados no hay desglose de donde sacar la comision sola.
            # Se cae al criterio historico y se DECLARA en el log: un fallback mudo haria
            # pasar la verificacion del arreglo sin que nadie se entere.
            _logger.warning(
                "MELI supplier fee: pago %s sin charges sincronizados -> se usa "
                "fee_amount (%.2f) en vez del desglose por cargos.",
                self.payment_id, fee_amount)
            return fee_amount
        excluded_names = self._get_supplier_fee_excluded_names(config=config)
        charges_fee = 0.0
        excluded_total = 0.0
        excluded_detail = []
        for charge in self.charge_ids:
            if charge.charge_type != 'fee':
                continue
            if (charge.name or '').strip().lower() in excluded_names:
                excluded_total += charge.amount_original or 0.0
                excluded_detail.append("%s=%.2f" % (charge.name, charge.amount_original or 0.0))
                continue
            charges_fee += charge.amount_original or 0.0

        if excluded_detail:
            # Se declara SIEMPRE: si manana MercadoPago cambia como informa un cargo, este
            # log es lo unico que separa "se excluyo bien" de "se comio la comision".
            _logger.info(
                "MELI supplier fee: pago %s -> comision %.2f; excluidos por nombre %.2f (%s).",
                self.payment_id, charges_fee, excluded_total, ", ".join(excluded_detail))

        if not charges_fee and fee_amount:
            _logger.warning(
                "MELI supplier fee: pago %s tiene charges pero ninguno de tipo 'fee' "
                "computable (fee_amount=%.2f, excluidos=%.2f) -> se usa fee_amount para no "
                "crear un pago en cero.",
                self.payment_id, fee_amount, excluded_total)
            return fee_amount
        return charges_fee

    def _get_supplier_fee_excluded_names(self, config=None):
        """Nombres de cargo `fee` que NO son comision, normalizados (minusculas, sin espacios)."""
        config = self._get_config(config=config)
        raw = self._meli_fee_setting("meli_supplier_fee_exclude_charges", "financing_fee,financing_add_on_fee",
                                     config=config)
        return {n.strip().lower() for n in (raw or "").split(",") if n.strip()}

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

        # [26.361] 430 OFF 720: nunca un pago de comision por 0 (o negativo). El monto sale del
        # resolvedor (fee_amount, y si quedo en 0, el JSON de MercadoPago). Sin monto: no se crea,
        # queda el aviso UNA vez en la venta y se crea en la proxima actualizacion de la orden.
        _fee_amount = self._get_supplier_fee_amount(config=config)
        if not _fee_amount or _fee_amount <= 0.0:
            meli_money_block_post(self._get_ml_customer_order() or self.order_id,
                "No se registro el pago de comision de MercadoLibre %s: MercadoPago todavia no informa "
                "el importe de la comision (%.2f). Se registra en la proxima actualizacion de la orden."
                % (self.payment_id, _fee_amount or 0.0), config=config,
                once_key="meli-pay-zero-fee-%s" % self.payment_id)
            return None

        vals_payment = {
                'company_id': payment_company.id,
                'partner_id': partner_id.id,
                'payment_type': 'outbound',
                'payment_method_id': payment_method_id.id,
                'journal_id': journal_id.id,
                'meli_payment_id': self.id,
                'currency_id': currency_id.id,
                'partner_type': 'supplier',
                'amount': _fee_amount,
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
        # [26.270] Linea de metodo SALIENTE explicita, con cuenta de pagos pendientes (mismo criterio
        # que el cobro, 26.269). Si ninguna sirve: no se crea el pago y queda el motivo en la venta.
        payment_method_line, pml_reason = meli_payment_method_line_for(journal_id, 'outbound', partner=partner_id)
        if not payment_method_line:
            msg = "No se registro el pago %s a %s de MercadoLibre %s: %s" % (
                "de comision", partner_id.display_name, self.payment_id, pml_reason)
            meli_money_block_post(self._get_ml_customer_order() or self.order_id, msg, config=config,
                                  once_key="meli-pay-noline-fee-%s" % self.payment_id)
            return None
        vals_payment['payment_method_id'] = payment_method_line.payment_method_id.id
        vals_payment['payment_method_line_id'] = payment_method_line.id
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
                vals_group["payment_on_account_amount"] = _fee_amount
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
        """[26.361] Corrige el monto del pago de comision si quedo distinto del que informa ML.
        Borrador: se corrige. Publicado sin conciliar: borrador -> monto -> publicar (como antes).
        Pagado/conciliado: NO se toca; aviso una vez en la venta. Ver _meli_supplier_payment_fix_amount."""
        if not self.account_supplier_payment_id:
            return False
        return self._meli_supplier_payment_fix_amount(
            self.account_supplier_payment_id, self._get_supplier_fee_amount(config=config), 'comision', config=config)

    def check_supplier_payment_shipment(self, config=None):
        """[26.361] Igual que check_supplier_payment, para el pago de envio."""
        if not self.account_supplier_payment_shipment_id:
            return False
        return self._meli_supplier_payment_fix_amount(
            self.account_supplier_payment_shipment_id, self._meli_shipping_amount_out(), 'envio', config=config)

    # ------------------------------------------------------------------------------------------
    # [26.361] 430 OFF caso-K75 (cliente B1, 2-nov-2026): pagos a proveedor de ML por 0.00.
    # MercadoPago informa la comision como cargo `meli_fee` y la ingesta la dejaba en 0; el pago
    # de comision se creaba igual por 0.00 y quedaba "Pagado". Desde aca: el monto se resuelve
    # (fee_amount o el JSON), nunca se crea un pago <= 0, y uno ya creado con monto distinto se
    # corrige solo si no esta conciliado. Lo conciliado NUNCA se modifica automaticamente.
    # ------------------------------------------------------------------------------------------
    def _meli_full_payment_dict(self):
        raw = self.full_payment
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        import json, ast
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            try:
                data = ast.literal_eval(raw)
            except (ValueError, SyntaxError, TypeError, MemoryError):
                return {}
        return data if isinstance(data, dict) else {}

    def _meli_fee_amount_resolved(self):
        """Comision del pago: `fee_amount` si es > 0; si quedo en 0, la del JSON de MercadoPago
        (fee_details application_fee del vendedor, o cargos type=fee). Nunca negativa."""
        self.ensure_one()
        fee = self.fee_amount or 0.0
        if fee > 0.0:
            return fee
        if meli_payment_commission_from_json:
            fb = meli_payment_commission_from_json(self._meli_full_payment_dict())
            if fb > 0.0:
                _logger.info("MELI supplier fee: pago %s con fee_amount=0 -> comision %.2f desde el JSON de MP",
                             self.payment_id, fb)
                return fb
        return 0.0

    def _meli_shipping_amount_out(self):
        """Monto del pago de envio a proveedor (mismo criterio que create_supplier_payment_shipment)."""
        self.ensure_one()
        so = self._get_ml_customer_order()
        amount = 0.0
        if so:
            amount = self.shipping_amount or 0.0
            if so.meli_shipping_seller_cost:
                amount = so.meli_shipping_seller_cost
        return amount

    def _meli_supplier_payment_is_locked(self, pay):
        """Pagado / conciliado: no se modifica automaticamente."""
        if pay.state == 'paid':
            return True
        for f in ('is_reconciled', 'is_matched'):
            if f in pay._fields and pay[f]:
                return True
        return False

    def _meli_supplier_payment_fix_amount(self, pay, amount, kind, config=None):
        self.ensure_one()
        if not pay or not amount or amount <= 0.0:
            return False
        rounding = (pay.currency_id and pay.currency_id.rounding) or 0.01
        # Comparacion con la precision de la moneda (un caso: con `!=` crudo se reescribia en cada ciclo).
        if float_compare(pay.amount, amount, precision_rounding=rounding) == 0:
            return False
        if pay.state in cancel_statuses:
            return False  # cancelado (p.ej. venta cancelada): no se revive
        so = self._get_ml_customer_order() or self.order_id
        if pay.state == 'draft':
            _logger.info("MELI: pago de %s %s en borrador %.2f -> %.2f (OP %s)",
                         kind, pay.display_name, pay.amount, amount, self.payment_id)
            pay.amount = amount
            return True
        if self._meli_supplier_payment_is_locked(pay):
            meli_money_block_post(so,
                "El pago de %s %s de MercadoLibre %s quedo registrado por %.2f y MercadoLibre informa %.2f. "
                "Esta pagado/conciliado: no se modifica automaticamente; corregirlo a mano."
                % (kind, pay.display_name, self.payment_id, pay.amount, amount), config=config,
                once_key="meli-pay-amount-%s-%s-%.2f" % (kind, self.payment_id, amount))
            return False
        if not self._get_ml_validate(config=config):
            return False
        _logger.info("MELI: pago de %s %s publicado sin conciliar %.2f -> %.2f (OP %s)",
                     kind, pay.display_name, pay.amount, amount, self.payment_id)
        pay.action_draft()
        pay.amount = amount
        payment_post(pay)
        return True

    # ------------------------------------------------------------------------------------------
    # IDEMPOTENCIA DEL PAGO DE ENVIO A PROVEEDOR (un cliente, medido en prod 9-oct-2026)
    #
    # La unica guarda contra duplicados era el link `account_supplier_payment_shipment_id`. Al
    # re-procesar ventas viejas (actualizar la orden re-corre confirm_ml) el modulo creaba el pago
    # a Meli Log aunque el envio de esa OP YA estuviera registrado: por un pago nuestro cuyo link se
    # perdio, o por el asiento de un conciliador del cliente (en un cliente: ref "MP-SHIP-<OP>", lineas
    # "Envio MercadoPago [<OP>]"). Resultado medido: 3 OP con doble gasto de envio.
    #
    # Criterio CONSERVADOR: solo se omite la creacion con evidencia fuerte; ante la duda se crea
    # como antes (y queda el aviso en el log).
    #   (1) account.payment saliente a proveedor, no cancelado, ajeno a los links de este registro,
    #       con memo == memo del modulo ("<SO> OP <op> SHP"), o meli_payment_id == este registro y
    #       memo terminado en "SHP"  =>  es el nuestro con el link perdido: se RE-VINCULA.
    #   (2) account.move POSTEADO de la compania, ajeno a los pagos de este registro, cuyo ref
    #       contiene la OP como numero completo + un marcador de envio (SHIP/SHP/ENVIO/FLETE) + una
    #       linea por el MISMO monto  =>  no se crea; mensaje (una sola vez) en la venta.
    # Sobreescribible por cliente (otro formato de conciliador). Bypass explicito con el contexto
    # `meli_force_shipment_payment=True`.
    # ------------------------------------------------------------------------------------------
    _MELI_SHP_MARKERS = ('SHIP', 'SHP', 'ENVIO', 'ENVÍO', 'FLETE')
    _MELI_PAY_CANCEL = ('cancel', 'cancelled', 'canceled')

    def _meli_shp_ref_field(self):
        Payment = self.env['account.payment']
        _acc_ref = globals().get('acc_pay_ref')
        return next((f for f in (_acc_ref, 'memo', 'ref', 'communication')
                     if f and f in Payment._fields), False)

    def _meli_shp_own_payments(self):
        """account.payment ya vinculados a ESTE registro (cobro, comision, envio)."""
        pays = self.env['account.payment']
        for f in ('account_payment_id', 'account_supplier_payment_id', 'account_supplier_payment_shipment_id'):
            if f in self._fields and self[f]:
                pays |= self[f]
        return pays

    def _meli_shp_payment_moves(self, payments):
        moves = self.env['account.move']
        for p in payments:
            if 'move_id' in p._fields and p.move_id:
                moves |= p.move_id
            elif 'move_line_ids' in p._fields:
                moves |= p.move_line_ids.mapped('move_id')
        return moves

    def _meli_shipment_already_accounted(self, amount, partner=None, company=None, communication=None, currency=None):
        """Devuelve (registro, tipo) si el envio de esta OP ya esta registrado; (None, None) si no.

        tipo: 'own_payment' (pago nuestro con link perdido) | 'move' (asiento de otro circuito).
        """
        self.ensure_one()
        op = str(self.payment_id or '').strip()
        if not op or not amount:
            return None, None
        company = company or (self.order_id and self.order_id.company_id) or self.env.company
        rounding = (currency and currency.rounding) or (company.currency_id and company.currency_id.rounding) or 0.01
        Payment = self.env['account.payment'].sudo()
        own = self._meli_shp_own_payments()
        ref_field = self._meli_shp_ref_field()

        # (1) pago nuestro con el link perdido
        dom = [('payment_type', '=', 'outbound'), ('partner_type', '=', 'supplier'),
               ('state', 'not in', list(self._MELI_PAY_CANCEL))]
        if 'company_id' in Payment._fields and company:
            dom.append(('company_id', '=', company.id))
        if partner:
            dom.append(('partner_id', '=', partner.id))
        cands = Payment.browse()
        if ref_field and communication:
            cands |= Payment.search(dom + [(ref_field, '=', communication)], order='id asc')
        if 'meli_payment_id' in Payment._fields:
            for p in Payment.search(dom + [('meli_payment_id', '=', self.id)], order='id asc'):
                if ref_field and str(p[ref_field] or '').strip().upper().endswith('SHP'):
                    cands |= p
        cands = cands - own
        if cands:
            return cands.sorted('id')[0], 'own_payment'

        # (2) asiento posteado de otro circuito (p.ej. conciliador del cliente)
        Move = self.env['account.move'].sudo()
        mdom = [('state', '=', 'posted'), ('ref', 'ilike', op)]
        if company:
            mdom.append(('company_id', '=', company.id))
        own_moves = self._meli_shp_payment_moves(own)
        op_re = re.compile(r'(?<!\d)%s(?!\d)' % re.escape(op))
        for mv in (Move.search(mdom, order='id asc', limit=50) - own_moves):
            ref = str(mv.ref or '')
            if not op_re.search(ref):
                continue
            ref_up = ref.upper()
            if not any(m in ref_up for m in self._MELI_SHP_MARKERS):
                continue
            same_amount = any(
                float_compare(max(l.debit, l.credit), amount, precision_rounding=rounding) == 0
                for l in mv.line_ids)
            if same_amount:
                return mv, 'move'
            _logger.warning(
                "create_supplier_payment_shipment: OP %s tiene el asiento %s (ref '%s') con marcador de envio "
                "pero por OTRO monto (pago a crear %s): NO se bloquea, revisar a mano.",
                op, mv.name, ref, amount)
        return None, None

    def _meli_shp_notify_sale(self, so, found, kind, amount):
        """Deja constancia (una sola vez por OP) en la venta de por que no se creo el pago de envio."""
        if not so or not hasattr(so, 'message_post'):
            return
        tag = "[meli-envio-ya-registrado OP %s]" % (self.payment_id,)
        try:
            Msg = self.env['mail.message'].sudo()
            if Msg.search_count([('model', '=', so._name), ('res_id', '=', so.id), ('body', 'ilike', tag)]):
                return
            if kind == 'own_payment':
                what = "el pago %s (link recuperado)" % (found.display_name,)
            else:
                what = "el asiento %s (ref %s)" % (found.name, found.ref or '')
            so.message_post(body="%s No se creo el pago de envio a proveedor por %s: el envio de esta OP ya "
                                 "esta registrado en %s. Si igual corresponde crearlo: create_supplier_payment_shipment con "
                                 "contexto meli_force_shipment_payment=True." % (tag, amount, what))
        except Exception as e:
            _logger.warning("create_supplier_payment_shipment: no se pudo dejar el mensaje en %s: %s", so, e)

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
        if shipping_amount_out and shipping_amount_out < 0.0:
            # [26.361] 430 OFF 720: un pago saliente de envio nunca es negativo. No se crea; aviso.
            meli_money_block_post(so or self.order_id,
                "No se registro el pago de envio de MercadoLibre %s: el costo de envio informado es "
                "negativo (%.2f)." % (self.payment_id, shipping_amount_out), config=config,
                once_key="meli-pay-neg-shp-%s" % self.payment_id)
            return None
        if not shipping_amount_out:
            # No shipping amount is a normal case - return None instead of raising
            _logger.debug('create_supplier_payment_shipment: No hay monto de costo de envio para %s', self.payment_id)
            return None
        # no duplicar el envio si ya esta registrado (ver _meli_shipment_already_accounted)
        if not self.env.context.get('meli_force_shipment_payment'):
            _shp_found, _shp_kind = self._meli_shipment_already_accounted(
                shipping_amount_out, partner=partner_id, company=payment_company,
                communication=communication, currency=currency_id)
            if _shp_found:
                if _shp_kind == 'own_payment':
                    self.account_supplier_payment_shipment_id = _shp_found.id
                    _logger.info("create_supplier_payment_shipment: OP %s ya tenia el pago %s (link perdido): se re-vincula",
                                 self.payment_id, _shp_found.id)
                else:
                    _logger.info("create_supplier_payment_shipment: OP %s ya registrada en %s (%s): NO se crea el pago",
                                 self.payment_id, _shp_found.name, _shp_found.ref)
                self._meli_shp_notify_sale(so, _shp_found, _shp_kind, shipping_amount_out)
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
        # [26.270] Linea de metodo SALIENTE explicita, con cuenta de pagos pendientes (mismo criterio
        # que el cobro, 26.269). Si ninguna sirve: no se crea el pago y queda el motivo en la venta.
        payment_method_line, pml_reason = meli_payment_method_line_for(journal_id, 'outbound', partner=partner_id)
        if not payment_method_line:
            msg = "No se registro el pago %s a %s de MercadoLibre %s: %s" % (
                "de envio", partner_id.display_name, self.payment_id, pml_reason)
            meli_money_block_post(self._get_ml_customer_order() or self.order_id, msg, config=config,
                                  once_key="meli-pay-noline-shp-%s" % self.payment_id)
            return None
        vals_payment['payment_method_id'] = payment_method_line.payment_method_id.id
        vals_payment['payment_method_line_id'] = payment_method_line.id
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
                vals_group["payment_on_account_amount"] = shipping_amount_out  # [26.361] = monto del pago
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

            # Pasos 1-3 DENTRO DE UN SAVEPOINT (un cliente).
            #
            # El orden del metodo es: cancelar el recibo -> limpiar el vinculo -> recrear.
            # Si el ultimo paso no llega a crear un pago, el borrado YA ESTA HECHO y no hay
            # nada que reponga el recibo anterior: la factura queda sin cobro imputado y el
            # operador lo tiene que armar a mano. Con el savepoint, un fallo posterior al
            # cancelado deshace el cancelado y el recibo original sobrevive.
            #
            # Mismo patron que meli_oerp 26.87 sobre la linea de envio, que era el mismo
            # fallo: el core borraba y recreaba, el error se descartaba en silencio y el
            # borrado quedaba consumado.
            #
            # create_payment() puede volver SIN crear nada y SIN lanzar (tiene varias
            # salidas tempranas), asi que el "no se pudo" se convierte en excepcion a mano:
            # es la unica forma de que el savepoint revierta.
            old_payment = pay.account_payment_id
            old_payment_name = old_payment.name or old_payment.display_name or str(old_payment.id)
            republish_error = None

            try:
                with pay.env.cr.savepoint():
                    # 1. Cancelar pago existente
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

                    if not pay.account_payment_id:
                        raise MeliRepublishPaymentError(
                            "create_payment no dejo ningun pago nuevo en el pago de "
                            "MercadoLibre %s" % pay.payment_id)
            except Exception as e:
                # El savepoint ya deshizo el cancelado: el recibo anterior sigue vivo.
                republish_error = e

            if republish_error is None and pay.account_payment_id:
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
                # El aviso TIENE que verse en la venta, no solo en el log del servidor:
                # es lo que pidio el cliente en el un caso y es parte del mismo arreglo. Antes
                # la rama de exito hacia message_post y esta solo logueaba, asi que el unico
                # caso que el operador necesitaba ver era justamente el invisible.
                _logger.warning(
                    "MELI republish_invoice_payments: no se pudo recrear el pago para %s "
                    "(%s); se conserva el recibo %s.",
                    pay.payment_id, republish_error, old_payment_name
                )
                so = pay._get_ml_customer_order()
                if so:
                    try:
                        so.message_post(
                            body="No se pudo republicar el pago de MercadoLibre al partner "
                                 "'%s' de la factura %s. Se conserva el recibo '%s' con el "
                                 "partner '%s'. Detalle: %s" % (
                                     invoice_partner.name,
                                     invoices[0].name or '',
                                     old_payment_name,
                                     payment_partner.name,
                                     republish_error,
                                 ),
                            message_type=product_message_type
                        )
                    except Exception as e:
                        _logger.warning(
                            "MELI republish_invoice_payments: no se pudo avisar en la venta "
                            "%s: %s", so.name, e)

    def _meli_is_pack_splitted(self):
        """True si el pedido de este pago fue PARTIDO por MercadoLibre (FULL).

        No es una inferencia: ML lo escribe en el detalle de estado, literalmente
        `pack_splitted: Purchases has splitted the pack`. Ese texto ya se guarda en dos
        lados (`mercadolibre.orders.status_detail` y `sale.order.meli_status_detail`), y
        hasta el un caso NINGUN codigo del arbol lo miraba: por eso mirarlo ahora no puede
        cambiarle el comportamiento a nadie que hoy funcione.

        Se miran los dos campos porque se pueblan en momentos distintos del import y no
        hay garantia de cual llego primero.
        """
        self.ensure_one()
        needle = "pack_splitted"
        order = self.order_id
        if order and needle in (order.status_detail or ""):
            return True
        so = self._get_ml_customer_order()
        if so and "meli_status_detail" in so._fields and needle in (so.meli_status_detail or ""):
            return True
        return False

    def _meli_cancel_payment_of_splitted_pack(self, config=None):
        """Cancela el recibo del pack CANCELADO por un split, si es seguro hacerlo.

        Seguro = el recibo no esta conciliado. Si lo esta, alguien ya lo aplico a algo y
        cancelarlo moveria contabilidad que no es nuestra: se DECLARA en el log y no se
        toca. Un skip mudo aca haria que el arreglo "pase" sin arreglar nada.
        """
        self.ensure_one()
        acct_pay = self.account_payment_id
        if not acct_pay or not acct_pay.exists():
            return False
        # OJO: `cancel_statuses` del modulo es ['cancel','cancelled'] y en Odoo 18 el estado
        # de account.payment es 'canceled' (UNA ele). O sea que `state in cancel_statuses`
        # no da verdadero nunca en 18. Aca se chequea bien a proposito; NO se corrige la
        # constante compartida desde este fix porque la usan varios puntos del modulo y
        # cambiarla de golpe mueve comportamiento fuera del alcance del un caso.
        if acct_pay.state in cancel_statuses or acct_pay.state == "canceled":
            return False

        if "is_reconciled" in acct_pay._fields and acct_pay.is_reconciled:
            _logger.warning(
                "MELI_PACK_SPLIT: el pago ML %s corresponde a un pack partido, pero su recibo "
                "%s ya esta CONCILIADO -> no se cancela. Revisar a mano.",
                self.payment_id, acct_pay.name or acct_pay.id)
            return False

        _logger.info(
            "MELI_PACK_SPLIT: pago ML %s en estado '%s' por pack partido -> se cancela el "
            "recibo %s (importe %.2f) para que no quede saldo a favor del cliente.",
            self.payment_id, self.status, acct_pay.name or acct_pay.id, acct_pay.amount or 0.0)

        self.cancel_payments(config=config)

        # El aviso va a la VENTA, no solo al log: es un movimiento contable hecho por el
        # conector y el operador tiene que poder verlo sin entrar al servidor.
        so = self._get_ml_customer_order()
        if so:
            try:
                so.message_post(
                    body="MercadoLibre partio el pack de este pedido y devolvio el cobro "
                         "original. Se cancelo el recibo '%s' para que no quede un saldo a "
                         "favor del cliente por un cobro que ya no existe. El cobro vigente "
                         "es el del pedido nuevo." % (acct_pay.name or acct_pay.id,),
                    message_type=product_message_type
                )
            except Exception as e:
                _logger.warning(
                    "MELI_PACK_SPLIT: no se pudo avisar en la venta %s: %s", so.name, e)
        return True

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

    def _meli_withholding_number(self, tax):
        """#caso-K47: numero de la linea de retencion = ID de operacion de MercadoPago.

        False si el impuesto tiene secuencia de retenciones (withholding_sequence_id):
        en ese caso numera Odoo al confirmar y no se le pisa la secuencia al cliente.
        """
        self.ensure_one()
        if 'withholding_sequence_id' in tax._fields and tax.withholding_sequence_id:
            return False
        return (self.payment_id and str(self.payment_id).strip()) or False

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
            # #caso-K47 (caso-K48 cliente O): el numero de la retencion es el ID de operacion de
            # MercadoPago, salvo que el impuesto tenga su propia secuencia de retenciones
            # (ahi numera Odoo). Sin numero ni secuencia, Odoo no deja confirmar el pago
            # ("Please enter the withholding number") y habia que tipearlo a mano en cada uno.
            wth_number = self._meli_withholding_number(tax)
            if wth_number:
                vals['name'] = wth_number

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

    # ------------------------------------------------------------------------------------
    # #caso-K72 (caso-K21 cliente F): retenciones de MercadoPago con l10n_ar_withholding (17/18/19, AR)
    # ------------------------------------------------------------------------------------
    # l10n_ar_withholding NO usa withholding_line_ids (eso es l10n_account_withholding_tax,
    # el camino de arriba). Sus retenciones de cobro son lineas del asiento del pago, las
    # mismas que arma el wizard "Registrar pago" (account.payment.register.
    # _create_payment_vals_from_wizard): linea de impuesto con tax_repartition_line_id de un
    # impuesto l10n_ar_withholding_payment_type='customer' + par de base (+/-) en
    # company.l10n_ar_tax_base_account_id; el amount del pago es el NETO y la cuenta a cobrar
    # salda el total. El monto es el que retuvo MercadoPago (no se recalcula con la alicuota
    # del impuesto de Odoo): es lo que dice el certificado y lo que falta en la cuenta de MP.

    def _meli_ar_wth_enabled(self, config=None):
        Tax = self.env['account.tax']
        if 'l10n_ar_withholding_payment_type' not in Tax._fields:
            return False
        # Si tambien esta l10n_account_withholding_tax, manda el camino existente.
        if ('is_withholding_tax_on_payment' in Tax._fields
                and 'withholding_line_ids' in self.env['account.payment']._fields):
            return False
        # Config de la cuenta ML (meli_oerp_multiple) -> su compania -> compania del entorno:
        # el flag vive en res.company y sirve con y sin cuentas de conexion.
        fname = 'mercadolibre_ar_withholding_on_payment'
        for source in (config,
                       config and 'company_id' in config._fields and config.company_id,
                       self.env.company):
            if source and fname in source._fields and source[fname]:
                return True
        return False

    def _meli_ar_wth_number(self, tax, charge):
        """Numero de la retencion: secuencia del impuesto si tiene; si no, el ID del cargo de
        MercadoPago (<operacion>-00N, unico por retencion); si no, el ID de la operacion."""
        if 'l10n_ar_withholding_sequence_id' in tax._fields and tax.l10n_ar_withholding_sequence_id:
            return tax.l10n_ar_withholding_sequence_id.next_by_id()
        return (charge.charge_id or '').strip() or (self.payment_id and str(self.payment_id).strip()) or False

    def _meli_ar_withholding_write_off(self, company, currency, date=None):
        """Lineas de retencion (write_off_line_vals) para el cobro de este pago de MP.

        :returns: (lineas, total_retenido, motivo) - si no hay nada que aplicar o falta
                  configuracion, lineas=[] y motivo explica por que (None = no habia retenciones).
        """
        self.ensure_one()
        if not self.charge_ids and self.full_payment:
            try:
                self.sync_charges_from_json()
            except Exception as e:
                _logger.info("MELI #caso-K72: no se pudieron leer los cargos del pago %s: %s", self.payment_id, e)
        charges = self.charge_ids.filtered(
            lambda c: c.charge_type == 'tax'
            and ((c.amount_original or 0.0) - (c.amount_refunded or 0.0)) > 0.0)
        if not charges:
            return [], 0.0, None

        Rule = self.env['mercadolibre.tax'].with_company(company)
        base_account = company.l10n_ar_tax_base_account_id
        if not base_account:
            return [], 0.0, ("falta la cuenta base de retenciones en la compania "
                             "(Contabilidad > Ajustes > Argentina: cuenta base de impuestos)")
        company_currency = company.currency_id
        date = date or fields.Date.context_today(self)

        def to_company(amount):
            if currency == company_currency:
                return company_currency.round(amount)
            return currency._convert(amount, company_currency, company, date)

        mapped, unmapped = [], []
        for charge in charges:
            rule = charge.meli_tax_id
            if not (rule and rule.state == 'confirmed' and rule.account_tax_id
                    and rule.company_id == company):
                rule = Rule.match_charge(
                    charge.charge_type, charge.name,
                    {'mov_financial_entity': charge.mov_financial_entity or '',
                     'source_detail': charge.source_detail or ''},
                )
            tax = rule and rule.account_tax_id
            if not tax or tax.l10n_ar_withholding_payment_type != 'customer':
                unmapped.append(charge.name or charge.charge_id or '?')
                continue
            rep = tax.invoice_repartition_line_ids.filtered(
                lambda l: l.repartition_type == 'tax' and l.account_id)[:1]
            if not rep:
                return [], 0.0, ("el impuesto '%s' no tiene cuenta en su linea de reparto de impuesto"
                                 % tax.name)
            mapped.append((charge, tax, rep))

        if unmapped:
            # Todo o nada: un cobro con una retencion sin registrar quedaria descuadrado
            # contra lo que efectivamente acredito MP.
            return [], 0.0, ("retenciones sin regla confirmada con impuesto de tipo 'Retencion en "
                             "pago de cliente' en MercadoLibre > Impuestos: %s" % ", ".join(unmapped))

        lines, bases, total = [], {}, 0.0
        for charge, tax, rep in mapped:
            amount = currency.round((charge.amount_original or 0.0) - (charge.amount_refunded or 0.0))
            base = currency.round(charge.base_amount or 0.0)
            lines.append({
                'currency_id': currency.id,
                'name': self._meli_ar_wth_number(tax, charge),
                'account_id': rep.account_id.id,
                'amount_currency': amount,
                'balance': to_company(amount),
                'tax_base_amount': base,
                'tax_repartition_line_id': rep.id,
            })
            bases.setdefault(base, []).append((tax, lines[-1]['name']))
            total += amount

        for base, taxes in bases.items():
            label = ','.join(str(n) for _t, n in taxes if n)
            tax_ids = list({t.id for t, _n in taxes})
            lines.append({
                'currency_id': currency.id,
                'name': label,
                'tax_ids': [(6, 0, tax_ids)],
                'account_id': base_account.id,
                'amount_currency': base,
                'balance': to_company(base),
            })
            lines.append({
                'currency_id': currency.id,
                'name': label,
                'account_id': base_account.id,
                'amount_currency': -base,
                'balance': -to_company(base),
            })
        return lines, currency.round(total), None

    def _meli_account_payment_gross(self):
        """Lo que el cobro salda en la cuenta a cobrar: amount + retenciones l10n_ar del asiento.
        Sin retenciones (o sin l10n_ar_withholding) es amount, como siempre."""
        self.ensure_one()
        ap = self.account_payment_id
        if not ap or not ap.exists():
            return 0.0
        gross = ap.amount or 0.0
        if 'l10n_ar_withholding_payment_type' in self.env['account.tax']._fields and ap.move_id:
            gross += sum(abs(l.amount_currency) for l in ap.move_id.line_ids
                         if l.tax_line_id and l.tax_line_id.l10n_ar_withholding_payment_type == 'customer')
        return gross

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
