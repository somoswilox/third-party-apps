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
import re

from datetime import timedelta
from datetime import datetime as _datetime  # alias: los `import *` de abajo re-ligan `datetime`

from .product_sku_rule import *
from odoo.addons.meli_oerp.models.versions import *
from odoo.exceptions import UserError as _MeliUserError, ValidationError as _MeliValidationError

class _MeliCloseNotClosed(Exception):
    """Interno del barrido un caso: fuerza el rollback del savepoint de un pedido
    cuando `meli_deliver` reportó errores en `res['errors']`."""



try:
    import inspect as _inspect
    # 26.394: `routine` (modo 'important') existe desde meli_oerp 26.394; con uno anterior no se pasa.
    _MELI_POST_HAS_ROUTINE = 'routine' in _inspect.signature(meli_message_post).parameters
except Exception:
    _MELI_POST_HAS_ROUTINE = False


def _meli_stock_post_once(order, body, config, once_key):
    """26.394 (un caso): aviso de almacén UNA vez por venta+almacén, respetando
    mercadolibre_notification_mode (lo hace meli_message_post). Es aviso de RUTINA: con el
    modo 'important' va sólo al log.

    Guarda de legado LOCAL (no usa el `legacy_text` de meli_oerp 26.394) para que este
    módulo no exija un meli_oerp nuevo: si la venta ya tiene el texto sin marca (ventas
    anteriores a 26.394), no se repostea."""
    try:
        if order.id and order.env['mail.message'].sudo().search_count([
                ('model', '=', order._name), ('res_id', '=', order.id),
                ('body', 'like', body)], limit=1):
            _logger.debug("ML(stock) aviso ya presente en %s: %s", order.name, body)
            return
    except Exception as e:
        _logger.warning("ML(stock) legacy check failed on %s: %s", order.id, e)
    kw = {'routine': True} if _MELI_POST_HAS_ROUTINE else {}
    meli_message_post(order, body, config=config, once_key=once_key, **kw)


