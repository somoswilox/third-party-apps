# -*- coding: utf-8 -*-
"""26.329 — dos fixes de flota en meli_oerp_multiple, sin red:
(a) 0e6051e (caso-K32, FCA "tiene que entrar", bus 2026-09-25T10:56:17Z): el publish/copy_from_rjson estampa
    meli_last_status desde el json del item; sin eso meli_status cae a "unknown" y la ficha no muestra ML.
(b) seguridad (bus 2026-09-25T14:30:56Z): stock_error del binding no persiste el access_token.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.connection_binding import meli_status_from_rjson

TOKEN = 'APP_USR-1234567890123456-102811-0123456789abcdef0123456789abcdef-123912281'


@tagged('post_install', '-at_install', 'meli', 'meli_26329')
class TestMultiple26329(TransactionCase):

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

    def _bind(self):
        cuenta = self.env['mercadolibre.account'].search([], limit=1)
        if not cuenta:
            try:
                cuenta = self._crear_minimo('mercadolibre.account')
            except Exception as e:
                self.skipTest("sin mercadolibre.account en esta base: %s" % e)
        prod = self.env['product.product'].create({'name': 'TEST 26329', 'default_code': 'TEST-26329'})
        return self.env['mercadolibre.product'].create({
            'name': 'TEST 26329', 'product_id': prod.id, 'connection_account': cuenta.id,
            'conn_id': 'MLA27422631', 'meli_id': 'MLA27422631'})

    def test_status_from_rjson(self):
        self.assertEqual(meli_status_from_rjson({'id': 'MLA1', 'status': 'Active '}), 'active')
        self.assertEqual(meli_status_from_rjson({'status': 'paused'}), 'paused')
        self.assertIsNone(meli_status_from_rjson({'status': 'payment_required'}), "fuera del Selection: no se escribe")
        self.assertIsNone(meli_status_from_rjson({'error': 'x'}))
        self.assertIsNone(meli_status_from_rjson(None))
        self.assertIsNone(meli_status_from_rjson('active'))

    def test_estampa_last_status(self):
        bind = self._bind()
        self.assertFalse(bind.meli_last_status)
        self.assertEqual(bind.meli_stamp_last_status({'id': 'MLA27422631', 'status': 'active'}), 'active')
        self.assertEqual(bind.meli_last_status, 'active')
        bind.meli_stamp_last_status({'id': 'MLA27422631', 'status': 'paused'})
        self.assertEqual(bind.meli_last_status, 'paused')
        # un json sin estado usable NO borra el que habia
        self.assertIsNone(bind.meli_stamp_last_status({'id': 'MLA27422631', 'status': 'payment_required'}))
        self.assertEqual(bind.meli_last_status, 'paused')

    def test_stock_error_binding_sin_token(self):
        bind = self._bind()
        res = {'error': 'field_not_updatable', 'code': 'field_not_updatable', 'access_token': TOKEN}
        bind.stock_error = str(res)
        self.assertNotIn(TOKEN, bind.stock_error)
        self.assertIn('field_not_updatable', bind.stock_error)
