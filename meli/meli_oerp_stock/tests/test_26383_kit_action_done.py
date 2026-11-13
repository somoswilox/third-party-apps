# -*- coding: utf-8 -*-
"""26.383 — caso-K10 cliente G (#caso-K65): validar una entrega con un producto KIT.

mrp explota en _action_done los moves de kit que llegaron sin explotar (la LdM kit se creo o se
asigno DESPUES de confirmar el picking) y BORRA el move original. Los hooks de meli que corren
despues del super() (meli_oerp_stock, meli_oerp_multiple, meli_oerp) iteraban `self` y leian el
move borrado => MissingError "El registro no existe o fue eliminado. (Registro: stock.move(N,))"
y la validacion entera se revertia.

Casos: kit solo, kit + producto normal en el mismo picking, y lote de dos pickings validados
juntos (uno con kit, otro normal). Control: un picking solo con producto normal.

    odoo-bin -d <db> -u meli_oerp_stock --test-enable --test-tags meli_26383 --stop-after-init
"""
import unittest

from odoo import release
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'meli_oerp_stock', 'meli_26383')
class TestKitActionDone26383(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        if 'mrp.bom' not in env:
            raise unittest.SkipTest('mrp no instalado')
        if release.version_info[0] < 18:
            # mrp < 18 no explota kits en _action_done: el camino del bug no existe
            raise unittest.SkipTest('mrp < 18')
        cls.company = env.company
        cls.warehouse = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.customer_loc = env.ref('stock.stock_location_customers')
        cls.out_type = cls.warehouse.out_type_id
        cls.comp_a = cls._storable('KITK65-CA', 50.0)
        cls.comp_b = cls._storable('KITK65-CB', 50.0)
        cls.normal = cls._storable('KITK65-N', 50.0)
        cls.kit = cls._product('KITK65-K', storable=False)

    @classmethod
    def _product(cls, sku, storable=True):
        Product = cls.env['product.product']
        vals = {'name': 'KitK65 %s' % sku, 'default_code': sku, 'type': 'consu'}
        if storable and 'is_storable' in Product._fields:
            vals['is_storable'] = True
        elif storable:
            vals['type'] = 'product'
        return Product.create(vals)

    @classmethod
    def _storable(cls, sku, qty):
        p = cls._product(sku)
        cls.env['stock.quant']._update_available_quantity(p, cls.stock_loc, qty)
        return p

    def _kit_bom(self):
        # la LdM kit aparece DESPUES de confirmar: el move del kit queda sin explotar y mrp lo
        # explota (y lo borra) dentro de _action_done — el camino de MELI/PICK/00027
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.kit.product_tmpl_id.id,
            'product_qty': 1.0,
            'type': 'phantom',
            'bom_line_ids': [
                (0, 0, {'product_id': self.comp_a.id, 'product_qty': 2.0}),
                (0, 0, {'product_id': self.comp_b.id, 'product_qty': 1.0}),
            ],
        })
        self.env.invalidate_all()   # is_kits es compute NO almacenado: que lo recalcule
        return bom

    def _picking(self, lines):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id,
            'location_id': self.stock_loc.id,
            'location_dest_id': self.customer_loc.id,
            'move_ids': [(0, 0, {
                **({'name': p.display_name} if 'name' in self.env['stock.move']._fields else {}),
                'product_id': p.id,
                'product_uom_qty': q,
                'product_uom': p.uom_id.id,
                'location_id': self.stock_loc.id,
                'location_dest_id': self.customer_loc.id,
            }) for p, q in lines],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _validar(self, pickings):
        for picking in pickings:
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
        res = pickings.with_context(skip_backorder=True, skip_sms=True).button_validate()
        if isinstance(res, dict) and res.get('res_model'):
            wiz = self.env[res['res_model']].with_context(res.get('context', {}))
            if res.get('res_id'):
                wiz = wiz.browse(res['res_id'])
            else:
                wiz = wiz.create({})
            for meth in ('process', 'action_confirm', 'process_cancel_backorder'):
                if hasattr(wiz, meth):
                    getattr(wiz, meth)()
                    break
        return pickings

    def _validar_hasta_done(self, pickings, intentos=2):
        """Valida como el usuario: si tras explotar el kit quedan componentes pendientes, re-valida."""
        n = 0
        while n < intentos and pickings.filtered(lambda p: p.state != 'done'):
            n += 1
            self._validar(pickings.filtered(lambda p: p.state != 'done'))
        return n

    def _assert_kit_explotado(self, picking, kit_move):
        """El move del kit desaparece y quedan sus componentes. Comportamiento estandar de Odoo: los
        componentes nacen con cantidad 0; si en el picking se hizo otra linea, pasan a la entrega
        pendiente (backorder); si no, quedan pendientes en el mismo picking."""
        self.assertFalse(kit_move.exists(), 'mrp tenia que reemplazar el move del kit')
        todos = picking | picking.backorder_ids
        self.assertFalse(todos.move_ids.filtered(lambda m: m.product_id == self.kit))
        self.assertTrue(todos.move_ids.filtered(lambda m: m.product_id == self.comp_a))
        return todos

    def test_01_kit_solo(self):
        picking = self._picking([(self.kit, 1.0)])
        kit_move = picking.move_ids
        self._kit_bom()
        self._validar(picking)            # en el control: MissingError stock.move(kit)
        self._assert_kit_explotado(picking, kit_move)
        self._validar_hasta_done(picking)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(sum(picking.move_ids.filtered(lambda m: m.product_id == self.comp_a).mapped('quantity')), 2.0)
        self.assertEqual(self.comp_a.qty_available, 48.0)

    def test_02_kit_y_normal(self):
        picking = self._picking([(self.kit, 2.0), (self.normal, 3.0)])
        kit_move = picking.move_ids.filtered(lambda m: m.product_id == self.kit)
        self._kit_bom()
        self._validar(picking)
        todos = self._assert_kit_explotado(picking, kit_move)
        self._validar_hasta_done(todos)
        self.assertEqual(set(todos.mapped('state')), {'done'})
        n = picking.move_ids.filtered(lambda m: m.product_id == self.normal)
        self.assertEqual((n.state, n.quantity), ('done', 3.0))
        self.assertEqual(self.normal.qty_available, 47.0)
        self.assertEqual(self.comp_a.qty_available, 46.0)

    def test_03_lote_kit_y_normal(self):
        p_kit = self._picking([(self.kit, 1.0), (self.normal, 1.0)])
        kit_move = p_kit.move_ids.filtered(lambda m: m.product_id == self.kit)
        p_norm = self._picking([(self.normal, 2.0)])
        self._kit_bom()
        self._validar(p_kit | p_norm)     # validacion en lote
        todos = self._assert_kit_explotado(p_kit, kit_move)
        self.assertEqual(p_norm.state, 'done')
        self._validar_hasta_done(todos | p_norm)
        self.assertEqual(set((todos | p_norm).mapped('state')), {'done'})
        self.assertEqual(self.comp_a.qty_available, 48.0)
        self.assertEqual(self.normal.qty_available, 47.0)

    def test_04_kit_ya_explotado_al_confirmar(self):
        # el camino normal: la LdM existe ANTES de confirmar => mrp explota en _action_confirm
        self._kit_bom()
        picking = self._picking([(self.kit, 1.0), (self.normal, 1.0)])
        self._validar(picking)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self.comp_a.qty_available, 48.0)

    def test_05_control_normal(self):
        picking = self._picking([(self.normal, 1.0)])
        moves = picking.move_ids
        self._validar(picking)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.move_ids, moves)
        self.assertEqual(self.normal.qty_available, 49.0)
