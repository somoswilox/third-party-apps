# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

from odoo import api, models, fields
import logging
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from .warning import warning
from datetime import datetime
from odoo.addons.meli_oerp.models.versions import get_ref_view, MeliCommit
from .connection_binding import _resolve_ml_site_urls

_logger = logging.getLogger(__name__)

import base64

class product_template_update(models.TransientModel):
    _inherit = "mercadolibre.product.template.update"

    connection_account = fields.Many2one("mercadolibre.account",string="MercadoLibre Account")

    def product_template_update(self, context=None):
        context = context or self.env.context
        #_logger.info("meli_oerp_multiple >> wizard product_template_update "+str(context))
        company = self.env.user.company_id
        product_ids = []
        if ('active_ids' in context):
            product_ids = context['active_ids']
        product_obj = self.env['product.template']

        warningobj = self.env['meli.warning']

        account = self.connection_account
        company = (account and account.company_id) or company

        if account:
            meli = self.env['meli.util'].get_new_instance( company, account )
            if meli.need_login():
                return meli.redirect_login()
        else:
            meli = None

        meli_id = False
        if self.meli_id:
            meli_id = self.meli_id
        res = {}
        for product_id in product_ids:
            product = product_obj.browse(product_id)
            if (product):
                if self.force_meli_pub:
                    product.meli_pub = True
                    for variant in product.product_variant_ids:
                        variant.meli_pub = True
                if (product.meli_pub):
                    res = product.product_template_update( meli_id=meli_id, meli=meli, account=account, import_images=self.force_import_images )

            if 'name' in res:
                return res

        return res

class ProductTemplateBindToMercadoLibre(models.TransientModel):

    _name = "mercadolibre.binder.wiz"
    _description = "Wizard de Product Template MercadoLibre Binder"
    _inherit = "ocapi.binder.wiz"

    connectors = fields.Many2many("mercadolibre.account", string='MercadoLibre Accounts',help="Cuenta de mercadolibre origen de la publicación")
    meli_id = fields.Char( string="MercadoLibre Products Ids",help="Ingresar uno o varios separados por coma: (MLXYYYYYYY: MLA123456789, MLA458..., ML...., ... )")
    bind_only = fields.Boolean( string="Bind only using SKU", help="Solo asociar producto y variantes usando SKU (No modifica el producto de Odoo)" )
    use_barcode = fields.Boolean( string="Use Barcode" )

    def product_template_add_to_connector(self, context=None):

        context = context or self.env.context

        #_logger.info("product_template_add_to_connector (MercadoLibre)")

        company = self.env.user.company_id
        product_ids = context['active_ids']
        product_obj = self.env['product.template']

        res = {}
        for product_id in product_ids:

            product = product_obj.browse(product_id)

            for mercadolibre in self.connectors:
                meli_id = False
                bind_only = False
                #_logger.info(_("Check %s in %s") % (product.display_name, mercadolibre.name))
                #Binding to
                if self.meli_id:
                    meli_id = self.meli_id.split(",")
                else:
                    meli_id = [False]
                if self.bind_only:
                    bind_only = self.bind_only
                for mid in meli_id:
                    product.mercadolibre_bind_to( mercadolibre, meli_id=mid, bind_variants=True, bind_only=bind_only )


    def product_template_remove_from_connector(self, context=None):

        context = context or self.env.context

        #_logger.info("product_template_remove_from_connector (MercadoLibre)")

        company = self.env.user.company_id
        product_ids = context['active_ids']
        product_obj = self.env['product.template']

        res = {}
        for product_id in product_ids:

            product = product_obj.browse(product_id)

            for mercadolibre in self.connectors:
                #_logger.info(_("Check %s in %s") % (product.display_name, mercadolibre.name))
                #Binding to
                meli_id = False
                if self.meli_id:
                    meli_id = self.meli_id.split(",")
                else:
                    meli_id = [False]
                for mid in meli_id:
                    product.mercadolibre_unbind_from( account=mercadolibre, meli_id=mid )

class ProductTemplateBindUpdate(models.TransientModel):

    _name = "mercadolibre.binder.update.wiz"
    _description = "Wizard de Product Template MercadoLibre Binder Update"

    update_odoo_product = fields.Boolean(string="Update Odoo Products")
    update_odoo_product_variants = fields.Boolean(string="Update Odoo Product Variants")
    update_images = fields.Boolean(string="Update images")
    update_stock = fields.Boolean(string="Only update stock")
    update_price = fields.Boolean(string="Only update price")
    update_binding = fields.Boolean(string="Only update binding (Revincular)")

    # --- Template orphan cleanup fields ---
    tmpl_orphan_action = fields.Selection([
        ('tmpl_analyze', 'Analizar vinculaciones huérfanas'),
        ('tmpl_rebind_sku', 'Re-vincular por SKU (buscar template activo)'),
        ('tmpl_delete_orphans', 'Eliminar vinculaciones huérfanas (sin template o template archivado + ML muerta)'),
        ('tmpl_delete_with_variants', 'Eliminar vinculación + variantes huérfanas'),
    ], string="Accion de huérfanos", help="Acciones para gestionar vinculaciones de template huérfanas")

    def binding_product_template_update(self, context=None):

        context = context or self.env.context

        #_logger.info("binding_product_template_update (MercadoLibre)")

        company = self.env.user.company_id
        bind_ids = ('active_ids' in context and context['active_ids']) or []
        bindobj = self.env['mercadolibre.product_template']

        res = {}

        for bind_id in bind_ids:

            bindT = bindobj.browse(bind_id)
            if bindT:
                if (self.update_binding):
                    _logger.info("binding_product_template_update (REVINCULAR)")
                    bindT.product_template_rebind(unbind_template=False)
                else:
                    bindT.product_template_update()

    def binding_product_template_orphan_cleanup(self, context=None):
        """Execute orphan cleanup action on selected template bindings."""
        context = context or self.env.context

        warningobj = self.env['meli.warning']
        bind_ids = ('active_ids' in context and context['active_ids']) or []

        if not bind_ids:
            return warningobj.info(title='LIMPIEZA DE TEMPLATES', message="No hay vinculaciones seleccionadas.")

        bindobj = self.env['mercadolibre.product_template'].with_context(active_test=False)
        bindings = bindobj.search([('id', 'in', bind_ids)])

        action = self.tmpl_orphan_action

        if not action:
            return warningobj.info(title='LIMPIEZA DE TEMPLATES', message="Seleccione una accion antes de ejecutar.")

        if action == 'tmpl_analyze':
            return self._tmpl_orphan_analyze(bindings)
        elif action == 'tmpl_rebind_sku':
            return self._tmpl_orphan_rebind_by_sku(bindings)
        elif action == 'tmpl_delete_orphans':
            return self._tmpl_orphan_delete(bindings, with_variants=False)
        elif action == 'tmpl_delete_with_variants':
            return self._tmpl_orphan_delete(bindings, with_variants=True)

    def _tmpl_orphan_analyze(self, bindings):
        """Analyze orphaned template bindings."""
        warningobj = self.env['meli.warning']

        total = len(bindings)
        unassigned = bindings.filtered(lambda b: not b.product_tmpl_id)
        archived = bindings.filtered(lambda b: b.product_tmpl_id and not b.product_tmpl_id.active)
        healthy = bindings.filtered(lambda b: b.product_tmpl_id and b.product_tmpl_id.active)

        # Check rebindable by SKU
        rebindable = 0
        for bind in unassigned | archived:
            if bind.sku and bind.sku != 'False':
                tmpl = self.env['product.template'].search([
                    ('default_code', '=', bind.sku), ('active', '=', True)
                ], limit=1)
                if not tmpl:
                    # Try via product.product
                    prod = self.env['product.product'].search([
                        ('default_code', '=', bind.sku), ('active', '=', True)
                    ], limit=1)
                    if prod:
                        tmpl = prod.product_tmpl_id
                if tmpl:
                    rebindable += 1

        # Count variant bindings that would also become orphaned
        orphan_variant_count = sum(len(b.variant_bindings) for b in unassigned | archived)

        report_lines = []
        report_lines.append("<h3>Análisis de %d vinculaciones de template</h3>" % total)
        report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
        report_lines.append(
            "<tr style='background:#f0f0f0'>"
            "<th style='padding:6px 10px;text-align:left'>Categoría</th>"
            "<th style='padding:6px 10px;text-align:right'>Cantidad</th>"
            "<th style='padding:6px 10px;text-align:left'>Acción recomendada</th></tr>"
        )

        rows = [
            ('#d4edda', 'Saludables (template activo)', len(healthy), 'Sin acción'),
            ('#f8d7da', 'Template desasignado', len(unassigned),
             'Re-vincular por SKU (%d recuperables)' % rebindable if rebindable else 'Eliminar'),
            ('#fff3cd', 'Producto archivado en Odoo', len(archived),
             'Re-vincular por SKU o eliminar'),
        ]

        for color, label, count, action_text in rows:
            if count > 0:
                pct = round(100.0 * count / total, 1) if total else 0
                report_lines.append(
                    "<tr style='background:%s'>"
                    "<td style='padding:4px 10px'>%s</td>"
                    "<td style='padding:4px 10px;text-align:right'>%d (%s%%)</td>"
                    "<td style='padding:4px 10px;font-size:0.9em'>%s</td></tr>" % (
                        color, label, count, pct, action_text
                    )
                )

        report_lines.append("</table>")
        report_lines.append("<br/><p><b>Vinculaciones de variante afectadas:</b> %d</p>" % orphan_variant_count)

        return warningobj.info(
            title='ANÁLISIS TEMPLATES - %d vinculaciones' % total,
            message="Análisis completado",
            message_html="\n".join(report_lines)
        )

    def _tmpl_orphan_rebind_by_sku(self, bindings):
        """Rebind orphaned template bindings by matching SKU to active product.template."""
        warningobj = self.env['meli.warning']

        to_rebind = bindings.filtered(
            lambda b: not b.product_tmpl_id or (b.product_tmpl_id and not b.product_tmpl_id.active)
        )

        if not to_rebind:
            return warningobj.info(
                title='RE-VINCULAR TEMPLATES',
                message="No se encontraron templates sin producto o con producto archivado."
            )

        rebound = []
        not_found = []
        errors = []

        for bind in to_rebind:
            sku = bind.sku
            if not sku or sku == 'False' or sku.startswith('['):
                # Try to get SKU from first variant binding
                for vb in bind.variant_bindings:
                    if vb.sku and vb.sku != 'False':
                        sku = vb.sku
                        break

            if not sku or sku == 'False':
                not_found.append({'conn_id': bind.conn_id or '', 'sku': '', 'reason': 'Sin SKU'})
                continue

            # Search for active product by SKU
            product = self.env['product.product'].search([
                ('default_code', '=', sku), ('active', '=', True)
            ], limit=1)

            if not product:
                not_found.append({'conn_id': bind.conn_id or '', 'sku': sku, 'reason': 'Producto activo no encontrado'})
                continue

            tmpl = product.product_tmpl_id
            old_tmpl = bind.product_tmpl_id

            try:
                # Check unique constraint
                existing = self.env['mercadolibre.product_template'].with_context(active_test=False).search([
                    ('connection_account', '=', bind.connection_account.id),
                    ('conn_id', '=', bind.conn_id),
                    ('product_tmpl_id', '=', tmpl.id),
                    ('id', '!=', bind.id),
                ], limit=1)

                if existing:
                    not_found.append({
                        'conn_id': bind.conn_id or '', 'sku': sku,
                        'reason': 'Ya existe vinculación para ese template'
                    })
                    continue

                bind.sudo().write({'product_tmpl_id': tmpl.id})
                rebound.append({
                    'conn_id': bind.conn_id or '',
                    'sku': sku,
                    'new_tmpl': tmpl.display_name,
                    'old_tmpl': old_tmpl.display_name if old_tmpl else '(sin template)',
                })
            except Exception as e:
                errors.append({'conn_id': bind.conn_id or '', 'sku': sku, 'error': str(e)[:80]})

        report_lines = []
        report_lines.append("<h3>Re-vinculación de templates: %d procesadas</h3>" % len(to_rebind))

        if rebound:
            report_lines.append("<h4 style='color:green'>Re-vinculadas: %d</h4>" % len(rebound))
            report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
            report_lines.append(
                "<tr style='background:#d4edda'><th style='padding:4px 8px'>ML Id</th>"
                "<th style='padding:4px 8px'>SKU</th><th style='padding:4px 8px'>Nuevo Template</th>"
                "<th style='padding:4px 8px'>Anterior</th></tr>"
            )
            for r in rebound[:50]:
                report_lines.append(
                    "<tr><td style='padding:2px 8px'>%s</td><td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td><td style='padding:2px 8px;color:#888'>%s</td></tr>" % (
                        r['conn_id'], r['sku'], r['new_tmpl'], r['old_tmpl']))
            report_lines.append("</table>")

        if not_found:
            report_lines.append("<h4 style='color:orange'>No encontradas: %d</h4>" % len(not_found))
            report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
            report_lines.append(
                "<tr style='background:#fff3cd'><th style='padding:4px 8px'>ML Id</th>"
                "<th style='padding:4px 8px'>SKU</th><th style='padding:4px 8px'>Razón</th></tr>"
            )
            for n in not_found[:30]:
                report_lines.append(
                    "<tr><td style='padding:2px 8px'>%s</td><td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td></tr>" % (n['conn_id'], n['sku'], n['reason']))
            report_lines.append("</table>")

        if errors:
            report_lines.append("<h4 style='color:red'>Errores: %d</h4>" % len(errors))
            for e in errors[:10]:
                report_lines.append("<p>%s - %s</p>" % (e['conn_id'], e['error']))

        return warningobj.info(
            title='RE-VINCULAR TEMPLATES - %d exitosas, %d no encontradas' % (len(rebound), len(not_found)),
            message="Re-vinculación completada",
            message_html="\n".join(report_lines)
        )

    def _tmpl_orphan_delete(self, bindings, with_variants=False):
        """Delete orphaned template bindings."""
        warningobj = self.env['meli.warning']

        orphaned = bindings.filtered(
            lambda b: not b.product_tmpl_id or (b.product_tmpl_id and not b.product_tmpl_id.active)
        )

        if not orphaned:
            return warningobj.info(
                title='ELIMINAR TEMPLATES HUÉRFANOS',
                message="No se encontraron templates huérfanos entre los seleccionados."
            )

        details = []
        variant_count = 0
        for bind in orphaned:
            vcount = len(bind.variant_bindings)
            variant_count += vcount
            details.append({
                'conn_id': bind.conn_id or '',
                'sku': bind.sku or '',
                'name': (bind.name or '')[:40],
                'reason': 'Sin template' if not bind.product_tmpl_id else 'Archivado',
                'variants': vcount,
            })

        count = len(orphaned)
        skipped = len(bindings) - count

        try:
            if with_variants:
                for bind in orphaned:
                    if bind.variant_bindings:
                        bind.variant_bindings.sudo().unlink()
            orphaned.sudo().unlink()
        except Exception as e:
            _logger.error("Error deleting orphaned template bindings: %s", e)
            return warningobj.info(title='ERROR', message="Error: %s" % str(e))

        report_lines = []
        report_lines.append("<h3>%d templates huérfanos eliminados</h3>" % count)
        if with_variants:
            report_lines.append("<p>%d vinculaciones de variante también eliminadas</p>" % variant_count)
        report_lines.append("<p>%d omitidos (no huérfanos)</p>" % skipped)
        report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
        report_lines.append(
            "<tr style='background:#f0f0f0'><th style='padding:4px 8px'>ML Id</th>"
            "<th style='padding:4px 8px'>SKU</th><th style='padding:4px 8px'>Nombre</th>"
            "<th style='padding:4px 8px'>Razón</th><th style='padding:4px 8px'>Variantes</th></tr>"
        )
        for d in details[:50]:
            report_lines.append(
                "<tr><td style='padding:2px 8px'>%s</td><td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td><td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px;text-align:center'>%d</td></tr>" % (
                    d['conn_id'], d['sku'], d['name'], d['reason'], d['variants']))
        report_lines.append("</table>")

        return warningobj.info(
            title='ELIMINADOS - %d templates' % count,
            message="%d templates huérfanos eliminados" % count,
            message_html="\n".join(report_lines)
        )


