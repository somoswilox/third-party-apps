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
from datetime import timedelta
_logger = logging.getLogger(__name__)

import pdb

import requests


class stock_move(models.Model):

    _inherit = "stock.move"

    #cancel_backorder parameter is present in odoo version >= 13.0
    def _action_done(self, cancel_backorder=None ):
        context = self.env.context
        #_logger.info("context: "+str(context))
        company = self.env.user.company_id
        #_logger.info("company: "+str(company))
        #_logger.info("meli_oerp_stock >> stock.move _action_done ")
        ret = super( stock_move, self)._action_done(cancel_backorder=cancel_backorder)
        #_logger.info("meli_oerp_stock >> stock.move _action_done OK ")
        for st in self:
            #_logger.info("Moved products, put all this product stock state on batch for inmediate update: #"+str(len(st.product_id))+" >> "+str(st.product_id.ids) )
            for p in st.product_id:
                _logger.info("post stock for: "+p.display_name)

        return ret

class stock_picking( models.Model):

    _inherit = "stock.picking"

    meli_shipment_status_brief = fields.Char(related="sale_id.meli_status_brief",index=True)
    meli_shipment_print_pdf = fields.Binary(related="sale_id.meli_shipment.pdf_file",index=True)
    meli_shipment_print = fields.Char(related="sale_id.meli_shipment.pdf_filename",index=True)
    meli_shipment = fields.Many2one(related="sale_id.meli_shipment",index=True)
    meli_order = fields.Many2one(related="sale_id.meli_shipment.sale_order",index=True)
    
    meli_shipment_logistic_type = fields.Char( related="meli_shipment.logistic_type", readonly=True, store=True, index=True )
    meli_handling_limit = fields.Datetime(
        related="meli_shipment.estimated_handling_limit",
        readonly=True, string="Límite despacho ML")

    meli_handling_limit_status = fields.Selection([
        ('none',    'Sin fecha límite'),
        ('ok',      'En plazo'),
        ('urgent',  'Urgente (< 4 h)'),
        ('overdue', 'Vencido'),
    ], compute='_compute_picking_handling_limit_status', store=False,
       string="Estado límite despacho")

    @api.depends('meli_handling_limit', 'meli_shipment.estimated_buffering_date')
    def _compute_picking_handling_limit_status(self):
        now = fields.Datetime.now()
        for rec in self:
            ship = rec.meli_shipment
            ehl = rec.meli_handling_limit or (ship.estimated_buffering_date if ship else False)
            if not ehl:
                rec.meli_handling_limit_status = 'none'
            elif ehl < now:
                rec.meli_handling_limit_status = 'overdue'
            elif ehl < now + timedelta(hours=4):
                rec.meli_handling_limit_status = 'urgent'
            else:
                rec.meli_handling_limit_status = 'ok'

    @api.depends('meli_shipment_logistic_type')
    def _compute_meli_shipment_logistic_type_label(self):
        """Mapea el logistic_type crudo de MELI a una opción válida del Selection.
        Si recibimos un tipo desconocido, caemos en 'other' para evitar errores.
        """
        # obtenemos los keys válidos del selection definido más abajo
        valid_keys = {
            key
            for key, _label in self._fields['meli_shipment_logistic_type_label'].selection
        }

        for sp in self:
            lt = (sp.meli_shipment_logistic_type or '').strip() or False
            if lt and lt in valid_keys:
                sp.meli_shipment_logistic_type_label = lt
            elif lt:
                # Tenemos un valor que MELI conoce pero nosotros no mapeamos aún
                sp.meli_shipment_logistic_type_label = 'other'
            else:
                sp.meli_shipment_logistic_type_label = False

    meli_shipment_logistic_type_label = fields.Selection(
        selection=[
            # ME1 / ME2 “clásico”
            ('default',      'ME1 / Envío estándar (default)'),

            # ME2
            ('drop_off',     'ME2 Drop Off (correo / sucursal)'),
            ('xd_drop_off',  'ME2 Places (XD Drop Off / punto de recolección)'),
            ('cross_docking','ME2 Colectas (Cross Docking)'),
            ('self_service', 'ME Flex / Turbo (Self Service)'),
            ('fulfillment',  'ME Full (Fulfillment)'),

            # Otros contextos
            ('remote',       'Envío remoto / Crossborder'),
            ('not_specified','Sin logística especificada'),

            # Fallback para futuros tipos
            ('other',        'Otro tipo logístico (no mapeado)'),
        ],
        compute='_compute_meli_shipment_logistic_type_label',
        store=True,
        index=True,
        readonly=True,
        string="Tipo logístico Mercado Envíos",
    )

    def action_reassign( self ):

        moves = self.mapped('move_lines').filtered(lambda move: move.state not in ('draft', 'cancel', 'done'))
        if moves:
            #re assign
            _logger.info("meli_oerp_stock reassign: "+str(moves))
            for m in moves:
                mv = m
                qty = mv.product_uom_qty
                _logger.info("action_reassign Move Line: State:"+str(mv.state)
                            +" Product:"+str(mv.product_id and mv.product_id.name)
                            +" Location:"+str(mv.location_id and mv.location_id.name)
                            #+" Lot:"+str(mv.lot_id and mv.lot_id.name)
                            +" Qty Reserved:"+str(mv.product_uom_qty)
                            )
                if m.product_id: # and m.location_id.mercadolibre_active == True:
                    _logger.info("meli_oerp_stock reassign: move: "+str(m))
                    lotids = self.env["stock.location"].search([('location_id','in',[self.location_id])]).mapped('id') or []
                    #quants_by_lot = self.env["stock.quant"].search([('product_id','=',self.product_id.id),('location_id','=',self.location_id.id)])
                    quants = self.env["stock.quant"].search([('product_id','=',m.product_id.id),('location_id','in',lotids)])
                    _logger.info("meli_oerp_stock reassign: quants:"+str(quants))
                    #search max!!!
                    max = 0
                    qs = None
                    for q in quants:
                        #_logger.info("meli_oerp_stock reassign: q:"+str(q.location_id and q.location_id.name))
                        #_logger.info("meli_oerp_stock reassign: q.quantity:"+str(q.quantity))
                        if q.quantity>max and q.location_id.mercadolibre_active == True:
                            qs = q
                            max = qs.quantity
                    if qs:
                        _logger.info("meli_oerp_stock reassign: qs:"+str(qs and qs.location_id and qs.location_id.name)+" quantity:"+str(qs.quantity))
                        m.lot_id = qs and qs.lot_id
                        m.location_id = qs and qs.location_id
                        #m.product_uom_qty = qty
                        #m.state = 'assigned'

    # Comprobar disponibilidad
    def __action_assign( self ):
        _logger.info("meli_oerp_stock re-assign: "+str(self))
        #puede llegar a asignar varios stocks asociados
        ret = super( stock_picking, self).action_assign()

        self.action_reassign()


        return ret

    def _meli_full_lot_policy(self):
        """Retorna la política activa de auto-asignación FIFO para FULL.

        Se lee desde la configuración de MercadoLibre asociada a la cuenta de
        la orden (shipment → seller → account → configuration). Si no se puede
        resolver, se asume 'on_assign' (opt-out vía configuración).

        Valores:
          - 'off'        → no hacer nada automático
          - 'on_assign'  → ejecutar en cada _action_assign de un picking FULL
          - 'manual'     → solo por wizard/botón manual (no hook automático)
        """
        self.ensure_one()
        try:
            config = self.sale_id.meli_shipment.seller.account.configuration
            policy = getattr(config, 'mercadolibre_full_lot_policy', False)
            if policy:
                return policy
        except Exception:
            pass
        return 'on_assign'

    def _meli_auto_assign_lots_fifo(self):
        """Auto-asigna lotes por FIFO (oldest first) en pickings MELI FULL.

        Problema que soluciona:
          Cuando un producto con tracking='lot' tiene >1 lote con stock en la
          ubicación fuente de un picking FULL, el assign estándar de Odoo no
          puede resolver automáticamente el split: deja el move sin reserva
          completa y el picking no se puede validar ("debe proporcionar un
          número de lote o serie para [SKU]").

        Estrategia:
          Para cada move sin lot assigned (o con reserva incompleta):
            1. Buscar stock.quant con available_quantity > 0 en la ubicación
               fuente (y sus descendientes), filtrando por lot_id != False.
            2. Ordenar por lot.create_date ASC (el más viejo primero — FIFO).
            3. Crear un stock.move.line por cada lote hasta cubrir product_uom_qty.
            4. Si no se cubre el total, se deja lo que se pudo asignar y se
               reporta como "partial" para revisión manual.

        Retorna un dict con contadores:
          {
            'pickings_ok': N,         # pickings completamente auto-asignados
            'pickings_partial': N,    # pickings con asignación parcial
            'pickings_skipped': N,    # pickings no FULL o ya en estado final
            'moves_processed': N,    # moves a los que se les asignó al menos 1 lote
            'lots_assigned': N,      # total de move.lines creadas por el helper
          }
        """
        Quant = self.env['stock.quant']
        MoveLine = self.env['stock.move.line']
        counters = {
            'pickings_ok': 0,
            'pickings_partial': 0,
            'pickings_skipped': 0,
            'moves_processed': 0,
            'lots_assigned': 0,
        }

        for picking in self:
            if picking.state in ('draft', 'cancel', 'done'):
                counters['pickings_skipped'] += 1
                continue
            if (picking.meli_shipment_logistic_type or '') != 'fulfillment':
                counters['pickings_skipped'] += 1
                continue

            picking_partial = False
            picking_touched = False

            # En Odoo 17+ el campo es move_ids (antes move_lines)
            moves = picking.move_ids.filtered(
                lambda m: m.state not in ('draft', 'cancel', 'done')
                          and m.product_id
                          and m.product_id.tracking in ('lot', 'serial')
            )

            for move in moves:
                qty_needed = move.product_uom_qty
                # Ya asignado lo que hay en las move_lines existentes
                qty_already_reserved = sum(
                    ml.quantity for ml in move.move_line_ids if ml.lot_id
                )
                qty_missing = qty_needed - qty_already_reserved
                if qty_missing <= 0:
                    continue

                # Buscar quants con lote en la ubicación fuente (y descendientes)
                # NB: Usamos child_of para cubrir sub-ubicaciones MELI.
                domain = [
                    ('product_id', '=', move.product_id.id),
                    ('location_id', 'child_of', move.location_id.id),
                    ('lot_id', '!=', False),
                    ('quantity', '>', 0),
                ]
                quants = Quant.search(domain)
                if not quants:
                    picking_partial = True
                    continue

                # FIFO: ordenar por fecha de creación del lote (oldest first)
                # Si create_date es False (edge case) se pone al final.
                def _sort_key(q):
                    cd = q.lot_id.create_date
                    return (cd is None, cd or fields.Datetime.now())

                quants_sorted = sorted(quants, key=_sort_key)

                qty_to_assign = qty_missing
                move_touched = False
                for q in quants_sorted:
                    if qty_to_assign <= 0:
                        break
                    available = q.quantity - q.reserved_quantity
                    if available <= 0:
                        continue
                    take = min(available, qty_to_assign)
                    try:
                        MoveLine.create({
                            'move_id': move.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'location_id': q.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                            'lot_id': q.lot_id.id,
                            'quantity': take,
                            'picking_id': picking.id,
                        })
                        qty_to_assign -= take
                        counters['lots_assigned'] += 1
                        move_touched = True
                    except Exception as e:
                        _logger.warning(
                            "meli_oerp_stock FIFO assign: error creando move.line "
                            "para %s lot=%s qty=%s: %s",
                            move.product_id.display_name,
                            q.lot_id.name, take, e
                        )

                if move_touched:
                    counters['moves_processed'] += 1
                    picking_touched = True
                if qty_to_assign > 0:
                    picking_partial = True

            if picking_touched:
                if picking_partial:
                    counters['pickings_partial'] += 1
                else:
                    counters['pickings_ok'] += 1
            else:
                counters['pickings_skipped'] += 1

        return counters

    def action_meli_full_auto_assign_lots(self):
        """Botón: ejecuta FIFO auto-assign en los pickings FULL seleccionados.

        Posteriormente notifica al usuario con el resumen de resultados.
        """
        res = self._meli_auto_assign_lots_fifo()
        msg = _(
            "Auto-asignación FIFO completada:\n"
            "  Pickings OK: %(ok)s\n"
            "  Pickings parciales: %(partial)s\n"
            "  Pickings omitidos (no FULL o estado final): %(skipped)s\n"
            "  Moves procesados: %(moves)s\n"
            "  Move.lines creadas: %(lines)s"
        ) % {
            'ok': res['pickings_ok'],
            'partial': res['pickings_partial'],
            'skipped': res['pickings_skipped'],
            'moves': res['moves_processed'],
            'lines': res['lots_assigned'],
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Lotes FIFO - MELI FULL"),
                'message': msg,
                'type': 'success' if res['pickings_partial'] == 0 else 'warning',
                'sticky': True,
            }
        }

    # Comprobar disponibilidad — hook: después del assign estándar, si es FULL
    # y la política lo permite, ejecutamos FIFO para cubrir moves con multi-lote.
    def _action_assign(self):
        ret = super()._action_assign()
        try:
            pickings_full = self.filtered(
                lambda p: (p.meli_shipment_logistic_type or '') == 'fulfillment'
                          and p.state not in ('draft', 'cancel', 'done')
            )
            for p in pickings_full:
                if p._meli_full_lot_policy() == 'on_assign':
                    p._meli_auto_assign_lots_fifo()
        except Exception as e:
            # No queremos bloquear el assign estándar por un fallo del hook
            _logger.warning(
                "meli_oerp_stock _action_assign FIFO hook falló: %s", e
            )
        return ret

    # ------------------------------------------------------------------
    # FIX #353: reserva fantasma también en el CIERRE MANUAL desde el UI
    # ------------------------------------------------------------------
    def _meli_is_ml_out(self):
        """True si el picking es una salida ML a cliente candidata a saneo #353.

        Mismo criterio que sale.order.meli_deliver: picking outgoing, origen
        internal/transit → destino customer, no devolución, no crossdock/compra.
        Acota el override de button_validate SOLO a pickings ML; cualquier otro
        picking pasa derecho al core sin tocarse.
        """
        self.ensure_one()
        p = self
        if p.state in ('done', 'cancel'):
            return False
        if p.picking_type_id.code != 'outgoing':
            return False
        if p.location_id.usage not in ('internal', 'transit'):
            return False
        if p.location_dest_id.usage != 'customer':
            return False
        moves = getattr(p, 'move_ids_without_package', None) or p.move_ids
        # devolución: algún move nacido como return
        if any(moves.mapped('origin_returned_move_id')):
            return False
        # crossdock / compra: no validar pickings nacidos de esa ruta
        rules = [r for r in moves.mapped('rule_id.route_id.name') if r]
        joined = ' | '.join(rules).lower()
        if ('cross dock' in joined) or ('comprar' in joined) or ('buy' in joined):
            return False
        return True

    def _meli_heal_phantom_reserve(self):
        """FIX #353 v2 — sanea reservas fantasma antes de validar (idempotente).

        Caso degenerado: la move_line reserva > 0 pero stock_quant.reserved_quantity
        no la cubre (desync ML↔quant). Ocurre cuando la mercadería ya salió
        físicamente pero Odoo no registró el consumo de reserva (stock negativo,
        ajustes manuales, FULL desincronizado).

        Problema: en _action_done, la move.line llama
        Quant._update_reserved_quantity(-reserved, strict=True), que verifica
        quant.reserved_quantity >= reserved. Si el quant tiene reserved=0 pero la
        ML tiene reserva=1, el guard lanza UserError aunque el qty_done esté
        completo. Un do_unreserve() previo tampoco alcanza: la ML write dispara el
        mismo guard.

        Estrategia (2 pasos):
          1) Camino normal do_unreserve()+action_assign(): sirve cuando hay
             on_hand suficiente y el desync es sólo de reserva.
          2) Fallback SQL: alinear quant.reserved_quantity con la reserva de la ML
             vía SQL directo (sin triggers ORM); si no existe quant, crear uno
             fantasma (quantity=0, reserved=gap). Así _action_done encuentra un
             quant coherente y libera la reserva; el quant queda negativo si
             on_hand=0 (stock negativo válido, se reconcilia luego).

        Cross-versión: la reserva de la ML es reserved_uom_qty (16) / quantity
        (17+); en unidades base es reserved_qty (16) / quantity_product_uom (17+).
        Se resuelven con getattr + fallback. Sin recursión: no llama a
        button_validate; el override lo invoca ANTES del super().
        """
        for spick in self:
            if spick.state in ('done', 'cancel'):
                continue

            # --- Detección: ¿alguna ML reserva más de lo que el quant tiene reservado?
            needs_fix = False
            for mv in spick.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                for ml in mv.move_line_ids:
                    ml_reserved = (getattr(ml, 'reserved_uom_qty', None)
                                   or getattr(ml, 'quantity', None)
                                   or getattr(ml, 'product_uom_qty', 0.0))
                    if not ml_reserved:
                        continue
                    quants = spick.env['stock.quant'].search([
                        ('product_id', '=', ml.product_id.id),
                        ('location_id', '=', ml.location_id.id),
                    ])
                    quant_reserved = sum(quants.mapped('reserved_quantity'))
                    if quant_reserved < ml_reserved:
                        needs_fix = True
                        _logger.warning(
                            "[meli_heal #353] %s (%s): SKU %s ml.reserved=%.4f > "
                            "quant.reserved=%.4f — reserva fantasma detectada (desync ML↔quant)",
                            spick.name, spick.id,
                            ml.product_id.default_code or ml.product_id.name,
                            ml_reserved, quant_reserved,
                        )
                        break
                if needs_fix:
                    break

            if not needs_fix:
                continue

            # --- Paso 1: camino normal (do_unreserve + action_assign)
            try:
                spick.do_unreserve()
                spick.action_assign()
                _logger.info(
                    "[meli_heal #353] %s (%s): reservas saneadas vía do_unreserve (state=%s)",
                    spick.name, spick.id, spick.state,
                )
            except Exception as unreserve_err:
                # --- Paso 2: fallback SQL quant-align
                _logger.warning(
                    "[meli_heal #353] %s (%s): do_unreserve falló (%s) — activando "
                    "fallback SQL quant-align", spick.name, spick.id, unreserve_err,
                )
                for mv2 in spick.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                    for ml2 in mv2.move_line_ids:
                        ml_res2 = (getattr(ml2, 'reserved_qty', None)
                                   or getattr(ml2, 'quantity_product_uom', None)
                                   or 0.0)  # unidades base del producto
                        if not ml_res2:
                            continue
                        quants2 = spick.env['stock.quant'].search([
                            ('product_id', '=', ml2.product_id.id),
                            ('location_id', '=', ml2.location_id.id),
                        ])
                        q_res2 = sum(quants2.mapped('reserved_quantity'))
                        gap = ml_res2 - q_res2
                        if gap <= 0:
                            continue
                        if quants2:
                            # Preferir el quant de mayor cantidad para absorber la reserva
                            best_q = quants2.sorted(lambda q: q.quantity, reverse=True)[0]
                            spick.env.cr.execute(
                                "UPDATE stock_quant SET reserved_quantity = reserved_quantity + %s WHERE id = %s",
                                (gap, best_q.id)
                            )
                            _logger.info(
                                "[meli_heal #353] %s (%s): quant id=%s SKU=%s reserved_quantity +%.4f (quant-align)",
                                spick.name, spick.id, best_q.id,
                                ml2.product_id.default_code or ml2.product_id.name, gap,
                            )
                        else:
                            # Sin quant existente: la mercadería ya salió, stock negativo.
                            # Crear quant fantasma quantity=0 reserved=gap para que
                            # _action_done pueda liberar la reserva y dejarlo en 0.
                            spick.env.cr.execute(
                                """INSERT INTO stock_quant
                                   (product_id, location_id, quantity, reserved_quantity, company_id, in_date)
                                   VALUES (%s, %s, 0, %s, %s, NOW())""",
                                (ml2.product_id.id, ml2.location_id.id, gap, spick.company_id.id)
                            )
                            _logger.info(
                                "[meli_heal #353] %s (%s): quant creado SKU=%s quantity=0 reserved=%.4f (quant-align, stock-neg)",
                                spick.name, spick.id,
                                ml2.product_id.default_code or ml2.product_id.name, gap,
                            )
                spick.env['stock.quant'].invalidate_model()
        return True

    def button_validate(self):
        """Override: sanea reserva fantasma (#353) también en el cierre MANUAL.

        El saneo de meli_deliver sólo corre en el path automático (cron/conector).
        Cuando el usuario valida a mano desde el UI ("Validar" en Expediciones),
        el core llega directo a _action_done → Quant._update_reserved_quantity
        (strict=True) y dispara el UserError "No es posible deshacer la reserva…"
        ANTES de que corra ningún código nuestro. Acá interceptamos SÓLO los
        pickings ML de salida y los saneamos antes del super(). Pickings normales
        (sin inconsistencia → _meli_heal_phantom_reserve es no-op) o no-ML pasan
        derecho. Sin recursión: el heal no llama a button_validate.
        """
        ml_pickings = self.filtered(lambda p: p._meli_is_ml_out())
        if ml_pickings:
            try:
                ml_pickings._meli_heal_phantom_reserve()
            except Exception as e:
                _logger.warning(
                    "meli_oerp_stock button_validate: heal #353 falló (%s); "
                    "se delega al core", e,
                )
        return super().button_validate()


