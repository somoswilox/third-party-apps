# -*- coding: utf-8 -*-

import base64
from odoo import http, api
from odoo import fields
from odoo.http import Controller, Response, request, route
import pdb
import logging
_logger = logging.getLogger(__name__)

from odoo.addons.odoo_connector_api.controllers.main import OcapiAuthorize
from odoo.addons.odoo_connector_api.controllers.main import OcapiCatalog
from ..models.versions import route_typejson

from odoo.addons.meli_oerp.controllers.main import MercadoLibreLogin
from odoo.addons.meli_oerp.controllers.main import MercadoLibre
import json

class MercadoLibreAuthorize(OcapiAuthorize):
    #@http.route()
    #def authorize(self, connector, **post):
    #    _logger.info("connector:"+str(connector))
    #    if connector and connector=="mercadolibre":
    #        return self.mercadolibre_authorize(**post)
    #    else:
    #        return super(OcapiAuthorize, self).authorize( connector, **post )

    @http.route()
    def status(self, connector, **post):
        #POST api user id and token, create id based on URL if need to create one
        #check all connectors
        client_id = post.get("client_id") or post.get("app_id")
        secret_key = post.get("secret_key") or post.get("app_key")

        connection_account = []
        access_status = []

        if not (connector=="mercadolibre"):
            _logger.info("Redirect status request for connector: "+str(connector))
            access_status = super(MercadoLibreAuthorize, self).status(connector, **post )
            return access_status

        if client_id and secret_key:
            _logger.info("Status request for connector: "+str(connector))
            connection_account = request.env['mercadolibre.account'].sudo().search([('client_id','=',client_id),('secret_key','=',secret_key)], limit=1)
            #_logger.info("Status request for connector: connection_account: "+str(connection_account))
        access_status = []
        for acc in connection_account:
            access_status+= acc.fetch_status()
        return access_status


    def mercadolibre_authorize(self, **post):
        #POST api user id and token, create id based on URL if need to create one
        #check all connectors
        #_logger.info("post:"+str(post))
        client_id = post.get("client_id") or post.get("app_id")
        secret_key = post.get("secret_key") or post.get("app_key")
        connection_account = []
        if client_id and secret_key:
            _logger.info("Authentication request for mercadolibre")
            connection_account = request.env['mercadolibre.account'].sudo().search([('client_id','=',client_id),('secret_key','=',secret_key)])
        access_tokens = []
        if not connection_account:
            _logger.error("No response for: client_id:"+str(client_id)+" secret_key:" + str(secret_key) )
        for a in connection_account:
            _logger.info("Trying")
            access_token = a.authorize_token( client_id, secret_key )
            access_tokens.append({ 'client_id': client_id, 'access_token': access_token  })
        _logger.info(access_tokens)
        return access_tokens

