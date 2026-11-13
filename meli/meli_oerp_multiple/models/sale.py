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
#from .warning import warning
import requests
from .config_account import meli_config_account
from .meli_util import meli_norm_sku
from odoo.addons.meli_oerp.models.gtin import meli_gtin_same  # 26.389 (caso-K77)
import ast
import json
import re

# carga de dependencia (el nombre importado lo pisaba la clase de abajo: pylint function-redefined) (F8b 20.0)
import odoo.addons.meli_oerp_stock.models.order  # noqa: F401
from odoo.addons.meli_oerp.models.versions import *


def _meli_exact_binding_product(binding_obj, meli_id, meli_id_variation, account_filter):
    """Producto de la vinculacion EXACTA de una publicacion/variacion, o vacio.

    Exacta = binding de esa variacion (si la venta trae variacion) o, si no trae, binding de la
    publicacion sin variacion; y UN solo producto activo detras. Cualquier otra cosa (sin binding,
    solo binding de otra variacion, varios productos) devuelve vacio y decide la heuristica.
    """
    product_obj = binding_obj.env['product.product']
    if not meli_id:
        return product_obj
    dom = [('conn_id', '=', meli_id)] + list(account_filter or [])
    if meli_id_variation:
        dom += [('conn_variation_id', '=', str(meli_id_variation))]
    else:
        dom += ['|', ('conn_variation_id', '=', False), ('conn_variation_id', '=', '')]
    prods = binding_obj.search(dom).mapped('product_id').filtered(lambda p: p.active)
    return prods if len(prods) == 1 else product_obj

