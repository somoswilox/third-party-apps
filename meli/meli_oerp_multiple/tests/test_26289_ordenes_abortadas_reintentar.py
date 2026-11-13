# -*- coding: utf-8 -*-
"""#caso-K10 cliente G (22-oct-2026): una orden ML que falla a mitad del lote del cron de
ordenes (CRON_UNPROCESSED_ORDERS) no volvia a entrar nunca.

Medido en Test: el build se apago por ocio a mitad de lote (`cursor already closed`), 4
ordenes quedaron sin sale_order ni mercadolibre.orders, y las corridas siguientes trajeron
siempre las 10 MAS NUEVAS (sort=date_desc + limit 10, ~760 ventas/24 h): las 4 quedaban
detras de cada tanda nueva hasta salir de la ventana de 24 h.

Promesa que se prueba (26.289):
  1. una orden que tira excepcion en la corrida N vuelve a intentarse en la corrida N+1,
     aunque hayan entrado mas ventas nuevas que el limite;
  2. lo que esa orden dejo a medias se descarta (no queda como "ya existia" al commitear
     la siguiente) y las demas ordenes del lote siguen entrando;
  3. si el cursor murio, el lote se corta en esa orden (no se intentan las demas contra un
     cursor cerrado) y el error se propaga.

Sin red: meli.util se reemplaza por un ML falso que respeta sort/offset/paging, y
orders_import_order por una version que crea el mercadolibre.orders. commit/rollback del
cursor se emulan con un SAVEPOINT (mismo comportamiento observable: lo commiteado queda, lo
no commiteado se pierde con el rollback).
"""
import re
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

LOGGER = 'odoo.addons.meli_oerp_multiple.models.connection_account'


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeMeli:
    """ML /orders/search: respeta sort=date_asc|date_desc, offset y paging.limit."""
    seller_id = '543000'
    access_token = 'TOKEN-TEST'
    needlogin_state = False

    def __init__(self, ids, page_limit=5):
        self.ids = list(ids)          # orden cronologico (date_closed ascendente)
        self.page_limit = page_limit
        self.queries = []

    def need_login(self):
        return False

    def get(self, path, params=None):
        self.queries.append(path)
        assert path.startswith('/orders/search'), path
        sort = re.search(r'sort=(date_asc|date_desc)', path).group(1)
        m = re.search(r'offset=(\d+)', path)
        offset = int(m.group(1)) if m else 0
        ordered = self.ids if sort == 'date_asc' else list(reversed(self.ids))
        page = ordered[offset:offset + self.page_limit]
        return _Resp({
            'paging': {'total': len(ordered), 'offset': offset, 'limit': self.page_limit},
            'results': [{'id': i} for i in page],
        })


class _CursorCerrado(Exception):
    pass


