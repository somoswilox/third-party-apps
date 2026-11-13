# -*- coding: utf-8 -*-
"""26.372 — mejoras de conciliacion Mercado Pago (cliente R #caso-K73, punto 6).

(El punto 4 —financiacion en campo separado— va aparte, en mp_financing_718.py, en pausa.)

Punto 6 — REEMBOLSO / CONTRACARGO. Por diseno (#caso-K46) un pago `refunded` no cancela el cobro original,
y la comision (FEE) y el envio (SHP) que ML devuelve quedaban registrados como pagados para siempre.
Ademas `amount_refunded` de los cargos quedaba en 0: el sync salteaba los cargos ya existentes, asi
que lo que MercadoPago informaba DESPUES del alta nunca llegaba. Caso: OP 173823500930 (orden
cancelada, pago reintegrado total; JSON fee 20.206,41 devuelto, en Odoo 0).
  * El sync ahora actualiza los importes de los cargos existentes (siempre: es dato de MP).
  * Con `meli_refund_revert_charges` (compania o cuenta; APAGADO por defecto) se registra la
    devolucion como un COBRO ENTRANTE del mismo proveedor y en el mismo diario que el original:
    memo `<venta> OP <op> FEE-REV` / `SHP-REV`. Importe = suma de `amount_refunded` (comision: mismo
    filtro de nombres que el pago de comision; envio: cargos `shipping`), TOPEADO al pago original.
    Solo si el original existe y no esta cancelado. El cobro original, la factura y lo conciliado
    NO se tocan.
    v2 (26.141.4, revision del cliente): lo registrado se mide como la SUMA de los REV vigentes (link
    + memo base + complementos `... FEE-REV #N`); parcial -> total registra solo la DIFERENCIA (ajusta
    el borrador o crea un complemento), nunca por encima del original. La publicacion va en su propio
    savepoint (no versions.payment_post, que tragaba el error): si falla queda en borrador, se avisa una
    vez en la venta y cada pasada la reintenta. Un REV anulado ('canceled' en 18) no cuenta. La orden
    cancelada (meli_cancel_with_detail, sin config) resuelve la config del pago.
  * NOTA DE CREDITO (decision del cliente, call 4-nov): con `meli_refund_credit_note_draft` (APAGADO
    por defecto) la NC se crea SIEMPRE EN BORRADOR y la valida el usuario; nunca se postea sola
    (la mayoria de sus ventas ML son consumidor final y no se facturan). Se crea cuando todos los
    pagos de la venta quedaron reintegrados TOTAL (`refunded`; no parcial, no contracargo, no pack
    partido), este o no cancelada la orden. Y el modo `credit_note` de `_meli_cancel_invoices`
    respeta el mismo flag. Idempotente: una reversion no cancelada (borrador incluido) cuenta.
  * Pack partido de FULL (`pack_splitted`, #caso-K74) NO es una devolucion: se saltea.

Archivo autocontenido a proposito: es identico en 16.0-20.0 y en las ramas de clientes; no depende
de helpers que existen solo en algunas series (`_meli_fee_setting` es solo 18.0).
"""
import ast
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from odoo.addons.meli_oerp_accounting.models.versions import (
    acc_pay_ref, acc_pay_group_ref, cancel_statuses, payment_group_post)

_logger = logging.getLogger(__name__)

MELI_718_FINANCING_PREFIX = 'financing'
MELI_718_EXCLUDE_DEFAULT = 'financing_fee,financing_add_on_fee'
MELI_718_REFUND_STATUSES = ('refunded', 'partially_refunded', 'charged_back')
# 18.0 usa 'canceled'/'rejected' en account.payment; versions.cancel_statuses solo trae 'cancel'/'cancelled'
MELI_718_DEAD = tuple(set(cancel_statuses) | {'cancel', 'cancelled', 'canceled', 'rejected'})
MELI_718_DRAFT = ('draft',)
MELI_718_LINK = {'FEE': 'account_supplier_payment_rev_id', 'SHP': 'account_supplier_payment_shipment_rev_id'}
MELI_718_POST_TAG = "[meli-718-rev-sin-publicar OP %s %s-REV %s]"