class SaleOrder(models.Model):

    _inherit = "sale.order"

    #mercadolibre could have more than one associated order... packs are usually more than one order
    mercadolibre_bindings = fields.Many2many( "mercadolibre.sale_order", string="MercadoLibre Connection Bindings",
                                             groups="meli_oerp_multiple.group_mercadolibre_connectors_manager" )

    # Depósito ML de origen VISIBLE en la venta (pestaña MercadoLibre): Many2one al depósito
    # mercadolibre.account.stock_location, resuelto del node_id/store_id de los ítems de la
    # orden. INFORMATIVO (se ve aunque el mapeo a ubicación Odoo esté vacío) y NO altera el
    # ruteo de stock (eso lo hace _meli_get_stock_location_from_mapping en meli_oerp_stock).
    meli_stock_location_id = fields.Many2one(
        "mercadolibre.account.stock_location", string="Depósito ML (origen)",
        compute="_compute_meli_stock_location_id", store=False,
        help="Depósito logístico de MercadoLibre de donde sale la venta (dominante si hay "
             "varios), resuelto del node_id/store_id de los ítems. No cambia el almacén.")

    @api.depends('meli_orders.order_items.meli_stock_node_id',
                 'meli_orders.order_items.meli_stock_store_id')
    def _compute_meli_stock_location_id(self):
        Mapping = self.env['mercadolibre.account.stock_location'].sudo()
        for order in self:
            depot = False
            if 'meli_orders' in order._fields and order.meli_orders:
                try:
                    mos = order.meli_orders
                    account = mos[:1].connection_account if 'connection_account' in mos._fields else False
                    base_dom = [('account_id', '=', account.id)] if account else []
                    qty_by_rec = {}
                    for mo in mos:
                        for item in mo.order_items:
                            node = ('meli_stock_node_id' in item._fields and item.meli_stock_node_id) or ''
                            store = ('meli_stock_store_id' in item._fields and item.meli_stock_store_id) or ''
                            if not node and not store:
                                continue
                            key_dom = [('network_node_id', '=', node)] if node else [('meli_store_id', '=', store)]
                            rec = Mapping.search(base_dom + key_dom, limit=1)
                            via = 'account'
                            if not rec and node and store:
                                rec = Mapping.search(base_dom + [('meli_store_id', '=', store)], limit=1)
                            if not rec:
                                # fallback SOLO-display (el ruteo real sí filtra por cuenta)
                                rec = Mapping.search(key_dom, limit=1)
                                if not rec and node and store:
                                    rec = Mapping.search([('meli_store_id', '=', store)], limit=1)
                                via = 'no-account-filter'
                            _logger.info("MULTIALMACEN-CMP so=%s ml=%s node=%r store=%r account=%s matched=%r via=%s",
                                         order.id, order.meli_order_id, node, store,
                                         (account.id if account else None), (rec.name if rec else None), via)
                            if rec:
                                qty_by_rec[rec.id] = qty_by_rec.get(rec.id, 0) + (item.quantity or 1)
                    if qty_by_rec:
                        depot = max(qty_by_rec, key=qty_by_rec.get)
                    _logger.info("MULTIALMACEN-CMP-RESULT so=%s ml=%s depot=%s", order.id, order.meli_order_id, depot)
                except Exception as e:
                    _logger.exception("MULTIALMACEN-CMP-ERROR so=%s: %s", order.id, e)
                    depot = False
            order.meli_stock_location_id = depot


    # Rounding adjustment fields
    meli_rounding_adjusted = fields.Boolean(
        string='Ajuste de Redondeo ML',
        default=False,
        help='Indica que esta orden tuvo un ajuste de redondeo para coincidir con el monto pagado en MercadoLibre'
    )
    meli_rounding_difference = fields.Float(
        string='Diferencia de Redondeo',
        digits=(16, 4),
        default=0.0,
        help='Diferencia en centavos/decimales que se ajusto'
    )

    def multi_meli_order_update( self, account=None ):
        #_logger.info("meli_oerp_multiple >> _meli_order_update: "+str(self))
        config = None
        if not account and self.meli_orders:
            account = self.meli_orders[0].connection_account


        for order in self:
            if not account:
                account = order.connection_account

            company = account.company_id
            if not config:
                config = account.configuration

            if ((order.meli_shipment and order.meli_shipment.logistic_type == "fulfillment")
                or order.meli_shipment_logistic_type=="fulfillment"):
                #seleccionar almacen para la orden
                warehouse_id = order.multi_meli_get_warehouse_id(account=account)
                if (warehouse_id and order.warehouse_id!=warehouse_id):
                    meli_message_post(order, "ML(multiple): Almacen; asignando para fulfillment: "+str(warehouse_id and warehouse_id.name)+" account:"+str(account and account.name), config=config)
                    order.warehouse_id = warehouse_id
                #_logger.info("order.warehouse_id: "+str(order.warehouse_id))

            #_logger.info("multi_meli_order_update journal_id: "+str(order.name))
            if "mercadolibre_invoice_journal_id" in config._fields and config.mercadolibre_invoice_journal_id:
                #_logger.info("config.mercadolibre_invoice_journal_id: "+str(config.mercadolibre_invoice_journal_id))
                journal_id = config.mercadolibre_invoice_journal_id
                if "journal_id" in order._fields and order.journal_id!=journal_id:
                    #_logger.info("order.journal_id: "+str(order.journal_id))
                    meli_message_post(order, "ML(multiple): asignando diario de facturacion: "+str(journal_id and journal_id.name)+" account:"+str(account and account.name), config=config)
                    order.journal_id = journal_id
                    #_logger.info("order.journal_id: "+str(order.journal_id))


    def multi_meli_get_warehouse_id( self, account=None ):

        company = self.company_id
        wh_id = None
        if not account and self.meli_orders:
            #toma la cuenta de la orden de venta de meli.order
            account = self.meli_orders[0].connection_account
        config = (account and account.configuration) or company

        #_logger.info("meli_oerp_multiple >> _meli_get_warehouse_id: "+str(self))

        if (config.mercadolibre_stock_warehouse):
            wh_id = config.mercadolibre_stock_warehouse

        #_logger.info("self.meli_shipment_logistic_type: "+str(self.meli_shipment_logistic_type))
        if (self.meli_shipment_logistic_type == "fulfillment"):
            if ( config.mercadolibre_stock_warehouse_full ):
                #_logger.info("company.mercadolibre_stock_warehouse_full: "+str(config.mercadolibre_stock_warehouse_full))
                wh_id = config.mercadolibre_stock_warehouse_full

        # Surtido multi-almacén por depósito ML (opt-in, fallback-preservador): si la
        # orden trae node/store mapeado a una ubicación Odoo (mercadolibre.account.stock_location
        # con odoo_location_id seteado), rutear a su warehouse. Helper compartido en
        # meli_oerp_stock (mismo modelo sale.order). Inerte mientras el mapeo esté vacío.
        try:
            mapped_loc = self._meli_get_stock_location_from_mapping(account=account)
            if mapped_loc:
                mapped_wh = self._meli_warehouse_from_location(mapped_loc)
                if mapped_wh:
                    wh_id = mapped_wh
        except Exception as e:
            _logger.info("ML(multiple) multi-almacén: fallo resolviendo depósito ML->warehouse (fallback): %s", e)

        #_logger.info("wh_id: "+str(wh_id))
        return wh_id

    def _apply_meli_rounding_adjustment(self, config=None):
        """
        Apply rounding adjustment to the sale order by modifying an existing
        line's price_unit so that the total matches meli_paid_amount.
        This resolves the issue where inverse tax calculations (21% IVA)
        cause small rounding differences due to Odoo's 2-decimal precision.

        The adjustment is made to the first product line (non-delivery).
        """
        self.ensure_one()

        if self.meli_rounding_adjusted:
            # Already adjusted
            return False

        if not self.meli_paid_amount:
            return False

        # Get configuration
        if not config:
            if self.meli_orders:
                account = self.meli_orders[0].connection_account
                config = account and account.configuration

        if not config:
            config = self.company_id

        # Get rounding tolerance
        tolerance = 1.0
        round_to_integer = False

        if hasattr(config, 'mercadolibre_rounding_tolerance') and config.mercadolibre_rounding_tolerance:
            tolerance = config.mercadolibre_rounding_tolerance

        if hasattr(config, 'mercadolibre_round_to_integer'):
            round_to_integer = config.mercadolibre_round_to_integer

        # Calculate expected amount (meli_paid_amount - coupon)
        expected_amount = self.meli_paid_amount - (self.meli_coupon_amount or 0.0)

        # Optionally round to integer
        if round_to_integer:
            expected_amount = round(expected_amount)

        # Calculate difference
        current_total = self.amount_total
        difference = expected_amount - current_total

        # Check if adjustment is needed
        if abs(difference) < 0.01:
            # No significant difference
            return False

        if abs(difference) >= tolerance:
            _logger.warning(
                "MELI: Rounding difference %.4f exceeds tolerance %.2f for order %s (expected: %.2f, total: %.2f)",
                difference, tolerance, self.name, expected_amount, current_total
            )
            return False

        # Check if order is in a state that allows modification
        if self.state in ['done', 'cancel']:
            _logger.warning("MELI: Cannot adjust order %s in state %s", self.name, self.state)
            return False

        # Find the first non-delivery product line to adjust
        line_to_adjust = None
        for line in self.order_line:
            if not line.is_delivery and line.product_uom_qty > 0:
                line_to_adjust = line
                break

        if not line_to_adjust:
            _logger.warning("MELI: No suitable line found to adjust for order %s", self.name)
            return False

        try:
            # Calculate the tax multiplier for this line
            # If line has taxes, we need to adjust the price_unit considering tax effect
            tax_multiplier = 1.0
            if line_to_adjust.tax_id:
                # Calculate total tax percentage
                for tax in line_to_adjust.tax_id:
                    if tax.amount_type == 'percent':
                        tax_multiplier += (tax.amount / 100.0)

            # Calculate price adjustment per unit
            # difference = adjustment_per_unit * qty * tax_multiplier
            # adjustment_per_unit = difference / (qty * tax_multiplier)
            qty = line_to_adjust.product_uom_qty
            price_adjustment = difference / (qty * tax_multiplier)

            # Store original price for logging
            original_price = line_to_adjust.price_unit
            new_price = original_price + price_adjustment

            _logger.info(
                "MELI: Adjusting line %s price: %.4f -> %.4f (diff: %.4f, tax_mult: %.4f)",
                line_to_adjust.product_id.display_name, original_price, new_price, price_adjustment, tax_multiplier
            )

            # Update the line price
            line_to_adjust.write({
                'price_unit': new_price,
            })

            # Mark as adjusted
            self.write({
                'meli_rounding_adjusted': True,
                'meli_rounding_difference': difference,
            })

            meli_message_post(self, "ML: Ajuste de redondeo aplicado a linea '%s': precio %.4f -> %.4f (diff total: %.4f, esperado: %.2f, anterior: %.2f)" % (
                    line_to_adjust.product_id.display_name, original_price, new_price,
                    difference, expected_amount, current_total
                ))

            return True

        except Exception as e:
            _logger.error("MELI: Error applying rounding adjustment to %s: %s", self.name, str(e))
            return False

    def confirm_ml( self, meli=None, config=None ):

        #_logger.info("meli_oerp_multiple confirm_ml")
        company = (config and 'company_id' in config._fields and config.company_id) or self.env.user.company_id
        config = config or company

        self._meli_order_update(config=config)

        # Apply rounding adjustment if configured (before confirmation in parent)
        if hasattr(config, 'mercadolibre_auto_rounding') and config.mercadolibre_auto_rounding:
            if self.state == 'draft' and not self.meli_rounding_adjusted:
                self._apply_meli_rounding_adjustment(config=config)

        super(SaleOrder, self).confirm_ml(meli=meli,config=config)

        #seleccionar en la confirmacion del stock.picking la informacion del carrier
        #
        # el hook manda el id de la venta a una URL libre, sin autenticación. Con el
        # Nivel de seguridad Alto queda bloqueado (se registra en el log y no sale nada).
        _hook_url = "mercadolibre_order_confirmation_hook" in config._fields and config.mercadolibre_order_confirmation_hook
        if _hook_url and "ocapi_security_level" in company._fields and company.sudo().ocapi_security_level == "high":
            _logger.warning("order_confirmation_hook bloqueado por Nivel de seguridad Alto (compañía %s, venta %s)", company.id, self.id)
            _hook_url = False
        if _hook_url and self.state and self.state in ['sale','done']:
            #headers = {'Accept': 'application/json', 'Content-type':'multipart/form-data'}
            try:
                params = { "target": "order", "id": self.id }
                #headers = {'Authorization': 'Bearer '+atok}
                headers = {}
                url = config.mercadolibre_order_confirmation_hook
                #_logger.info(headers)
                response = requests.post( url=url, json=dict(params) )
                if response:
                    rjson = response.json()
                    #_logger.info(rjson)
            except Exception as e:
                _logger.error(e)
                pass;

        #_logger.info("mercadolibre_shipment_print_guide: "+str(config and config.mercadolibre_shipment_print_guide)+" self.state:"+str(self.state))
        if "mercadolibre_shipment_print_guide" in config._fields and config.mercadolibre_shipment_print_guide and self.state and self.state in ['sale','done']:
            if self.meli_orders:
                meli_order = self.meli_orders[0]
                shipment = self.meli_shipment or (meli_order and meli_order.shipment)
                #_logger.info("shipment:"+str(shipment)+" substatus:"+str(shipment and shipment.substatus)+" pdf_filename:"+str(shipment and shipment.pdf_filename))
                if (shipment):
                    shipment.update(meli=meli,config=config)
                    if shipment.substatus in ["ready_to_print","printed"] and not shipment.pdf_file:
                        #_logger.info("autoprint shipment ml:"+str(self.name))
                        shipment.shipment_print( meli=meli, config=config, include_ready_to_print=True )



