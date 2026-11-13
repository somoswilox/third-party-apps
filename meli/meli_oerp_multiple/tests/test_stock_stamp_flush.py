# -*- coding: utf-8 -*-
"""#caso-K30 (cliente Q, 15-oct-2026): validar una recepcion NO marcaba el binding.

Caso medido en produccion: tras validar OV/IN/05788 y OV/IN/05790, el sello del
producto (product_product.meli_stock_moves_update) quedo en 15-oct 20:27 pero el del
binding seguia en el 14-oct (confirmacion de la OC). Causa: el sello del producto se
escribe por ORM (queda en cache) y mercadolibre.product.process_meli_stock_moves_update
lo copia al binding con un UPDATE ... FROM product_product por SQL, que leia el valor
VIEJO de la base. Las publicaciones con un push posterior al sello viejo quedaban
'updated' y el cron no las veia (4 publicaciones de 3 productos).

Los tests arman ese estado y verifican, leyendo la BASE por SQL, que el binding avanza
y queda en 'update'.
"""

from datetime import datetime

from odoo import fields
from odoo.tests import TransactionCase, tagged


T_OC = datetime(2020, 10, 14, 18, 29, 41)      # sello viejo (confirmacion de la OC)
T_PUSH = datetime(2020, 10, 14, 19, 19, 43)    # push posterior al sello viejo


@tagged('post_install', '-at_install', 'meli_K30')
class TestStockStampFlush(TransactionCase):

    def _crear_minimo(self, model, _visitados=None):
        _visitados = _visitados or set()
        Model = self.env[model]
        vals = {}
        for name, f in Model._fields.items():
            if not f.required or f.compute or f.related or f.readonly:
                continue
            if f.type in ('char', 'text', 'html'):
                vals[name] = 'TEST'
            elif f.type == 'integer':
                vals[name] = 1
            elif f.type in ('float', 'monetary'):
                vals[name] = 1.0
            elif f.type == 'boolean':
                vals[name] = False
            elif f.type == 'date':
                vals[name] = fields.Date.today()
            elif f.type == 'datetime':
                vals[name] = fields.Datetime.now()
            elif f.type == 'selection':
                sel = f.selection(Model) if callable(f.selection) else f.selection
                vals[name] = sel[0][0] if sel else False
            elif f.type == 'many2one':
                rec = self.env[f.comodel_name].search([], limit=1)
                if not rec and f.comodel_name not in _visitados:
                    _visitados.add(f.comodel_name)
                    rec = self._crear_minimo(f.comodel_name, _visitados)
                vals[name] = rec.id if rec else False
        return Model.create(vals)

    def _cuenta(self):
        cuenta = self.env['mercadolibre.account'].search([], limit=1)
        if cuenta:
            return cuenta
        try:
            return self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("No se pudo obtener una mercadolibre.account en esta base: %s" % e)

    def _escenario(self):
        """Producto + binding activo con el estado de los 4 omitidos ANTES de validar:
        sello viejo (OC) en producto y binding, push posterior, status 'updated'."""
        cuenta = self._cuenta()
        prod = self.env['product.product'].create({
            'name': 'TEST K30 WELLMAGGLY300', 'default_code': 'TEST-K30-STAMP'})
        bind = self.env['mercadolibre.product'].create({
            'name': 'TEST K30', 'product_id': prod.id,
            'connection_account': cuenta.id, 'conn_id': 'MLM418204764',
            'meli_id': 'MLM418204764'})
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("UPDATE product_product SET meli_stock_moves_update=%s WHERE id=%s",
                   (T_OC, prod.id))
        cr.execute("""UPDATE mercadolibre_product
                         SET meli_stock_moves_update=%s, product_meli_stock_moves_update=%s,
                             stock_update=%s, meli_stock_status='updated',
                             meli_last_status='active', stock_error=NULL
                       WHERE id=%s""", (T_OC, T_OC, T_PUSH, bind.id))
        self.env.invalidate_all()
        return prod, bind

    def _leer_binding(self, bind):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT meli_stock_moves_update, meli_stock_status FROM mercadolibre_product WHERE id=%s",
            (bind.id,))
        return self.env.cr.fetchone()

    def test_binding_lee_el_sello_del_producto_sin_flushear(self):
        """El sello nuevo del producto escrito por ORM (sin flush) llega al binding."""
        prod, bind = self._escenario()
        nuevo = datetime(2020, 10, 15, 20, 27, 2)
        # Igual que _meli_write_moves_stamp: escritura ORM, queda en cache.
        prod._meli_write_moves_stamp(nuevo, current=T_OC)
        bind.process_meli_stock_moves_update()
        stamp, status = self._leer_binding(bind)
        self.assertEqual(stamp, nuevo, "el binding tiene que tomar el sello NUEVO del producto")
        self.assertEqual(status, 'update', "con sello > ultimo push el binding va a la cola")

    def test_camino_direct_de_la_validacion_marca_el_binding(self):
        """Camino real del DIRECT de _update_meli_bindings (<50 productos):
        product.process_meli_stock_moves_update() con un movimiento nuevo del producto."""
        prod, bind = self._escenario()
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        sup = self.env.ref('stock.stock_location_suppliers')
        vals = {
            'product_id': prod.id, 'product_uom_qty': 6.0, 'product_uom': prod.uom_id.id,
            'location_id': sup.id, 'location_dest_id': wh.lot_stock_id.id,
        }
        if 'name' in self.env['stock.move']._fields:
            vals['name'] = 'TEST K30'
        self.env['stock.move'].with_context(meli_skip_stock_update=True).create(vals)
        prod.process_meli_stock_moves_update()
        stamp, status = self._leer_binding(bind)
        self.assertGreater(stamp, T_PUSH, "el sello del binding tiene que avanzar al movimiento nuevo")
        self.assertEqual(status, 'update', "la recepcion tiene que dejar el binding en la cola del cron")
