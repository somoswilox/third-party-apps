# -*- coding: utf-8 -*-
"""26.360 (OFF 719, caso-K39 cliente B1) -- Connection Accounts abría el popup «JSON Usuario ML» vacío.

La acción de Connection Accounts no fija vistas: el form lo elige Odoo con `default_view`
(form primario ACTIVO de menor priority, después nombre). Había dos forms primarios de
mercadolibre.account sin priority: el principal y el popup del JSON (sólo para el botón, con
view_id explícito). Si el principal queda inactivo (p. ej. tras una migración de versión) o con
otra priority, el default pasa a ser el popup, y un `-u` no lo arreglaba porque el XML no
declaraba `active` (un <record> sólo escribe los campos que trae).
Ahora: popup con priority 99 (nunca compite) y el principal con active=True explícito (el `-u`
lo reactiva). Los tests simulan la base del cliente y recargan el XML como lo hace el `-u`.
Control (origin sin el fix): fallan los dos escenarios de recarga.
"""
import inspect

from odoo.tests import TransactionCase, tagged
from odoo.tools import convert

MAIN = 'meli_oerp_multiple.view_connection_account_mercadolibre'
POPUP = 'meli_oerp_multiple.view_mercadolibre_account_json_popup'
MODEL = 'mercadolibre.account'


@tagged('post_install', '-at_install', 'meli_K39_vista')
class TestVistaCuentaDefault26360(TransactionCase):

    def setUp(self):
        super().setUp()
        self.main = self.env.ref(MAIN)
        self.popup = self.env.ref(POPUP)

    def _default_form(self):
        return self.env['ir.ui.view'].default_view(MODEL, 'form')

    def _form_de_la_accion(self):
        # lo que pide el cliente web: get_views con view_id False para el form
        return self.env[MODEL].get_views([(False, 'form')])['views']['form']['id']

    def _recargar_xml(self):
        """Lo mismo que hace `-u meli_oerp_multiple` con el archivo de vistas."""
        first = list(inspect.signature(convert.convert_file).parameters)[0]
        target = self.env.cr if first == 'cr' else self.env
        convert.convert_file(target, 'meli_oerp_multiple', 'views/connection_account_view.xml',
                             {}, mode='update', noupdate=False)
        self.env.invalidate_all() if hasattr(self.env, 'invalidate_all') else self.env.cache.invalidate()

    def test_1_default_es_el_principal(self):
        self.assertEqual(self._default_form(), self.main.id)
        self.assertEqual(self._form_de_la_accion(), self.main.id)

    def test_2_principal_inactivo_se_reactiva_con_update(self):
        self.main.active = False
        # sintoma del cliente: con el principal inactivo, el default es el popup
        self.assertEqual(self._default_form(), self.popup.id)
        self._recargar_xml()
        self.assertTrue(self.main.active, 'el -u tiene que reactivar el form principal')
        self.assertEqual(self._default_form(), self.main.id)
        self.assertEqual(self._form_de_la_accion(), self.main.id)

    def test_3_popup_no_compite_aunque_cambie_la_priority_del_principal(self):
        self.main.priority = 20
        self._recargar_xml()
        self.assertGreater(self.popup.priority, self.main.priority)
        self.assertEqual(self._default_form(), self.main.id)

    def test_4_boton_json_sigue_abriendo_el_popup(self):
        acc = self.env[MODEL].new({'name': 'Cuenta 26360'})
        act = acc.action_view_raw_json_popup()
        self.assertEqual(act['view_id'], self.popup.id)
        self.assertEqual(act['target'], 'new')
