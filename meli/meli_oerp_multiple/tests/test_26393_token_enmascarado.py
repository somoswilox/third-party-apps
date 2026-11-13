# -*- coding: utf-8 -*-
"""26.393 (PLAN-2026-11-10-token-enmascarado-y-niveles-es):
El Token de Acceso de la cuenta ML (`access_token`, fields.Text heredado de odoo_connector_api) se veía EN CLARO en
la pestaña Configuración de la cuenta aunque la vista tuviera password="True": el widget de Text ignora `password`.
Cada pantalla compartida en soporte lo exponía. Ahora va con widget="char" (que sí respeta password).

Barrido: todo nodo <field> de un secreto (access_token / refresh_token / secret_key / client_secret, con o sin prefijo)
en las vistas de los módulos del suite debe llevar password, y si el campo es Text, widget="char".
"""
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged

SECRETO = re.compile(r'(^|_)(access_token|refresh_token|secret_key|client_secret)$')
MODULOS = ('odoo_connector_api', 'meli_oerp', 'meli_oerp_multiple', 'meli_oerp_stock', 'meli_oerp_accounting',
           'meli_oerp_autofacturacion', 'meli_oerp_campaign')
VERDADERO = ('1', 'true', 'True')


@tagged('post_install', '-at_install', 'meli_26393')
class TestTokenEnmascarado26393(TransactionCase):

    def _gfield(self):
        return 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'

    def _admin(self):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin token 26393', 'login': 'admin_token_26393',
            self._gfield(): [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('base.group_system').id,
                                     self.env.ref('meli_oerp_multiple.group_mercadolibre_connectors_manager').id])]})

    def _assert_nodo(self, model, node, donde):
        fname = node.get('name')
        field = self.env[model]._fields.get(fname)
        if field is None:
            return  # nodo de un sub-modelo (one2many embebido): no es de este modelo
        if (node.get('invisible') or '').strip() in VERDADERO or node.get('column_invisible') in VERDADERO:
            return
        self.assertIn(node.get('password'), VERDADERO, "%s: %s.%s se muestra sin password" % (donde, model, fname))
        if field.type == 'text':
            self.assertEqual(node.get('widget'), 'char',
                             "%s: %s.%s es Text y el widget de Text IGNORA password => token en claro"
                             % (donde, model, fname))

    def test_01_cuenta_ml_token_enmascarado_get_view(self):
        """La vista combinada que recibe el navegador del admin (pestaña Configuración de la cuenta)."""
        self.assertEqual(self.env['mercadolibre.account']._fields['access_token'].type, 'text',
                         "si el campo dejó de ser Text, revisar este test")
        view = self.env.ref('meli_oerp_multiple.view_connection_account_mercadolibre')
        arch = self.env['mercadolibre.account'].with_user(self._admin()).get_view(
            view_id=view.id, view_type='form')['arch']
        nodes = etree.fromstring(arch).xpath("//field[@name='access_token']")
        self.assertTrue(nodes, "el admin no ve el campo access_token (¿cambió la vista?)")
        for n in nodes:
            self._assert_nodo('mercadolibre.account', n, 'get_view cuenta ML')

    def test_02_barrido_vistas_del_suite(self):
        """Toda vista (raw, sin filtrar grupos) de los módulos del suite que muestre un secreto lo enmascara."""
        imd = self.env['ir.model.data'].search([('model', '=', 'ir.ui.view'), ('module', 'in', MODULOS)])
        views = self.env['ir.ui.view'].browse(imd.mapped('res_id')).exists()
        vistos = 0
        for v in views:
            if not v.model or v.model not in self.env or not v.arch_db:
                continue
            try:
                root = etree.fromstring(v.arch_db.encode())
            except Exception:
                continue
            for n in root.iter('field'):
                if n.get('name') and SECRETO.search(n.get('name')):
                    vistos += 1
                    self._assert_nodo(v.model, n, v.xml_id or v.name)
        self.assertTrue(vistos, "el barrido no encontró ningún campo secreto (¿cambió el patrón?)")

    def _nombre_en(self, lang, xmlid):
        self.env['res.lang']._activate_lang(lang)
        self.env['ir.module.module']._load_module_terms(['meli_oerp', 'meli_oerp_multiple'], [lang], overwrite=True)
        return self.env.ref(xmlid).with_context(lang=lang).name

    def test_03_niveles_ml_en_castellano(self):
        """Selector «Mercado Libre» del usuario: los 3 niveles en castellano (es_AR por su .po, es_MX por es.po)."""
        esperado = {'meli_oerp.group_mercadolibre_reader': 'Lector de MercadoLibre',
                    'meli_oerp.group_mercadolibre_manager': 'Encargado de MercadoLibre',
                    'meli_oerp_multiple.group_mercadolibre_connectors_manager': 'Administrador de MercadoLibre'}
        for lang in ('es_AR', 'es_MX'):
            for xmlid, nombre in esperado.items():
                self.assertEqual(self._nombre_en(lang, xmlid), nombre, "%s en %s" % (xmlid, lang))
