# -*- coding: utf-8 -*-
"""MODO FAMILIA — publicación de plantillas con variantes en cuentas user_product_seller (#caso-K21 cliente F, 28-sep-2026).

Mercado Libre ya no acepta variations[] en estas cuentas: cada variante es su propia publicación y ML
las agrupa por family_name. Toda esa lógica vive ACÁ, en una sola unidad:

  product.template._meli_post_family            ← entrada única (binding: product_template_post)
    1. _meli_family_plan                        variantes de ESTE binding + publicación de cada una
    2. _meli_family_preflight                   básicos → categoría/atributo de variación → GTIN
    3. _meli_family_post_variant (savepoint)    alta/actualización (product_post) + _meli_family_bind
         └─ product.product._meli_family_item_body   body por variante (lo invoca _product_set_variations)
    4. meli_family.family_post_summary          resumen al usuario

Decisiones puras (sin Odoo, con tests) en models/meli_family.py. Flujo documentado en
.roots/docs/publicacion-modo-familia.md.

26.371 (B1 armonización 18.0): este camino NO se prende solo por ser cuenta user_product. Lo elige
el botón «Publicar (nuevo)» del asistente (contexto meli_post_mode='family') o el binding que ya se
publicó así (campo `meli_post_mode` = 'family'). Con modo 'classic' (default) el código es el del
source anterior sin cambios.
"""
import logging

from odoo import models
from odoo.tools import html2plaintext

from . import meli_family as _mf
from .versions import att_value_ids

try:
    from odoo.addons.meli_oerp.models.product import _meli_is_valid_gtin
except Exception:  # meli_oerp viejo: sin validador, se acepta cualquier código no vacío
    def _meli_is_valid_gtin(code):
        return bool(code)

_logger = logging.getLogger(__name__)


class _MeliFamilyVariantError(Exception):
    """Error al publicar UNA variante: vuelve al savepoint de esa variante sin tocar lo que ya quedó
    publicado y vinculado de las otras."""


