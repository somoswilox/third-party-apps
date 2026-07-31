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
from ast import literal_eval
import random

#from .warning import warning
try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode
from . import versions
from odoo.addons.meli_oerp.models.versions import *
from .versions import *
import hashlib

class MercadoLibreConnectionNotification(models.Model):

    #_name = "mercadolibre.notification"
    #_description = "MercadoLibre Notification"
    #_inherit = "ocapi.connection.notification"
    _inherit = "mercadolibre.notification"

    #Connection reference defining mkt place credentials
    connection_account = fields.Many2one( "mercadolibre.account", string="MercadoLibre Account", index=True )

    notification_parent_id = fields.Many2one( "mercadolibre.notification", string="Parent Notification",index=True)
    notification_childs = fields.One2many( "mercadolibre.notification", "notification_parent_id", string="Notificationes anteriores" )

    company = fields.Many2one("res.company",string="Noti. Company")
    company_id = fields.Many2one("res.company", related="connection_account.company_id",string="Company")
    user = fields.Many2one("res.users",string="User")

    limit_attempts = fields.Integer(string='Attempts limit')
    model_ids_step = fields.Integer(string='Models Step Count')
    model_ids_count = fields.Integer(string='Models Count')
    model_ids_count_processed = fields.Integer(string='Models Count Processed')
    model_ids = fields.Text(string="Models",readonly=False)
    model_ids_processed = fields.Text(string="Models Processed",readonly=False)

    def _prepare_values(self, values, company=None, account=None ):
        if not account:
            return {}
        company = (account and account.company_id) or self.env.user.company_id
        seller_id = None
        config = account.configuration
        if config.mercadolibre_seller_user:
            seller_id = config.mercadolibre_seller_user.id
        vals = {
            "connection_account": account.id,
            "notification_id": values["_id"],
            "application_id": values["application_id"],
            "user_id": values["user_id"],
            "company": ("company" in values and values["company"]) or company.id,
            "user": ("user" in values and values["user"]) or self.env.user.id,
            "topic": values["topic"],
            "resource": values["resource"],
            "received": ml_datetime(values["received"]),
            "sent": ml_datetime(values["sent"]),
            "attempts": values["attempts"],
            "state": "RECEIVED",
            'company_id': company.id,
            'seller_id': seller_id,
        }
        ("model_ids" in values) and vals.update({"model_ids": values["model_ids"] })
        ("model_ids_step" in values) and vals.update({"model_ids_step": values["model_ids_step"] })
        ("model_ids_count" in values) and vals.update({"model_ids_count": values["model_ids_count"] })
        ("model_ids_count_processed" in values) and vals.update({"model_ids_count_processed": values["model_ids_count_processed"] })
        ("processing_started" in values) and vals.update({"processing_started": values["processing_started"] })
        return vals

    def fetch_lasts( self, data=None, company=None, account=None, meli=None):

        #_logger.info("MercadoLibreConnectionNotification fetch_lasts: "+str(data)+str(company)+str(account))

        if not meli:
            meli = self.env['meli.util'].get_new_instance( account.company_id, account )

        try:
            messages = []
            if data:

                if not "application_id" in data:
                    return {"error": "Bad notification format!", "status": "520" }

                if str(meli.client_id) != str(data["application_id"]):
                    return {"error": "account.client_id and application_id does not match!", "status": "520" }

                if (not "_id" in data):
                    #TODO: change to UUID style, too many notifications on the same window can overlap...
                    date_time = ml_datetime( str( datetime.now() ) )
                    base_str = str(data["application_id"]) + str(data["user_id"]) + str(date_time)
                    hash = hashlib.md5()
                    hash.update( base_str.encode() )
                    hexhash = str("n")+hash.hexdigest()
                    data["_id"] = hexhash

                messages.append(data)

            #process all notifications
            res = []
            for n in messages:
                try:
                    if ("_id" in n):
                        topic = "topic" in n and n["topic"]
                        resource = "resource" in data and data["resource"]
                        #_logger.info("resource:"+str(resource))
                        noti = False
                        last_noti = False
                        all_notis = []
                        old_notis = []

                        #ver tema shipments
                        if topic and resource and topic in ["order","created_orders","orders_v2","questions"]:

                            old_notis = self.env["mercadolibre.notification"].sudo().search([( 'resource','=',str(resource) )])
                            #_logger.info("old_notis:"+str(old_notis))
                            noti = self.env["mercadolibre.notification"].sudo().start_internal_notification( n, account=account )
                            #_logger.info("new noti:"+str(noti))
                            all_notis = self.env["mercadolibre.notification"].search([( 'resource','=',str(resource) )], order='id desc')
                            #_logger.info("all_notis:"+str(all_notis))
                            #_logger.info("Created new Meli Resource notification from topic "+str(n["topic"]))

                        if all_notis:
                            # Use the latest notification
                            last_noti = all_notis[0]
                            noti = last_noti
                            # Note: Notification grouping (notification_parent_id) removed to avoid
                            # serialization errors in concurrent scenarios. The cron processes
                            # notifications regardless of grouping.

                        if (n["topic"] in ["order","created_orders","orders_v2"]):

                            if (noti):
                                # For orders_v2, only register without processing (async kills system)
                                # Processing will be done by cron_process_order_notifications
                                if n["topic"] == "orders_v2":
                                    _logger.debug("Registrada notificación orders_v2: [%s] %s", account and account.name, resource)
                                    # Just mark as received, cron will process later
                                    noti.state = 'RECEIVED'
                                else:
                                    _logger.debug("Procesando notificación order: [%s] %s", account and account.name, resource)
                                    re = noti._process_notification_order(meli=meli)
                                    if re:
                                        res.append(re)

                        if (n["topic"] in ["questions"]):
                            if (noti):
                                _logger.debug("Procesando notificación question: %s", resource)
                                re = noti._process_notification_question(meli=meli)
                                if re:
                                    res.append(re)

                except Exception as e:
                    _logger.error("Error creating notification.")
                    _logger.info(e, exc_info=True)
                    return {"error": "Error creating notification.", "status": "520" }
                    pass;
            return res

            #must upgrade to /missed_feeds
            #response = meli.get("/myfeeds", {'app_id': company.mercadolibre_client_id,'offset': 1, 'limit': 10,'access_token':meli.access_token} )
            #rjson = response.json()

            #if ("messages" in rjson):
            #    for n in rjson["messages"]:
            #        messages.append(n)

        except Exception as e:
            _logger.error("Error connecting to Meli, myfeeds")
            #_logger.info(e, exc_info=True)
            return {"error": "Error connecting to Meli.", "status": "520" }
            pass;

        return {"error": "Error connecting to Meli.", "status": "520" }

    def process_notification(self, context=None, meli=None):
        context = context or self.env.context
        _logger.info("process_notification > id:"+str(self and self.ids) + " context:"+str(context))
        #if context and "params" in context:
        #    pars = context["params"]
        #    if pars and ("id" in pars) and ("model" in pars) and (pars["model"] == "mercadolibre.notification"):
        #        self = self.browse([pars["id"]])
        #        _logger.info("process_notification self.browse: "+str(self) )
        result = []
        for noti in self:
            #_logger.info("Premium MercadoLibreConnectionNotification process notification")
            if noti.connection_account:
                account = noti.connection_account

                if (noti.topic in ["questions"]):
                    res = noti._process_notification_question(meli=meli)
                    if res:
                        result.append(res)

                if (noti.topic in ["order","created_orders","orders_v2"]):

                    res = noti._process_notification_order(meli=meli)
                    if res:
                        result.append(res)

                if noti.topic == "internal_job":
                    if "reprocess_force" in context and context["reprocess_force"]:
                        noti.model_ids_processed = False
                        noti.state = 'RECEIVED'
                        noti.processing_errors = ''
                        noti.processing_logs = ''
                    res = noti._process_notification_internal_job(meli=meli)
                    if res:
                        result.append(res)

                if noti.topic == "component_stock_update":
                    if "reprocess_force" in context and context["reprocess_force"]:
                        noti.model_ids_processed = False
                        noti.state = 'RECEIVED'
                        noti.processing_errors = ''
                        noti.processing_logs = ''
                    res = noti._process_notification_component_stock_update(meli=meli)
                    if res:
                        result.append(res)

                if noti.topic == "sales":
                    #sales = json.loads(noti.processing_logs)
                    sales = literal_eval(noti.processing_logs)

                    #_logger.info("Re Processing sales " + str(sales))

                    for sale in sales:
                        res = account.import_sale( sale, noti )
                        for r in res:
                            result.append(r)

                    #_logger.info("process_notification " + str(result))


        return result

    def _process_notification_order( self, meli=None):
        #_logger.info("meli_oerp_multiple >> _process_notification_order")

        account = self.connection_account
        #_logger.info("meli_oerp_multiple >> _process_notification_order account:"+str(account and account.name))
        if not account:
            #_logger.error("meli_oerp_multiple >> _process_notification_order no account!")
            return {}

        company = account.company_id or self.env.user.company_id
        config = account.configuration

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )

        for noti in self:
            # IDEMPOTENCY CHECK: Skip if same resource was processed recently (5 minutes)
            # This prevents cascading loops when order updates trigger new notifications
            if noti.resource:
                self.env.cr.execute("""
                    SELECT id FROM mercadolibre_notification
                    WHERE resource = %s
                      AND id != %s
                      AND state = 'SUCCESS'
                      AND processing_ended > NOW() - INTERVAL '5 minutes'
                    LIMIT 1
                """, (noti.resource, noti.id))
                recent_success = self.env.cr.fetchone()
                if recent_success:
                    _logger.info("IDEMPOTENCY SKIP: resource %s was processed recently (noti %s)", noti.resource, recent_success[0])
                    noti.state = 'SUCCESS'
                    noti.processing_errors = "Skipped: duplicate notification (order processed recently)"
                    MeliCommit(self)
                    continue

            noti.state = 'PROCESSING'
            #noti.attempts+= 1
            noti.processing_started = ml_datetime(str(datetime.now()))
            MeliCommit( self )

            # Retry logic for serialization errors
            max_retries = 3
            retry_count = 0
            last_error = None

            while retry_count < max_retries:
                try:
                    #_logger.info("meli_oerp_multiple >> processing order resource:"+str(noti.resource))
                    res = meli.get(""+str(noti.resource), {'access_token':meli.access_token} )

                    ojson =  res and res.json()
                    #_logger.info("Notification fetched: ")
                    #_logger.info(ojson)

                    if (ojson and 'error' in ojson):
                        noti.state = 'FAILED'
                        noti.processing_errors = "Notification error:"+str(ojson)
                        MeliCommit( self )
                        break  # No retry for API errors

                    if (ojson and "id" in ojson):

                        morder = self.env["mercadolibre.orders"].search( [('order_id','=',ojson["id"])], limit=1 )

                        #_logger.info(str(morder))
                        pdata = { "id": False, "order_json": ojson }

                        so = None
                        if (morder and len(morder)):
                            pdata["id"] =  morder.id
                            so = morder.sale_order or None
                            #Fix auto seller team assignation, if the team company doesnt match the account company  (access issues)
                            if so:
                                so.meli_fix_team( meli=meli, config=config )



                        # Skip invoice validation on notifications to avoid AFIP concurrent numbering issues.
                        # mail_notrack + tracking_disable: evita que Odoo escriba chatter/tracking
                        # en cada campo modificado durante el procesamiento del cron (~2-3s por orden).
                        rsjson = morder.with_context(
                            meli_skip_invoice_validation=True,
                            mail_notrack=True,
                            tracking_disable=True,
                            mail_auto_subscribe_no_notify=True,
                        ).orders_update_order_json( data=pdata, meli=meli, config=config )
                        #_logger.info("meli_oerp_multiple >> _process_notification_order >> orders_update_order_json >> rsjson: "+str(rsjson))

                        if (rsjson and 'error' in rsjson):
                            _err = str(rsjson['error'])
                            # "orden filtrada por fecha" es un SKIP intencional (orden anterior a la
                            # fecha de corte configurada), no un fallo: marcar SUCCESS para NO
                            # reprocesar en loop, y loguear a INFO (no ensucia el log como ERROR).
                            _is_date_filter = 'filtrada por fecha' in _err
                            # "No product related to meli_id" = el ítem de ML no tiene producto en
                            # Odoo (publicación borrada/no importada). Reintentar NO lo va a crear,
                            # así que es otro SKIP no-reintentable: marcar SUCCESS para no reprocesar
                            # en loop cada ~45s (la orden ya tiene su sale_order). Log a INFO.
                            _is_no_product = 'No product related to meli_id' in _err
                            _is_skip = _is_date_filter or _is_no_product
                            noti.state = 'SUCCESS' if _is_skip else 'FAILED'
                            noti.processing_errors = _err
                            MeliCommit( self )
                            _msg = "meli_oerp_multiple >> _process_notification_order >> orders_update_order_json >> rsjson error: " + _err
                            if _is_skip:
                                _logger.info(_msg)
                            else:
                                _logger.error(_msg)
                        else:
                            noti.state = 'SUCCESS'
                            noti.processing_errors = str(rsjson)
                            MeliCommit( self )

                    break  # Success, exit retry loop

                except Exception as E:
                    last_error = str(E)
                    # Check if it's a serialization error that we can retry
                    if 'could not serialize access' in last_error or 'SerializationFailure' in last_error:
                        retry_count += 1
                        if retry_count < max_retries:
                            _logger.warning("meli_oerp_multiple >> _process_notification_order >> serialization error, retry %d/%d", retry_count, max_retries)
                            import time
                            time.sleep(0.5 * retry_count)  # Exponential backoff: 0.5s, 1s, 1.5s
                            self.env.cr.rollback()  # Rollback the failed transaction
                            continue
                    # Non-retryable error or max retries reached
                    noti.state = 'FAILED'
                    noti.processing_errors = last_error
                    _logger.error("meli_oerp_multiple >> _process_notification_order >> "+str(noti.processing_errors))
                    break

            noti.processing_ended = ml_datetime(str(datetime.now()))
            #MeliCommit( self )

    def _process_notification_question( self, meli=None):

        #_logger.info("meli_oerp_multiple >> _process_notification_question")

        account = self.connection_account
        if not account:
            _logger.error("meli_oerp_multiple >> _process_notification_question >> Account not defined")
            return {}

        company = account.company_id or self.env.user.company_id
        config = account.configuration

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )

        for noti in self:
            noti.state = 'PROCESSING'
            #noti.attempts+= 1
            noti.processing_started = ml_datetime(str(datetime.now()))

            try:
                res = meli.get(""+str(noti.resource), {'access_token':meli.access_token} )
                ojson =  res.json()
                #_logger.info("Notification fetched: ")
                #_logger.info(ojson)

                if ('error' in ojson):
                    noti.state = 'FAILED'
                    noti.processing_errors = "Notification error:"+str(ojson)

                if ("id" in ojson):

                    #morder = self.env["mercadolibre.orders"].search( [('order_id','=',ojson["id"])], limit=1 )

                    #_logger.info(str(morder))
                    #pdata = { "id": False, "order_json": ojson }

                    #if (morder and len(morder)):
                    #    pdata["id"] =  morder.id

                    rsjson = {}
                    #question_id =
                    rsjson = self.env["mercadolibre.questions"].process_question( Question=ojson, meli=meli, config=config )
                    #rsjson = morder.orders_update_order_json( data=pdata, meli=meli, config=config )
                    #_logger.info("meli_oerp_multiple >> _process_notification_question >> rsjson: "+str(rsjson))

                    if (rsjson and 'error' in rsjson):
                        noti.state = 'FAILED'
                        noti.processing_errors = str(('message' in rsjson and rsjson['message']) or rsjson['error'])
                        _logger.error("meli_oerp_multiple >> _process_notification_question >> rsjson error: "+noti.processing_errors)
                    else:
                        noti.state = 'SUCCESS'
                        noti.processing_errors = str(rsjson)

            except Exception as E:
                noti.state = 'FAILED'
                noti.processing_errors = str(E)
                _logger.error("meli_oerp_multiple >> _process_notification_question >> "+noti.processing_errors)
            finally:
                noti.processing_ended = ml_datetime(str(datetime.now()))

    def _process_notification_internal_job( self, meli=None):
        #_logger.info("meli_oerp_multiple >> _process_notification_internal_job")

        account = self.connection_account
        if not account:
            return {}

        company = account.company_id or self.env.user.company_id
        config = account.configuration

        if not meli:
            meli = self.env['meli.util'].get_new_instance( company, account )

        for noti in self:

            noti.state = 'PROCESSING'
            noti.processing_started = ml_datetime(str(datetime.now()))
            if (config.mercadolibre_cron_post_update_stock):
                #_logger.info("config.mercadolibre_cron_post_update_stock True "+str(config.name))
                account.meli_update_remote_stock_injobs( meli=meli, notification=noti )

            if (config.mercadolibre_cron_post_update_price):
                _logger.info("config.mercadolibre_cron_post_update_price True "+str(config.name))
                pass;
                #account.meli_update_remote_price_injobs( meli=meli, notification=noti )

        return {}

    def _process_notification_component_stock_update(self, meli=None):
        """
        Process component_stock_update notifications.

        These notifications contain component IDs that need to trigger
        stock updates for their parent BOMs.

        Flow:
        1. Read component IDs from model_ids (JSON list)
        2. For each component, find parent BOMs
        3. Get parent product bindings
        4. Update stock for those bindings
        """
        _logger.info("meli_oerp_multiple >> _process_notification_component_stock_update")

        account = self.connection_account
        if not account:
            return {}

        company = account.company_id or self.env.user.company_id
        config = account.configuration

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        if not config.mercadolibre_cron_post_update_stock:
            _logger.info("component_stock_update: mercadolibre_cron_post_update_stock is disabled")
            return {}

        for noti in self:
            noti.state = 'PROCESSING'
            noti.processing_started = ml_datetime(str(datetime.now()))

            try:
                # Read component IDs from notification
                component_ids = []
                if noti.model_ids:
                    component_ids = json.loads(noti.model_ids)

                if not component_ids:
                    noti.state = 'SUCCESS'
                    noti.processing_logs = 'No components to process'
                    noti.processing_ended = ml_datetime(str(datetime.now()))
                    continue

                _logger.info(f"component_stock_update: Processing {len(component_ids)} components")

                # Track processed components
                processed_ids = []
                if noti.model_ids_processed:
                    processed_ids = json.loads(noti.model_ids_processed)

                # Get pending components
                pending_components = [c for c in component_ids if c not in processed_ids]

                if not pending_components:
                    noti.state = 'SUCCESS'
                    noti.processing_logs = 'All components already processed'
                    noti.processing_ended = ml_datetime(str(datetime.now()))
                    continue

                # Find parent products through BOMs
                # SQL query to get parent product IDs from components
                parent_product_ids = set()
                bom_line_obj = self.env['mrp.bom.line']

                for comp_id in pending_components[:50]:  # Process in chunks of 50
                    # Find BOM lines where this component is used
                    bom_lines = bom_line_obj.search([('product_id', '=', comp_id)])
                    for line in bom_lines:
                        if line.bom_id and line.bom_id.product_tmpl_id:
                            # Get all variants of the BOM's template
                            for variant in line.bom_id.product_tmpl_id.product_variant_ids:
                                parent_product_ids.add(variant.id)

                    processed_ids.append(comp_id)

                _logger.info(f"component_stock_update: Found {len(parent_product_ids)} parent products from {len(pending_components[:50])} components")

                # Find bindings for parent products
                if parent_product_ids:
                    bindings = self.env['mercadolibre.product'].search([
                        ('product_id', 'in', list(parent_product_ids)),
                        ('connection_account', '=', account.id),
                        ('meli_id', '!=', False),
                    ])

                    if bindings:
                        _logger.info(f"component_stock_update: Updating stock for {len(bindings)} bindings")

                        # Mark bindings for stock update
                        bindings.sudo().write({
                            'meli_stock_moves_update': fields.Datetime.now()
                        })

                        # Trigger actual stock update (limited batch)
                        for bind in bindings[:20]:  # Process 20 at a time
                            try:
                                bind.product_post_stock(meli=meli)
                            except Exception as e:
                                _logger.warning(f"component_stock_update: Error updating {bind.meli_id}: {e}")

                # Update notification progress
                noti.model_ids_processed = json.dumps(processed_ids)

                # Check if all done
                remaining = len(component_ids) - len(processed_ids)
                if remaining == 0:
                    noti.state = 'SUCCESS'
                    noti.processing_logs = f'Processed {len(component_ids)} components, updated {len(parent_product_ids)} products'
                else:
                    noti.state = 'RECEIVED'  # Keep for next cron run
                    noti.processing_logs = f'Processed {len(processed_ids)}/{len(component_ids)} components, {remaining} remaining'

                noti.processing_ended = ml_datetime(str(datetime.now()))

            except Exception as e:
                _logger.error(f"component_stock_update error: {e}", exc_info=True)
                noti.state = 'FAILED'
                noti.processing_errors = str(e)
                noti.processing_ended = ml_datetime(str(datetime.now()))

        return {}

    def start_internal_notification(self, internals, account=None):

        noti = None
        date_time = ml_datetime( str( datetime.now() ) )
        base_str = str(internals["application_id"]) + str(internals["user_id"]) + str(date_time)

        hash = hashlib.md5()
        hash.update( base_str.encode() )
        hexhash = str("i-")+hash.hexdigest()+str("#")+str(int(random.random()*900000+100000))

        internals["processing_started"] = date_time
        internals["_id"] = hexhash
        internals["received"] = date_time
        internals["sent"] = date_time
        internals["attempts"] = 1
        internals["state"] = "RECEIVED"

        vals = self._prepare_values(values=internals, account=account)
        if vals:
            noti = self.sudo().create(vals)
            #MeliCommit( self )

        return  noti

    def _process_notification_item(self, meli=None):
        """
        REFATODO: Procesa webhooks de tipo 'items' de MercadoLibre.
        Cuando ML notifica que un item cambió, busca el binding correspondiente
        y actualiza meli_last_status en BD sin necesidad de polling.
        Requiere activar 'Process all notifications' en la configuración.
        Ver .roots/refatodo/debug/fixes-log.md
        """
        account = self.connection_account
        if not account:
            return {}

        company = account.company_id or self.env.user.company_id

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)

        for noti in self:
            try:
                resource = noti.resource or ""
                # Extraer meli_id del resource tipo "/items/MLM1234567890"
                meli_id = resource.replace("/items/", "").strip()
                if not meli_id:
                    noti.state = 'FAILED'
                    noti.processing_errors = 'No meli_id en resource: %s' % resource
                    continue

                # Fetch status actual del item en ML
                response = meli.get("/items/" + meli_id, {'access_token': meli.access_token})
                rjson = response.json()

                if not rjson or "error" in rjson:
                    status_code = rjson.get("status") if rjson else None
                    if status_code == 404:
                        # Item eliminado en ML - actualizar todos los bindings
                        bindings = self.env['mercadolibre.product'].sudo().search([
                            ('meli_id', '=', meli_id),
                            ('connection_account', '=', account.id),
                        ])
                        if bindings:
                            bindings.sudo().write({
                                'meli_last_status': 'not_found',
                                'stock_error': 'not_found:404 - El item no existe en ML',
                            })
                            _logger.debug("items webhook: %s marcado not_found (%d bindings)", meli_id, len(bindings))
                    else:
                        _logger.debug("items webhook: Error fetching %s: %s", meli_id, rjson)
                    noti.state = 'SUCCESS'
                    continue

                ml_status = rjson.get("status", "unknown")
                ml_sub_status = ""
                if "sub_status" in rjson and rjson["sub_status"]:
                    ml_sub_status = rjson["sub_status"][0] if len(rjson["sub_status"]) > 0 else ""

                # Actualizar bindings correspondientes
                bindings = self.env['mercadolibre.product'].sudo().search([
                    ('meli_id', '=', meli_id),
                    ('connection_account', '=', account.id),
                ])

                if bindings:
                    update_vals = {}
                    if ml_status in ('active', 'paused', 'closed', 'under_review', 'inactive'):
                        update_vals['meli_last_status'] = ml_status
                    if ml_sub_status == 'deleted':
                        update_vals['meli_last_status'] = 'deleted'
                    if update_vals:
                        bindings.sudo().write(update_vals)
                        _logger.debug("items webhook: %s → status=%s (%d bindings)", meli_id, ml_status, len(bindings))

                noti.state = 'SUCCESS'

            except Exception as e:
                _logger.error("items webhook error para %s: %s", noti.resource, str(e))
                noti.state = 'FAILED'
                noti.processing_errors = str(e)[:500]

        return {}