class MercadoLibrePremium(MercadoLibre):
    @http.route('/meli/', auth='public')
    def index(self):
        company = request.env.user.company_id
        meli_util_model = request.env['meli.util']
        meli = meli_util_model.get_new_instance(company)
        if meli.need_login():
            return "<a href='"+meli.auth_url()+"'>Login Please</a>"

        return "MercadoLibre Publisher for Odoo - Copyright Moldeo Interactive 2021"

    # csrf=False is required because this endpoint is a webhook called
    # from MercadoLibre servers — they cannot provide an Odoo CSRF token.
    # Authentication is done inside the handler by looking up the account
    # from the URL path (meli_login_id) and validating the payload's
    # application_id / user_id against the stored client_id and seller list.
    #
    # The /odoo/meli_notify aliases exist so the webhook works no matter
    # whether the ML app was configured with https://<host>/meli_notify/<id>
    # or https://<host>/odoo/meli_notify/<id> (Odoo 17+ backend prefix).
    # In production at kelebcenter ML posts to /odoo/meli_notify/keleb.
    @http.route(
        [
            '/meli_notify',
            '/meli_notify/<string:meli_login_id>',
            '/odoo/meli_notify',
            '/odoo/meli_notify/<string:meli_login_id>',
        ],
        type=route_typejson, auth='public', methods=['POST'], csrf=False,
    )
    def meli_notify(self, meli_login_id=None, **kw):
        """
        Handle MercadoLibre notifications.

        Routes:
        - /meli_notify - Uses application_id from notification data
        - /meli_notify/<meli_login_id> - Uses meli_login_id from URL (e.g., /meli_notify/scoremx)

        Account resolution priority:
        1. Find by meli_login_id from URL (PRIMARY - must match)
        2. Validate that notification's app_id matches account's client_id (REQUIRED)
        3. Check if user_id is in allowed sellers (log warning if not, but continue)

        NEVER: Find account only by user_id if app_id doesn't match
        """
        meli_account = None

        try:
            data = json.loads(request.httprequest.data)
        except json.JSONDecodeError as e:
            _logger.error("meli_notify: Invalid JSON data: %s", str(e))
            return ""

        # Extract notification identifiers
        user_id = data.get("user_id")
        app_id = data.get("application_id")
        topic = data.get("topic", "unknown")
        resource = data.get("resource", "unknown")

        _logger.debug(
            "meli_notify: Received - URL: /meli_notify/%s | topic: %s | resource: %s | user_id: %s | app_id: %s",
            meli_login_id or "(none)", topic, resource, user_id, app_id
        )

        # Strategy 1: Find by meli_login_id from URL (PRIMARY)
        if meli_login_id:
            meli_account = request.env['mercadolibre.account'].sudo().search([
                ('meli_login_id', '=', meli_login_id)
            ], limit=1)

            if meli_account:
                # REQUIRED: Validate app_id matches account's client_id
                if app_id and str(meli_account.client_id) != str(app_id):
                    _logger.warning(
                        "meli_notify: app_id mismatch for account '%s'. "
                        "Account client_id: %s | Notification app_id: %s. Rejecting.",
                        meli_account.name, meli_account.client_id, app_id
                    )
                    return "App ID mismatch"

                # Check if user_id is in allowed sellers (log if not, but continue)
                if user_id and not meli_account.is_seller_allowed(user_id):
                    _logger.info(
                        "meli_notify: user_id %s not in allowed sellers for account '%s' (seller_id=%s). "
                        "Continuing anyway since app_id matches.",
                        user_id, meli_account.name, meli_account.seller_id
                    )
                # Happy path - no log needed
            else:
                _logger.warning(
                    "meli_notify: No account found for meli_login_id '%s'",
                    meli_login_id
                )
                return "Account not found"

        # Strategy 2: No meli_login_id in URL - find by app_id (REQUIRED)
        if not meli_account and app_id:
            accounts_with_app = request.env['mercadolibre.account'].sudo().search([
                ('client_id', '=', str(app_id))
            ])

            if accounts_with_app:
                # First try to find account where user_id is allowed
                for acc in accounts_with_app:
                    if user_id and acc.is_seller_allowed(user_id):
                        meli_account = acc
                        break

                # If no exact match but only one account with this app_id, use it
                if not meli_account and len(accounts_with_app) == 1:
                    meli_account = accounts_with_app[0]
                    if user_id:
                        _logger.info(
                            "meli_notify: Using account %s for app_id %s. "
                            "Note: user_id %s not in allowed sellers.",
                            meli_account.name, app_id, user_id
                        )

                # Multiple accounts with same app_id and no user_id match
                if not meli_account and len(accounts_with_app) > 1:
                    _logger.warning(
                        "meli_notify: Multiple accounts (%d) share app_id %s and user_id %s is not allowed in any. "
                        "Cannot determine which account. Accounts: %s",
                        len(accounts_with_app), app_id, user_id,
                        ', '.join([f"{a.name}(seller={a.seller_id})" for a in accounts_with_app])
                    )
                    return "Cannot determine account"
            else:
                _logger.warning(
                    "meli_notify: No account found with app_id %s",
                    app_id
                )

        # NO Strategy 3 (user_id only) - that's explicitly not allowed

        if not meli_account:
            _logger.warning(
                "meli_notify: No valid account found for notification. "
                "user_id: %s, app_id: %s, meli_login_id: %s",
                user_id, app_id, meli_login_id
            )
            return "Account not found"

        company = meli_account.company_id or request.env.user.company_id

        meli_util_model = request.env['meli.util']
        meli = meli_util_model.sudo().get_new_instance(company, meli_account)

        # Process notification (no log for happy path)
        result = meli_account.sudo().meli_notifications(data=data, meli=meli)
        if result and "error" in result:
            _logger.error(
                "meli_notify: Error processing notification - %s (status: %s)",
                result.get("error"), result.get("status")
            )
            return Response(result["error"], content_type='text/html;charset=utf-8', status=result["status"])
        else:
            return ""

#class MercadoLibreAuthorize(OcapiAuthorize):

    #@http.route()
    #def authorize(self, connector, **post):
    #    if connector and connector=="mercadolibre":
    #        return self.mercadolibre_authorize(**post)
    #    else:
    #        return super(OcapiAuthorize, self).authorize( connector, **post )

    #def mercadolibre_authorize(self, **post):
        #POST api user id and token, create id based on URL if need to create one
        #check all connectors
    #    client_id = post.get("client_id") or post.get("app_id")
    #    secret_key = post.get("secret_key") or post.get("app_key")
    #    connection_account = []
    #    if client_id and secret_key:
    #        #_logger.info("Authentication request for mercadolibre")
    #        connection_account = request.env['mercadolibre.account'].sudo().search([('client_id','=',client_id),('secret_key','=',secret_key)])
    #    access_tokens = []
    #    for a in connection_account:
    #        #_logger.info("Trying")
    #        access_token = a.authorize_token( client_id, secret_key )
    #        access_tokens.append({ 'client_id': client_id, 'access_token': access_token  })
    #    #_logger.info(access_tokens)
    #    return access_tokens


#class MercadoLibreCatalog(OcapiCatalog):

#    def __get_mercadolibre_connection(self, **post):

#        connector = "mercadolibre"

#        access_token = post.get("access_token")

#        if not access_token:
#            return False

#        connection_account = request.env['mercadolibre.account'].sudo().search([('access_token','=',access_token)])

#        #_logger.info(connection_account)

#        if not connection_account or not len(connection_account)==1:
#            return False
#
#        if not (connector == connection_account.type):
#            return False
#
#        return connection_account

#    def __get_connection_account(self, connector,**post):
#        if connector and connector=="mercadolibre":
#            return self.get_mercadolibre_connection(**post)
#        else:
#            return super(OcapiCatalog, self).get_connection(connector,**post)