class stock_move_line(models.Model):

    _inherit = "stock.move.line"

    #@api.onchange('location_id')
    def __onchange_location_id_ml(self):
        """ When the user is encoding a move line for a tracked product, we apply some logic to
        help him. This includes:
            - automatically switch `qty_done` to 1.0
            - warn if he has already encoded `lot_name` in another move line
        """
        res = {}
        if self.location_id:
            # and self.location_id.mercadolibre_active == True:
            #
            _logger.info("Location es ML Active "+str(self.location_id))
            #search for the max... check the origin (move_ids.origin)
            # check  and search for lot_id
            # search for stock.quant   related to this location_id, then choose the first bigger lot_id
            if self.product_id:
                #quants_by_lot = self.env["stock.quant"].search([('product_id','=',self.product_id.id),('location_id','=',self.location_id.id)])
                quants = self.env["stock.quant"].search([('product_id','=',self.product_id.id),('location_id','=',self.location_id.id)])
                #search max!!!
                max = 0
                qs = quants and quants[0]
                for q in quants:
                    if q.quantity>max:
                        qs = q
                        max = qs.quantity
                self.lot_id = qs and qs.lot_id


        else:
            message = "Use a MercadoLibre Active Location"
            #if message:
            #    res['warning'] = {'title': _('Warning'), 'message': message}
        return res


    #@api.onchange('lot_id')
    def __onchange_lot_id_ml(self):
        """ When the user is encoding a move line for a tracked product, we apply some logic to
        help him. This includes:
            - automatically switch `qty_done` to 1.0
            - warn if he has already encoded `lot_name` in another move line
        """
        res = {}
        if self.lot_id:
            #
            #_logger.info("Location es ML Active "+str(self.location_id))
            #search for the max... check the origin (move_ids.origin)
            # check  and search for lot_id
            # search for stock.quant   related to this location_id, then choose the first bigger lot_id
            if self.product_id:
                quants = self.env["stock.quant"].search([('product_id','=',self.product_id.id),('lot_id','=',self.lot_id.id)])
                #search max!!!
                max = 0
                qs = quants and quants[0]
                for q in quants:
                    if q.quantity>max:
                        qs = q
                        max = qs.quantity
                self.location_id = qs and qs.location_id


        else:
            message = "Use a Lot"
            #if message:
            #    res['warning'] = {'title': _('Warning'), 'message': message}
        return res

