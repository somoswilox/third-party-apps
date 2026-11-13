# -*- coding: utf-8 -*-
"""26.329 (caso-K11 cliente L, bus 2026-09-24T18:15:24Z): product_meli_get_products(context={meli_id: X})
NO procesaba X. list_meli_ids(filter_ids=[X]) devuelve las vinculadas MENOS X y reemplazaba la lista:
recorria las 429 vinculadas y X nunca. Sin red: ML simulado; se mide QUE ids se piden a ML."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


class _Meli:
    access_token = 'TEST'

    def need_login(self):
        return False


@tagged('post_install', '-at_install', 'meli', 'meli_26329')
class TestGetProductsMeliId(TransactionCase):

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

    def test_importa_solo_el_meli_id_pedido(self):
        cuenta = self.env['mercadolibre.account'].search([], limit=1)
        if not cuenta:
            try:
                cuenta = self._crear_minimo('mercadolibre.account')
            except Exception as e:
                self.skipTest("sin mercadolibre.account: %s" % e)
        # 3 publicaciones YA vinculadas en la cuenta (las que se recorrian por error)
        for i in range(3):
            tmpl = self.env['product.template'].create({'name': 'Vinculada %s' % i})
            self.env['mercadolibre.product_template'].create({
                'name': 'Vinculada %s' % i, 'product_tmpl_id': tmpl.id,
                'connection_account': cuenta.id, 'conn_id': 'MLA9990000%s' % i})
        pedidos = []
        Acc = type(cuenta)

        def _multiget(self, ids=None, meli=None):
            pedidos.extend(ids or [])
            return {}

        def _one(self, meli_id=None, meli=None):
            pedidos.append(meli_id)
            return {}
        with patch.object(type(self.env['meli.util']), 'get_new_instance', lambda *a, **k: _Meli()), \
                patch.object(Acc, 'fetch_list_meli_ids_maestro', lambda self, params=None: []), \
                patch.object(Acc, 'fetch_meli_products_multiget', _multiget), \
                patch.object(Acc, 'fetch_meli_product', _one):
            cuenta.product_meli_get_products(context={'meli_id': 'MLA14779960'})
        self.assertIn('MLA14779960', pedidos, "el meli_id pedido se tiene que consultar a ML")
        self.assertFalse([p for p in pedidos if p.startswith('MLA9990000')],
                         "no se recorren las otras vinculadas: %s" % pedidos)