#        return connection_account

    def get_mercadolibre_connection(self, **post):
        connector = "mercadolibre"
        access_token = post.get("access_token")
        if not access_token:
            return False
        connection_account = request.env['mercadolibre.account'].sudo().search([('access_token','=',access_token)])
        #_logger.info(connection_account)
        if not connection_account or not len(connection_account)==1:
            return False
        if not (connector == connection_account.type):
            return False
        return connection_account

    def get_mercadolibre_connection_by_credentials(self, **post):
        """Obtiene conexión de MercadoLibre usando client_id y secret_key."""
        connector = "mercadolibre"
        client_id = post.get("client_id") or post.get("app_id")
        secret_key = post.get("secret_key") or post.get("app_key")
        if not client_id or not secret_key:
            _logger.warning("get_mercadolibre_connection_by_credentials: Missing client_id or secret_key")
            return False
        connection_account = request.env['mercadolibre.account'].sudo().search([
            ('client_id', '=', client_id),
            ('secret_key', '=', secret_key)
        ], limit=1)
        if not connection_account:
            _logger.warning("get_mercadolibre_connection_by_credentials: No account found for client_id=%s", client_id)
            return False
        if not (connector == connection_account.type):
            _logger.warning("get_mercadolibre_connection_by_credentials: Account type mismatch")
            return False
        return connection_account

    def get_connection_account(self, connector,**post):
        if connector and connector=="mercadolibre":
            return self.get_mercadolibre_connection(**post)
        else:
            return super(MercadoLibrePremium, self).get_connection_account(connector,**post)

    @http.route('/ocapi/<string:connector>/<string:meli_id>/rebind', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def rebind(self, connector, meli_id, **post):
        #_logger.info("rebind: "+str(connector)+" meli_id:"+str(meli_id))
        #_logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}
        return connection.rebind(meli_id=meli_id, **post)

    @http.route('/ocapi/<string:connector>/<string:meli_id>/post_stock', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def post_stock(self, connector, meli_id, **post):
        #_logger.info("post_stock: "+str(connector)+" meli_id:"+str(meli_id))
        #_logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}
        return connection.post_stock(meli_id=meli_id, **post)

    @http.route('/ocapi/<string:connector>/<string:meli_id>/<string:meli_id_variation>/post_stock', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def post_stock(self, connector, meli_id, meli_id_variation, **post):
        #_logger.info("post_stock: "+str(connector)+" meli_id:"+str(meli_id)+" meli_id_variation:"+str(meli_id_variation))
        #_logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}
        return connection.post_stock_variant(meli_id=meli_id, meli_id_variation=meli_id_variation, **post)

    @http.route('/ocapi/<string:connector>/<string:meli_id>/post_price', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def post_price(self, connector, meli_id, **post):
        #_logger.info("post_price: "+str(connector)+" meli_id:"+str(meli_id))
        #_logger.info(post)
        connection = self.get_connection_account(connector,**post)
        if not connection:
            return {}
        return connection.post_price(meli_id=meli_id, **post)

    @http.route('/ocapi/<string:connector>/<string:channel>/status', auth='public', type=route_typejson, methods=['POST','GET'], csrf=False, cors='*')
    def status_channel(self, connector, channel, **post):
        _logger.info("MELI status: connector:"+str(connector)+" channel:"+str(channel))
        _logger.info(post)
        connection = self.get_connection_account(connector,**post)

        if not connection:
            return {}

        #filter products using connection account and configuration bindings
        return connection.fetch_status(**post)

    # ===================== KPI ENDPOINTS =====================

    @http.route('/ocapi/<string:connector>/kpis', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def kpis(self, connector, **post):
        """Get full KPI data for the account."""
        connection = self.get_mercadolibre_connection_by_credentials(**post)
        if not connection:
            return {'success': False, 'error': 'Invalid credentials or account not found'}

        date_from = post.get('date_from')
        date_to = post.get('date_to')
        filters = post.get('filters')

        return connection.get_orders_kpi_data(
            date_from=date_from,
            date_to=date_to,
            filters=filters
        )

    @http.route('/ocapi/<string:connector>/kpis/summary', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def kpis_summary(self, connector, **post):
        """Get grouped summary of orders."""
        connection = self.get_mercadolibre_connection_by_credentials(**post)
        if not connection:
            return {'success': False, 'error': 'Invalid credentials or account not found'}

        date_from = post.get('date_from')
        date_to = post.get('date_to')
        group_by = post.get('group_by', 'status')

        return connection.get_orders_summary(
            date_from=date_from,
            date_to=date_to,
            group_by=group_by
        )

    @http.route('/ocapi/<string:connector>/kpis/timeline', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def kpis_timeline(self, connector, **post):
        """Get orders timeline for charts."""
        connection = self.get_mercadolibre_connection_by_credentials(**post)
        if not connection:
            return {'success': False, 'error': 'Invalid credentials or account not found'}

        date_from = post.get('date_from')
        date_to = post.get('date_to')
        interval = post.get('interval', 'day')

        return connection.get_orders_timeline(
            date_from=date_from,
            date_to=date_to,
            interval=interval
        )

    @http.route('/ocapi/<string:connector>/kpis/donut', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def kpis_donut(self, connector, **post):
        """
        Get KPI data formatted for donut/pie charts with team breakdown.
        Returns data for Sales, Invoices, and Publications charts.
        """
        connection = self.get_mercadolibre_connection_by_credentials(**post)
        if not connection:
            return {'success': False, 'error': 'Invalid credentials or account not found'}

        date_from = post.get('date_from')
        date_to = post.get('date_to')

        period_domain = connection._build_period_domain(date_from, date_to)

        # Get sales data with team breakdown
        sales_counts, sales_by_team = connection._kpi_get_sales_counts(period_domain)

        # Get invoice data with team breakdown
        invoice_counts, invoices_by_team = connection._kpi_get_invoice_counts(period_domain)

        # Get publication/stock sync data
        pub_counts, pub_by_team = connection._kpi_get_publication_counts(period_domain)

        return {
            'success': True,
            'period': {
                'from': str(date_from) if date_from else None,
                'to': str(date_to) if date_to else None,
            },
            'sales': {
                'counts': sales_counts,
                'by_team': sales_by_team,
            },
            'invoices': {
                'counts': invoice_counts,
                'by_team': invoices_by_team,
            },
            'publications': {
                'counts': pub_counts,
                'by_team': pub_by_team,
            },
            'timestamp': str(fields.Datetime.now()),
        }

    @http.route('/ocapi/<string:connector>/kpis/config', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def kpis_config(self, connector, **post):
        """
        Get account configuration data for KPI reports.
        Returns import/export settings, order processing config, etc.
        """
        connection = self.get_mercadolibre_connection_by_credentials(**post)
        if not connection:
            return {'success': False, 'error': 'Invalid credentials or account not found'}

        return connection.get_kpi_config()

    @http.route('/ocapi/<string:connector>/kpis/orders/query', auth='public', type=route_typejson, methods=['POST'], csrf=False, cors='*')
    def kpis_orders_query(self, connector, **post):
        """
        Extended orders query with full details including:
        - Order info
        - Product/item info
        - Category (id + full path)
        - Shipment address with geolocation
        - Buyer billing info (CUIT)
        """
        connection = self.get_mercadolibre_connection_by_credentials(**post)
        if not connection:
            return {'success': False, 'error': 'Invalid credentials or account not found'}

        date_from = post.get('date_from')
        date_to = post.get('date_to')
        limit = post.get('limit', 100)
        offset = post.get('offset', 0)
        order_by = post.get('order_by', 'date_created')
        order_dir = post.get('order_dir', 'desc')

        if 'mercadolibre.orders' not in request.env:
            return {'success': False, 'error': 'mercadolibre.orders model not found'}

        # Build domain
        domain = []
        if date_from:
            domain.append(('date_created', '>=', date_from))
        if date_to:
            domain.append(('date_created', '<=', date_to))

        # Get orders
        ml_orders = request.env['mercadolibre.orders'].sudo()
        orders = ml_orders.search(
            domain,
            limit=limit,
            offset=offset,
            order=f'{order_by} {order_dir}'
        )

        # Cache for categories
        category_cache = {}

        def get_category_full_path(category):
            """Get the full category path traversing parents."""
            if not category:
                return None
            if category.id in category_cache:
                return category_cache[category.id]

            path_parts = []
            current = category
            seen = set()
            while current and current.id not in seen:
                seen.add(current.id)
                path_parts.insert(0, current.name or '')
                current = getattr(current, 'meli_father_category', None)

            full_path = ' > '.join(path_parts)
            category_cache[category.id] = {
                'id': category.meli_category_id if hasattr(category, 'meli_category_id') else str(category.id),
                'name': category.name,
                'full_path': full_path,
            }
            return category_cache[category.id]

        results = []
        for order in orders:
            order_data = {
                'id': order.id,
                'order_id': order.order_id,
                'status': order.status,
                'status_detail': getattr(order, 'status_detail', None),
                'date_created': str(order.date_created) if order.date_created else None,
                'date_closed': str(order.date_closed) if getattr(order, 'date_closed', None) else None,
                'total_amount': order.total_amount,
                'paid_amount': order.paid_amount,
                'currency_id': order.currency_id,
                'pack_id': getattr(order, 'pack_id', None),
            }

            # Items/Products
            items = []
            if hasattr(order, 'order_items') and order.order_items:
                for item in order.order_items:
                    item_data = {
                        'id': item.id,
                        'meli_id': getattr(item, 'meli_id', None),
                        'title': getattr(item, 'title', getattr(item, 'name', None)),
                        'quantity': getattr(item, 'quantity', 1),
                        'unit_price': getattr(item, 'unit_price', 0),
                        'sku': getattr(item, 'seller_custom_field', getattr(item, 'seller_sku', None)),
                        'variation_id': getattr(item, 'variation_id', None),
                    }

                    # Category info
                    category = getattr(item, 'category_id', None) or getattr(item, 'meli_category', None)
                    if category:
                        item_data['category'] = get_category_full_path(category)
                    else:
                        # Try to get from product
                        product = getattr(item, 'product_id', None) or getattr(item, 'meli_product', None)
                        if product:
                            cat = getattr(product, 'meli_category', None)
                            if cat:
                                item_data['category'] = get_category_full_path(cat)

                    items.append(item_data)
            order_data['items'] = items

            # Shipment info
            shipment = getattr(order, 'shipment', None)
            if shipment:
                ship_data = {
                    'id': shipment.id,
                    'shipment_id': getattr(shipment, 'shipment_id', None),
                    'status': getattr(shipment, 'status', None),
                    'logistic_type': getattr(shipment, 'logistic_type', None),
                    'tracking_number': getattr(shipment, 'tracking_number', None),
                }

                # Address
                receiver_address = getattr(shipment, 'receiver_address', None)
                if receiver_address:
                    ship_data['address'] = {
                        'street_name': getattr(receiver_address, 'street_name', None),
                        'street_number': getattr(receiver_address, 'street_number', None),
                        'city': getattr(receiver_address, 'city', getattr(receiver_address, 'city_name', None)),
                        'state': getattr(receiver_address, 'state', getattr(receiver_address, 'state_name', None)),
                        'zip_code': getattr(receiver_address, 'zip_code', None),
                        'country': getattr(receiver_address, 'country', getattr(receiver_address, 'country_name', None)),
                    }

                # Geolocation
                if hasattr(shipment, 'latitude') and hasattr(shipment, 'longitude'):
                    ship_data['geolocation'] = {
                        'latitude': shipment.latitude,
                        'longitude': shipment.longitude,
                    }

                order_data['shipment'] = ship_data

            # Buyer info
            buyer = getattr(order, 'buyer', None)
            if buyer:
                buyer_data = {
                    'id': buyer.id,
                    'buyer_id': getattr(buyer, 'buyer_id', None),
                    'nickname': getattr(buyer, 'nickname', None),
                    'first_name': getattr(buyer, 'first_name', None),
                    'last_name': getattr(buyer, 'last_name', None),
                    'email': getattr(buyer, 'email', None),
                }

                # Billing info (CUIT)
                billing_info = getattr(buyer, 'billing_info', None)
                if billing_info:
                    buyer_data['billing'] = {
                        'doc_type': getattr(billing_info, 'doc_type', None),
                        'doc_number': getattr(billing_info, 'doc_number', None),
                    }
                elif hasattr(buyer, 'cuit'):
                    buyer_data['billing'] = {
                        'doc_type': 'CUIT',
                        'doc_number': buyer.cuit,
                    }

                order_data['buyer'] = buyer_data

            results.append(order_data)

        # Get total count for pagination
        total_count = ml_orders.search_count(domain)

        return {
            'success': True,
            'total': total_count,
            'limit': limit,
            'offset': offset,
            'orders': results,
        }

    @http.route('/ocapi/<string:connector>/kpis/orders/export', auth='public', type='http', methods=['GET', 'POST'], csrf=False, cors='*')
    def kpis_orders_export(self, connector, **post):
        """
        Export orders as comprehensive CSV file.

        Includes:
        - Order info (id, status, dates, amounts)
        - Item details (product, category, prices)
        - Shipment details (address, geolocation, tracking)
        - Buyer info (contact, billing/CUIT)
        - Payment info
        """
        import csv
        import io

        connection = self.get_mercadolibre_connection_by_credentials(**post)
        if not connection:
            return Response(
                'Invalid credentials',
                status=401,
                content_type='text/plain'
            )

        date_from = post.get('date_from')
        date_to = post.get('date_to')
        limit = int(post.get('limit', 10000))
        status_filter = post.get('status')

        if 'mercadolibre.orders' not in request.env:
            return Response('Model not found', status=500, content_type='text/plain')

        # Build domain
        domain = []
        if date_from:
            domain.append(('date_created', '>=', date_from))
        if date_to:
            domain.append(('date_created', '<=', date_to))
        if status_filter:
            if ',' in status_filter:
                domain.append(('status', 'in', status_filter.split(',')))
            else:
                domain.append(('status', '=', status_filter))

        ml_orders = request.env['mercadolibre.orders'].sudo()
        orders = ml_orders.search(domain, limit=limit, order='date_created desc')

        # Category cache for performance
        category_cache = {}

        def get_category_info(cat_id):
            """Get category name and full path from cache or DB."""
            if not cat_id:
                return '', ''
            if cat_id in category_cache:
                return category_cache[cat_id]

            cat = request.env['mercadolibre.category'].sudo().search(
                [('meli_category_id', '=', cat_id)], limit=1
            )
            if cat:
                path_parts = []
                current = cat
                seen = set()
                while current and current.id not in seen:
                    seen.add(current.id)
                    path_parts.insert(0, current.name or '')
                    current = current.meli_father_category
                result = (cat.name or '', ' > '.join(path_parts))
            else:
                result = ('', '')
            category_cache[cat_id] = result
            return result

        # Create CSV with semicolon delimiter for Excel compatibility
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        # Comprehensive headers
        headers = [
            # === ORDER INFO ===
            'order_id',
            'order_name',
            'status',
            'status_detail',
            'date_created',
            'date_closed',
            'pack_id',
            'pack_order',
            'catalog_order',
            'context',
            'tags',
            # === AMOUNTS ===
            'total_amount',
            'paid_amount',
            'fee_amount',
            'financing_fee_amount',
            'shipping_cost',
            'shipping_seller_cost',
            'shipping_list_cost',
            'coupon_amount',
            'currency',
            # === ITEM INFO ===
            'item_meli_id',
            'item_variation_id',
            'item_title',
            'item_sku',
            'item_seller_custom_field',
            'item_quantity',
            'item_unit_price',
            'item_full_unit_price',
            'item_sale_fee',
            'item_iva',
            # === PRODUCT INFO ===
            'product_id',
            'product_name',
            'product_default_code',
            'product_barcode',
            # === CATEGORY INFO ===
            'category_id',
            'category_name',
            'category_full_path',
            # === SHIPMENT STATUS ===
            'shipment_id',
            'shipment_status',
            'shipment_substatus',
            'shipment_logistic_type',
            'shipment_mode',
            'shipment_shipping_mode',
            'tracking_number',
            'tracking_method',
            'shipment_date_created',
            # === SHIPMENT COSTS ===
            'ship_shipping_amount',
            'ship_shipping_cost',
            'ship_shipping_seller_cost',
            'ship_shipping_list_cost',
            # === RECEIVER ADDRESS ===
            'receiver_name',
            'receiver_phone',
            'receiver_address_line',
            'receiver_street_name',
            'receiver_street_number',
            'receiver_city',
            'receiver_city_code',
            'receiver_state',
            'receiver_state_code',
            'receiver_country',
            'receiver_country_code',
            'receiver_zip_code',
            'receiver_latitude',
            'receiver_longitude',
            # === BUYER INFO ===
            'buyer_id',
            'buyer_name',
            'buyer_nickname',
            'buyer_email',
            'buyer_phone',
            'buyer_alternative_phone',
            'buyer_first_name',
            'buyer_last_name',
            # === BILLING INFO ===
            'billing_doc_type',
            'billing_doc_number',
            'billing_tax_type',
            'billing_business_name',
            'billing_street_name',
            'billing_street_number',
            'billing_city_name',
            'billing_state_name',
            'billing_zip_code',
            # === PAYMENT INFO ===
            'payment_id',
            'payment_status',
            'payment_transaction_amount',
            'payment_total_paid_amount',
            'payment_fee_amount',
            'payment_shipping_amount',
            'payment_financing_fee',
            'payment_date_created',
            # === SALE ORDER ===
            'sale_order_id',
            'sale_order_name',
        ]
        writer.writerow(headers)

        # Write data rows
        for order in orders:
            # Get related objects
            ship = order.shipment
            buyer = order.buyer
            items = order.order_items
            payments = order.payments
            sale = order.sale_order

            # Base order data (common for all items)
            base_data = {
                # Order info
                'order_id': order.order_id or '',
                'order_name': order.name or '',
                'status': order.status or '',
                'status_detail': order.status_detail or '',
                'date_created': order.date_created.strftime('%Y-%m-%d %H:%M:%S') if order.date_created else '',
                'date_closed': order.date_closed.strftime('%Y-%m-%d %H:%M:%S') if order.date_closed else '',
                'pack_id': order.pack_id or '',
                'pack_order': 'Si' if order.pack_order else 'No',
                'catalog_order': 'Si' if order.catalog_order else 'No',
                'context': order.context or '',
                'tags': order.tags or '',
                # Amounts
                'total_amount': order.total_amount or 0,
                'paid_amount': order.paid_amount or 0,
                'fee_amount': order.fee_amount or 0,
                'financing_fee_amount': order.financing_fee_amount or 0,
                'shipping_cost': order.shipping_cost or 0,
                'shipping_seller_cost': order.shipping_seller_cost or 0,
                'shipping_list_cost': order.shipping_list_cost or 0,
                'coupon_amount': order.coupon_amount or 0,
                'currency': order.currency_id or '',
            }

            # Shipment data
            ship_data = {
                'shipment_id': ship.shipping_id if ship else '',
                'shipment_status': ship.status if ship else '',
                'shipment_substatus': ship.substatus if ship else '',
                'shipment_logistic_type': ship.logistic_type if ship else '',
                'shipment_mode': ship.mode if ship else '',
                'shipment_shipping_mode': ship.shipping_mode if ship else '',
                'tracking_number': ship.tracking_number if ship else '',
                'tracking_method': ship.tracking_method if ship else '',
                'shipment_date_created': ship.date_created.strftime('%Y-%m-%d %H:%M:%S') if ship and ship.date_created else '',
                # Shipment costs
                'ship_shipping_amount': ship.shipping_amount if ship else '',
                'ship_shipping_cost': ship.shipping_cost if ship else '',
                'ship_shipping_seller_cost': ship.shipping_seller_cost if ship else '',
                'ship_shipping_list_cost': ship.shipping_list_cost if ship else '',
                # Receiver address
                'receiver_name': ship.receiver_address_name if ship else '',
                'receiver_phone': ship.receiver_address_phone if ship else '',
                'receiver_address_line': ship.receiver_address_line if ship else '',
                'receiver_street_name': ship.receiver_street_name if ship else '',
                'receiver_street_number': ship.receiver_street_number if ship else '',
                'receiver_city': ship.receiver_city if ship else '',
                'receiver_city_code': ship.receiver_city_code if ship else '',
                'receiver_state': ship.receiver_state if ship else '',
                'receiver_state_code': ship.receiver_state_code if ship else '',
                'receiver_country': ship.receiver_country if ship else '',
                'receiver_country_code': ship.receiver_country_code if ship else '',
                'receiver_zip_code': ship.receiver_zip_code if ship else '',
                'receiver_latitude': ship.receiver_latitude if ship else '',
                'receiver_longitude': ship.receiver_longitude if ship else '',
            }

            # Buyer data
            buyer_data = {
                'buyer_id': buyer.buyer_id if buyer else '',
                'buyer_name': buyer.name if buyer else '',
                'buyer_nickname': buyer.nickname if buyer else '',
                'buyer_email': buyer.email if buyer else '',
                'buyer_phone': buyer.phone if buyer else '',
                'buyer_alternative_phone': buyer.alternative_phone if buyer else '',
                'buyer_first_name': buyer.first_name if buyer else '',
                'buyer_last_name': buyer.last_name if buyer else '',
                # Billing info
                'billing_doc_type': buyer.billing_info_doc_type if buyer else '',
                'billing_doc_number': buyer.billing_info_doc_number if buyer else '',
                'billing_tax_type': buyer.billing_info_tax_type if buyer else '',
                'billing_business_name': buyer.billing_info_business_name if buyer else '',
                'billing_street_name': buyer.billing_info_street_name if buyer else '',
                'billing_street_number': buyer.billing_info_street_number if buyer else '',
                'billing_city_name': buyer.billing_info_city_name if buyer else '',
                'billing_state_name': buyer.billing_info_state_name if buyer else '',
                'billing_zip_code': buyer.billing_info_zip_code if buyer else '',
            }

            # Payment data (first payment)
            payment = payments[0] if payments else None
            payment_data = {
                'payment_id': payment.payment_id if payment else '',
                'payment_status': payment.status if payment else '',
                'payment_transaction_amount': payment.transaction_amount if payment else '',
                'payment_total_paid_amount': payment.total_paid_amount if payment else '',
                'payment_fee_amount': payment.fee_amount if payment else '',
                'payment_shipping_amount': payment.shipping_amount if payment else '',
                'payment_financing_fee': payment.financing_fee_amount if payment else '',
                'payment_date_created': payment.date_created.strftime('%Y-%m-%d %H:%M:%S') if payment and payment.date_created else '',
            }

            # Sale order data
            sale_data = {
                'sale_order_id': sale.id if sale else '',
                'sale_order_name': sale.name if sale else '',
            }

            # Write one row per item (or one row if no items)
            if not items:
                # No items - write order with empty item fields
                row = [
                    base_data['order_id'], base_data['order_name'], base_data['status'],
                    base_data['status_detail'], base_data['date_created'], base_data['date_closed'],
                    base_data['pack_id'], base_data['pack_order'], base_data['catalog_order'],
                    base_data['context'], base_data['tags'],
                    base_data['total_amount'], base_data['paid_amount'], base_data['fee_amount'],
                    base_data['financing_fee_amount'], base_data['shipping_cost'],
                    base_data['shipping_seller_cost'], base_data['shipping_list_cost'],
                    base_data['coupon_amount'], base_data['currency'],
                    # Empty item fields
                    '', '', '', '', '', '', '', '', '', '',
                    # Empty product fields
                    '', '', '', '',
                    # Empty category fields
                    '', '', '',
                    # Shipment
                    ship_data['shipment_id'], ship_data['shipment_status'], ship_data['shipment_substatus'],
                    ship_data['shipment_logistic_type'], ship_data['shipment_mode'],
                    ship_data['shipment_shipping_mode'], ship_data['tracking_number'],
                    ship_data['tracking_method'], ship_data['shipment_date_created'],
                    ship_data['ship_shipping_amount'], ship_data['ship_shipping_cost'],
                    ship_data['ship_shipping_seller_cost'], ship_data['ship_shipping_list_cost'],
                    ship_data['receiver_name'], ship_data['receiver_phone'],
                    ship_data['receiver_address_line'], ship_data['receiver_street_name'],
                    ship_data['receiver_street_number'], ship_data['receiver_city'],
                    ship_data['receiver_city_code'], ship_data['receiver_state'],
                    ship_data['receiver_state_code'], ship_data['receiver_country'],
                    ship_data['receiver_country_code'], ship_data['receiver_zip_code'],
                    ship_data['receiver_latitude'], ship_data['receiver_longitude'],
                    # Buyer
                    buyer_data['buyer_id'], buyer_data['buyer_name'], buyer_data['buyer_nickname'],
                    buyer_data['buyer_email'], buyer_data['buyer_phone'],
                    buyer_data['buyer_alternative_phone'], buyer_data['buyer_first_name'],
                    buyer_data['buyer_last_name'],
                    buyer_data['billing_doc_type'], buyer_data['billing_doc_number'],
                    buyer_data['billing_tax_type'], buyer_data['billing_business_name'],
                    buyer_data['billing_street_name'], buyer_data['billing_street_number'],
                    buyer_data['billing_city_name'], buyer_data['billing_state_name'],
                    buyer_data['billing_zip_code'],
                    # Payment
                    payment_data['payment_id'], payment_data['payment_status'],
                    payment_data['payment_transaction_amount'], payment_data['payment_total_paid_amount'],
                    payment_data['payment_fee_amount'], payment_data['payment_shipping_amount'],
                    payment_data['payment_financing_fee'], payment_data['payment_date_created'],
                    # Sale order
                    sale_data['sale_order_id'], sale_data['sale_order_name'],
                ]
                writer.writerow(row)
            else:
                for item in items:
                    # Get category info
                    cat_name, cat_path = get_category_info(item.order_item_category_id)

                    # Get product info
                    product = item.product_id

                    row = [
                        # Order info
                        base_data['order_id'], base_data['order_name'], base_data['status'],
                        base_data['status_detail'], base_data['date_created'], base_data['date_closed'],
                        base_data['pack_id'], base_data['pack_order'], base_data['catalog_order'],
                        base_data['context'], base_data['tags'],
                        # Amounts
                        base_data['total_amount'], base_data['paid_amount'], base_data['fee_amount'],
                        base_data['financing_fee_amount'], base_data['shipping_cost'],
                        base_data['shipping_seller_cost'], base_data['shipping_list_cost'],
                        base_data['coupon_amount'], base_data['currency'],
                        # Item info
                        item.order_item_id or '',
                        item.order_item_variation_id or '',
                        item.order_item_title or '',
                        item.seller_sku or '',
                        item.seller_custom_field or '',
                        item.quantity or '',
                        item.unit_price or '',
                        item.full_unit_price or '',
                        item.sale_fee or '',
                        item.order_item_iva or '',
                        # Product info
                        product.id if product else '',
                        product.display_name if product else '',
                        product.default_code if product else '',
                        product.barcode if product else '',
                        # Category info
                        item.order_item_category_id or '',
                        cat_name,
                        cat_path,
                        # Shipment
                        ship_data['shipment_id'], ship_data['shipment_status'], ship_data['shipment_substatus'],
                        ship_data['shipment_logistic_type'], ship_data['shipment_mode'],
                        ship_data['shipment_shipping_mode'], ship_data['tracking_number'],
                        ship_data['tracking_method'], ship_data['shipment_date_created'],
                        ship_data['ship_shipping_amount'], ship_data['ship_shipping_cost'],
                        ship_data['ship_shipping_seller_cost'], ship_data['ship_shipping_list_cost'],
                        ship_data['receiver_name'], ship_data['receiver_phone'],
                        ship_data['receiver_address_line'], ship_data['receiver_street_name'],
                        ship_data['receiver_street_number'], ship_data['receiver_city'],
                        ship_data['receiver_city_code'], ship_data['receiver_state'],
                        ship_data['receiver_state_code'], ship_data['receiver_country'],
                        ship_data['receiver_country_code'], ship_data['receiver_zip_code'],
                        ship_data['receiver_latitude'], ship_data['receiver_longitude'],
                        # Buyer
                        buyer_data['buyer_id'], buyer_data['buyer_name'], buyer_data['buyer_nickname'],
                        buyer_data['buyer_email'], buyer_data['buyer_phone'],
                        buyer_data['buyer_alternative_phone'], buyer_data['buyer_first_name'],
                        buyer_data['buyer_last_name'],
                        buyer_data['billing_doc_type'], buyer_data['billing_doc_number'],
                        buyer_data['billing_tax_type'], buyer_data['billing_business_name'],
                        buyer_data['billing_street_name'], buyer_data['billing_street_number'],
                        buyer_data['billing_city_name'], buyer_data['billing_state_name'],
                        buyer_data['billing_zip_code'],
                        # Payment
                        payment_data['payment_id'], payment_data['payment_status'],
                        payment_data['payment_transaction_amount'], payment_data['payment_total_paid_amount'],
                        payment_data['payment_fee_amount'], payment_data['payment_shipping_amount'],
                        payment_data['payment_financing_fee'], payment_data['payment_date_created'],
                        # Sale order
                        sale_data['sale_order_id'], sale_data['sale_order_name'],
                    ]
                    writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        filename = f"orders_export_{date_from or 'all'}_{date_to or 'now'}.csv"

        return Response(
            csv_content,
            headers={
                'Content-Type': 'text/csv; charset=utf-8',
                'Content-Disposition': f'attachment; filename="{filename}"',
            }
        )


class MercadoLibreLoginMultiple(MercadoLibreLogin):

    @http.route(['/meli_login/<string:meli_login_id>'], type='http', auth="user", methods=['GET'], website=True)
    def index(self, meli_login_id, **codes ):

        #_logger.info("Meli Login Multiple: "+str(meli_login_id))

        if not meli_login_id:
            company = request.env.user.company_id
            meli_account = company and company.mercadolibre_connections and company.mercadolibre_connections[0]
            if meli_account:
                meli_login_id = meli_account.meli_login_id
            if not meli_login_id:
                return ""

        #_logger.info("User: "+str(request.env.user))
        #_logger.info("User Name: "+str(request.env.user.name))
        #_logger.info("User Company Ids: "+str(request.env.user.company_ids))

        meli_account = request.env['mercadolibre.account'].sudo().search([('meli_login_id','=',meli_login_id)])
        #_logger.info("Search meli_account: " + str(meli_account) )
        if not meli_account:
            return "Account not founded."

        company = meli_account.company_id or request.env.user.company_id

        meli_util_model = request.env['meli.util']
        meli = meli_util_model.get_new_instance( company, meli_account )

        codes.setdefault('code','none')
        codes.setdefault('error','none')
        if codes['error']!='none':
            message = "ERROR: %s" % codes['error']
            return "<h5>"+message+"</h5><br/>Retry (check your redirect_uri field in MercadoLibre company configuration, also the actual user and public user default company must be the same company ): <a href='"+meli.auth_url(redirect_URI=meli_account.redirect_uri)+"'>Login</a>"

        if codes['code']!='none':
            #_logger.info( "Meli: Authorize: REDIRECT_URI: %s, code: %s" % ( meli_account.redirect_uri, codes['code'] ) )
            resp = meli.authorize( codes['code'], meli_account.redirect_uri)
            login_data = { 'access_token': meli.access_token,
                             'refresh_token': meli.refresh_token,
                             'code': codes['code'],
                             'cron_refresh': True,
                             'status': 'connected' }
            meli_account.write( login_data )
            meli_account.message_post(body=str("Login result: "+str(login_data)+str("\n"+"RESPONSE:") +str(resp) ), message_type="notification" )
            
            return 'LOGGED WITH CODE: %s <br>ACCESS_TOKEN: %s <br>REFRESH_TOKEN: %s <br>MercadoLibre Publisher for Odoo - Copyright Moldeo Interactive <br><a href="javascript:window.history.go(-2);">Volver a Odoo</a> <script>window.history.go(-2)</script>' % ( codes['code'], meli.access_token, meli.refresh_token )
        else:
            return "<a href='"+meli.auth_url()+"'>Try to Login Again Please</a>"