class stock_location(models.Model):

    _inherit = "stock.location"

    mercadolibre_active = fields.Boolean(string="Ubicacion activa para MercadoLibre",index=True)
    mercadolibre_logistic_type = fields.Char(string="Logistic Type Asociado",index=True)

    @api.onchange('mercadolibre_active')
    def _onchange_mercadolibre_active(self):
        if not self.mercadolibre_active:
            return
        company = self.company_id or self.env.company
        other_active = self.env['stock.location'].search([
            ('mercadolibre_active', '=', True),
            ('company_id', '=', company.id),
            ('id', '!=', self._origin.id),
        ])
        if not other_active:
            return

        my_path = self.parent_path or ''
        my_id = self._origin.id
        ancestors_active = other_active.filtered(
            lambda l: my_path and l.parent_path and my_path.startswith(l.parent_path) and l.id != my_id
        )
        descendants_active = other_active.filtered(
            lambda l: my_path and l.parent_path and l.parent_path.startswith(my_path) and l.id != my_id
        )

        warnings = []
        if ancestors_active:
            names = ', '.join(ancestors_active.mapped('display_name'))
            warnings.append(
                "Las ubicaciones padre (%s) también están activas para ML. "
                "Al guardar se desactivarán automáticamente para evitar stock duplicado." % names
            )
        if descendants_active:
            names = ', '.join(descendants_active.mapped('display_name'))
            warnings.append(
                "Las sub-ubicaciones (%s) también están activas para ML. "
                "Se recomienda usar solo las hojas o solo el padre, no ambos." % names
            )

        if warnings:
            return {
                'warning': {
                    'title': 'Ubicaciones ML: posible stock duplicado',
                    'message': '\n\n'.join(warnings),
                }
            }

    def write(self, vals):
        res = super().write(vals)
        if vals.get('mercadolibre_active'):
            for loc in self:
                my_path = loc.parent_path or ''
                if not my_path:
                    continue
                ancestors = self.env['stock.location'].search([
                    ('mercadolibre_active', '=', True),
                    ('company_id', '=', loc.company_id.id),
                    ('id', '!=', loc.id),
                ])
                to_deactivate = ancestors.filtered(
                    lambda l: l.parent_path and my_path.startswith(l.parent_path) and l.id != loc.id
                )
                if to_deactivate:
                    to_deactivate.sudo().write({'mercadolibre_active': False})
        return res

class DeliveryCarrier(models.Model):

    _inherit = "delivery.carrier"

    ml_tracking_url = fields.Char(string="Default tracking url")

    def get_tracking_link(self, picking):
        if self.ml_tracking_url and picking and picking.carrier_tracking_ref:
            return self.ml_tracking_url+str(picking.carrier_tracking_ref)

        return super(DeliveryCarrier, self).get_tracking_link(picking)


#class stock_valuation_layer( models.Model):

#    _inherit = "stock.valuation.layer"

    #unit_cost = fields.Monetary('Unit Value', readonly=False)
    #value = fields.Monetary('Total Value', readonly=False)