class ProductVariantBindUpdate(models.TransientModel):

    _name = "mercadolibre.binder.variant.update.wiz"
    _description = "Wizard de Product Variant MercadoLibre Binder Update"

    update_odoo_product = fields.Boolean(string="Update Full Odoo Product")
    #update_odoo_product_variants = fields.Boolean(string="Update Odoo Product Variants")
    #update_images = fields.Boolean(string="Update images")
    update_stock = fields.Boolean(string="Solo actualizar stock")
    update_price = fields.Boolean(string="Solo actualiza precios")

    update_stock_planified = fields.Boolean(string="Marcar para actualizar stock por cron",help="El cron se ocupara de actualizar estas publicaciones",default=False)
    unblock_product_stock = fields.Boolean(string="Desbloquear producto")

    # --- Stock cleanup fields ---
    cleanup_action = fields.Selection([
        ('analyze', 'Analizar estado real en ML'),
        ('unbind_dead', 'Desvincular publicaciones muertas (cerradas/404/inactivas)'),
        ('unbind_closed', 'Desvincular solo publicaciones cerradas'),
        ('unbind_not_found', 'Desvincular solo items 404 (no existen en ML)'),
        ('unbind_inactive', 'Desvincular solo publicaciones inactivas'),
        ('unbind_variation_not_found', 'Desvincular variantes no encontradas'),
        ('reset_errors', 'Resetear errores y marcar para reintentar'),
        ('force_stock_update', 'Forzar actualizacion de stock ahora'),
    ], string="Accion de limpieza", help="Seleccione la accion de limpieza a ejecutar sobre las vinculaciones seleccionadas")

    # --- Orphan cleanup fields ---
    orphan_action = fields.Selection([
        ('orphan_analyze', 'Analizar vinculaciones huérfanas'),
        ('orphan_rebind_sku', 'Re-vincular por SKU (desasignados y archivados → busca producto activo)'),
        ('orphan_reactivate', 'Reactivar productos archivados que tienen publicaciones activas'),
        ('orphan_delete', 'Eliminar vinculaciones huérfanas irrecuperables'),
        ('orphan_delete_archived', 'Eliminar vinculaciones de productos archivados (incluye plantilla)'),
    ], string="Accion de huérfanos", help="Acciones para gestionar vinculaciones huérfanas (sin producto asociado o con producto archivado)")

    cleanup_report = fields.Text(string="Resultado del analisis", readonly=True)

    def binding_product_variant_update(self, context=None):

        context = context or self.env.context

        #_logger.info("binding_product_variant_update (MercadoLibre)")

        warningobj = self.env['meli.warning']
        company = self.env.user.company_id
        bind_ids = ('active_ids' in context and context['active_ids']) or []
        bindobj = self.env['mercadolibre.product']

        rest = []
        correct = []

        for bind_id in bind_ids:

            bind = bindobj.browse(bind_id)
            if bind:
                if self.unblock_product_stock:
                    bind.product_meli_unblock()

                if self.update_odoo_product:
                    res = bind.product_update()
                    if res and 'error' in res:
                        rest.append(res)
                    correct.append("Id: "+str(bind.conn_id)+" Product:"+str(bind.product_id.default_code))

                if self.update_price:
                    res = bind.product_post_price(context=context)
                    if res and 'error' in res:
                        rest.append(res)
                    correct.append("Id: "+str(bind.conn_id)+" Product:"+str(bind.product_id.default_code)+" Price:"+str(bind.price))

                if self.update_stock:
                    res = bind.product_post_stock(context=context)
                    if res and 'error' in res:
                        rest.append(res)
                    correct.append("Id: "+str(bind.conn_id)+" Product:"+str(bind.product_id.default_code)+" Stock:"+str(bind.stock))

                if self.update_stock_planified:
                    bind.meli_stock_status = 'update'
                    correct.append("Id: "+str(bind.conn_id)+" Product:"+str(bind.product_id.default_code)+" Stock Status:"+str(bind.meli_stock_status))

        if len(rest):
            return warningobj.info( title='STOCK POST WARNING', message="Revisar publicaciones", message_html="<h3>Correct</h3>"+str(correct)+"<br/>"+"<h2>Errores</h2>"+str(rest), context = { "rjson": rest })

        return rest

    def binding_product_variant_stock_cleanup(self, context=None):
        """Execute stock cleanup action on selected variant bindings."""
        context = context or self.env.context

        warningobj = self.env['meli.warning']
        company = self.env.user.company_id
        bind_ids = ('active_ids' in context and context['active_ids']) or []
        bindobj = self.env['mercadolibre.product']

        if not bind_ids:
            return warningobj.info(title='LIMPIEZA DE STOCK', message="No hay vinculaciones seleccionadas.")

        bindings = bindobj.browse(bind_ids)
        action = self.cleanup_action

        if not action:
            return warningobj.info(title='LIMPIEZA DE STOCK', message="Seleccione una accion de limpieza antes de ejecutar.")

        if action == 'analyze':
            return self._cleanup_analyze(bindings)
        elif action == 'unbind_dead':
            return self._cleanup_unbind_by_status(bindings, [
                'revision_closed', 'revision_not_found', 'revision_inactive'
            ], "Publicaciones muertas (cerradas/404/inactivas)",
               ml_statuses=['closed', 'not_found', 'inactive', 'deleted'])
        elif action == 'unbind_closed':
            return self._cleanup_unbind_by_status(bindings, ['revision_closed'], "Publicaciones cerradas",
                                                  ml_statuses=['closed'])
        elif action == 'unbind_not_found':
            return self._cleanup_unbind_by_status(bindings, ['revision_not_found'], "Items 404",
                                                  ml_statuses=['not_found'])
        elif action == 'unbind_inactive':
            return self._cleanup_unbind_by_status(bindings, ['revision_inactive'], "Publicaciones inactivas",
                                                  ml_statuses=['inactive'])
        elif action == 'unbind_variation_not_found':
            return self._cleanup_unbind_by_status(bindings, ['revision_variation_not_found'], "Variantes no encontradas")
        elif action == 'reset_errors':
            return self._cleanup_reset_errors(bindings)
        elif action == 'force_stock_update':
            return self._cleanup_force_stock_update(bindings)

    def _refresh_ml_status_batch(self, bindings):
        """Batch refresh meli_last_status by calling ML API for each binding.

        Groups bindings by account to reuse meli connection instances.
        Updates meli_last_status and triggers meli_stock_status recalculation.
        Returns dict with counts: {refreshed, errors, skipped}.
        """
        refreshed = 0
        errors = 0
        skipped = 0

        # Group by account for connection reuse
        account_bindings = {}
        for bind in bindings:
            acc_id = bind.connection_account.id if bind.connection_account else False
            if acc_id not in account_bindings:
                account_bindings[acc_id] = (bind.connection_account, self.env['mercadolibre.product'])
            account_bindings[acc_id] = (account_bindings[acc_id][0], account_bindings[acc_id][1] | bind)

        for acc_id, (account, acc_bindings) in account_bindings.items():
            if not account:
                skipped += len(acc_bindings)
                continue

            meli = None
            try:
                meli = self.env['meli.util'].get_new_instance(account.company_id, account)
            except Exception as e:
                _logger.warning("Could not get meli instance for account %s: %s", account.name, e)
                skipped += len(acc_bindings)
                continue

            if not meli or meli.need_login():
                skipped += len(acc_bindings)
                continue

            for bind in acc_bindings:
                meli_id = bind.conn_id or bind.meli_id
                if not meli_id:
                    skipped += 1
                    continue

                try:
                    response = meli.get("/items/" + meli_id, {'access_token': meli.access_token})
                    rjson = response.json()

                    write_vals = {}

                    if rjson and "error" in rjson:
                        status_code = rjson.get("status")
                        if status_code == 404:
                            write_vals = {
                                'meli_last_status': 'not_found',
                                'meli_stock_status': 'revision_not_found',
                                'stock_error': 'not_found:404',
                            }
                        elif status_code in (401, 403):
                            write_vals = {
                                'meli_stock_status': 'revision_forbidden',
                                'stock_error': 'forbidden:%s' % status_code,
                            }
                        else:
                            errors += 1
                            continue
                    elif rjson and "status" in rjson:
                        ml_status = rjson["status"]
                        if ml_status in ('active', 'paused', 'closed', 'under_review', 'inactive'):
                            if bind.meli_last_status != ml_status:
                                write_vals['meli_last_status'] = ml_status

                    if write_vals:
                        bind.sudo().write(write_vals)
                        # Recalculate stock status based on new ML status
                        bind._meli_stock_status()

                    refreshed += 1

                except Exception as e:
                    _logger.warning("Error refreshing ML status for %s: %s", meli_id, e)
                    errors += 1

        return {'refreshed': refreshed, 'errors': errors, 'skipped': skipped}

    def _cleanup_analyze(self, bindings):
        """Analyze real status of bindings by checking ML API and show summary report."""
        warningobj = self.env['meli.warning']

        # Refresh ML status from API before analyzing
        refresh_result = self._refresh_ml_status_batch(bindings)

        # Count current statuses (now updated)
        status_counts = {}
        for bind in bindings:
            st = bind.meli_stock_status or 'sin_estado'
            status_counts[st] = status_counts.get(st, 0) + 1

        # Build a summary report grouped by status
        total = len(bindings)
        # Get human-readable labels from the selection field
        try:
            status_labels = dict(self.env['mercadolibre.product']._fields['meli_stock_status'].selection)
        except Exception:
            status_labels = {}

        report_lines = []
        report_lines.append("<h3>Analisis de %d vinculaciones seleccionadas</h3>" % total)
        report_lines.append(
            "<p style='color:#666'>Estado ML actualizado desde API: %d refrescadas, %d errores, %d omitidas</p>" % (
                refresh_result['refreshed'], refresh_result['errors'], refresh_result['skipped']
            )
        )
        report_lines.append("<table style='border-collapse:collapse;width:100%'>")
        report_lines.append("<tr style='background:#f0f0f0'><th style='padding:4px 8px;text-align:left'>Estado</th>"
                          "<th style='padding:4px 8px;text-align:right'>Cantidad</th>"
                          "<th style='padding:4px 8px;text-align:left'>Accion sugerida</th></tr>")

        # Suggested actions per status
        suggested_actions = {
            'updated': 'OK - Sin accion necesaria',
            'updated_with_warning': 'Revisar avisos',
            'update': 'Actualizar stock (cron o manual)',
            'update_rt': 'Actualizar stock RT',
            'revision': 'Revisar manualmente',
            'revision_error': 'Resetear errores y reintentar',
            'revision_unmoved': 'Forzar actualizacion de stock',
            'revision_blocked': 'Desbloquear producto',
            'revision_blocked_multiorigin': 'Revisar MultiOrigen en ML',
            'revision_fulfillment': 'Sin accion - Gestionado por ML Fulfillment',
            'revision_has_bids': 'Esperar a que finalicen las ventas',
            'revision_under_review': 'Esperar revision de ML',
            'revision_closed': 'Desvincular - Publicacion cerrada',
            'revision_inactive': 'Desvincular - Publicacion inactiva',
            'revision_not_modifiable': 'Sin accion - Stock no modificable en ML',
            'revision_not_found': 'Desvincular - Item no existe en ML',
            'revision_sku_mismatch': 'Revisar SKU manualmente',
            'revision_variation_not_found': 'Desvincular o revincular variante',
            'revision_forbidden': 'Verificar cuenta de ML',
            'multiwarehouse': 'Actualizar manualmente en ML',
        }

        # Sort by count descending
        for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
            label = status_labels.get(status, status)
            action = suggested_actions.get(status, 'Revisar')
            pct = round(100.0 * count / total, 1)
            color = '#d4edda' if status in ('updated',) else (
                '#fff3cd' if status in ('update', 'update_rt', 'updated_with_warning', 'revision_unmoved') else '#f8d7da'
            )
            report_lines.append(
                "<tr style='background:%s'><td style='padding:4px 8px'>%s</td>"
                "<td style='padding:4px 8px;text-align:right'>%d (%s%%)</td>"
                "<td style='padding:4px 8px;font-size:0.9em'>%s</td></tr>" % (
                    color, label, count, pct, action
                )
            )

        report_lines.append("</table>")

        # Add actionable summary
        dead_count = sum(status_counts.get(s, 0) for s in ['revision_closed', 'revision_not_found', 'revision_inactive'])
        error_count = status_counts.get('revision_error', 0)
        unmoved_count = status_counts.get('revision_unmoved', 0)

        if dead_count or error_count or unmoved_count:
            report_lines.append("<br/><h4>Acciones recomendadas:</h4><ul>")
            if dead_count:
                report_lines.append("<li><b>Desvincular publicaciones muertas:</b> %d vinculaciones (cerradas/404/inactivas) que se pueden eliminar</li>" % dead_count)
            if error_count:
                report_lines.append("<li><b>Resetear errores:</b> %d vinculaciones con error que se pueden reintentar</li>" % error_count)
            if unmoved_count:
                report_lines.append("<li><b>Forzar stock:</b> %d vinculaciones sin movimientos que se pueden forzar</li>" % unmoved_count)
            report_lines.append("</ul>")

        return warningobj.info(
            title='ANALISIS DE STOCK - %d vinculaciones' % total,
            message="Analisis completado",
            message_html="\n".join(report_lines)
        )

    def _cleanup_unbind_by_status(self, bindings, target_statuses, action_label, ml_statuses=None):
        """Unbind (delete) bindings matching target stock statuses or ML statuses.

        Args:
            bindings: recordset of mercadolibre.product
            target_statuses: list of meli_stock_status values to match
            action_label: human-readable label for the report
            ml_statuses: optional list of meli_last_status values as fallback
        """
        warningobj = self.env['meli.warning']

        if ml_statuses:
            to_unbind = bindings.filtered(
                lambda b: b.meli_stock_status in target_statuses or b.meli_last_status in ml_statuses
            )
        else:
            to_unbind = bindings.filtered(lambda b: b.meli_stock_status in target_statuses)
        skipped = bindings - to_unbind

        if not to_unbind:
            return warningobj.info(
                title='LIMPIEZA DE STOCK',
                message="No se encontraron vinculaciones con estado '%s' entre las seleccionadas." % action_label,
            )

        # Collect info before deletion
        unbind_details = []
        for bind in to_unbind:
            matched_by = 'stock: %s' % (bind.meli_stock_status or '')
            if ml_statuses and bind.meli_last_status in ml_statuses and bind.meli_stock_status not in target_statuses:
                matched_by = 'ML: %s' % (bind.meli_last_status or '')
            unbind_details.append({
                'conn_id': bind.conn_id or '',
                'conn_variation_id': bind.conn_variation_id or '',
                'sku': bind.sku or '',
                'product': bind.product_id.default_code or bind.product_id.name or '',
                'status': matched_by,
                'error': bind.stock_error or '',
            })

        # Perform unbind: clear binding fields and delete the binding record
        count = len(to_unbind)
        try:
            to_unbind.sudo().unlink()
        except Exception as e:
            _logger.error("Error unbinding variants: %s", e)
            return warningobj.info(
                title='ERROR EN LIMPIEZA',
                message="Error al desvincular: %s" % str(e),
            )

        # Build report
        report_lines = []
        report_lines.append("<h3>%s - %d vinculaciones desvinculadas</h3>" % (action_label, count))
        report_lines.append("<p>%d vinculaciones omitidas (no coinciden con el estado)</p>" % len(skipped))
        report_lines.append("<table style='border-collapse:collapse;width:100%'>")
        report_lines.append(
            "<tr style='background:#f0f0f0'>"
            "<th style='padding:4px 8px'>ML Id</th>"
            "<th style='padding:4px 8px'>Variacion</th>"
            "<th style='padding:4px 8px'>SKU</th>"
            "<th style='padding:4px 8px'>Producto</th>"
            "<th style='padding:4px 8px'>Estado</th>"
            "</tr>"
        )
        for d in unbind_details[:50]:  # Limit to 50 rows for readability
            report_lines.append(
                "<tr><td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td></tr>" % (
                    d['conn_id'], d['conn_variation_id'], d['sku'], d['product'], d['status']
                )
            )
        if len(unbind_details) > 50:
            report_lines.append("<tr><td colspan='5' style='padding:4px 8px'>... y %d mas</td></tr>" % (len(unbind_details) - 50))
        report_lines.append("</table>")

        return warningobj.info(
            title='LIMPIEZA COMPLETADA - %d desvinculadas' % count,
            message="%d vinculaciones eliminadas (%s)" % (count, action_label),
            message_html="\n".join(report_lines)
        )

    def _cleanup_reset_errors(self, bindings):
        """Reset stock errors and mark for retry via cron."""
        warningobj = self.env['meli.warning']

        error_statuses = ['revision_error', 'revision_sku_mismatch']
        to_reset = bindings.filtered(lambda b: b.meli_stock_status in error_statuses)

        if not to_reset:
            return warningobj.info(
                title='LIMPIEZA DE STOCK',
                message="No se encontraron vinculaciones con error entre las seleccionadas.",
            )

        count = len(to_reset)
        reset_details = []
        for bind in to_reset:
            reset_details.append("ML:%s SKU:%s Error:%s" % (
                bind.conn_id or '', bind.sku or '', (bind.stock_error or '')[:80]
            ))
            bind.sudo().write({
                'stock_error': '',
                'meli_stock_status': 'update',
            })

        report_lines = []
        report_lines.append("<h3>%d vinculaciones reseteadas y marcadas para reintentar</h3>" % count)
        report_lines.append("<p>El cron se encargara de actualizar el stock de estas publicaciones.</p>")
        report_lines.append("<ul>")
        for detail in reset_details[:30]:
            report_lines.append("<li>%s</li>" % detail)
        if len(reset_details) > 30:
            report_lines.append("<li>... y %d mas</li>" % (len(reset_details) - 30))
        report_lines.append("</ul>")

        return warningobj.info(
            title='ERRORES RESETEADOS - %d vinculaciones' % count,
            message="%d vinculaciones marcadas para reintentar" % count,
            message_html="\n".join(report_lines)
        )

    def _cleanup_force_stock_update(self, bindings):
        """Force immediate stock update on selected bindings."""
        warningobj = self.env['meli.warning']
        context = self.env.context

        # Filter: only update items that are in a retryable state
        retryable_statuses = [
            'update', 'update_rt', 'revision', 'revision_error',
            'revision_unmoved', 'revision_blocked', 'updated_with_warning',
        ]
        to_update = bindings.filtered(
            lambda b: b.meli_stock_status in retryable_statuses or not b.meli_stock_status
        )

        if not to_update:
            # If user explicitly asked, try all selected regardless of status
            to_update = bindings

        count = len(to_update)
        errors = []
        success = []

        for bind in to_update:
            try:
                # Unblock first if needed
                if bind.meli_stock_status == 'revision_blocked':
                    bind.product_meli_unblock()

                res = bind.product_post_stock(context=context)
                if res and 'error' in res:
                    errors.append("ML:%s SKU:%s Error:%s" % (
                        bind.conn_id or '', bind.sku or '', str(res.get('error', ''))[:80]
                    ))
                else:
                    success.append("ML:%s SKU:%s Stock:%s" % (
                        bind.conn_id or '', bind.sku or '', bind.stock
                    ))
            except Exception as e:
                errors.append("ML:%s SKU:%s Exception:%s" % (
                    bind.conn_id or '', bind.sku or '', str(e)[:80]
                ))

        report_lines = []
        report_lines.append("<h3>Actualizacion forzada de stock: %d procesadas</h3>" % count)

        if success:
            report_lines.append("<h4 style='color:green'>Exitosas: %d</h4>" % len(success))
            report_lines.append("<ul>")
            for s in success[:20]:
                report_lines.append("<li>%s</li>" % s)
            if len(success) > 20:
                report_lines.append("<li>... y %d mas</li>" % (len(success) - 20))
            report_lines.append("</ul>")

        if errors:
            report_lines.append("<h4 style='color:red'>Errores: %d</h4>" % len(errors))
            report_lines.append("<ul>")
            for e in errors[:20]:
                report_lines.append("<li>%s</li>" % e)
            if len(errors) > 20:
                report_lines.append("<li>... y %d mas</li>" % (len(errors) - 20))
            report_lines.append("</ul>")

        return warningobj.info(
            title='STOCK ACTUALIZADO - %d exitosas, %d errores' % (len(success), len(errors)),
            message="Actualizacion forzada completada",
            message_html="\n".join(report_lines)
        )

    # =========================================================================
    # Orphan cleanup methods
    # =========================================================================

    def binding_product_variant_orphan_cleanup(self, context=None):
        """Execute orphan cleanup action on selected variant bindings."""
        context = context or self.env.context

        warningobj = self.env['meli.warning']
        bind_ids = ('active_ids' in context and context['active_ids']) or []

        if not bind_ids:
            return warningobj.info(title='LIMPIEZA DE HUÉRFANOS', message="No hay vinculaciones seleccionadas.")

        # Search with active_test=False to include archived/inactive bindings
        # Use search to get only records that actually exist in DB
        bindobj = self.env['mercadolibre.product'].with_context(active_test=False)
        bindings = bindobj.search([('id', 'in', bind_ids)])

        action = self.orphan_action

        if not action:
            return warningobj.info(title='LIMPIEZA DE HUÉRFANOS', message="Seleccione una accion antes de ejecutar.")

        if action == 'orphan_analyze':
            return self._orphan_analyze(bindings)
        elif action == 'orphan_rebind_sku':
            return self._orphan_rebind_by_sku(bindings)
        elif action == 'orphan_reactivate':
            return self._orphan_reactivate_products(bindings)
        elif action == 'orphan_delete':
            return self._orphan_delete(bindings)
        elif action == 'orphan_delete_archived':
            return self._orphan_delete_archived(bindings)

    def _orphan_analyze(self, bindings):
        """Analyze orphaned bindings and show a detailed report."""
        warningobj = self.env['meli.warning']

        # Refresh ML status from API before analyzing
        refresh_result = self._refresh_ml_status_batch(bindings)

        total = len(bindings)
        unassigned = bindings.filtered(lambda b: not b.product_id)
        product_archived = bindings.filtered(lambda b: b.product_id and not b.product_id.active)
        ml_dead = bindings.filtered(lambda b: b.meli_last_status in ('closed', 'not_found', 'inactive', 'deleted'))
        healthy = bindings.filtered(lambda b: b.product_id and b.product_id.active and b.meli_last_status not in ('closed', 'not_found', 'inactive', 'deleted'))

        # Check how many unassigned could be rebound by SKU
        rebindable_count = 0
        for bind in unassigned:
            if bind.sku:
                product = self.env['product.product'].search([('default_code', '=', bind.sku)], limit=1)
                if product:
                    rebindable_count += 1

        # Check how many archived products have active ML publications
        reactivatable_count = 0
        for bind in product_archived:
            if bind.meli_last_status in ('active', 'paused'):
                reactivatable_count += 1

        report_lines = []
        report_lines.append("<h3>Análisis de %d vinculaciones seleccionadas</h3>" % total)
        report_lines.append(
            "<p style='color:#666'>Estado ML actualizado desde API: %d refrescadas, %d errores, %d omitidas</p>" % (
                refresh_result['refreshed'], refresh_result['errors'], refresh_result['skipped']
            )
        )
        report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
        report_lines.append(
            "<tr style='background:#f0f0f0'>"
            "<th style='padding:6px 10px;text-align:left'>Categoría</th>"
            "<th style='padding:6px 10px;text-align:right'>Cantidad</th>"
            "<th style='padding:6px 10px;text-align:left'>Acción recomendada</th></tr>"
        )

        rows = [
            ('#d4edda', 'Saludables (producto activo, ML OK)', len(healthy), 'Sin acción necesaria'),
            ('#f8d7da', 'Producto desasignado (sin product_id)', len(unassigned),
             'Re-vincular por SKU (%d recuperables)' % rebindable_count if rebindable_count else 'Eliminar vinculación'),
            ('#fff3cd', 'Producto archivado en Odoo', len(product_archived),
             'Reactivar producto (%d con ML activa)' % reactivatable_count if reactivatable_count else 'Revisar manualmente'),
            ('#f8d7da', 'Publicación muerta en ML (cerrada/404/inactiva)', len(ml_dead), 'Eliminar vinculación'),
        ]

        for color, label, count, action_text in rows:
            if count > 0:
                pct = round(100.0 * count / total, 1) if total else 0
                report_lines.append(
                    "<tr style='background:%s'>"
                    "<td style='padding:4px 10px'>%s</td>"
                    "<td style='padding:4px 10px;text-align:right'>%d (%s%%)</td>"
                    "<td style='padding:4px 10px;font-size:0.9em'>%s</td></tr>" % (
                        color, label, count, pct, action_text
                    )
                )

        report_lines.append("</table>")

        # Detailed list of unassigned bindings
        if unassigned:
            report_lines.append("<br/><h4>Detalle: Vinculaciones sin producto (%d)</h4>" % len(unassigned))
            report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
            report_lines.append(
                "<tr style='background:#f0f0f0'>"
                "<th style='padding:4px 8px'>ML Id</th>"
                "<th style='padding:4px 8px'>Variación</th>"
                "<th style='padding:4px 8px'>SKU</th>"
                "<th style='padding:4px 8px'>Nombre</th>"
                "<th style='padding:4px 8px'>Recuperable</th></tr>"
            )
            for bind in unassigned[:30]:
                recoverable = 'No'
                if bind.sku:
                    product = self.env['product.product'].search([('default_code', '=', bind.sku)], limit=1)
                    if product:
                        recoverable = 'Sí → %s' % product.display_name
                report_lines.append(
                    "<tr><td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td></tr>" % (
                        bind.conn_id or '', bind.conn_variation_id or '',
                        bind.sku or '', (bind.name or '')[:40], recoverable
                    )
                )
            if len(unassigned) > 30:
                report_lines.append("<tr><td colspan='5' style='padding:4px 8px'>... y %d más</td></tr>" % (len(unassigned) - 30))
            report_lines.append("</table>")

        # Recommendations
        report_lines.append("<br/><h4>Acciones recomendadas:</h4><ul>")
        if rebindable_count:
            report_lines.append("<li><b>Re-vincular por SKU:</b> %d vinculaciones se pueden recuperar automáticamente</li>" % rebindable_count)
        if reactivatable_count:
            report_lines.append("<li><b>Reactivar productos:</b> %d productos archivados tienen publicaciones activas en ML</li>" % reactivatable_count)
        if len(unassigned) - rebindable_count > 0:
            report_lines.append("<li><b>Eliminar irrecuperables:</b> %d vinculaciones sin producto y sin SKU válido</li>" % (len(unassigned) - rebindable_count))
        if ml_dead:
            report_lines.append("<li><b>Limpiar ML muertas:</b> %d vinculaciones con publicaciones cerradas/eliminadas en ML</li>" % len(ml_dead))
        if not any([rebindable_count, reactivatable_count, len(unassigned), len(ml_dead)]):
            report_lines.append("<li>Todas las vinculaciones seleccionadas están saludables.</li>")
        report_lines.append("</ul>")

        return warningobj.info(
            title='ANÁLISIS DE HUÉRFANOS - %d vinculaciones' % total,
            message="Análisis completado",
            message_html="\n".join(report_lines)
        )

    def _orphan_rebind_by_sku(self, bindings):
        """Try to rebind orphaned bindings by matching SKU to an active product.product.

        Handles two cases:
        - Bindings without product_id (unassigned)
        - Bindings with archived product_id (searches for an active product with same SKU)
        """
        warningobj = self.env['meli.warning']

        # Include both: unassigned AND archived product bindings
        to_rebind = bindings.filtered(
            lambda b: not b.product_id or (b.product_id and not b.product_id.active)
        )

        if not to_rebind:
            return warningobj.info(
                title='RE-VINCULAR POR SKU',
                message="No se encontraron vinculaciones sin producto o con producto archivado entre las seleccionadas."
            )

        rebound = []
        not_found = []
        already_active = []
        errors = []
        to_delete = self.env['mercadolibre.product']

        for bind in to_rebind:
            sku = bind.sku
            old_product = bind.product_id
            was_archived = bool(old_product and not old_product.active)

            if not sku or sku == 'False':
                not_found.append({
                    'conn_id': bind.conn_id or '',
                    'sku': '',
                    'reason': 'Sin SKU definido',
                })
                continue

            # Search for ACTIVE product by SKU (default_code) - exclude archived
            product = self.env['product.product'].search([
                ('default_code', '=', sku),
                ('active', '=', True),
            ], limit=1)
            if not product:
                # Also try with barcode
                if bind.barcode:
                    product = self.env['product.product'].search([
                        ('barcode', '=', bind.barcode),
                        ('active', '=', True),
                    ], limit=1)

            if not product:
                not_found.append({
                    'conn_id': bind.conn_id or '',
                    'sku': sku,
                    'reason': 'Sin producto activo con ese SKU en Odoo',
                })
                continue

            # Skip if it's the same product (already correctly linked)
            if old_product and old_product.id == product.id and old_product.active:
                already_active.append({
                    'conn_id': bind.conn_id or '',
                    'sku': sku,
                    'product': product.display_name,
                })
                continue

            try:
                # Check if a variant binding already exists for this product (unique constraint)
                existing_bind = self.env['mercadolibre.product'].with_context(active_test=False).search([
                    ('connection_account', '=', bind.connection_account.id),
                    ('conn_id', '=', bind.conn_id),
                    ('conn_variation_id', '=', bind.conn_variation_id),
                    ('product_id', '=', product.id),
                    ('id', '!=', bind.id),
                ], limit=1)
                if existing_bind:
                    # Binding already exists for this product — mark orphan for deletion
                    to_delete |= bind
                    rebound.append({
                        'conn_id': bind.conn_id or '',
                        'sku': sku,
                        'product': product.display_name,
                        'old_product': (old_product.display_name if was_archived else '(sin producto)') + ' [duplicado eliminado]',
                    })
                    continue

                write_vals = {'product_id': product.id}

                # Find template binding for this conn_id
                tmpl_bind = self.env['mercadolibre.product_template'].with_context(active_test=False).search([
                    ('connection_account', '=', bind.connection_account.id),
                    ('conn_id', '=', bind.conn_id),
                ], limit=1)
                if tmpl_bind:
                    write_vals['binding_product_tmpl_id'] = tmpl_bind.id
                    # Only update template's product_tmpl_id if no constraint conflict
                    if tmpl_bind.product_tmpl_id != product.product_tmpl_id:
                        existing_tmpl = self.env['mercadolibre.product_template'].with_context(active_test=False).search([
                            ('connection_account', '=', bind.connection_account.id),
                            ('conn_id', '=', bind.conn_id),
                            ('product_tmpl_id', '=', product.product_tmpl_id.id),
                            ('id', '!=', tmpl_bind.id),
                        ], limit=1)
                        if not existing_tmpl:
                            tmpl_bind.sudo().write({'product_tmpl_id': product.product_tmpl_id.id})

                bind.sudo().write(write_vals)
                rebound.append({
                    'conn_id': bind.conn_id or '',
                    'sku': sku,
                    'product': product.display_name,
                    'old_product': old_product.display_name if was_archived else '(sin producto)',
                })
            except Exception as e:
                errors.append({
                    'conn_id': bind.conn_id or '',
                    'sku': sku,
                    'error': str(e)[:80],
                })

        # Batch delete duplicates collected during the loop
        if to_delete:
            try:
                to_delete.sudo().unlink()
            except Exception as e:
                _logger.error("Error deleting duplicate orphan bindings: %s", e)

        # Build report
        report_lines = []
        report_lines.append("<h3>Re-vinculación por SKU: %d procesadas</h3>" % len(to_rebind))

        if rebound:
            report_lines.append("<h4 style='color:green'>Re-vinculadas exitosamente: %d</h4>" % len(rebound))
            report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
            report_lines.append(
                "<tr style='background:#d4edda'>"
                "<th style='padding:4px 8px'>ML Id</th>"
                "<th style='padding:4px 8px'>SKU</th>"
                "<th style='padding:4px 8px'>Nuevo Producto</th>"
                "<th style='padding:4px 8px'>Anterior</th></tr>"
            )
            for r in rebound[:50]:
                report_lines.append(
                    "<tr><td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px;color:#888'>%s</td></tr>" % (
                        r['conn_id'], r['sku'], r['product'], r['old_product']
                    )
                )
            if len(rebound) > 50:
                report_lines.append("<tr><td colspan='4' style='padding:4px 8px'>... y %d más</td></tr>" % (len(rebound) - 50))
            report_lines.append("</table>")

        if not_found:
            report_lines.append("<h4 style='color:orange'>No se pudo re-vincular: %d</h4>" % len(not_found))
            report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
            report_lines.append(
                "<tr style='background:#fff3cd'>"
                "<th style='padding:4px 8px'>ML Id</th>"
                "<th style='padding:4px 8px'>SKU</th>"
                "<th style='padding:4px 8px'>Razón</th></tr>"
            )
            for n in not_found[:30]:
                report_lines.append(
                    "<tr><td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td></tr>" % (
                        n['conn_id'], n['sku'], n['reason']
                    )
                )
            report_lines.append("</table>")

        if errors:
            report_lines.append("<h4 style='color:red'>Errores: %d</h4>" % len(errors))
            for e in errors[:10]:
                report_lines.append("<p>ML:%s SKU:%s - %s</p>" % (e['conn_id'], e['sku'], e['error']))

        return warningobj.info(
            title='RE-VINCULAR - %d exitosas, %d no encontradas, %d errores' % (len(rebound), len(not_found), len(errors)),
            message="Re-vinculación por SKU completada",
            message_html="\n".join(report_lines)
        )

    def _orphan_reactivate_products(self, bindings):
        """Reactivate archived Odoo products that still have active ML publications."""
        warningobj = self.env['meli.warning']

        # Find bindings with archived products that have active/paused ML status
        archived_with_active_ml = bindings.filtered(
            lambda b: b.product_id and not b.product_id.active and b.meli_last_status in ('active', 'paused')
        )

        if not archived_with_active_ml:
            return warningobj.info(
                title='REACTIVAR PRODUCTOS',
                message="No se encontraron productos archivados con publicaciones activas en ML."
            )

        reactivated = []
        errors = []

        # Group by product template to reactivate entire templates
        templates_done = set()
        for bind in archived_with_active_ml:
            product = bind.product_id
            template = product.product_tmpl_id
            if template.id in templates_done:
                continue
            templates_done.add(template.id)

            try:
                template.sudo().write({'active': True})
                reactivated.append({
                    'template': template.display_name,
                    'product': product.display_name,
                    'conn_id': bind.conn_id or '',
                    'ml_status': bind.meli_last_status or '',
                })
            except Exception as e:
                errors.append({
                    'template': template.display_name,
                    'error': str(e)[:80],
                })

        report_lines = []
        report_lines.append("<h3>Reactivación de productos: %d templates procesados</h3>" % len(templates_done))

        if reactivated:
            report_lines.append("<h4 style='color:green'>Reactivados: %d</h4>" % len(reactivated))
            report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
            report_lines.append(
                "<tr style='background:#d4edda'>"
                "<th style='padding:4px 8px'>Template</th>"
                "<th style='padding:4px 8px'>ML Id</th>"
                "<th style='padding:4px 8px'>Estado ML</th></tr>"
            )
            for r in reactivated[:30]:
                report_lines.append(
                    "<tr><td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td></tr>" % (
                        r['template'], r['conn_id'], r['ml_status']
                    )
                )
            report_lines.append("</table>")

        if errors:
            report_lines.append("<h4 style='color:red'>Errores: %d</h4>" % len(errors))
            for e in errors[:10]:
                report_lines.append("<p>%s - %s</p>" % (e['template'], e['error']))

        return warningobj.info(
            title='REACTIVADOS - %d productos, %d errores' % (len(reactivated), len(errors)),
            message="Reactivación completada",
            message_html="\n".join(report_lines)
        )

    def _orphan_delete(self, bindings):
        """Delete orphaned bindings that cannot be recovered."""
        warningobj = self.env['meli.warning']

        # Only delete bindings that are truly orphaned
        orphaned = bindings.filtered(
            lambda b: (
                not b.product_id  # Unassigned
                or (b.product_id and not b.product_id.active and b.meli_last_status in ('closed', 'not_found', 'inactive', 'deleted'))  # Archived + dead ML
            )
        )

        if not orphaned:
            return warningobj.info(
                title='ELIMINAR HUÉRFANOS',
                message="No se encontraron vinculaciones huérfanas irrecuperables entre las seleccionadas. "
                        "Solo se eliminan vinculaciones sin producto o con producto archivado Y publicación muerta en ML."
            )

        # Collect info before deletion
        delete_details = []
        for bind in orphaned:
            delete_details.append({
                'conn_id': bind.conn_id or '',
                'conn_variation_id': bind.conn_variation_id or '',
                'sku': bind.sku or '',
                'name': (bind.name or '')[:40],
                'reason': 'Sin producto' if not bind.product_id else 'Archivado + ML %s' % (bind.meli_last_status or ''),
            })

        count = len(orphaned)
        skipped = len(bindings) - count

        try:
            orphaned.sudo().unlink()
        except Exception as e:
            _logger.error("Error deleting orphaned bindings: %s", e)
            return warningobj.info(
                title='ERROR AL ELIMINAR',
                message="Error: %s" % str(e),
            )

        report_lines = []
        report_lines.append("<h3>%d vinculaciones huérfanas eliminadas</h3>" % count)
        report_lines.append("<p>%d vinculaciones omitidas (no cumplen criterio de huérfano irrecuperable)</p>" % skipped)
        report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
        report_lines.append(
            "<tr style='background:#f0f0f0'>"
            "<th style='padding:4px 8px'>ML Id</th>"
            "<th style='padding:4px 8px'>Variación</th>"
            "<th style='padding:4px 8px'>SKU</th>"
            "<th style='padding:4px 8px'>Nombre</th>"
            "<th style='padding:4px 8px'>Razón</th></tr>"
        )
        for d in delete_details[:50]:
            report_lines.append(
                "<tr><td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td></tr>" % (
                    d['conn_id'], d['conn_variation_id'], d['sku'], d['name'], d['reason']
                )
            )
        if len(delete_details) > 50:
            report_lines.append("<tr><td colspan='5' style='padding:4px 8px'>... y %d más</td></tr>" % (len(delete_details) - 50))
        report_lines.append("</table>")

        return warningobj.info(
            title='HUÉRFANOS ELIMINADOS - %d registros' % count,
            message="%d vinculaciones huérfanas eliminadas" % count,
            message_html="\n".join(report_lines)
        )

    def _orphan_delete_archived(self, bindings):
        """Delete variant bindings where the product is archived, and cascade-delete
        the parent template binding when all its variant bindings are removed."""
        warningobj = self.env['meli.warning']

        # Filter: product exists but is archived
        archived = bindings.filtered(
            lambda b: b.product_id and not b.product_id.active
        )

        if not archived:
            return warningobj.info(
                title='ELIMINAR VINCULACIONES ARCHIVADAS',
                message="No se encontraron vinculaciones con producto archivado entre las seleccionadas."
            )

        # Collect parent template bindings before deletion
        tmpl_bind_obj = self.env['mercadolibre.product_template'].with_context(active_test=False)
        tmpl_bind_ids = set()
        delete_details = []

        for bind in archived:
            if bind.binding_product_tmpl_id:
                tmpl_bind_ids.add(bind.binding_product_tmpl_id.id)
            delete_details.append({
                'conn_id': bind.conn_id or '',
                'conn_variation_id': bind.conn_variation_id or '',
                'sku': bind.sku or '',
                'name': (bind.name or '')[:40],
                'product': (bind.product_id.display_name or '')[:30],
            })

        variant_count = len(archived)
        skipped = len(bindings) - variant_count

        try:
            archived.sudo().unlink()
        except Exception as e:
            _logger.error("Error deleting archived variant bindings: %s", e)
            return warningobj.info(
                title='ERROR AL ELIMINAR',
                message="Error al eliminar vinculaciones de variantes: %s" % str(e),
            )

        # Cascade: delete template bindings that have no remaining variant bindings
        tmpl_deleted = 0
        tmpl_details = []
        if tmpl_bind_ids:
            tmpl_orphans = tmpl_bind_obj.search([
                ('id', 'in', list(tmpl_bind_ids)),
                ('variant_bindings', '=', False),
            ])
            if tmpl_orphans:
                for tb in tmpl_orphans:
                    tmpl_details.append({
                        'conn_id': tb.conn_id or '',
                        'name': (tb.name or '')[:40],
                        'product': (tb.product_tmpl_id.display_name or '')[:30] if tb.product_tmpl_id else 'Sin template',
                    })
                tmpl_deleted = len(tmpl_orphans)
                try:
                    tmpl_orphans.sudo().unlink()
                except Exception as e:
                    _logger.error("Error deleting orphaned template bindings: %s", e)

        # Build report
        report_lines = []
        report_lines.append("<h3>%d vinculaciones de variantes eliminadas</h3>" % variant_count)
        report_lines.append("<p>%d vinculaciones omitidas (producto no archivado)</p>" % skipped)
        report_lines.append("<p><b>%d vinculaciones de plantilla eliminadas en cascada</b> (sin variantes restantes)</p>" % tmpl_deleted)

        report_lines.append("<h4>Variantes eliminadas</h4>")
        report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
        report_lines.append(
            "<tr style='background:#f0f0f0'>"
            "<th style='padding:4px 8px'>ML Id</th>"
            "<th style='padding:4px 8px'>Variación</th>"
            "<th style='padding:4px 8px'>SKU</th>"
            "<th style='padding:4px 8px'>Nombre</th>"
            "<th style='padding:4px 8px'>Producto (archivado)</th></tr>"
        )
        for d in delete_details[:50]:
            report_lines.append(
                "<tr><td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td>"
                "<td style='padding:2px 8px'>%s</td></tr>" % (
                    d['conn_id'], d['conn_variation_id'], d['sku'], d['name'], d['product']
                )
            )
        if len(delete_details) > 50:
            report_lines.append("<tr><td colspan='5' style='padding:4px 8px'>... y %d más</td></tr>" % (len(delete_details) - 50))
        report_lines.append("</table>")

        if tmpl_details:
            report_lines.append("<h4>Plantillas eliminadas en cascada</h4>")
            report_lines.append("<table style='border-collapse:collapse;width:100%%'>")
            report_lines.append(
                "<tr style='background:#f0f0f0'>"
                "<th style='padding:4px 8px'>ML Id</th>"
                "<th style='padding:4px 8px'>Nombre</th>"
                "<th style='padding:4px 8px'>Template (archivado)</th></tr>"
            )
            for d in tmpl_details[:50]:
                report_lines.append(
                    "<tr><td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td>"
                    "<td style='padding:2px 8px'>%s</td></tr>" % (
                        d['conn_id'], d['name'], d['product']
                    )
                )
            if len(tmpl_details) > 50:
                report_lines.append("<tr><td colspan='3' style='padding:4px 8px'>... y %d más</td></tr>" % (len(tmpl_details) - 50))
            report_lines.append("</table>")

        return warningobj.info(
            title='ARCHIVADOS ELIMINADOS - %d variantes, %d plantillas' % (variant_count, tmpl_deleted),
            message="%d vinculaciones de variantes eliminadas, %d plantillas en cascada" % (variant_count, tmpl_deleted),
            message_html="\n".join(report_lines)
        )

