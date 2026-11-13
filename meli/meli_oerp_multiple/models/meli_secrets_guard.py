# -*- coding: utf-8 -*-
"""26.329 (bus 2026-09-25T14:30:56Z, medido en caso-K11): mercadolibre.product(_template).stock_error guardaba el
JSON crudo del error de ML con "access_token". Se limpia al escribir (create/write): punto unico de control.
El helper vive en meli_oerp (models/meli_secrets.py); si el meli_oerp instalado es anterior, el
import no tumba la carga del modulo y se usa una copia local equivalente."""
import re

from odoo import api, models

try:
    from odoo.addons.meli_oerp.models.meli_secrets import meli_scrub_secrets
except ImportError:  # meli_oerp < 26.329
    _KEYS = ('access_token', 'refresh_token', 'client_secret', 'secret_key')
    _KV_RE = re.compile(
        r"""(?i)(["']?(?:access_token|refresh_token|client_secret|secret_key)["']?\s*[:=]\s*["']?)([^"'&,\s}\])]+)""")
    _TOKEN_RE = re.compile(r'\b(APP_USR|TG)-[0-9A-Za-z][0-9A-Za-z\-]{10,}')

    def meli_scrub_secrets(value):
        if isinstance(value, dict):
            return {k: ('***' if (k in _KEYS and v) else meli_scrub_secrets(v)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(meli_scrub_secrets(v) for v in value)
        if isinstance(value, str) and value:
            value = _KV_RE.sub(lambda m: m.group(1) + '***', value)
            return _TOKEN_RE.sub(lambda m: m.group(1) + '-***', value)
        return value

_FIELDS = ('stock_error', 'price_error', 'meli_stock_error', 'meli_price_error')


def _scrub(vals):
    if not isinstance(vals, dict) or not any(f in vals for f in _FIELDS):
        return vals
    vals = dict(vals)
    for f in _FIELDS:
        if isinstance(vals.get(f), str):
            vals[f] = meli_scrub_secrets(vals[f])
    return vals


class MercadoLibreProductTemplateSecretGuard(models.Model):
    _inherit = 'mercadolibre.product_template'

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([_scrub(v) for v in vals_list])

    def write(self, vals):
        return super().write(_scrub(vals))


class MercadoLibreProductSecretGuard(models.Model):
    _inherit = 'mercadolibre.product'

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([_scrub(v) for v in vals_list])

    def write(self, vals):
        return super().write(_scrub(vals))
