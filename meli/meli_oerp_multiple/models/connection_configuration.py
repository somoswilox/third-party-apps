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
from odoo.tools import html_escape
from datetime import timedelta
import logging
_logger = logging.getLogger(__name__)
import pdb
#from .warning import warning
import requests

class MercadoLibreChannel(models.Model):

    _name = 'mercadolibre.channel'
    _description = 'MercadoLibre Channel'

    name = fields.Char(string="Name",required=True,index=True)
    code = fields.Char(string="Code",help="Code Prefix for Orders: (ML for MercadoLibre) SHO (Shopify)")
    app_id = fields.Char(string="App Id",required=True,index=True)
    country_id = fields.Many2one("res.country",string="Country",index=True)
    journal_id = fields.Many2one( "account.journal", string="Journal")
    partner_id = fields.Many2one( "res.partner", string="Partner")
    #sequence_id = fields.Many2one('ir.sequence', string='Order Sequence',
    #    help="Order labelling for this channel", copy=False)

class MercadoLibreConnectionConfiguration(models.Model):

    _name = "mercadolibre.configuration"
    _description = "MercadoLibre Connection Parameters Configuration"
    _inherit = ["ocapi.connection.configuration", "mercadolibre.seller.perms.mixin"]

    @api.onchange('mercadolibre_seller_user', 'mercadolibre_seller_team')
    def _onchange_meli_seller_perms(self):
        return self._meli_seller_perms_warning()

    # Fields that must be synced from configuration to res.company
    _CRON_SYNC_FIELDS = [
        'mercadolibre_cron_post_update_price',
        'mercadolibre_cron_post_update_stock',
        'mercadolibre_cron_post_update_products',
        'mercadolibre_cron_post_new_products',
        'mercadolibre_cron_get_update_products',
        'mercadolibre_cron_get_orders',
        'mercadolibre_cron_get_questions',
    ]

    def write(self, vals):
        res = super().write(vals)
        # Sync cron booleans to res.company when changed
        sync_vals = {k: vals[k] for k in self._CRON_SYNC_FIELDS if k in vals and k in self.env['res.company']._fields}
        if sync_vals:
            for config in self:
                company = config.company_id
                if company:
                    company.sudo().write(sync_vals)
        # Invalidate location cache when any location-related config changes so the next
        # stock calculation uses the updated configuration rather than a stale cached result.
        _loc_fields = {'publish_stock', 'publish_stock_locations', 'mercadolibre_stock_warehouse',
                       'mercadolibre_stock_location_to_post', 'mercadolibre_stock_location_to_post_many'}
        if _loc_fields & set(vals):
            try:
                from odoo.addons.meli_oerp_stock.models.product import product_product
                if hasattr(product_product, '_clear_logistic_type_cache'):
                    product_product._clear_logistic_type_cache()
                    _logger.info("MercadoLibreConfiguration.write: location cache invalidated (changed: %s)",
                                 ', '.join(_loc_fields & set(vals)))
            except Exception:
                pass
        return res

    #mercadolibre_channels = fields.Many2many("mercadolibre.channel", string="MercadoLibre Channels")
    accounts = fields.One2many( "mercadolibre.account","configuration", string="Accounts", help="Accounts"  )

    @api.depends('accounts')
    def _connection_account( self ):
        for mc in self:
            mc.connection_account = False
            if mc.accounts:
                mc.connection_account = (mc.accounts and mc.accounts[0]) or False

    connection_account = fields.Many2one("mercadolibre.account",compute=_connection_account, store=True)
    mercadolibre_user_product_seller = fields.Boolean(string="User Product Seller",related="connection_account.user_product_seller",store=True)

    # Campo computado para mostrar el estado de la cuenta en la configuración
    # NOTE: Using compute instead of related because account_state is defined
    # only on mercadolibre.account (not on parent ocapi.connection.account),
    # and related fields through computed Many2one fail during _setup_fields.
    account_state = fields.Selection([
        ("new", "Nuevo"),
        ("configuring", "Configurando"),
        ("active", "Activo"),
        ("paused", "Pausado"),
        ("error", "Error"),
        ("disconnected", "Desconectado")
    ], string="Estado de Cuenta",
       compute='_compute_account_state',
       readonly=True,
       help="Estado operacional de la cuenta de MercadoLibre asociada")

    account_status = fields.Selection([
        ("disconnected", "Disconnected"),
        ("connected", "Connected"),
    ], string="Conexión",
       compute='_compute_account_state',
       readonly=True,
       help="Estado de conexión con MercadoLibre")

    @api.depends('connection_account')
    def _compute_account_state(self):
        for config in self:
            if config.connection_account:
                config.account_state = config.connection_account.account_state
                config.account_status = config.connection_account.status
            else:
                config.account_state = False
                config.account_status = False

    def _connection_account_company( self ):
        for mc in self:
            mc.company_id = False
            mc._connection_account()
            if mc.connection_account:
                mc.company_id = (mc.connection_account and mc.connection_account.company_id) or False
    company_id = fields.Many2one("res.company", string="Company",index=True)

    #Import #extending because of relational table name conflicts, conflict with publish price list (TODO: let one)
    import_price_lists = fields.Many2many("product.pricelist",relation='mercadolibre_conf_import_pricelist_rel',column1='configuration_id',column2='pricelist_id',string="Import Price Lists")

    mercadolibre_category_import = fields.Char( string='Category to import', help='Category Code to Import, check Recursive Import to import the full tree', size=256)
    mercadolibre_recursive_import = fields.Boolean( string='Recursive import', help='Import all the category tree from Category Code')

    mercadolibre_cron_refresh = fields.Boolean(string='Keep alive',help='Cron Automatic Token Refresh for keeping ML connection alive.')
    mercadolibre_cron_mail = fields.Many2one(
        comodel_name="mail.template",
        string="Error E-mail Template",
        help="Select the email template that will be sent when "
        "cron refresh fails.")
    mercadolibre_cron_get_orders = fields.Boolean(string="Importar pedidos",help='Cron Get Orders / Pedidos de venta')
    mercadolibre_cron_orders_limit = fields.Integer(
        string="Límite de órdenes por cron",
        help="Cantidad máxima de órdenes a procesar por ejecución del cron (notificaciones + órdenes faltantes). Default: 10",
        default=10
    )
    mercadolibre_cron_get_orders_shipment = fields.Boolean(string='Importar envíos',help='Cron Get Orders Shipment')
    mercadolibre_including_shipping_cost = fields.Selection(string="Incluir envio en pedido y factura", selection=[('always','Siempre'),('never','Nunca')],default='always')
    mercadolibre_use_payment_shipping_amount = fields.Boolean(string="Usar Monto de envío de Pagos",help="El monto del envio puede variar, en el objeto de envio tenemos el shippig_cost y en los pagos el shipping amount.",default=True)

    mercadolibre_cron_get_orders_shipment_client = fields.Boolean(string='Importar clientes',help='Cron Get Orders Shipment Client')
    mercadolibre_cron_get_orders_client_set_company = fields.Boolean(string='Asociar Empresa',help='Asociar el cliente siempre a la empresa de la cuenta',default=True)
    mercadolibre_cron_get_questions = fields.Boolean(string='Importar preguntas',help='Cron Get Questions')
    mercadolibre_cron_get_update_products = fields.Boolean(string='Actualizar productos en Odoo',help='Cron Update Products already imported')

    mercadolibre_cron_post_update_products = fields.Boolean(string='Actualizar productos en ML',help='Cron Update Posted Products, Product Templates or Variants with Meli Publication field checked')
    mercadolibre_cron_post_update_stock = fields.Boolean(string='Publicar Stock',help='Cron Post Updated Stock')
    mercadolibre_shipment_print_guide = fields.Boolean(string='Imprimir etiquetas',help='Imprimir etiquetas')
    mercadolibre_shipment_print_guide_mode = fields.Selection(string="Modo",help="Formato/empaquetado de la etiqueta: PDF, ZPL (zip tal cual lo entrega ML) o ZPL (txt: contenido extraído del zip, archivo .zpl)",selection=[('pdf','PDF'),('zpl','ZPL (zip)'),('zpl_txt','ZPL (txt)')],default='pdf')
    mercadolibre_shipment_printer_name = fields.Char(
        string="Destino de impresión",
        help="Nombre de la impresora o destino donde se envían las etiquetas. "
             "Para ZPL: nombre de la impresora Zebra (ej: 'Zebra ZD421 - Despacho'). "
             "Para PDF: nombre de la impresora o 'Descargar' si es manual.",
    )
    
    mercadolibre_cron_post_update_price = fields.Boolean(string='Publicar Precio',help='Cron Post Updated Price')
    mercadolibre_create_website_categories = fields.Boolean(string='Crear categorías',help='Create Website eCommerce Categories from imported products ML categories')
    mercadolibre_pricelist = fields.Many2one( "product.pricelist", "Product Pricelist default", help="Select price list for ML product"
        "when published from Odoo to ML", required=True)
    mercadolibre_pricelist_usd = fields.Many2one( "product.pricelist", "Product Pricelist default USD", help="USD Select price list for ML product"
        "when published from Odoo to ML")

    mercadolibre_order_total_config = fields.Selection( [
                                                        ('manual','Manual'),
                                                        ('manual_conflict','Manual conflict'),
                                                        ('paid_amount','Paid Amount'),
                                                        ('transaction_amount','Transaction Amount'),
                                                        ('total_amount','Total Amount')
                                                        ] ,
                                                        default='paid_amount',
                                                        string="Total Config.",
                                                        help='Order Total Config, stategy to calculate order/invoice total amount.',
                                                        required=True )


    mercadolibre_buying_mode = fields.Selection( [("buy_it_now","Compre ahora"),
                                                  ("classified","Clasificado")],
                                                  string='Método de compra predeterminado', required=True)
    mercadolibre_currency = fields.Selection([  ("ARS","Peso Argentino (ARS)"),
                                                ("MXN","Peso Mexicano (MXN)"),
                                                ("COP","Peso Colombiano (COP)"),
                                                ("PEN","Sol Peruano (PEN)"),
                                                ("BOB","Boliviano (BOB)"),
                                                ("BRL","Real (BRL)"),
                                                ("CLP","Peso Chileno (CLP)"),
                                                ("CRC","Colon Costarricense (CRC)"),
                                                ("UYU","Peso Uruguayo (UYU)"),
                                                ("VES","Bolivar Soberano (VES)"),
                                                ("PAB","Balboa Panameño (PAB)"),
                                                ("USD","Dolar Estadounidense (USD)")],
                                                string='Moneda predeterminada', required=True)
    mercadolibre_condition = fields.Selection([ ("new", "Nuevo"),
                                                ("used", "Usado"),
                                                ("not_specified","No especificado")],
                                                default='new',
                                                string='Condición',
                                                help='Condición del producto predeterminado',
                                                required=True)
    mercadolibre_warranty = fields.Char(string='Garantía', size=256, help='Garantía del producto predeterminado. Es obligatorio y debe ser un número seguido por una unidad temporal. Ej. 2 meses, 3 años.')
    mercadolibre_listing_type = fields.Selection([("free","Libre"),
                                                ("bronze","Bronce/Clásica-(UY)"),
                                                ("silver","Plata"),
                                                ("gold","Oro"),
                                                ("gold_premium","Gold Premium/Oro Premium"),
                                                ("gold_special","Gold Special/Clásica/Premium-(UY)"),
                                                ("gold_pro","Oro Pro")],
                                                default='gold_special',
                                                string='Tipo de lista',
                                                help='Tipo de lista  predeterminada para todos los productos',
                                                required=True)

    mercadolibre_channel_mkt = fields.Many2many( "meli.channel.mkt", string="Channels", index=True )

    mercadolibre_attributes = fields.Boolean(string='Apply product attributes')
    mercadolibre_exclude_attributes = fields.Many2many('product.attribute.value',
        string='Valores excluidos', help='Seleccionar valores que serán excluidos para las publicaciones de variantes')
    mercadolibre_update_local_stock = fields.Boolean(string='Cron Get Products and take Stock from ML')
    mercadolibre_product_template_override_variant = fields.Boolean(string='Product template override Variant')
    mercadolibre_product_template_override_method = fields.Selection(string='Método para Sobreescribir',
                                                                    help='Método para Sobreescribir Titulo y Descripcion desde la información del Producto a la solapa de ML y sus variantes de ML',
                                                                    selection=[
                                                                        ('default','Predeterminado, sobreescribe descripcion solamente'),
                                                                        ('description','Sobreescribir descripcion solamente'),
                                                                        ('title','Sobreescribir título solamente'),
                                                                        ('title_and_description','Sobreescribir titulo y descripcion')
                                                                    ],
                                                                    default='default')
    mercadolibre_order_confirmation = fields.Selection([ ("manual", "Manual"),
                                                ("paid_confirm", "Pagado>Confirmado"),
                                                ("paid_delivered", "Pagado>Entregado"),
                                                ("paid_confirm_with_invoice", "Pagado>Facturado"),
                                                ("paid_delivered_with_invoice", "Pagado>Facturado y Entregado")],
                                                default='manual',
                                                string='Acción al recibir un pedido',
                                                help='Acción al confirmar una orden o pedido de venta',
                                                required=True)
    mercadolibre_order_confirmation_full = fields.Selection([
                                                ("manual", "Manual"),
                                                ("do_not_process", "No procesar"),
                                                ("paid_confirm", "Pagado>Confirmado"),
                                                ("paid_delivered", "Pagado>Entregado"),
                                                ("paid_confirm_with_invoice", "Pagado>Facturado"),
                                                ("paid_delivered_with_invoice", "Pagado>Facturado y Entregado")],
                                                default='manual',
                                                string='Acción al recibir un pedido en FULL',
                                                help='Acción al confirmar una orden o pedido de venta en FULL',
                                                required=True)
    mercadolibre_product_attribute_creation = fields.Selection([ ("manual", "Manual"),
                                                ("full", "Sincronizado completo (uno a uno, sin importar si se usa o no)"),
                                                ("dynamic", "Dinámico (cuando se asocia un producto a una categoría (ML) con atributos (ML))") ],
                                                default='manual',
                                                string='Create Product Attributes',
                                                required=True)
    #'mercadolibre_login': fields.selection( [ ("unknown", "Desconocida"), ("logged","Abierta"), ("not logged","Cerrada")],string='Estado de la sesión'), )
    mercadolibre_overwrite_template = fields.Boolean(string='Overwrite product template',help='Sobreescribir siempre Nombre y Descripción de la plantilla.')
    mercadolibre_overwrite_variant = fields.Boolean(string='Overwrite product variant',help='Sobreescribir siempre Nombre y Descripción de la variante.')
    mercadolibre_process_notifications = fields.Boolean(string='Process all notifications',help='Procesar las notificaciones recibidas (/meli_notify)')

    mercadolibre_create_product_from_order = fields.Boolean(string='Importar productos inexistentes',help='Importar productos desde la orden si no se encuentran en la base.')
    mercadolibre_update_existings_variants = fields.Boolean(string='Actualiza/agrega variantes',help='Permite agregar y actualizar variantes de un producto existente (No recomendable cuando se está ya en modo Odoo a ML, solo usar cuando se importa por primera vez de ML a Odoo, para no romper el stock)')
    mercadolibre_update_product_company = fields.Boolean(string='Setea la empresa del producto',default=False,help='Setea la empresa del producto con la empresa de la cuenta')
    mercadolibre_tax_included = fields.Selection( string='Tax Included',
                                                  help='Esto se aplica al importar ordenes, productos y tambien al publicar, sobre la lista de precio seleccionada o sobre el precio de lista.',
                                                  selection=[ ('auto','Configuración del sistema'),
                                                              ('tax_included','Impuestos ya incluídos del precio de lista'),
                                                              ('tax_excluded','Impuestos excluídos del precio de lista') ],
                                                  default='auto',
                                                  required=True )

    mercadolibre_do_not_use_first_image = fields.Boolean(string="Do not use first image")
    mercadolibre_cron_post_new_products = fields.Boolean(string='Incluir nuevos productos',help='Cron Post New Products, Product Templates or Variants with Meli Publication field checked')
    mercadolibre_cron_get_new_products = fields.Boolean(string='Importar nuevos productos',help='Cron Import New Products, Product Templates or Variants')
    mercadolibre_cron_get_new_products_batch_size = fields.Integer(
        string='Lote de importacion (cron)',
        help='Cantidad de publicaciones a importar por ejecucion del cron. '
             'Default: 300. Lote mas grande = menos writes de progreso en la fila '
             'mercadolibre.account = menos ventanas de colision 40001 con los otros '
             'crones meli (la API ML corre limpia sin 429 con lotes de 300-500).',
        default=300
    )
    mercadolibre_cron_get_new_products_post_state = fields.Selection([
        ('active', 'Activos'),
        ('paused', 'Pausados'),
        ('all', 'Todos'),
    ], string='Estado a importar (cron)',
       help='Estado de publicaciones ML a importar en el cron',
       default='active')
    mercadolibre_cron_get_new_products_force_dont_create = fields.Boolean(
        string='No crear productos (cron)',
        help='Solo vincular por SKU, no crear productos nuevos en Odoo',
        default=True
    )
    mercadolibre_cron_get_new_products_force_meli_pub = fields.Boolean(
        string='Force Meli Pub (cron)',
        help='Marcar campo Meli Publication al importar',
        default=True
    )
    mercadolibre_cron_get_new_products_force_import_images = fields.Boolean(
        string='Importar imagenes (cron)',
        help='Importar imagenes al importar productos en cron',
        default=True
    )
    # Modo explicito de dos fases para el batch import maestro-aware.
    #  - 'fetch'  : solo poblar la maestra (record_maestro_review) por publicacion,
    #               sin crear productos. Recalcula masters al cubrir toda la lista.
    #  - 'import' : crear productos SOLO desde los masters (is_master=True).
    # El operador corre primero FETCH (rapido) y luego cambia a IMPORT.
    # default='fetch' cubre los registros viejos sin migracion (arranca por fase 1,
    # que es idempotente y no crea nada).
    mercadolibre_cron_get_new_products_mode = fields.Selection([
        ('fetch',  'Fase 1: Relevar maestra (no crea productos)'),
        ('import', 'Fase 2: Importar masters (crea productos)'),
    ], string='Modo de importacion masiva (cron)',
       help='FETCH releva la maestra de publicaciones (rapido, sin crear). '
            'IMPORT crea productos solo desde los masters seleccionados por SKU. '
            'Corra primero FETCH hasta completar el ciclo, luego cambie a IMPORT.',
       default='fetch')

    mercadolibre_process_offset = fields.Char('Offset for pause all')
    mercadolibre_post_default_code = fields.Boolean(string='Post SKU',default=True,help='Post Odoo default_code field for templates or variants to seller_custom_field in ML')
    mercadolibre_post_barcode = fields.Boolean(string='Post Barcode',default=True,help='Post Odoo barcode as GTIN')
    mercadolibre_import_search_sku = fields.Boolean(string='Search SKU',default=True,help='Search product by default_code')

    mercadolibre_seller_user = fields.Many2one("res.users", string="Vendedor ML", help="Usuario con el que se registrarán las órdenes automáticamente")
    mercadolibre_seller_team = fields.Many2one("crm.team", string="Equipo de ventas ML", help="Equipo de ventas asociado a las ventas de ML")

    mercadolibre_contact_partner = fields.Many2one("res.partner",string="Contacto Predeterminado")
    mercadolibre_shipping_partner = fields.Many2one("res.partner",string="Contacto de Envio Predeterminado")
    mercadolibre_invoice_partner = fields.Many2one("res.partner",string="Contacto de Facturación Predeterminado")

    mercadolibre_generic_vats = fields.Char(
        string="VATs genéricos (no fiscales)",
        help="Lista separada por comas de números de documento considerados genéricos "
             "(ej: XAXX010101000,XEXX010101000 en México). Estos VATs no generan "
             "entidad fiscal independiente: se asignan al buyer directamente y "
             "no se usan para buscar/crear contactos de facturación en Modo 3. "
             "Si se deja vacío, se usan los valores predeterminados del país.",
    )

    mercadolibre_skip_same_name_billing_contact = fields.Boolean(
        string="Fusionar contacto si nombre = razón social",
        default=False,
        help="Cuando el nombre del buyer de MercadoLibre y el nombre legal de "
             "facturación son idénticos (ignorando mayúsculas y acentos), "
             "evita crear un contacto hijo de facturación duplicado: los datos "
             "fiscales (CUIT/VAT, tipo doc, etc.) se asignan directamente al "
             "contacto principal y el nombre se corrige al formato legal.\n\n"
             "Recomendado para Argentina/Chile donde el nickname de Meli suele "
             "coincidir con el nombre legal de la persona física.",
    )

    mercadolibre_billing_force_on_main = fields.Boolean(
        string="Datos fiscales SIEMPRE en el contacto principal (no separar)",
        default=False,
        help="ESTRATEGIA B: asigna los datos de facturación (razón social, CUIT/VAT, tipo doc, "
             "posición fiscal) directamente al contacto principal del comprador y corrige su "
             "nombre al legal, AUNQUE el nickname de MercadoLibre no coincida con la razón social "
             "(misma persona escrita distinto). Evita el contacto fiscal separado (Modo 3).\n\n"
             "Recomendado para clientes de personas físicas (AR/CL). Para B2B/multi-CUIT dejar "
             "en False (mantener el contacto fiscal independiente por CUIT).",
    )

    mercadolibre_days_to_availability = fields.Integer(
        string="Días para disponibilidad de envío",
        default=0,
        help="Días hábiles que tarda el vendedor en despachar el producto (days_to_availability). "
             "0 = despacho inmediato.",
    )

    mercadolibre_merge_same_name_contacts = fields.Boolean(
        string="Unificar contactos con mismo nombre",
        default=False,
        help="Cuando el comprador, el contacto de facturación y el de envío tienen el mismo nombre "
             "(normalizado), los tres se unifican al registro del comprador. "
             "Evita triplicar contactos para la misma persona.",
    )

    mercadolibre_set_fiscal_position = fields.Boolean(
        string="Setear posición fiscal en la venta",
        default=True,
        help="Si está activo (por defecto), la orden toma la posición fiscal del contacto "
             "de facturación (property_account_position_id) — útil para que el tipo de "
             "documento de factura salga correcto. Si se desactiva, la posición fiscal de "
             "la venta queda EN BLANCO (no la fuerza el conector).",
    )

    mercadolibre_remove_unsync_images = fields.Boolean(string='Removing unsync images (ml id defined for image but no longer in ML publication)')

    mercadolibre_official_store_id = fields.Char(string="Official Store Id",index=True)

    mercadolibre_payment_term = fields.Many2one("account.payment.term",string="Payment Term")

    mercadolibre_banner = fields.Many2one("mercadolibre.banner",string="Plantilla Descriptiva")

    ## STOCK Configuration

    mercadolibre_stock_warehouse = fields.Many2one("stock.warehouse", string="Stock Warehouse Default", help="Almacen predeterminado", required=True)
    mercadolibre_stock_location_to_post = fields.Many2one("stock.location", string="Stock Location To Post", help="Ubicación desde dónde publicar el stock")
    #mercadolibre_stock_location_to_post_many = fields.Many2many("stock.location", string="Stock Location To Post", help="Ubicaciones desde dónde publicar el stock")

    mercadolibre_stock_warehouse_full = fields.Many2one("stock.warehouse", string="Stock Warehouse Default for FULL", help="Almacen predeterminado para modo fulfillment", required=True)
    mercadolibre_stock_location_to_post_full = fields.Many2one("stock.location", string="Stock Location To Post for Full", help="Ubicación desde dónde publicar el stock en modo Full")

    mercadolibre_full_lot_policy = fields.Selection(
        selection=[
            ('off',        'Desactivado (no tocar lotes automáticamente)'),
            ('on_assign',  'Automático en _action_assign (recomendado)'),
            ('manual',     'Solo manual (wizard / botón)'),
        ],
        string="FULL — Política de auto-asignación de lotes (FIFO)",
        default='on_assign',
        required=True,
        help="Controla cómo se resuelven automáticamente los lotes en pickings de MELI FULL\n"
             "cuando un producto con tracking='lot' tiene stock repartido en varios lotes:\n\n"
             "  • Desactivado: el usuario debe asignar los lotes manualmente.\n"
             "  • Automático (recomendado): al momento del 'Check availability' (hook "
             "_action_assign), el sistema divide la reserva creando un stock.move.line "
             "por lote tomando FIFO (el lote más viejo primero por create_date).\n"
             "  • Solo manual: no corre en el hook, pero sí cuando el usuario lanza la "
             "acción del wizard de acciones masivas o el botón del picking.")

    mercadolibre_order_confirmation_delivery = fields.Selection([ ("manual", "No entregar"),
                                                ("paid_confirm_deliver", "Pagado > Entregar"),
                                                ("paid_confirm_shipped_deliver", "Pagado > Entregado > Entregar")],
                                                string='Acción de la entrega al confirmar un pedido',
                                                default='manual',
                                                help='Acción de la entrega al confirmar una orden o pedido de venta',
                                                required=True)

    mercadolibre_order_confirmation_delivery_full = fields.Selection([ ("manual", "No entregar"),
                                                ("paid_confirm_deliver", "Pagado > Entregar"),
                                                ("paid_confirm_shipped_deliver", "Pagado > Entregado > Entregar")],
                                                string='(FULL) Acción de la entrega al confirmar un pedido',
                                                default='manual',
                                                help='(FULL) Acción de la entrega al confirmar una orden o pedido de venta',
                                                required=True)

    #TODO: process shippings
    mercadolibre_stock_filter_order_datetime = fields.Datetime("Order Closed Date (For shipping)")
    mercadolibre_stock_filter_order_datetime_to = fields.Datetime("Order Closed Date To (For shipping)")


    mercadolibre_stock_update_mode = fields.Selection(selection=[
                                                            ("auto","Automático (detecta por publicación)"),
                                                            ("standard","Estándar (/items/{id})"),
                                                            ("user_product","Multi-warehouse (/user-products/{id}/stock)"),
                                                            ("user_product_type","Multi-warehouse por tipo (/user-products/{id}/stock/type/{tipo})"),
                                                    ],
                                                    string="Modo actualización de stock",
                                                    default='auto',
                                                    help="Automático: detecta el tipo de stock por publicación desde la API (recomendado para multi-warehouse).\n"
                                                         "Estándar: PUT /items/{id} con available_quantity (sellers normales).\n"
                                                         "Multi-warehouse: PUT /user-products/{id}/stock (sellers multiwarehouse).\n"
                                                         "Multi-warehouse por tipo: PUT /user-products/{id}/stock/type/{tipo} (sellers con selling_address o seller_warehouse).")

    mercadolibre_stock_update_type = fields.Selection(selection=[
                                                            ("selling_address","selling_address"),
                                                            ("seller_warehouse","seller_warehouse"),
                                                    ],
                                                    string="Tipo de stock (multi-warehouse)",
                                                    default='seller_warehouse',
                                                    help="Tipo de ubicación para el endpoint /user-products/{id}/stock/type/{tipo}.\n"
                                                         "seller_warehouse: stock por bodega del vendedor.\n"
                                                         "selling_address: stock por dirección de venta.")

    #TODO: activate
    mercadolibre_stock_virtual_available = fields.Selection(selection=[
                                                                            ("virtual","Planificado (virtual_available)"),
                                                                            ("theoretical","En mano (quantity)"),
                                                                            ("qty_reserved","Cantidad menos reservado (quantity - reserved)"),
                                                                            ("virtual_absoluto","Planificado (no suma negativos)"),
                                                                ],
                                                            default='virtual',
                                                            required=True)

    #mercadolibre_stock_sku_mapping = fields.Many2many("meli_oerp.sku.rule",string="Sku Rules")
    mercadolibre_stock_sku_mapping = fields.One2many("meli_oerp.sku.rule","configuration_id", string="Sku Rules")
    mercadolibre_stock_sku_mapping_rt = fields.Many2many("meli_oerp.sku.rule","configuration_id", string="Sku Rules RT")

    #TODO: 3 publicaciones, minimo 3 productos, si solo hay 1 unidad y 2 publicaciones, se pausea uno de las dos...
    #mercadolibre_stock_pause_rule = fields.Selection(selection=[('leave_max_price','Max price active'),('leave_max_seller','Max seller')], default='leave_max_price' )


    ## ACCOUNT configuration

    mercadolibre_process_payments_customer = fields.Boolean(string="Process payments from Customer")
    mercadolibre_process_payments_supplier_fea = fields.Boolean(string="Process payments fea to Supplier ML")
    mercadolibre_process_payments_supplier_shipment = fields.Boolean(string="Process payments shipping list cost to Supplier ML")

    mercadolibre_payment_receipt_validation = fields.Selection([('draft','Borrador'),('validate','Autovalidación'),('concile','Conciliar')], string="Payment validation",default='draft')

    mercadolibre_process_payments_journal = fields.Many2one("account.journal",string="Account Journal for MercadoLibre")
    mercadolibre_process_payments_res_partner = fields.Many2one("res.partner",string="MercadoLibre Partner")

    mercadolibre_process_payments_journal_shp = fields.Many2one("account.journal",string="Account Journal for MercadoLibre (SHP)")
    mercadolibre_process_payments_res_partner_shp = fields.Many2one("res.partner",string="MercadoLibre Partner (SHP)")


    mercadolibre_order_confirmation_hook = fields.Char(string="Order Hook",help="https://www.hookserver.com/app")
    mercadolibre_product_confirmation_hook = fields.Char(string="Product Hook",help="https://www.hookserver.com/app")

    mercadolibre_filter_order_datetime_start = fields.Datetime("Start Order Closed Date",help="Fecha a partir de la cual no se bloquean las entradas de pedidos desde ML")
    #mercadolibre_filter_order_cron_max = fields.Integer(string="Cantidad de ordenes maximas a chequear por iteracion de cron")
    mercadolibre_filter_order_datetime = fields.Datetime("Order Closed Date From",help="Fecha inicial para la importacion de pedidos (vacio: ultimas 50)")
    mercadolibre_filter_order_datetime_to = fields.Datetime("Order Closed Date To",help="Fecha final para la importacion de pedidos (vacio: el dia de hoy)")

    mercadolibre_so_name_tracking = fields.Boolean(
        string="Incluir tracking en nombre de venta",
        default=False,
        help="Si está activo, agrega el ID de envío o número de seguimiento "
             "al nombre de la orden de venta (ej: 'ML 123456 | TRACK-789'). "
             "Si está desactivado, el nombre queda solo con el ID de orden ML.",
    )

    mercadolibre_order_confirmation_invoice = fields.Selection([ ("manual", "No facturar"),
                                                ("paid_confirm_invoice", "Pagado > Facturar"),
                                                ("paid_confirm_draft_invoice", "Pagado > Facturar borrador"),
                                                ("paid_confirm_delivered_invoice", "Entregado > Facturar"),
                                                #("paid_confirm_invoice_deliver", "Pagado > Facturar > Entregar")
                                                ],
                                                default='manual',
                                                string='Acción al confirmar un pedido',
                                                help='Acción al confirmar una orden o pedido de venta',
                                                required=True)

    mercadolibre_order_confirmation_invoice_full = fields.Selection([ ("manual", "No facturar"),
                                                ("paid_confirm_invoice", "Pagado > Facturar"),
                                                ("paid_confirm_draft_invoice", "Pagado > Facturar borrador"),
                                                ("paid_confirm_delivered_invoice", "Entregado > Facturar"),
                                                #("paid_confirm_invoice_deliver", "Pagado > Facturar > Entregar")
                                                ],
                                                default='manual',
                                                string='(FULL) Acción al confirmar un pedido',
                                                help='(FULL) Acción al confirmar una orden o pedido de venta',
                                                required=True)

    meli_coupon_invoice_mode = fields.Selection(
        selection=[
            ("full", "Precio pleno (sin descuento de cupón)"),
            ("product_discount", "Descuento en producto"),
            ("separate_line", "Línea de descuento separada (avanzado)"),
        ],
        string="Tratamiento del cupón ML en la factura",
        default="full",
        help="Cómo se refleja el 'coupon_amount' que MercadoLibre financia de su propio costo "
             "(no es un descuento del vendedor):\n\n"
             "• Precio pleno (por defecto): la factura se emite por el precio de venta completo. "
             "Correcto cuando ML reembolsa el cupón al vendedor (su ingreso gravado es el precio "
             "pleno). Ni el producto ni el envío llevan el descuento.\n"
             "• Descuento en producto: el cupón se aplica como % de descuento sobre las líneas de "
             "producto (la factura coincide con lo que pagó el comprador).\n"
             "• Línea de descuento separada (avanzado): el cupón se imputa como línea(s) de "
             "descuento aparte, una por grupo de impuesto, sin tocar producto ni envío. Requiere "
             "validación fiscal previa (facturación electrónica AFIP/CL).\n\n"
             "Reemplaza a la antigua casilla 'Facturar con descuento de cupón'.",
    )

    meli_coupon_discount_on_invoice = fields.Boolean(
        string="Facturar con descuento de cupón financiado por ML",
        default=False,
        help="Controla cómo se trata el 'coupon_amount' que MercadoLibre reporta en la orden "
             "(descuento que ML financia de su propio costo para el comprador).\n\n"
             "☐ Desactivado (por defecto): la factura se emite por el precio de venta completo "
             "(lo que recibe el vendedor). Recomendado cuando contabilidad no tiene comprobante "
             "ML que respalde la diferencia.\n\n"
             "☑ Activado: el cupón ML se refleja como % de descuento en las líneas del pedido, "
             "de modo que la factura al comprador coincida con lo que él pagó (precio − cupón ML).\n\n"
             "NOTA: esto solo afecta el 'coupon_amount' de ML — no toca descuentos del vendedor "
             "ni otros descuentos aplicados manualmente en el pedido.",
    )

    mercadolibre_post_invoice = fields.Boolean(string="Send Invoice",help="Try to post invoice, when order is revisited or refreshed.")
    mercadolibre_post_invoice_dont_send = fields.Boolean(string="Dont really send, just prepare to post invoice.")

    mercadolibre_invoice_journal_id = fields.Many2one( "account.journal", string="Diario Facturacion" )
    mercadolibre_invoice_journal_report_id = fields.Many2one( "ir.actions.report", string="Reporte de factura" )
    mercadolibre_invoice_journal_id_full = fields.Many2one( "account.journal", string="Diario Facturacion Full" )

    mercadolibre_order_add_fea = fields.Selection([ ("manual", "No agregar"),
                                                ("per_item", "Agregar linea de orden de comision por pago/producto"),
                                                ("grouped", "Agregar linea de orden de comision agrupado")],
                                                string='Agregar comisiones a la orden',
                                                help='Agregar comisiones a la orden, por item o agrupado para poder hacer margen de ganancia')

    mercadolibre_product_fea = fields.Many2one("product.product", string="Product Fea")

    mercadolibre_analytic_account_id = fields.Many2one( "account.analytic.account", string="Cuenta Analítica" )


    #mercadolibre_account_payment_receiptbook_id = fields.Many2one( "account.payment.receiptbook", string="Recibos")
    #mercadolibre_account_payment_supplier_receiptbook_id = fields.Many2one( "account.payment.receiptbook", string="Orden de pago")

    BLOCK_TYPE = [
        ('qty_hand', 'Cantidad a mano = Cantidad a meno - Stock block'),
        ('qty_projected', 'Cantidad proyectado = Cantidad a mano - Pedidos confirmados - Stock block'),
    ]

    stock_block = fields.Boolean(string='Aplicar stock bloqueo')
    stock_block_type = fields.Selection(BLOCK_TYPE, string='Tipo de stock')

    # Rounding adjustment configuration
    mercadolibre_rounding_product_id = fields.Many2one(
        "product.product",
        string="Producto de Ajuste de Redondeo",
        help="Producto usado para agregar linea de ajuste de redondeo cuando hay diferencia de centavos"
    )
    mercadolibre_rounding_tolerance = fields.Float(
        string="Tolerancia de Redondeo",
        default=1.0,
        help="Diferencia maxima en moneda (ej: 1.0 = un peso) para ajustar automaticamente el monto de la orden"
    )
    mercadolibre_round_to_integer = fields.Boolean(
        string="Redondear a Entero (sin centavos)",
        default=False,
        help="Para paises como Argentina donde ya no existen los centavos"
    )
    mercadolibre_auto_rounding = fields.Boolean(
        string="Ajuste Automatico de Redondeo",
        default=False,
        help="Aplicar ajuste de redondeo automaticamente al crear/confirmar ordenes"
    )

    def copy_from_company( self, context=None, company=None ):
        context = context or self.env.context
        company = company or (self.accounts and self.accounts[0].company_id) or self.env.user.company_id
        #_logger.info("Copy configuration from company: "+str(context)+" company:" +str(company))
        if company:
            #self.import_price_lists = company.
            for field in self._fields:
                if "mercadolibre_" in field and field in company._fields:
                    #_logger.info("copy field: " + str(field)+" value: "+str(self[field]) )
                    self[field] = company[field]

    def copy_from_configuration( self ):
        _logger.info("Copy configuration from configuration")
        pass;

    # action_diagnose_stock_config fue movido a mercadolibre.account (connection_account.py)
    # para poder usar message_post (requiere mail.thread) y ubicarse junto al botón
    # "Check & Test Multiwarehouse" en el formulario de la cuenta.

        OK  = "✅"
        WARN = "⚠️"
        ERR  = "❌"

        issues = []   # (icon, text)
        infos  = []   # (icon, text)

        # ── 1. Modo de actualización ──────────────────────────────────────────
        mode       = (hasattr(config, 'mercadolibre_stock_update_mode') and config.mercadolibre_stock_update_mode) or 'standard'
        qty_method = (hasattr(config, 'mercadolibre_stock_virtual_available') and config.mercadolibre_stock_virtual_available) or 'virtual'
        _MODE_LABELS = {
            'standard':         'Estándar (PUT /items/{id})',
            'auto':             'Automático (detecta por publicación)',
            'user_product':     'Multi-warehouse (PUT /user-products/{id}/stock)',
            'user_product_type':'Multi-warehouse por tipo',
        }
        _QTY_LABELS = {
            'virtual':          'Virtual disponible (reservas descontadas)',
            'virtual_absoluto': 'Virtual absoluto (sin negativos)',
            'theoretical':      'Teórico (stock real sin movimientos)',
            'qty_reserved':     'Stock - reservado',
        }
        infos.append((OK, "Modo: <b>%s</b>" % html_escape(_MODE_LABELS.get(mode, mode))))
        infos.append((OK, "Método cantidad: <b>%s</b>" % html_escape(_QTY_LABELS.get(qty_method, qty_method))))

        # ── 2. Almacén estándar ───────────────────────────────────────────────
        wh          = config.mercadolibre_stock_warehouse
        loc_to_post = config.mercadolibre_stock_location_to_post
        if wh:
            infos.append((OK, "Almacén configurado: <b>%s</b> → ubicación stock: %s"
                          % (html_escape(wh.name), html_escape(wh.lot_stock_id.complete_name))))
        else:
            infos.append((WARN, "No hay almacén configurado (<i>mercadolibre_stock_warehouse</i> vacío)"))

        if loc_to_post:
            infos.append((OK, "Ubicación directa (override): <b>%s</b>" % html_escape(loc_to_post.complete_name)))

        # ── 3. Ubicaciones con mercadolibre_active=True ───────────────────────
        active_locs = self.env['stock.location'].search([
            ('mercadolibre_active', '=', True),
            ('company_id', '=', company.id),
        ])
        non_full_active = active_locs.filtered(
            lambda l: not l.mercadolibre_logistic_type or 'fulfillment' not in (l.mercadolibre_logistic_type or '')
        )
        full_active = active_locs - non_full_active

        if not active_locs:
            if not wh and not loc_to_post:
                issues.append((ERR, "Sin ubicaciones activas ni almacén configurado — "
                               "el stock <b>no se enviará</b> a ML"))
            else:
                infos.append((OK, "Sin ubicaciones con <i>mercadolibre_active</i> — "
                              "se usará el almacén/ubicación directa configurada"))
        else:
            infos.append((OK, "Ubicaciones con <i>mercadolibre_active=True</i>: <b>%d</b>" % len(active_locs)))

            # Verificar si las activas (no-FULL) pertenecen al almacén configurado
            if wh and non_full_active:
                wh_lot = wh.lot_stock_id
                wh_descendants = self.env['stock.location'].search([('id', 'child_of', wh_lot.id)])
                wh_ids = set(wh_descendants.ids) | {wh_lot.id}

                in_wh  = non_full_active.filtered(lambda l: l.id in wh_ids)
                out_wh = non_full_active.filtered(lambda l: l.id not in wh_ids)

                if in_wh:
                    infos.append((OK, "Dentro del almacén '<b>%s</b>': %s"
                                  % (html_escape(wh.name),
                                     ", ".join(html_escape(l.complete_name) for l in in_wh))))
                if out_wh:
                    # Check if out-of-warehouse locs are covered by publish_stock_locations
                    _psl = config.publish_stock_locations if ("publish_stock_locations" in config._fields and config.publish_stock) else self.env['stock.location']
                    _psl_ids = set(_psl.ids) if _psl else set()
                    out_covered = out_wh.filtered(lambda l: l.id in _psl_ids)
                    out_excluded = out_wh - out_covered
                    if out_covered:
                        infos.append((WARN,
                            "<b>%d ubicación(es) activa(s) FUERA del almacén '%s'</b> pero incluidas en "
                            "<i>Publish Stock location</i> — se usarán en el cálculo:<br/>%s"
                            % (len(out_covered), html_escape(wh.name),
                               "<br/>".join("&nbsp;&nbsp;• " + html_escape(l.complete_name) for l in out_covered))))
                    if out_excluded:
                        issues.append((WARN,
                            "<b>%d ubicación(es) activa(s) FUERA del almacén '%s'</b> y NO en "
                            "<i>Publish Stock location</i> — se excluirán del cálculo:<br/>%s"
                            % (len(out_excluded), html_escape(wh.name),
                               "<br/>".join("&nbsp;&nbsp;• " + html_escape(l.complete_name) for l in out_excluded))))

            elif non_full_active and not wh and not loc_to_post:
                # Activas pero sin almacén → se suman todas
                issues.append((WARN,
                    "Hay <b>%d ubicación(es)</b> activa(s) sin almacén configurado. "
                    "Si pertenecen a distintos almacenes, el stock se suma (posible sobrestock en ML):<br/>%s"
                    % (len(non_full_active),
                       "<br/>".join("&nbsp;&nbsp;• " + html_escape(l.complete_name) for l in non_full_active))))
            elif non_full_active:
                for l in non_full_active:
                    infos.append((OK, "&nbsp;&nbsp;• %s" % html_escape(l.complete_name)))

        # ── 4. Configuración FULL (fulfillment) ───────────────────────────────
        wh_full  = config.mercadolibre_stock_warehouse_full
        loc_full = config.mercadolibre_stock_location_to_post_full

        if wh_full:
            infos.append((OK, "Almacén FULL: <b>%s</b>" % html_escape(wh_full.name)))
        if loc_full:
            infos.append((OK, "Ubicación FULL directa: <b>%s</b>" % html_escape(loc_full.complete_name)))
        if full_active:
            infos.append((OK, "Ubicaciones FULL activas: %s"
                          % ", ".join(html_escape(l.complete_name) for l in full_active)))
        if not wh_full and not loc_full and not full_active:
            infos.append((OK, "Sin configuración FULL (normal si no se usan publicaciones fulfillment)"))

        # ── 5. Multi-ubicación explícita ──────────────────────────────────────
        multi_locs = hasattr(config, 'mercadolibre_stock_location_to_post_many') and config.mercadolibre_stock_location_to_post_many
        if multi_locs:
            infos.append((OK, "Multi-ubicación configurada (<i>mercadolibre_stock_location_to_post_many</i>): <b>%d</b> ubicación(es)" % len(multi_locs)))
            for l in multi_locs:
                infos.append((OK, "&nbsp;&nbsp;• %s (logistic: %s)"
                              % (html_escape(l.complete_name), html_escape(l.mercadolibre_logistic_type or 'estándar'))))

        # ── 6. Consistencia modo multi-warehouse ──────────────────────────────
        if mode in ('auto', 'user_product', 'user_product_type'):
            account = config.accounts and config.accounts[0]
            is_mw = account and getattr(account, 'multiwarehouse', False)
            if not is_mw:
                issues.append((WARN,
                    "Modo '<b>%s</b>' configurado pero el vendedor no está marcado como "
                    "multi-almacén en ML. Verificar con botón 'Check Multiwarehouse'." % html_escape(mode)))
            else:
                infos.append((OK, "Vendedor confirmado como multi-warehouse en ML"))

        # ── 7. Consistencia: sin nada configurado ─────────────────────────────
        nada = (not wh and not loc_to_post and not active_locs and not multi_locs)
        if nada:
            issues.append((ERR, "Configuración vacía: no hay almacén, ubicación directa ni ubicaciones activas. "
                           "El stock <b>no se actualizará</b> en ML."))

        # ── 8. Publicaciones con poco movimiento / pausadas ────────────────────
        accounts = config.accounts
        if accounts:
            MeliProd = self.env['mercadolibre.product']
            threshold_days = 30
            threshold_date = fields.Datetime.now() - timedelta(days=threshold_days)

            # Contar por estado (consulta eficiente con read_group)
            status_counts = {}
            groups = MeliProd.read_group(
                domain=[('connection_account', 'in', accounts.ids)],
                fields=['meli_last_status'],
                groupby=['meli_last_status'],
            )
            total_pubs = 0
            for g in groups:
                s = g['meli_last_status'] or 'desconocido'
                c = g['meli_last_status_count']
                status_counts[s] = c
                total_pubs += c

            if total_pubs > 0:
                status_str = ", ".join(
                    "<b>%s</b>: %d" % (html_escape(s), c)
                    for s, c in sorted(status_counts.items(), key=lambda x: -x[1])
                )
                infos.append((OK, "Publicaciones totales: <b>%d</b> — por estado: %s" % (total_pubs, status_str)))

                # Pausadas con stock Odoo > 0 (potencial pérdida de ventas)
                paused_with_stock = MeliProd.search([
                    ('connection_account', 'in', accounts.ids),
                    ('meli_last_status', '=', 'paused'),
                    ('meli_available_quantity', '>', 0),
                ], limit=11)
                if paused_with_stock:
                    shown = paused_with_stock[:10]
                    detail = "<br/>".join(
                        "&nbsp;&nbsp;• <b>%s</b> — %s — stock Odoo: %d uds" % (
                            html_escape(p.meli_id or p.conn_id or '?'),
                            html_escape((p.product_id.display_name if p.product_id else p.name or '')[:60]),
                            p.meli_available_quantity,
                        ) for p in shown
                    )
                    if len(paused_with_stock) > 10:
                        detail += "<br/>&nbsp;&nbsp;<i>... y más. Filtrar por estado=Pausado en Publicaciones ML.</i>"
                    issues.append((ERR,
                        "<b>%d publicación(es) PAUSADA(S) con stock disponible en Odoo</b> — "
                        "posible pérdida de ventas activa:<br/>%s" % (len(shown), detail)))

                # Pausadas sin movimiento reciente (olvidadas)
                stale_paused_count = MeliProd.search_count([
                    ('connection_account', 'in', accounts.ids),
                    ('meli_last_status', '=', 'paused'),
                    '|',
                    ('meli_stock_moves_update', '=', False),
                    ('meli_stock_moves_update', '<', threshold_date),
                ])
                if stale_paused_count:
                    issues.append((WARN,
                        "<b>%d publicación(es) pausada(s)</b> sin movimiento de stock "
                        "en los últimos %d días — revisar si corresponde reactivar" % (stale_paused_count, threshold_days)))

                # Activas sin movimiento reciente (posible desincronización)
                stale_active_count = MeliProd.search_count([
                    ('connection_account', 'in', accounts.ids),
                    ('meli_last_status', '=', 'active'),
                    ('meli_stock_moves_update', '!=', False),
                    ('meli_stock_moves_update', '<', threshold_date),
                ])
                if stale_active_count:
                    infos.append((WARN,
                        "<b>%d publicación(es) activa(s)</b> sin movimiento de stock "
                        "en los últimos %d días — stock podría estar desincronizado con ML" % (stale_active_count, threshold_days)))

                # Activas con quantity = 0 en Odoo (pueden pausarse automáticamente)
                active_zero_count = MeliProd.search_count([
                    ('connection_account', 'in', accounts.ids),
                    ('meli_last_status', '=', 'active'),
                    ('meli_available_quantity', '=', 0),
                ])
                if active_zero_count:
                    issues.append((WARN,
                        "<b>%d publicación(es) activa(s) con stock = 0</b> según Odoo — "
                        "ML puede pausarlas si el cron actualiza stock" % active_zero_count))
            else:
                infos.append((OK, "Sin publicaciones registradas para esta configuración"))

        # ── Build HTML report ─────────────────────────────────────────────────
        n_issues = len(issues)
        if n_issues == 0:
            status_icon = OK
            status_text = "Sin problemas detectados"
            notif_type  = "success"
        else:
            status_icon = WARN
            status_text = "%d problema(s) detectado(s)" % n_issues
            notif_type  = "warning"

        lines = [
            "<div style='font-family:monospace;font-size:13px'>",
            "<h3>%s Diagnóstico de Configuración de Stock — %s</h3>" % (status_icon, html_escape(status_text)),
            "<b>Empresa:</b> %s &nbsp;|&nbsp; <b>Config:</b> %s<br/><br/>"
            % (html_escape(company.name), html_escape(config.name or str(config.id))),
            "<b>Información:</b><ul>",
        ]
        for icon, text in infos:
            lines.append("<li>%s %s</li>" % (icon, text))
        lines.append("</ul>")

        if issues:
            lines.append("<b>Problemas / Advertencias:</b><ul>")
            for icon, text in issues:
                lines.append("<li>%s %s</li>" % (icon, text))
            lines.append("</ul>")

        lines.append("</div>")
        body = "".join(lines)

        self.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Diagnóstico de Stock',
                'message': "%s %s — Ver chatter para el reporte completo." % (status_icon, status_text),
                'type': notif_type,
                'sticky': n_issues > 0,
            },
        }

class meli_oerp_sku_rule(models.Model):

    _inherit = "meli_oerp.sku.rule"
    
    configuration_id = fields.Many2one("mercadolibre.configuration",string="Account configuration",index=True)