class ProductVariantBindToMercadoLibre(models.TransientModel):

    _name = "mercadolibre.variant.binder.wiz"
    _description = "Wizard de Product Variant MercadoLibre Binder"
    _inherit = "ocapi.binder.wiz"

    connectors = fields.Many2many("mercadolibre.account", string='MercadoLibre Accounts')
    meli_id = fields.Char(string="MercadoLibre Product Id (MLXYYYYYYY: MLA123456789 )")
    meli_id_variation = fields.Char(string="MercadoLibre Product Variation Id ( ZZZZZZZZZ: 123456789 )")
    bind_only = fields.Boolean( string="Bind only using SKU", help="Solo asociar producto y variantes usando SKU (No modifica el producto de Odoo)" )

    def product_product_add_to_connector(self, context=None):

        context = context or self.env.context

        #_logger.info("product_product_add_to_connector (MercadoLibre)")

        company = self.env.user.company_id
        product_ids = context['active_ids']
        product_obj = self.env['product.product']

        res = {}
        for product_id in product_ids:

            product = product_obj.browse(product_id)

            for mercadolibre in self.connectors:
                #_logger.info(_("Check %s in %s") % (product.display_name, mercadolibre.name))
                meli_id = False
                meli_id_variation = False
                #Binding to
                if self.meli_id:
                    meli_id = self.meli_id

                if self.meli_id_variation:
                    meli_id_variation = self.meli_id_variation

                if self.bind_only:
                    bind_only = self.bind_only

                product.mercadolibre_bind_to( mercadolibre, meli_id=meli_id, meli_id_variation=meli_id_variation, bind_only=bind_only  )


    def product_product_remove_from_connector(self, context=None):

        context = context or self.env.context

        #_logger.info("product_product_remove_from_connector (MercadoLibre)")

        company = self.env.user.company_id
        product_ids = context['active_ids']
        product_obj = self.env['product.product']

        res = {}
        for product_id in product_ids:

            product = product_obj.browse(product_id)

            for mercadolibre in self.connectors:
                #_logger.info(_("Check %s in %s") % (product.display_name, mercadolibre.name))
                #Binding to
                meli_id = False
                meli_id_variation = False
                if self.meli_id:
                    meli_id = self.meli_id
                if self.meli_id_variation:
                    meli_id_variation = self.meli_id_variation
                product.mercadolibre_unbind_from( account=mercadolibre, meli_id=meli_id, meli_id_variation=meli_id_variation )

