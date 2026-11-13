# -*- coding: utf-8 -*-
"""caso-K15 cliente E (26-oct-2026): la factura borrador 12906 de SO 13974 (compania 3, fulfillment) nacio en la
compania 1 porque la configuracion de la cuenta DELTA tenia `mercadolibre_invoice_journal_id_full` = diario 9
de la compania 1. `account.move` recalcula `company_id` desde el diario y el post fallaba con
"accounts from a different company". Un diario de otra compania ya no se usa: queda el de la venta.

Correr:  odoo-bin ... -u meli_oerp_accounting --test-enable --test-tags meli_K15_diario_compania --stop-after-init
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_K15_diario_compania')
class TestDiarioOtraCompaniaK15(TransactionCase):

    def setUp(self):
        super().setUp()
        self.co_a = self.env.company
        self.co_b = self.env['res.company'].create({'name': 'Compania B (K15)'})
        self.j_a = self.env['account.journal'].create({
            'name': 'Ventas A K15', 'code': 'VK15A', 'type': 'sale', 'company_id': self.co_a.id})
        self.j_b = self.env['account.journal'].with_company(self.co_b).create({
            'name': 'Ventas B K15', 'code': 'VK15B', 'type': 'sale', 'company_id': self.co_b.id})
        partner = self.env['res.partner'].create({'name': 'Comprador K15', 'company_id': False})
        self.so_b = self.env['sale.order'].with_company(self.co_b).create({
            'partner_id': partner.id, 'company_id': self.co_b.id})

    def test_diario_de_otra_compania_se_descarta(self):
        # el WARNING del descarte es el log esperado del escenario: se verifica y no ensucia el log del build
        with self.assertLogs('odoo.addons.meli_oerp_accounting.models.order', level='WARNING') as logs:
            self.assertFalse(self.so_b._meli_invoice_journal_same_company(self.j_a))
        self.assertTrue(any('se ignora' in m for m in logs.output), logs.output)

    def test_diario_de_la_misma_compania_se_respeta(self):
        self.assertEqual(self.so_b._meli_invoice_journal_same_company(self.j_b), self.j_b)

    def test_sin_diario(self):
        self.assertFalse(self.so_b._meli_invoice_journal_same_company(False))

    def test_diario_de_la_compania_madre_se_respeta(self):
        hija = self.env['res.company'].create({'name': 'Hija de A (K15)', 'parent_id': self.co_a.id})
        so_hija = self.env['sale.order'].with_company(hija).create({
            'partner_id': self.so_b.partner_id.id, 'company_id': hija.id})
        self.assertEqual(so_hija._meli_invoice_journal_same_company(self.j_a), self.j_a)