def _meli_718_post(record, body, config=None):
    """Nota en la venta sin depender de la firma de meli_message_post de cada serie."""
    try:
        from odoo.addons.meli_oerp.models.versions import meli_message_post
        return meli_message_post(record, body, config=config)
    except Exception:  # pragma: no cover - fallback minimo
        try:
            record.message_post(body=body)
        except Exception:
            _logger.info("MELI 718: sin chatter para %s: %s", record, body)


class ResCompany(models.Model):
    _inherit = 'res.company'

    meli_refund_revert_charges = fields.Boolean(
        string='Registrar comisión y envío devueltos por ML',
        default=False,
        help="Cuando un pago de Mercado Pago queda reintegrado (refunded / partially_refunded) o con "
             "contracargo (charged_back), registra la comisión y el envío que Mercado Libre devolvió "
             "como un cobro entrante del mismo proveedor (memo '<venta> OP <op> FEE-REV' / 'SHP-REV'). "
             "No modifica el cobro original, la factura ni lo conciliado. Apagado por defecto.")
    meli_refund_credit_note_draft = fields.Boolean(
        string='Nota de crédito en borrador al reembolsar',
        default=False,
        help="Cuando Mercado Libre reintegra TODO el pago de una venta facturada, crea la nota de "
             "crédito EN BORRADOR (la valida el usuario; nunca se publica sola). También hace que el "
             "modo 'Crear nota de crédito' de 'Acción sobre factura al cancelar pedido' deje la NC en "
             "borrador. Apagado por defecto.")