class MercadoLibreOrder(models.Model):

    _inherit = "mercadolibre.orders"

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account", index='btree_not_null' )

    meli_pending_batch_update = fields.Boolean(
        string="Pendiente actualización batch",
        default=False,
        index=True,
        help="Marcado por el wizard para ser procesado en el cron de actualización masiva ML."
    )

    def init(self):
        super().init()
        # #caso-K13: red de seguridad contra la orden ML importada dos veces por dos procesos en paralelo
        # (el arreglo es el lock por orden de meli_oerp/models/import_lock.py; esto es el respaldo).
        # Indice unico PARCIAL: sólo filas NUEVAS (id > max(id) al crearlo), así los duplicados
        # históricos que ya existen en las bases no impiden crearlo ni hay que tocarlos.
        # Se crea una vez (IF NOT EXISTS) y el corte queda fijo en esa primera creación.
        cr = self.env.cr
        cr.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'mercadolibre_orders_order_account_uniq_new'")
        if not cr.fetchone():
            cr.execute("SELECT COALESCE(MAX(id), 0) FROM mercadolibre_orders")
            cutoff = int(cr.fetchone()[0])
            cr.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS mercadolibre_orders_order_account_uniq_new
                ON mercadolibre_orders (order_id, COALESCE(connection_account, 0))
                WHERE id > %d AND order_id IS NOT NULL
            """ % cutoff)
            _logger.info("meli_oerp_multiple: indice unico parcial mercadolibre_orders(order_id, cuenta) desde id > %s", cutoff)

    @api.model
    def cron_batch_update_marked_orders(self, batch_size=20):
        """Cron: procesa hasta batch_size órdenes marcadas con meli_pending_batch_update.

        Usa SQL directo para evitar problemas con el flush() del ORM al entrar
        en savepoints (Odoo 19 hace flush() antes de crear el savepoint, y
        orders_update_order() puede hacer cr.commit() internamente).
        Cada orden se procesa y desmarca en su propio commit independiente.

        Tracking: registra una ejecución 'batch_update' por cada cuenta ML que
        tenga órdenes pendientes, así aparece en el page de CRONs de la cuenta
        igual que los otros crons monitoreados.
        """
        cr = self.env.cr

        cr.execute(
            "SELECT COUNT(*) FROM mercadolibre_orders WHERE meli_pending_batch_update = true"
        )
        pending_total = cr.fetchone()[0]
        if not pending_total:
            return

        cr.execute(
            "SELECT id, connection_account FROM mercadolibre_orders "
            "WHERE meli_pending_batch_update = true ORDER BY id ASC LIMIT %s",
            [batch_size]
        )
        rows = cr.fetchall()
        order_ids = [r[0] for r in rows]
        account_ids = sorted({r[1] for r in rows if r[1]})

        _logger.info("cron_batch_update_marked_orders: procesando %d de %d pendientes (batch_size=%d, cuentas=%s)",
                     len(order_ids), pending_total, batch_size, account_ids)

        AccountModel = self.env['mercadolibre.account'].sudo()
        executions_by_acc = {}
        for acc_id in account_ids:
            acc = AccountModel.browse(acc_id)
            if acc.exists():
                try:
                    executions_by_acc[acc_id] = acc._start_cron_execution('batch_update')
                except Exception as _track_err:
                    _logger.warning("cron_batch_update: no se pudo iniciar tracking para cuenta %s: %s",
                                    acc_id, _track_err)
        try:
            cr.commit()
        except Exception:
            pass

        ok_by_acc = {acc_id: 0 for acc_id in account_ids}
        err_by_acc = {acc_id: 0 for acc_id in account_ids}
        ok = 0
        errors = []

        for order_id, acc_id in rows:
            order_name = str(order_id)
            try:
                cr.execute("SELECT order_id FROM mercadolibre_orders WHERE id = %s", [order_id])
                row = cr.fetchone()
                if row and row[0]:
                    order_name = row[0]
            except Exception:
                try:
                    cr.rollback()
                except Exception:
                    pass

            try:
                order = self.browse(order_id)
                order.orders_update_order()
                ok += 1
                if acc_id:
                    ok_by_acc[acc_id] = ok_by_acc.get(acc_id, 0) + 1
            except Exception as e:
                _logger.error("cron_batch_update: error en orden %s: %s", order_name, str(e)[:300])
                errors.append(order_name)
                if acc_id:
                    err_by_acc[acc_id] = err_by_acc.get(acc_id, 0) + 1
                try:
                    cr.rollback()
                except Exception:
                    pass

            try:
                cr.execute(
                    "UPDATE mercadolibre_orders SET meli_pending_batch_update = false WHERE id = %s",
                    [order_id]
                )
                cr.commit()
            except Exception as ue:
                _logger.error("cron_batch_update: no se pudo desmarcar orden %s: %s", order_name, ue)
                try:
                    cr.rollback()
                except Exception:
                    pass

        remaining = pending_total - len(order_ids)
        _logger.info("cron_batch_update_marked_orders: OK=%d errores=%d restantes=%d%s",
                     ok, len(errors), remaining,
                     " | errores: " + str(errors[:5]) if errors else '')

        for acc_id, execution in executions_by_acc.items():
            acc = AccountModel.browse(acc_id)
            if not acc.exists():
                continue
            _ok = ok_by_acc.get(acc_id, 0)
            _err = err_by_acc.get(acc_id, 0)
            _state = 'success' if _err == 0 else ('warning' if _ok > 0 else 'error')
            try:
                acc._end_cron_execution(
                    execution, state=_state,
                    items_processed=_ok + _err,
                    items_success=_ok,
                    items_error=_err,
                    log_summary="OK=%d Err=%d Restantes=%d" % (_ok, _err, remaining),
                )
            except Exception as _track_err:
                _logger.warning("cron_batch_update: tracking _end_cron_execution falló para cuenta %s: %s",
                                acc_id, _track_err)

    @api.model
    def cron_meli_drain_draft_invoices(self, batch_size=30):
        """Cron safety-net: auto-descubre facturas en BORRADOR en diarios AFIP
        (l10n_ar_afip_pos_number) vinculadas a pedidos ML confirmados y las postea
        vía sale_order.meli_create_invoice() — PATH LIVIANO: NO hace refetch a la
        API de MercadoLibre (a diferencia del cron mark-driven, que sí). Pensado
        para drenar borradores acumulados (p.ej. tras un desfasaje de secuencia
        AFIP) sin marcar a mano ni martillar la API de ML.

        - Procesa las más VIEJAS primero (prioriza cierre fiscal del mes).
        - Una factura por commit independiente, con reintentos ante
          SerializationFailure/deadlock (el conector toca registros en paralelo).
        - meli_create_invoice() es dedup-safe (guard `if not invoices`): postea el
          borrador existente, NO duplica.
        - active=False por default — habilitar a mano desde Ajustes > Técnico >
          Acciones planificadas. Supersede el reintento de drafts hecho ad-hoc.
        """
        AM = self.env['account.move'].sudo()
        drafts = AM.search([
            ('state', '=', 'draft'),
            ('move_type', '=', 'out_invoice'),
            ('journal_id.l10n_ar_afip_pos_number', '!=', False),
        ], order='invoice_date asc, id asc')
        if not drafts:
            _logger.info("cron_meli_drain_draft_invoices: no hay borradores AFIP")
            return

        seen = set()
        batch = self.env['sale.order'].sudo()
        for inv in drafts:
            for so in inv.line_ids.sale_line_ids.order_id:
                if so.id in seen or so.state not in ('sale', 'done'):
                    continue
                if not so.meli_orders:
                    continue
                seen.add(so.id)
                batch |= so
                if len(batch) >= batch_size:
                    break
            if len(batch) >= batch_size:
                break

        _logger.info("cron_meli_drain_draft_invoices: %d borradores AFIP, procesando %d pedidos (batch_size=%d)",
                     len(drafts), len(batch), batch_size)

        cr = self.env.cr
        ok = 0
        errors = 0
        for so in batch:
            for attempt in range(3):
                try:
                    so.meli_create_invoice()
                    cr.commit()
                    ok += 1
                    break
                except Exception as e:
                    cr.rollback()
                    msg = str(e).lower()
                    if ('serialize' in msg or 'deadlock' in msg) and attempt < 2:
                        continue
                    errors += 1
                    _logger.error("cron_meli_drain_draft_invoices: error en pedido %s: %s",
                                  so.name, str(e)[:200])
                    break

        _logger.info("cron_meli_drain_draft_invoices: fin — ok=%d err=%d restantes~%d",
                     ok, errors, max(0, len(drafts) - ok))

    def brand_fix( self ):
        self._meli_brand_fix()

    def _meli_brand_fix( self ):
        #_logger.info("_meli_brand_fix")
        mos = self.search([('brand','=',None)],order='connection_account')
        #_logger.info("_meli_brand_fix "+str(mos))
        account = None
        mercadolibre_brands = []
        for mo in mos:
            mo.brand = None

            if (account!= mo.connection_account):
                account = mo.connection_account
                mercadolibre_brands = account._mercadolibre_brands()

            if mo.order_items:
                moi = mo.order_items[0]
                if moi:
                    for br in mercadolibre_brands:
                        if moi.order_item_id:
                            binds = self.env["mercadolibre.product_template"].search([('conn_id','=ilike',str(moi.order_item_id))])
                            if (binds):
                                for bind in binds:
                                    if (bind.meli_official_store_id and str(br.official_store_id)==str(bind.meli_official_store_id) ):
                                        mo.brand = br
                                    if (not bind.meli_official_store_id):
                                        mo.orders_update_order()


    def _meli_brand( self ):
        account = None
        mercadolibre_brands = []
        for mo in self:
            mo.brand = None
            if mo.order_items:
                moi = mo.order_items[0]
                if moi:
            #        #associate brand with product official_store_id
                    if (account!= mo.connection_account):
                        account = mo.connection_account
                        mercadolibre_brands = account._mercadolibre_brands()
                    #_logger:info("Brands:"+str(mercadolibre_brands))
                    for br in mercadolibre_brands:
                        if moi.order_item_id:
                            binds = self.env["mercadolibre.product_template"].search([('conn_id','=ilike',str(moi.order_item_id))])
                            #_logger:info("bind:"+str(bind and bind.meli_official_store_id))
                            if (binds):
                                for bind in binds:
                                    if (bind.meli_official_store_id and str(br.official_store_id)==str(bind.meli_official_store_id) ):
                                        mo.brand = br

    brand = fields.Many2one("mercadolibre.brand", string="Brand" )


    def update_order_status( self, meli=None, config=None):
        for order in self:
            account = ("connection_account" in order._fields and order.connection_account)
            config = config or account.configuration
            order._meli_brand()

            company = (config and 'company_id' in config._fields and config.company_id) or self.env.user.company_id
            config = config or company

            if not meli:
                meli = self.env['meli.util'].get_new_instance(company,account=account)
            if not meli:
                return {}
            response = meli.get("/orders/"+str(order.order_id), {'access_token':meli.access_token})
            order_json = response.json()
            if "id" in order_json:
                if (str(order.status)!=str(order_json["status"])):
                    #full update if status changed!
                    order.orders_update_order(meli=meli,config=config)
                order.status = order_json["status"]
                order.status_detail = order_json["status_detail"] or ''
                if order.sale_order:
                    order.sale_order.confirm_ml(meli=meli,config=config)

    def prepare_ml_order_vals( self, meli=None, order_json=None, config=None ):

        order_fields = super(MercadoLibreOrder, self).prepare_ml_order_vals(meli=meli, order_json=order_json, config=config)

        account = meli_config_account(config)
        if account:
            company = account.company_id

            order_fields["connection_account"] = account.id
            order_fields["company_id"] = company.id
            #order_fields['seller_id'] = seller_id,

        #_logger.info("prepare_ml_order_vals (multiple) > order_fields:"+str(order_fields))

        return order_fields

    def prepare_sale_order_vals( self, meli=None, order_json=None, config=None, sale_order=None, shipment=None ):

        meli_order_fields = super(MercadoLibreOrder, self).prepare_sale_order_vals(meli=meli, order_json=order_json, config=config,sale_order=sale_order, shipment=shipment)

        if config and "accounts" in config._fields and config.accounts:
            account = config.accounts[0]
            company = account.company_id

            meli_order_fields["company_id"] = company.id
            #order_fields['seller_id'] = seller_id,

        #_logger.info("prepare_sale_order_vals (multiple) > meli_order_fields:"+str(meli_order_fields))

        return meli_order_fields

    def search_meli_product( self, meli=None, meli_item=None, config=None ):

        #_logger.info("search_meli_product (multiple): "+str(meli_item))
        product_related = None
        check_sku = True
        check_barcode = True
        product_obj = self.env['product.product']
        binding_obj = self.env['mercadolibre.product']

        if not meli_item:
            return product_obj

        account = None
        account_filter = []

        account = meli_config_account(config, fallback=('connection_account' in self._fields and self[:1].connection_account) or None)
        if account:
            account_filter = [('connection_account','=',account.id)]
        else:
            _logger.error("search_meli_product (multiple): no account")
            return []

        meli_id = meli_item['id']
        meli_id_variation = ("variation_id" in meli_item and meli_item['variation_id'])
        seller_sku = ('seller_sku' in meli_item and meli_item['seller_sku']) or ('seller_custom_field' in meli_item and meli_item['seller_custom_field'])
        # 26.363 (caso-K10): SKU con espacios no separables (U+00A0) ⇒ normalizado antes de buscar.
        seller_sku = meli_norm_sku(seller_sku)

        rjson = account.fetch_meli_product( meli_id=meli_id, meli=meli )
        #_logger.info("rjson: " + str(rjson) )
        meli_official_store_id = rjson and "official_store_id" in rjson and rjson["official_store_id"]
        account_store_id = account
        account_filter = [('connection_account','=',account_store_id.id)]

        if (str(account.official_store_id)!=str(meli_official_store_id)):
            #change account
            #_logger.info("search_meli_product > changing account:"+str(meli_official_store_id))
            account_store_id = self.env['mercadolibre.account'].search( [( 'official_store_id', '=ilike', str(meli_official_store_id) )], limit=1 )
            #_logger.info("search_meli_product > account_store_id:"+str(account_store_id))
            if (account_store_id):
                account_filter = [('connection_account','=',account_store_id.id)]
            else:
                account_store_id = account

        if (not (seller_sku)):
            #check product actual sku
            seller_sku = account.fetch_meli_sku(
                                    meli_id=meli_id,
                                    meli_id_variation=meli_id_variation,
                                    meli=meli,
                                    rjson=rjson)
        seller_barcode = account.fetch_meli_barcode(
                                meli_id=meli_id,
                                meli_id_variation=meli_id_variation,
                                meli=meli,
                                rjson=rjson)

        #_logger.info("search_meli_product (multiple): seller_sku: "+str(seller_sku)+ " barcode: "+str(seller_barcode) )

        bindP = False

        if (meli_id_variation):
            bindP = binding_obj.search([('conn_id','=',meli_id),
                                        ('conn_variation_id','=',meli_id_variation)]
                                        + account_filter,
                                        limit=1)

        if not bindP:
            bindP = binding_obj.search([('conn_id','=',meli_id)]
                                        + account_filter,
                                        limit=1)

        #_logger.info("search_meli_product (multiple): bindP: "+str(bindP))

        # [#caso-K70 cliente F caso-K21, 29-oct-2026] La vinculacion EXPLICITA gana sobre la heuristica GTIN/SKU.
        # Antes, un binding encontrado se DESCARTABA si el GTIN de ML no era el barcode del producto
        # y el SELLER_SKU no era su referencia: la venta caia por SKU en OTRO producto (un combo/kit
        # vinculado a la publicacion entraba como el articulo suelto que tiene ese GTIN/SKU).
        # Se respeta solo si el binding es EXACTO y sin ambiguedad: la variacion de la venta (o la
        # publicacion sin variacion) vinculada a UN solo producto. El fallback por conn_id cuando
        # la venta trae variacion, o varios productos, siguen verificando GTIN/SKU como antes.
        bind_exact = _meli_exact_binding_product(binding_obj, meli_id, meli_id_variation, account_filter)
        if bind_exact:
            if ((seller_barcode and str(seller_barcode) != str(bind_exact.barcode or ''))
                    or (seller_sku and str(seller_sku) != str(bind_exact.default_code or ''))):
                _logger.info("search_meli_product (multiple): %s/%s vinculada a %s [%s]: se respeta la "
                                "vinculacion aunque ML informa SKU %s / GTIN %s.", meli_id, meli_id_variation or '-',
                                bind_exact.display_name, bind_exact.default_code or '', seller_sku, seller_barcode)
            return bind_exact

        product_related = (bindP and bindP.product_id)

        product_related_barcode = None
        if product_related:
            #_logger.info("product_related from binding:"+str(product_related))

            if seller_barcode and check_barcode:
                if seller_barcode and len(product_related)>0:
                    if ( not meli_gtin_same(seller_barcode, product_related and product_related[0].barcode) ):  # 26.389 (caso-K77)
                        #force search by sku
                        #_logger.info("search_meli_product (multiple): binding found, but force check barcode not passed: "+str(seller_barcode))
                        product_related_barcode = []
                else:
                    product_related_barcode = product_related

            if not product_related_barcode and check_sku:
                if seller_sku and len(product_related)>0:
                    if ( str(seller_sku) != str(product_related and product_related[0].default_code)):
                        #force search by sku
                        #_logger.info("search_meli_product (multiple): binding found, but force check sku not passed: "+str(seller_sku))
                        product_related = []
            else:
                return product_related

        #classic meli_oerp version:
        if (meli_id_variation):
            product_related = product_obj.search([ ('meli_id','=',meli_id), ('meli_id_variation','=',meli_id_variation) ])
            if "mercadolibre_update_product_company" in config._fields and config.mercadolibre_update_product_company:
                product_related = product_obj.sudo().search([ ('meli_id','=',meli_id), ('meli_id_variation','=',meli_id_variation)])
                for p in product_related:
                    if (p.company_id != account.company_id):
                        _logger.info("product_related bad company: "+str(p.default_code))
                    #p.company_id = account.company_id
                    #p.product_tmpl_id.company_id = account.company_id
        else:
            if not product_related:
                product_related = product_obj.search([('meli_id','=', meli_id)])
                if "mercadolibre_update_product_company" in config._fields and config.mercadolibre_update_product_company:
                    product_related = product_obj.sudo().search([ ('meli_id','=',meli_id) ])
                    for p in product_related:
                        if (p.company_id != account.company_id):
                            _logger.info("product_related bad company: "+str(p.default_code))
                        #p.company_id = account.company_id
                        #p.product_tmpl_id.company_id = account.company_id

        #_logger.info("product_related from product:"+str(product_related))

        if check_barcode and seller_barcode and product_related and len(product_related)>0:
            if ( not meli_gtin_same(seller_barcode, product_related and product_related[0].barcode) ):  # 26.389 (caso-K77)
                #force search by sku
                #_logger.info("search_meli_product (multiple): Master founded but force check barcode not passed: "+str(seller_barcode))
                product_related_barcode = []
            else:
                product_related_barcode = product_related

        if not product_related_barcode and check_sku and seller_sku and product_related and len(product_related)>0:
            if ( str(seller_sku) != str(product_related and product_related[0].default_code)):
                #force search by sku
                #_logger.info("search_meli_product (multiple): Master founded but force check sku not passed: "+str(seller_sku))
                product_related = []

        if ( len(product_related)==0 and seller_sku):

            #1ST attempt "seller_sku" or "seller_custom_field"
            if (seller_sku):
                #_logger.info("search_meli_product (multiple): Search using seller_sku: "+str(seller_sku))
                product_related = product_obj.search([('default_code','=ilike',seller_sku),'|',('company_id','=',account.company_id.id),('company_id','=',False)])
                if "mercadolibre_update_product_company" in config._fields and config.mercadolibre_update_product_company:
                    product_relateds = product_obj.sudo().search([('default_code','=ilike',seller_sku),'|',('company_id','=',account.company_id.id),('company_id','=',False)])
                    if product_relateds:
                        for p in product_relateds:
                            if (p.company_id != account.company_id):
                                _logger.info("product_related bad company: "+str(p.default_code))
                            #p.company_id = account.company_id
                            #p.product_tmpl_id.company_id = account.company_id

            #2ND attempt only old "seller_custom_field"
            if (not product_related and 'seller_custom_field' in meli_item and meli_item['seller_custom_field']):
                seller_sku = ('seller_custom_field' in meli_item and meli_item['seller_custom_field'])
                #_logger.info("search_meli_product (multiple): Search using seller_custom_field: "+str(seller_sku))
                product_related = product_obj.search([('default_code','=ilike',seller_sku),'|',('company_id','=',account.company_id.id),('company_id','=',False)])
                if "mercadolibre_update_product_company" in config._fields and config.mercadolibre_update_product_company:
                    product_relateds = product_obj.sudo().search([('default_code','=ilike',seller_sku)])
                    if product_relateds:
                        for p in product_relateds:
                            if (p.company_id != account.company_id):
                                _logger.info("product_related bad company: "+str(p.default_code))
                            #p.company_id = account.company_id
                            #p.product_tmpl_id.company_id = account.company_id

            #TODO: 3RD attempt using barcode
            #if (not product_related):
            #   search using item attributes GTIN and SELLER_SKU

            if (len(product_related)):
                #_logger.info("order product related by seller_sku and default_code:"+str(seller_sku) )

                if (len(product_related)>1):
                    product_related = product_related[0]

                if (not product_related.meli_id):
                    prod_fields = {
                        'meli_id': meli_item['id'],
                        'meli_pub': True,
                    }
                    #_logger.info("Binding item:"+str(prod_fields) +" product_related:"+str(product_related) )
                    if "mercadolibre_update_product_company" in config._fields and config.mercadolibre_update_product_company:
                        prod_fields['company_id'] = account.company_id.id
                    product_related.sudo().write((prod_fields))  # bind meli_id con privilegios (cron Vendedor ML sin grupo productos)
                    if (product_related.product_tmpl_id):
                        product_related.product_tmpl_id.meli_pub = True
                    if (config.mercadolibre_create_product_from_order and seller_sku):
                        product_related.product_meli_get_product(meli=meli)
                    #brand_account =
                    product_related.mercadolibre_bind_to( account=account_store_id, binding_product_tmpl_id=False, meli_id=meli_item['id'], meli_id_variation=meli_item['variation_id'], meli=meli, bind_only=True )
                    #if (seller_sku):
                    #    prod_fields['default_code'] = seller_sku
                elif (product_related.meli_id):
                    #_logger.info("Add mercadolibre bind to: " +str(meli_item['id'])+" - "+str(meli_item['variation_id']))
                    if (product_related.product_tmpl_id):
                        product_related.product_tmpl_id.meli_pub = True
                    product_related.mercadolibre_bind_to( account=account_store_id, binding_product_tmpl_id=False, meli_id=meli_item['id'], meli_id_variation=meli_item['variation_id'], meli=meli, bind_only=True )

            else:
                combination = []
                if ('variation_id' in meli_item and meli_item['variation_id'] ):
                    combination = [( 'meli_id_variation','=',meli_item['variation_id'])]
                product_related = product_obj.search([('meli_id','=',meli_item['id'])] + combination)
                if (product_related and len(product_related)):
                    _logger.info("Product founded:"+str(meli_item['id']))
                else:
                    #optional, get product
                    productcreated = None
                    product_related = None

                    try:
                        response3 = meli.get("/items/"+str(meli_item['id']), {'access_token':meli.access_token})
                        rjson3 = response3.json()
                        prod_fields = {
                            'name': rjson3['title'].encode("utf-8"),
                            'description': rjson3['title'].encode("utf-8"),
                            'meli_id': rjson3['id'],
                            'meli_pub': True,
                        }
                        prod_fields.update(ProductType())
                        if (seller_sku):
                            prod_fields['default_code'] = seller_sku
                        if "mercadolibre_update_product_company" in config._fields and config.mercadolibre_update_product_company:
                            prod_fields['company_id'] = account.company_id.id
                        #prod_fields['default_code'] = rjson3['id']
                        #productcreated = False
                        with self.env.cr.savepoint():
                            if (config.mercadolibre_create_product_from_order and seller_sku):
                                #_logger.info( "Creando producto: "+str(prod_fields) )
                                # sudo: crear el producto on-the-fly al importar una orden es una INTEGRACIÓN DE SISTEMA, no una acción de usuario. El cron puede correr como el Vendedor ML (with_user) que NO tiene grupo de creación de productos → sin sudo lanza AccessError (product.template/product.product). Gate de negocio: config.mercadolibre_create_product_from_order.
                                productcreated = self.env['product.product'].sudo().create((prod_fields))
                            if (productcreated):
                                if (productcreated.product_tmpl_id):
                                    productcreated.product_tmpl_id.meli_pub = True
                                #_logger.info( "product created: " + str(productcreated) + " >> meli_id:" + str(rjson3['id']) + "-" + str( rjson3['title'].encode("utf-8")) )
                                #pdb.set_trace()
                                #_logger.info(productcreated)
                                productcreated.product_meli_get_product(meli=meli)
                                productcreated.mercadolibre_bind_to( account=account_store_id, binding_product_tmpl_id=False, meli_id=meli_item['id'], meli=meli, bind_only=True )
                            else:
                                _logger.info( "product couldnt be created. Crear producto desde la orden? "+str(config.mercadolibre_create_product_from_order))
                            product_related = productcreated
                    except Exception as e:
                        #_logger.info("Error creando producto.")
                        _logger.error(e, exc_info=True)
                        pass;

                if ('variation_attributes' in meli_item):
                    _logger.info("TODO: search by attributes")

        #_logger.info("search_meli_product (multiple) ended: "+str(meli_item))
        # [caso-K15 cliente E] nunca devolver None. Si la creacion del producto desde la orden falla
        # (savepoint revertido), product_related queda en None y los herederos
        # (meli_oerp_stock: len(product_related)) rompen con "NoneType has no len()": la
        # orden no entra nunca y la notificacion se reintenta. Con un recordset vacio sigue
        # el camino normal (busqueda por SKU / aviso "PRODUCTO NO ENCONTRADO").
        return product_related or product_obj

    def orders_update_order( self, context=None, meli=None, config=None ):

        #_logger.info("meli_oerp_multiple >> orders_update_order")
        #get with an item id
        company = self.env.user.company_id

        order_obj = self.env['mercadolibre.orders']
        order = self
        order._meli_brand()

        account = order.connection_account

        if not account and order.seller:
            #_logger.info( "orders_update_order >> NO ACCOUNT for order, check seller id vs accounts: " + str(order.seller) )
            # order.seller se guarda como str(dict) (repr de Python); nunca eval() (auditoría de seguridad, un caso)
            sellerjson = None
            try:
                sellerjson = ast.literal_eval( order.seller )
            except (ValueError, SyntaxError):
                try:
                    sellerjson = json.loads( order.seller )
                except ValueError:
                    sellerjson = None
            if not isinstance( sellerjson, dict ):
                sellerjson = None
            if sellerjson and "id" in sellerjson:
                seller_id = sellerjson["id"]
                if seller_id:
                    accounts = self.env["mercadolibre.account"].search([('seller_id','=',seller_id)])
                    if accounts and len(accounts):
                        #use first coincidence
                        account = accounts[0]
                        order.connection_account = account

        if account:
            account = order.connection_account
            company = account.company_id
            if not config:
                config = account.configuration

        log_msg = 'orders_update_order: %s' % (order.order_id)
        #_logger.info(log_msg)

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )

        if not config:
            config = company

        response = meli.get("/orders/"+str(order.order_id), {'access_token':meli.access_token})
        order_json = response.json()
        #_logger.info( order_json )

        if "error" in order_json:
            _logger.error( order_json["error"] )
            _logger.error( order_json["message"] )
        else:
            try:
                with self.env.cr.savepoint():
                    self.orders_update_order_json( {"id": order.id, "order_json": order_json }, meli=meli, config=config )
                #MeliCommit( self )
            except Exception as e:
                #_logger.info("orders_update_order > Error actualizando ORDEN")
                _logger.error(e, exc_info=True)
                meli_message_post(order, "Error actualizando ORDEN: "+str(e), config=config)
                pass;

            #_logger.info("orders_update_order journal_id: "+str(order.name))
            if order.sale_order and "mercadolibre_invoice_journal_id" in config._fields and config.mercadolibre_invoice_journal_id:
                #_logger.info("order.sale_order > config.mercadolibre_invoice_journal_id: "+str(config.mercadolibre_invoice_journal_id))
                if "journal_id" in order.sale_order._fields:
                    #_logger.info("order.sale_order.journal_id: "+str(order.sale_order.journal_id))
                    order.sale_order.journal_id = config.mercadolibre_invoice_journal_id
                    #_logger.info("orders_update_order order.journal_id: "+str(order.sale_order.journal_id))
            if order.sale_order:
                if (config.mercadolibre_order_confirmation!="manual"):
                    try:
                        with self.env.cr.savepoint():
                            order.sale_order.confirm_ml( meli=meli, config=config )
                    except Exception as e:
                        _logger.error("confirm_ml failed for order %s: %s", order.order_id, e, exc_info=True)

        return {}

    def orders_update_order_json( self, data, context=None, config=None, meli=None ):
        #_logger.info("meli_oerp_multiple >> orders_update_order_json START")
        res = super(MercadoLibreOrder, self).orders_update_order_json( data=data, context=context, config=config, meli=meli)
        #_logger.info("meli_oerp_multiple >> orders_update_order_json END: "+str(res))
        company = self.env.user.company_id

        res2 = {}

        if self.sale_order:
            self._meli_brand()
            #_logger.info("meli_oerp_multiple >> calling _meli_order_update")
            #res2 = super(SaleOrderMul, self.sale_order)._meli_order_update(account=self.connection_account)
            res2 = self.sale_order.multi_meli_order_update(account=self.connection_account)


        #MeliCommit( self )
        #_logger.info("meli_oerp_multiple >> orders_update_order_json END2: "+str(res))
        return res

    def _get_config( self, config=None ):
        config = config or (self and self.connection_account and self.connection_account.configuration) or (self and self.company_id)
        return config

    def _meli_cancel_api(self, config=None):
        """Cliente de ML para leer la foto de una cancelacion con el token de la CUENTA de la
        orden (sin esto, get_new_instance() elige la primera cuenta conectada del usuario y la
        foto de otra cuenta vuelve 403/404 => la cancelacion quedaria en espera para siempre)."""
        self.ensure_one()
        account = "connection_account" in self._fields and self.connection_account
        if not account:
            return super()._meli_cancel_api(config=config)
        meli = self.env['meli.util'].get_new_instance(account.company_id, account=account)
        if not meli or getattr(meli, "needlogin_state", False):
            return None
        return meli

    def _meli_post_sale_custom_message( self, config=None ):
        """Mensaje postventa propio de la cuenta (Configuración › «Mensaje postventa»), o None."""
        config = self._get_config(config=config)
        if config and 'mercadolibre_post_sale_message' in config._fields:
            return (config.mercadolibre_post_sale_message or '').strip() or None
        return None

    def _meli_autofactura_installed( self ):
        """La plantilla por defecto apunta a /AUTOFACTURA/register, que sólo existe con meli_oerp_autofacturacion."""
        return bool(self.env['ir.module.module'].sudo().search_count([
            ('name', '=', 'meli_oerp_autofacturacion'), ('state', '=', 'installed')]))

    def send_post_message_inv_link( self ):
        """Botón «Mensaje Postventa (mensaje autofactura)»: manda la liga de facturación al comprador.
        26.351 (#caso-K68 cliente B1). Texto, en orden: el «Mensaje postventa» de la configuración de la
        cuenta; el «Mensaje y link autofactura» de meli_oerp_autofacturacion (el mismo de confirm_ml);
        la plantilla con /AUTOFACTURA/register (sólo con autofacturación instalada). Antes pasaba
        message=None y salía «Buen día, gracias por su compra» SIN la liga."""
        res = True
        for order in self:
            config = order._get_config()
            message = order._meli_post_sale_custom_message(config) \
                or (config and 'autoinvoice_message' in config._fields and config.autoinvoice_message) or None
            res = order.send_post_message(message=message, config=config, force_send=True)
        return res

    def action_send_post_message( self ):
        """Botón «Mensaje Postventa»: con «Mensaje postventa» configurado en la cuenta manda ese mismo
        texto (#caso-K68: el mismo en los dos botones); sin configurar, como antes, sólo consulta y registra
        en la venta qué mensajes permite ML, sin escribirle al comprador."""
        res = True
        for order in self:
            config = order._get_config()
            message = order._meli_post_sale_custom_message(config)
            res = order.send_post_message(message=message, config=config, force_send=bool(message))
        return res

    def _meli_post_sale_buyer_name( self ):
        """Nombre para el saludo: first_name, si no name; nunca el nickname (#caso-K68)."""
        buyer = 'buyer' in self._fields and self.buyer
        if not buyer:
            return ''
        return (buyer.first_name or '').strip() or (buyer.name or '').strip()

    def _meli_post_sale_invoice_text( self, message=None, base_url=None, config=None ):
        """Texto de la opción SEND_INVOICE_LINK de ML => (texto, None) o (None, motivo) si NO hay que enviar.
        26.351 (#caso-K68). Comodines: {BUYER} {ORDERID} {ORDERAMOUNT} {LINK}.
        {LINK} = el campo de la venta indicado en «Campo de la liga de facturación» (liga propia de cada
        orden; vacía => no se envía, para no mandar una liga rota) o, sin ese campo, <base_url>/AUTOFACTURA/register.
        Sin mensaje propio y sin autofacturación instalada no se envía (la liga por defecto daría 404)."""
        config = self._get_config(config=config)
        so = self and self.sale_order
        link_field = (config and 'mercadolibre_post_sale_link_field' in config._fields
                      and (config.mercadolibre_post_sale_link_field or '').strip()) or ''
        if link_field:
            if not so or link_field not in so._fields:
                return None, "la venta no tiene el campo de liga de facturación «%s»" % link_field
            link = str(so[link_field] or '').strip()
            if not link:
                return None, "la liga de facturación de la venta (campo %s) está vacía" % link_field
        else:
            link = str(base_url or '') + "/AUTOFACTURA/register"
        if not message:
            if not link_field and not self._meli_autofactura_installed():
                return None, ("no hay mensaje postventa configurado: cargarlo en la configuración de la cuenta "
                              "(«Mensaje postventa» y «Campo de la liga de facturación»)")
            message = "Para obtener su factura por favor acceder a: {LINK} con los siguientes datos: {ORDERID} - {ORDERAMOUNT}"
        text = message.replace('{LINK}', link)
        if '{BUYER}' in text:
            name = self._meli_post_sale_buyer_name()
            text = text.replace('{BUYER}', name) if name else re.sub(r'[ ,]*\{BUYER\}', '', text)
        if so and so.name and so.amount_total:
            text = text.replace('{ORDERID}', str(so.name))
            text = text.replace('{ORDERAMOUNT}', str(so.amount_total))
        return text, None

    def send_post_message( self, message=None, config=None, force_send=False):
        #_logger.info("send_post_message: "+str(message)+" order:"+str(self.order_id))
        #_logger.info("send_post_message: "+str(message))
        account = self and self.connection_account
        config = self and self._get_config(config=config)
        pack_id = self.pack_id or self.order_id
        so = self and self.sale_order

        #_logger.info("send_post_message: "+str(account and account.name)+" pack_id:"+str(pack_id))

        if account:
            #/messages/action_guide/packs/200000000000/caps_available?tag=post_sale
            company = account.company_id
            base_url = company.get_base_url()
            base_autofac = None
            if force_send:
                base_autofac, why = self._meli_post_sale_invoice_text(message=message, base_url=base_url, config=config)
                if not base_autofac:
                    _logger.warning("send_post_message %s: no se envia: %s", pack_id, why)
                    if so:
                        so.message_post(body="Mensaje postventa NO enviado: "+str(why))
                    return False

            meli = self.env['meli.util'].get_new_instance( account.company_id, account )
            if meli:
                uri = "/messages/action_guide/packs/"+str(pack_id)+"/caps_available?tag=post_sale"
                response = meli.get(uri,{'access_token':meli.access_token})
                rjson = response and response.json()
                #_logger.info("send_post_message:"+str(rjson))
                if so:
                    so.message_post(body=str("Mensajes post venta: ")+str(rjson))

                site_id = account.company_id._get_ML_sites(meli=meli)
                #_logger.info("send_post_message: "+str(site_id)+" base_url:"+str(base_url) )

                #if site_id=="MLA" and not 'error' in rjson:
                #_logger.info("send_post_message:"+str(site_id))

                # MLA
                # [{'option_id': 'OTHER', 'cap_available': 1}, {'option_id': 'REQUEST_VARIANTS', 'cap_available': 20}, {'option_id': 'REQUEST_BILLING_INFO', 'cap_available': 20}]
                #https://api.mercadolibre.com/messages/action_guide/packs/<order_id>/option
                for res in rjson:
                    #_logger.info("send_post_message res:"+str(res))
                    option = res

                    if (res and res=="error" or "error" in res):
                        _logger.warning("send_post_message error:"+str(res))
                        break;

                    #_logger.info("send_post_message base_autofac:"+str(base_autofac) )

                    if (force_send and option['option_id']=='SEND_INVOICE_LINK' and option['cap_available']>=1):
                        #_logger.info("send_post_message SEND_INVOICE_LINK")
                        uri = "/messages/action_guide/packs/"+str(pack_id)+"/option"
                        if so:
                            so.message_post(body="AUTOFACTURA ENVIANDO: "+str(base_autofac))
                        response2 = meli.post(uri,body={
                            'option_id': 'SEND_INVOICE_LINK',
                            "text": base_autofac
                        },params={
                            'access_token':meli.access_token
                        })
                        if so:
                            so.message_post(body="RESULTADO: "+str(response2))

                        rjson2 = response2.json()
                        _logger.info("send_post_message SEND_INVOICE_LINK:"+str(rjson2))
                        if hasattr(self, '_meli_post_sale_mark_manual'):
                            self._meli_post_sale_mark_manual(rjson2)  # 26.370 (#caso-K67): el automático no lo repite

                    if (1==2 and force_send and option['option_id']=='OTHER' and option['cap_available']==1):
                        #_logger.info("send_post_message OTHER")
                        uri = "/messages/action_guide/packs/"+str(pack_id)+"/option"

                        response2 = meli.post(uri,body={
                            'option_id': 'OTHER',
                            "text": base_autofac
                        },params={
                            'access_token':meli.access_token
                        })

                        rjson2 = response2.json()
                        #_logger.info("send_post_message:"+str(rjson2))


                    if (1==2 and force_send and option['option_id']=='REQUEST_BILLING_INFO' and option['cap_available']==20):
                        #_logger.info("send_post_message REQUEST_BILLING_INFO")
                        uri = "/messages/action_guide/packs/"+str(pack_id)+"/option"
                        response2 = meli.post(uri,body={
                            'option_id': 'REQUEST_BILLING_INFO',
                            'template_id': 'TEMPLATE___REQUEST_BILLING_INFO___1'
                        },params={
                            'access_token':meli.access_token
                        })
                        rjson2 = response2.json()
                        #_logger.info("send_post_message:"+str(rjson2))
                        #{'id': '5cbcb23d56f342c5827e520c8b583f74', 'status': 'available', 'text': 'Hola, estoy generando la factura de tu compra y necesito los siguientes datos: Nombre y apellido, DNI, domicilio, código postal. Gracias.', 'text_translated': None, 'to': {'user_id': 36064836, 'name': None}, 'message_date': {'received': None, 'available': '2023-08-30T13:13:39Z', 'notified': '2023-08-30T13:13:39Z', 'created': '2023-08-30T13:13:39Z', 'read': None}, 'message_moderation': {'status': 'clean', 'reason': '', 'source': 'online', 'moderation_date': '2023-08-30T13:13:39Z'}}


                # MLM
                #




class SaleOrderLine(models.Model):

    _inherit = "sale.order.line"

    #here we must use Many2one more accurate, there is no reason to have more than one binding (more than one account and more than one item/order associated to one sale order line)
    mercadolibre_bindings = fields.Many2one( "mercadolibre.sale_order_line", string="MercadoLibre Connection Bindings" )


class AccountMove(models.Model):

    _inherit = "account.move"

    def meli_global_invoice_fix_status(self):

        for inv in self:
            for iline in inv.invoice_line_ids:
                order = iline.meli_sale_id
                if order:
                    for oli in order.order_line:
                        oli.qty_invoiced = oli.qty_to_invoice
                        oli.invoice_status = "invoiced"
                    order.invoice_status = "invoiced"

class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    #meli_sale_id = fields.Many2one("sale.order",string="Orden ML")
    #meli_sale_name = fields.Char(string="Label ML")
    #meli_sale_invoice_status = fields.Selection(string="Invoice",related="meli_sale_id.invoice_status")

class ResPartner(models.Model):

    _inherit = "res.partner"

    #several possible relations? we really dont know for sure, how to not duplicate clients from different platforms
    #besides, is there a way to identify duplicates other than integration ids
    mercadolibre_bindings = fields.Many2many( "mercadolibre.client", string="MercadoLibre Connection Bindings" )

class mercadolibre_shipment(models.Model):

    _inherit = "mercadolibre.shipment"

    # Contador acotado de re-consultas del cron de etiquetas (un caso). Sin tope, un
    # envio que nunca va a tener etiqueta (retiro en sucursal, flex, cancelado)
    # se re-consultaria en cada corrida para siempre. Mismo patron que
    # meli_stock_retry_count (un caso).
    meli_label_retry_count = fields.Integer(
        string="Reintentos de etiqueta",
        default=0,
        copy=False,
        help="Cuantas veces el cron de reintento de etiquetas volvio a consultar este envio.")

    def _meli_label_instance(self):
        """un caso: la etiqueta se baja con el token de la cuenta de la orden (como shipment_print)."""
        self.ensure_one()
        order = self.orders and self.orders[0]
        account = order and order.connection_account
        if account:
            return self.env['meli.util'].get_new_instance(account.company_id, account)
        return super()._meli_label_instance()

    def shipment_print( self, meli=None, config=None, include_ready_to_print=None ):

        shipment = self
        order = shipment.orders and shipment.orders[0]
        account = order and order.connection_account
        company = (account and account.company_id) or self.env.user.company_id
        config = (account and account.configuration) or company

        #order by account
        if account:

            #_logger.info(" meli:"+str(meli and meli.meli_login_id)+" account:"+str(account.name)+" company:"+str(account.company_id))

            if not meli or not (meli.meli_login_id==account.meli_login_id):
                meli = self.env['meli.util'].get_new_instance( account.company_id, account )

            return super(mercadolibre_shipment,self).shipment_print(  meli=meli, config=config, include_ready_to_print=include_ready_to_print )

        return super(mercadolibre_shipment,self).shipment_print( meli=meli, config=config, include_ready_to_print=include_ready_to_print )


class mercadolibre_shipment_print(models.TransientModel):

    _inherit = "mercadolibre.shipment.print"

    def shipment_print(self, context=None, meli=None, config=None):
        context = context or self.env.context
        company = self.env.user.company_id
        #if not config:
        #    config = company

        #_logger.info( "shipment_print context: " + str(context) )

        shipment_ids = ('active_ids' in context and context['active_ids']) or []
        #check if model is stock_picking or mercadolibre.shipment
        #stock.picking > sale_id is the order, then the shipment is sale_id.meli_shipment

        active_model = context.get("active_model")

        #_logger.info( "shipment_print active_model: " + str(active_model) )
        if active_model == "stock.picking":
            shipment_ids_from_pick = []
            for spick_id in shipment_ids:
                spick = self.env["stock.picking"].browse(spick_id)
                sale_order = spick.sale_id
                if sale_order and sale_order.meli_shipment:
                    shipment_ids_from_pick.append(sale_order.meli_shipment.id)
            shipment_ids = shipment_ids_from_pick
            #_logger.info("stock.picking shipment_ids:"+str(shipment_ids))

        shipment_obj = self.env['mercadolibre.shipment']
        warningobj = self.env['meli.warning']

        return self.shipment_print_report(shipment_ids=shipment_ids,meli=meli,config=config,include_ready_to_print=self.include_ready_to_print)
