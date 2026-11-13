# -*- coding: utf-8 -*-
"""26.394 (un caso): «ML(stock): Almacen; asignando: …» UNA vez por venta y almacén.

El patrón MeliRollback (orders_update_order) revierte el write del almacén y la siguiente
sincronización lo vuelve a asignar. La guarda anterior miraba sólo los ÚLTIMOS 20 mensajes del
chatter ⇒ en cuanto la venta acumulaba otros avisos, el de almacén volvía a salir en cada pasada.

Control: en la rama de versión SIN el fix, test_rollback_con_chatter_largo FALLA (2 avisos).

    odoo-bin -d <db> -i meli_oerp_stock --test-enable --test-tags meli_26394 --stop-after-init
"""
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

PREFIX = "ML(stock): Almacen; asignando: "


@tagged('post_install', '-at_install', 'meli_oerp_stock', 'meli_26394')
class TestAvisoAlmacen26394(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.mercadolibre_notification_mode = 'internal_note'
        cls.wh1 = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.wh2 = cls.env['stock.warehouse'].create({'name': 'ML 26394', 'code': 'M394',
                                                     'company_id': cls.company.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente 26394'})

    def _venta(self):
        return self.env['sale.order'].create({'partner_id': self.partner.id, 'warehouse_id': self.wh1.id})

    def _sync(self, so):
        """Una pasada de _meli_order_update: ML dice almacén wh2."""
        MO = type(self.env['mercadolibre.orders'])
        with patch.object(type(so), '_meli_get_warehouse_id', lambda self, config=None: self.env['stock.warehouse'].browse(
                              self.env.context.get('t26394_wh')), create=True), \
             patch.object(MO, 'get_sale_order_type', lambda self, **kw: {}, create=True):
            so.with_context(t26394_wh=self.wh2.id)._meli_order_update(config=self.company)

    def _count(self, so):
        return self.env['mail.message'].search_count([
            ('model', '=', so._name), ('res_id', '=', so.id), ('body', 'like', PREFIX + self.wh2.name)])

    def test_rollback_con_chatter_largo(self):
        so = self._venta()
        self._sync(so)
        self.assertEqual(so.warehouse_id, self.wh2)
        self.assertEqual(self._count(so), 1)
        # MeliRollback: el almacén vuelve al anterior; mientras tanto el chatter crece.
        so.warehouse_id = self.wh1
        for i in range(25):
            so.message_post(body="otro aviso %s" % i)
        self._sync(so)
        self.assertEqual(so.warehouse_id, self.wh2, "la asignación se mantiene")
        self.assertEqual(self._count(so), 1, "dos sincronizaciones => UN solo aviso de almacén")

    def test_modo_none(self):
        self.company.mercadolibre_notification_mode = 'none'
        so = self._venta()
        self._sync(so)
        self.assertEqual(so.warehouse_id, self.wh2)
        self.assertEqual(self._count(so), 0, "modo 'none': sólo log")

    def test_venta_vieja_sin_marca(self):
        so = self._venta()
        so.message_post(body=PREFIX + self.wh2.name)  # como quedaba antes de 26.394
        for i in range(25):
            so.message_post(body="otro aviso %s" % i)
        self._sync(so)
        self.assertEqual(self._count(so), 1, "guarda de legado: no reabre la ronda en ventas viejas")

    def test_modo_important_rutina_al_log(self):
        if 'important' not in dict(self.company._fields['mercadolibre_notification_mode'].selection):
            self.skipTest("meli_oerp sin el modo 'important' (< 26.394)")
        self.company.mercadolibre_notification_mode = 'important'
        so = self._venta()
        self._sync(so)
        self.assertEqual(so.warehouse_id, self.wh2)
        self.assertEqual(self._count(so), 0, "modo important: el aviso de almacén es rutina => sólo log")