class ProductTemplatePostExtended(models.TransientModel):

    _inherit = "mercadolibre.product.template.post"

    force_meli_new_pub = fields.Boolean(string="Crear una nueva publicación")
    connectors = fields.Many2one("mercadolibre.account",string="MercadoLibre Account",required=True)
    force_meli_new_title = fields.Char(string="New Title")
    force_meli_new_price = fields.Float(string="New Price")
    force_meli_new_pricelist = fields.Many2one("product.pricelist",string="New Price List")
    force_meli_listing_type = fields.Selection([("free","Libre"),
                                                ("bronze","Bronce/Clásica-(UY)"),
                                                ("silver","Plata"),
                                                ("gold","Oro"),
                                                ("gold_premium","Gold Premium/Oro Premium"),
                                                ("gold_special","Gold Special/Clásica/Premium-(UY)"),
                                                ("gold_pro","Oro Pro")],
                                                string='Tipo de lista',
                                                help='Tipo de lista')

    force_meli_channel_mkt = fields.Many2many( "meli.channel.mkt", string="Channels", index=True )


    def product_template_post(self, context=None):

        context = context or self.env.context
        company = self.env.user.company_id
        #_logger.info("multiple product_template_post: context: " + str(context))

        product_ids = []
        if ('active_ids' in context):
            product_ids = context['active_ids']
        product_obj = self.env['product.template']
        warningobj = self.env['meli.warning']

        res = {}

        #_logger.info("wizard > context in product_template_post:")
        #_logger.info(self.env.context)
        custom_context = {
            'connectors': self.connectors,
            'force_meli_new_pub': self.force_meli_new_pub,

            'force_meli_variant': self.force_meli_variant,
            'force_meli_pub': self.force_meli_pub,
            'force_meli_active': self.force_meli_active,

            'post_stock': self.post_stock,
            'post_price': self.post_price,

            'force_meli_new_title': self.force_meli_new_title,
            'force_meli_new_price': self.force_meli_new_price,
            'force_meli_new_pricelist': self.force_meli_new_pricelist,
            'force_meli_listing_type': self.force_meli_listing_type

        }
        posted_products = 0
        for product_id in product_ids:

            productT = product_obj.browse(product_id)

            for account in self.connectors:
                comp = account.company_id or company
                meli = self.env['meli.util'].get_new_instance( comp, account )
                if meli:
                    if meli.need_login():
                        return meli.redirect_login()
                    #res = productT.with_context(custom_context).product_template_post( context=None, account=account, meli=meli )

                    if (self.force_meli_pub and not productT.meli_pub):
                        productT.meli_pub = True

                    if (self.force_meli_variant):
                        productT.meli_pub_as_variant = True

                    if (productT.meli_pub):

                        if self.post_stock:
                            res = productT.with_context(custom_context).product_template_post_stock(meli=meli,account=account)
                        if self.post_price:
                            res = productT.with_context(custom_context).product_template_post_price(meli=meli,account=account)
                        if not self.post_stock and not self.post_price:
                            res = productT.with_context(custom_context).product_template_post(context=None, account=account, meli=meli)

                    if res and 'name' in res:
                        return res
                    if (productT.meli_pub):
                        posted_products+=1

        if (posted_products==0 and not 'name' in res):
            res = warningobj.info( title='MELI WARNING', message="Se intentaron publicar 0 productos. Debe forzar las publicaciones o marcar el producto con el campo Meli Publication, debajo del titulo.", message_html="" )

        return res

class ProductTemplateBindingPostExtended(models.TransientModel):

    _name = "mercadolibre.product.template.binding.post"
    _inherit = "mercadolibre.product.template.post"
    _description = "Mercadolibre Product Template Binding"

    def product_template_post(self, context=None):

        context = context or self.env.context
        company = self.env.user.company_id
        #_logger.info("multiple product_template_post: context: " + str(context))

        product_bindT_ids = []
        if ('active_ids' in context):
            product_bindT_ids = context['active_ids']
        product_bindT_obj = self.env['mercadolibre.product_template']
        warningobj = self.env['meli.warning']

        res = {}

        #_logger.info("wizard > context in product_template_post:")
        #_logger.info(self.env.context)
        custom_context = {
            'connectors': self.connectors,
            'force_meli_new_pub': self.force_meli_new_pub,

            'force_meli_pub': self.force_meli_pub,
            'force_meli_active': self.force_meli_active,

            'post_stock': self.post_stock,
            'post_price': self.post_price,

            'force_meli_new_title': self.force_meli_new_title,
            'force_meli_new_price': self.force_meli_new_price,
            'force_meli_new_pricelist': self.force_meli_new_pricelist,

        }
        posted_products = 0
        connectors = self.connectors and self.connectors.ids or []
        for product_bindT_id in product_bindT_ids:

            product_bindT = product_bindT_obj.browse(product_bindT_id)
            account = product_bindT.connection_account
            if account.id in connectors:

                comp = account.company_id or company
                meli = self.env['meli.util'].get_new_instance( comp, account )

                if meli:
                    if meli.need_login():
                        return meli.redirect_login()
                    #res = productT.with_context(custom_context).product_template_post( context=None, account=account, meli=meli )

                    if (self.force_meli_pub and not product_bindT.meli_pub):
                        product_bindT.meli_pub = True

                    if (product_bindT.meli_pub):

                        if self.post_stock:
                            res = product_bindT.with_context(custom_context).product_template_post_stock(meli=meli,account=account)
                        if self.post_price:
                            res = product_bindT.with_context(custom_context).product_template_post_price(meli=meli,account=account)
                        if not self.post_stock and not self.post_price:
                            res = product_bindT.with_context(custom_context).product_template_post(context=None, account=account, meli=meli)

                    if res and 'name' in res:
                        return res

                    if (product_bindT.meli_pub):
                        posted_products+=1

        if (posted_products==0 and not 'name' in res):
            res = warningobj.info( title='MELI WARNING', message="Se intentaron publicar 0 productos. Debe forzar las publicaciones o marcar el producto con el campo Meli Publication, debajo del titulo.", message_html="" )

        return res


class NotificationsProcessWiz(models.TransientModel):
    _name = "mercadolibre.notification.wiz"
    _description = "MercadoLibre Notifications Wiz"

    connection_account = fields.Many2one( "mercadolibre.account", string='MercadoLibre Account',help="Cuenta de mercadolibre origen de la publicación")
    reprocess_force = fields.Boolean(string="Reprocess",default=False)

    def process_notifications( self, context=None ):

        context = context or self.env.context

        #_logger.info("process_notifications (MercadoLibre)")
        noti_ids = ('active_ids' in context and context['active_ids']) or []
        noti_obj = self.env['mercadolibre.notification']

        custom_context = {
            'connection_account': self.connection_account,
            'reprocess_force': self.reprocess_force,
        }

        try:
            meli = None
            if self.connection_account:
                meli = self.env['meli.util'].get_new_instance( self.connection_account.company_id, self.connection_account )
                if meli.need_login():
                    return meli.redirect_login()

            ##if not self.connection_account:
            #    raise UserError('Connection Account not defined!')
            for noti_id in noti_ids:

                #_logger.info("Processing notification: %s " % (noti_id) )

                noti = noti_obj.browse(noti_id)
                ret = []
                if noti:
                    reti = None
                    if self.connection_account and noti.connection_account and noti.connection_account.id==self.connection_account.id:
                        reti = noti.with_context(custom_context).process_notification(meli=meli)
                    else:
                        reti = noti.with_context(custom_context).process_notification()
                    if reti:
                        ret.append(str(reti))

        except Exception as e:
            #_logger.info("process_notifications > Error procesando notificacion")
            _logger.error(e, exc_info=True)
            _logger.error(str(ret))
            #MeliRollback( self )
            raise e

        #_logger.info("Processing notification result: %s " % (str(ret)) )


#class SaleOrderGlobalInvoice(models.TransientModel):
#
#    _name = "sale.order.global.invoice.meli.wiz"
#    _description = "Wizard de Factura Global"


