# -*- coding: utf-8 -*-
"""26.329 — port al source del caso-K15 cliente E (26.173, bus 2026-10-01T14:36:12Z), sin red:
- _meli_post_stock_enabled: sin cuentas => True (mono-empresa, como siempre); con cuentas, True sólo
  si alguna tiene 'Publicar Stock'. Apagado => el hook de stock no calcula nada en la tx del usuario.
- search_meli_product: nunca None (meli_oerp_stock hacia len(None) y la orden no entraba).
- cron de notificaciones de orden: FAILED con attempts >= tope no se reintenta más.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli', 'meli_26329')
class TestK15HookStock(TransactionCase):

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

    def test_post_stock_enabled(self):
        Move = self.env['stock.move']
        Acc = self.env['mercadolibre.account'].sudo()
        cuentas = Acc.search([])
        if not cuentas:
            self.assertTrue(Move._meli_post_stock_enabled(), "sin cuentas multiple: comportamiento de siempre")
            try:
                cuentas = self._crear_minimo('mercadolibre.account')
            except Exception as e:
                self.skipTest("no se pudo crear una mercadolibre.account: %s" % e)
        cfgs = cuentas.mapped('configuration')
        cfgs.write({'mercadolibre_cron_post_update_stock': False})
        companies = cuentas.mapped('company_id')
        if 'mercadolibre_cron_post_update_stock' in companies._fields:
            companies.write({'mercadolibre_cron_post_update_stock': False})
        self.assertFalse(Move._meli_post_stock_enabled())
        cfgs[:1].mercadolibre_cron_post_update_stock = True
        self.assertTrue(Move._meli_post_stock_enabled())

    def test_search_meli_product_nunca_none(self):
        order = self.env['mercadolibre.orders']
        res = order.search_meli_product(meli_item=None)
        self.assertIsNotNone(res)
        self.assertEqual(len(res), 0)
