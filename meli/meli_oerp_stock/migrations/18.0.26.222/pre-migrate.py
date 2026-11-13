# -*- coding: utf-8 -*-
# 26.188 (un caso): stock.picking.meli_handling_limit pasa a almacenado y toma el valor
# del pedido (sale_id.meli_handling_limit, que ya llenó meli_oerp 26.188). Se crea y
# llena por SQL para evitar el recompute registro por registro.
import logging
_logger = logging.getLogger(__name__)


def _has_column(cr, table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema()
                     AND table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return
    cr.execute("ALTER TABLE stock_picking ADD COLUMN IF NOT EXISTS meli_handling_limit timestamp")
    if _has_column(cr, 'sale_order', 'meli_handling_limit'):
        cr.execute("""
            UPDATE stock_picking p
               SET meli_handling_limit = so.meli_handling_limit
              FROM sale_order so
             WHERE p.sale_id = so.id
               AND so.meli_handling_limit IS NOT NULL
        """)
    elif _has_column(cr, 'mercadolibre_shipment', 'estimated_handling_limit'):
        cr.execute("""
            UPDATE stock_picking p
               SET meli_handling_limit = s.estimated_handling_limit
              FROM sale_order so
              JOIN mercadolibre_shipment s ON s.id = so.meli_shipment
             WHERE p.sale_id = so.id
               AND s.estimated_handling_limit IS NOT NULL
        """)
    else:
        # Guarda (26.226, detectado en un cliente): estimated_handling_limit nace en 26.16 de
        # meli_oerp. Sin ninguna de las dos columnas origen no hay nada que copiar.
        _logger.info("meli_oerp_stock 26.222: sin columna origen (upgrade desde < 26.16); nada que copiar")
        return
    _logger.info("meli_oerp_stock 26.222 (SLA, era 26.188): stock_picking.meli_handling_limit llenado en %s entregas", cr.rowcount)
