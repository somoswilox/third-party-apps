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
from datetime import datetime, timedelta
from .versions import *
import logging

_logger = logging.getLogger(__name__)


class MercadolibreCronExecution(models.Model):
    """Model to track CRON execution history for MercadoLibre accounts."""

    _name = "mercadolibre.cron.execution"
    _description = "MercadoLibre CRON Execution Log"
    _order = "date_start desc"
    _rec_name = "display_name"

    connection_account = fields.Many2one(
        "mercadolibre.account",
        string="Cuenta ML",
        required=True,
        ondelete="cascade",
        index=True
    )

    cron_type = fields.Selection([
        ("orders", "Cron Meli Orders"),
        ("stock", "Cron Meli Stock"),
        ("stock_rt", "Cron Meli Stock RT"),
        ("products_post", "Cron Post Products"),
        ("products_get", "Cron Get Products"),
        ("price", "Cron Post Price"),
        ("internal_jobs", "Internal Jobs"),
        ("questions", "Cron Questions"),
        ("process", "Cron Process"),
        ("batch_update", "Cron Batch Update Marked Orders"),
        ("stock_diagnostic", "Cron Stock Diagnostic"),
    ], string="Tipo de CRON", required=True, index=True)

    state = fields.Selection([
        ("running", "Ejecutando"),
        ("success", "Exitoso"),
        ("warning", "Con Advertencias"),
        ("error", "Error"),
    ], string="Estado", default="running", index=True)

    date_start = fields.Datetime(
        string="Inicio",
        default=fields.Datetime.now,
        required=True,
        index=True
    )

    date_end = fields.Datetime(string="Fin")

    duration = fields.Float(
        string="Duración (seg)",
        compute="_compute_duration",
        store=True,
        help="Duración en segundos"
    )

    duration_per_item = fields.Float(
        string="Duración/Item (seg)",
        compute="_compute_duration_per_item",
        store=True,
        help="Duración promedio por item procesado en segundos"
    )

    duration_display = fields.Char(
        string="Duración",
        compute="_compute_duration_display",
        help="Duración formateada"
    )

    duration_per_item_display = fields.Char(
        string="Duración/Item",
        compute="_compute_duration_per_item_display",
        help="Duración por item formateada"
    )

    items_processed = fields.Integer(
        string="Items Procesados",
        default=0,
        help="Cantidad de items procesados en esta ejecución"
    )

    items_success = fields.Integer(
        string="Items Exitosos",
        default=0
    )

    items_error = fields.Integer(
        string="Items con Error",
        default=0
    )

    items_skipped = fields.Integer(
        string="Items Omitidos",
        default=0,
        help="Items salteados esperadamente (sin match y sin crear, o no disponibles). "
             "NO cuentan como error."
    )

    # Orders-specific breakdown (only populated for cron_type='orders')
    orders_by_notification = fields.Integer(
        string="Órd. por Notificación",
        default=0,
        help="Órdenes procesadas vía notificaciones orders_v2"
    )

    orders_new = fields.Integer(
        string="Órd. Nuevas",
        default=0,
        help="Órdenes nuevas importadas (no estaban en Odoo)"
    )

    orders_by_query = fields.Integer(
        string="Órd. por Query",
        default=0,
        help="Órdenes tocadas por el query de seguridad (capa 3)"
    )

    # Per-order timing benchmark (seconds)
    orders_avg_time = fields.Float(
        string="Tiempo prom/orden (seg)",
        default=0,
        digits=(10, 3),
        help="Tiempo promedio de procesamiento por orden de venta"
    )
    orders_max_time = fields.Float(
        string="Tiempo máx/orden (seg)",
        default=0,
        digits=(10, 3),
        help="Tiempo máximo de procesamiento de una orden"
    )
    orders_min_time = fields.Float(
        string="Tiempo mín/orden (seg)",
        default=0,
        digits=(10, 3),
        help="Tiempo mínimo de procesamiento de una orden"
    )
    orders_timing_display = fields.Char(
        string="Benchmark/orden",
        compute="_compute_orders_timing_display",
        help="Resumen de tiempos de procesamiento por orden"
    )

    # MULTIGET: Campo de progreso legible en tiempo real
    # Muestra "820/1500 | 800 ok, 20 err" mientras el cron está corriendo
    progress_display = fields.Char(
        string="Progreso",
        compute="_compute_progress_display",
        help="Progreso actual del lote en tiempo real"
    )

    error_message = fields.Text(string="Mensaje de Error")

    log_summary = fields.Text(string="Resumen de Log")

    kanban_color = fields.Integer(
        string="Color",
        compute="_compute_kanban_color",
        store=False
    )

    display_name = fields.Char(
        string="Nombre",
        compute="_compute_display_name",
        store=True
    )

    @api.depends('cron_type', 'date_start')
    def _compute_display_name(self):
        cron_labels = {
            'orders': 'Órdenes',
            'stock': 'Stock',
            'stock_rt': 'Stock RT',
            'products_post': 'Post Productos',
            'products_get': 'Get Productos',
            'price': 'Precios',
            'internal_jobs': 'Jobs Internos',
            'questions': 'Preguntas',
            'process': 'Proceso',
            'batch_update': 'Batch Update',
            'stock_diagnostic': 'Stock Diagnostic',
        }
        for rec in self:
            label = cron_labels.get(rec.cron_type, rec.cron_type)
            date_str = rec.date_start.strftime('%d/%m %H:%M') if rec.date_start else ''
            rec.display_name = f"{label} - {date_str}"

    @api.depends('orders_avg_time', 'orders_max_time', 'orders_min_time')
    def _compute_orders_timing_display(self):
        def _fmt(secs):
            if not secs:
                return '-'
            if secs < 1:
                return '%dms' % (secs * 1000)
            return '%.1fs' % secs

        for rec in self:
            if rec.orders_avg_time:
                rec.orders_timing_display = 'prom:%s  máx:%s  mín:%s' % (
                    _fmt(rec.orders_avg_time),
                    _fmt(rec.orders_max_time),
                    _fmt(rec.orders_min_time),
                )
            else:
                rec.orders_timing_display = '-'

    @api.depends('items_processed', 'items_success', 'items_error', 'state',
                 'cron_type', 'orders_by_notification', 'orders_new', 'orders_by_query')
    def _compute_progress_display(self):
        # MULTIGET: Progreso legible en tiempo real para el historial de crons
        for rec in self:
            if rec.cron_type == 'orders' and rec.state != 'running':
                parts = []
                if rec.orders_by_notification:
                    parts.append("Notif:%d" % rec.orders_by_notification)
                if rec.orders_new:
                    parts.append("Nuevas:%d" % rec.orders_new)
                if rec.orders_by_query:
                    parts.append("Query:%d" % rec.orders_by_query)
                if rec.items_error:
                    parts.append("Err:%d" % rec.items_error)
                if parts:
                    rec.progress_display = " | ".join(parts)
                elif rec.state == 'error':
                    rec.progress_display = "Error"
                else:
                    rec.progress_display = "0 órdenes"
            elif rec.state == 'running':
                if rec.items_processed > 0:
                    rec.progress_display = "%d/%d | %d ok, %d err" % (
                        rec.items_processed,
                        rec.items_processed + (rec.items_error or 0),
                        rec.items_success,
                        rec.items_error,
                    )
                else:
                    rec.progress_display = "Iniciando..."
            elif rec.state in ('success', 'warning'):
                rec.progress_display = "%d ok, %d err" % (rec.items_success, rec.items_error)
            elif rec.state == 'error':
                rec.progress_display = "Error tras %d ok, %d err" % (rec.items_success, rec.items_error)
            else:
                rec.progress_display = "-"

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for rec in self:
            if rec.date_start and rec.date_end:
                delta = rec.date_end - rec.date_start
                rec.duration = delta.total_seconds()
            else:
                rec.duration = 0

    @api.depends('duration', 'items_processed')
    def _compute_duration_per_item(self):
        for rec in self:
            if rec.duration and rec.items_processed > 0:
                rec.duration_per_item = rec.duration / rec.items_processed
            else:
                rec.duration_per_item = 0

    @api.depends('duration')
    def _compute_duration_display(self):
        for rec in self:
            if rec.duration:
                if rec.duration < 60:
                    rec.duration_display = f"{rec.duration:.1f} seg"
                elif rec.duration < 3600:
                    minutes = rec.duration / 60
                    rec.duration_display = f"{minutes:.1f} min"
                else:
                    hours = rec.duration / 3600
                    rec.duration_display = f"{hours:.1f} hrs"
            else:
                rec.duration_display = "-"

    @api.depends('duration_per_item')
    def _compute_duration_per_item_display(self):
        for rec in self:
            if rec.duration_per_item:
                if rec.duration_per_item < 1:
                    rec.duration_per_item_display = f"{rec.duration_per_item * 1000:.0f} ms"
                elif rec.duration_per_item < 60:
                    rec.duration_per_item_display = f"{rec.duration_per_item:.2f} seg"
                else:
                    minutes = rec.duration_per_item / 60
                    rec.duration_per_item_display = f"{minutes:.1f} min"
            else:
                rec.duration_per_item_display = "-"

    @api.depends('state')
    def _compute_kanban_color(self):
        color_map = {
            'running': 4,   # Azul
            'success': 10,  # Verde
            'warning': 3,   # Amarillo
            'error': 1,     # Rojo
        }
        for rec in self:
            rec.kanban_color = color_map.get(rec.state, 0)

    def action_view_details(self):
        """Open form view with details."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Detalle de Ejecución',
            'res_model': 'mercadolibre.cron.execution',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def cleanup_old_records(self, days=30):
        """Remove records older than specified days."""
        cutoff_date = datetime.now() - timedelta(days=days)
        old_records = self.search([('date_start', '<', cutoff_date)])
        old_records.unlink()
        return True


class MercadolibreCronStatus(models.Model):
    """Model to track current status of each CRON type per account."""

    _name = "mercadolibre.cron.status"
    _description = "MercadoLibre CRON Status"
    _rec_name = "cron_type"

    connection_account = fields.Many2one(
        "mercadolibre.account",
        string="Cuenta ML",
        required=True,
        ondelete="cascade",
        index=True
    )

    cron_mode = fields.Selection([
        ('global', 'Global'),
        ('individual', 'Individual'),
    ], string='Modo', default='global', required=True,
        help='Global: usa el ir.cron compartido entre todas las cuentas.\n'
             'Individual: clon del ir.cron exclusivo para esta cuenta (code con account_id=ID).')

    individual_cron_id = fields.Many2one(
        'ir.cron',
        string='CRON individual',
        ondelete='set null',
        help='ir.cron clonado exclusivo para esta cuenta. Se gestiona automáticamente al cambiar el modo.',
    )

    cron_type = fields.Selection([
        ("orders", "Cron Meli Orders"),
        ("stock", "Cron Meli Stock"),
        ("stock_rt", "Cron Meli Stock RT"),
        ("products_post", "Cron Post Products"),
        ("products_get", "Cron Get Products"),
        ("price", "Cron Post Price"),
        ("internal_jobs", "Internal Jobs"),
        ("questions", "Cron Questions"),
        ("process", "Cron Process"),
        ("batch_update", "Cron Batch Update Marked Orders"),
        ("stock_diagnostic", "Cron Stock Diagnostic"),
    ], string="Tipo de CRON", required=True, index=True)

    cron_name = fields.Char(
        string="Nombre CRON",
        compute="_compute_cron_name",
        store=True
    )

    is_enabled = fields.Boolean(
        string="Habilitado",
        default=True,
        help="Indica si este CRON está habilitado para esta cuenta"
    )

    last_execution = fields.Many2one(
        "mercadolibre.cron.execution",
        string="Última Ejecución",
        compute="_compute_last_execution"
    )

    last_run_date = fields.Datetime(
        string="Fecha Última Ejecución",
        compute="_compute_last_execution"
    )

    last_run_state = fields.Selection([
        ("running", "Ejecutando"),
        ("success", "Exitoso"),
        ("warning", "Con Advertencias"),
        ("error", "Error"),
        ("never", "Nunca ejecutado"),
    ], string="Último Estado", compute="_compute_last_execution")

    last_run_duration = fields.Float(
        string="Última Duración (seg)",
        compute="_compute_last_execution"
    )

    last_items_processed = fields.Integer(
        string="Últimos Items Procesados",
        compute="_compute_last_execution"
    )

    last_duration_per_item = fields.Float(
        string="Última Duración/Item (seg)",
        compute="_compute_last_execution"
    )

    last_error_message = fields.Text(
        string="Último Error",
        compute="_compute_last_execution"
    )

    last_log_summary = fields.Text(
        string="Último Resumen",
        compute="_compute_last_execution"
    )

    # Estadísticas de duración del CRON
    avg_duration = fields.Float(
        string="Duración Promedio (seg)",
        compute="_compute_stats",
        help="Duración promedio de las ejecuciones"
    )

    min_duration = fields.Float(
        string="Duración Mínima (seg)",
        compute="_compute_stats",
        help="Duración mínima registrada"
    )

    max_duration = fields.Float(
        string="Duración Máxima (seg)",
        compute="_compute_stats",
        help="Duración máxima registrada"
    )

    # Estadísticas de duración por item
    avg_duration_per_item = fields.Float(
        string="Duración/Item Promedio (seg)",
        compute="_compute_stats",
        help="Duración promedio por item procesado"
    )

    min_duration_per_item = fields.Float(
        string="Duración/Item Mínima (seg)",
        compute="_compute_stats",
        help="Duración mínima por item"
    )

    max_duration_per_item = fields.Float(
        string="Duración/Item Máxima (seg)",
        compute="_compute_stats",
        help="Duración máxima por item"
    )

    # Estadísticas generales
    total_executions = fields.Integer(
        string="Total Ejecuciones",
        compute="_compute_stats"
    )

    total_items_processed = fields.Integer(
        string="Total Items Procesados",
        compute="_compute_stats",
        help="Total de items procesados en todas las ejecuciones"
    )

    success_rate = fields.Float(
        string="Tasa de Éxito (%)",
        compute="_compute_stats"
    )

    # Campos de display formateados
    avg_duration_display = fields.Char(
        string="Duración Promedio",
        compute="_compute_display_stats"
    )

    avg_duration_per_item_display = fields.Char(
        string="Duración/Item Promedio",
        compute="_compute_display_stats"
    )

    kanban_color = fields.Integer(
        string="Color",
        compute="_compute_kanban_color",
        store=False
    )

    kanban_state = fields.Selection([
        ("normal", "Normal"),
        ("done", "Exitoso"),
        ("blocked", "Bloqueado"),
    ], string="Estado Kanban", compute="_compute_kanban_state")

    # Enlace al ir.cron global correspondiente
    ir_cron_id = fields.Many2one(
        'ir.cron',
        string='CRON del sistema',
        compute='_compute_ir_cron',
        store=False,
    )
    next_call = fields.Datetime(
        string='Próxima ejecución',
        compute='_compute_ir_cron',
        store=False,
    )
    interval_display = fields.Char(
        string='Frecuencia',
        compute='_compute_ir_cron',
        store=False,
    )
    ir_cron_active = fields.Boolean(
        string='CRON activo en sistema',
        compute='_compute_ir_cron',
        store=False,
    )
    next_call_relative = fields.Char(
        string='Próxima ejecución (relativo)',
        compute='_compute_ir_cron',
        store=False,
    )

    # Price batch fields (from parent account)
    price_batch_active = fields.Boolean(
        string='Batch precio configurado',
        compute='_compute_price_batch',
        store=False,
    )
    price_batch_running = fields.Boolean(
        string='Batch precio en curso',
        compute='_compute_price_batch',
        store=False,
    )
    price_batch_progress = fields.Char(
        string='Progreso batch',
        compute='_compute_price_batch',
        store=False,
    )

    @api.depends('cron_type', 'connection_account')
    def _compute_price_batch(self):
        for rec in self:
            if rec.cron_type == 'price' and rec.connection_account:
                acc = rec.connection_account
                rec.price_batch_active = acc.meli_cron_price_batch_hour and acc.meli_cron_price_batch_hour != '-1'
                rec.price_batch_running = acc.meli_cron_price_batch_running
                if acc.meli_cron_price_batch_running and acc.meli_cron_price_batch_total:
                    rec.price_batch_progress = '%d/%d' % (acc.meli_cron_price_batch_processed, acc.meli_cron_price_batch_total)
                else:
                    rec.price_batch_progress = ''
            else:
                rec.price_batch_active = False
                rec.price_batch_running = False
                rec.price_batch_progress = ''

    # Cron types que soportan account_id (pueden tener modo Individual)
    INDIVIDUAL_SUPPORTED = {'orders', 'stock', 'stock_rt', 'products_post', 'products_get', 'price'}

    # Mapeo cron_type → xmlid del ir.cron global en el sistema.
    # Usamos xmlid y NO el name porque ir.cron.name es traducible — buscar por
    # nombre falla en instalaciones localizadas (ej: es_AR traduce "Cron Meli
    # Process Post Stock" → "Cron Publicar Stock" y el search no lo encuentra).
    IR_CRON_XMLID_MAP = {
        'orders':           'meli_oerp.ir_cron_module_cron_meli_orders',
        'stock':            'meli_oerp.ir_cron_module_cron_meli_process_post_stock',
        'stock_rt':         'meli_oerp.ir_cron_module_cron_meli_process_post_stock_rt',
        'products_post':    'meli_oerp.ir_cron_module_cron_meli_process_post_products',
        'products_get':     'meli_oerp.ir_cron_module_cron_meli_process_get_products',
        'price':            'meli_oerp.ir_cron_module_cron_meli_process_post_price',
        'internal_jobs':    'meli_oerp_multiple.ir_cron_module_internal_jobs',
        'questions':        'meli_oerp.ir_cron_module_cron_meli_questions',
        'process':          'meli_oerp.ir_cron_module_cron_meli_process',
        'batch_update':     'meli_oerp_multiple.ir_cron_meli_batch_update_marked_orders',
        'stock_diagnostic': 'meli_oerp_multiple.ir_cron_meli_stock_diagnostic',
    }

    # Mapeo cron_type → nombre del ir.cron (fallback, solo para instalaciones
    # donde el xmlid no exista — ej: clon manual). La busqueda por nombre es
    # sensible a traducciones, asi que se usa con lang=None para consultar el
    # valor original en la tabla.
    IR_CRON_NAME_MAP = {
        'orders':           'Cron Meli Orders',
        'stock':            'Cron Meli Process Post Stock',
        'stock_rt':         'Cron Meli Process Post Stock RT',
        'products_post':    'Cron Meli Process Post Products',
        'products_get':     'Cron Meli Process Get Products',
        'price':            'Cron Meli Process Post Price',
        'internal_jobs':    'Meli Internal Jobs',
        'questions':        'Cron Meli Questions',
        'process':          'Cron Meli Process',
        'batch_update':     'Meli Batch Update Marked Orders',
        'stock_diagnostic': 'Meli Stock Diagnostic',
    }

    # Mapeo cron_type → código Python con account_id para ir.cron individual
    IR_CRON_CODE_MAP = {
        'orders':        'model.cron_meli_orders(account_id=%d)',
        'stock':         'model.cron_meli_process_post_stock(account_id=%d)',
        'stock_rt':      'model.cron_meli_process_post_stock_rt(account_id=%d)',
        'products_post': 'model.cron_meli_process_post_products(account_id=%d)',
        'products_get':  'model.cron_meli_process_get_products(account_id=%d)',
        'price':         'model.cron_meli_process_post_price(account_id=%d)',
    }

    def _resolve_global_ir_cron(self, cron_type):
        """Resuelve el ir.cron global por xmlid (robusto a traducciones y
        renombres). Si no existe el xmlid, cae a busqueda por nombre con
        lang=None para evitar el problema de nombres traducidos (es_AR,
        pt_BR, etc.).
        """
        IrCron = self.env['ir.cron'].sudo().with_context(active_test=False)
        xmlid = self.IR_CRON_XMLID_MAP.get(cron_type)
        if xmlid:
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if cron:
                return cron.sudo()
        # Fallback: busqueda por nombre original (sin traducir)
        cron_name = self.IR_CRON_NAME_MAP.get(cron_type)
        if cron_name:
            return IrCron.with_context(lang=None).search(
                [('name', '=', cron_name)], limit=1
            )
        return IrCron.browse()

    @api.depends('cron_type', 'cron_mode', 'individual_cron_id')
    def _compute_ir_cron(self):
        interval_type_labels = {
            'minutes': 'min', 'hours': 'h', 'days': 'd', 'weeks': 'sem', 'months': 'mes',
        }
        for rec in self:
            # En modo Individual usa el clon; en Global resuelve el cron compartido
            if rec.cron_mode == 'individual' and rec.individual_cron_id:
                cron = rec.individual_cron_id.sudo()
            else:
                cron = self._resolve_global_ir_cron(rec.cron_type)

            rec.ir_cron_id = cron.id if cron else False
            rec.next_call = cron.nextcall if cron else False
            rec.ir_cron_active = cron.active if cron else False
            if cron:
                unit = interval_type_labels.get(cron.interval_type, cron.interval_type)
                rec.interval_display = 'cada %d %s' % (cron.interval_number, unit)
            else:
                rec.interval_display = ''
            # Compute relative next call
            if rec.next_call:
                now = fields.Datetime.now()
                diff = rec.next_call - now
                total_sec = int(diff.total_seconds())
                if total_sec < 0:
                    rec.next_call_relative = 'pendiente'
                elif total_sec < 60:
                    rec.next_call_relative = 'en %ds' % total_sec
                elif total_sec < 3600:
                    rec.next_call_relative = 'en %d min' % (total_sec // 60)
                elif total_sec < 86400:
                    hours = total_sec // 3600
                    mins = (total_sec % 3600) // 60
                    rec.next_call_relative = 'en %dh %dm' % (hours, mins) if mins else 'en %dh' % hours
                else:
                    rec.next_call_relative = 'en %d días' % (total_sec // 86400)
            else:
                rec.next_call_relative = ''

    @api.depends('cron_type')
    def _compute_cron_name(self):
        cron_labels = {
            'orders': 'Cron Meli Orders',
            'stock': 'Cron Meli Stock',
            'stock_rt': 'Cron Meli Stock RT',
            'products_post': 'Cron Post Products',
            'products_get': 'Cron Get Products',
            'price': 'Cron Post Price',
            'internal_jobs': 'Internal Jobs',
            'questions': 'Cron Questions',
            'process': 'Cron Process',
        }
        for rec in self:
            rec.cron_name = cron_labels.get(rec.cron_type, rec.cron_type)

    def _compute_last_execution(self):
        for rec in self:
            last_exec = self.env['mercadolibre.cron.execution'].search([
                ('connection_account', '=', rec.connection_account.id),
                ('cron_type', '=', rec.cron_type)
            ], order='date_start desc', limit=1)

            rec.last_execution = last_exec.id if last_exec else False
            rec.last_run_date = last_exec.date_start if last_exec else False
            rec.last_run_state = last_exec.state if last_exec else 'never'
            rec.last_run_duration = last_exec.duration if last_exec else 0
            rec.last_items_processed = last_exec.items_processed if last_exec else 0
            rec.last_duration_per_item = last_exec.duration_per_item if last_exec else 0
            rec.last_error_message = last_exec.error_message if last_exec else False
            rec.last_log_summary = last_exec.log_summary if last_exec else False

    def _compute_stats(self):
        for rec in self:
            executions = self.env['mercadolibre.cron.execution'].search([
                ('connection_account', '=', rec.connection_account.id),
                ('cron_type', '=', rec.cron_type),
                ('state', '!=', 'running')
            ])

            rec.total_executions = len(executions)

            if executions:
                # Tasa de éxito
                successful = executions.filtered(lambda x: x.state == 'success')
                rec.success_rate = (len(successful) / len(executions)) * 100

                # Estadísticas de duración del CRON
                durations = [e.duration for e in executions if e.duration and e.duration > 0]
                if durations:
                    rec.avg_duration = sum(durations) / len(durations)
                    rec.min_duration = min(durations)
                    rec.max_duration = max(durations)
                else:
                    rec.avg_duration = 0
                    rec.min_duration = 0
                    rec.max_duration = 0

                # Estadísticas de duración por item
                durations_per_item = [e.duration_per_item for e in executions
                                      if e.duration_per_item and e.duration_per_item > 0]
                if durations_per_item:
                    rec.avg_duration_per_item = sum(durations_per_item) / len(durations_per_item)
                    rec.min_duration_per_item = min(durations_per_item)
                    rec.max_duration_per_item = max(durations_per_item)
                else:
                    rec.avg_duration_per_item = 0
                    rec.min_duration_per_item = 0
                    rec.max_duration_per_item = 0

                # Total items procesados
                rec.total_items_processed = sum(e.items_processed for e in executions)
            else:
                rec.success_rate = 0
                rec.avg_duration = 0
                rec.min_duration = 0
                rec.max_duration = 0
                rec.avg_duration_per_item = 0
                rec.min_duration_per_item = 0
                rec.max_duration_per_item = 0
                rec.total_items_processed = 0

    def _compute_display_stats(self):
        """Compute formatted display values for statistics."""
        for rec in self:
            # Formato para duración promedio
            if rec.avg_duration:
                if rec.avg_duration < 60:
                    rec.avg_duration_display = f"{rec.avg_duration:.1f} seg"
                elif rec.avg_duration < 3600:
                    rec.avg_duration_display = f"{rec.avg_duration / 60:.1f} min"
                else:
                    rec.avg_duration_display = f"{rec.avg_duration / 3600:.1f} hrs"
            else:
                rec.avg_duration_display = "-"

            # Formato para duración por item
            if rec.avg_duration_per_item:
                if rec.avg_duration_per_item < 1:
                    rec.avg_duration_per_item_display = f"{rec.avg_duration_per_item * 1000:.0f} ms"
                elif rec.avg_duration_per_item < 60:
                    rec.avg_duration_per_item_display = f"{rec.avg_duration_per_item:.2f} seg"
                else:
                    rec.avg_duration_per_item_display = f"{rec.avg_duration_per_item / 60:.1f} min"
            else:
                rec.avg_duration_per_item_display = "-"

    @api.depends('last_run_state', 'is_enabled')
    def _compute_kanban_color(self):
        for rec in self:
            if not rec.is_enabled:
                rec.kanban_color = 0  # Gris
            elif rec.last_run_state == 'success':
                rec.kanban_color = 10  # Verde
            elif rec.last_run_state == 'warning':
                rec.kanban_color = 3  # Amarillo
            elif rec.last_run_state == 'error':
                rec.kanban_color = 1  # Rojo
            elif rec.last_run_state == 'running':
                rec.kanban_color = 4  # Azul
            else:
                rec.kanban_color = 0  # Gris

    @api.depends('last_run_state', 'is_enabled')
    def _compute_kanban_state(self):
        for rec in self:
            if not rec.is_enabled:
                rec.kanban_state = 'blocked'
            elif rec.last_run_state in ('success', 'warning'):
                rec.kanban_state = 'done'
            elif rec.last_run_state == 'error':
                rec.kanban_state = 'blocked'
            else:
                rec.kanban_state = 'normal'

    def action_view_executions(self):
        """Open list of executions for this CRON type."""
        return {
            'type': 'ir.actions.act_window',
            'name': f'Ejecuciones - {self.cron_name}',
            'res_model': 'mercadolibre.cron.execution',
            'view_mode': f'{view_mode_tree},form',
            'domain': [
                ('connection_account', '=', self.connection_account.id),
                ('cron_type', '=', self.cron_type)
            ],
            'context': {
                'default_connection_account': self.connection_account.id,
                'default_cron_type': self.cron_type,
            }
        }

    def action_set_individual(self):
        """
        Cambia este CRON a modo Individual: clona el ir.cron global con el
        código ajustado para ejecutarse solo para esta cuenta (account_id=ID).
        """
        self.ensure_one()
        account = self.connection_account

        if self.cron_type not in self.INDIVIDUAL_SUPPORTED:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No soportado',
                    'message': 'El CRON "%s" no soporta modo Individual (no tiene parámetro account_id).' % self.cron_name,
                    'type': 'warning',
                }
            }

        # Si ya tiene un cron individual, simplemente activarlo
        if self.individual_cron_id:
            self.individual_cron_id.sudo().write({'active': True})
            self.write({'cron_mode': 'individual'})
            return self._notify('Individual activado', '"%s" ya tenía un CRON individual. Reactivado.' % self.cron_name)

        # Obtener el cron global base por xmlid (robusto a traducciones).
        # _resolve_global_ir_cron ya resuelve por xmlid con fallback por nombre.
        IrCron = self.env['ir.cron'].sudo().with_context(active_test=False)
        global_cron = self._resolve_global_ir_cron(self.cron_type)
        if not global_cron:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'No se encontró el ir.cron global para "%s".' % self.cron_name,
                    'type': 'danger',
                }
            }

        # Construir el código con account_id
        code_template = self.IR_CRON_CODE_MAP.get(self.cron_type)
        individual_code = code_template % account.id

        # Clonar el ir.cron — numbercall=-1 para ejecución indefinida
        clone_name = '%s [%s]' % (global_cron.name, account.name or str(account.id))
        clone_vals = {
            'name': clone_name,
            'active': True,
            'code': individual_code,
            'interval_number': global_cron.interval_number,
            'interval_type': global_cron.interval_type,
            'nextcall': fields.Datetime.now(),
            'model_id': global_cron.model_id.id,
            'state': global_cron.state,
            'user_id': global_cron.user_id.id,
            'priority': global_cron.priority,
            'numbercall': -1,
        }
        new_cron = IrCron.create(clone_vals)
        self.write({'cron_mode': 'individual', 'individual_cron_id': new_cron.id})
        return self._notify(
            'Modo Individual activado',
            'CRON "%s" creado para la cuenta "%s".\nCódigo: %s' % (clone_name, account.name, individual_code)
        )

    def action_set_global(self):
        """Vuelve al modo Global: desactiva el cron individual (no lo elimina)."""
        self.ensure_one()
        if self.individual_cron_id:
            self.individual_cron_id.sudo().write({'active': False})
        self.write({'cron_mode': 'global'})
        return self._notify('Modo Global activado', 'El CRON "%s" volvió al modo Global.' % self.cron_name)

    def _notify(self, title, message, msg_type='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': msg_type, 'sticky': False},
        }

    def action_open_ir_cron(self):
        """Abre el formulario del ir.cron del sistema correspondiente a este tipo de CRON.

        Si no hay un ir.cron linkeado (ir_cron_id es False), abre la lista de
        ir.cron filtrada por los CRONs de Meli para que el usuario pueda buscar
        o crear el que falta.
        """
        self.ensure_one()
        cron = self.ir_cron_id
        if not cron:
            # Sin ir.cron asociado: abrir la lista de todos los ir.cron conocidos
            # de Meli (resolvemos todos los xmlids del map). Esto es robusto a
            # traducciones; un filtro por name ilike 'Meli' fallaria para crons
            # con nombres traducidos como "Cron Publicar Stock".
            known_ids = []
            for xmlid in self.IR_CRON_XMLID_MAP.values():
                rec = self.env.ref(xmlid, raise_if_not_found=False)
                if rec:
                    known_ids.append(rec.id)
            domain = [('id', 'in', known_ids)] if known_ids else [('name', 'ilike', 'Meli')]
            return {
                'type': 'ir.actions.act_window',
                'name': 'CRONs del sistema (Meli)',
                'res_model': 'ir.cron',
                'view_mode': f'{view_mode_tree},form',
                'target': 'current',
                'domain': domain,
                'context': {'active_test': False},
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Editar %s' % (cron.name or self.cron_name),
            'res_model': 'ir.cron',
            'res_id': cron.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'active_test': False},
        }

    def action_run_now(self):
        """Manually trigger this CRON for the account."""
        self.ensure_one()
        account = self.connection_account

        method_map = {
            'orders': 'cron_meli_orders',
            'stock': 'meli_update_remote_stock',
            'stock_rt': 'meli_update_remote_stock_rt',
            'products_post': 'meli_update_remote_products',
            'products_get': 'cron_batch_import_products',
            'price': 'meli_update_remote_price',
            'internal_jobs': 'cron_meli_process_internal_jobs',
            'questions': 'meli_query_get_questions',
            'process': 'cron_meli_process',
        }

        method_name = method_map.get(self.cron_type)
        if method_name and hasattr(account, method_name):
            method = getattr(account, method_name)
            method()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'CRON Ejecutado',
                'message': f'{self.cron_name} ejecutado manualmente',
                'type': 'success',
            }
        }

    _unique_account_cron = UniqueIndex('connection_account, cron_type', message='Ya existe un registro de este CRON para esta cuenta')
