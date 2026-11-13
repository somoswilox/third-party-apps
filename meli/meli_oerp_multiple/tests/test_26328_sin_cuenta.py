# -*- coding: utf-8 -*-
"""26.328 (PLAN-2026-10-28-meli-warnings): warnings de log sin cuenta ML conectada.
- `Need login for False`: el compute `_meli_brand` del form de una cuenta NUEVA (sin token) instanciaba ML.
- `default_get error loading cron profile`: el wizard de importacion masiva abierto desde la COMPANIA
  (active_model=res.company) leia los active_ids como ids de mercadolibre.account.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli', 'meli_26328')
class TestSinCuenta26328(TransactionCase):

    def _patch_instance(self):
        called = []
        util = self.env['meli.util']
        orig = type(util).get_new_instance

        class _M:
            access_token = 'T'

            def get(self, *a, **k):
                class R:
                    def json(self):
                        return {}
                return R()

        type(util).get_new_instance = lambda self, *a, **k: (called.append(1), _M())[1]
        self.addCleanup(setattr, type(util), 'get_new_instance', orig)
        return called

    def test_brands_cuenta_sin_token_no_instancia_ml(self):
        called = self._patch_instance()
        self.env['mercadolibre.account'].new({'name': False})._mercadolibre_brands()
        self.assertEqual(called, [])

    def test_brands_cuenta_con_token_sigue_igual(self):
        called = self._patch_instance()
        self.env['mercadolibre.account'].new(
            {'name': 'x', 'seller_id': '123', 'access_token': 'APP_USR-1-123'})._mercadolibre_brands()
        self.assertEqual(called, [1])

    def test_get_account_respeta_active_model(self):
        W = self.env['mercadolibre.product.template.import']
        Account = self.env['mercadolibre.account']
        company = self.env.company
        # ids de compania NO se leen como ids de cuenta
        self.assertFalse(W.with_context(active_model='product.template', active_ids=[1])._get_account())
        conns = company.mercadolibre_connections
        expected = conns if len(conns) == 1 else Account
        self.assertEqual(W.with_context(active_model='res.company', active_ids=company.ids)._get_account(), expected)
        res = W.with_context(active_model='res.company', active_ids=company.ids).default_get(['cron_batch_size'])
        self.assertIsInstance(res, dict)
        # cuenta / llamada vieja sin active_model: igual que antes
        fake_ids = [999999]
        self.assertEqual(W.with_context(active_model='mercadolibre.account', active_ids=fake_ids)._get_account().ids, fake_ids)
        self.assertEqual(W.with_context(active_ids=fake_ids)._get_account().ids, fake_ids)
