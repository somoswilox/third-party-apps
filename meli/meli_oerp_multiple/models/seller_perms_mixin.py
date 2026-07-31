# -*- coding: utf-8 -*-
"""Mixin: asegurar que el Vendedor ML y el Equipo de ventas ML tengan los grupos
manager necesarios para operar la cuenta (el cron de pedidos corre COMO ese usuario,
y los modelos meli son manager-only → sin el grupo, AccessError).

Lo usan res.company y mercadolibre.configuration (ambos exponen mercadolibre_seller_user
y mercadolibre_seller_team). El chequeo es parte del form de configuración:
- onchange al asignar Vendedor/Equipo → avisa si faltan permisos.
- botón 'Asignar permisos ML' (con confirmación) → agrega los grupos.
Backfill de configs existentes: migrations/19.0.26.46/post-migrate.py.
"""
from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)

# Grupos que un Vendedor/Equipo ML necesita para operar la cuenta.
MELI_REQUIRED_GROUP_XMLIDS = [
    'meli_oerp_multiple.group_mercadolibre_connectors_manager',
]


class MercadolibreSellerPermsMixin(models.AbstractModel):
    _name = 'mercadolibre.seller.perms.mixin'
    _description = 'ML: permisos del Vendedor / Equipo de ventas'

    @api.model
    def _meli_groups_field(self):
        """Nombre del campo m2m de grupos en res.users (Odoo 19: group_ids; 16-18: groups_id)."""
        return 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'

    @api.model
    def _meli_required_groups(self):
        groups = self.env['res.groups']
        for xmlid in MELI_REQUIRED_GROUP_XMLIDS:
            g = self.env.ref(xmlid, raise_if_not_found=False)
            if g:
                groups |= g
        return groups

    def _meli_seller_users(self):
        """Vendedor ML + miembros (y líder) del Equipo de ventas ML, en estos registros."""
        users = self.env['res.users']
        for rec in self:
            if rec.mercadolibre_seller_user:
                users |= rec.mercadolibre_seller_user
            team = rec.mercadolibre_seller_team
            if team:
                if 'member_ids' in team._fields:
                    users |= team.member_ids
                if team.user_id:
                    users |= team.user_id
        return users

    def _meli_users_missing_groups(self):
        """(usuarios_a_los_que_les_falta, grupos_requeridos)."""
        groups = self._meli_required_groups()
        fld = self._meli_groups_field()
        missing = self.env['res.users']
        if groups:
            for u in self._meli_seller_users():
                if groups - u[fld]:
                    missing |= u
        return missing, groups

    def action_meli_assign_seller_permissions(self):
        """Agrega los grupos manager faltantes al Vendedor/Equipo ML (con sudo)."""
        missing, groups = self._meli_users_missing_groups()
        if not groups:
            return self._meli_notify(_("Sin grupos requeridos"),
                                     _("No se encontró el grupo MercadoLibre Manager."), 'warning')
        if not missing:
            return self._meli_notify(_("Permisos OK"),
                                     _("El Vendedor ML y el Equipo de ventas ya tienen los permisos necesarios."), 'info')
        fld = self._meli_groups_field()
        missing.sudo().write({fld: [(4, g.id) for g in groups]})
        names = ", ".join(missing.mapped('login'))
        _logger.info("ML permisos: agregados %s al Vendedor/Equipo ML: %s", groups.mapped('name'), names)
        return self._meli_notify(_("Permisos asignados"),
                                 _("Se agregó MercadoLibre Manager a: %s") % names, 'success')

    def _meli_notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': ntype, 'sticky': False},
        }

    def _meli_seller_perms_warning(self):
        """Warning para onchange: avisa si el Vendedor/Equipo no tiene los permisos."""
        missing, groups = self._meli_users_missing_groups()
        if missing:
            names = ", ".join(missing.mapped('login'))
            return {'warning': {
                'title': _("Permisos de MercadoLibre faltantes"),
                'message': _(
                    "El/los usuario(s) %s no tienen el grupo 'MercadoLibre Manager', "
                    "necesario para que el cron de pedidos opere la cuenta ML.\n\n"
                    "Usá el botón 'Asignar permisos ML' para agregarlos."
                ) % names,
            }}
        return {}