class ProductTemplateMeliFamily(models.Model):
    _inherit = "product.template"

    # ------------------------------------------------------------------------------------------
    # #caso-K21 cliente F (28-sep-2026) — MODO FAMILIA (cuentas user_product_seller)
    #
    # ML ya no acepta variations[] en estas cuentas: cada variante es una publicación propia y ML
    # las agrupa por family_name. Este es el ÚNICO camino de publicación de una plantilla en una
    # cuenta así (con o sin 'publicar como variantes'):
    #   1. pre-flight SIN red hacia /items: atributo ML que diferencia las variantes (resuelto por la
    #      categoría si el atributo de Odoo no está mapeado) y GTIN por variante. Si falta algo, no
    #      se publica NADA y el usuario recibe qué falta y cómo cargarlo;
    #   2. cada variante en su SAVEPOINT: si falla, vuelve atrás SÓLO esa; lo ya publicado queda
    #      guardado y vinculado (antes: raise/rollback ⇒ publicación viva huérfana);
    #   3. cada variante se vincula a SU publicación (binding de variante + product.meli_id);
    #   4. resumen al usuario con lo publicado y lo que falló.
    # ------------------------------------------------------------------------------------------
    def _meli_family_account_bindings(self, account):
        """Bindings de plantilla de ESTA plantilla en la cuenta (por búsqueda, no por el m2m)."""
        self.ensure_one()
        return self.env["mercadolibre.product_template"].search(
            [("product_tmpl_id", "=", self.id), ("connection_account", "=", account.id)], order="id")

    def _meli_family_template_binding(self, account, meli=None, new_pub=False):
        """El binding de plantilla de la cuenta para el modo familia: el más viejo CON publicación,
        si no el más viejo, si no uno nuevo (sin variantes: cada una se vincula al publicarse)."""
        self.ensure_one()
        mine = self._meli_family_account_bindings(account)
        if not new_pub:
            bindT = mine.filtered(lambda b: b.conn_id)[:1] or mine[:1]
            if bindT:
                return bindT
        return self.mercadolibre_bind_to(account=account, meli_id=None, meli=meli, bind_variants=False)

    def _meli_family_variants_to_post(self, force_context=None, only_variants=None):
        self.ensure_one()
        ctx = force_context or {}
        variants = self.product_variant_ids
        if only_variants is not None:
            variants = variants & only_variants
        if self.meli_pub_as_variant:
            for v in variants:
                try:
                    if v._conditions_ok():
                        v.meli_pub = True
                except Exception:
                    pass
        elif ctx.get("force_meli_pub"):
            variants.filtered(lambda v: not v.meli_pub).write({"meli_pub": True})
        variants = variants.filtered(lambda v: v.meli_pub)
        principal = self.meli_pub_principal_variant
        order = _mf.order_family_variants(variants.ids, principal.id or None)
        return self.env["product.product"].browse(order)

    def _meli_family_listing(self, variant, account, force_new=False, bindT=None):
        """(listing_id, error) de UNA variante en ESTA cuenta y ESTE binding de plantilla.
        Nunca la de otra variante (caso a)."""
        if force_new:
            return None, None
        vb_obj = self.env["mercadolibre.product"]
        dom = [("product_id", "=", variant.id), ("conn_id", "!=", False)]
        mine = bindT and bindT.exists() and bindT.variant_bindings.filtered(
            lambda b: b.product_id.id == variant.id and b.conn_id)[:1]
        if not mine and account:
            mine = vb_obj.search(dom + [("connection_account", "=", account.id)], order="id desc", limit=1)
        listing = _mf.listing_id_for_variant(mine and mine.conn_id, variant.meli_id)
        if account and not (mine and mine.conn_id) and variant.meli_id:
            other = vb_obj.search(dom + [("connection_account", "!=", account.id),
                                         ("conn_id", "=", variant.meli_id)], limit=1)
            if other:
                return None, ("la variante ya está publicada en otra cuenta (%s, %s); en modo familia "
                              "no se publica la misma variante en dos cuentas desde la plantilla"
                              % (other.connection_account.name, variant.meli_id))
        return listing, None

    def _meli_family_preflight(self, creating, meli=None, config=None):
        """Mensaje de bloqueo (str) o None. Sólo para variantes que se van a CREAR."""
        self.ensure_one()
        if not creating:
            return None
        pp = self.env["product.product"]
        # 1c: primero lo BÁSICO, con los mismos fallbacks que usa el alta (_product_post_set_*)
        category = self._meli_family_resolve_category(creating)
        title = self.meli_title or self.name or any(creating.mapped("meli_title"))
        listing_type = (self.meli_listing_type or any(creating.mapped("meli_listing_type"))
                        or (config is not None and "mercadolibre_listing_type" in config._fields
                            and config.mercadolibre_listing_type))
        price = self.meli_price or any(creating.mapped("meli_price")) or self.list_price
        missing = _mf.basic_missing(has_category=bool(category), has_title=bool(title),
                                    has_price=bool(price), has_listing_type=bool(listing_type))
        if missing:
            return _mf.basic_missing_message(missing)
        cat_atts = pp._meli_get_category_attributes(category, meli=meli) if meli else []
        read_error = (not cat_atts) and (not meli or pp._meli_category_attributes_read_error(category))
        # (c) atributo de ML que diferencia las variantes
        if len(self.product_variant_ids) > 1:
            specs = pp._meli_family_line_specs(self)
            mapping, unresolved, cands = _mf.resolve_variant_lines(specs, cat_atts)
            if unresolved:
                return _mf.missing_mapping_message(
                    unresolved, cands, category.meli_category_id or category.name, read_error=bool(read_error))
        # GTIN por variante (variante sin EAN: error claro ANTES de publicar)
        base = pp._meli_family_base_attributes(self)
        vs = [{"label": v.default_code or v.display_name,
               "gtin": v.barcode if (v.barcode and _meli_is_valid_gtin(v.barcode)) else None}
              for v in creating]
        missing = _mf.variants_missing_gtin(vs, cat_atts, base)
        if missing:
            return _mf.missing_gtin_message(missing, cat_atts)
        return None

    def _meli_family_resolve_category(self, variants=None):
        """Categoría de ML con la que va a salir el alta — mismo criterio que _product_post_set_category:
        la de la plantilla, la de una variante o la de una categoría del sitio web mapeada."""
        self.ensure_one()
        variants = variants if variants is not None else self.product_variant_ids
        cat = self.meli_category or next((v.meli_category for v in variants if v.meli_category), False)
        if not cat and "public_categ_ids" in self._fields:
            cat = next((c.mercadolibre_category for c in self.public_categ_ids
                        if "mercadolibre_category" in c._fields and c.mercadolibre_category), False)
        return cat

    def _meli_family_bind(self, bindT, variant, account, meli=None):
        """Vincula `variant` a SU publicación (variant.meli_id) dentro del binding de plantilla de la
        cuenta. Crea el binding de plantilla si no hay (o si el que venía fue borrado). Limpia los
        bindings VACÍOS (sin publicación) de esa variante que dejaron intentos anteriores."""
        self.ensure_one()
        if not account or not variant.meli_id:
            return bindT
        tb_obj = self.env["mercadolibre.product_template"]
        vb_obj = self.env["mercadolibre.product"]
        if not (bindT and bindT.exists()):
            bindT = tb_obj.search([("product_tmpl_id", "=", self.id), ("connection_account", "=", account.id),
                                   ("conn_id", "!=", False)], order="id", limit=1)
            if not bindT:
                bindT = tb_obj.search([("product_tmpl_id", "=", self.id), ("connection_account", "=", account.id)],
                                      order="id", limit=1)
            if not bindT:
                bindT = self.mercadolibre_bind_to(account=account, meli_id=variant.meli_id,
                                                  bind_variants=False, meli=meli)
        if not bindT:
            return bindT
        tvals = {}
        if "meli_post_mode" in bindT._fields and bindT.meli_post_mode != "family":
            tvals["meli_post_mode"] = "family"
        if not bindT.conn_id:
            tvals["conn_id"] = variant.meli_id
        fam = "meli_family_id" in variant._fields and variant.meli_family_id
        if fam and "meli_family_id" in bindT._fields and not bindT.meli_family_id:
            tvals["meli_family_id"] = fam
        if tvals:
            bindT.write(tvals)
        vb = vb_obj.search([("product_id", "=", variant.id), ("connection_account", "=", account.id),
                            ("conn_id", "=", variant.meli_id)], order="id desc", limit=1)
        if not vb:
            vb = bindT.variant_bindings.filtered(
                lambda b: b.product_id.id == variant.id and (not b.conn_id or b.conn_id == variant.meli_id))[:1]
        vvals = {"conn_id": variant.meli_id, "meli_id": variant.meli_id,
                 "conn_variation_id": False, "meli_id_variation": False}
        if "meli_post_mode" in vb_obj._fields:
            vvals["meli_post_mode"] = "family"
        if fam and "meli_family_id" in vb_obj._fields:
            vvals["meli_family_id"] = fam
        if vb:
            if not vb.binding_product_tmpl_id:
                vvals["binding_product_tmpl_id"] = bindT.id
            vb.write(vvals)
        else:
            vb = variant.mercadolibre_bind_to(account, binding_product_tmpl_id=bindT,
                                              meli_id=variant.meli_id, meli=meli)
            if vb:
                vb.write(vvals)
        if vb:
            variant.mercadolibre_bindings = [(4, vb.id)]
            self.mercadolibre_bindings = [(4, (vb.binding_product_tmpl_id or bindT).id)]
        # placeholders vacíos de intentos anteriores (los 3922/3982 de cliente F): sólo sin publicación
        empties = vb_obj.search([("product_id", "=", variant.id), ("connection_account", "=", account.id),
                                 ("conn_id", "=", False)])
        if vb:
            empties -= vb
        if empties:
            _logger.info("meli family: borrando bindings vacíos de %s: %s", variant.display_name, empties.ids)
            empties.unlink()
        empty_tpl = tb_obj.search([("product_tmpl_id", "=", self.id), ("connection_account", "=", account.id),
                                   ("conn_id", "=", False)]).filtered(lambda t: not t.variant_bindings and t != bindT)
        if empty_tpl:
            empty_tpl.unlink()
        try:
            if vb:
                vb.update_price()
        except Exception:
            _logger.exception("meli family: update_price del binding %s", vb)
        return bindT

    # ---------------------------------------------------------------- orquestador (entrada única)
    def _meli_post_family(self, bindT=None, account=None, meli=None, config=None, force_context=None,
                          only_variants=None):
        """ENTRADA ÚNICA del modo familia. Pasos:
          1. PLAN       (_meli_family_plan): qué variantes procesa ESTE binding y cuál es la publicación
                        de cada una; None si es una publicación legacy CON variations (camino clásico).
          2. PRE-FLIGHT (_meli_family_preflight): sólo si hay ALTAS; sin red hacia /items.
          3. POR VARIANTE (_meli_family_post_variant): savepoint, alta o actualización, vínculo, y
                        recuperación del vínculo si ML ya la creó y algo falló después.
          4. RESUMEN    (meli_family.family_post_summary): lo publicado y lo que falló.
        Devuelve (publicadas, acción|{}, resultados) o None (legacy)."""
        self.ensure_one()
        warningobj = self.env["meli.warning"]
        account = account or (bindT and bindT.exists() and bindT.connection_account) or None
        config = config or (account and account.configuration) or self.env.user.company_id
        if not meli and account:
            meli = self.env["meli.util"].get_new_instance(account.company_id, account)
        created_log = []
        ctx = dict(force_context or {})
        ctx.update({"family_name_variant_post": True, "meli_keep_published": True,
                    "meli_created_listings": created_log, "meli_post_mode": "family"})

        planned = self._meli_family_plan(bindT=bindT, account=account, ctx=ctx, only_variants=only_variants)
        if planned is None:
            return None
        plan, results = planned
        if not plan and not results:
            return 0, {}, []

        creating = self.env["product.product"].browse([v.id for v, listing in plan if not listing])
        block = self._meli_family_preflight(creating, meli=meli, config=config)
        if block:
            _logger.warning("meli family pre-flight %s: %s", self.display_name, block)
            return 0, warningobj.info(title="MELI WARNING", message=block, message_html=""), results

        posted = 0
        for v, listing in plan:
            res, bindT = self._meli_family_post_variant(v, listing, bindT=bindT, account=account, meli=meli,
                                                        config=config, ctx=ctx, created_log=created_log)
            results.append(res)
            if res.get("meli_id"):
                posted += 1

        has_error, text = _mf.family_post_summary(results)
        _logger.info("meli family %s: %s", self.display_name, text.replace("\n", " | "))
        if has_error:
            return posted, warningobj.info(title="MELI WARNING", message=text, message_html=""), results
        return posted, {}, results

    # ---------------------------------------------------------------- 1. plan
    def _meli_family_plan(self, bindT=None, account=None, ctx=None, only_variants=None):
        """([(variante, publicación|None)], resultados_con_error) o None si es legacy con variations."""
        self.ensure_one()
        ctx = ctx or {}
        force_new = bool(ctx.get("force_meli_new_pub"))
        variants = self._meli_family_variants_to_post(force_context=ctx, only_variants=only_variants)
        vb_obj = self.env["mercadolibre.product"]
        if variants and bindT and bindT.exists() and account and not force_new:
            # este binding procesa SUS variantes; el primario de la cuenta, además, las que todavía
            # no tienen publicación vinculada en la cuenta (altas nuevas / vínculo perdido).
            acc_vbs = vb_obj.search([("product_id", "in", variants.ids), ("connection_account", "=", account.id),
                                     ("conn_id", "!=", False)])
            in_this = acc_vbs.filtered(lambda b: b.binding_product_tmpl_id.id == bindT.id).mapped("product_id")
            unbound = variants - acc_vbs.mapped("product_id")
            tbs = self._meli_family_account_bindings(account)
            primary = tbs.filtered(lambda b: b.conn_id)[:1] or tbs[:1]
            keep = in_this | (unbound if (not primary or primary.id == bindT.id) else self.env["product.product"])
            variants = variants.filtered(lambda v: v in keep)
        if not variants:
            return [], []
        plan, results = [], []
        for v in variants:
            listing, err = self._meli_family_listing(v, account, force_new=force_new, bindT=bindT)
            if err:
                results.append({"variant": v.default_code or v.display_name, "meli_id": None, "error": err})
                continue
            plan.append((v, listing))
        # Publicación VIEJA con variations[] (anterior a user_product): variantes que comparten publicación
        # o con id de variación ⇒ NO es modo familia (tocarla borraría el id de variación y el stock).
        listings = [l for _v, l in plan if l]
        legacy_vb = account and vb_obj.search(
            [("product_id", "in", variants.ids), ("connection_account", "=", account.id),
             ("conn_id", "!=", False), ("conn_variation_id", "!=", False)], limit=1)
        if legacy_vb or len(set(listings)) < len(listings):
            _logger.info("meli family: %s tiene una publicación con variaciones (legacy) — camino clásico",
                         self.display_name)
            return None
        return plan, results

    # ---------------------------------------------------------------- 3. una variante
    def _meli_family_post_variant(self, v, listing, bindT=None, account=None, meli=None, config=None, ctx=None,
                                  created_log=None):
        """Alta o actualización de UNA variante, aislada en su savepoint. Devuelve (resultado, bindT)."""
        self.ensure_one()
        pp = self.env["product.product"]
        created_log = created_log if created_log is not None else []
        label = v.default_code or v.display_name
        # apuntar la variante a SU publicación (el binding de la cuenta manda); product.meli_id se
        # restaura si la publicación es ADICIONAL o si es "Crear una nueva publicación"
        pre, restore_meli_id = {}, False
        if listing and listing != v.meli_id:
            pre["meli_id"] = listing
            if v.meli_id:
                restore_meli_id = v.meli_id
        if not listing and v.meli_id:
            restore_meli_id = v.meli_id
            pre["meli_id"] = False
        if v.meli_id_variation:
            pre["meli_id_variation"] = False
        if pre:
            v.write(pre)
        n_created = len(created_log)
        try:
            with self.env.cr.savepoint():
                ret = v.with_context(ctx or {}).product_post(meli=meli, config=config)
                err = pp._meli_ret_error_text(ret)
                if err:
                    raise _MeliFamilyVariantError(err)
                if not v.meli_id:
                    raise _MeliFamilyVariantError("Mercado Libre no devolvió el id de la publicación")
                bindT = self._meli_family_bind(bindT, v, account, meli=meli)
        except Exception as e:
            msg = str(e) if isinstance(e, _MeliFamilyVariantError) else ("%s: %s" % (type(e).__name__, e))
            if not isinstance(e, _MeliFamilyVariantError):
                _logger.exception("meli family: error inesperado publicando %s", v.display_name)
            # (e) si ML YA creó la publicación antes del error, el vínculo se recupera fuera del
            # savepoint: nunca queda una publicación viva sin vínculo en Odoo.
            new_ids = [mid for (pid, mid) in created_log[n_created:] if pid == v.id]
            if new_ids:
                v.write({"meli_id": new_ids[-1], "meli_id_variation": False})
                bindT = self._meli_family_bind(bindT, v, account, meli=meli)
                if restore_meli_id:
                    v.write({"meli_id": restore_meli_id})
                return ({"variant": label, "meli_id": new_ids[-1], "created": True,
                         "error": "publicada y vinculada, pero después falló: " + msg}, bindT)
            if restore_meli_id:
                v.write({"meli_id": restore_meli_id})
            return {"variant": label, "meli_id": None, "error": msg}, bindT
        res = {"variant": label, "meli_id": v.meli_id, "created": not listing}
        if not self.meli_pub_principal_variant:
            self.meli_pub_principal_variant = v
        if restore_meli_id:
            v.write({"meli_id": restore_meli_id})
        return res, bindT


