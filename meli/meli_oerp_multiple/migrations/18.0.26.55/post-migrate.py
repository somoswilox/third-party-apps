# -*- coding: utf-8 -*-
"""Migración tri-estado del cupón ML: meli_coupon_discount_on_invoice (bool) -> meli_coupon_invoice_mode.
True  -> 'product_discount'   (comportamiento del flag ON)
False -> 'full'               (precio pleno; ya es el default del campo nuevo)
Solo se ajustan los registros que tenían el flag activado. [#433]"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    Model = env['mercadolibre.configuration']
    if "meli_coupon_discount_on_invoice" not in Model._fields or "meli_coupon_invoice_mode" not in Model._fields:
        return
    recs = Model.search([("meli_coupon_discount_on_invoice", "=", True)])
    if recs:
        recs.write({"meli_coupon_invoice_mode": "product_discount"})
        _logger.info("meli cupón tri-estado: %d registro(s) -> product_discount", len(recs))