class MeliPaymentMejoras718(models.Model):
    _inherit = 'mercadolibre.payments'

    account_supplier_payment_rev_id = fields.Many2one(
        'account.payment', string='Devolución de comisión (FEE-REV)', copy=False)
    account_supplier_payment_shipment_rev_id = fields.Many2one(
        'account.payment', string='Devolución de envío (SHP-REV)', copy=False)

    # ------------------------------------------------------------------ ajustes
    def _meli_718_setting(self, field, default=None, config=None):
        """Cuenta ML (config) -> su compania -> compania del entorno; el primero con valor gana."""
        for source in (config,
                       config and 'company_id' in config._fields and config.company_id,
                       self.env.company):
            if source and field in source._fields and source[field]:
                return source[field]
        return default

    def _meli_718_excluded_fee_names(self, config=None):
        raw = self._meli_718_setting('meli_supplier_fee_exclude_charges', MELI_718_EXCLUDE_DEFAULT, config=config)
        return {n.strip().lower() for n in (raw or '').split(',') if n.strip()}

    # ------------------------------------------------------------------ sync de cargos
    def _meli_718_full_payment_dict(self, full_payment=None):
        if full_payment:
            return full_payment
        raw = self.full_payment
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            try:
                return ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                return None

    def sync_charges_from_json(self, full_payment=None):
        """El alta de cargos sigue igual; ademas se ACTUALIZAN los importes de los ya existentes.

        Antes un cargo existente se salteaba entero, asi que el reintegro que MercadoPago informa
        despues del alta (`amounts.refunded`) no llegaba nunca a Odoo.
        """
        res = super().sync_charges_from_json(full_payment=full_payment)
        for payment in self:
            data = payment._meli_718_full_payment_dict(full_payment)
            if not isinstance(data, dict):
                continue
            by_id = {c.charge_id: c for c in payment.charge_ids if c.charge_id}
            for detail in data.get('charges_details') or []:
                charge = by_id.get(detail.get('id') or '')
                if not charge:
                    continue
                amounts = detail.get('amounts') or {}
                vals = {}
                for fname, key in (('amount_original', 'original'), ('amount_refunded', 'refunded')):
                    if key not in amounts:
                        continue
                    new = float(amounts.get(key) or 0.0)
                    if float_compare(new, charge[fname] or 0.0, precision_digits=2) != 0:
                        vals[fname] = new
                if vals:
                    charge.write(vals)
        return res

    # ------------------------------------------------------------------ reversion FEE/SHP
    def _meli_718_refund_amounts(self, config=None):
        """(comision devuelta, envio devuelto) segun los cargos de MercadoPago."""
        self.ensure_one()
        excluded = self._meli_718_excluded_fee_names(config=config)
        fee = shp = 0.0
        for c in self.charge_ids:
            refunded = c.amount_refunded or 0.0
            if refunded <= 0:
                continue
            if c.charge_type == 'fee':
                _n = (c.name or '').strip().lower()
                if _n.startswith(MELI_718_FINANCING_PREFIX) or _n in excluded:
                    continue
                fee += refunded
            elif c.charge_type == 'shipping':
                shp += refunded
        return fee, shp

    def _meli_718_is_pack_splitted(self):
        fn = getattr(self, '_meli_is_pack_splitted', None)
        try:
            return bool(fn and fn())
        except Exception:
            return False

    def _meli_718_ref_field(self):
        Payment = self.env['account.payment']
        return next((f for f in (acc_pay_ref, 'memo', 'ref') if f and f in Payment._fields), False)

    def _meli_718_rev_base(self, kind, so):
        return "%s OP %s %s-REV" % (so.name, self.payment_id, kind)

    def _meli_718_rev_payments(self, kind, so, original):
        """Todos los cobros REV VIGENTES de este pago y tipo: el vinculado + los encontrados por memo
        (el base `<venta> OP <op> FEE-REV` y los complementos `... FEE-REV #N`)."""
        Payment = self.env['account.payment'].sudo()
        link = MELI_718_LINK[kind]
        found = Payment.browse()
        current = self[link]
        if current and current.exists() and current.state not in MELI_718_DEAD:
            found |= current
        ref_field = self._meli_718_ref_field()
        if ref_field:
            base = self._meli_718_rev_base(kind, so)
            dom = [('payment_type', '=', 'inbound'), ('partner_id', '=', original.partner_id.id),
                   ('state', 'not in', list(MELI_718_DEAD)),
                   '|', (ref_field, '=', base), (ref_field, '=like', base + ' #%')]
            if 'company_id' in Payment._fields:
                dom.append(('company_id', '=', original.company_id.id))
            found |= Payment.search(dom)
        return found.sorted('id')

    def _meli_718_new_rev(self, kind, amount, original, so, communication, config=None):
        """Crea el cobro entrante (SIN publicar: la publicacion va aparte, ver _meli_718_post_rev)."""
        self.ensure_one()
        Payment = self.env['account.payment']
        vals = {
            'company_id': original.company_id.id,
            'partner_id': original.partner_id.id,
            'payment_type': 'inbound',
            'partner_type': 'supplier',
            'journal_id': original.journal_id.id,
            'currency_id': original.currency_id.id,
            'amount': amount,
            'meli_payment_id': self.id,
        }
        if 'date' in Payment._fields:
            vals['date'] = fields.Date.context_today(self)
        if 'payment_method_line_id' in Payment._fields and 'inbound_payment_method_line_ids' in original.journal_id._fields:
            line = original.journal_id.inbound_payment_method_line_ids[:1]
            if line:
                vals['payment_method_line_id'] = line.id
        ref_field = self._meli_718_ref_field()
        if ref_field:
            vals[ref_field] = communication
        if 'account.payment.group' in self.env:
            gvals = {
                'company_id': original.company_id.id,
                'partner_id': original.partner_id.id,
                'currency_id': original.currency_id.id,
                'partner_type': 'supplier',
                'payment_ids': [(0, 0, vals)],
            }
            Group = self.env['account.payment.group']
            if acc_pay_group_ref in Group._fields:
                gvals[acc_pay_group_ref] = communication
            if 'payment_on_account_amount' in Group._fields:
                gvals['payment_on_account_amount'] = amount
            group = Group.with_company(original.company_id).create(gvals)
            return group.payment_ids[:1]
        return Payment.with_company(original.company_id).create(vals)

    def _meli_718_set_draft_amount(self, rev, amount):
        rev.amount = amount
        group = 'payment_group_id' in rev._fields and rev.payment_group_id
        if group and 'payment_on_account_amount' in group._fields:
            group.payment_on_account_amount = amount

    def _meli_718_post_rev(self, rev, kind, so, config=None):
        """Publica un REV en borrador. NO usa versions.payment_post: ese helper traga toda excepcion y el
        REV quedaba en borrador, vinculado y sin aviso, y ninguna pasada lo volvia a intentar.
        Si falla: queda en borrador, se avisa UNA vez en la venta y la pasada siguiente reintenta."""
        if rev.state not in MELI_718_DRAFT:
            return True
        group = 'payment_group_id' in rev._fields and rev.payment_group_id
        try:
            with self.env.cr.savepoint():
                if group:
                    payment_group_post(group)
                else:
                    rev.action_post()
                if rev.state in MELI_718_DRAFT:
                    raise UserError("el cobro siguió en borrador después de publicarlo")
        except Exception as e:
            _logger.warning("MELI 718: OP %s %s-REV %s no se pudo publicar (queda en borrador, se reintenta en "
                            "la proxima pasada): %s", self.payment_id, kind, rev.id, e)
            tag = MELI_718_POST_TAG % (self.payment_id, kind, rev.id)
            Msg = self.env['mail.message'].sudo()
            if not Msg.search_count([('model', '=', so._name), ('res_id', '=', so.id), ('body', 'ilike', tag)]):
                _meli_718_post(so, "%s No se pudo publicar el cobro de devolución de %s %s (%.2f, OP %s): %s. "
                                   "Quedó en borrador; se reintenta en la próxima sincronización o se puede "
                                   "publicar a mano." % (tag, 'comisión' if kind == 'FEE' else 'envío',
                                                          rev.display_name, rev.amount, self.payment_id, e),
                               config=config)
            return False
        if not group and 'action_validate' in dir(rev) and rev.state == 'in_process':
            # mismo final que versions.payment_post (18: in_process -> paid); un fallo aca no deja borrador
            try:
                with self.env.cr.savepoint():
                    rev.action_validate()
            except Exception as e:
                _logger.info("MELI 718: OP %s %s-REV %s publicado; action_validate: %s", self.payment_id, kind, rev.id, e)
        return True

    def _meli_718_sync_rev(self, kind, target, original, so, config=None):
        """Deja la devolucion registrada IGUAL a `target` (ya topeado al original), sin duplicar.

        Parcial -> total: lo ya registrado (REV vigentes) se resta y solo se registra la DIFERENCIA:
        se ajusta el REV en borrador si lo hay; si no, un complemento `... <kind>-REV #N` por el delta.
        Un REV publicado no se modifica. Despues se publican (o reintentan) los REV en borrador si la
        config valida cobros. Devuelve el REV vinculado.
        """
        self.ensure_one()
        link = MELI_718_LINK[kind]
        revs = self._meli_718_rev_payments(kind, so, original)
        if revs and self[link] not in revs:
            self[link] = revs[0].id  # link perdido o apuntando a uno anulado: se re-vincula
        registered = sum(revs.mapped('amount'))
        delta = target - registered
        label = 'la comisión' if kind == 'FEE' else 'el envío'
        if float_compare(delta, 0.0, precision_digits=2) > 0:
            draft = revs.filtered(lambda p: p.state in MELI_718_DRAFT)[-1:]
            if draft:
                self._meli_718_set_draft_amount(draft, draft.amount + delta)
                _logger.info("MELI 718: OP %s %s-REV %s (borrador) ajustado a %.2f (total devuelto %.2f)",
                             self.payment_id, kind, draft.id, draft.amount, target)
            else:
                base = self._meli_718_rev_base(kind, so)
                memo = base if not revs else "%s #%d" % (base, len(revs) + 1)
                rev = self._meli_718_new_rev(kind, delta, original, so, memo, config=config)
                revs |= rev
                if not self[link]:
                    self[link] = rev.id
                _logger.info("MELI 718: OP %s %s-REV %.2f creado (%s, '%s') contra %s; total devuelto %.2f",
                             self.payment_id, kind, delta, rev.id, memo, original.id, target)
                _meli_718_post(so, "Mercado Libre devolvió %s: %.2f (OP %s, total devuelto %.2f). Registrado "
                                   "como cobro '%s'." % (label, delta, self.payment_id, target, memo), config=config)
        elif float_compare(delta, 0.0, precision_digits=2) < 0:
            _logger.warning("MELI 718: OP %s %s-REV registrado %.2f y ML informa %.2f devuelto: no se modifica, "
                            "revisar a mano.", self.payment_id, kind, registered, target)
        validate = self._get_ml_validate(config=config) if hasattr(self, '_get_ml_validate') else False
        if validate:
            for rev in revs.filtered(lambda p: p.state in MELI_718_DRAFT):
                self._meli_718_post_rev(rev, kind, so, config=config)
        return self[link]

    def _meli_revert_refunded_charges(self, config=None):
        """Registra la comision/envio que ML devolvio en un pago reintegrado o con contracargo.

        :return: dict {'FEE': account.payment|False, 'SHP': ...} con lo creado o re-vinculado.
        """
        done = {}
        for payment in self:
            if payment.status not in MELI_718_REFUND_STATUSES:
                continue
            if not payment._meli_718_setting('meli_refund_revert_charges', False, config=config):
                continue
            if payment._meli_718_is_pack_splitted():
                # #caso-K74: el pack partido de FULL no es una devolucion (ML re-crea el pack con otro pago)
                continue
            so = payment._get_ml_customer_order() if hasattr(payment, '_get_ml_customer_order') else False
            if not so:
                continue
            fee_ref, shp_ref = payment._meli_718_refund_amounts(config=config)
            for kind, refunded, original in (
                    ('FEE', fee_ref, payment.account_supplier_payment_id),
                    ('SHP', shp_ref, payment.account_supplier_payment_shipment_id)):
                if float_is_zero(refunded, precision_digits=2):
                    continue
                if not original or not original.exists() or original.state in MELI_718_DEAD:
                    _logger.info("MELI 718: OP %s devuelve %s %.2f pero no hay pago %s original vigente: "
                                 "no se registra devolucion.", payment.payment_id, kind, refunded, kind)
                    continue
                amount = min(refunded, original.amount or 0.0)
                if float_compare(refunded, original.amount or 0.0, precision_digits=2) > 0:
                    _logger.warning("MELI 718: OP %s %s devuelto %.2f > pago original %.2f: se registra el "
                                    "importe del original.", payment.payment_id, kind, refunded, original.amount)
                try:
                    with self.env.cr.savepoint():
                        done[(payment.id, kind)] = payment._meli_718_sync_rev(kind, amount, original, so, config=config)
                except Exception as e:
                    _logger.warning("MELI 718: OP %s no se pudo registrar %s-REV %.2f: %s",
                                    payment.payment_id, kind, amount, e, exc_info=True)
                    _meli_718_post(so, "No se pudo registrar la devolución de %s (OP %s): %s" % (
                        'comisión' if kind == 'FEE' else 'envío', payment.payment_id, e), config=config)
        return done