class product_template_import(models.TransientModel):

    _inherit = "mercadolibre.product.template.import"

    sku_filter = fields.Selection([
        ('all', 'Todas'),
        ('no_sku', 'Sin SKU en ML'),
        ('no_sku_no_barcode', 'Sin SKU y sin Barcode'),
        ('no_sku_odoo', 'SKU no existe en Odoo'),
    ], default='all', string='Filtrar por SKU',
       help='Filtro adicional sobre publicaciones según SKU/Barcode')

    sync_filter = fields.Selection([
        ('all', 'Todos'),
        ('synced', 'Sincronizados'),
        ('not_synced', 'No sincronizados'),
    ], default='all', string='Sincronización',
       help='Filtrar por estado de sincronización con Odoo')

    # Cached product_lines JSON for re-filtering without re-querying ML
    product_lines_json = fields.Text(string="Product Lines Cache", readonly=True)

    # Maestro indicator
    maestro_count = fields.Integer(string="Maestros", readonly=True)
    maestro_active = fields.Boolean(string="Maestro activo", readonly=True)

    # Alertas de binding (banners): publicaciones con SKU duplicado en Odoo y sin vincular
    duplicate_count = fields.Integer(string="Duplicados", compute="_compute_binding_alerts")
    unbound_count = fields.Integer(string="Sin vincular", compute="_compute_binding_alerts")
    duplicate_skus = fields.Char(string="SKUs duplicados", compute="_compute_binding_alerts")

    @api.depends('import_lines.import_status', 'import_lines.sku')
    def _compute_binding_alerts(self):
        for rec in self:
            dups = rec.import_lines.filtered(lambda l: l.import_status == 'duplicate')
            rec.duplicate_count = len(dups)
            rec.unbound_count = len(rec.import_lines.filtered(lambda l: l.import_status == 'missing'))
            skus = [s for s in dups.mapped('sku') if s]
            rec.duplicate_skus = ", ".join(skus[:20]) + ("…" if len(skus) > 20 else "")

    def list_meli_ids(self, context=None, config=None, meli=None):
        context = context or self.env.context
        company = self.env.user.company_id
        account_ids = ('active_ids' in context and context['active_ids']) or []
        account = self.env['mercadolibre.account'].browse(account_ids)
        odoo_meli_ids = (account and account.list_meli_ids()) or []
        return odoo_meli_ids

    def _get_account(self, context=None):
        """Helper: resolve account from context active_ids."""
        context = context or self.env.context
        account_ids = context.get('active_ids') or []
        return self.env['mercadolibre.account'].browse(account_ids)

    # ------------------------------------------------------------------
    # STEP 1: Consultar ML — fetch publication ids, build product_lines
    # ------------------------------------------------------------------
    def check_sync_status(self, context=None, config=None, meli=None):
        context = context or self.env.context
        account = self._get_account(context)
        if not account:
            return {'product_lines': [], 'actives_to_sync': '0', 'paused_to_sync': '0', 'closed_to_sync': '0'}

        company = (account and account.company_id) or self.env.user.company_id
        meli = meli or self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            return meli.redirect_login()

        # Use set for O(1) lookups instead of list
        odoo_meli_ids = set(account.list_meli_ids() or [])
        meli_id_filter = self.meli_id
        product_lines = []

        # Advanced batch flags: decide which ML statuses to actually fetch and
        # whether we should skip already-synced items entirely (saves time and
        # avoids cluttering the preview with items the user does not want).
        states_to_fetch, _effective_post_state, force_not_synced = self._effective_batch_filters()

        # Helper: fetch ids for a given status, classify as synced/missing
        def _fetch_and_classify(status, skip_synced=False):
            params = {'status': status}
            if meli_id_filter:
                params['meli_id'] = meli_id_filter
            fetched = account.fetch_list_meli_ids(params=params)
            total = len(fetched)
            to_sync = 0

            for mli in fetched:
                is_synced = mli in odoo_meli_ids
                if not is_synced:
                    to_sync += 1

                # When advanced batch flags force "not synced" mode we drop the
                # synced items right here so they do not bloat product_lines_json
                # or the preview tree.
                if skip_synced and is_synced:
                    continue

                # Basic line data - details filled via multiget below
                line_data = {
                    'meli_id': mli,
                    'meli_status': status,
                    'import_status': 'synced' if is_synced else 'missing',
                    'name': mli,  # Will be updated via multiget
                    'sku': '',    # SKU only via individual call (form open)
                    'meli_price': 0,
                    'meli_qty': 0,
                    'variations_count': 0,
                }
                product_lines.append(line_data)

            return to_sync, total

        _logger.info(
            "check_sync_status: states_to_fetch=%s force_not_synced=%s "
            "(batch_actives=%s, batch_paused=%s, batch_left=%s, post_state=%s)",
            states_to_fetch, force_not_synced,
            self.batch_actives_to_sync, self.batch_paused_to_sync,
            self.batch_left_to_sync, self.post_state,
        )

        actives_sync, actives_total = 0, 0
        if 'active' in states_to_fetch:
            actives_sync, actives_total = _fetch_and_classify('active', skip_synced=force_not_synced)

        paused_sync, paused_total = 0, 0
        if 'paused' in states_to_fetch:
            paused_sync, paused_total = _fetch_and_classify('paused', skip_synced=force_not_synced)

        closed_sync, closed_total = 0, 0
        if 'closed' in states_to_fetch:
            closed_sync, closed_total = _fetch_and_classify('closed', skip_synced=force_not_synced)

        # ----------------------------------------------------------------
        # MULTIGET: Fetch title, price, stock, variations count in batches
        # ML API allows max 20 items per request
        # MULTIGET: Si sync_filter='not_synced', solo hace multiget de los
        # no sincronizados (ahorra hasta 95% de requests en catálogos grandes)
        # Ejemplo: 25k total, 1.7k no sync → 87 batches en vez de 1,258
        # ----------------------------------------------------------------
        sync_filter = self.sync_filter or 'all'
        if product_lines:
            from datetime import datetime
            multiget_start = datetime.now()

            # MULTIGET: Filtrar antes del multiget cuando sync_filter='not_synced'
            if sync_filter == 'not_synced':
                lines_for_multiget = [pl for pl in product_lines if pl.get('import_status') not in ('synced', 'imported', 'duplicate')]
                _logger.info("REFATODO multiget inteligente: %d/%d items (solo no sincronizados)",
                             len(lines_for_multiget), len(product_lines))
            else:
                lines_for_multiget = product_lines

            total_items = len(lines_for_multiget)
            _logger.info("check_sync_status: fetching details via multiget for %s items", total_items)

            # Build a dict for quick lookup: meli_id -> line_data
            lines_by_id = {pl['meli_id']: pl for pl in product_lines}

            # Split meli_ids into batches of 20 (ML API limit)
            all_ids = [pl['meli_id'] for pl in lines_for_multiget]
            batch_size = 20
            batches = [all_ids[i:i + batch_size] for i in range(0, len(all_ids), batch_size)]
            total_batches = len(batches)

            items_updated = 0
            errors_count = 0

            for batch_idx, batch in enumerate(batches):
                try:
                    ids_str = ",".join(batch)
                    url = "/items?ids=%s&attributes=id,title,price,available_quantity,variations,seller_custom_field,attributes" % ids_str
                    response_raw = meli.get(url, {'access_token': meli.access_token})

                    # Handle Response object or dict
                    if hasattr(response_raw, 'json'):
                        response = response_raw.json()
                    else:
                        response = response_raw

                    if response and isinstance(response, list):
                        for item in response:
                            if item.get('code') == 200 and item.get('body'):
                                body = item['body']
                                item_id = body.get('id')
                                if item_id and item_id in lines_by_id:
                                    line = lines_by_id[item_id]
                                    line['name'] = (body.get('title') or item_id)[:80]
                                    line['meli_price'] = body.get('price') or 0
                                    line['meli_qty'] = body.get('available_quantity') or 0
                                    variations = body.get('variations') or []
                                    line['variations_count'] = len(variations) if variations else 1

                                    # Extract SKU from attributes or seller_custom_field
                                    sku = ''
                                    barcode = ''
                                    if body.get('attributes'):
                                        for att in body['attributes']:
                                            att_id = att.get('id', '')
                                            if att_id == 'SELLER_SKU':
                                                sku = att.get('value_name') or ''
                                            elif att_id == 'GTIN':
                                                barcode = att.get('value_name') or ''
                                    if not sku:
                                        sku = body.get('seller_custom_field') or ''

                                    # Extract SKUs/barcodes from ALL variations
                                    var_skus = []
                                    var_barcodes = []
                                    for var in variations:
                                        found_sku_in_var = False
                                        for att in (var.get('attributes') or []):
                                            att_id = att.get('id', '')
                                            if att_id == 'SELLER_SKU' and att.get('value_name'):
                                                var_skus.append(att['value_name'])
                                                found_sku_in_var = True
                                            elif att_id == 'GTIN' and att.get('value_name'):
                                                var_barcodes.append(att['value_name'])
                                        # Fallback per-variation: seller_custom_field
                                        if not found_sku_in_var and var.get('seller_custom_field'):
                                            var_skus.append(var['seller_custom_field'])

                                    line['sku'] = sku or ','.join(var_skus)
                                    line['barcode'] = barcode or ','.join(var_barcodes)
                                    items_updated += 1

                    # Log progress every 10 batches (200 items) for large lists
                    if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
                        elapsed = (datetime.now() - multiget_start).total_seconds()
                        _logger.info("  multiget progress: %s/%s batches (%.1fs)",
                                    batch_idx + 1, total_batches, elapsed)

                except Exception as e:
                    errors_count += 1
                    _logger.warning("check_sync_status multiget batch %s error: %s", batch_idx, str(e))
                    # Continue with next batch - don't stop on errors

            multiget_elapsed = (datetime.now() - multiget_start).total_seconds()
            _logger.info("check_sync_status: multiget completed in %.2fs - %s/%s items updated, %s errors",
                        multiget_elapsed, items_updated, total_items, errors_count)

        # Attachment/report link
        attachments = self.env["ir.attachment"].search([('res_id', '=', self.id)], order='id desc', limit=1)
        report_import_link = ""
        last_attachment = None
        if attachments:
            last_attachment = attachments[0]
            report_import_link = "/web/content/%s?download=true&access_token=%s" % (
                str(last_attachment.id), str(last_attachment.access_token))

        return {
            'actives_to_sync': "%s / %s" % (actives_sync, actives_total),
            'paused_to_sync': "%s / %s" % (paused_sync, paused_total),
            'closed_to_sync': "%s / %s" % (closed_sync, closed_total),
            'product_lines': product_lines,
            'report_import': last_attachment,
            'report_import_link': report_import_link,
        }

    # ------------------------------------------------------------------
    # Advanced batch flags helper
    # ------------------------------------------------------------------
    def _effective_batch_filters(self):
        """Translate the 'Batch avanzado' checkboxes into effective filters.

        The advanced flags are shortcuts for common sync workflows:
          - batch_actives_to_sync: only active publications NOT yet synced
          - batch_paused_to_sync:  only paused publications NOT yet synced
          - batch_left_to_sync:    anything NOT yet synced (honors post_state)

        Returns a tuple (states_to_fetch, effective_post_state, force_not_synced):
          - states_to_fetch: list of ML statuses to actually query from the API
          - effective_post_state: value to pass to _apply_filters as post_state_filter
            ('all' if multiple states are selected, single state otherwise)
          - force_not_synced: True when any batch flag is set, meaning the sync_filter
            must be overridden to 'not_synced' so already-imported items are hidden.

        When no batch flag is set, the method falls back to the user's post_state
        field without changing sync_filter.
        """
        states = []
        force_not_synced = False
        if self.batch_actives_to_sync:
            states.append('active')
            force_not_synced = True
        if self.batch_paused_to_sync:
            states.append('paused')
            force_not_synced = True
        if self.batch_left_to_sync:
            # "All lefts" means every not-synced item — do not restrict state here,
            # we will derive the states from post_state below.
            force_not_synced = True

        if not states:
            ps = self.post_state or 'all'
            if ps == 'all':
                states = ['active', 'paused', 'closed']
            else:
                states = [ps]

        if len(states) == 1:
            effective_post_state = states[0]
        else:
            # Multi-state selection. _apply_filters will accept the list directly.
            effective_post_state = 'all'

        return states, effective_post_state, force_not_synced

    # ------------------------------------------------------------------
    # Human-readable summary of the active filters / advanced options.
    # Used to enrich the "import_status" status bar so the user can always
    # tell which parameters produced the current preview.
    # ------------------------------------------------------------------
    def _build_filter_summary(self):
        """Return a short human-readable string like
        '[estado: Activas | sku: Sin SKU | sync: No sincronizados | batch: Pausadas | lote: 50 / off: 0 | forzar: meli_pub, imagenes]'.

        Only non-default options are listed so the string stays compact.
        """
        parts = []

        # Filtros básicos (los dropdowns visibles en el header)
        _post_state_labels = {
            'all': 'Todos', 'active': 'Activas',
            'paused': 'Pausadas', 'closed': 'Cerradas',
        }
        if self.post_state and self.post_state != 'all':
            parts.append("estado: %s" % _post_state_labels.get(self.post_state, self.post_state))

        _sku_filter_labels = {
            'all': 'Todas', 'no_sku': 'Sin SKU en ML',
            'no_sku_no_barcode': 'Sin SKU y sin Barcode',
            'no_sku_odoo': 'SKU no existe en Odoo',
        }
        if self.sku_filter and self.sku_filter != 'all':
            parts.append("sku: %s" % _sku_filter_labels.get(self.sku_filter, self.sku_filter))

        _sync_filter_labels = {
            'all': 'Todos', 'synced': 'Sincronizados',
            'not_synced': 'No sincronizados',
        }
        if self.sync_filter and self.sync_filter != 'all':
            parts.append("sync: %s" % _sync_filter_labels.get(self.sync_filter, self.sync_filter))

        # Batch avanzado — flags del bloque Opciones avanzadas
        _batch_labels = []
        if self.batch_actives_to_sync:
            _batch_labels.append("Activas")
        if self.batch_paused_to_sync:
            _batch_labels.append("Pausadas")
        if self.batch_left_to_sync:
            _batch_labels.append("Restantes")
        if _batch_labels:
            parts.append("batch: %s" % "+".join(_batch_labels))

        # Lote / offset siempre útiles cuando son != default
        if self.batch_processing_unit or self.batch_processing_unit_offset:
            parts.append("lote: %s / off: %s" % (
                self.batch_processing_unit or 0,
                self.batch_processing_unit_offset or 0,
            ))

        # Flags de forzado (solo si están activos)
        _force_labels = []
        if self.force_meli_pub:
            _force_labels.append("meli_pub")
        if self.force_import_images:
            _force_labels.append("imagenes")
        if self.force_create_variants:
            _force_labels.append("variantes")
        if self.force_dont_create:
            _force_labels.append("no_crear")
        if self.force_meli_website_published:
            _force_labels.append("web_pub")
        if self.force_meli_website_category_create_and_assign:
            _force_labels.append("web_cat")
        if _force_labels:
            parts.append("forzar: %s" % ", ".join(_force_labels))

        # meli_id individual, si lo hubo
        if self.meli_id:
            parts.append("meli_id: %s" % self.meli_id)

        return (" [%s]" % " | ".join(parts)) if parts else ""

    # ------------------------------------------------------------------
    # Filter helper: apply sku_filter + post_state on product_lines
    # ------------------------------------------------------------------
    def _apply_filters(self, product_lines, sku_filter=None, post_state_filter=None, sync_filter=None):
        """Filter product_lines by SKU filter, meli_status and/or sync status. Returns filtered list."""
        import json
        result = list(product_lines)

        # Filter by meli_status (post_state). Accepts a single string or a list
        # (the latter is used when batch_actives_to_sync + batch_paused_to_sync
        # are combined, so multiple states must pass through).
        if post_state_filter and post_state_filter != 'all':
            if isinstance(post_state_filter, (list, tuple, set)):
                allowed = set(post_state_filter)
                result = [pl for pl in result if pl.get('meli_status') in allowed]
            else:
                result = [pl for pl in result if pl.get('meli_status') == post_state_filter]

        # Filter by sync status
        sync_filter = sync_filter or 'all'
        if sync_filter == 'synced':
            # Include synced, created, and imported as "processed" statuses
            result = [pl for pl in result if pl.get('import_status') in ('synced', 'created', 'imported')]
        elif sync_filter == 'not_synced':
            result = [pl for pl in result if pl.get('import_status') not in ('synced', 'created', 'imported', 'duplicate')]

        # Filter by SKU
        sku_filter = sku_filter or 'all'
        if sku_filter != 'all':
            # For 'no_sku_odoo' filter, batch-check which SKUs exist in Odoo
            odoo_skus = set()
            if sku_filter == 'no_sku_odoo':
                all_skus = set()
                for pl in result:
                    sku = pl.get('sku') or ''
                    for s in sku.split(','):
                        s = s.strip()
                        if s:
                            all_skus.add(s)
                if all_skus:
                    found = self.env['product.product'].search([
                        ('default_code', 'in', list(all_skus))
                    ])
                    odoo_skus = set(found.mapped('default_code'))

            filtered = []
            for pl in result:
                sku = (pl.get('sku') or '').strip()
                barcode = (pl.get('barcode') or '').strip()
                if sku_filter == 'no_sku' and not sku:
                    filtered.append(pl)
                elif sku_filter == 'no_sku_no_barcode' and not sku and not barcode:
                    filtered.append(pl)
                elif sku_filter == 'no_sku_odoo':
                    # Include if SKU is empty OR none of its SKUs exist in Odoo
                    if not sku:
                        filtered.append(pl)
                    else:
                        sku_parts = [s.strip() for s in sku.split(',') if s.strip()]
                        if not any(s in odoo_skus for s in sku_parts):
                            filtered.append(pl)
            result = filtered

        return result

    def _create_import_lines(self, wizard_id, product_lines):
        """Create import_line records from product_lines dicts.
        MULTIGET: Batch create en bloques de 500 en lugar de 1 por 1.
        Para 1,736 líneas: de ~39 segundos a ~2-3 segundos.
        """
        line_obj = self.env["mercadolibre.products.import.line"]
        BATCH = 500
        vals_list = []
        for pline in product_lines:
            vals_list.append({
                "import_id": wizard_id,
                "name": pline.get("name") or pline.get("meli_id") or "",
                "meli_id": pline.get("meli_id") or "",
                "meli_status": pline.get("meli_status") or "",
                "sku": pline.get("sku") or "",
                "meli_price": pline.get("meli_price") or 0,
                "meli_qty": pline.get("meli_qty") or 0,
                "variations_count": pline.get("variations_count") or 0,
                "import_status": pline.get("import_status") or "pending",
                "error": pline.get("error") or "",
                "meli_permalink": pline.get("meli_permalink") or "",
                "meli_barcode": pline.get("barcode") or "",
            })
        # Crear en lotes de 500 para evitar timeouts con catálogos grandes
        for i in range(0, len(vals_list), BATCH):
            line_obj.create(vals_list[i:i + BATCH])

    def _get_maestro_info(self, context=None):
        """Return maestro count for the current account."""
        account = self._get_account(context or self.env.context)
        if not account:
            return 0
        return self.env["mercadolibre.product.maestro"].search_count([
            ('connection_account', '=', account.id)
        ])

    def _enrich_skus(self, product_lines, context=None):
        """Fetch real SKUs for items that have empty sku field.
        Uses multiget in batches of 20 requesting full variation data.
        Returns (enriched_product_lines, enriched_count)."""
        context = context or self.env.context
        account = self._get_account(context)
        if not account:
            return product_lines, 0

        # Identify items missing SKU
        missing_sku = [pl for pl in product_lines if not (pl.get('sku') or '').strip()]
        if not missing_sku:
            return product_lines, 0

        company = (account and account.company_id) or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            return product_lines, 0

        lines_by_id = {pl['meli_id']: pl for pl in product_lines}
        ids_to_fetch = [pl['meli_id'] for pl in missing_sku]
        batch_size = 20
        batches = [ids_to_fetch[i:i + batch_size] for i in range(0, len(ids_to_fetch), batch_size)]
        enriched = 0

        _logger.info("_enrich_skus: fetching SKUs for %s items (%s batches)",
                      len(ids_to_fetch), len(batches))

        for batch_idx, batch in enumerate(batches):
            try:
                ids_str = ",".join(batch)
                # Request full variation data including seller_custom_field
                url = "/items?ids=%s&attributes=id,variations,seller_custom_field,attributes" % ids_str
                response_raw = meli.get(url, {'access_token': meli.access_token})

                if hasattr(response_raw, 'json'):
                    response = response_raw.json()
                else:
                    response = response_raw

                if response and isinstance(response, list):
                    for item in response:
                        if item.get('code') == 200 and item.get('body'):
                            body = item['body']
                            item_id = body.get('id')
                            if item_id and item_id in lines_by_id:
                                line = lines_by_id[item_id]

                                # Item-level SKU
                                sku = ''
                                barcode = ''
                                if body.get('attributes'):
                                    for att in body['attributes']:
                                        att_id = att.get('id', '')
                                        if att_id == 'SELLER_SKU':
                                            sku = att.get('value_name') or ''
                                        elif att_id == 'GTIN':
                                            barcode = att.get('value_name') or ''
                                if not sku:
                                    sku = body.get('seller_custom_field') or ''

                                # Variation-level SKUs
                                var_skus = []
                                var_barcodes = []
                                for var in (body.get('variations') or []):
                                    found_sku_in_var = False
                                    for att in (var.get('attributes') or []):
                                        att_id = att.get('id', '')
                                        if att_id == 'SELLER_SKU' and att.get('value_name'):
                                            var_skus.append(att['value_name'])
                                            found_sku_in_var = True
                                        elif att_id == 'GTIN' and att.get('value_name'):
                                            var_barcodes.append(att['value_name'])
                                    if not found_sku_in_var and var.get('seller_custom_field'):
                                        var_skus.append(var['seller_custom_field'])

                                new_sku = sku or ','.join(var_skus)
                                new_barcode = barcode or ','.join(var_barcodes)
                                if new_sku or new_barcode:
                                    line['sku'] = new_sku
                                    line['barcode'] = new_barcode
                                    enriched += 1

            except Exception as e:
                _logger.warning("_enrich_skus batch %s error: %s", batch_idx, str(e))

        _logger.info("_enrich_skus: enriched %s / %s items", enriched, len(ids_to_fetch))
        return product_lines, enriched

    # ------------------------------------------------------------------
    # STEP 2: Show import wizard — create new wizard with import_lines
    # (same pattern as orders wizard: self.create() + return act_window)
    # ------------------------------------------------------------------
    def show_import_wizard(self, context=None):
        import json
        context = context or self.env.context
        refview = get_ref_view(self, "meli_oerp_multiple", 'view_product_template_import_multiple')

        # Get product_lines from sync_status (fresh query) or from cached JSON (re-filter)
        sync_status = context.get("sync_status") or {}
        product_lines = sync_status.get("product_lines") or []

        # If no fresh data but we have cached JSON, use that
        cached_json = context.get("product_lines_json") or (self.product_lines_json if product_lines == [] else "")
        if not product_lines and cached_json:
            try:
                product_lines = json.loads(cached_json)
            except Exception:
                product_lines = []

        # Maestro info
        maestro_count = self._get_maestro_info(context)

        res_id = self.create({
            "title": "Importar",
            "post_state": self.post_state,
            "sku_filter": self.sku_filter,
            "sync_filter": self.sync_filter,
            "meli_id": self.meli_id,
            "force_meli_pub": self.force_meli_pub,
            "force_import_images": self.force_import_images,
            "force_create_variants": self.force_create_variants,
            "force_dont_create": self.force_dont_create,
            "force_meli_website_published": self.force_meli_website_published,
            "force_meli_website_category_create_and_assign": self.force_meli_website_category_create_and_assign,
            "batch_processing_unit": self.batch_processing_unit,
            "batch_processing_unit_offset": self.batch_processing_unit_offset,
            "batch_actives_to_sync": self.batch_actives_to_sync,
            "batch_paused_to_sync": self.batch_paused_to_sync,
            "batch_left_to_sync": self.batch_left_to_sync,
            "report_import": (self.report_import and self.report_import.id),
            "report_import_link": (self.report_import_link or ""),
            "actives_to_sync": self.actives_to_sync or "",
            "paused_to_sync": self.paused_to_sync or "",
            "closed_to_sync": self.closed_to_sync or "",
            "import_status": self.import_status or "",
            "product_lines_json": json.dumps(product_lines) if product_lines else "",
            "maestro_count": maestro_count,
            "maestro_active": maestro_count > 0,
        })

        # Apply ALL filters (including post_state which must be re-applied on the full JSON).
        # When advanced batch flags are active, use the derived post_state (possibly a list)
        # and force sync_filter='not_synced' so already-imported items are hidden.
        _states_to_fetch, _effective_ps, _force_ns = self._effective_batch_filters()
        if len(_states_to_fetch) == 1:
            _post_state_for_filter = _states_to_fetch[0]
        elif _force_ns and len(_states_to_fetch) < 3:
            # Multiple specific states were chosen via batch flags (e.g. actives + paused)
            _post_state_for_filter = list(_states_to_fetch)
        else:
            _post_state_for_filter = self.post_state
        # After a direct import, show ALL results (errors sorted first by the sort below)
        # instead of filtering to not_synced — the user wants to see the full batch outcome.
        if context.get("post_import"):
            _sync_filter_for_filter = 'all'
        else:
            _sync_filter_for_filter = 'not_synced' if _force_ns else self.sync_filter

        filtered = self._apply_filters(product_lines,
                                        sku_filter=self.sku_filter,
                                        post_state_filter=_post_state_for_filter,
                                        sync_filter=_sync_filter_for_filter)
        _logger.info("Filters applied (estado=%s, sku=%s, sync=%s, batch_actives=%s, batch_paused=%s, batch_left=%s): %s / %s lines",
                     _post_state_for_filter, self.sku_filter or 'all',
                     _sync_filter_for_filter or 'all',
                     self.batch_actives_to_sync, self.batch_paused_to_sync, self.batch_left_to_sync,
                     len(filtered), len(product_lines))

        # Sort: errors/duplicates/missing FIRST, then pending, then processed (created/synced/imported)
        _status_order = {'error': 0, 'duplicate': 1, 'missing': 2, 'pending': 3, 'created': 4, 'synced': 5, 'imported': 6}
        filtered.sort(key=lambda x: _status_order.get(x.get('import_status', 'pending'), 9))

        self._create_import_lines(res_id.id, filtered)

        return {
            'name': _("Importar Masivamente ML (...)"),
            'view_mode': 'form',
            'view_id': (refview and refview[1]),
            'res_id': (res_id and res_id.id),
            'res_model': 'mercadolibre.product.template.import',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'domain': [],
            'context': context
        }

    # ------------------------------------------------------------------
    # Button: "Aplicar Filtro" — re-filter cached lines
    # If SKU filter is active and many items lack SKU data, warns first
    # then enriches + filters on second click.
    # ------------------------------------------------------------------
    def apply_filter(self, context=None):
        """Re-filter the cached product_lines using current filters.
        When SKU filter is active, enriches empty-SKU items from ML API."""
        import json
        context = context or self.env.context

        # Read cached product_lines
        product_lines = []
        if self.product_lines_json:
            try:
                product_lines = json.loads(self.product_lines_json)
            except Exception:
                _logger.warning("apply_filter: could not parse product_lines_json")
                product_lines = []

        if not product_lines:
            _logger.info("apply_filter: no cached product_lines, re-querying ML")
            return self.check_import_status(context=context)

        sku_filter = self.sku_filter or 'all'

        # If SKU filter is active, check if enrichment is needed
        if sku_filter != 'all':
            empty_sku_count = sum(1 for pl in product_lines if not (pl.get('sku') or '').strip())

            if empty_sku_count > 0:
                est_seconds = max(1, (empty_sku_count // 20 + 1) * 2)
                warning_text = (
                    "%s publicaciones sin SKU. Consultando variaciones a ML (~%ss)..."
                    % (empty_sku_count, est_seconds)
                )
                _logger.info("apply_filter: %s", warning_text)
                self.import_status = warning_text

                # Enrich: fetch real SKUs from ML for items missing them
                product_lines, enriched = self._enrich_skus(product_lines, context=context)

                # Update cache with enriched data
                self.product_lines_json = json.dumps(product_lines)

                self.import_status = "SKUs completados: %s/%s publicaciones actualizadas" % (
                    enriched, empty_sku_count)
                _logger.info("apply_filter: enriched %s / %s items", enriched, empty_sku_count)

        # Apply all filters. Honor the advanced batch flags by overriding the
        # effective post_state / sync_filter before calling _apply_filters.
        _states_to_fetch, _effective_ps, _force_ns = self._effective_batch_filters()
        if len(_states_to_fetch) == 1:
            _post_state_for_filter = _states_to_fetch[0]
        elif _force_ns and len(_states_to_fetch) < 3:
            _post_state_for_filter = list(_states_to_fetch)
        else:
            _post_state_for_filter = self.post_state
        _sync_filter_for_filter = 'not_synced' if _force_ns else self.sync_filter

        filtered = self._apply_filters(
            product_lines,
            sku_filter=sku_filter,
            post_state_filter=_post_state_for_filter,
            sync_filter=_sync_filter_for_filter,
        )
        _logger.info("apply_filter: %s / %s lines after filter (sku=%s, estado=%s, sync=%s, batch_actives=%s, batch_paused=%s, batch_left=%s)",
                      len(filtered), len(product_lines),
                      sku_filter, _post_state_for_filter, _sync_filter_for_filter,
                      self.batch_actives_to_sync, self.batch_paused_to_sync, self.batch_left_to_sync)

        # Update status with filter result — include the active options so the
        # user can tell exactly which filter combination was applied.
        self.import_status = "Filtro aplicado: %s / %s publicaciones%s" % (
            len(filtered), len(product_lines), self._build_filter_summary())

        # Delete old import_lines and recreate with filtered data
        if self.import_lines:
            self.import_lines.sudo().unlink()

        self._create_import_lines(self.id, filtered)

        # Stay on the same wizard (no new wizard needed)
        refview = get_ref_view(self, "meli_oerp_multiple", 'view_product_template_import_multiple')
        return {
            'name': _("Importar Masivamente ML (...)"),
            'view_mode': 'form',
            'view_id': (refview and refview[1]),
            'res_id': self.id,
            'res_model': 'mercadolibre.product.template.import',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'domain': [],
            'context': context,
        }

    # ------------------------------------------------------------------
    # MULTIGET: has_consulta — activa el botón "Importar Consultados"
    # ------------------------------------------------------------------
    has_consulta = fields.Boolean(
        string="Consulta realizada",
        compute="_compute_has_consulta",
        readonly=True,
    )

    def _compute_has_consulta(self):
        for rec in self:
            try:
                rec.has_consulta = bool(rec.product_lines_json and len(rec.product_lines_json) > 2)
            except Exception:
                rec.has_consulta = False

    def action_import_consulted(self, context=None):
        """MULTIGET: Importa publicaciones ya consultadas sin re-consultar ML.
        Resuelve el problema de timeout de Cloudflare: si la consulta se cortó
        pero los datos quedaron en product_lines_json, los importa directamente."""
        context = context or self.env.context
        account = self._get_account(context)
        if not account:
            return self.env['meli.warning'].error(title="No account defined")
        if not self.import_lines:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Sin publicaciones',
                               'message': 'No hay publicaciones consultadas. Primero usa "Consultar ML".',
                               'type': 'warning'}}
        pending_lines = [il for il in self.import_lines
                         if il.import_status not in ('synced', 'imported', 'error', 'duplicate')]
        if not pending_lines:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Nada que importar',
                               'message': 'Todas las publicaciones ya fueron procesadas.',
                               'type': 'info'}}
        return self.product_template_import(context=context)

    # ------------------------------------------------------------------
    # REFATODO: Control de Cron desde el wizard
    # ------------------------------------------------------------------
    cron_active = fields.Boolean(string="Cron activo", compute="_compute_cron_status",
                                  inverse="_inverse_cron_active", readonly=False)
    cron_has_profile = fields.Boolean(string="Tiene perfil guardado",
                                       compute="_compute_cron_status", readonly=True)
    cron_profile_display = fields.Text(string="Perfil Actual",
                                        compute="_compute_cron_status", readonly=True)
    cron_post_state = fields.Selection([('active', 'Activos'), ('paused', 'Pausados'),
                                         ('all', 'Todos')], string='Status', default='all')
    cron_batch_size = fields.Integer(string='Batch size', default=1500)
    cron_force_dont_create = fields.Boolean(string='No crear productos', default=True)
    cron_force_import_images = fields.Boolean(string='Importar imágenes', default=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        try:
            account_ids = self.env.context.get('active_ids') or []
            if account_ids:
                account = self.env['mercadolibre.account'].browse(account_ids)
                config = account.configuration if account else None
                if config and hasattr(config, 'mercadolibre_cron_get_new_products_batch_size') \
                        and self._config_has_profile(config):
                    if 'cron_post_state' in fields_list:
                        res['cron_post_state'] = config.mercadolibre_cron_get_new_products_post_state or 'all'
                    if 'cron_batch_size' in fields_list:
                        res['cron_batch_size'] = config.mercadolibre_cron_get_new_products_batch_size or 1500
                    if 'cron_force_dont_create' in fields_list:
                        res['cron_force_dont_create'] = config.mercadolibre_cron_get_new_products_force_dont_create
                    if 'cron_force_import_images' in fields_list:
                        res['cron_force_import_images'] = config.mercadolibre_cron_get_new_products_force_import_images
        except Exception as e:
            _logger.warning("default_get error loading cron profile: %s", str(e))
        return res

    @api.model
    def _config_has_profile(self, config):
        try:
            return bool(config.mercadolibre_cron_get_new_products_batch_size
                        or config.mercadolibre_cron_get_new_products_post_state)
        except Exception:
            return False

    def _compute_cron_status(self):
        for rec in self:
            try:
                account = rec._get_account()
                config = account.configuration if account else None
                if not config or not hasattr(config, 'mercadolibre_cron_get_new_products'):
                    rec.cron_active = False
                    rec.cron_has_profile = False
                    rec.cron_profile_display = "Sin configuración"
                    continue
                rec.cron_active = bool(config.mercadolibre_cron_get_new_products)
                if rec._config_has_profile(config):
                    rec.cron_has_profile = True
                    sl = {'active': 'Activos', 'paused': 'Pausados', 'all': 'Todos'}
                    ck = lambda v: "✓" if v else "✗"
                    rec.cron_profile_display = "Status: %s | Batch: %d | No crear: %s | Imgs: %s" % (
                        sl.get(config.mercadolibre_cron_get_new_products_post_state or 'all', 'Todos'),
                        config.mercadolibre_cron_get_new_products_batch_size or 1500,
                        ck(config.mercadolibre_cron_get_new_products_force_dont_create),
                        ck(config.mercadolibre_cron_get_new_products_force_import_images))
                else:
                    rec.cron_has_profile = False
                    rec.cron_profile_display = "Sin perfil guardado"
            except Exception as e:
                rec.cron_active = False
                rec.cron_has_profile = False
                rec.cron_profile_display = "Error: %s" % str(e)[:80]

    def _inverse_cron_active(self):
        for rec in self:
            account = rec._get_account()
            config = account.configuration if account else None
            if not config:
                continue
            if rec.cron_active:
                vals = {'mercadolibre_cron_get_new_products': True}
                if not rec._config_has_profile(config):
                    vals.update({
                        'mercadolibre_cron_get_new_products_batch_size': rec.cron_batch_size or 1500,
                        'mercadolibre_cron_get_new_products_post_state': rec.cron_post_state or 'all',
                        'mercadolibre_cron_get_new_products_force_dont_create': rec.cron_force_dont_create,
                        'mercadolibre_cron_get_new_products_force_meli_pub': True,
                        'mercadolibre_cron_get_new_products_force_import_images': rec.cron_force_import_images,
                    })
                config.write(vals)
            else:
                config.write({'mercadolibre_cron_get_new_products': False})

    def action_create_or_update_cron(self, context=None):
        """Actualiza el perfil del cron con los valores del formulario."""
        account = self._get_account(context or self.env.context)
        config = account.configuration if account else None
        if not config:
            return self.env['meli.warning'].error(title="No configuration defined")
        was_profile = self._config_has_profile(config)
        config.write({
            'mercadolibre_cron_get_new_products': True,
            'mercadolibre_cron_get_new_products_batch_size': self.cron_batch_size or 1500,
            'mercadolibre_cron_get_new_products_post_state': self.cron_post_state or 'all',
            'mercadolibre_cron_get_new_products_force_dont_create': self.cron_force_dont_create,
            'mercadolibre_cron_get_new_products_force_meli_pub': True,
            'mercadolibre_cron_get_new_products_force_import_images': self.cron_force_import_images,
        })
        label = 'creado' if not was_profile else 'actualizado'
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Perfil Cron %s' % label.capitalize(),
                           'message': 'Batch: %d | Status: %s' % (
                               self.cron_batch_size or 1500, self.cron_post_state or 'all'),
                           'type': 'success'}}

    def action_run_cron_now(self, context=None):
        """Ejecuta el cron ahora con el perfil guardado."""
        account = self._get_account(context or self.env.context)
        if not account:
            return self.env['meli.warning'].error(title="No account defined")
        account.cron_batch_import_products()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Cron Ejecutado',
                           'message': 'Cron de importación ejecutado con el perfil guardado.',
                           'type': 'success'}}

    # ------------------------------------------------------------------
    # Button: "Consultar ML" — fetch + preview
    # ------------------------------------------------------------------
    def check_import_status(self, context=None):
        context = context or self.env.context
        _logger.info("check_import_status: fetching sync status from ML API")

        sync_status = self.check_sync_status(context=context)

        # Update counters on self before creating new wizard
        self.actives_to_sync = sync_status.get('actives_to_sync', '0')
        self.paused_to_sync = sync_status.get('paused_to_sync', '0')
        self.closed_to_sync = sync_status.get('closed_to_sync', '0')
        # Include the active filters/advanced options in the status bar so the
        # user can always tell which parameters produced the preview they see.
        self.import_status = "Consultado%s" % self._build_filter_summary()

        new_context = dict(context)
        new_context["sync_status"] = sync_status

        return self.show_import_wizard(context=new_context)

    # ------------------------------------------------------------------
    # Button: "Importar" — process import_lines one by one
    # ------------------------------------------------------------------
    def product_template_import(self, context=None):
        context = context or self.env.context
        account = self._get_account(context)
        warningobj = self.env['meli.warning']

        if not account:
            return warningobj.error(title="No account defined")

        company = (account and account.company_id) or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            return meli.redirect_login()

        custom_context = {
            "post_state": self.post_state,
            "meli_id": self.meli_id,
            "force_meli_pub": self.force_meli_pub,
            "force_import_images": self.force_import_images,
            "force_create_variants": self.force_create_variants,
            "force_dont_create": self.force_dont_create,
            "force_meli_website_published": self.force_meli_website_published,
            "force_meli_website_category_create_and_assign": self.force_meli_website_category_create_and_assign,
            "batch_processing_unit": self.batch_processing_unit,
            "batch_processing_unit_offset": self.batch_processing_unit_offset,
            "batch_actives_to_sync": self.batch_actives_to_sync,
            "batch_paused_to_sync": self.batch_paused_to_sync,
            "batch_left_to_sync": self.batch_left_to_sync,
        }

        # If we have import_lines, process them line by line (orders pattern)
        if self.import_lines:
            batch_start = 0
            processed_meli_ids = {}
            remaining_lines = []

            # --- Import plan summary ---
            import time as _time
            pending_lines = [il for il in self.import_lines if il.import_status not in ('synced', 'created', 'imported', 'error', 'duplicate')]
            total_to_process = min(len(pending_lines), self.batch_processing_unit) if self.batch_processing_unit > 0 else len(pending_lines)
            _logger.info("=== IMPORT PLAN: %s products to process (batch_unit=%s, pending=%s) ===",
                         total_to_process, self.batch_processing_unit, len(pending_lines))
            _import_times = []
            _import_batch_start_time = _time.time()

            for imli in self.import_lines:
                if batch_start >= self.batch_processing_unit and self.batch_processing_unit > 0:
                    _logger.info("Breaking batch at %s", batch_start)
                    break

                # Skip already-processed lines (synced, created, imported, errored, etc.)
                # 'missing' means not linked in Odoo — these SHOULD be processed
                if imli.import_status in ('synced', 'created', 'imported', 'error', 'duplicate'):
                    continue

                batch_start += 1
                meli_id = imli.meli_id
                _item_start = _time.time()

                # Time estimate based on average so far
                if _import_times:
                    avg_time = sum(_import_times) / len(_import_times)
                    remaining = total_to_process - batch_start + 1
                    eta_seconds = avg_time * remaining
                    eta_min = int(eta_seconds // 60)
                    eta_sec = int(eta_seconds % 60)
                    _logger.info("Importing product %s (%s/%s) [avg %.1fs/product, ETA ~%dm%02ds]",
                                 meli_id, batch_start, total_to_process, avg_time, eta_min, eta_sec)
                else:
                    _logger.info("Importing product %s (%s/%s)", meli_id, batch_start, total_to_process)

                try:
                    with self.env.cr.savepoint():
                        import_ctx = dict(custom_context)
                        import_ctx['meli_id'] = meli_id
                        res = account.product_meli_get_products(context=import_ctx)

                        if res and "json_report" in res:
                            jr = res["json_report"]
                            # Check results in priority order: created > synced > duplicates > missing
                            if jr.get("created"):
                                try:
                                    imli.sudo().import_status = 'created'
                                    created_info = jr["created"][0] if jr["created"] else {}
                                    imli.sudo().error = 'Creado: odoo_id=%s' % created_info.get('odoo_id', '')
                                    _logger.info("WIZARD: Product %s CREATED (odoo_id=%s)", meli_id, created_info.get('odoo_id', ''))
                                except Exception:
                                    pass
                            elif jr.get("synced"):
                                try:
                                    imli.sudo().import_status = 'synced'
                                    imli.sudo().error = ''
                                    _logger.info("WIZARD: Product %s SYNCED", meli_id)
                                except Exception:
                                    pass
                            elif jr.get("duplicates"):
                                try:
                                    imli.sudo().import_status = 'duplicate'
                                    imli.sudo().error = 'SKU duplicado en Odoo'
                                    _logger.info("WIZARD: Product %s DUPLICATE", meli_id)
                                except Exception:
                                    pass
                            elif jr.get("missing"):
                                try:
                                    imli.sudo().import_status = 'error'
                                    imli.sudo().error = 'No se encontró producto en Odoo por SKU'
                                    _logger.info("WIZARD: Product %s MISSING", meli_id)
                                except Exception:
                                    pass
                            else:
                                try:
                                    imli.sudo().import_status = 'imported'
                                    imli.sudo().error = ''
                                    _logger.info("WIZARD: Product %s IMPORTED (no specific status)", meli_id)
                                except Exception:
                                    pass
                            processed_meli_ids[meli_id] = True
                        else:
                            try:
                                imli.sudo().import_status = 'error'
                                imli.sudo().error = 'Sin respuesta de product_meli_get_products'
                            except Exception:
                                pass

                        MeliCommit(self)

                except Exception as E:
                    _logger.error("Import error for %s: %s", meli_id, str(E))
                    try:
                        imli.sudo().import_status = 'error'
                        imli.sudo().error = str(E)[:200]
                    except Exception:
                        pass
                    processed_meli_ids[meli_id] = False

                # Track time for this product
                _item_elapsed = _time.time() - _item_start
                _import_times.append(_item_elapsed)
                _logger.info("Imported %s in %.1fs", meli_id, _item_elapsed)

            # Final summary
            _batch_elapsed = _time.time() - _import_batch_start_time
            if _import_times:
                _logger.info("=== IMPORT DONE: %s/%s products in %.1fs (avg %.1fs/product) ===",
                             len(_import_times), total_to_process, _batch_elapsed,
                             sum(_import_times) / len(_import_times))

            # --- Progressive CSV report: append this batch's results ---
            try:
                import io
                import csv as csv_mod

                csv_headers = ['ML Id', 'Estado ML', 'SKU', 'Nombre', 'Precio ML',
                               'Stock ML', 'Variaciones', 'Estado Importación', 'Error', 'Fecha']
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Read existing CSV if we already have a report attachment
                existing_rows = []
                if self.report_import and self.report_import.datas:
                    try:
                        raw = base64.b64decode(self.report_import.datas).decode('utf-8')
                        # Strip BOM if present
                        if raw.startswith('\ufeff'):
                            raw = raw[1:]
                        reader = csv_mod.reader(io.StringIO(raw), delimiter=';')
                        rows = list(reader)
                        if rows:
                            existing_rows = rows[1:]  # skip header
                    except Exception:
                        existing_rows = []

                # Collect new rows from THIS batch only (items we actually processed)
                new_rows = []
                for imli in self.import_lines:
                    mid = imli.meli_id
                    if mid not in processed_meli_ids:
                        continue  # was not processed in this batch
                    new_rows.append([
                        imli.meli_id or '',
                        imli.meli_status or '',
                        imli.sku or '',
                        (imli.name or '')[:80],
                        imli.meli_price or 0,
                        imli.meli_qty or 0,
                        imli.variations_count or 0,
                        imli.import_status or '',
                        imli.error or '',
                        now_str,
                    ])

                # Write combined CSV
                csv_buffer = io.StringIO()
                csv_buffer.write('\ufeff')  # BOM for Excel UTF-8
                writer = csv_mod.writer(csv_buffer, delimiter=';', quoting=csv_mod.QUOTE_ALL)
                writer.writerow(csv_headers)
                for row in existing_rows:
                    writer.writerow(row)
                for row in new_rows:
                    writer.writerow(row)

                csv_content = csv_buffer.getvalue()
                b64_csv = base64.b64encode(csv_content.encode('utf-8'))

                if self.report_import:
                    # Update existing attachment
                    self.report_import.sudo().write({
                        'datas': b64_csv,
                    })
                else:
                    # Create new attachment
                    att_name = "ImportReport-%s-%s.csv" % (
                        str(account and account.name or 'unknown'),
                        datetime.now().strftime("%Y-%m-%d_%H%M"))
                    csv_attachment = self.env['ir.attachment'].create({
                        'name': att_name,
                        'type': 'binary',
                        'datas': b64_csv,
                        'access_token': self.env['ir.attachment']._generate_access_token(),
                        'res_model': 'mercadolibre.product.template.import',
                        'res_id': self.id,
                        'mimetype': 'text/csv',
                    })
                    self.report_import = csv_attachment.id

                # Set download link
                if self.report_import:
                    att = self.report_import
                    if not att.access_token:
                        att.sudo().access_token = self.env['ir.attachment']._generate_access_token()
                    self.report_import_link = "/web/content/%s?download=true&access_token=%s" % (
                        str(att.id), str(att.access_token))
                    _logger.info("Progressive CSV report updated: %s rows total", len(existing_rows) + len(new_rows))

            except Exception as csv_err:
                _logger.warning("Could not update progressive CSV report: %s", str(csv_err))

            # Build updated status map from processed import_lines
            import json as _json
            status_updates = {}
            for imli in self.import_lines:
                mid = imli.meli_id
                if mid:
                    status_updates[mid] = {
                        'import_status': imli.import_status or 'pending',
                        'error': imli.error or '',
                    }

            # Update the FULL product_lines_json with new statuses, then let
            # show_import_wizard apply filters again.  This avoids the bug where
            # remaining_lines was empty (all imported) and the wizard fell back
            # to the stale cached JSON, re-showing the same items.
            full_lines = []
            if self.product_lines_json:
                try:
                    full_lines = _json.loads(self.product_lines_json)
                except Exception:
                    full_lines = []

            if full_lines:
                for pl in full_lines:
                    mid = pl.get('meli_id')
                    if mid in status_updates:
                        pl['import_status'] = status_updates[mid]['import_status']
                        pl['error'] = status_updates[mid]['error']
                remaining_lines = full_lines
            else:
                # Fallback: build from import_lines only
                for imli in self.import_lines:
                    remaining_lines.append({
                        'meli_id': imli.meli_id,
                        'meli_status': imli.meli_status or '',
                        'sku': imli.sku or '',
                        'name': imli.name or imli.meli_id or '',
                        'meli_price': imli.meli_price or 0,
                        'meli_qty': imli.meli_qty or 0,
                        'variations_count': imli.variations_count or 0,
                        'import_status': imli.import_status or 'pending',
                        'error': imli.error or '',
                        'meli_permalink': imli.meli_permalink or '',
                    })

            _logger.info("Remaining lines: %s total, updated statuses for %s items",
                         len(remaining_lines), len(status_updates))

            # Build filter + advanced-options summary for the status message,
            # reusing the same helper the preview / filter buttons use so the
            # user sees a consistent description everywhere (includes the
            # batch_actives/paused/left_to_sync flags and the force_* options,
            # not just estado/sku/sync like the inline version used to).
            _filter_str = self._build_filter_summary()

            # Count results by status for this batch
            _created = 0
            _synced = 0
            _imported = 0
            _errors = 0
            _duplicates = 0
            for imli in self.import_lines:
                if imli.meli_id not in processed_meli_ids:
                    continue
                if imli.import_status == 'created':
                    _created += 1
                elif imli.import_status == 'synced':
                    _synced += 1
                elif imli.import_status == 'imported':
                    _imported += 1
                elif imli.import_status == 'error':
                    _errors += 1
                elif imli.import_status == 'duplicate':
                    _duplicates += 1

            _summary_parts = []
            if _created:
                _summary_parts.append("created: %s" % _created)
            if _synced:
                _summary_parts.append("synced: %s" % _synced)
            if _imported:
                _summary_parts.append("imported: %s" % _imported)
            if _errors:
                _summary_parts.append("errors: %s" % _errors)
            if _duplicates:
                _summary_parts.append("duplicates: %s" % _duplicates)
            _summary_str = " [%s]" % ", ".join(_summary_parts) if _summary_parts else ""

            _logger.info("=== WIZARD BATCH SUMMARY: created=%s, synced=%s, imported=%s, errors=%s, duplicates=%s ===",
                         _created, _synced, _imported, _errors, _duplicates)

            # Advance offset by the number of items processed in this batch
            self.batch_processing_unit_offset += batch_start

            self.import_status = "Importado lote de %s%s%s" % (batch_start, _filter_str, _summary_str)

            new_context = dict(context)
            new_context["sync_status"] = {"product_lines": remaining_lines}
            new_context["post_import"] = True
            return self.show_import_wizard(context=new_context)

        # Fallback: no import_lines, run legacy import
        res = {}
        if account:
            res = account.product_meli_get_products(context=custom_context)

        if res and "json_report" in res:
            if "paging" in res:
                if "next_offset" in res["paging"]:
                    self.batch_processing_unit_offset = res["paging"]["next_offset"]

            self.import_status = "Importado (legacy)"
            new_context = dict(context)
            new_context["sync_status"] = {"product_lines": []}
            return self.show_import_wizard(context=new_context)

        return res

    # ------------------------------------------------------------------
    # Button: "Crear Reporte Completo"
    # ------------------------------------------------------------------
    def action_activate_cron_import(self, context=None):
        """Activa el cron de importacion batch con los parametros actuales del wizard."""
        context = context or self.env.context
        account = self._get_account(context)
        if not account:
            return self.env['meli.warning'].error(title="No account defined")

        config = account.configuration
        if not config:
            return self.env['meli.warning'].error(title="No configuration defined")

        config.write({
            'mercadolibre_cron_get_new_products': True,
            'mercadolibre_cron_get_new_products_batch_size': self.batch_processing_unit or 100,
            'mercadolibre_cron_get_new_products_post_state': self.post_state if self.post_state != 'all' else 'active',
            'mercadolibre_cron_get_new_products_force_dont_create': self.force_dont_create,
            'mercadolibre_cron_get_new_products_force_meli_pub': self.force_meli_pub,
            'mercadolibre_cron_get_new_products_force_import_images': self.force_import_images,
        })

        # Transferir el estado actual del wizard al account para continuar desde donde estamos
        if self.product_lines_json:
            account.write({
                'cron_import_product_lines_json': self.product_lines_json,
                'cron_import_offset': self.batch_processing_unit_offset,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Cron Activado',
                'message': 'El cron de importacion batch ha sido activado con lote=%s, estado=%s' % (
                    self.batch_processing_unit or 100, self.post_state or 'active'),
                'type': 'success',
            }
        }

    def action_run_cron_now(self, context=None):
        """Ejecuta una iteracion del cron batch import inmediatamente."""
        context = context or self.env.context
        account = self._get_account(context)
        if not account:
            return self.env['meli.warning'].error(title="No account defined")

        # Activar/transferir config primero
        self.action_activate_cron_import(context=context)

        # Ejecutar una iteracion
        account.cron_batch_import_products()

        # Refrescar wizard con datos actualizados
        return self.show_import_wizard(context=context)

    def create_full_report(self, context=None, config=None, meli=None):
        context = context or self.env.context
        account = self._get_account(context)
        warningobj = self.env['meli.warning']

        if not account:
            return warningobj.error(title="No account defined")

        company = (account and account.company_id) or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            return meli.redirect_login()

        odoo_meli_ids = set(account.list_meli_ids() or [])
        import_line_obj = self.env["mercadolibre.products.import.line"]

        product_lines = []
        for status in ('active', 'paused'):
            fetched = account.fetch_list_meli_ids(params={'status': status})
            for mli in fetched:
                is_synced = mli in odoo_meli_ids
                rjson = account.fetch_meli_product(meli_id=mli, meli=meli)
                line_data = {
                    'meli_id': mli,
                    'meli_status': status,
                    'import_status': 'synced' if is_synced else 'missing',
                    'sku': '',
                    'name': '',
                    'meli_price': 0,
                    'meli_qty': 0,
                    'variations_count': 1,
                }
                if rjson:
                    # fetch_meli_sku returns list for variations, string for single product
                    skus = account.fetch_meli_sku(meli_id=mli, meli=meli, rjson=rjson)
                    if isinstance(skus, list):
                        line_data['sku'] = ', '.join(skus) if skus else ''
                    else:
                        line_data['sku'] = skus or ''
                    line_data['name'] = (rjson.get("title") or mli)[:80]
                    line_data['meli_price'] = rjson.get("price") or 0
                    line_data['meli_qty'] = rjson.get("available_quantity") or 0
                    variations = rjson.get("variations")
                    line_data['variations_count'] = len(variations) if variations else 1
                product_lines.append(line_data)

        # Generate CSV with proper headers
        import io
        import csv as csv_mod
        csv_buffer = io.StringIO()
        csv_buffer.write('\ufeff')  # BOM for Excel UTF-8
        csv_headers = ['ML Id', 'Estado ML', 'SKU', 'Nombre', 'Precio ML', 'Stock ML', 'Variaciones', 'Estado Importación']
        writer = csv_mod.writer(csv_buffer, delimiter=';', quoting=csv_mod.QUOTE_ALL)
        writer.writerow(csv_headers)
        for pl in product_lines:
            writer.writerow([
                pl['meli_id'], pl['meli_status'], pl['sku'], pl['name'],
                pl['meli_price'], pl['meli_qty'], pl['variations_count'], pl['import_status']
            ])

        csv_content = csv_buffer.getvalue()
        b64_csv = base64.b64encode(csv_content.encode('utf-8'))
        now = datetime.now()
        ATTACHMENT_NAME = "FullReport-%s-%s" % (
            str(account and account.name), now.strftime("%Y-%m-%d_%H%M"))

        csv_attachment = self.env['ir.attachment'].create({
            'name': ATTACHMENT_NAME + '.csv',
            'type': 'binary',
            'datas': b64_csv,
            'access_token': self.env['ir.attachment']._generate_access_token(),
            'res_model': 'mercadolibre.product.template.import',
            'res_id': self.id,
            'mimetype': 'text/csv'
        })

        if csv_attachment:
            self.report_import = csv_attachment.id
            link = "/web/content/%s?download=true&access_token=%s" % (
                str(csv_attachment.id), str(csv_attachment.access_token))
            self.report_import_link = link

        # Also show results as import_lines in wizard
        self.import_status = "Reporte completo generado"
        new_context = dict(context)
        new_context["sync_status"] = {"product_lines": product_lines}
        return self.show_import_wizard(context=new_context)



class mercadolibre_products_import_line_ext(models.TransientModel):
    _inherit = "mercadolibre.products.import.line"

    meli_permalink = fields.Char(string="Link ML", readonly=True)
    meli_barcode = fields.Char(string="Barcode ML", readonly=True)
    # Additional fields for detailed info
    seller_skus = fields.Text(string="SKUs ML", readonly=True, help="SKUs de todas las variaciones de esta publicación")
    barcodes = fields.Text(string="Barcodes", readonly=True, help="Códigos de barra de todas las variaciones")
    variations_detail = fields.Text(string="Detalle variaciones", readonly=True, help="Detalle completo de variaciones")
    sku_found_in_odoo = fields.Boolean(string="SKU existe en Odoo", readonly=True, default=False)
    odoo_product_info = fields.Text(string="Productos Odoo", readonly=True, help="Productos encontrados en Odoo por SKU")
    odoo_product_ids = fields.Many2many(
        'product.product',
        'meli_import_line_product_rel',
        'line_id', 'product_id',
        string="Productos encontrados en Odoo",
        readonly=True,
    )
    ml_title = fields.Char(string="Título ML", readonly=True)
    import_suggestion = fields.Text(string="Sugerencia", compute='_compute_import_suggestion')
    # Campo computado que dispara la carga de datos al abrir el form
    detail_fetched = fields.Boolean(string="Detalle consultado", compute='_compute_ml_details')

    @api.depends('import_status', 'error', 'sku_found_in_odoo', 'seller_skus')
    def _compute_import_suggestion(self):
        for rec in self:
            status = rec.import_status
            has_sku_in_ml = bool(rec.seller_skus and rec.seller_skus != '(sin SKU)')
            found_in_odoo = rec.sku_found_in_odoo

            if status == 'error':
                if found_in_odoo and not has_sku_in_ml:
                    rec.import_suggestion = (
                        "Se encontraron productos en Odoo por barcode pero la publicación ML "
                        "no tiene SKU asignado. Para resolver:\n"
                        "① Agregar el SKU del producto en la publicación de MercadoLibre, o\n"
                        "② En Odoo: abrir el producto encontrado → pestaña MercadoLibre → "
                        "ingresar el MLM ID de esta publicación para vincularlo manualmente."
                    )
                elif found_in_odoo and has_sku_in_ml:
                    rec.import_suggestion = (
                        "El producto existe en Odoo pero el import falló. Posibles causas:\n"
                        "① El SKU en ML no coincide exactamente con el SKU en Odoo (verificar mayúsculas/espacios),\n"
                        "② Error temporal de API — reintentar con el botón Importar de esta línea."
                    )
                elif not found_in_odoo:
                    rec.import_suggestion = (
                        "No se encontró ningún producto en Odoo con el SKU o barcode de esta publicación.\n"
                        "① Crear el producto en Odoo con el SKU correcto, o\n"
                        "② Importar como producto nuevo desde ML usando el botón Importar."
                    )
                else:
                    rec.import_suggestion = (
                        "Revisar el detalle del error más abajo y los logs del servidor para más información."
                    )
            elif status == 'duplicate':
                rec.import_suggestion = (
                    "Más de un producto en Odoo coincide con el SKU o barcode de esta publicación.\n"
                    "① Identificar cuál es el producto correcto en la lista de abajo,\n"
                    "② Eliminar o unificar los duplicados en Odoo,\n"
                    "③ Reimportar esta línea."
                )
            else:
                rec.import_suggestion = False

    def _get_account_for_line(self):
        """Get the ML account from wizard or context."""
        context = self.env.context
        account_ids = context.get('active_ids') or []
        account = self.env['mercadolibre.account'].browse(account_ids)
        if not account and self.import_id:
            account = self.import_id._get_account(context)
        return account

    def import_single_line(self):
        """Import a single publication from this line."""
        self.ensure_one()
        wizard = self.import_id
        if not wizard:
            return {'type': 'ir.actions.act_window_close'}

        account = self._get_account_for_line()
        if not account:
            self.import_status = 'error'
            self.error = 'No se encontró cuenta ML'
            return {'type': 'ir.actions.act_window_close'}

        company = (account and account.company_id) or self.env.user.company_id
        meli = self.env['meli.util'].get_new_instance(company, account)
        if meli.need_login():
            return meli.redirect_login()

        import_ctx = {
            "meli_id": self.meli_id,
            "force_meli_pub": wizard.force_meli_pub,
            "force_import_images": wizard.force_import_images,
            "force_create_variants": wizard.force_create_variants,
            "force_dont_create": wizard.force_dont_create,
            "force_meli_website_published": wizard.force_meli_website_published,
            "force_meli_website_category_create_and_assign": wizard.force_meli_website_category_create_and_assign,
        }

        try:
            res = account.product_meli_get_products(context=import_ctx)
            if res and "json_report" in res:
                jr = res["json_report"]
                if jr.get("missing"):
                    self.import_status = 'missing'
                    self.error = 'No se encontró producto en Odoo por SKU'
                elif jr.get("duplicates"):
                    self.import_status = 'duplicate'
                    self.error = 'SKU duplicado en Odoo'
                else:
                    self.import_status = 'imported'
                    self.error = ''
            else:
                self.import_status = 'error'
                self.error = 'Sin respuesta de product_meli_get_products'
            MeliCommit(self)
        except Exception as E:
            _logger.error("Import single line error for %s: %s", self.meli_id, str(E))
            self.import_status = 'error'
            self.error = str(E)[:200]

        return {'type': 'ir.actions.act_window_close'}

    def action_open_ml(self):
        """Open the MercadoLibre API with access token in a new browser tab."""
        self.ensure_one()
        account = self._get_account_for_line()

        # Build API URL with access token
        url = "https://api.mercadolibre.com/items/%s?include_attributes=all" % self.meli_id
        if account and account.access_token:
            url += "&access_token=%s" % account.access_token

        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_open_ml_web(self):
        """Open the MercadoLibre publication webpage (public link).

        Construye el fallback 100% offline (sin llamadas a la API de ML) usando
        _resolve_ml_site_urls() con el site_id del account. ML acepta
        articulo/<meli_id> sin slug y redirige al permalink canónico, así que
        no necesitamos pegarle a /items/<id> para obtener el permalink real.
        """
        self.ensure_one()
        if self.meli_permalink:
            url = self.meli_permalink
        else:
            # Fallback: try to construct URL or fetch it
            account = self._get_account_for_line()
            company = (account and account.company_id) or self.env.user.company_id
            _site_id, _urls = _resolve_ml_site_urls(account=account, company=company)
            # meli_id ya incluye el prefijo de site (ej: "MLA123", "MLM123").
            url = _urls["articulo"] + "/" + str(self.meli_id)

        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def _compute_ml_details(self):
        """Compute field that fetches ML details when form is opened.
        Only fetches for SINGLE record (when user opens line form).
        Skips when loading multiple records (tree view in One2many).
        """
        # OPTIMIZATION: Skip if loading multiple records (tree view)
        # Only fetch details when user opens a specific line form (single record)
        if len(self) > 1:
            for rec in self:
                rec.detail_fetched = False
            return

        for rec in self:
            _logger.info("=== _COMPUTE_ML_DETAILS: %s ===", rec.meli_id)
            rec.detail_fetched = False  # Default

            if not rec.meli_id:
                continue

            account = rec._get_account_for_line()
            if not account:
                rec.error = 'No se encontró cuenta ML'
                continue

            company = (account and account.company_id) or self.env.user.company_id
            meli = self.env['meli.util'].get_new_instance(company, account)
            if meli.need_login():
                rec.error = 'Sesión ML expirada'
                continue

            try:
                rjson = account.fetch_meli_product(meli_id=rec.meli_id, meli=meli)
                if not rjson:
                    rec.error = 'No se pudo obtener datos de ML'
                    continue

                # Update basic fields
                rec.ml_title = (rjson.get("title") or "")[:100]
                rec.meli_permalink = rjson.get("permalink") or ""
                rec.meli_price = rjson.get("price") or 0
                rec.meli_qty = rjson.get("available_quantity") or 0
                rec.name = rec.ml_title or rec.meli_id

                # Get SKUs
                all_skus = account.fetch_meli_sku(meli_id=rec.meli_id, meli=meli, rjson=rjson)
                if all_skus is None:
                    seller_skus = []
                elif isinstance(all_skus, list):
                    seller_skus = [s for s in all_skus if s]
                else:
                    seller_skus = [all_skus] if all_skus else []

                # Get barcodes
                all_barcodes = account.fetch_meli_barcode(meli_id=rec.meli_id, meli=meli, rjson=rjson)
                if all_barcodes is None:
                    barcodes = []
                elif isinstance(all_barcodes, list):
                    barcodes = [b for b in all_barcodes if b]
                else:
                    barcodes = [all_barcodes] if all_barcodes else []

                # Build variations detail
                variations_info = []
                variations = rjson.get("variations") or []
                rec.variations_count = len(variations) if variations else 1

                if variations:
                    for var in variations:
                        var_sku = var.get("seller_sku") or var.get("inventory_id") or ""
                        var_barcode = var.get("barcode") or ""
                        var_qty = var.get("available_quantity") or 0
                        attr_parts = []
                        for combo in var.get("attribute_combinations") or []:
                            attr_parts.append("%s: %s" % (combo.get("name") or "", combo.get("value_name") or ""))
                        var_info = "SKU: %s | Stock: %s" % (var_sku or '-', var_qty)
                        if var_barcode:
                            var_info += " | Barcode: %s" % var_barcode
                        if attr_parts:
                            var_info += " | " + ", ".join(attr_parts)
                        variations_info.append(var_info)
                else:
                    main_sku = seller_skus[0] if seller_skus else '-'
                    main_barcode = barcodes[0] if barcodes else '-'
                    variations_info.append("Producto simple | SKU: %s | Barcode: %s" % (main_sku, main_barcode))

                rec.seller_skus = ", ".join(seller_skus) if seller_skus else "(sin SKU)"
                rec.barcodes = ", ".join(barcodes) if barcodes else "(sin barcode)"
                rec.variations_detail = "\n".join(variations_info)
                rec.sku = ", ".join(seller_skus) if seller_skus else ""

                # Check if SKUs exist in Odoo
                rec._check_skus_in_odoo(seller_skus, barcodes)

                rec.detail_fetched = True
                rec.error = ''
                _logger.info("=== _COMPUTE_ML_DETAILS SUCCESS: %s SKUs: %s ===", rec.meli_id, rec.seller_skus)

            except Exception as E:
                _logger.error("=== _COMPUTE_ML_DETAILS ERROR: %s - %s ===", rec.meli_id, str(E))
                rec.error = str(E)[:200]

    def _check_skus_in_odoo(self, seller_skus, barcodes):
        """Check if SKUs or barcodes exist in Odoo products."""
        product_obj = self.env['product.product']
        found_ids = []
        self.sku_found_in_odoo = False

        # Search by SKU
        for sku in seller_skus:
            if not sku:
                continue
            for p in product_obj.search([('default_code', '=ilike', sku)], limit=50):
                if p.id not in found_ids:
                    found_ids.append(p.id)
                self.sku_found_in_odoo = True

        # Search by barcode
        for barcode in barcodes:
            if not barcode:
                continue
            for p in product_obj.search([('barcode', '=ilike', barcode)], limit=50):
                if p.id not in found_ids:
                    found_ids.append(p.id)
                self.sku_found_in_odoo = True

        if found_ids:
            variants = self.env['product.product'].browse(found_ids)
            self.odoo_product_info = "\n".join(
                "SKU:%s | Barcode:%s | %s (ID:%s)" % (
                    v.default_code or '-', v.barcode or '-', v.name[:50], v.id)
                for v in variants
            )
            self.odoo_product_ids = variants
        else:
            self.odoo_product_info = "(No se encontraron productos en Odoo con estos SKUs/barcodes)"
            self.odoo_product_ids = self.env['product.product']


class mercadolibre_product_maestro_update(models.TransientModel):
    _name = "mercadolibre.product.maestro.update"
    _description = "MercadoLibre Product Maestro Update Wizard"

    connection_account = fields.Many2one("mercadolibre.account",string="MercadoLibre Account")

    def maestro_update(self, context=None):
        context = context or self.env.context
        #_logger.info("meli_oerp_multiple >> wizard maestro_update "+str(context))
        company = self.env.user.company_id
        product_ids = []

        if ('active_ids' in context):
            product_ids = context['active_ids']

        maestro_product_obj = self.env['mercadolibre.product.maestro']

        warningobj = self.env['meli.warning']

        account = self.connection_account
        company = (account and account.company_id) or company

        if account:
            meli = self.env['meli.util'].get_new_instance( company, account )
            if meli.need_login():
                return meli.redirect_login()
        else:
            meli = None

        res = {}
        #for product_id in product_ids:
        #    product = product_obj.browse(product_id)
        #    if (product):
        #        res = product.calculate_variations()

        maestro_products = maestro_product_obj.search([('id','in',product_ids)])
        if (maestro_products):
            maestro_products.calculate_variations(meli=None)
            if res and 'name' in res:
                return res

        return res


class mercadolibre_product_maestro_sku_post_load(models.TransientModel):
    """Wizard que carga SKUs pendientes (sku_post) en el maestro a partir de
    la planilla oficial de MercadoLibre (la que se descarga desde
    'Editar varias publicaciones a la vez' en el sitio).

    Estructura esperada del xlsx:
      - R0: banner (Publicaciones / Información del producto)
      - R1: headers (Agrupador, Número de publicación, Número de producto,
            SKU, Título, Variantes, Stock)
      - R2: marcador 'Obligatorio'
      - R3: separador
      - R4..: datos (col B = meli_id, col A = variación, col C = catálogo, col D = SKU)
    """
    _name = "mercadolibre.product.maestro.sku_post.load"
    _description = "Cargar SKU Post desde planilla MercadoLibre"

    connection_account = fields.Many2one(
        "mercadolibre.account", string="Cuenta MercadoLibre", required=True
    )
    xlsx_file = fields.Binary(string="Planilla MercadoLibre (.xlsx)", required=True)
    xlsx_filename = fields.Char(string="Nombre archivo")
    overwrite_pushed = fields.Boolean(
        string="Sobrescribir aplicados",
        default=False,
        help="Si está marcado, registros ya en estado 'pushed' se vuelven a "
             "marcar como 'draft' con el nuevo SKU. Por defecto se respetan."
    )
    skip_catalog = fields.Boolean(
        string="Omitir productos de catálogo (U…)",
        default=False,
        help="Los ítems con 'Número de producto' (U…) no aceptan SKU vía la "
             "planilla del sitio. Sin embargo, vía API (esta acción) el "
             "atributo SELLER_SKU sí suele ser aceptado. Default: intentar. "
             "Marcá esta opción solo si querés cargarlos como 'skipped' sin "
             "intentar el push."
    )

    result_summary = fields.Text(string="Resumen", readonly=True)

    def action_load(self):
        self.ensure_one()
        if not self.xlsx_file:
            raise UserError(_("Tenés que adjuntar la planilla .xlsx."))

        try:
            import openpyxl
        except ImportError:
            raise UserError(_(
                "Falta la librería 'openpyxl' en el servidor. "
                "Instalala con: pip install openpyxl"
            ))

        import io
        try:
            data = base64.b64decode(self.xlsx_file)
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise UserError(_("No pude abrir el .xlsx: %s") % str(e))

        ws = wb.worksheets[0]
        Maestro = self.env['mercadolibre.product.maestro']
        account = self.connection_account

        loaded = 0
        skipped_catalog = 0
        not_found = 0
        overwritten = 0
        ignored_pushed = 0
        errors = []

        # Datos arrancan en la fila 5 del archivo (índice 4 en 0-based).
        # iter_rows con min_row=5 levanta esa convención de ML.
        for idx, row in enumerate(ws.iter_rows(min_row=5, values_only=True), start=5):
            if not row:
                continue
            # Defensivo: row puede tener menos columnas si la planilla está recortada.
            col_a = row[0] if len(row) > 0 else None   # Agrupador / variation_id
            col_b = row[1] if len(row) > 1 else None   # meli_id (MCO/MLA…)
            col_c = row[2] if len(row) > 2 else None   # catálogo (U…)
            col_d = row[3] if len(row) > 3 else None   # SKU

            if not col_b or not str(col_b).strip():
                continue
            meli_id = str(col_b).strip()
            sku_new = (str(col_d).strip() if col_d not in (None, '') else False)

            if not sku_new:
                continue

            is_catalog = bool(col_c and str(col_c).strip().upper().startswith('U'))

            # Buscar el maestro por (cuenta, meli_id). Si hay variación, intentar
            # matchear meli_id_variation con col_a.
            domain = [
                ('connection_account', '=', account.id),
                ('meli_id', '=', meli_id),
            ]
            candidates = Maestro.search(domain)
            if not candidates:
                not_found += 1
                continue

            target = candidates
            if len(candidates) > 1 and col_a:
                variation = str(col_a).strip()
                filtered = candidates.filtered(
                    lambda r: r.meli_id_variation and r.meli_id_variation == variation
                )
                if filtered:
                    target = filtered
                else:
                    # Si no encuentro la variación exacta, no piso todas las hermanas.
                    errors.append("Fila %d: meli_id=%s con %d variantes, no matcheó %s" % (
                        idx, meli_id, len(candidates), variation
                    ))
                    continue

            for rec in target:
                if rec.sku_post_state == 'pushed' and not self.overwrite_pushed:
                    ignored_pushed += 1
                    continue

                vals = {
                    'sku_post': sku_new,
                    'sku_post_log': False,
                    'sku_post_date': False,
                }
                if is_catalog and self.skip_catalog:
                    vals['sku_post_state'] = 'skipped'
                    vals['sku_post_log'] = 'Catálogo ML: SKU no aplicable por planilla'
                    skipped_catalog += 1
                else:
                    vals['sku_post_state'] = 'draft'
                    if rec.sku_post_state == 'pushed':
                        overwritten += 1
                    loaded += 1
                rec.write(vals)

        try:
            wb.close()
        except Exception:
            pass

        summary_lines = [
            "Filas cargadas como pendientes (draft): %d" % loaded,
            "Filas marcadas como skipped (catálogo): %d" % skipped_catalog,
            "Filas ya aplicadas previamente ignoradas: %d" % ignored_pushed,
            "Filas que pisaron un 'pushed' previo: %d" % overwritten,
            "Publicaciones del archivo sin maestro en Odoo: %d" % not_found,
        ]
        if errors:
            summary_lines.append("")
            summary_lines.append("Avisos:")
            summary_lines.extend(errors[:50])
            if len(errors) > 50:
                summary_lines.append("... (%d más)" % (len(errors) - 50))

        self.result_summary = "\n".join(summary_lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply_all_pending(self):
        """Aplica todos los sku_post 'draft' de la cuenta seleccionada."""
        self.ensure_one()
        if not self.connection_account:
            raise UserError(_("Elegí una cuenta primero."))
        pending = self.env['mercadolibre.product.maestro'].search([
            ('connection_account', '=', self.connection_account.id),
            ('sku_post_state', '=', 'draft'),
            ('sku_post', '!=', False),
        ])
        if not pending:
            raise UserError(_("No hay SKUs pendientes para esta cuenta."))
        pending.action_apply_sku_post()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('SKU Post'),
                'message': _('Se procesaron %d registros pendientes.') % len(pending),
                'type': 'success',
                'sticky': False,
            }
        }


class MeliMultiwarehouseDiagnostic(models.TransientModel):
    _name = 'meli.multiwarehouse.diagnostic'
    _description = 'Diagnóstico Multiwarehouse ML'

    result_text = fields.Text(string='Resultado del diagnóstico', readonly=True)