class SaleOrder(models.Model):

    _inherit = "sale.order"

    # FIX un caso v2 — rotación del barrido de cierre: último intento (ok, error o
    # salteado). El barrido excluye los intentados hace menos de 24 h y prioriza
    # los nunca intentados, así un bloque que falla siempre (p.ej. por
    # stock_no_negative) no ocupa el lote entero en cada corrida.
    meli_close_attempt_date = fields.Datetime(
        string="ML: último intento de cierre de entrega",
        copy=False, readonly=True, index=True,
        help="Técnico (barrido): fecha del último intento automático de "
             "cerrar las entregas de un pedido ya entregado en MercadoLibre.")

    def _meli_order_update( self, config=None, data=None ):
        #_logger.info("_meli_order_update")
        for order in self:

            wh_id = order._meli_get_warehouse_id(config=config)

            if wh_id and order.warehouse_id!=wh_id:
                # FIX un caso (un cliente, tickets un caso): el patron MeliRollback
                # (orders.py orders_update_order) revierte el write del warehouse y la 2da
                # llamada re-posteaba -> spam. La asignacion se MANTIENE, pero el mensaje se
                # postea solo si no hay ya uno identico reciente (slice acotado por performance).
                # 26.394 (un caso): la guarda miraba sólo los últimos 20 mensajes ⇒ cuando el
                # chatter crecía el aviso volvía a salir en cada sync. Ahora: una vez por venta y
                # almacén (once_key + guarda de legado para ventas viejas sin marca).
                _wh_msg = "ML(stock): Almacen; asignando: "+str(wh_id and wh_id.name)
                _meli_stock_post_once(order, _wh_msg, config, "stock-wh-%s-%s" % (order.id, wh_id.id))
                order.warehouse_id = wh_id

            #is_full = 'order_json' in data
            if ((order.meli_shipment and order.meli_shipment.logistic_type == "fulfillment")
                or order.meli_shipment_logistic_type=="fulfillment"):
                #seleccionar almacen para la orden
                wh_id = order._meli_get_warehouse_id(config=config)
                if wh_id and order.warehouse_id!=wh_id:
                    # FIX un caso: mismo guard de idempotencia que arriba (patron MeliRollback).
                    _wh_msg = "ML(stock): Almacen; asignando para fulfillment: "+str(wh_id and wh_id.name)
                    _meli_stock_post_once(order, _wh_msg, config, "stock-wh-full-%s-%s" % (order.id, wh_id.id))
                    order.warehouse_id = wh_id

            order_type = self.env["mercadolibre.orders"].get_sale_order_type( config=config, sale_order=order, shipment=(order and order.meli_shipment) )
            if order_type and "type_id" in order_type and "type_id" in order._fields:
                order.type_id = order_type["type_id"]
                #_logger.info("order_type:"+str(order_type))

    def _old_meli_deliver( self, meli=None, config=None, data=None):
        #_logger.info("meli_deliver stock")
        res = {}
        if getattr(config._fields, 'mercadolibre_stock_mrp_production_process', False) and config.mercadolibre_stock_mrp_production_process:
            self.meli_produce(meli=meli, config=config, data=data)

        for spick in self.picking_ids:
            try:
                if spick.state == 'draft':
                    spick.action_confirm()

                if (spick.state in ['confirmed','waiting','draft']):
                    spick.action_assign()

                if spick.move_line_ids and not (spick.state in ['done','cancel']):
                    stock_picking_set_quantities(picking=spick)

                if not (spick.state in ['done','cancel']):
                    spick.button_validate()

            except Exception as e:
                _logger.error(f"[meli_deliver] Error procesando picking {spick.name} ({spick.id}): {e}")
                _logger.info(e, exc_info=True)
                res = {'error': str(e)}
                # Si quieres saltar al siguiente picking en vez de abortar todo, descomenta:
                # continue
                break

        return res
        
    def meli_deliver(self, meli=None, config=None, data=None):
        """
        Valida automáticamente pickings de entrega a cliente (OUT),
        excluyendo devoluciones y recepciones. Fuerza qty_done si no hay reservas.
        """
        res = {}

        # 1) Si corresponde, producir antes de entregar
        if getattr(config._fields, 'mercadolibre_stock_mrp_production_process', False) and config.mercadolibre_stock_mrp_production_process:
            try:
                self.meli_produce(meli=meli, config=config, data=data)
            except Exception as e:
                _logger.error("[meli_deliver] Error en meli_produce: %s", e, exc_info=True)
                # seguimos, no abortamos la entrega

        def _is_return(picking):
            """True si alguno de los movimientos fue creado como devolución."""
            # move_ids_without_package fue eliminado en Odoo 17; move_ids cubre el mismo caso
            moves = getattr(picking, 'move_ids_without_package', None) or picking.move_ids
            return any(moves.mapped('origin_returned_move_id'))

        def _force_qty_done(picking):
            """
            Odoo 16–19: asegura qty_done > 0 para poder validar el picking.
            - Completa qty_done en move lines existentes usando la cantidad planificada del move.
            - Si un move no tiene move lines, crea una con qty_done = product_uom_qty del move.
            Devuelve True si realizó cambios.
            Nota: si el producto requiere lote/serie, esta función no asigna lot_id/lot_name.
            """
            wrote = False
            env = picking.env
            StockMoveLine = env['stock.move.line']

            # Helper seguro para convertir unidades
            def _uom_convert(qty, from_uom, to_uom):
                if not qty:
                    return 0.0
                if from_uom and to_uom and from_uom != to_uom:
                    return from_uom._compute_quantity(qty, to_uom)
                return qty or 0.0

            # --- 1) Completar qty_done en líneas existentes ---
            # En Odoo 19 qty_done fue renombrado a quantity en stock.move.line
            _qty_field = 'quantity' if hasattr(StockMoveLine, 'quantity') and not hasattr(StockMoveLine, 'qty_done') else 'qty_done'
            for ml in picking.move_line_ids:
                if not getattr(ml, _qty_field, 0.0):
                    move = ml.move_id
                    planned_qty = getattr(move, 'product_uom_qty', 0.0) or 0.0
                    move_uom = getattr(move, 'product_uom', False)
                    line_uom = getattr(ml, 'product_uom_id', False) or move_uom
                    setattr(ml, _qty_field, _uom_convert(planned_qty, move_uom, line_uom))
                    wrote = True

            # --- 2) Crear move lines cuando el move no tiene ninguna (sin reserva) ---
            # move_ids_without_package fue eliminado en Odoo 17; usar move_ids
            _moves_src = getattr(picking, 'move_ids_without_package', None) or picking.move_ids
            for mv in _moves_src.filtered(lambda m: not m.move_line_ids and (getattr(m, 'product_uom_qty', 0.0) > 0.0)):
                qty = mv.product_uom_qty
                vals = {}

                # _prepare_move_line_vals existe en 16–19, pero su firma puede variar (acepta quantity)
                prep = getattr(mv, '_prepare_move_line_vals', None)
                if callable(prep):
                    try:
                        vals = prep(quantity=qty) or {}
                    except TypeError:
                        # Por compatibilidad si no acepta 'quantity'
                        vals = prep() or {}

                # Reforzar campos críticos
                vals.update({
                    _qty_field: qty,
                    'location_id': mv.location_id.id,
                    'location_dest_id': mv.location_dest_id.id,
                    'product_uom_id': mv.product_uom.id,
                    'product_id': mv.product_id.id,
                    'picking_id': picking.id,
                    'move_id': mv.id,
                })

                StockMoveLine.create(vals)
                wrote = True

            # --- 3) Recalcular estado del picking si hicimos cambios ---
            if wrote and hasattr(picking, '_recompute_state'):
                picking._recompute_state()

            return wrote


        # 2) Filtramos pickings a procesar: sólo OUT a cliente, no returns, no done/cancel
        def _has_crossdock(p):
            _moves = getattr(p, 'move_ids_without_package', None) or p.move_ids
            rules = _moves.mapped('rule_id.route_id.name')
            joined = ' | '.join(rules).lower()
            return ('cross dock' in joined) or ('comprar' in joined) or ('buy' in joined) 

        # ... dentro del filtrado:
        pickings = self.picking_ids.filtered(lambda p:
            p.state not in ('done','cancel') and
            p.picking_type_id.code == 'outgoing' and
            p.location_id.usage in ('internal','transit') and
            p.location_dest_id.usage == 'customer' and
            not _is_return(p) and
            not _has_crossdock(p)        # ⟵ evita validar pickings nacidos de esa ruta
        )

        skipped = self.picking_ids - pickings
        for sp in skipped:
            _logger.debug(
                "[meli_deliver] Omitido %s (%s): state=%s, type=%s, from=%s, to=%s, is_return=%s",
                sp.name, sp.id, sp.state,
                getattr(sp.picking_type_id, 'code', None),
                getattr(sp.location_id, 'usage', None),
                getattr(sp.location_dest_id, 'usage', None),
                _is_return(sp),
            )

        # 3) Procesamos cada OUT seguro
        # FIX un caso v2 (savepoint): cada picking corre dentro de un SAVEPOINT. Si
        # `button_validate` falla a mitad de camino (caso típico: stock_no_negative
        # "would become negative"), la escritura parcial del quant, el heal de
        # reservas (un caso) y el qty_done forzado quedaban sucios en la transacción y
        # el `cr.commit()` de quien llamó (barrido un caso, cron de órdenes) los
        # persistía: el stock bajaba SIN ningún move done (un cliente, 28-sep-2026).
        # Al salir por excepción, el savepoint hace `cr.clear()` (descarta el cache
        # sucio) + ROLLBACK TO SAVEPOINT: ese picking queda exactamente como estaba.
        for spick in pickings:
            try:
                with self.env.cr.savepoint():
                    _logger.debug("[meli_deliver] Procesando %s (%s) state=%s", spick.name, spick.id, spick.state)

                    # Confirmar si está en borrador
                    if spick.state == 'draft':
                        spick.action_confirm()

                    # Asignar si está confirmado/en espera (reserva si hay stock)
                    if spick.state in ('confirmed', 'waiting'):
                        spick.action_assign()

                    # --- FIX 26.381 (6-nov-2026): reserva SIN lote de un producto con lote/serie
                    # (legado de versiones sin savepoint). Ver stock.picking._meli_heal_lotless_reserve.
                    if spick.state not in ('done', 'cancel'):
                        spick._meli_heal_lotless_reserve()

                    # --- FIX un caso v2: sanear reservas fantasma antes de validar ---
                    # Lógica canónica extraída al helper stock.picking._meli_heal_phantom_reserve
                    # (ver models/stock_location.py). Detecta desync ML↔quant
                    # (move_line.reserved > stock_quant.reserved_quantity), intenta
                    # do_unreserve+action_assign y, si el guard de _action_done lo impide,
                    # alinea el quant vía SQL (fallback robusto). El MISMO helper corre en
                    # el override de button_validate para cubrir el cierre MANUAL del UI.
                    # FIX cierre sin stock (29-oct-2026): ¿la cantidad hecha la puso ESTE
                    # cierre automático? Ver _meli_heal_phantom_reserve (guarda del operador).
                    _auto_qty = False
                    if spick.state not in ('done', 'cancel'):
                        spick._meli_heal_phantom_reserve()

                    # Si sigue sin cantidades hechas, forzamos qty_done
                    if spick.state not in ('done', 'cancel'):
                        # Si no hay qty_done en ninguna línea, lo forzamos
                        _qf = 'quantity' if not hasattr(spick.move_line_ids[:1], 'qty_done') else 'qty_done'
                        all_zero = all(not getattr(ml, _qf, 0.0) for ml in spick.move_line_ids)
                        if all_zero or not spick.move_line_ids:
                            changed = _force_qty_done(spick)
                            _auto_qty = bool(changed)
                            _logger.info("[meli_deliver] %s qty_done %s", spick.name, "forzado" if changed else "no requerido")

                    # Validar evitando wizards (backorder / immediate transfer)
                    if spick.state not in ('done', 'cancel'):
                        # FIX cierre sin stock: si la cantidad la forzó este cierre, el saneo del
                        # override de button_validate NO la toma como carga del operador.
                        spick.with_context(skip_backorder=True, skip_immediate=True,
                                           meli_deliver_forced_qty=_auto_qty).button_validate()
                        _logger.info("[meli_deliver] Validado %s (%s)", spick.name, spick.id)

            except Exception as e:
                # [caso-K02, 26.307] Una REGLA DE NEGOCIO (UserError/ValidationError: típicamente falta de
                # stock con stock negativo bloqueado) no es un error de código: WARNING sin traceback.
                # En caso-K02 el barrido de cierre dejó 46 ERROR + traceback en una sola corrida por esto.
                _business = isinstance(e, (_MeliUserError, _MeliValidationError))
                if _business:
                    _logger.warning("[meli_deliver] %s (%s) no validado (regla de negocio): %s",
                                    spick.name, spick.id, e)
                else:
                    _logger.error("[meli_deliver] Error procesando %s (%s): %s", spick.name, spick.id, e)
                    _logger.info(e, exc_info=True)
                # El savepoint ya revirtió TODO lo de este picking (quant, reservas,
                # qty_done). Registramos y seguimos con el resto; quien llama DEBE
                # mirar res['errors'] (el barrido un caso lo cuenta como error).
                res.setdefault('errors', []).append({'picking': spick.name, 'id': spick.id, 'error': str(e),
                                                     'business': _business})
                continue

        return res

    # ------------------------------------------------------------------
    # FIX un caso — cierre de entregas ML que quedaron abiertas post-`delivered`
    # ------------------------------------------------------------------
    def _meli_sweep_config(self):
        """Config EFECTIVA del pedido para el barrido de cierre.

        Mismo criterio que el dispatcher multi-cuenta (`account.configuration or
        account.company_id`): manda la `mercadolibre.configuration` de la cuenta ML,
        y recién si no hay, la compañía.

        ⚠️ CUIDADO AL TOCAR ESTO: los campos homónimos de `res.company`
        (`mercadolibre_order_confirmation*`) son LEGACY y en instalaciones reales
        quedan en `manual`/vacío mientras la config viva está en la
        `mercadolibre.configuration` de la cuenta. Si esta resolución cae a la
        compañía cuando no debe, el barrido se auto-apaga en silencio (verificado en
        un cliente: compañía `manual` vs configuración `paid_confirm_shipped_deliver`).
        Por eso se busca la cuenta por tres caminos antes de rendirse.
        """
        self.ensure_one()
        account = False
        # 1) campo propio del pedido (si algún módulo lo agrega)
        if 'connection_account' in self._fields:
            account = self.connection_account
        # 2) camino real en meli_oerp_multiple: la cuenta vive en la orden ML
        if not account and self.meli_orders:
            mo = self.meli_orders[:1]
            if 'connection_account' in mo._fields:
                account = mo.connection_account
        # 3) mono-cuenta: si la compañía tiene UNA sola cuenta ML, es esa
        if not account:
            Account = self.env.get('mercadolibre.account')
            if Account is not None:
                accounts = Account.sudo().search(
                    [('company_id', '=', (self.company_id or self.env.user.company_id).id)], limit=2)
                if len(accounts) == 1:
                    account = accounts
        config = (account and getattr(account, 'configuration', False)) or False
        return config or self.company_id or self.env.user.company_id

    def _meli_delivery_on_delivered_enabled(self, config):
        """True si la config del cliente pide entregar cuando ML ya entregó.

        El barrido NO cambia la política del cliente: sólo termina lo que su propia
        configuración ya pide. Si entrega a mano (`manual`), no hace nada.
        Cubre las dos familias de opciones que disparan `meli_deliver`:
          - `mercadolibre_order_confirmation_delivery[_full]` (`confirm_ml_stock`):
            `paid_confirm_deliver` / `paid_confirm_shipped_deliver`
          - `mercadolibre_order_confirmation[_full]` (`confirm_ml`): `paid_delivered`
        """
        self.ensure_one()
        is_full = (self.meli_shipment_logistic_type == "fulfillment")

        def _val(name):
            return (name in config._fields and config[name]) or ""

        deli = _val("mercadolibre_order_confirmation_delivery_full" if is_full
                    else "mercadolibre_order_confirmation_delivery")
        conf = _val("mercadolibre_order_confirmation_full" if is_full
                    else "mercadolibre_order_confirmation")
        return ("paid_confirm_deliver" in deli
                or "paid_confirm_shipped_deliver" in deli
                or "paid_delivered" in conf)

    # Parámetros del barrido (ir.config_parameter). Se leen en cada corrida:
    # cambiarlos no requiere -u ni reinicio.
    _MELI_CLOSE_DAYS_PARAM = 'meli_oerp_stock.close_delivered_days'
    _MELI_CLOSE_LIMIT_PARAM = 'meli_oerp_stock.close_delivered_limit'
    _MELI_CLOSE_DAYS_DEFAULT = 180
    _MELI_CLOSE_LIMIT_DEFAULT = 100
    _MELI_CLOSE_RETRY_HOURS = 24

    def _meli_close_param(self, key, default):
        raw = self.env['ir.config_parameter'].sudo().get_param(key)
        try:
            val = int(raw) if raw not in (None, False, '') else default
        except (TypeError, ValueError):
            _logger.warning("[meli_close_delivered] parámetro %s=%r inválido, uso %s", key, raw, default)
            val = default
        return val if val > 0 else default

    @api.model
    def _meli_close_delivered_candidates(self, days, limit):
        """Pedidos entregados en ML con alguna salida ML todavía abierta.

        Lote ROTATIVO (FIX un caso v2): excluye los intentados hace menos de
        `_MELI_CLOSE_RETRY_HOURS` y prioriza los nunca intentados; dentro de cada
        grupo, el más viejo primero. Antes el orden era sólo `date_order asc`
        con `limit`: los mismos pedidos que fallan siempre (stock_no_negative)
        ocupaban el lote entero y el resto nunca se procesaba.
        """
        now = fields.Datetime.now()
        cutoff = now - timedelta(days=days)
        retry_cutoff = now - timedelta(hours=self._MELI_CLOSE_RETRY_HOURS)
        candidates = self.env['sale.order'].sudo().search([
            ('state', 'in', ('sale', 'done')),
            ('meli_order_id', '!=', False),
            ('meli_status', 'not in', ('cancelled', 'invalid')),
            ('meli_shipment.status', '=', 'delivered'),
            ('date_order', '>=', cutoff),
            # prefiltro barato en SQL (positivo = "algún picking abierto"); el
            # criterio real es `_meli_is_ml_out` más abajo.
            ('picking_ids.state', 'in', ('draft', 'waiting', 'confirmed', 'assigned')),
            '|', ('meli_close_attempt_date', '=', False),
                 ('meli_close_attempt_date', '<', retry_cutoff),
        ], order='date_order asc, id asc')
        candidates = candidates.sorted(key=lambda o: (
            bool(o.meli_close_attempt_date),
            o.meli_close_attempt_date or _datetime.min,
            o.date_order or _datetime.min,
            o.id,
        ))
        # Filtro real en Python: `_meli_is_ml_out` es el mismo criterio que usa
        # `meli_deliver` (outgoing, interno/tránsito → cliente, no devolución, no
        # crossdock), así que no hay riesgo de validar un picking que meli_deliver
        # después descartaría.
        todo = self.env['sale.order'].sudo()
        for order in candidates:
            if any(p._meli_is_ml_out() for p in order.picking_ids):
                todo |= order
            if len(todo) >= limit:
                break
        return todo, len(candidates)

    @api.model
    def _meli_close_delivered_process(self, orders, commit=True):
        """Intenta cerrar las entregas de `orders`, un pedido por vez.

        Cada pedido corre en un SAVEPOINT: si `meli_deliver` reporta CUALQUIER
        error en `res['errors']` (o levanta), se revierte el pedido COMPLETO y se
        cuenta como error — nunca como cerrado. Luego se sella
        `meli_close_attempt_date` (también en error y salteado) para que el lote
        rote. `commit=True` (cron) commitea pedido a pedido; los tests pasan
        `commit=False`.
        """
        cr = self.env.cr
        ok = errors = skipped = blocked = 0
        failed = []
        blocked_names = []
        for order in orders:
            status = 'error'
            detail = ''
            business = False
            try:
                with cr.savepoint():
                    config = order._meli_sweep_config()
                    if not order._meli_delivery_on_delivered_enabled(config):
                        status = 'skipped'
                    else:
                        res = order.meli_deliver(config=config) or {}
                        errs = res.get('errors') or []
                        if errs:
                            business = all(e.get('business') for e in errs)
                            detail = '; '.join("%s: %s" % (e.get('picking'), str(e.get('error'))[:200])
                                               for e in errs[:3])
                            # revierte el pedido entero (defensa en profundidad:
                            # meli_deliver ya revirtió cada picking fallido)
                            raise _MeliCloseNotClosed(detail)
                        status = 'ok'
            except _MeliCloseNotClosed:
                status = 'error'
            except Exception as e:
                status = 'error'
                detail = str(e)[:300]
                business = isinstance(e, (_MeliUserError, _MeliValidationError))
            if status == 'ok':
                ok += 1
                _logger.info("[meli_close_delivered] cerrado %s", order.name)
            elif status == 'skipped':
                skipped += 1
            else:
                errors += 1
                failed.append(order.id)
                if business:
                    # [caso-K02, 26.307] falta de stock u otra regla de negocio: se reintenta en
                    # _MELI_CLOSE_RETRY_HOURS; va al resumen de abajo, no un ERROR por pedido.
                    blocked += 1
                    blocked_names.append(order.name)
                    _logger.debug("[meli_close_delivered] %s no cerrado (regla de negocio): %s",
                                  order.name, detail)
                else:
                    _logger.error("[meli_close_delivered] %s NO cerrado (revertido): %s", order.name, detail)
            try:
                with cr.savepoint():
                    order.with_context(tracking_disable=True).write(
                        {'meli_close_attempt_date': fields.Datetime.now()})
            except Exception as e:
                _logger.error("[meli_close_delivered] no pude sellar el intento de %s: %s", order.name, e)
            if commit:
                cr.commit()
        if blocked:
            _logger.warning(
                "[meli_close_delivered] %s pedidos sin cerrar por regla de negocio (p.ej. falta de "
                "stock); revertidos, se reintentan en %sh: %s%s", blocked, self._MELI_CLOSE_RETRY_HOURS,
                ', '.join(blocked_names[:20]), ' …' if len(blocked_names) > 20 else '')
        return {'processed': ok, 'errors': errors, 'skipped': skipped, 'blocked': blocked,
                'failed_order_ids': failed}

    @api.model
    def cron_meli_close_delivered_pickings(self, days=None, limit=None):
        """FIX un caso — cierra las entregas ML que quedaron abiertas después de que
        MercadoLibre marcó el envío como `delivered`.

        AGUJERO QUE TAPA: `meli_deliver()` sólo corre cuando el conector procesa el
        pedido (`confirm_ml` / `confirm_ml_stock`) y el envío ya figura entregado. Si
        el pedido entra a Odoo ANTES de que ML lo marque `delivered`, después **nadie
        lo vuelve a mirar**: el sweep de importación va `date_desc` (ya no lo alcanza)
        y `orders_resync_status` lo EXCLUYE por diseño (`shipment_status not in
        ('delivered',)`, un caso). El picking de salida queda `assigned` para siempre
        reteniendo la reserva, y el cliente ve "cantidades reservadas que no se liberan".

        SIN COSTO DE API: trabaja sólo con datos que ya están en Odoo.

        - Respeta la config del cliente (`_meli_delivery_on_delivered_enabled`): si
          entrega a mano, el barrido no hace nada.
        - Idempotente: `meli_deliver` saltea lo que ya está `done`/`cancel`.
        - FIX un caso v2 (28-sep-2026, un cliente): un pedido con CUALQUIER error en
          `meli_deliver` se revierte entero y se cuenta como error (antes se
          commiteaba y contaba "cerrado": el quant bajaba sin move done). El log
          final es honesto: cerrados / errores / salteados.
        - Lote rotativo: ver `_meli_close_delivered_candidates`.

        Ventana y lote por `ir.config_parameter` (sin -u):
          - `meli_oerp_stock.close_delivered_days`  (default 180)
          - `meli_oerp_stock.close_delivered_limit` (default 100)
        El default de 180 días cubre backlogs viejos; el costo lo acota el lote
        rotativo + el prefiltro SQL de pickings abiertos. Los argumentos explícitos
        mandan sobre los parámetros, p.ej. desde `odoo shell`:
            env['sale.order'].cron_meli_close_delivered_pickings(days=365, limit=500)
        """
        if not days:
            days = self._meli_close_param(self._MELI_CLOSE_DAYS_PARAM, self._MELI_CLOSE_DAYS_DEFAULT)
        if not limit:
            limit = self._meli_close_param(self._MELI_CLOSE_LIMIT_PARAM, self._MELI_CLOSE_LIMIT_DEFAULT)

        todo, n_candidates = self._meli_close_delivered_candidates(days, limit)
        if not todo:
            _logger.info("[meli_close_delivered] nada para cerrar "
                         "(candidatos entregados con salida abierta en %s días, fuera de "
                         "reintento: %s)", days, n_candidates)
            return {'processed': 0, 'errors': 0, 'skipped': 0, 'blocked': 0, 'failed_order_ids': []}

        _logger.info("[meli_close_delivered] %s pedidos entregados en ML con la entrega "
                     "abierta (de %s candidatos en %s días) — procesando",
                     len(todo), n_candidates, days)
        result = self._meli_close_delivered_process(todo, commit=True)
        _logger.info("[meli_close_delivered] fin — cerrados=%s errores=%s (de ellos por regla de "
                     "negocio=%s) salteados_por_config=%s", result['processed'], result['errors'],
                     result['blocked'], result['skipped'])
        return result

    @api.model
    def _meli_close_delivered_cron_repair(self):
        """[caso-K02, 26.307] El cron de cierre nació ONE-SHOT en 16/17.

        El XML no declaraba `numbercall` y en 16/17 `ir.cron.numbercall` vale 1 por defecto: tras
        la primera corrida Odoo lo deja `numbercall=0, active=False` (odoo/<v>/odoo/addons/base/
        models/ir_cron.py, "active = active and bool(call_count_left)"). El registro es
        `noupdate`, así que el `-u` no lo corrige: lo hace la migración llamando a esto.

        - `numbercall=0` + inactivo = lo apagó Odoo al agotarse ⇒ recurrente y activo otra vez.
        - `numbercall>0` ⇒ recurrente; `active` queda como esté (si lo apagó alguien, sigue apagado).
        - 18+ no tiene `numbercall` (el cron es recurrente siempre) ⇒ no-op.
        Devuelve los valores escritos, o False si no había nada que hacer.
        """
        cron = self.env.ref('meli_oerp_stock.ir_cron_meli_close_delivered_pickings',
                            raise_if_not_found=False)
        if not cron or 'numbercall' not in cron._fields:
            return False
        cron = cron.sudo().with_context(active_test=False)
        if cron.numbercall < 0:
            return False
        vals = {'numbercall': -1}
        if cron.numbercall == 0 and not cron.active:
            vals['active'] = True
        cron.write(vals)
        _logger.info("[meli_close_delivered] cron %s reparado: %s", cron.id, vals)
        return vals

    def meli_produce( self, meli=None, config=None, data=None):
        #_logger.info("meli_produce")
        order = self
        productions = self.env['mrp.production'].search( [ ('origin','=',order.name), ('state', 'not in', ['draft','done','cancel']) ])
        if productions:
            for prod in productions:
                _logger.info("meli_produce "+str(prod.name))
                if prod.reservation_state in ['confirmed']:
                    _logger.info("meli_produce (confirmed) action_assign")
                    res = prod.action_assign()
                    _logger.info("meli_produce (confirmed) action_assign res:"+str(res))

                if prod.reservation_state in ['assigned']:
                    _logger.info("meli_produce (assigned) open_produce_product")
                    res = prod.open_produce_product()
                    _logger.info("meli_produce (confirmed) open_produce_product res:"+str(res))

                if prod.state in ['to_close']:
                    _logger.info("meli_produce (to_close) button_mark_down")
                    res = prod.button_mark_done()
                    _logger.info("meli_produce (to_close) button_mark_down res:"+str(res))


    def _meli_get_stock_location_from_mapping( self, account=None ):
        """Surtido multi-almacén por depósito ML (OPT-IN, fallback-preservador).

        La orden ML trae el depósito logístico de origen a nivel ítem
        (Item['stock'] = {store_id, node_id}), persistido por línea en
        mercadolibre.order_items.meli_stock_node_id / meli_stock_store_id (meli_oerp).
        Se cruza contra la tabla de mapeo mercadolibre.account.stock_location
        (network_node_id <- node_id ; meli_store_id <- store_id) y, si el nodo está
        mapeado a una ubicación Odoo (odoo_location_id seteado), se devuelve esa
        stock.location.

        Multi-ítem con depósitos distintos: se devuelve la ubicación DOMINANTE
        (mayor cantidad acumulada). El split de picking por depósito queda como
        follow-up (ver STATE tusrefac-multialmacen-prep).

        Devuelve False si: la tabla de mapeo no existe (meli_oerp_multiple no
        instalado), la orden no trae node/store, el nodo no está en el mapeo, o su
        odoo_location_id está vacío. En todos esos casos el caller MANTIENE el
        comportamiento actual (mercadolibre_stock_warehouse / _full) => INERTE
        mientras el mapeo esté sin poblar.
        """
        self.ensure_one()

        # opt-in: la tabla de mapeo vive en meli_oerp_multiple; sin ese módulo, inerte.
        if 'mercadolibre.account.stock_location' not in self.env:
            return False

        # órdenes ML vinculadas a esta sale.order
        meli_orders = self.env['mercadolibre.orders']
        if 'meli_orders' in self._fields and self.meli_orders:
            meli_orders = self.meli_orders
        elif 'meli_order_id' in self._fields and self.meli_order_id:
            meli_orders = self.meli_order_id
        if not meli_orders:
            return False

        if not account and 'connection_account' in meli_orders._fields:
            account = meli_orders[:1].connection_account or False

        Mapping = self.env['mercadolibre.account.stock_location'].sudo()
        base_dom = [('account_id', '=', account.id)] if account else []

        loc_qty = {}
        for mo in meli_orders:
            for item in mo.order_items:
                node = ('meli_stock_node_id' in item._fields and item.meli_stock_node_id) or ''
                store = ('meli_stock_store_id' in item._fields and item.meli_stock_store_id) or ''
                if not node and not store:
                    continue
                rec = Mapping
                if node:
                    rec = Mapping.search(base_dom + [('network_node_id', '=', node)], limit=1)
                if not rec and store:
                    rec = Mapping.search(base_dom + [('meli_store_id', '=', store)], limit=1)
                if rec and rec.odoo_location_id:
                    loc = rec.odoo_location_id
                    loc_qty[loc.id] = loc_qty.get(loc.id, 0) + (item.quantity or 1)

        if not loc_qty:
            return False

        dominant_loc_id = max(loc_qty, key=loc_qty.get)
        return self.env['stock.location'].browse(dominant_loc_id)

    def _meli_warehouse_from_location( self, location ):
        """Warehouse cuya ubicación de stock es (o contiene) `location`. False si no hay."""
        if not location:
            return False
        Warehouse = self.env['stock.warehouse'].sudo()
        wh = Warehouse.search([('lot_stock_id', '=', location.id)], limit=1)
        if not wh:
            wh = Warehouse.search([('view_location_id', 'parent_of', location.id)], limit=1)
        return wh or False

    def _meli_get_warehouse_id( self, config=None ):

        company = (config and 'company_id' in config._fields and config.company_id) or self.env.user.company_id
        config = config or company
        wh_id = None

        if (config.mercadolibre_stock_warehouse):
            wh_id = config.mercadolibre_stock_warehouse

        if (self.meli_shipment_logistic_type == "fulfillment"):
            if (config.mercadolibre_stock_warehouse_full):
                wh_id = config.mercadolibre_stock_warehouse_full

        # Surtido multi-almacén por depósito ML (opt-in, fallback-preservador):
        # si la orden trae node/store mapeado a una ubicación Odoo, rutear a su warehouse.
        # Si no resuelve nada, wh_id queda como arriba (comportamiento actual).
        try:
            mapped_loc = self._meli_get_stock_location_from_mapping()
            if mapped_loc:
                mapped_wh = self._meli_warehouse_from_location(mapped_loc)
                if mapped_wh:
                    wh_id = mapped_wh
        except Exception as e:
            _logger.info("ML multi-almacén: fallo resolviendo depósito ML->warehouse (fallback a config): %s", e)

        return wh_id

    def confirm_ml_stock( self, meli=None, config=None, force=False ):

        #_logger.info("meli_oerp_stock confirm_ml_stock")
        company = (config and 'company_id' in config._fields and config.company_id) or self.env.user.company_id
        config = config or company

        forcing_date = False
        forcing_date = config and config.mercadolibre_stock_filter_order_datetime and self.meli_date_closed >= config.mercadolibre_stock_filter_order_datetime
        forcing_date = forcing_date and config.mercadolibre_stock_filter_order_datetime_to and self.meli_date_closed <= config.mercadolibre_stock_filter_order_datetime_to

        force = force or forcing_date
        #_logger.info("Forcing shipment validation: "+str(force))

        self._meli_order_update( config=config )

        delinofull = "mercadolibre_order_confirmation_delivery" in config._fields and config.mercadolibre_order_confirmation_delivery
        delifull = "mercadolibre_order_confirmation_delivery_full" in config._fields and config.mercadolibre_order_confirmation_delivery_full
        #shipped_or_delivered = self.meli_shipment and ("delivered" in self.meli_shipment.status or "shipped" in self.meli_shipment.status)
        shipped_or_delivered = self.meli_shipment and ("delivered" in self.meli_shipment.status)
        #_logger.info("shipped_or_delivered:"+str(shipped_or_delivered))

        condition = self.meli_shipment_logistic_type=="fulfillment" and delifull and "paid_confirm_deliver" in delifull
        condition = condition or (not self.meli_shipment_logistic_type and delinofull and  "paid_confirm_deliver" in delinofull)

        condition = condition or (self.meli_shipment_logistic_type=="fulfillment" and shipped_or_delivered and delifull and "paid_confirm_shipped_deliver" in delifull)
        condition = condition or (self.meli_shipment_logistic_type=="" and shipped_or_delivered and delinofull and  "paid_confirm_shipped_deliver" in delinofull )
        #last check:
        condition = condition and ("paid" in self.meli_status) and self.state in ['sale','done']


        #if self.picking_ids:
            #for spick in self.picking_ids:
                #_logger.info(spick)
                #if self.warehouse_id and spick.location_id:

                    #if self.warehouse_id.lot_stock_id.id != spick.location_id.id:
                    #    _logger.info("Fixing location!")
                        #spick.location_id = self.warehouse_id.lot_stock_id
                        #if spick.state=="assigned":
                        #    spick.move_line_ids_without_package = None
                        #    spick.do_unreserve()
                        #    if self.warehouse_id.lot_stock_id.id == spick.location_id.id:
                        #        spick.action_assign()

                     #if self.warehouse_id.lot_stock_id.id != spick.location_id.id:
                    #    _logger.info("Fixing location NOT POSSIBLE! Aborting delivery.")
                    #    return { "error": "Fixing location NOT POSSIBLE! Aborting delivery." }


        #_logger.info("delivery condition: "+str(condition))
        if (condition or force):
            self.meli_deliver( meli=meli, config=config)

        #_logger.info("meli_oerp_stock confirm_ml_stock ended")

    #try to update order before confirmation (quotation)
    def confirm_ml( self, meli=None, config=None ):

        #_logger.info("meli_oerp_stock confirm_ml: config:"+str(config and config.name))

        company = (config and 'company_id' in config._fields and config.company_id) or self.env.user.company_id
        config = config or company

        self.confirm_ml_stock( meli=meli, config=config )

        super(SaleOrder, self).confirm_ml( meli=meli, config=config )

        #if self.location_id and self.location_id.mercadolibre_active == True:

        # select lot_id based on max quantity , and assign location_id based on lot_id (search quant assigned... to this lot_id (name) )
        # _logger.info("Location es ML Active "+str(self.location_id))
        #search for the max... check the origin (move_ids.origin)
        # check  and search for lot_id
        # search for stock.quant   related to this location_id, then choose the first bigger lot_id
        # if self.product_id:
        #     quants = self.env["stock.quant"].search([('product_id','=',self.product_id.id),('location_id','=',self.location_id.id)])
            #search max!!!
        #     max = 0
        #     qs = quants and quants[0]
        #     for q in quants:
        #         if q.inventory_quantity>max:
        #             qs = q
        #             max = qs.inventory_quantity
        #     self.lot_id = qs and qs.lot_id
        #

        #seleccionar en la confirmacion del stock.picking la informacion del carrier
        #
        #_logger.info("meli_oerp_stock confirm_ml ended.")


    # (F8b 20.0) borrados `___action_confirm` y `__action_confirm`: doble guion bajo => Python los renombra
    # (`_SaleOrder___action_confirm`, `_SaleOrder__action_confirm`) y el ORM nunca los llamaba (codigo muerto,
    # solo logueaban).

