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

class ResCompany(models.Model):
    _name = "res.company"
    _inherit = ["res.company", "mercadolibre.seller.perms.mixin"]

    @api.onchange('mercadolibre_seller_user', 'mercadolibre_seller_team')
    def _onchange_meli_seller_perms(self):
        return self._meli_seller_perms_warning()

    mercadolibre_connections = fields.One2many( "mercadolibre.account", "company_id", string="MercadoLibre Connection Accounts", help="MercadoLibre Connection Accounts" )

    def action_create_mercadolibre_account(self):
        """Open form view to create a new MercadoLibre account for this company."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nueva Cuenta MercadoLibre',
            'res_model': 'mercadolibre.account',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_company_id': self.id,
            },
        }

    def get_meli_state( self ):
        #_logger.info('meli_oerp_multiple company get_meli_state() ')
        company = self or self.env.user.company_id
        for comp in company:
            #company = self or self.env.user.company_id
            #_logger.info( 'meli_oerp_multiple company get_meli_state() ' + comp.name )
            #meli = self.env['meli.util'].get_new_instance(company)
            #if meli:
            comp.mercadolibre_state = True

            for account in comp.mercadolibre_connections:
                #_logger.info('get_connector_state for: ' +str(comp.name) + str(" >> ") + str(account.name))
                account.get_connector_state()

    def cron_meli_orders( self, account_id=None ):
        # Buscar TODAS las cuentas ML con sudo, SIN depender de las compañías del
        # usuario del cron (OdooBot). Antes se recorría self.env.user.company_ids, por
        # lo que si OdooBot no tenía la compañía de la cuenta en sus Compañías
        # permitidas, el dispatcher no la veía y el cron "no hacía nada".
        Account = self.env['mercadolibre.account'].sudo()
        accounts = Account.browse(account_id).exists() if account_id else Account.search([])
        _logger.info("cron_meli_orders: DISPATCHER — %d cuenta(s) ML encontradas (account_id=%s, usuario_cron=%s).",
                     len(accounts), account_id, self.env.user.name)

        for account in accounts:
            # Gate del estado de crons
            cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'orders')
            if cron_status and not cron_status[0].is_enabled:
                _logger.info("cron_meli_orders: cuenta [%s] DESHABILITADA en estado de crons — se omite.", account.name)
                continue

            # Operar en la COMPAÑÍA de la cuenta y, si está configurado, COMO el
            # Vendedor ML de la cuenta (así las ventas quedan a su nombre y el scope
            # de compañía es el correcto, en vez de depender del usuario del cron).
            #
            # IMPORTANTE — el import de órdenes corre con PRIVILEGIOS (su=True / sudo):
            # es una INTEGRACIÓN DE SISTEMA, no una acción interactiva de usuario. El
            # Vendedor ML tiene los grupos *MercadoLibre* (Manager/Reader) pero NO los
            # grupos estándar de Odoo (Sales/Stock/Invoicing), por lo que correr la
            # transacción con su=False disparaba AccessError en cascada por CADA modelo
            # de la cadena de creación de una orden (sale.order, stock.picking,
            # account.move, res.partner, ...). En Odoo moderno `.sudo()` NO cambia el
            # uid: sólo activa el flag superusuario → con `with_user(vendedor).sudo()`
            # el uid (create_uid/atribución) sigue siendo el Vendedor ML, pero se saltan
            # los ACL/record-rules. La atribución de negocio (salesperson user_id +
            # team_id) la fija además explícitamente meli_fix_team() vía sudo desde la
            # config. Las constraints Python/SQL y los computes NO se saltan (su sólo
            # afecta ACL/reglas), así que la integridad de datos se preserva.
            config = account.configuration or account.company_id
            seller_user = config.mercadolibre_seller_user if (config and 'mercadolibre_seller_user' in config._fields) else False
            target = account.sudo()
            run_user_name = self.env.user.name
            if seller_user and seller_user.active:
                target = account.with_user(seller_user.id).sudo()
                run_user_name = seller_user.name
            if account.company_id:
                target = target.with_company(account.company_id)

            _logger.info("cron_meli_orders: despachando cuenta [%s] (id=%s) — usuario=[%s], compañía=[%s].",
                         account.name, account.id, run_user_name, account.company_id.name if account.company_id else "-")
            try:
                # Execution tracking (start/commit/end + stats) se maneja dentro de
                # account.cron_meli_orders() en connection_account.py
                target.cron_meli_orders()
            except Exception as e:
                # Una cuenta que falla (p.ej. el Vendedor ML sin permisos/compañía) no
                # debe cortar el procesamiento de las demás.
                _logger.error("cron_meli_orders: cuenta [%s] FALLÓ en el dispatcher: %s", account.name, e, exc_info=True)

    def cron_process_order_notifications( self, account_id=None ):
        # Dispatcher DEDICADO al DRENADO de notificaciones de órdenes (orders_v2)
        # que quedan en estado RECEIVED/FAILED (buffer de webhooks /meli_notify).
        #
        # Existe porque el drenado de notificaciones sólo estaba cableado como el
        # paso 1 de account.cron_meli_orders(), acoplado al cron de órdenes por
        # CONSULTA (60 min, limit 10). En cuentas con volumen alto ese ritmo no
        # alcanza a vaciar el buffer y las notificaciones se acumulan sin drenarse
        # nunca (caso Shoppy: 7.697 RECEIVED). Este dispatcher corre con alta
        # frecuencia (cron cada 5 min) y ejecuta SÓLO el drenado — NO hace consultas
        # a la API de órdenes (eso lo sigue haciendo cron_meli_orders).
        #
        # Mismo scoping que cron_meli_orders: sudo, compañía de la cuenta y, si está
        # configurado, el Vendedor ML; respeta el gate de cron_status ('orders') y el
        # toggle mercadolibre_cron_get_orders. Un fallo por cuenta no corta el resto.
        Account = self.env['mercadolibre.account'].sudo()
        accounts = Account.browse(account_id).exists() if account_id else Account.search([])
        _logger.info("cron_process_order_notifications: DISPATCHER — %d cuenta(s) ML (account_id=%s).",
                     len(accounts), account_id)

        for account in accounts:
            cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'orders')
            if cron_status and not cron_status[0].is_enabled:
                continue

            config = account.configuration or account.company_id
            if config and not config.mercadolibre_cron_get_orders:
                continue

            seller_user = config.mercadolibre_seller_user if (config and 'mercadolibre_seller_user' in config._fields) else False
            target = account.sudo()
            if seller_user and seller_user.active:
                target = account.with_user(seller_user.id).sudo()
            if account.company_id:
                target = target.with_company(account.company_id)

            orders_limit = (config.mercadolibre_cron_orders_limit or 10) if config else 10
            try:
                target.cron_process_order_notifications(limit=orders_limit)
            except Exception as e:
                _logger.error("cron_process_order_notifications: cuenta [%s] FALLÓ en el dispatcher: %s", account.name, e, exc_info=True)

    def cron_meli_orders_status( self, account_id=None ):
        # #475 - Dispatcher DEDICADO al RE-SYNC de ESTADO de pedidos (detectar
        # cancelaciones ML fuera de la ventana date_desc del cron de importación).
        #
        # El método base (meli_oerp/res.company.cron_meli_orders_status →
        # mercadolibre.orders.orders_resync_status) es MONO-cuenta: usa
        # self.env.user.company_id + un ÚNICO token get_new_instance(company). En
        # instancias MULTI-CUENTA sólo cubre la compañía default del usuario del cron
        # (OdooBot) y con SU token, dejando las demás cuentas/compañías sin barrer
        # (p.ej. Score co1 vs WODPRO co3 comparten Odoo → una quedaba sin re-sync).
        #
        # Este override itera TODAS las mercadolibre.account (sudo, sin depender de las
        # compañías del usuario del cron) y por cada una corre orders_resync_status con
        # SU token, SU compañía y scope por cuenta (connection_account). Mismo
        # scoping/guarding que cron_meli_orders / cron_process_order_notifications:
        # sudo + with_company + with_user(Vendedor ML); respeta el gate cron_status
        # ('orders') y el toggle mercadolibre_cron_get_orders_status; un fallo por cuenta
        # NO corta el procesamiento de las demás. No requiere ir.cron nuevo: reutiliza el
        # registro base ir_cron_module_cron_meli_orders_status (llama al mismo método).
        Account = self.env['mercadolibre.account'].sudo()
        accounts = Account.browse(account_id).exists() if account_id else Account.search([])
        _logger.info("cron_meli_orders_status: DISPATCHER — %d cuenta(s) ML (account_id=%s).",
                     len(accounts), account_id)

        for account in accounts:
            cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'orders')
            if cron_status and not cron_status[0].is_enabled:
                continue

            config = account.configuration or account.company_id
            if config and "mercadolibre_cron_get_orders_status" in config._fields and not config.mercadolibre_cron_get_orders_status:
                continue

            # Operar en la COMPAÑÍA de la cuenta y, si está configurado, COMO el Vendedor
            # ML de la cuenta (mismo racional que cron_meli_orders: integración de sistema
            # con privilegios; el Vendedor ML no tiene los grupos estándar de Odoo).
            seller_user = config.mercadolibre_seller_user if (config and 'mercadolibre_seller_user' in config._fields) else False
            target = account.sudo()
            if seller_user and seller_user.active:
                target = account.with_user(seller_user.id).sudo()
            if account.company_id:
                target = target.with_company(account.company_id)

            try:
                # meli con el token de ESTA cuenta (firma 2-arg de meli.util en multiple).
                meli = target.env['meli.util'].get_new_instance(account.company_id or target.env.user.company_id, account)
                # orders_resync_status guardea internamente needlogin_state y el scope por
                # cuenta/compañía vía account + config.
                target.env['mercadolibre.orders'].orders_resync_status(meli=meli, config=config, account=account)
            except Exception as e:
                _logger.error("cron_meli_orders_status: cuenta [%s] FALLÓ en el dispatcher: %s", account.name, e, exc_info=True)

    def meli_query_orders(self):
        #_logger.info("meli_oerp_multiple >> meli_query_orders")
        company = self or self.env.user.company_ids or self.env.user.company_id
        result = []
        for comp in company:
            res = {}
            for account in comp.mercadolibre_connections:

                #_logger.info('meli_query_orders for: ' +str(comp.name) + str(" >> ") + str(account.name))
                res = account.meli_query_orders()
                if (res):
                    result.append(res)

        return result

    def cron_meli_questions( self ):
        company = self or self.env.user.company_ids or self.env.user.company_id
        result = []
        for comp in company:
            res = {}
            for account in comp.mercadolibre_connections:

                config = account and account.configuration

                if config and config.mercadolibre_cron_get_questions:
                    # Check is_enabled on cron status
                    cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'questions')
                    if cron_status and not cron_status[0].is_enabled:
                        continue

                    execution = account._start_cron_execution('questions')
                    self.env.cr.commit()
                    try:
                        res = account.meli_query_get_questions()
                        if (res):
                            result.append(res)
                        account._end_cron_execution(execution, state='success')
                    except Exception as e:
                        account._end_cron_execution(execution, state='error', error_message=str(e))
                        raise

        return result

    def cron_meli_process( self ):
        company = self or self.env.user.company_ids or self.env.user.company_id
        for comp in company:

            for account in comp.mercadolibre_connections:

                # Check is_enabled on cron status
                cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'process')
                if cron_status and not cron_status[0].is_enabled:
                    continue

                # Execution tracking handled inside account.cron_meli_process()
                account.cron_meli_process()

    def meli_query_products(self):
        company = self or self.env.user.company_ids or self.env.user.company_id
        result = []
        for comp in company:

            for account in comp.mercadolibre_connections:
                account.meli_query_products()

        return result

    def cron_meli_process_internal_jobs(self):
        company = self or self.env.user.company_ids or self.env.user.company_id
        for comp in company:

            for account in comp.mercadolibre_connections:

                # Check is_enabled on cron status
                cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'internal_jobs')
                if cron_status and not cron_status[0].is_enabled:
                    continue

                # Execution tracking handled inside account.cron_meli_process_internal_jobs()
                account.cron_meli_process_internal_jobs()


    def cron_meli_process_post_stock( self, meli=None, account_id=None ):

        company_ids = self.env.user.company_ids
        for comp in company_ids:
            #_logger.info("cron_meli_process_post_stock > company "+str(comp))
            for account in comp.mercadolibre_connections:

                if account_id and account_id!=account.id:
                    continue;

                #_logger.info("cron_meli_process_post_stock > account "+str(account and account.name))
                config = account.configuration
                if (config.mercadolibre_cron_post_update_stock):
                    # Check is_enabled on cron status
                    cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'stock')
                    if cron_status and not cron_status[0].is_enabled:
                        continue

                    execution = account._start_cron_execution('stock')
                    self.env.cr.commit()
                    try:
                        account.meli_update_remote_stock(meli=meli)
                        account._end_cron_execution(execution, state='success')
                    except Exception as e:
                        account._end_cron_execution(execution, state='error', error_message=str(e))
                        raise

    def cron_meli_process_post_stock_rt( self, meli=None, account_id=None ):

        company_ids = self.env.user.company_ids
        for comp in company_ids:
            #_logger.info("cron_meli_process_post_stock_rt > company "+str(comp))
            for account in comp.mercadolibre_connections:

                if account_id and account_id!=account.id:
                    continue;

                #_logger.info("cron_meli_process_post_stock_rt > account "+str(account and account.name))
                config = account.configuration
                if (config.mercadolibre_cron_post_update_stock):
                    # Check is_enabled on cron status
                    cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'stock_rt')
                    if cron_status and not cron_status[0].is_enabled:
                        continue

                    execution = account._start_cron_execution('stock_rt')
                    self.env.cr.commit()
                    try:
                        account.meli_update_remote_stock_rt(meli=meli)
                        account._end_cron_execution(execution, state='success')
                    except Exception as e:
                        account._end_cron_execution(execution, state='error', error_message=str(e))
                        raise



    def cron_meli_process_post_price( self, meli=None, account_id=None ):

        company_ids = self.env.user.company_ids
        for comp in company_ids:

            for account in comp.mercadolibre_connections:

                if account_id and account_id!=account.id:
                    continue;

                config = account.configuration
                if (config.mercadolibre_cron_post_update_price):
                    # Skip if batch mode is active — Internal Jobs handles it
                    if account.meli_cron_price_batch_hour and account.meli_cron_price_batch_hour != '-1':
                        _logger.info('cron_meli_process_post_price SKIPPED for %s - batch mode active (hour=%s)', account.name, account.meli_cron_price_batch_hour)
                        continue

                    # Check is_enabled on cron status
                    cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'price')
                    if cron_status and not cron_status[0].is_enabled:
                        continue

                    execution = account._start_cron_execution('price')
                    self.env.cr.commit()
                    try:
                        account.meli_update_remote_price(meli=meli)
                        account._end_cron_execution(execution, state='success')
                    except Exception as e:
                        account._end_cron_execution(execution, state='error', error_message=str(e))
                        raise



    def cron_meli_process_post_products( self, meli=None, account_id=None ):

        company = self or self.env.user.company_ids or self.env.user.company_id

        for comp in company:

            for account in comp.mercadolibre_connections:

                if account_id and account_id!=account.id:
                    continue;

                config = account.configuration
                if (config.mercadolibre_cron_post_update_products or config.mercadolibre_cron_post_new_products):
                    # Check is_enabled on cron status
                    cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'products_post')
                    if cron_status and not cron_status[0].is_enabled:
                        continue

                    execution = account._start_cron_execution('products_post')
                    self.env.cr.commit()
                    try:
                        account.meli_update_remote_products(post_new=config.mercadolibre_cron_post_new_products)
                        account._end_cron_execution(execution, state='success')
                    except Exception as e:
                        account._end_cron_execution(execution, state='error', error_message=str(e))
                        raise

    def cron_meli_process_get_products( self, meli=None, account_id=None ):

        company = self or self.env.user.company_ids or self.env.user.company_id

        for comp in company:

            for account in comp.mercadolibre_connections:
                if account_id and account_id!=account.id:
                    continue;                
                config = account.configuration
                if (config.mercadolibre_cron_get_update_products):
                    # Check is_enabled on cron status
                    cron_status = account.cron_status_ids.filtered(lambda c: c.cron_type == 'products_get')
                    if cron_status and not cron_status[0].is_enabled:
                        continue

                    execution = account._start_cron_execution('products_get')
                    self.env.cr.commit()
                    try:
                        account.meli_update_local_products()
                        account._end_cron_execution(execution, state='success')
                    except Exception as e:
                        account._end_cron_execution(execution, state='error', error_message=str(e))
                        raise

                if (config.mercadolibre_cron_get_new_products):
                    #_logger.info("config.mercadolibre_cron_get_new_products")
                    account.cron_batch_import_products()