class ProductProductMeliFamily(models.Model):
    _inherit = "product.product"

    # ---------------- #caso-K21 cliente F (28-sep-2026): helpers del modo FAMILIA ----------------
    def _meli_family_template_names(self, source_tmpl=None):
        """Candidatos (en orden) para el family_name, SÓLO de la plantilla: binding de plantilla
        (family_name, título) y product.template (family_name, meli_title, nombre)."""
        names = []
        src = source_tmpl
        tmpl = self.product_tmpl_id
        if src is not None and src and src._name == "mercadolibre.product_template":
            names += [src.meli_family_name if "meli_family_name" in src._fields else None,
                      src.meli_title if "meli_title" in src._fields else None]
            tmpl = src.product_tmpl_id or tmpl
        elif src is not None and src and src._name == "product.template":
            tmpl = src
        if tmpl:
            names += [tmpl.meli_family_name if "meli_family_name" in tmpl._fields else None,
                      tmpl.meli_title, tmpl.name]
        return names

    def _meli_is_new_post_mode(self):
        """26.371: ¿esta llamada va por el camino NUEVO de publicación? Lo decide el contexto
        `meli_post_mode` que ponen el botón «Publicar (nuevo)» y el binding marcado 'family'.
        Sin contexto ⇒ camino clásico (el del source anterior)."""
        return self.env.context.get("meli_post_mode") == "family"

    def _meli_is_family_mode(self, config=None):
        """Modo FAMILIA: camino nuevo (`meli_post_mode`='family') en una cuenta user_product_seller ⇒
        cada variante es su propia publicación (family_name). En cuenta clásica el camino nuevo es
        `_meli_post_separate_variants` (binding de plantilla)."""
        return bool(self._meli_is_new_post_mode()
                    and config is not None and config
                    and "mercadolibre_user_product_seller" in config._fields
                    and config.mercadolibre_user_product_seller)

    def _meli_in_test_mode(self):
        """`registry.in_test_mode()` existe hasta 18.0 y NO en el core 19.0 (ESTUDIO A2.4): guardia
        compatible para las 5 series. Si no se puede saber, se asume que NO es test."""
        reg = self.env.registry
        fn = getattr(reg, "in_test_mode", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                pass
        try:
            from odoo.modules import module as _odoo_module
            if getattr(_odoo_module, "current_test", None):
                return True
        except Exception:
            pass
        try:
            from odoo.tools import config as _odoo_config
            return bool(_odoo_config.get("test_enable"))
        except Exception:
            return False

    def _meli_family_line_specs(self, product_tmpl):
        """Líneas de atributo de la plantilla en forma plana para `meli_family.resolve_variant_lines`."""
        specs = []
        tmpl = product_tmpl
        if tmpl and "product_tmpl_id" in tmpl._fields and tmpl._name != "product.template":
            tmpl = tmpl.product_tmpl_id
        for line in (tmpl and tmpl.attribute_line_ids) or []:
            att = line.attribute_id
            m = att.meli_default_id_attribute
            specs.append({
                "key": line.id,
                "name": att.name,
                "n_values": len(line.value_ids),
                "values": line.value_ids.mapped("name"),
                "creates_variant": att.create_variant != "no_variant",
                "mapped": (m and m.att_id) and {"id": m.att_id, "name": m.name,
                                                "variation": bool(m.variation_attribute and not m.hidden)} or None,
            })
        return specs

    def _meli_family_base_attributes(self, product_tmpl):
        """Atributos comunes declarados en la plantilla (líneas de un solo valor mapeadas a ML).
        Alcanza para saber, por ejemplo, si el producto declara EMPTY_GTIN_REASON."""
        out = []
        for line in (product_tmpl and product_tmpl.attribute_line_ids) or []:
            m = line.attribute_id.meli_default_id_attribute
            if m and m.att_id and len(line.value_ids) == 1:
                out.append({"id": m.att_id, "value_name": line.value_ids.name})
        return out

    def _meli_family_combination(self, cat_atts=None, lang=None):
        """[{id, value_name, value_id}] que diferencian a ESTA variante dentro de la familia
        (ej. COVER_COLOR=Rosa), resolviendo por categoría si el atributo de Odoo no está mapeado."""
        self.ensure_one()
        specs = self._meli_family_line_specs(self.product_tmpl_id)
        mapping, _unresolved, _c = _mf.resolve_variant_lines(specs, cat_atts or [])
        comb = []
        for ptav in att_value_ids(self):
            c = mapping.get(ptav.attribute_line_id.id)
            if not c:
                continue
            name = ptav.with_context(lang=lang).name if lang else ptav.name
            vname, vid = _mf.normalize_value(name, c.get("values"))
            comb.append({"id": c["id"], "name": c.get("name"), "value_name": vname, "value_id": vid})
        return comb

    def _meli_ret_error_text(self, ret):
        """Texto legible del error que devolvió product_post (acción meli.warning), o None si fue OK."""
        r = ret
        if isinstance(r, (list, tuple)):
            r = r[0] if r else {}
        if not isinstance(r, dict) or not r:
            return None
        if r.get("res_model") == "meli.warning" and r.get("res_id"):
            w = self.env["meli.warning"].browse(r["res_id"]).exists()
            if w:
                parts = [w.message or ""]
                if w.message_html:
                    parts.append(html2plaintext(w.message_html))
                txt = " ".join(p.strip() for p in parts if p and p.strip())
                return (txt or w.title or "error de Mercado Libre")[:800]
        if "name" in r:
            return str(r.get("name"))
        if r.get("type") == "ir.actions.act_url":
            return "Debe iniciar sesión en Mercado Libre"
        if r.get("error"):
            return str(r.get("error"))
        return None

    def _meli_rollback_unless_kept(self):
        """El rollback de _product_post deshace TODO lo de la request, incluido el vínculo de otra
        variante que YA se publicó en ML ⇒ publicación huérfana (#caso-K21 e). Los flujos multi-variante
        piden `meli_keep_published` y aíslan cada variante en su propio savepoint."""
        if self.env.context.get("meli_keep_published"):
            return
        self.env.cr.rollback()

    def _meli_trace_created_listing(self, meli_id):
        """Registro de una ALTA en ML apenas ML la confirma, antes de seguir (#caso-K21 e):
        (1) en la lista del contexto `meli_created_listings` (la usa el llamador para recuperar el
        vínculo si algo falla después); (2) en el log; (3) en ir.logging por un cursor APARTE,
        que sobrevive a un rollback de la transacción principal."""
        lst = self.env.context.get("meli_created_listings")
        if isinstance(lst, list):
            lst.append((self.id, meli_id))
        msg = ("ALTA en Mercado Libre: %s para %s [%s] (product.product %s). Si no aparece vinculada en "
               "Odoo, vincularla — NO republicar (sería un duplicado)." % (
                   meli_id, self.display_name, self.default_code or "", self.id))
        _logger.warning(msg)
        try:
            if self._meli_in_test_mode():
                return
            with self.env.registry.cursor() as cr2:
                cr2.execute("""INSERT INTO ir_logging (create_date, create_uid, type, dbname, name, level,
                                                       message, path, func, line)
                               VALUES (NOW() AT TIME ZONE 'UTC', %s, 'server', %s, %s, 'WARNING', %s, %s, %s, %s)""",
                            (self.env.uid, cr2.dbname, "meli_oerp_multiple.alta", msg,
                             "meli_oerp_multiple/models/product.py", "_product_post", "0"))
        except Exception:
            _logger.exception("meli: no se pudo registrar el alta %s en ir.logging", meli_id)

    # ---------------------------------------------------------------- 3a. body de UNA publicación
    def _meli_family_item_body(self, body, product_tmpl=None, config=None, meli=None, productjson=None):
        """Body de la publicación de ESTA variante en la familia (sin variations[]). A nivel ITEM:
        su SELLER_SKU, su GTIN, el atributo que la diferencia (resuelto por la categoría si el de Odoo
        no está mapeado; desempate por valores) y su foto como principal.
        SIN atributo custom con el valor diferenciador (28-sep, PROD cliente F): ML genera el título con
        family_name + esos valores y el custom lo duplicaba ("… Lila Lila"). En UPDATE (`productjson` =
        GET del item) se borra el custom que haya dejado la etapa 1f.
        Lógica pura en meli_family (build_variant_attributes, custom_cleanup_for_update,
        family_pictures, strip_variations_for_family)."""
        self.ensure_one()
        product = self
        product_tmpl = product_tmpl or product.product_tmpl_id
        _COUNTRY_LANG_MAP = {
            'BR': 'pt_BR', 'AR': 'es_AR', 'MX': 'es_MX', 'CO': 'es_CO',
            'CL': 'es_CL', 'PE': 'es_PE', 'UY': 'es_UY', 'VE': 'es_VE',
            'EC': 'es_EC', 'BO': 'es_BO', 'PY': 'es_PY',
        }
        lang = None
        if config and 'country_id' in config._fields and config.country_id:
            lang = _COUNTRY_LANG_MAP.get(config.country_id.code)
        if not lang and config and 'company_id' in config._fields and config.company_id:
            lang = config.company_id.partner_id.lang
        base = list(body.get("attributes") or [])
        cat = product.meli_category or ("meli_category" in product_tmpl._fields and product_tmpl.meli_category)
        cat_atts = product._meli_get_category_attributes(cat, meli=meli) if (cat and meli) else []
        comb = product._meli_family_combination(cat_atts=cat_atts, lang=lang)
        prev = dict((a.get("id"), a.get("value_name")) for a in base if isinstance(a, dict))
        sku = ((config and config.mercadolibre_post_default_code and product.default_code) or prev.get("SELLER_SKU"))
        gtin = ((config and config.mercadolibre_post_barcode and product.barcode
                 and _meli_is_valid_gtin(product.barcode) and product.barcode) or prev.get("GTIN"))
        atts = _mf.build_variant_attributes(base, sku=sku, gtin=gtin, combination=comb)
        if isinstance(productjson, dict) and productjson.get("id"):
            cat_ids = [a.get("id") for a in (cat_atts or []) if isinstance(a, dict) and a.get("id")]
            cleanup = _mf.custom_cleanup_for_update(productjson.get("attributes"), comb,
                                                    outgoing_attributes=atts, category_ids=cat_ids)
            if cleanup:
                _logger.info("meli family %s: se borra el custom %s del item %s", product.display_name,
                             cleanup, productjson.get("id"))
                atts = atts + cleanup
        body["attributes"] = atts
        if body.get("pictures"):
            body["pictures"] = _mf.family_pictures(body["pictures"], main_id=product.meli_imagen_id or None)
        body, _removed = _mf.strip_variations_for_family(body)
        _logger.info("meli family body %s: sku=%s gtin=%s combinación=%s", product.display_name, sku, gtin, comb)
        return body