class MercadolibreOrder(models.Model):

    _inherit = "mercadolibre.orders"

    #update order after any quotation/order confirmation
    def orders_update_order_json( self, data, context=None, config=None, meli=None ):

        result = super(MercadolibreOrder, self).orders_update_order_json( data=data, context=context, config=config, meli=meli)

        if result and "error" in result and not 'No product related to meli_id' in result['error']:
            return result
        #company = self.env.user.company_id
        oid = (data and 'order_json' in data and 'id' in data['order_json'] and data['order_json']["id"])
        cid = (data and 'id' in data and data['id'])
        if oid or cid:
            order = oid and self.env['mercadolibre.orders'].search([( 'order_id','=',str(oid) )], limit=1)
            order = order or (not order and cid and self.env['mercadolibre.orders'].browse(cid))
            if order:
                sorder = order.sale_order or (order.shipment and order.shipment.sale_order)
                if sorder:
                    sorder._meli_order_update( config=config, data=data )
                else:
                    _logger.info("missing sale order for:"+str(order.name))
            else:
                _logger.info("missing meli order for: oid:"+str(oid)+" or "+str(cid))
        else:
            _logger.info("missing id in data:"+str(data))

        return result

    #mapping procedure params: sku or item
    def map_meli_sku( self, meli_sku=None, meli_item=None ):
        _logger.info("map_meli_sku: "+str(meli_item))
        odoo_sku = None
        mapped_sku = None
        filtered = None
        seller_sku = meli_sku or (meli_item and 'seller_sku' in meli_item and meli_item['seller_sku']) or (meli_item and 'seller_custom_field' in meli_item and meli_item['seller_custom_field'])

        if seller_sku:
            #mapped skus (json dict string assigned)
            if mapping_meli_sku_regex:
                for reg in mapping_meli_sku_regex:
                    rules = mapping_meli_sku_regex[reg]
                    for rule in rules:
                        regex = "regex" in rule and rule["regex"]
                        if regex and not filtered:
                            group = "group" in rule and rule["group"]
                            c = re.compile(regex)
                            if c:
                                ms = c.findall(seller_sku)
                                if ms:
                                    if len(ms)>group:
                                        m = ms[group]
                                        filtered = m
                                        _logger.info("filtered ok: regex: "+str(rule)+" result: "+str(m))
                                        break;

            mapped_sku = (mapping_meli_sku_defaut_code and seller_sku in mapping_meli_sku_defaut_code and mapping_meli_sku_defaut_code[seller_sku])
            mapped_sku = mapped_sku or self.env['meli_oerp.sku.rule'].map_to_sku(name=seller_sku)
            odoo_sku = mapped_sku or filtered or seller_sku

        if mapped_sku:
            _logger.info("map_meli_sku(): meli_sku: "+str(seller_sku)+" mapped to: "+str(odoo_sku))

        return odoo_sku

    #extended from mercadolibre.orders: SKU formulas
    def search_meli_product( self, meli=None, meli_item=None, config=None ):
        _logger.info("search_meli_product extended: "+str(meli_item))
        product_related = super(MercadolibreOrder, self).search_meli_product( meli=meli, meli_item=meli_item, config=config )

        product_obj = self.env['product.product']
        if ( len(product_related)==0 and ('seller_custom_field' in meli_item or 'seller_sku' in meli_item)):

            #Mapping meli sku to odoo sku
            meli_item["seller_sku"] = self.map_meli_sku( meli_item=meli_item )

            #1ST attempt "seller_sku" or "seller_custom_field"
            seller_sku = ('seller_sku' in meli_item and meli_item['seller_sku']) or ('seller_custom_field' in meli_item and meli_item['seller_custom_field'])
            if (seller_sku):
                product_related = product_obj.search([('default_code','=ilike',seller_sku)])

            #2ND attempt only old "seller_custom_field"
            if (not product_related and 'seller_custom_field' in meli_item):
                seller_sku = ('seller_custom_field' in meli_item and meli_item['seller_custom_field'])
            if (seller_sku):
                product_related = product_obj.search([('default_code','=',seller_sku)])
            if not product_related:
                order = self
                order and order.message_post(body=str('seller sku not founded: '+str(seller_sku)))

        #product_obj = self.env['product.product']

        return product_related

    def get_sale_order_type( self, meli=None, order_json=None, config=None, sale_order=None, shipment=None ):

        meli_order_fields =  {}

        if ('sale.order.type' in self.env and sale_order):

            so_type_log_id = None
            so_type_log = None

            #check first for sale_type_id from sale.order > seller team
            so_type_log_id = sale_order and sale_order.team_id and "sale_type_id" in sale_order.team_id._fields and sale_order.team_id.sale_type_id and sale_order.team_id.sale_type_id.id

            so_type_log = self.env['sale.order.type'].search([('name','like','SO-MELI')],limit=1)
            if not so_type_log:
                so_type_log = self.env['sale.order.type'].search([('name','like','SO-MLB')],limit=1)
            if not so_type_log:
                so_type_log = self.env['sale.order.type'].search([('name','like','SO-ECM')],limit=1)

            logistic_type = (shipment and "logistic_type" in shipment._fields and shipment.logistic_type)
            logistic_type = logistic_type or (sale_order and sale_order.meli_shipment_logistic_type)

            if logistic_type:
                #
                if "fulfillment" in logistic_type:
                    so_type_log = self.env['sale.order.type'].search([('name','like','SO-MLF')],limit=1)
            else:
                # BUG-016: "acordar entrega" (sin logistic_type / shipping.id null) → usar el
                # tipo configurable mercadolibre_sale_order_type (meli_oerp_sale_order_type) si
                # está definido, antes del default SO-MELI. Evita quedar sin tipo mapeable.
                if config and 'mercadolibre_sale_order_type' in config._fields and config.mercadolibre_sale_order_type:
                    so_type_log = config.mercadolibre_sale_order_type

            so_type_log_id = so_type_log_id or (so_type_log and so_type_log.id)
            # BUG-016: NO escribir type_id=None (pisaría la corrección manual del operador) y
            # write-once: no tocar el type_id si el pedido de venta YA tiene uno (el cron no
            # debe re-pisar en corridas posteriores lo seteado a mano).
            _so_has_type = sale_order and 'type_id' in sale_order._fields and sale_order.type_id
            if so_type_log_id and not _so_has_type:
                meli_order_fields["type_id"] = so_type_log_id

        return meli_order_fields

    def prepare_sale_order_vals( self, meli=None, order_json=None, config=None, sale_order=None, shipment=None ):
        meli_order_fields = super(MercadolibreOrder, self).prepare_sale_order_vals(meli=meli, order_json=order_json, config=config, sale_order=sale_order, shipment=shipment )
        if ('sale.order.type' in self.env):
            meli_order_fields.update( self.get_sale_order_type(meli=meli, order_json=order_json, config=config, sale_order=sale_order, shipment=shipment) )

        wh_id = None
        if (config.mercadolibre_stock_warehouse):
            wh_id = config.mercadolibre_stock_warehouse
        if (self.shipment_logistic_type == "fulfillment"):
            if (config.mercadolibre_stock_warehouse_full):
                wh_id = config.mercadolibre_stock_warehouse_full
        if wh_id:
            meli_order_fields.update({'warehouse_id': wh_id.id })
        #_logger.info("prepare_sale_order_vals > meli_order_fields:"+str(meli_order_fields))

        return meli_order_fields

#cancelled ship-delivered
#cancelled ship-not_deliveredreturned_to_hub
#cancelled ship-not_deliveredreturning_to_sender
#DEVUELTES
#ni siquiera salio
#cancelled ship-cancelled
