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
import json

from odoo.addons.meli_oerp_stock.models.order import SaleOrder
from odoo.addons.meli_oerp.models.versions import *

class SaleOrder(models.Model):

    _inherit = "sale.order"

    #mercadolibre could have more than one associated order... packs are usually more than one order
    mercadolibre_bindings = fields.Many2many( "mercadolibre.sale_order", string="MercadoLibre Connection Bindings",
                                             groups="meli_oerp_multiple.group_mercadolibre_connectors_manager" )

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
        if "mercadolibre_order_confirmation_hook" in config._fields and config.mercadolibre_order_confirmation_hook and self.state and self.state in ['sale','done']:
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

    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account" )

    meli_pending_batch_update = fields.Boolean(
        string="Pendiente actualización batch",
        default=False,
        index=True,
        help="Marcado por el wizard para ser procesado en el cron de actualización masiva ML."
    )

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

        if config and config.accounts:
            account = config.accounts[0]
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
            return None

        account = None
        account_filter = []

        if config.accounts:
            account = config.accounts[0]
            account_filter = [('connection_account','=',account.id)]
        else:
            _logger.error("search_meli_product (multiple): no account")
            return []

        meli_id = meli_item['id']
        meli_id_variation = ("variation_id" in meli_item and meli_item['variation_id'])
        seller_sku = ('seller_sku' in meli_item and meli_item['seller_sku']) or ('seller_custom_field' in meli_item and meli_item['seller_custom_field'])

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

        product_related = (bindP and bindP.product_id)

        product_related_barcode = None
        if product_related:
            #_logger.info("product_related from binding:"+str(product_related))

            if seller_barcode and check_barcode:
                if seller_barcode and len(product_related)>0:
                    if ( str(seller_barcode) != str(product_related and product_related[0].barcode)):
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
            if ( str(seller_barcode) != str(product_related and product_related[0].barcode)):
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
        return product_related

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
            sellerjson = eval( order.seller )
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

    def send_post_message_inv_link( self ):
        return self.send_post_message(message=None, config=None, force_send=True)

    def send_post_message( self, message=None, config=None, force_send=False):
        #_logger.info("send_post_message: "+str(message)+" order:"+str(self.order_id))
        message = message or "Buen día, gracias por su compra"
        #_logger.info("send_post_message: "+str(message))
        account = self and self.connection_account
        config = self and self._get_config(config=config)
        pack_id = self.pack_id or self.order_id
        so = self and self.sale_order

        #_logger.info("send_post_message: "+str(account and account.name)+" pack_id:"+str(pack_id))
        message = message or "Buen día, gracias por su compra"

        if account:
            #/messages/action_guide/packs/200000000000/caps_available?tag=post_sale
            company = account.company_id
            base_url = company.get_base_url()

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
                #https://api.mercadolibre.com/messages/action_guide/packs/2000000000000000/option
                for res in rjson:
                    #_logger.info("send_post_message res:"+str(res))
                    option = res

                    if (res and res=="error" or "error" in res):
                        _logger.warning("send_post_message error:"+str(res))
                        break;

                    base_autofac = "Para obtener su factura por favor acceder a: "+str(base_url)+"/AUTOFACTURA/register con los siguientes datos: {ORDERID} - {ORDERAMOUNT}"
                    base_autofac = message or base_autofac
                    if (base_autofac):
                        so = self.sale_order
                        if so and so.name and so.amount_total:
                            base_autofac = base_autofac.replace('{ORDERID}', str(so.name))
                            base_autofac = base_autofac.replace('{ORDERAMOUNT}', str(so.amount_total))
                    #_logger.info("send_post_message base_autofac:"+str(base_autofac) )

                    if (force_send and option['option_id']=='SEND_INVOICE_LINK' and option['cap_available']>=1):
                        #_logger.info("send_post_message SEND_INVOICE_LINK")
                        uri = "/messages/action_guide/packs/"+str(pack_id)+"/option"
                        if so:
                            so.message_post(body="AUTOFACTURA ENVIANDO: "+str(message))
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
