# -*- coding: utf-8 -*-
"""caso-K30 (un cliente MX, 05-nov-2026): un AJUSTE DE INVENTARIO no marcaba el binding para publicar.

Caso medido en produccion (19.0.26.270): la usuaria cambio la cantidad de una carta desde la ficha
del producto (1 -> 2). El sello del producto (product_product.meli_stock_moves_update) avanzo a la
hora del ajuste, pero el del binding quedo en el anterior; como el binding tenia un envio posterior
a ese sello viejo, _batch_update_stock_status lo dejo 'updated' y ningun cron lo planifico (Plan 0/0).

A diferencia de test_stock_stamp_flush (que arma el sello por escritura ORM), este test recorre el
CAMINO REAL de la pantalla: stock.quant en modo inventario -> action_apply_inventory -> stock.move
_action_done -> hook de meli (_update_meli_bindings DIRECT). Lee la BASE por SQL.
"""

from datetime import datetime

from odoo.tests import TransactionCase, tagged

from . import test_stock_stamp_flush as _t475


T_VIEJO = datetime(2020, 10, 31, 0, 25, 3)    # sello anterior del producto y del binding
T_PUSH = datetime(2020, 11, 3, 19, 0, 14)     # ultimo envio, posterior al sello viejo


@tagged('post_install', '-at_install', 'meli_K30', 'meli_K30_ajuste')
class TestAjusteInventarioMarcaBinding(TransactionCase):

    _crear_minimo = _t475.TestStockStampFlush._crear_minimo
    _cuenta = _t475.TestStockStampFlush._cuenta

    def _escenario(self):
        cuenta = self._cuenta()
        cfg = cuenta.configuration or cuenta.company_id
        if 'mercadolibre_cron_post_update_stock' in cfg._fields:
            cfg.mercadolibre_cron_post_update_stock = True
        vals = {'name': 'TEST K30 AJUSTE', 'default_code': 'TEST-K30-AJUSTE'}
        Product = self.env['product.product']
        if 'is_storable' in Product._fields:
            vals.update({'type': 'consu', 'is_storable': True})
        else:
            vals['type'] = 'product'
        prod = Product.create(vals)
        bind = self.env['mercadolibre.product'].create({
            'name': 'TEST K30', 'product_id': prod.id,
            'connection_account': cuenta.id, 'conn_id': 'MLMK30000001',
            'meli_id': 'MLMK30000001'})
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("UPDATE product_product SET meli_stock_moves_update=%s WHERE id=%s",
                   (T_VIEJO, prod.id))
        cr.execute("""UPDATE mercadolibre_product
                         SET meli_stock_moves_update=%s, product_meli_stock_moves_update=%s,
                             stock_update=%s, meli_stock_status='updated',
                             meli_last_status='active', stock_error=NULL
                       WHERE id=%s""", (T_VIEJO, T_VIEJO, T_PUSH, bind.id))
        self.env.invalidate_all()
        return prod, bind

    def _leer(self, prod, bind):
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("SELECT meli_stock_moves_update FROM product_product WHERE id=%s", (prod.id,))
        p_stamp = cr.fetchone()[0]
        cr.execute("SELECT meli_stock_moves_update, meli_stock_status FROM mercadolibre_product "
                   "WHERE id=%s", (bind.id,))
        b_stamp, status = cr.fetchone()
        return p_stamp, b_stamp, status

    def test_ajuste_desde_la_ficha_deja_el_binding_en_la_cola(self):
        prod, bind = self._escenario()
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        quant = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': prod.id, 'location_id': wh.lot_stock_id.id, 'inventory_quantity': 2.0})
        quant.action_apply_inventory()
        p_stamp, b_stamp, status = self._leer(prod, bind)
        # control del escenario: el ajuste SI movio el sello del producto (si no, el test no mide nada)
        self.assertTrue(p_stamp and p_stamp > T_PUSH,
                        "control: el ajuste tiene que mover el sello del PRODUCTO (%s)" % p_stamp)
        self.assertEqual(b_stamp, p_stamp,
                         "el binding tiene que tomar el sello del ajuste (binding=%s producto=%s)"
                         % (b_stamp, p_stamp))
        self.assertEqual(status, 'update', "el ajuste tiene que dejar el binding en la cola del cron")