def _meli_718_setting_for(record, field, default=None, config=None):
    for source in (config,
                   config and 'company_id' in config._fields and config.company_id,
                   record.env.company):
        if source and field in source._fields and source[field]:
            return source[field]
    return default


def _meli_718_already_reversed(inv):
    if 'payment_state' in inv._fields and inv.payment_state == 'reversed':
        return True
    for fname in ('reversal_move_ids', 'reversal_move_id'):
        if fname in inv._fields and inv[fname].filtered(lambda r: r.state not in ('cancel',)):
            return True
    return False


class SaleOrderMejoras718(models.Model):
    _inherit = 'sale.order'

    def _meli_718_nc_draft(self, config=None):
        return bool(_meli_718_setting_for(self, 'meli_refund_credit_note_draft', False, config=config))

    def _meli_718_fully_refunded(self):
        """True si TODOS los pagos ML de la venta quedaron reintegrados total (y al menos uno)."""
        self.ensure_one()
        pays = self.env['mercadolibre.payments']
        for morder in self.meli_orders:
            if 'payments' in morder._fields:
                pays |= morder.payments
        if not pays:
            return False
        live = pays.filtered(lambda p: p.status not in ('cancelled', 'rejected'))
        if not live or any(p.status != 'refunded' for p in live):
            return False
        return not any(p._meli_718_is_pack_splitted() for p in live)

    def _meli_718_refund_credit_notes(self, config=None):
        """NC EN BORRADOR por cada factura publicada de una venta reintegrada total. Devuelve las NC."""
        created = self.env['account.move']
        for so in self:
            if not so._meli_718_nc_draft(config=config) or not so._meli_718_fully_refunded():
                continue
            invoices = so.invoice_ids.filtered(
                lambda i: i.state == 'posted' and i.move_type == 'out_invoice' and not _meli_718_already_reversed(i))
            for inv in invoices:
                try:
                    with self.env.cr.savepoint():
                        wiz = self.env['account.move.reversal'].with_context(
                            active_model='account.move', active_ids=inv.ids).create({
                                'journal_id': inv.journal_id.id,
                                'reason': 'Reembolso de MercadoLibre',
                            })
                        fn = getattr(wiz, 'refund_moves', None) or getattr(wiz, 'reverse_moves')
                        res = fn()
                        nc = self.env['account.move']
                        if isinstance(res, dict) and res.get('res_id'):
                            nc = self.env['account.move'].browse(res['res_id'])
                        if not nc:
                            for fname in ('reversal_move_ids', 'reversal_move_id'):
                                if fname in inv._fields and inv[fname]:
                                    nc = inv[fname].sorted('id')[-1:]
                                    break
                        if nc and nc.state != 'draft':
                            _logger.warning("MELI 718: la NC %s de %s no quedo en borrador (%s)", nc.id, inv.name, nc.state)
                        created |= nc
                        _meli_718_post(so, "Mercado Libre reintegró el pago: nota de crédito %s creada EN BORRADOR "
                                           "para la factura %s. Revisarla y validarla." % (nc.name or nc.id, inv.name),
                                       config=config)
                except Exception as e:
                    _logger.warning("MELI 718: NC borrador para %s (%s): %s", inv.name, so.name, e, exc_info=True)
                    _meli_718_post(so, "No se pudo crear la nota de crédito en borrador para %s: %s. Gestionar a mano."
                                   % (inv.name, e), config=config)
        return created

    def _meli_718_revert_refunds(self, config=None):
        for so in self:
            so_config = config
            for morder in so.meli_orders:
                pays = morder.payments.filtered(lambda p: p.status in MELI_718_REFUND_STATUSES) \
                    if 'payments' in morder._fields else self.env['mercadolibre.payments']
                for pay in pays:
                    # La orden cancelada entra por meli_cancel_with_detail(cancel_msg) SIN config: sin
                    # resolverla, _get_ml_validate(None)=False y el REV nacia en borrador para siempre.
                    cfg = config or (hasattr(pay, '_get_config') and pay._get_config()) or None
                    so_config = so_config or cfg
                    try:
                        with self.env.cr.savepoint():
                            pay.sync_charges_from_json()
                            pay._meli_revert_refunded_charges(config=cfg)
                    except Exception as e:
                        _logger.warning("MELI 718: devolucion FEE/SHP de %s / OP %s: %s",
                                        so.name, pay.payment_id, e, exc_info=True)
            so._meli_718_refund_credit_notes(config=so_config)

    def confirm_ml(self, meli=None, config=None):
        res = super().confirm_ml(meli=meli, config=config)
        self._meli_718_revert_refunds(config=config)
        return res

    def meli_cancel_with_detail(self, *args, **kwargs):
        # La orden cancelada en ML suele entrar por aca y NO por confirm_ml (orders_update_order).
        res = super().meli_cancel_with_detail(*args, **kwargs)
        self._meli_718_revert_refunds(config=kwargs.get('config'))
        return res
