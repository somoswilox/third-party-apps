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

    # 26.351 (#caso-K68): mensaje postventa editable por cuenta (botones «Mensaje Postventa» de la orden ML)
    mercadolibre_post_sale_message = fields.Text(
        string="Mensaje postventa",
        help="Texto que mandan al comprador los botones «Mensaje Postventa» de la orden de Mercado Libre "
             "(opción «enviar liga de factura» de ML). Comodines: {BUYER} nombre del comprador (si ML no lo "
             "comparte se quita, p.ej. «¡Hola, {BUYER}!» queda «¡Hola!»), {LINK} liga de facturación, "
             "{ORDERID} número de la venta, {ORDERAMOUNT} importe. Vacío: el botón simple sólo consulta "
             "y el de autofactura usa el mensaje de autofacturación.")
    mercadolibre_post_sale_link_field = fields.Char(
        string="Campo de la liga de facturación",
        help="Nombre técnico del campo de la venta (sale.order) que tiene la liga de facturación propia de "
             "cada orden, p.ej. autoinvoice_url. Se usa en {LINK}; si en una venta viene vacío, el mensaje "
             "NO se envía. Vacío: {LINK} = <url del sitio>/AUTOFACTURA/register (módulo de autofacturación).")

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

    connection_account = fields.Many2one("mercadolibre.account",compute=_connection_account, store=True, index='btree_not_null')
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

    # Politica de facturacion de los productos que CREA el conector. Ver el mismo campo
    # en res.company (meli_oerp): aca manda la configuracion de la cuenta, y si esta
    # vacia se cae a la de la compania. Vacio en las dos = comportamiento de siempre.
    mercadolibre_product_invoice_policy = fields.Selection(
        [('order', 'Cantidad pedida'), ('delivery', 'Cantidad entregada')],
        string='Politica de facturacion de productos nuevos',
        help='Politica de facturacion con la que nacen los productos que crea el '
             'conector de MercadoLibre. Vacio = heredar de la compania, y si la '
             'compania tampoco lo define, usar el valor por defecto de Odoo.')

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
    # un caso - Gemelos de los campos de meli_oerp_accounting/res.company (red de seguridad
    # de re-facturacion). ⚠️ Los defaults DEBEN coincidir con los de alla: en multi-cuenta
    # la config EFECTIVA es esta (`mercadolibre.configuration`), no `res.company`
    # (bug del un caso: defaults distintos = la opcion queda apagada sin que se note).
    mercadolibre_invoice_requeue = fields.Boolean(
        string="Reintentar facturas que fallaron",
        default=True,
        help="Barrido periodico que vuelve a intentar emitir la factura de las ventas de "
             "MercadoLibre pagadas que quedaron sin factura posteada (rechazo de ARCA, "
             "webservice caido, tipo de documento faltante...). Requiere ademas que el cron "
             "'MELI: reintentar facturas que quedaron sin emitir' este activo.")
    mercadolibre_invoice_requeue_days = fields.Integer(
        string="Dias hacia atras (reintento de factura)",
        default=30,
        help="Ventana en dias (por fecha del pedido) de ventas a considerar en el barrido "
             "de re-facturacion.")
    mercadolibre_invoice_requeue_limit = fields.Integer(
        string="Max ventas por ciclo (reintento de factura)",
        default=20,
        help="Tope de ventas a re-facturar por ciclo del cron, para acotar el uso del "
             "webservice fiscal y el tiempo del cron.")
    mercadolibre_invoice_requeue_max_retries = fields.Integer(
        string="Max reintentos por venta (factura)",
        default=8,
        help="Cuantas veces se reintenta emitir la factura de una misma venta antes de "
             "marcarla como TRABADA, avisar por actividad y dejar de tocarla.")

    mercadolibre_cron_get_orders_shipment = fields.Boolean(string='Importar envíos',help='Cron Get Orders Shipment')
    mercadolibre_including_shipping_cost = fields.Selection(string="Incluir envio en pedido y factura", selection=[('always','Siempre'),('never','Nunca')],default='always')
    mercadolibre_shipping_cost_as_purchase_price = fields.Boolean(
        string="Imputar el flete como coste del envio",
        help="Activado (default, comportamiento historico): la linea de envio lleva como coste "
             "el flete que MercadoLibre le cobra al vendedor, y el margen del pedido lo descuenta.\n"
             "Desactivado: la linea de envio se sigue creando y facturando igual, pero sin coste, "
             "y el margen del pedido no descuenta el flete. Util para comparar el margen contra "
             "cuentas que tienen 'Incluir envio en pedido y factura' en Nunca (sin linea de envio).\n"
             "Solo afecta el COSTE (margen); no cambia nada de lo que se factura.",
        default=True)
    mercadolibre_use_payment_shipping_amount = fields.Boolean(string="Usar Monto de envío de Pagos",help="El monto del envio puede variar, en el objeto de envio tenemos el shippig_cost y en los pagos el shipping amount.",default=True)
    # ------------------------------------------------------------------ #
    #  OLA 2 del mapeo de cancelaciones -- el eje MERCADERIA.              #
    #  GEMELO de meli_oerp/models/company.py. El default DEBE ser el mismo #
    #  en los DOS modelos: cuando hay cuenta de conexion, el _get_config() #
    #  de meli_oerp devuelve ESTA `mercadolibre.configuration`, no         #
    #  res.company, y un campo que solo existe alla cae al                 #
    #  `in config._fields` -> False y la opcion queda APAGADA EN SILENCIO  #
    #  (bug del un caso; y otra vez el un caso en un cliente, 24-sep-2026).          #
    #  Si se toca el default de un lado, se toca el del otro.              #
    # ------------------------------------------------------------------ #
    mercadolibre_return_mode = fields.Selection([
        ("none", "No crear devolucion"),
        ("draft", "Crear sin validar (queda reservada)"),
        ("done", "Crear y validar (el stock vuelve)"),
    ], string="Devolucion de mercaderia al cancelar pedido",
       default="done",
       help="Que hacer con la mercaderia ya entregada cuando MercadoLibre cancela un pedido:\n"
            "- No crear devolucion: no se toca el stock, se gestiona a mano.\n"
            "- Crear sin validar: genera el albaran de devolucion reservado. OJO: al cancelar "
            "la orden, Odoo cancela los albaranes que no esten en Hecho, asi que esa devolucion "
            "queda cancelada y el stock NO vuelve.\n"
            "- Crear y validar (por defecto): genera el albaran de devolucion y lo valida ANTES "
            "de cancelar la orden, de modo que el stock vuelve al deposito y la devolucion "
            "sobrevive a la cancelacion.\n\n"
            "No aplica a los envios FULL, donde el stock vive en el fulfillment de MercadoLibre: "
            "esos albaranes se saltean solos por no tener cantidades que devolver.")

    # Cancelaciones decididas con la FOTO FRESCA de ML (29-sep-2026, un frente).
    # GEMELO de meli_oerp/models/company.py: MISMO default ('legacy') en los dos modelos.
    # Con cuenta de conexion la config EFECTIVA es esta (bug del un caso): si el campo solo
    # viviera en res.company, el modo quedaria en 'legacy' EN SILENCIO para toda cuenta.
    mercadolibre_cancel_mode = fields.Selection([
        ("legacy", "Según configuración (histórico)"),
        ("por_estado_ml", "Según el estado actualizado de ML (orden, pagos y envío)"),
    ], string="Decisión al cancelar pedido",
       default="legacy",
       help="Cómo se decide qué hacer cuando MercadoLibre cancela un pedido de esta cuenta. "
            "'Según el estado actualizado de ML' consulta la orden, los pagos y el envío ANTES "
            "de accionar: devuelve la mercadería si el envío nunca salió o volvió, ESPERA si está "
            "en tránsito, no mueve stock si se entregó o es FULL, y emite la nota de crédito por "
            "lo reintegrado. Ver la ayuda del mismo campo en la compañía.")

    # Venta ML sin existencia al confirmar (un caso, un cliente, 30-sep-2026).
    # GEMELO de meli_oerp/models/company.py: MISMO default (confirm) en los dos modelos.
    # Con cuenta de conexion la config EFECTIVA es esta (bug del un caso).
    mercadolibre_order_confirm_no_stock_mode = fields.Selection([
        ("confirm", "Confirmar; si el abastecimiento falla, queda en cotización"),
        ("waiting", "Confirmar siempre: la salida queda en espera de existencia"),
        ("quotation", "No confirmar sin existencia: queda en cotización hasta que haya"),
    ], string="Venta sin existencia al confirmar",
       default="confirm",
       help="Qué hacer al confirmar una venta de MercadoLibre cuando algún producto no tiene "
            "existencia libre en el almacén de la venta:\n"
            "- Confirmar; si el abastecimiento falla, queda en cotización (por defecto): se "
            "confirma como siempre. Si Odoo no puede abastecerla (p. ej. la ruta intenta COMPRAR "
            "y el producto no tiene un precio de proveedor válido), la venta queda como "
            "cotización con un aviso que nombra el producto.\n"
            "- Confirmar siempre, la salida queda en espera: la venta se confirma y el albarán de "
            "salida se crea en 'En espera' aunque no haya existencia. Si el producto tiene "
            "proveedor, se genera la compra como siempre; si no se puede generar la compra (sin "
            "precio de proveedor), la salida igual se crea en espera y se avisa UNA vez en la "
            "venta qué productos no se pudieron comprar.\n"
            "- No confirmar sin existencia: la venta queda en cotización con un aviso de los "
            "productos y las cantidades que faltan, y se confirma sola en la próxima "
            "sincronización cuando haya existencia en el almacén de la venta.\n"
            "Los servicios, los consumibles sin control de inventario y los productos de "
            "triangulación (dropship o referencia DSTR_) no se consideran.")

    # 26.171 (E2, un cliente): "Cancelaciones automáticas desde".
    # GEMELO de meli_oerp/models/company.py: MISMO default (vacío) en los dos modelos.
    # Con cuenta de conexion la config EFECTIVA es esta (bug del un caso).
    mercadolibre_cancel_auto_from = fields.Datetime(
       string="Cancelaciones automáticas desde",
       help="Fecha y hora desde la que las cancelaciones de MercadoLibre se procesan "
            "automáticamente (devolución, factura y cancelación de la venta, según 'Devolución "
            "de mercadería al cancelar pedido' y 'Decisión al cancelar pedido').\n"
            "Un pedido que ML canceló ANTES de esta fecha no se toca: queda retenido, marcado "
            "'ML Cancelación retenida' y visible en los filtros 'MercadoLibre Cancelaciones "
            "retenidas' y 'MercadoLibre Canceladas pendientes en Odoo', para tratarlo a mano. "
            "Se compara con la fecha de cancelación que informa ML; si no se tiene, con la fecha "
            "de la venta.\n"
            "Vacío (por defecto): se procesan todas, como hasta ahora.")

    # [caso de un cliente] Campo gemelo del de meli_oerp/models/company.py.
    # ⚠️ El default DEBE ser el mismo en los dos modelos: en multi-cuenta la config
    # EFECTIVA es esta (`mercadolibre.configuration`), no `res.company`. Declararlos
    # con defaults distintos fue el bug del un caso (`mercadolibre_billing_force_on_main`:
    # True en company / False acá → la opción quedaba apagada sin que se notara).
    mercadolibre_protect_invoiced_orders = fields.Boolean(
        string="No modificar pedidos ya facturados",
        default=True,
        help="Si el pedido ya tiene una factura POSTEADA, el conector no reescribe sus líneas "
             "ni sus montos (en particular la línea de envío): deja el pedido como está y avisa "
             "en el chatter que encontró una diferencia. Evita que el pedido quede por debajo "
             "de lo que se facturó. Desactivar solo si se necesita el comportamiento anterior.",
    )


    mercadolibre_cron_get_orders_shipment_client = fields.Boolean(string='Importar clientes',help='Cron Get Orders Shipment Client')
    mercadolibre_cron_get_orders_client_set_company = fields.Boolean(string='Asociar Empresa',help='Asociar el cliente siempre a la empresa de la cuenta',default=True)
    mercadolibre_cron_get_questions = fields.Boolean(string='Importar preguntas',help='Cron Get Questions')
    mercadolibre_cron_get_update_products = fields.Boolean(string='Actualizar productos en Odoo',help='Cron Update Products already imported')

    mercadolibre_cron_post_update_products = fields.Boolean(string='Actualizar productos en ML',help='Cron Update Posted Products, Product Templates or Variants with Meli Publication field checked')
    mercadolibre_cron_post_update_stock = fields.Boolean(string='Publicar Stock',help='Cron Post Updated Stock')
    mercadolibre_stock_diag_reactivate = fields.Selection(
        [('all', 'Todas (comportamiento anterior)'),
         ('out_of_stock', 'Sólo las pausadas por falta de stock'),
         ('never', 'Nunca')],
        string='Diagnóstico: reactivar pausadas', default='all',
        help="Qué hace el diagnóstico de stock con una publicación PAUSADA en MercadoLibre que tiene stock en Odoo. "
             "'Todas' la reactiva siempre (también una pausa hecha a mano). "
             "'Sólo falta de stock' la reactiva sólo si ML la pausó por quedarse sin stock. 'Nunca' no la toca.")
    mercadolibre_shipment_print_guide = fields.Boolean(string='Imprimir etiquetas',help='Imprimir etiquetas')
    # ── Reintento de etiquetas (un caso) ────────────────────────────────────────────
    # El envio se consulta UNA sola vez, al importar/confirmar la orden. Si Mercado
    # Libre publica la etiqueta despues (lo normal en ME2/colecta: de 8 a 50 h
    # despues), nada vuelve a mirar esa orden: el cron de ordenes solo repasa las
    # `mercadolibre_cron_orders_limit` mas nuevas y ML no notifica el topic
    # `shipments`. La etiqueta queda sin bajar hasta que alguien actualiza la orden
    # a mano. Estos parametros gobiernan el cron que vuelve a consultarlas.
    # Solo actua si `mercadolibre_shipment_print_guide` esta activo: si la cuenta no
    # pidio que bajemos las etiquetas, el cron no hace nada.
    mercadolibre_cron_shipment_label_retry = fields.Boolean(
        string='Reintentar etiquetas pendientes',
        help="Vuelve a consultar los envios que quedaron sin etiqueta y la baja apenas "
             "Mercado Libre la publica. Requiere 'Imprimir etiquetas' activo.",
        default=True)
    mercadolibre_cron_shipment_label_retry_days = fields.Integer(
        string='Dias hacia atras (etiquetas)',
        help="Cuantos dias hacia atras se revisan los envios sin etiqueta. Default: 3",
        default=3)
    mercadolibre_cron_shipment_label_retry_limit = fields.Integer(
        string='Envios por corrida (etiquetas)',
        help="Maximo de envios a re-consultar por ejecucion del cron. Acota el gasto de "
             "llamadas a la API por corrida. Default: 50",
        default=50)
    mercadolibre_cron_shipment_label_retry_max = fields.Integer(
        string='Reintentos maximos por envio (etiquetas)',
        help="Tope de reintentos por envio. Evita re-consultar para siempre un envio que "
             "nunca va a tener etiqueta (retiro en sucursal, flex, cancelado). Default: 20",
        default=20)
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
    # 26.352 (caso-K21 C): de dónde sale el «Fabricante» (MANUFACTURER) cuando no está cargado.
    mercadolibre_manufacturer_source = fields.Selection([('supplier', 'Proveedor principal'), ('brand', 'Marca')],
        string='Fabricante desde', default='supplier',
        help='Si el producto no tiene el atributo Fabricante, se completa con el proveedor principal de la '
             'compra (sin S.A./S.R.L.) o con la Marca. Sin proveedor, se usa la Marca.')
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

    mercadolibre_mx_cfdi_override_default = fields.Boolean(
        string="México: corregir régimen/uso CFDI por defecto (601/G03) con el dato de ML",
        default=False,
        help="Sólo MercadoLibre México con l10n_mx_edi. Odoo crea los contactos con régimen fiscal 601 "
             "(y uso de CFDI G03) por defecto, así que una persona física (612) o público en general (616) "
             "ya cargados quedan con un régimen que no es el suyo. Prendida: si el contacto tiene 601 (o G03) "
             "y MercadoLibre informa otro código válido, se escribe el de ML. Nunca pisa un valor distinto "
             "(carga manual) ni contactos bloqueados para MercadoLibre. Apagada (por defecto): sólo se completan "
             "campos vacíos.",
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

    # 26.87 (F1d) — RED DE SEGURIDAD del sincronizado de stock.
    #
    # La cola de publicacion es event-driven: un binding entra solo cuando
    # meli_stock_moves_update > stock_update (ver mercadolibre.product
    # _meli_stock_status). Ese sello se deriva de stock_move, y ningun esquema
    # derivado puede GARANTIZAR que no se pierda un evento — de hecho se perdian
    # todos los que no creaban una fila nueva de movimiento (bug corregido en F1).
    #
    # Este parametro cierra el agujero por abajo: cualquier publicacion cuyo
    # ultimo push sea mas viejo que N dias vuelve a la cola, haya o no habido
    # movimientos. Es el equivalente a un "full resync" amortizado.
    # 0 = desactivado (comportamiento anterior a 26.87).
    mercadolibre_stock_resync_days = fields.Integer(
        string="Resincronizar stock cada (días)",
        default=7,
        help="Red de seguridad del sincronizado de stock.\n"
             "Toda publicación cuyo último envío de stock a MercadoLibre sea más "
             "antiguo que esta cantidad de días vuelve a la cola de publicación, "
             "aunque no haya habido movimientos de stock.\n"
             "Sirve para que un evento perdido (o un producto cuyo stock cambió "
             "sin generar movimiento) no quede desincronizado para siempre.\n"
             "Recomendado: 7. Poner 0 desactiva la red de seguridad.")

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
    # (F8b 20.0) borrado el REMANENTE de ese cuerpo, que habia quedado colgado de `copy_from_configuration`
    # (despues de su `pass;`): sin `def` propio, usaba `config`/`company` sin definir (21 undefined-variable) y
    # nadie llama a `copy_from_configuration`. La version viva esta en connection_account.py.


class meli_oerp_sku_rule(models.Model):

    _inherit = "meli_oerp.sku.rule"
    
    configuration_id = fields.Many2one("mercadolibre.configuration",string="Account configuration",index=True)
