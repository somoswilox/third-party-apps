# -*- coding: utf-8 -*-
"""26.304 (video demo 20, 25-oct-2026): abrir una Venta daba "Error de acceso" sobre
ocapi.binding.sale_order a todo usuario sin "Odoo Connectors Api Manager" (aunque fuera
MercadoLibre Manager). El formulario pide sale.order.ocapi_bindings (pagina invisible) con
`order`, y web_read hace search() sobre el comodelo => AccessError aunque el M2M este vacio.
Fix: groups= en el campo (como mercadolibre_bindings). El test abre el formulario COMPLETO como
el cliente web: get_views + web_read con fields/order/limit para cada x2many del arch.
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    etree = None


@tagged('post_install', '-at_install', 'meli_26304')
class TestSaleFormAcl26304(TransactionCase):

    def setUp(self):
        super().setUp()
        gfield = 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'
        groups = [self.env.ref('base.group_user').id,
                  self.env.ref('sales_team.group_sale_salesman_all_leads').id,
                  self.env.ref('meli_oerp_multiple.group_mercadolibre_connectors_manager').id]
        self.user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Ventas + ML Manager 26304', 'login': 'ventas_ml_26304', gfield: [(6, 0, groups)]})
        self.assertFalse(self.user.has_group('odoo_connector_api.group_ocapi_connectors_manager'),
                         "el usuario de prueba no debe tener el grupo ocapi")
        partner = self.env['res.partner'].create({'name': 'Cliente 26304'})
        self.order = self.env['sale.order'].create({'partner_id': partner.id})

    def _spec_del_formulario(self, SO):
        views = SO.get_views([(False, 'form')])
        arch = views['views']['form']['arch']
        node = etree.fromstring(arch.encode() if isinstance(arch, str) else arch)
        top = [n.get('name') for n in node.iter('field')
               if not any(a.tag == 'field' for a in n.iterancestors())]
        spec = {}
        for f in dict.fromkeys(top):
            if f not in SO._fields:
                continue
            fd = SO._fields[f]
            if fd.type in ('one2many', 'many2many'):
                co = self.env[fd.comodel_name]
                # 17/18: el core trae x2many propios (p.ej. sale.order.transaction_ids) que este usuario
                # tampoco lee, y el cliente no los pide con `order`. El test mide NUESTROS campos.
                if not (fd._module or '').startswith(('meli_oerp', 'odoo_connector_api')) and \
                        not SO.env[fd.comodel_name].check_access_rights('read', raise_exception=False):
                    continue
                spec[f] = {'fields': {'display_name': {}}, 'limit': 40, 'order': co._order or 'id'}
            elif fd.type == 'many2one':
                spec[f] = {'fields': {'display_name': {}}}
            else:
                spec[f] = {}
        return spec

    def test_ventas_ml_manager_abre_venta(self):
        SO = self.env['sale.order'].with_user(self.user)
        spec = self._spec_del_formulario(SO)
        self.assertNotIn('ocapi_bindings', spec, "ocapi_bindings no debe llegar al formulario sin el grupo ocapi")
        self.env.invalidate_all()
        SO.browse(self.order.id).web_read(spec)

    def test_control_sin_groups_falla(self):
        # Control: pedir el campo como lo pedia el formulario antes del fix da AccessError.
        SO = self.env['sale.order'].with_user(self.user)
        co = self.env['ocapi.binding.sale_order']
        with self.assertRaises(AccessError):
            SO.browse(self.order.id).web_read(
                {'ocapi_bindings': {'fields': {'display_name': {}}, 'limit': 40, 'order': co._order or 'id'}})
