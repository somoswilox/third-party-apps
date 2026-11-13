# -*- coding: utf-8 -*-
"""26.269 (#caso-K14): un usuario interno SIN grupo de MercadoLibre editaba un contacto con
mercadolibre_bindings y recibia "Error de acceso" (mercadolibre.client solo tenia ACL para el
grupo manager de conectores). Ahora base.group_user tiene LECTURA (sin escribir/crear/borrar).

Control: test_control_sin_acl_falla quita el ACL nuevo dentro del test y mide el AccessError.
"""
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_26269')
class TestClientAcl26269(TransactionCase):

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
            groups.append(pm.id)  # crear/editar contactos: no es un grupo de ML
        gfield = 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'
        self.user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Interno sin ML 26269', 'login': 'interno_sin_ml_26269',
            gfield: [(6, 0, groups)]})
        for xid in ('meli_oerp_multiple.group_mercadolibre_connectors_manager',
                    'meli_oerp.group_mercadolibre_manager', 'meli_oerp.group_mercadolibre_reader'):
            g = self.env.ref(xid, raise_if_not_found=False)
            if g:
                self.assertFalse(self.user.has_group(xid), "el usuario de prueba no debe tener %s" % xid)
        self.client_ml = self._crear_minimo('mercadolibre.client', {'name': 'NICK26269'})
        self.partner = self.env['res.partner'].create({
            'name': 'Contacto con binding ML', 'mercadolibre_bindings': [(6, 0, [self.client_ml.id])]})

    def _leer_y_editar(self):
        p = self.partner.with_user(self.user)
        p.invalidate_recordset()
        binds = p.mercadolibre_bindings
        self.assertEqual(binds.ids, [self.client_ml.id])
        binds.mapped('display_name')                    # lo que pinta el many2many del formulario
        p.read(['name', 'mercadolibre_bindings'])
        if hasattr(p, 'web_read'):                      # 17+: lo que pide el formulario
            p.web_read({'name': {}, 'mercadolibre_bindings': {'fields': {'display_name': {}, 'name': {}}}})
        p.write({'name': 'Contacto con binding ML (editado)'})
        self.assertEqual(self.partner.name, 'Contacto con binding ML (editado)')

    def test_interno_sin_grupo_ml_lee_y_edita_contacto(self):
        self._leer_y_editar()

    def test_interno_no_puede_escribir_el_binding(self):
        with self.assertRaises(AccessError):
            self.client_ml.with_user(self.user).write({'name': 'otro'})

    def test_control_sin_acl_falla(self):
        acl = self.env.ref('meli_oerp_multiple.access_mercadolibre_client_user', raise_if_not_found=False)
        if acl:
            acl.unlink()
        with self.assertRaises(AccessError):
            self._leer_y_editar()