@tagged('post_install', '-at_install', 'meli_26289')
class TestOrdenesAbortadasReintentar(TransactionCase):

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

    def setUp(self):
        super().setUp()
        cuenta = self.env['mercadolibre.account'].search([], limit=1)
        if not cuenta:
            try:
                cuenta = self._crear_minimo('mercadolibre.account')
            except Exception as e:
                self.skipTest("No se pudo obtener una mercadolibre.account: %s" % e)
        self.cuenta = cuenta
        self.Orders = self.env['mercadolibre.orders']
        self.intentos = []          # [(corrida, order_id)]
        self.corrida = 0
        self.falla = {}             # order_id -> 'exc' | 'parcial' | 'cerrado'
        self.cerrado = False

        # commit/rollback reales estan prohibidos en tests: se emulan con un savepoint.
        cr = self.env.cr
        cr.execute('SAVEPOINT tK10')

        def _commit():
            self.env.flush_all()
            cr.execute('RELEASE SAVEPOINT tK10')
            cr.execute('SAVEPOINT tK10')

        def _rollback():
            cr.execute('ROLLBACK TO SAVEPOINT tK10')
            self.env.invalidate_all()

        p1 = patch.object(cr, 'commit', _commit)
        p2 = patch.object(cr, 'rollback', _rollback)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

        test = self

        def _import(self_orders, order_id=None, context=None, meli=None, config=None):
            test.intentos.append((test.corrida, order_id))
            modo = test.falla.pop(order_id, None)
            if modo in ('parcial', None):
                test.Orders.create({'order_id': str(order_id),
                                    'connection_account': test.cuenta.id})
            if modo == 'exc' or modo == 'parcial':
                raise RuntimeError('fallo importando %s (test)' % order_id)
            if modo == 'cerrado':
                test.cerrado = True
                raise _CursorCerrado('cursor already closed')
            return {'ret': True}

        p3 = patch.object(type(self.Orders), 'orders_import_order', _import)
        p3.start(); self.addCleanup(p3.stop)

        # cr.closed: el real o el simulado por la falla 'cerrado'
        CursorCls = type(cr)
        real_closed = CursorCls.closed
        p4 = patch.object(CursorCls, 'closed',
                          property(lambda c: test.cerrado or real_closed.fget(c)))
        p4.start(); self.addCleanup(p4.stop)

    def _correr(self, ml):
        self.corrida += 1
        with mute_logger(LOGGER):
            return self.cuenta.cron_process_unprocessed_orders(meli=ml, limit=10)

    def _existe(self, order_id):
        return self.Orders.search_count([('order_id', '=', str(order_id)),
                                         ('connection_account', '=', self.cuenta.id)])

    def _ids(self, desde, n):
        return [2000667369025217 + desde + i for i in range(n)]

    def test_excepcion_se_reintenta_en_la_corrida_siguiente(self):
        ml = _FakeMeli(self._ids(0, 25))
        # la 3ra orden que intente la corrida 1 tira excepcion
        orig = type(self.Orders).orders_import_order
        primeras = []

        def _marcar(self_orders, order_id=None, **kw):
            primeras.append(order_id)
            if len(primeras) == 3:
                self.falla[order_id] = 'exc'
            return orig(self_orders, order_id=order_id, **kw)

        with patch.object(type(self.Orders), 'orders_import_order', _marcar):
            r1 = self._correr(ml)
        fallida = primeras[2]
        self.assertEqual(r1.get('failed'), 1)
        self.assertEqual(r1.get('processed'), 9)
        self.assertFalse(self._existe(fallida))

        # entran 10 ventas nuevas (>= limit) antes de la corrida siguiente
        ml.ids += self._ids(100, 10)
        self._correr(ml)
        self.assertIn((2, fallida), self.intentos,
                      "la orden que fallo en la corrida 1 no se reintento en la 2")
        self.assertEqual(self._existe(fallida), 1)

    def test_orden_a_medias_no_queda_como_existente(self):
        ml = _FakeMeli(self._ids(0, 25))
        orig = type(self.Orders).orders_import_order
        primeras = []

        def _marcar(self_orders, order_id=None, **kw):
            primeras.append(order_id)
            if len(primeras) == 3:
                self.falla[order_id] = 'parcial'
            return orig(self_orders, order_id=order_id, **kw)

        with patch.object(type(self.Orders), 'orders_import_order', _marcar):
            r1 = self._correr(ml)
        fallida = primeras[2]
        # las demas del lote entraron (no hubo cascada) y la fallida NO quedo creada a medias
        self.assertEqual(r1.get('processed'), 9)
        self.assertEqual(self._existe(fallida), 0,
                         "el mercadolibre.orders a medias se commiteo con la orden siguiente")
        self._correr(ml)
        self.assertIn((2, fallida), self.intentos)
        self.assertEqual(self._existe(fallida), 1)

    def test_cursor_cerrado_corta_el_lote(self):
        ml = _FakeMeli(self._ids(0, 25))
        orig = type(self.Orders).orders_import_order
        primeras = []

        def _marcar(self_orders, order_id=None, **kw):
            primeras.append(order_id)
            if len(primeras) == 3:
                self.falla[order_id] = 'cerrado'
            return orig(self_orders, order_id=order_id, **kw)

        # sin self.assertRaises: el de Odoo abre un savepoint propio y el commit emulado
        # (RELEASE del savepoint del test) lo liberaria.
        propagado = None
        with patch.object(type(self.Orders), 'orders_import_order', _marcar):
            try:
                self._correr(ml)
            except _CursorCerrado as e:
                propagado = e
        self.assertIsNotNone(propagado, "el cursor cerrado no se propago: la corrida siguio como si nada")
        self.assertEqual(len(primeras), 3,
                         "siguio intentando ordenes contra un cursor cerrado: %s" % primeras)
        self.cerrado = False
        # la corrida siguiente arranca por la que se corto
        self._correr(ml)
        self.assertEqual([oid for c, oid in self.intentos if c == 2][0], primeras[2])
