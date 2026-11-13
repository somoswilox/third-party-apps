# -*- coding: utf-8 -*-
"""26.295 (#caso-K38, cuenta caso-K39): un usuario interno SIN grupos de conectores no podia abrir NINGUN
contacto. El formulario de Contacto carga en paginas invisibles dos Many2many de bindings:
res.partner.mercadolibre_bindings (mercadolibre.client, arreglado en 26.269) y
res.partner.ocapi_bindings (ocapi.binding.client, ACL solo para "Odoo Connectors Api Manager").
26.295 da LECTURA de ocapi.binding.client a base.group_user (sin escribir/crear/borrar).

El test abre el formulario COMPLETO como lo hace el cliente web (get_views + lectura de todos los
campos del arch), no un campo suelto: asi un binding nuevo sin ACL vuelve a dar rojo aca.
Control: test_control_sin_acl_ocapi_falla quita el ACL nuevo dentro del test y mide el AccessError.
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    etree = None


@tagged('post_install', '-at_install', 'meli_26295')
class TestPartnerFormAcl26295(TransactionCase):

    def _crear_minimo(self, model, extra=None, _visitados=None):
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
            elif f.type == 'selection':
                sel = f.selection(Model) if callable(f.selection) else f.selection
                vals[name] = sel[0][0] if sel else False
            elif f.type == 'many2one':
                rec = self.env[f.comodel_name].search([], limit=1)
                if not rec and f.comodel_name not in _visitados:
                    _visitados.add(f.comodel_name)
                    rec = self._crear_minimo(f.comodel_name, None, _visitados)
                vals[name] = rec.id if rec else False
        vals.update(extra or {})
        return Model.create(vals)

    def setUp(self):
        super().setUp()
        groups = [self.env.ref('base.group_user').id]
        pm = self.env.ref('base.group_partner_manager', raise_if_not_found=False)
        if pm:
            groups.append(pm.id)  # crear/editar contactos: no es un grupo de conectores
        gfield = 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'
        self.user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Interno sin conectores 26295', 'login': 'interno_sin_conectores_26295',
            gfield: [(6, 0, groups)]})
        for xid in ('meli_oerp_multiple.group_mercadolibre_connectors_manager',
                    'odoo_connector_api.group_ocapi_connectors_manager',
                    'meli_oerp.group_mercadolibre_manager', 'meli_oerp.group_mercadolibre_reader'):
            if self.env.ref(xid, raise_if_not_found=False):
                self.assertFalse(self.user.has_group(xid), "el usuario de prueba no debe tener %s" % xid)
        self.client_ml = self._crear_minimo('mercadolibre.client', {'name': 'NICK26295'})
        self.client_ocapi = self._crear_minimo('ocapi.binding.client', {'name': 'OCAPI26295'})
        self.partner = self.env['res.partner'].create({
            'name': 'Contacto con bindings 26295',
            'mercadolibre_bindings': [(6, 0, [self.client_ml.id])],
            'ocapi_bindings': [(6, 0, [self.client_ocapi.id])]})

    def _campos_del_formulario(self, Partner):
        views = Partner.get_views([(False, 'form')])
        arch = views['views']['form']['arch']
        fdesc = views['models']['res.partner']
        if isinstance(fdesc, dict) and 'fields' in fdesc:
            fdesc = fdesc['fields']
        node = etree.fromstring(arch.encode() if isinstance(arch, str) else arch)
        top = [n.get('name') for n in node.iter('field')
               if not any(a.tag == 'field' for a in n.iterancestors())]
        return {f: (fdesc.get(f) or {}) for f in dict.fromkeys(top) if f in Partner._fields}

    def _abrir_formulario(self):
        Partner = self.env['res.partner'].with_user(self.user)
        campos = self._campos_del_formulario(Partner)
        self.assertIn('ocapi_bindings', campos, "el formulario debe cargar ocapi_bindings (si no, el test no mide nada)")
        self.assertIn('mercadolibre_bindings', campos)
        p = Partner.browse(self.partner.id)
        if hasattr(self.env, 'invalidate_all'):  # cache vacia, como un request nuevo del cliente web
            self.env.invalidate_all()
        else:
            self.env.cache.invalidate()
        relacionales = [f for f, d in campos.items()
                        if p._fields[f].type in ('many2one', 'one2many', 'many2many')]
        if hasattr(p, 'web_read'):  # 17+: lo que pide el formulario
            spec = {f: ({'fields': {'display_name': {}}} if f in relacionales else {}) for f in campos}
            p.web_read(spec)
        else:  # 16: read + display_name de los relacionales
            p.read(list(campos))
            for f in relacionales:
                p[f].mapped('display_name')
        self.assertEqual(p.ocapi_bindings.ids, [self.client_ocapi.id])
        p.write({'name': 'Contacto con bindings 26295 (editado)'})
        self.assertEqual(self.partner.name, 'Contacto con bindings 26295 (editado)')

    def test_interno_sin_grupos_abre_y_edita_contacto(self):
        self._abrir_formulario()

    def test_interno_no_puede_escribir_binding_ocapi(self):
        with self.assertRaises(AccessError):
            self.client_ocapi.with_user(self.user).write({'name': 'otro'})

    def test_control_sin_acl_ocapi_falla(self):
        acl = self.env.ref('odoo_connector_api.access_ocapi_client_user', raise_if_not_found=False)
        if acl:
            acl.unlink()
        with self.assertRaises(AccessError):
            self._abrir_formulario()
