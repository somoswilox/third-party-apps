# -*- coding: utf-8 -*-
# 26.382 (caso-K51 cliente U, 7-nov-2026): re-apuntar una vinculación cambiando product_id (mercadolibre.product)
# o product_tmpl_id (mercadolibre.product_template) dejaba VIEJAS las listas inversas
#   product.product.mercadolibre_bindings   (rel mercadolibre_product_product_product_rel)
#   product.template.mercadolibre_bindings  (rel mercadolibre_product_template_product_template_rel)
# mercadolibre_bind_to sólo hacía (4, id) en el destino y nunca (3, id) en el origen; los wizards de re-vínculo
# ni eso. Efecto: Publicar stock/precio desde la plantilla nueva (product_template_post_stock/price iteran la M2M
# de la plantilla) y el post por movimiento de stock de la variante nueva (product_post_stock itera la M2M de la
# variante) no llegaban a la publicación, y la lista "Bindings" de la plantilla la omitía.
# Fix en el write de los dos modelos: cubre bind_to, wizards y cualquier script por ORM. Opt-out: contexto
# meli_skip_bind_rels (lo usa el propio sync al escribir la M2M, para no re-entrar).
import logging

from odoo import models

_logger = logging.getLogger(__name__)


def _meli_sync_bind_rels(bindings, vals, owner_field):
    """Antes/después del write: mueve el binding de la M2M `mercadolibre_bindings` del dueño viejo al nuevo."""
    if owner_field not in vals or bindings.env.context.get('meli_skip_bind_rels'):
        return None
    return {b.id: b[owner_field] for b in bindings}


def _meli_apply_bind_rels(bindings, before, owner_field):
    if not before:
        return
    for b in bindings:
        old = before.get(b.id)
        new = b[owner_field]
        if old == new:
            continue
        ctx = dict(bindings.env.context, meli_skip_bind_rels=True)
        try:
            with bindings.env.cr.savepoint():
                if old and 'mercadolibre_bindings' in old._fields:
                    old_s = old.sudo().with_context(ctx)
                    if b.id in old_s.mercadolibre_bindings.ids:
                        old_s.write({'mercadolibre_bindings': [(3, b.id)]})
                if new and 'mercadolibre_bindings' in new._fields:
                    new_s = new.sudo().with_context(ctx)
                    if b.id not in new_s.mercadolibre_bindings.ids:
                        new_s.write({'mercadolibre_bindings': [(4, b.id)]})
                _logger.info("[bind-rels] %s %s: %s %s -> %s (lista Bindings actualizada)",
                             b._name, b.id, owner_field, old.ids if old else [], new.ids if new else [])
        except Exception as e:
            _logger.warning("[bind-rels] %s %s: no pude mover la lista Bindings %s -> %s: %s",
                            b._name, b.id, old.ids if old else [], new.ids if new else [], e)


class MercadoLibreBindingProductTemplateRels(models.Model):
    _inherit = "mercadolibre.product_template"

    def write(self, vals):
        before = _meli_sync_bind_rels(self, vals, 'product_tmpl_id')
        res = super(MercadoLibreBindingProductTemplateRels, self).write(vals)
        _meli_apply_bind_rels(self, before, 'product_tmpl_id')
        return res


class MercadoLibreBindingProductRels(models.Model):
    _inherit = "mercadolibre.product"

    def write(self, vals):
        before = _meli_sync_bind_rels(self, vals, 'product_id')
        res = super(MercadoLibreBindingProductRels, self).write(vals)
        _meli_apply_bind_rels(self, before, 'product_id')
        return res
