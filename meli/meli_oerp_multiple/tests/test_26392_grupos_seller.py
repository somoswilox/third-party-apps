# -*- coding: utf-8 -*-
"""26.392 (PLAN-2026-11-10-meli-grupos-categoria-tax-included, pedidos MINT e-learning):
1. «MercadoLibre Manager» (multiple) es el nivel Administrador del selector «Mercado Libre» de meli_oerp
   (Lector < Encargado < Administrador), asignable sin modo desarrollador; NO implica el grupo OCAPI.
   «Odoo Connectors Api Manager» tiene categoría/privilegio propio (también sin modo desarrollador).
2. «Tax Included» de la configuración de la cuenta visible para un admin sin modo desarrollador.
3. El login de multiple completa el Seller id de la cuenta si está vacío (nunca lo pisa).
"""
from odoo.tests import TransactionCase, tagged


class _Meli:
    def __init__(self, token='APP_USR-1234-111026-abc-555001'):
        self.access_token = token


@tagged('post_install', '-at_install', 'meli_26392')
class TestGruposSeller26392(TransactionCase):

    def setUp(self):
        super().setUp()
        self.reader = self.env.ref('meli_oerp.group_mercadolibre_reader')
        self.manager = self.env.ref('meli_oerp.group_mercadolibre_manager')
        self.admin_ml = self.env.ref('meli_oerp_multiple.group_mercadolibre_connectors_manager')
        self.ocapi = self.env.ref('odoo_connector_api.group_ocapi_connectors_manager')
        self.privileges = 'privilege_id' in self.env['res.groups']._fields

    def _implied(self, g):
        return g.trans_implied_ids if 'trans_implied_ids' in g._fields else g.all_implied_ids

    def test_01_admin_ml_es_el_tercer_nivel(self):
        self.assertIn(self.manager, self._implied(self.admin_ml))
        self.assertIn(self.reader, self._implied(self.admin_ml))
        self.assertNotIn(self.ocapi, self._implied(self.admin_ml), "no debe implicar el grupo OCAPI (26.304)")
        if self.privileges:
            self.assertEqual(self.admin_ml.privilege_id, self.manager.privilege_id)
            self.assertTrue(self.admin_ml.privilege_id)
            self.assertTrue(self.ocapi.privilege_id, "Odoo Connectors Api Manager sin privilegio => sólo modo dev")
            self.assertNotEqual(self.ocapi.privilege_id, self.admin_ml.privilege_id)
            hier = self.env['res.groups']._get_view_group_hierarchy()
            ids = hier['privileges'][self.admin_ml.privilege_id.id]['group_ids']
            self.assertEqual([i for i in ids if i in (self.reader.id, self.manager.id, self.admin_ml.id)],
                             [self.reader.id, self.manager.id, self.admin_ml.id])
            return
        self.assertEqual(self.admin_ml.category_id, self.manager.category_id)
        self.assertTrue(self.admin_ml.category_id)
        by = {}
        for app, kind, gs, _cat in self.env['res.groups'].get_groups_by_application():
            for g in gs:
                by[g] = (kind, list(gs))
        kind, gs = by[self.admin_ml]
        self.assertEqual(kind, 'selection', "el selector Mercado Libre se rompió (casillas = sólo modo dev)")
        self.assertEqual([g for g in gs if g in (self.reader, self.manager, self.admin_ml)],
                         [self.reader, self.manager, self.admin_ml])
        self.assertEqual(by[self.ocapi][0], 'selection', "OCAPI sólo asignable en modo dev")
        self.assertEqual(by[self.env.ref('sales_team.group_sale_salesman')][0], 'selection',
                         "Ventas dejó de ser selector")

    def _assert_raw_group_system(self, model):
        """El nodo del campo en la vista del módulo: group_system, no group_no_one (en 19+ los tests
        corren con group_no_one activo y get_view no discrimina)."""
        from lxml import etree
        views = self.env['ir.ui.view'].search([('model', '=', model), ('arch_db', 'ilike', 'mercadolibre_tax_included')])
        nodes = []
        for v in views:
            nodes += etree.fromstring(v.arch_db.encode()).xpath("//field[@name='mercadolibre_tax_included']")
        self.assertTrue(nodes, "no se encontró el campo en ninguna vista de %s" % model)
        for n in nodes:
            self.assertNotIn('group_no_one', n.get('groups') or '', "Tax Included sigue en modo desarrollador")

    def test_02_tax_included_visible_admin_sin_modo_dev(self):
        self._assert_raw_group_system('mercadolibre.configuration')
        gfield = 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'
        admin = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin ML 26392', 'login': 'admin_ml_26392',
            gfield: [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('base.group_system').id, self.admin_ml.id])]})
        view = self.env.ref('meli_oerp_multiple.view_connection_configuration_mercadolibre')
        arch = self.env['mercadolibre.configuration'].with_user(admin).get_view(view_id=view.id, view_type='form')['arch']
        self.assertIn('name="mercadolibre_pricelist"', arch)
        self.assertIn('name="mercadolibre_tax_included"', arch, "Tax Included oculto sin modo desarrollador")

    def _account(self, seller=False):
        env = self.env
        wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
        pl = env['product.pricelist'].search([], limit=1) or env['product.pricelist'].create({'name': 'S392'})
        config = env['mercadolibre.configuration'].create({
            'name': 'S392', 'mode': 'test', 'company_id': env.company.id, 'mercadolibre_pricelist': pl.id,
            'mercadolibre_buying_mode': 'buy_it_now', 'mercadolibre_currency': 'ARS',
            'mercadolibre_stock_warehouse': wh.id, 'mercadolibre_stock_warehouse_full': wh.id,
            'mercadolibre_listing_type': 'gold_special'})
        vals = {'name': 'Cuenta 26392', 'type': 'mercadolibre', 'company_id': env.company.id,
                'configuration': config.id, 'country_id': env.ref('base.ar').id,
                'meli_login_id': 'c26392', 'client_id': '1234', 'secret_key': 'x',
                'redirect_uri': 'https://example.com/meli_login/c26392'}
        if seller:
            vals['seller_id'] = seller
        return env['mercadolibre.account'].create(vals)

    def test_03_login_completa_seller_id_vacio(self):
        acc = self._account()
        self.assertFalse(acc.seller_id)
        acc._meli_fill_seller_id_from_login({'user_id': 987654, 'access_token': 'APP_USR-x'}, _Meli())
        self.assertEqual(acc.seller_id, '987654')

    def test_04_login_token_si_no_hay_user_id(self):
        acc = self._account()
        acc._meli_fill_seller_id_from_login({}, _Meli('APP_USR-1234-111026-abc-555001'))
        self.assertEqual(acc.seller_id, '555001')

    def test_05_login_no_pisa_seller_id(self):
        acc = self._account(seller='111')
        acc._meli_fill_seller_id_from_login({'user_id': 222}, _Meli())
        self.assertEqual(acc.seller_id, '111')
