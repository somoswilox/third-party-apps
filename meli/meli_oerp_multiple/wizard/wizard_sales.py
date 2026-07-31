# -*- coding: utf-8 -*-

from odoo import api, models, fields, api, _

from odoo.exceptions import UserError
from odoo.exceptions import ValidationError

from odoo.addons.meli_oerp_multiple.models.warning import warning
from odoo.addons.meli_oerp.models.versions import *

from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import base64
import json

import logging
_logger = logging.getLogger(__name__)

try:
    # psycopg2 (older) vs psycopg (newer) compatibility for unique violations
    from psycopg2 import IntegrityError
except Exception:  # pragma: no cover
    try:
        from psycopg.errors import UniqueViolation as IntegrityError
    except Exception:
        IntegrityError = Exception  # fallback

class mercadolibre_orders_import(models.TransientModel):

    _name = "mercadolibre.orders.import"
    _description = "Wizard de Orders Import ML"

    title = fields.Char(string="Title", size=100, readonly=True)
    order_state = fields.Selection([
                ('all','Todos'),
                ('paid','Pagadas'),
                ('cancelled','Canceladas')], 
                default='all', 
                string='Filtrar ventas por estado',
                help='Estado de venta a importar (todos, pagadas o canceladas)' )

    order_date_block = fields.Datetime("Block Date",help="Fecha a partir de la cual no se bloquean las entradas de pedidos desde ML")
    order_date_from = fields.Datetime( string="Importar desde", help="Fecha inicial para la importacion de pedidos (vacio: ultimas 50)")
    order_date_to = fields.Datetime( string="Hasta", help="Fecha final para la importacion de pedidos (vacio: el dia de hoy)")

    nro_venta = fields.Char(string="Número de venta")

    date_preset = fields.Selection([
        ('1d', 'Último día'),
        ('3d', 'Últimos 3 días'),
        ('1w', 'Última semana'),
        ('1m', 'Último mes'),
    ], string="Rango rápido")

    @api.onchange('date_preset')
    def _onchange_date_preset(self):
        if not self.date_preset:
            return
        now = fields.Datetime.now()
        presets = {
            '1d': relativedelta(days=1),
            '3d': relativedelta(days=3),
            '1w': relativedelta(weeks=1),
            '1m': relativedelta(months=1),
        }
        self.order_date_from = now - presets[self.date_preset]
        self.order_date_to = now
    order_id = fields.Char(string="Buscar order id", help="Buscar pedido por order id (de producto)")
    pack_id = fields.Char(string="Buscar pack id", help="Buscar pedido por numero de carrito, pack id")

    _req_name = 'title'

    batch_processing_unit = fields.Integer(string="Numero de lotes a procesar por iteracion (0 - 100)", default=50 )
    batch_processing_unit_offset = fields.Integer(string="Offset", default=0 )
    batch_processing_status = fields.Char(string="Status proceso por lotes")
    batch_processing = fields.Boolean(string="Batch Processing Active",default=False)

    batch_sales_to_sync = fields.Boolean(string="Process Sales To Sync",default=False)
    skip_stock_update = fields.Boolean(string="Omitir actualización de stock MeLi", default=False,
        help="Si está activado, no actualiza el stock en MercadoLibre durante la importación de órdenes. Útil para evitar errores de serialización en importaciones masivas.")
    import_lines = fields.One2many('mercadolibre.orders.import.line','import_id',string="Import lines")
    import_lines_processed = fields.One2many(
        'mercadolibre.orders.import.line', 'import_id',
        string="Ventas procesadas",
        domain=[('import_status', 'in', ['imported', 'warning'])],
    )
    # Ventas ML del período YA importadas (tienen sale.order) que NO están listas
    # para confirmar: producto faltante, total $0, o total que no coincide. Se
    # detectan con mercadolibre.orders.meli_confirm_ready (read-only).
    import_lines_incomplete = fields.One2many(
        'mercadolibre.orders.import.line', 'import_id',
        string="Ventas incompletas",
        domain=[('import_status', '=', 'warning')],
    )
    import_ok_count = fields.Integer(compute='_compute_import_counts')
    import_warning_count = fields.Integer(compute='_compute_import_counts')
    import_error_count = fields.Integer(compute='_compute_import_counts')
    import_incomplete_count = fields.Integer(compute='_compute_import_counts')

    @api.depends('import_lines.import_status')
    def _compute_import_counts(self):
        for rec in self:
            lines = rec.import_lines
            rec.import_ok_count = len(lines.filtered(lambda l: l.import_status == 'imported'))
            rec.import_warning_count = len(lines.filtered(lambda l: l.import_status == 'warning'))
            rec.import_error_count = len(lines.filtered(lambda l: l.import_status == 'error'))
            # "Incompletas" = warning (mismo dominio que import_lines_incomplete).
            rec.import_incomplete_count = len(lines.filtered(lambda l: l.import_status == 'warning'))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Prefill "Block Date" (order_date_block) from the MeLi
        # configuration so users don't have to re-type it every time the
        # wizard opens. The action binds to mercadolibre.account, so
        # active_ids points to the account(s) whose configuration we want.
        if 'order_date_block' in fields_list and not res.get('order_date_block'):
            active_model = self.env.context.get('active_model')
            active_ids = self.env.context.get('active_ids') or []
            account = self.env['mercadolibre.account']
            if active_model == 'mercadolibre.account' and active_ids:
                account = account.browse(active_ids)
            company = (account and account[:1].company_id) or self.env.company
            config = (account and account[:1].configuration) or company
            block_dt = False
            if config and 'mercadolibre_filter_order_datetime_start' in config._fields:
                block_dt = config.mercadolibre_filter_order_datetime_start
            if not block_dt and company and 'mercadolibre_filter_order_datetime_start' in company._fields:
                block_dt = company.mercadolibre_filter_order_datetime_start
            if block_dt:
                res['order_date_block'] = block_dt
        return res

    def _calculate_sync_status( self ):
        _logger.info('_calculate_sync_status batch_processing_status: ' + str(self.batch_processing_status))
        sync_status = self.check_sync_status()

        for imp in self:
            report_import_link = str('report_import_link' in sync_status and str(sync_status['report_import_link']))
            _logger.info('_calculate_sync_status: ' + str(imp)+" sync_status:"+report_import_link)
            imp.batch_processing_status = "processed"
            imp.import_status = "Idle "+str(report_import_link)
            imp.batch_sales_to_sync = str(0)
            imp.report_import_link =  ""
            imp.sales_to_sync = str(0)
            imp.sales_left_number = ("sales_left_number" in sync_status and sync_status["sales_left_number"]) or 0
            imp.sales_total_number = ("sales_total_number" in sync_status and sync_status["sales_total_number"]) or 0

            if "sales_to_sync" in sync_status:
                imp.sales_to_sync = str(sync_status['sales_to_sync'])
                #imp.report_import = 'report_import' in sync_status and sync_status['report_import'] and sync_status['report_import'].id
                _logger.info('_calculate_sync_status: imp.report_import > ' + str(imp.report_import))
                if imp.report_import:
                    imp.report_import_link = 'report_import_link' in sync_status and str(sync_status['report_import_link'])
                    _logger.info('_calculate_sync_status: imp.report_import_link > ' + str(imp.report_import_link))

        return sync_status

    def _scan_incomplete_sales(self, target=None, context=None):
        """Escanea las ventas ML del período [order_date_from, order_date_to] de la
        cuenta activa que YA fueron importadas (tienen sale.order) y NO están listas
        para confirmar, y crea líneas import_status='warning' en `target` (el wizard
        recién creado por show_import_wizard).

        Es READ-ONLY respecto de los datos del cliente: NO confirma ni modifica las
        ventas; sólo las lista. El criterio de "no lista" es el helper compartido
        mercadolibre.orders.meli_confirm_ready (misma matemática que confirm_ml).
        """
        context = context or self.env.context
        target = target or self
        account_ids = context.get('active_ids') or []
        if not account_ids:
            return 0
        account = self.env['mercadolibre.account'].browse(account_ids)
        company = (account and account.company_id) or self.env.user.company_id
        config = (account and account.configuration) or company
        if not self.order_date_from or not self.order_date_to:
            return 0

        # Órdenes ML del período (por fecha de cierre) de esta cuenta, con sale.order
        # y NO canceladas. La detección de "incompleta" se hace con el helper.
        domain = [
            ('connection_account', '=', account.id),
            ('sale_order', '!=', False),
            ('status', '!=', 'cancelled'),
            ('date_closed', '>=', self.order_date_from),
            ('date_closed', '<=', self.order_date_to),
        ]
        ml_orders = self.env['mercadolibre.orders'].search(domain, order='date_closed desc')
        meli = None
        line_obj = self.env['mercadolibre.orders.import.line']
        # IDs de órdenes que ya tienen una línea (evitar duplicar con las del flujo
        # de importación que quedaron en warning por "sin sale.order").
        existing_order_ids = set(target.import_lines.mapped('order_id'))
        created = 0
        for ml in ml_orders:
            try:
                ready, reason = ml.meli_confirm_ready(meli=meli, config=config)
            except Exception as e:
                _logger.error("scan incompletas: error evaluando orden %s: %s", ml.order_id, str(e))
                ready, reason = False, "No se pudo evaluar (%s)" % str(e)
            if ready:
                continue
            if ml.order_id and ml.order_id in existing_order_ids:
                # Ya hay una línea para esta orden: actualizarla a warning con el motivo.
                existing = target.import_lines.filtered(lambda l, oid=ml.order_id: l.order_id == oid)[:1]
                if existing:
                    existing.write({
                        'import_status': 'warning',
                        'error': reason,
                        'meli_order': ml.id,
                        'sale_order': ml.sale_order.id,
                    })
                continue
            buyer_name = (ml.buyer and ml.buyer.name) or ml.seller or ""
            line_obj.create({
                'import_id': target.id,
                'name': str("Venta #") + str(ml.pack_id or ml.order_id or ""),
                'order_id': ml.order_id or "",
                'pack_id': ml.pack_id or "",
                'paid_amount': ml.paid_amount or 0.0,
                'buyer': buyer_name,
                'status': ml.status or "",
                'date_closed': ml.date_closed,
                'error': reason,
                'import_status': 'warning',
                'meli_order': ml.id,
                'sale_order': ml.sale_order.id,
            })
            if ml.order_id:
                existing_order_ids.add(ml.order_id)
            created += 1
        _logger.info("scan incompletas: %s ventas incompletas en el período (cuenta %s)", created, account.id)
        return created

    sales_to_sync = fields.Char(string="Sales to sync")

    sales_left_number = fields.Float(string="Sales Left",default=0)
    sales_total_number = fields.Float(string="Sales Total",default=0)

    report_import_link = fields.Char(string="Report Link")
    import_status = fields.Char(string="Import Status")

    report_import = fields.Many2one( "ir.attachment",string="Reporte Importación")

    def pretty_json( self, data ):
        return json.dumps( data, sort_keys=False, indent=4 )

    def check_sync_status(self, context=None, config=None, meli=None, p_sales_to_sync=None, offset=0):
        context = context or self.env.context
        n_sales_to_sync = list(p_sales_to_sync or [])

        #_logger.info(
        #    "check_sync_status: %s offset:%s self.batch_processing_status:%s n_sales_to_sync:%s",
        #    str(self._context_resume(context)), str(offset), str(self.batch_processing_status), str(len(n_sales_to_sync))
        #)

        account_ids = context.get('active_ids') or []
        account = self.env['mercadolibre.account'].browse(account_ids)
        company = (account and account.company_id) or self.env.user.company_id
        config = account.configuration or company

        if not meli:
            meli = self.env['meli.util'].get_new_instance(company, account)
            if meli.need_login():
                return meli.redirect_login()

        # ----- helper: asegurar rango mínimo de 31 días (último mes aprox) -----
        def _ensure_last_month_range():
            now_utc = fields.Datetime.now()  # ya viene tz-naive (UTC en Odoo)
            to_dt = self.order_date_to or now_utc
            from_dt = self.order_date_from or (to_dt - relativedelta(days=31))
            # si el rango es menor a 31 días, expandimos hacia atrás
            if (to_dt - from_dt) < timedelta(days=31):
                from_dt = to_dt - relativedelta(days=31)
            return from_dt, to_dt

        nro_venta_raw = (self.nro_venta or "").strip()
        # ----------------------------------------------------------------------
        # FLUJO A: por nro_venta (pack_id preferente; sino order_id), en último mes
        # ----------------------------------------------------------------------
        if nro_venta_raw:
            # permitir múltiples: "123, 456 789"
            nro_list = [nv.strip() for nv in nro_venta_raw.replace(",", " ").split() if nv.strip()]

            # Asegurar rango del último mes para recorrer todo
            from_dt, to_dt = _ensure_last_month_range()

            # Guardar en el wizard para que la UI refleje el rango usado
            self.write({'order_date_from': from_dt, 'order_date_to': to_dt})

            from_str = from_dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000-00:00')
            to_str = to_dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000-00:00')

            # Recorremos el último mes paginado y filtramos por pack_id u order_id
            sales_total = 0
            local_offset = offset or 0
            encontrados = []  # acumulador de órdenes que matchean

            while True:
                orders_query = (
                    "/orders/search?seller=" + meli.seller_id +
                    "&sort=date_desc&order.status=paid" +
                    "&order.date_closed.from=" + str(from_str) +
                    "&order.date_closed.to=" + str(to_str) +
                    ("&offset=" + str(local_offset) if local_offset else "")
                )
                _logger.info("orders_query (nro_venta): %s", orders_query)
                response = meli.get(orders_query, {'access_token': meli.access_token})
                orders_json = response and response.json() or {}

                if isinstance(orders_json, dict) and "error" in orders_json:
                    _logger.error(orders_query)
                    _logger.error(orders_json.get("error"))
                    if orders_json.get("message") == "invalid_token":
                        _logger.error(orders_json["message"])
                    return {
                        'sales_to_sync': 'error: ' + str(orders_json.get("error")),
                        'sales_left_number': 0,
                        'sales_total_number': 0,
                        'order_lines': []
                    }

                # Paginación
                paging = orders_json.get("paging") or {}
                total = paging.get("total", 0)
                limit = paging.get("limit", 0)
                sales_total = total  # total del último mes
                results = orders_json.get("results") or []

                # Filtrado por nro_list (pack_id preferente; sino order_id)
                # Si pack_id coincide, puede traer varias órdenes => incluir todas
                for order_json in results:
                    oid = str(order_json.get("id") or "")
                    pack_id = order_json.get("pack_id")
                    pack_id_str = str(pack_id) if pack_id else ""
                    # ¿Coincide con alguno?
                    match = False
                    for nv in nro_list:
                        # si hay pack_id y coincide -> match inmediato
                        if pack_id_str and nv == pack_id_str:
                            match = True
                            break
                        # si no hay pack, comparar por order_id
                        if nv == oid:
                            match = True
                            break
                    if not match:
                        continue

                    # Evitar duplicados si ya lo agregamos antes en otra página
                    already = any(str(x.get("id")) == oid for x in encontrados)
                    if not already:
                        encontrados.append(order_json)

                # continuar si hay siguiente página
                if total and limit and (local_offset + limit) < total:
                    local_offset += limit
                else:
                    break

            # De los encontrados, solo agregar los que NO existen aún en Odoo
            for order_json in encontrados:
                oid = order_json.get("id")
                if not oid:
                    continue
                exists = self.env["mercadolibre.orders"].search(
                    [('order_id', '=', str(oid)), ('connection_account', '=', account.id)],
                    limit=1
                )
                if not exists:
                    n_sales_to_sync.append(order_json)

            # Adjuntos/reporte
            attachments = self.env["ir.attachment"].search([('res_id', '=', self.id)], order='id desc')
            last_attachment = attachments and attachments[0] or False
            report_import_link = ""
            if last_attachment:
                report_import_link = "/web/content/%s?download=true&access_token=%s" % (
                    str(last_attachment.id), str(last_attachment.access_token)
                )

            left = len(n_sales_to_sync)
            # OJO: sales_total es el total de órdenes en el mes (para contexto),
            # pero para dar señal clara de progreso de "lo buscado", usamos encontrados.
            result = {
                'sales_to_sync': f"{left} / {len(encontrados)}",
                'sales_left_number': left,
                'sales_total_number': len(encontrados),
                'order_lines': n_sales_to_sync
            }
            if last_attachment:
                result.update({'report_import': last_attachment, 'report_import_link': report_import_link})

            _logger.info("check_sync_status (por nro_venta, último mes) -> %s", str(self._context_resume(result)))
            return result

        # ----------------------------------------------------------------------
        # FLUJO B: original por fechas (si NO hay nro_venta)
        # ----------------------------------------------------------------------
        if not self.order_date_from or not self.order_date_to:
            return {'sales_to_sync': 'error - definir fechas'}

        if self.batch_processing_status == "processed":
            return {
                'sales_to_sync': self.sales_to_sync or 0,
                'sales_left_number': self.sales_left_number or 0,
                'sales_total_number': self.sales_total_number or 0,
            }

        from_str = self.order_date_from.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000-00:00')
        to_str = self.order_date_to.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000-00:00')

        orders_query = "/orders/search?seller=" + meli.seller_id + "&sort=date_desc"
        orders_query += "&order.status=paid"
        orders_query += "&order.date_closed.from=" + str(from_str)
        orders_query += "&order.date_closed.to=" + str(to_str)
        if offset:
            orders_query += "&offset=" + str(offset).strip()

        _logger.info("orders_query: %s", orders_query)
        response = meli.get(orders_query, {'access_token': meli.access_token})
        orders_json = response and response.json() or {}

        if isinstance(orders_json, dict) and "error" in orders_json:
            _logger.error(orders_query)
            _logger.error(orders_json.get("error"))
            if orders_json.get("message") == "invalid_token":
                _logger.error(orders_json["message"])
            return {
                'sales_to_sync': 'error: ' + str(orders_json.get("error")),
                'sales_left_number': 0,
                'sales_total_number': 0,
                'order_lines': []
            }

        sales_total = 0
        offset_next = 0
        if "paging" in orders_json:
            sales_total = orders_json["paging"].get("total", 0)
            sales_limit = orders_json["paging"].get("limit", 0)
            if sales_total == 0:
                return {}
            if sales_limit and (sales_total >= (offset + sales_limit)):
                offset_next = offset + sales_limit

        if "results" in orders_json:
            nn = offset
            _logger.info("#%s / %s", str(nn), str(sales_total))
            for order_json in orders_json["results"]:
                nn += 1
                order_id = order_json.get("id")
                if not order_id:
                    continue
                meli_order = self.env["mercadolibre.orders"].search(
                    [('order_id', '=', order_id), ('connection_account', '=', account.id)],
                    limit=1
                )
                if not meli_order:
                    n_sales_to_sync.append(order_json)

        if offset_next > 0:
            _logger.info("check_sync_status offset_next:%s n_sales_to_sync:%s", str(offset_next), str(len(n_sales_to_sync)))
            return self.check_sync_status(
                context=context, config=config, meli=meli, p_sales_to_sync=n_sales_to_sync, offset=offset_next
            )

        # Adjuntos/reporte
        attachments = self.env["ir.attachment"].search([('res_id', '=', self.id)], order='id desc')
        last_attachment = attachments and attachments[0] or False
        report_import_link = ""
        if last_attachment:
            report_import_link = "/web/content/%s?download=true&access_token=%s" % (
                str(last_attachment.id), str(last_attachment.access_token)
            )

        left = len(n_sales_to_sync)
        result = {
            'sales_to_sync': f"{left} / {sales_total}",
            'sales_left_number': left,
            'sales_total_number': sales_total,
            'order_lines': n_sales_to_sync
        }
        if last_attachment:
            result.update({'report_import': last_attachment, 'report_import_link': report_import_link})

        _logger.info("check sync status result context:%s", str(self._context_resume(result)))
        return result


    def show_import_wizard(self, context=None):
        #first fetch wizard view id
        context = context or self.env.context
        context_resume = self._context_resume( context )
        
        _logger.info("show_import_wizard:"+str(context_resume))

        refview = get_ref_view( self, "meli_oerp_multiple", 'view_orders_import')
        sync_status = context["sync_status"]
        if (sync_status and "order_lines" in sync_status):            
            self.sales_left_number = len(sync_status["order_lines"])
            self.sales_to_sync = str(int(self.sales_left_number))+"/"+str(int(self.sales_total_number))

        res_id = self.create({
            "title": "Importar",            
            "batch_processing_unit": ("batch_processing_unit" in context and context["batch_processing_unit"]) or self.batch_processing_unit,
            "batch_processing_unit_offset": ("batch_processing_unit_offset" in context and context["batch_processing_unit_offset"]) or self.batch_processing_unit_offset,
            "report_import": (self.report_import and self.report_import.id),
            "report_import_link": (self.report_import_link or ""),
            
            "batch_processing": self.batch_processing,
            "order_state": self.order_state,
            "sales_to_sync": self.sales_to_sync,
            "sales_left_number": self.sales_left_number,
            "sales_total_number": self.sales_total_number,
            "order_date_block": self.order_date_block,
            "order_date_from": self.order_date_from,
            "order_date_to": self.order_date_to,
            "nro_venta": self.nro_venta,
            "order_id": self.order_id,
            "pack_id": self.pack_id
        })

        #put new import lines
        import_errors = context.get("import_errors") or {}
        if (sync_status and "order_lines" in sync_status):
            for oline in sync_status["order_lines"]:
                oid = str(oline["id"]) if oline.get("id") else ""
                prev_error = import_errors.get(oid, "")
                self.env["mercadolibre.orders.import.line"].create({
                            "import_id": res_id.id,
                            "name": str("Venta #")+str(oline["pack_id"] or oline["id"]),
                            "order_id": oline["id"],
                            "pack_id": oline["pack_id"],
                            "paid_amount": oline["paid_amount"],
                            "buyer": str(oline["buyer"] and oline["buyer"]["nickname"]),
                            "status": oline["status"],
                            "date_closed": ml_datetime(oline["date_closed"]),
                            "error": prev_error,
                            "import_status": 'error' if prev_error else 'pending',
                        })

        # Restore successfully processed lines from previous wizard instances.
        # These were removed from sync_status on success so we carry them via context.
        for result in (context.get("import_results") or []):
            dc = False
            if result.get("date_closed"):
                try:
                    dc = fields.Datetime.from_string(result["date_closed"])
                except Exception:
                    try:
                        from datetime import datetime as _dt
                        dc = _dt.fromisoformat(result["date_closed"])
                    except Exception:
                        dc = False
            self.env["mercadolibre.orders.import.line"].create({
                "import_id": res_id.id,
                "name": result.get("name") or "",
                "order_id": result.get("order_id") or "",
                "pack_id": result.get("pack_id") or "",
                "paid_amount": result.get("paid_amount") or "",
                "buyer": result.get("buyer") or "",
                "status": result.get("status") or "",
                "date_closed": dc,
                "error": result.get("error") or "",
                "import_status": result.get("import_status") or "imported",
                "meli_order": result.get("meli_order_id") or False,
                "sale_order": result.get("sale_order_id") or False,
            })

        # "Verificar estado de importación": escanear ventas YA importadas del
        # período que no estén listas para confirmar (pestaña Ventas incompletas).
        if context.get("scan_incomplete"):
            try:
                self._scan_incomplete_sales(target=res_id, context=context)
            except Exception as e:
                _logger.error("show_import_wizard scan_incomplete error: %s", str(e), exc_info=True)

        return {
            'name':_("Importar Ventas ML (...)"),
            'view_mode': 'form',
            'view_id': (refview and refview[1]),
            'res_id': (res_id and res_id.id),
            'view_type': 'form',
            'res_model': 'mercadolibre.orders.import',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'domain': [],
            'context': context
        }


    def check_import_status( self , context=None):
        _logger.info('Processing import status ' + str(self.import_status))
        context = context or self.env.context
        context_resume = self._context_resume( context )

        _logger.info("check_import_status > context:"+str(context_resume))
        warningobj = self.env['meli.warning']

        self.batch_processing_status = "processing";
        
        new_context = {}
        new_context.update(context)
        new_context["sync_status"] = self._calculate_sync_status()
        # Pedir el escaneo de "Ventas incompletas" sobre el wizard que se va a crear.
        new_context["scan_incomplete"] = True
        _logger.info("check_import_status > new_context:"+str( self._context_resume(new_context) ) )

        self.batch_processing_status = "processed";

        #messhtml = ""
        #messhtml+= "<br/>Sales to sync: "+self.sales_to_sync
        #res = warningobj.info( title='CHECK IMPORT STATUS', message="Import Status", message_html=messhtml )
        res = self.show_import_wizard( context=new_context)
        return res

    def create_full_report( self, context=None, config=None, meli=None):
        _logger.info("Creating full report")
        context = context or self.env.context
        company = self.env.user.company_id

    def _context_resume(self, context=None):
        return str(context and "sales_to_sync" in context and context["sales_to_sync"])

    def orders_import(self, context=None):
        context = context or self.env.context
        #_logger.info("orders_import context:"+str(context))
        company = self.env.user.company_id
        context_resume = self._context_resume(context)
        #_logger.info("orders_import context:"+str(context_resume))

        account_ids = ('active_ids' in context and context['active_ids']) or []
        #product_obj = self.env['product.template']
        account = self.env['mercadolibre.account'].browse(account_ids)
        warningobj = self.env['meli.warning']
        if not account:
            return warningobj.error(title="No account defined")
        company = (account and account.company_id) or company
        meli = self.env['meli.util'].get_new_instance(company, account )
        if meli.need_login():
            return meli.redirect_login()

        config = account.configuration or company        

        #_logger.info("orders_import import_lines:"+str(self.import_lines))
        batch_start = 0
        imported_order_ids = []
        imported_order_ids_hash = {}
        imported_order_ids_left = []
        # Errors produced in this batch, keyed by order_id; propagated to the
        # next wizard instance so the user can see why an order failed even
        # after the wizard rebuilds its lines from a fresh ML query.
        imported_order_errors = dict(context.get("import_errors") or {})
        # Lines successfully processed in previous wizard instances (imported/warning).
        # Errors stay in sync_status so we don't duplicate them here.
        imported_results = list(context.get("import_results") or [])

        #force test one by one
        #self.batch_processing_unit = 1 #min segun pack id x2 o x3 o xN
        if (self.import_lines):
            _logger.info("Start importing! "+str(len(self.import_lines)) 
                         +" from: "+str(self.batch_processing_unit_offset)
                         +" to: "+str(self.batch_processing_unit_offset+self.batch_processing_unit))
            #import some orders, update context and then reload wizard....
            
            for imli in self.import_lines:                
                if (batch_start>=self.batch_processing_unit):
                    _logger.info("Breaking batch!")
                    break;

                batch_start+=1      
                order_id = imli.order_id
                pack_id = imli.pack_id
                 
                check_meli_order = self.env["mercadolibre.orders"].search(
                        [   ('order_id','=',order_id),
                            ('connection_account','=', account.id)], limit=1 )
                _logger.info("Importing! "+str(order_id)+" pack_id:"+str(pack_id)+" check_meli_order:"+str(check_meli_order) )
                ret = {}
                if not check_meli_order:
                    #import!!

                    try:
                        # Note: No savepoint here because orders_import_order may call MeliCommit()
                        # which commits the transaction and invalidates any savepoint
                        # Optionally skip stock updates during import to avoid serialization errors
                        ctx = {}
                        if self.skip_stock_update:
                            ctx['meli_skip_stock_update'] = True
                        ret = self.env["mercadolibre.orders"].with_context(**ctx).orders_import_order(order_id=order_id, meli=meli, config=config)
                    except IntegrityError as E:
                        # duplicate key / constraint violation, etc.
                        msg = f"DB integrity error importing order {order_id}: {E}"
                        _logger.exception(msg)
                        ret = {"error": str(E)}
                    except Exception as E:
                        _logger.error("import error: "+str(E))
                        _logger.error(E, exc_info=True)
                        ret = {"error": str(E)}
                        pass;

                    if ("error" in ret):
                        try:
                            imli.sudo().write({
                                'error': ret["error"],
                                'import_status': 'error',
                            })
                        except Exception as write_err:
                            _logger.error("Could not write error to import line: %s", str(write_err))
                        imported_order_errors[str(order_id)] = ret["error"]
                        _logger.error("Import error order_id"+str(order_id)+" error:"+str(ret["error"]))
                    else:
                        MeliCommit( self )
                        _meli_order_id = False
                        _sale_order_id = False
                        try:
                            # Verify sale.order was actually created
                            ml_order = self.env["mercadolibre.orders"].search(
                                [('order_id', '=', order_id),
                                 ('connection_account', '=', account.id)], limit=1)
                            if ml_order:
                                _meli_order_id = ml_order.id
                            if ml_order and not ml_order.sale_order:
                                imli.sudo().write({
                                    'import_status': 'warning',
                                    'error': 'Orden ML creada pero sin Pedido de Venta (sale.order). '
                                             'Posibles causas: orden pack pendiente de envío, '
                                             'producto no encontrado, o falta contacto.',
                                    'meli_order': _meli_order_id,
                                })
                                imported_order_errors[str(order_id)] = imli.error
                                _logger.warning(
                                    "Import warning: ML order %s created but no sale.order. "
                                    "Check products, partner, and shipment.", order_id)
                            else:
                                if ml_order and ml_order.sale_order:
                                    _sale_order_id = ml_order.sale_order.id
                                imli.sudo().write({
                                    'import_status': 'imported',
                                    'meli_order': _meli_order_id,
                                    'sale_order': _sale_order_id,
                                })
                        except Exception:
                            pass
                        # clear any previous error carried over from prior batches
                        if str(order_id) not in imported_order_errors:
                            imported_order_errors.pop(str(order_id), None)

                    _logger.error("Import result:"+str(order_id)+" "+str(ret))

                    # Capture successfully processed lines for cross-wizard persistence.
                    # Error lines stay in sync_status/import_errors so skip them here.
                    if "error" not in ret:
                        try:
                            dc = imli.date_closed and imli.date_closed.isoformat() or ""
                            imported_results.append({
                                "order_id": imli.order_id or "",
                                "pack_id": imli.pack_id or "",
                                "name": imli.name or "",
                                "buyer": imli.buyer or "",
                                "paid_amount": imli.paid_amount or "",
                                "status": imli.status or "",
                                "date_closed": dc,
                                "import_status": imli.import_status or "imported",
                                "error": imli.error or "",
                                "meli_order_id": _meli_order_id or False,
                                "sale_order_id": _sale_order_id or False,
                            })
                        except Exception:
                            pass

                re_check_meli_order = self.env["mercadolibre.orders"].search(
                        [   ('order_id','=',order_id),
                            ('connection_account','=', account.id)], limit=1 )
                if not re_check_meli_order or not "error" in ret:
                    imported_order_ids.append(order_id)
                    imported_order_ids_hash[order_id] = True
                else:
                    imported_order_ids_left.append(order_id)
                    imported_order_ids_hash[order_id] = False
                    
                    
        new_context = {}
        new_context.update(context)
        new_context.update({
            "batch_processing_unit": self.batch_processing_unit,
            "batch_processing_unit_offset": self.batch_processing_unit_offset,
            "batch_sales_to_sync": self.batch_sales_to_sync,
            "import_errors": imported_order_errors,
            "import_results": imported_results,
        })
        if (self.batch_processing==False):
            new_context["sync_status"] = self._calculate_sync_status()
        else:
            #reprocess sync lines
            _logger.info("reprocess sync lines: imported_order_ids #"+str(len(imported_order_ids))
                         +" imported_order_ids:"+str(imported_order_ids)
                         +" imported_order_ids_hash:"+str(imported_order_ids_hash))

            resynclines = []
            for ol in new_context["sync_status"]["order_lines"]:
                _logger.info("ol:"+str(ol["id"]))
                if (str(ol["id"]) in imported_order_ids_hash and imported_order_ids_hash[str(ol["id"])]):
                    pass;
                else:
                    resynclines.append(ol)
            new_context["sync_status"]["order_lines"] = resynclines
            _logger.info("resynclines:"+str(len(resynclines)))


        res = self.show_import_wizard(context=new_context)

        return res

    def __orders_import(self, context=None):

        context = context or self.env.context
        company = self.env.user.company_id
        #product_ids = ('active_ids' in context and context['active_ids']) or []
        #product_obj = self.env['product.template']

        #_logger.info("orders_import context:"+str(context))

        account_ids = ('active_ids' in context and context['active_ids']) or []
        #product_obj = self.env['product.template']
        account = self.env['mercadolibre.account'].browse(account_ids)
        
        #odoo_meli_ids = account.list_meli_ids()

        warningobj = self.env['meli.warning']

        if not account:
            return warningobj.error(title="No account defined")

        company = (account and account.company_id) or company
        meli = self.env['meli.util'].get_new_instance(company, account )
        if meli.need_login():
            return meli.redirect_login()
        
        custom_context = {
            "order_state": self.order_state,
            "nro_venta": self.nro_venta,
            "order_id": self.order_id,
            "pack_id": self.pack_id,
            "batch_processing_unit": self.batch_processing_unit,
            "batch_processing_unit_offset": self.batch_processing_unit_offset,
            "batch_sales_to_sync": self.batch_sales_to_sync,            
        }

        _logger.info("product_template_import custom_context:"+str(custom_context))

        meli_id = False
        if self.meli_id:
            meli_id = self.meli_id

        res = {}

        ##res = company.product_meli_get_products(context=custom_context)
        #for product_id in product_ids:
        #    product = product_obj.browse(product_id)
        #    if (product):
        #        if self.force_meli_pub and not product.meli_pub:
        #            product.meli_pub = True
        #            for variant in product.product_variant_ids:
        #                variant.meli_pub = True
        #        if (product.meli_pub):
        #                res = product.product_template_update(meli_id=meli_id)

        #    if res and 'name' in res:
        #        return res

        _logger.info("import res:"+str(res))
        if res and "json_report" in res:
            if "paging" in res:
                if "next_offset" in res["paging"]:
                    self.batch_processing_unit_offset = res["paging"]["next_offset"]

            #update batch_processing_unit_offset
            json_report = res["json_report"]
            full_report = json_report["synced"]+json_report["missing"]+json_report["duplicates"]
            csv_report_header = ""
            csv_report = ""

            sep = ""
            full_report = full_report or []
            if full_report:
                for field in full_report[0]:
                    csv_report_header+= sep+str(field)
                    sep = ";"

                for sync in full_report:
                    sep = ""
                    for field in sync:
                        csv_report+= sep+'"'+str(sync[field])+'"'
                        sep = ";"
                    csv_report+= "\n"

            csv_report_attachment_last = self.report_import or self.env["ir.attachment"].search([('res_id','=',self.id)], order='id desc', limit=1 )
            if (csv_report_attachment_last):
                csv_report_last = csv_report_attachment_last.index_content
                if (csv_report_last):
                    csv_report = csv_report_last+"\n"+csv_report
            else:
                csv_report = csv_report_header+"\n"+csv_report
            #_logger.info(csv_report)

            b64_csv = base64.b64encode(csv_report.encode())
            now = datetime.now()
            ATTACHMENT_NAME = "MassiveImport-"+str(now.strftime("%Y-%m-%d, %H:%M"))

            csv_report_attachment = self.env['ir.attachment'].create({
                'name': ATTACHMENT_NAME+'.csv',
                'type': 'binary',
                'datas': b64_csv,
                #'datas_fname': ATTACHMENT_NAME + '.csv',
                'access_token': self.env['ir.attachment']._generate_access_token(),
                #'store_fname': ATTACHMENT_NAME+'.csv',
                'res_model': 'mercadolibre.orders.import',
                'res_id': self.id,
                'mimetype': 'text/csv'
            })

            csv_report_attachment_link= ''
            if csv_report_attachment:
                self.report_import = csv_report_attachment.id
                csv_report_attachment_link = "/web/content/"+str(csv_report_attachment.id)+"?download=true&access_token="+str(csv_report_attachment.access_token)
                self.report_import_link = csv_report_attachment_link
                #<a class="fa fa-download" t-attf-title="Download Attachment {{asset.name}}" t-attf-href="/web/content/#{asset.attachment.id}?download=true&amp;access_token=#{asset.attachment.access_token}" target="_blank"></a>

            res.update({'csv_report':  csv_report, 'csv_report_attachment':  csv_report_attachment, 'csv_report_attachment_link': csv_report_attachment_link })

            _logger.info('Processing import status ' + str(self.import_status)+ " report_import:"+str(self.report_import))
            messhtml = "Import status: "+str(res)
            res = warningobj.info( title='IMPORT STATUS', message="Import Status", message_html=messhtml )
            res = self.show_import_wizard()

        return res

class mercadolibre_orders_import_line(models.TransientModel):

    _name = "mercadolibre.orders.import.line"
    _description = "Orders Import ML LINE"

    name = fields.Char(string="Venta",index=True)
    import_id = fields.Many2one('mercadolibre.orders.import',string="wizard import",index=True)
    order_id = fields.Char(string="Order ID",index=True)
    pack_id = fields.Char(string="Pack ID",index=True)
    paid_amount = fields.Char(string="Paid Amount")
    buyer = fields.Char(string="Buyer",index=True)
    status = fields.Char(string="Status",index=True)
    date_closed = fields.Datetime(string="Fecha",index=True)
    error = fields.Char(string="Error")
    import_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('imported', 'Importado'),
        ('warning', 'Incompleto'),
        ('error', 'Error'),
    ], string="Estado Importación", default='pending', index=True)
    meli_order = fields.Many2one('mercadolibre.orders', string="Orden ML", ondelete='set null')
    sale_order = fields.Many2one('sale.order', string="Pedido de Venta", ondelete='set null')
