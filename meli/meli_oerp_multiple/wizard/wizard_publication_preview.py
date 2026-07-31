# -*- coding: utf-8 -*-
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class MeliPublicationPreviewWizard(models.TransientModel):
    _name = 'meli.publication.preview.wizard'
    _description = 'Preview de Publicación MercadoLibre'

    product_tmpl_id = fields.Many2one('product.template', string='Producto Template', readonly=True)
    product_id = fields.Many2one('product.product', string='Variante', readonly=True)

    # JSON que se enviará
    json_body = fields.Text(string='JSON Body (POST/PUT)', readonly=True)
    json_body_formatted = fields.Html(string='JSON Body Formateado', readonly=True, sanitize=False)

    # JSON de variaciones
    json_variations = fields.Text(string='JSON Variaciones', readonly=True)
    json_variations_formatted = fields.Html(string='Variaciones Formateadas', readonly=True, sanitize=False)

    # Información adicional
    meli_id = fields.Char(string='ML ID (si existe)', readonly=True)
    operation_type = fields.Selection([
        ('create', 'Crear Nueva Publicación'),
        ('update', 'Actualizar Publicación Existente')
    ], string='Tipo de Operación', readonly=True)

    images_info = fields.Text(string='Información de Imágenes', readonly=True)
    images_info_formatted = fields.Html(string='Imágenes Formateadas', readonly=True, sanitize=False)

    warnings = fields.Text(string='Advertencias', readonly=True)

    def _format_json_to_html(self, data, title=""):
        """Convierte un dict/JSON a HTML formateado con colores"""
        if not data:
            return "<p>Sin datos</p>"

        try:
            if isinstance(data, str):
                data = json.loads(data)

            json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)

            # Escapar caracteres HTML
            json_str = json_str.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            # Colorear JSON
            # Strings
            import re
            json_str = re.sub(r'"([^"]*)":', r'<span style="color:#0066cc;">"\1"</span>:', json_str)
            json_str = re.sub(r': "([^"]*)"', r': <span style="color:#009900;">"\1"</span>', json_str)
            # Numbers
            json_str = re.sub(r': (\d+\.?\d*)', r': <span style="color:#cc6600;">\1</span>', json_str)
            # Booleans/null
            json_str = re.sub(r': (true|false|null)', r': <span style="color:#990099;">\1</span>', json_str)

            html = f"""
            <div style="background:#f8f8f8; border:1px solid #ddd; border-radius:4px; padding:10px; margin:5px 0;">
                {f'<h4 style="margin:0 0 10px 0; color:#333;">{title}</h4>' if title else ''}
                <pre style="margin:0; font-family:monospace; font-size:12px; white-space:pre-wrap; word-wrap:break-word;">{json_str}</pre>
            </div>
            """
            return html
        except Exception as e:
            return f"<p style='color:red;'>Error formateando JSON: {str(e)}</p><pre>{str(data)}</pre>"

    @api.model
    def create_preview(self, product_tmpl_id=None, product_id=None):
        """Crea el preview de publicación para un producto"""

        if product_tmpl_id:
            product_tmpl = self.env['product.template'].browse(product_tmpl_id)
            product = product_tmpl.meli_pub_principal_variant or product_tmpl.product_variant_ids[:1]
        elif product_id:
            product = self.env['product.product'].browse(product_id)
            product_tmpl = product.product_tmpl_id
        else:
            raise ValidationError(_("Debe especificar un producto"))

        if not product:
            raise ValidationError(_("No se encontró variante del producto"))

        # Obtener configuración
        company = self.env.user.company_id
        config = company

        # Obtener MELI instance
        meli_util = self.env['meli.util']
        meli = meli_util.get_new_instance(company)

        if not meli or meli.need_login():
            raise ValidationError(_("Debe iniciar sesión en MercadoLibre primero"))

        # Determinar tipo de operación
        meli_id = product.meli_id
        operation_type = 'update' if meli_id else 'create'

        # Obtener productjson actual si existe
        productjson = None
        if meli_id:
            try:
                response = meli.get("/items/" + str(meli_id), {'access_token': meli.access_token, 'include_attributes': 'all'})
                productjson = response.json() if response else None
            except Exception as e:
                _logger.warning("Error obteniendo producto de ML: %s", str(e))

        # Preparar atributos
        attributes = []
        if hasattr(product, '_product_post_set_attributes'):
            attributes = product._product_post_set_attributes(product_tmpl=product_tmpl, product=product, meli=meli, config=config)

        # Preparar imágenes
        images_info = self._get_images_info(product_tmpl, product, meli, config)

        # Preparar body
        body = self._prepare_preview_body(product_tmpl, product, meli, config, attributes, productjson)

        # Preparar variaciones
        variations_data = None
        if product_tmpl.meli_pub_as_variant and len(product_tmpl.product_variant_ids) > 1:
            variations_data = self._prepare_variations_preview(product_tmpl, product, meli, config)

        # Preparar advertencias
        warnings = self._check_warnings(product_tmpl, product, body, images_info)

        # Crear wizard
        vals = {
            'product_tmpl_id': product_tmpl.id,
            'product_id': product.id,
            'meli_id': meli_id or '',
            'operation_type': operation_type,
            'json_body': json.dumps(body, indent=2, ensure_ascii=False, default=str) if body else '',
            'json_body_formatted': self._format_json_to_html(body, "Body de Publicación"),
            'images_info': json.dumps(images_info, indent=2, ensure_ascii=False) if images_info else '',
            'images_info_formatted': self._format_json_to_html(images_info, "Información de Imágenes"),
            'warnings': warnings,
        }

        if variations_data:
            vals['json_variations'] = json.dumps(variations_data, indent=2, ensure_ascii=False, default=str)
            vals['json_variations_formatted'] = self._format_json_to_html(variations_data, "Variaciones")

        wizard = self.create(vals)

        return {
            'name': _('Preview de Publicación ML'),
            'type': 'ir.actions.act_window',
            'res_model': 'meli.publication.preview.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
            'context': self.env.context,
        }

    def _get_images_info(self, product_tmpl, product, meli, config):
        """Obtiene información sobre las imágenes que se publicarían"""
        from ..models.product import variant_image_ids, template_image_ids, get_image_full

        info = {
            'prioridad_orden': [
                '1. Imagen principal de cada variante (image_variant_1920)',
                '2. Imagen principal del template (image_1920)',
                '3. Imágenes adicionales del template (galería)',
                '4. Imágenes adicionales de variantes',
            ],
            'P1_variantes_con_imagen_propia': [],
            'P2_template_main_image': bool(product_tmpl.image_1920),
            'P3_template_additional_images': 0,
            'P4_variant_additional_images': 0,
            'total_images': 0,
            'max_allowed': 10,
            'will_use_new_system': False,
        }

        # P1: Imagen principal propia de cada variante
        for variant in product_tmpl.product_variant_ids:
            has_own = bool(hasattr(variant, 'image_variant_1920') and variant.image_variant_1920)
            if has_own:
                info['P1_variantes_con_imagen_propia'].append(variant.display_name)
                info['total_images'] += 1

        # P2: Imagen principal del template
        if product_tmpl.image_1920:
            info['total_images'] += 1

        # P3: Imágenes adicionales del template
        tpl_images = template_image_ids(product_tmpl)
        if tpl_images:
            info['P3_template_additional_images'] = len(tpl_images)
            info['total_images'] += len(tpl_images)

        # P4: Imágenes adicionales de variantes
        for variant in product_tmpl.product_variant_ids:
            var_images = variant_image_ids(variant)
            if var_images:
                info['P4_variant_additional_images'] += len(var_images)
                info['total_images'] += len(var_images)

        # ¿Usará el nuevo sistema?
        info['will_use_new_system'] = product_tmpl.meli_pub_as_variant and len(product_tmpl.product_variant_ids) > 1

        # Advertencia si excede límite
        if info['total_images'] > info['max_allowed']:
            info['se_recortaran'] = f"Se encontraron {info['total_images']} imágenes, se recortarán a {info['max_allowed']} (prioridad baja se elimina primero)"

        return info

    def _prepare_preview_body(self, product_tmpl, product, meli, config, attributes, productjson):
        """Prepara el body que se enviaría a ML (sin enviar realmente)"""
        body = {
            'title': product.meli_title or product_tmpl.name or '',
            'category_id': product.meli_category.meli_category_id if product.meli_category else 'NO DEFINIDA',
            'listing_type_id': product.meli_listing_type or 'NO DEFINIDO',
            'buying_mode': product.meli_buying_mode or 'buy_it_now',
            'price': product.meli_price or 0,
            'currency_id': product.meli_currency or 'ARS',
            'condition': product.meli_condition or 'new',
            'available_quantity': product.meli_available_quantity or 0,
            'video_id': product.meli_video or '',
            'pictures': '[Se generarán al publicar]',
        }

        if product.meli_description:
            body['description'] = {'plain_text': product.meli_description[:200] + '...' if len(product.meli_description or '') > 200 else product.meli_description}

        if attributes:
            body['attributes'] = attributes

        if product.default_code and config.mercadolibre_post_default_code:
            body['seller_custom_field'] = product.default_code

        # Info de shipping
        if product.meli_shipping_mode:
            body['shipping'] = {'mode': product.meli_shipping_mode}

        return body

    def _prepare_variations_preview(self, product_tmpl, product, meli, config):
        """Prepara preview de variaciones"""
        variations = []

        for variant in product_tmpl.product_variant_ids:
            if not variant._conditions_ok():
                continue

            var_data = {
                'variant_name': variant.display_name,
                'default_code': variant.default_code or '',
                'price': product_tmpl.meli_price or 0,
                'available_quantity': variant.meli_available_quantity or 0,
                'attribute_combinations': [],
                'picture_ids': '[Se asignarán según imágenes]',
            }

            # Obtener combinaciones de atributos
            if hasattr(variant, '_combination'):
                comb = variant._combination()
                if comb and 'attribute_combinations' in comb:
                    var_data['attribute_combinations'] = comb['attribute_combinations']

            # Info de imagen específica
            if hasattr(variant, 'image_variant_1920') and variant.image_variant_1920:
                var_data['has_specific_image'] = True
            else:
                var_data['has_specific_image'] = False

            variations.append(var_data)

        return {
            'total_variations': len(variations),
            'variations': variations,
        }

    def _check_warnings(self, product_tmpl, product, body, images_info):
        """Verifica posibles problemas antes de publicar"""
        warnings = []

        if not product.meli_category:
            warnings.append("⚠️ No hay categoría ML definida")

        if not product.meli_title and not product_tmpl.name:
            warnings.append("⚠️ No hay título definido")

        # meli_price es Char (product.py); castear seguro a float contemplando coma
        # decimal (ML puede traer "42144,08" o "42144.08") para no romper con TypeError
        # str<=int al comparar (bloqueaba la publicación de cualquier producto con precio).
        _mp = str(product.meli_price or '').replace(',', '.').strip()
        try:
            _mp_val = float(_mp) if _mp else 0.0
        except (ValueError, TypeError):
            _mp_val = 0.0
        if not product.meli_price or _mp_val <= 0:
            warnings.append("⚠️ El precio no está definido o es 0")

        if not product_tmpl.image_1920:
            warnings.append("⚠️ No hay imagen principal en el template")

        if images_info.get('total_images', 0) > images_info.get('max_allowed', 10):
            warnings.append(f"⚠️ Hay {images_info['total_images']} imágenes, se recortarán a {images_info['max_allowed']}")

        if product_tmpl.meli_pub_as_variant and not product_tmpl.meli_pub_principal_variant:
            warnings.append("⚠️ Publicar como variante está activo pero no hay variante principal definida")

        if not product.meli_listing_type:
            warnings.append("⚠️ No hay tipo de publicación definido")

        return '\n'.join(warnings) if warnings else "✅ Todo parece correcto para publicar"

    def action_proceed_publish(self):
        """Procede a publicar después del preview"""
        self.ensure_one()

        if self.product_tmpl_id:
            return self.product_tmpl_id.product_template_post()
        elif self.product_id:
            return self.product_id.product_meli_post()

        raise ValidationError(_("No hay producto para publicar"))
