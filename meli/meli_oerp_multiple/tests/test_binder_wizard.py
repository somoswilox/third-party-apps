# -*- coding: utf-8 -*-
"""Tests de los wizards de VINCULACION de publicaciones de MercadoLibre.

Escritos a partir de dos bugs medidos en la una cuenta (un cliente) el 22-sep-2026, que
juntos hacian que vincular una publicacion a mano fuera imposible Y silencioso:

  BUG A  `product_product_add_to_connector` asignaba `bind_only` SOLO dentro de
         `if self.bind_only:` y despues lo pasaba al bind => con el tilde apagado
         reventaba con UnboundLocalError. Log del cliente:
         2026-09-22 16:13:39 "cannot access local variable 'bind_only'".
  BUG B  la vista `view_product_product_add_to_mercadolibre` tenia los campos sueltos
         bajo <form>, fuera de un <group> y sin <label for=...> => en Odoo 17+ se
         dibujan SIN etiqueta. El usuario no veia donde poner el MLA, lo dejaba vacio,
         y la accion llamaba al bind con meli_id=False sin decir nada.

Los dos eran invisibles: ningun test existia sobre este camino, la accion descartaba
el retorno del bind y el `except` de mas abajo se comia las excepciones.
"""

from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBinderWizard(TransactionCase):

    # ---------------------------------------------------------------- helpers
    def _crear_minimo(self, model, _visitados=None):
        """Crea un registro llenando SOLO los campos required. Generico a proposito:
        mercadolibre.account pide una decena de required y una configuration, y
        enumerarlos a mano deja el test quebradizo ante cualquier campo nuevo."""
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
            elif f.type == 'date':
                vals[name] = fields.Date.today()
            elif f.type == 'datetime':
                vals[name] = fields.Datetime.now()
            elif f.type == 'selection':
                sel = f.selection(Model) if callable(f.selection) else f.selection
                vals[name] = sel[0][0] if sel else False
            elif f.type == 'many2one':
                rec = self.env[f.comodel_name].search([], limit=1)
                if not rec and f.comodel_name not in _visitados:
                    _visitados.add(f.comodel_name)
                    rec = self._crear_minimo(f.comodel_name, _visitados)
                vals[name] = rec.id if rec else False
        return Model.create(vals)

    def _cuenta(self):
        cuenta = self.env['mercadolibre.account'].search([], limit=1)
        if cuenta:
            return cuenta
        try:
            return self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("No se pudo obtener una mercadolibre.account en esta base: %s" % e)

    def _producto(self):
        prod = self.env['product.product'].search([('default_code', '!=', False)], limit=1)
        if not prod:
            prod = self.env['product.product'].create({'name': 'TEST bind', 'default_code': 'TEST-BIND-1'})
        return prod

    # ---------------------------------------------------------------- BUG A
    def test_variante_con_tilde_apagado_no_levanta_unbound_local(self):
        """BUG A: con bind_only apagado la accion no debe reventar por variable no ligada.

        Es LA regresion: antes del fix esto era un UnboundLocalError, y como el tilde
        no estaba en la vista, era el 100% de las corridas.
        """
        cuenta = self._cuenta()
        prod = self._producto()
        wiz = self.env['mercadolibre.variant.binder.wiz'].create({
            'meli_id': 'MLA986502348',
            'connectors': [(6, 0, cuenta.ids)],
            'bind_only': False,
        })
        llamadas = []

        def _fake_bind(self_prod, account, **kw):
            llamadas.append(kw)
            return self_prod.env['mercadolibre.product']

        with patch.object(type(prod), 'mercadolibre_bind_to', _fake_bind):
            res = wiz.with_context(active_ids=[prod.id]).product_product_add_to_connector()

        self.assertTrue(llamadas, "el bind no se llamo")
        self.assertIn('bind_only', llamadas[0])
        self.assertIs(llamadas[0]['bind_only'], False,
                      "bind_only tiene que llegar como False, no faltar")
        self.assertEqual(res.get('tag'), 'display_notification',
                         "la accion tiene que devolver una notificacion")

    def test_variante_con_tilde_encendido_pasa_bind_only_true(self):
        cuenta = self._cuenta()
        prod = self._producto()
        wiz = self.env['mercadolibre.variant.binder.wiz'].create({
            'meli_id': 'MLA986502348',
            'connectors': [(6, 0, cuenta.ids)],
            'bind_only': True,
        })
        llamadas = []

        def _fake_bind(self_prod, account, **kw):
            llamadas.append(kw)
            return self_prod.env['mercadolibre.product']

        with patch.object(type(prod), 'mercadolibre_bind_to', _fake_bind):
            wiz.with_context(active_ids=[prod.id]).product_product_add_to_connector()

        self.assertIs(llamadas[0]['bind_only'], True)

    # ------------------------------------------------- guard de meli_id vacio
    def test_variante_sin_meli_id_avisa_en_vez_de_bindear_con_false(self):
        """Antes llamaba al bind con meli_id=False y cerraba el dialogo sin decir nada."""
        cuenta = self._cuenta()
        prod = self._producto()
        wiz = self.env['mercadolibre.variant.binder.wiz'].create({
            'connectors': [(6, 0, cuenta.ids)],
        })
        with patch.object(type(prod), 'mercadolibre_bind_to') as m:
            with self.assertRaises(UserError):
                wiz.with_context(active_ids=[prod.id]).product_product_add_to_connector()
            m.assert_not_called()

    def test_variante_sin_cuenta_avisa(self):
        prod = self._producto()
        wiz = self.env['mercadolibre.variant.binder.wiz'].create({'meli_id': 'MLA986502348'})
        with self.assertRaises(UserError):
            wiz.with_context(active_ids=[prod.id]).product_product_add_to_connector()

    def test_plantilla_sin_meli_id_avisa(self):
        cuenta = self._cuenta()
        tmpl = self._producto().product_tmpl_id
        wiz = self.env['mercadolibre.binder.wiz'].create({
            'connectors': [(6, 0, cuenta.ids)],
        })
        with self.assertRaises(UserError):
            wiz.with_context(active_ids=[tmpl.id]).product_template_add_to_connector()

    def test_plantilla_devuelve_notificacion(self):
        cuenta = self._cuenta()
        tmpl = self._producto().product_tmpl_id
        wiz = self.env['mercadolibre.binder.wiz'].create({
            'meli_id': 'MLA986502348',
            'connectors': [(6, 0, cuenta.ids)],
        })

        def _fake_bind(self_tmpl, account, **kw):
            return self_tmpl.env['mercadolibre.product_template']

        with patch.object(type(tmpl), 'mercadolibre_bind_to', _fake_bind):
            res = wiz.with_context(active_ids=[tmpl.id]).product_template_add_to_connector()
        self.assertEqual(res.get('tag'), 'display_notification')

    # ---------------------------------------------------------------- BUG B
    def test_vista_de_variante_tiene_los_campos_dentro_de_un_group(self):
        """BUG B: un <field> suelto bajo <form> se dibuja SIN label en Odoo 17+.

        Este test es el que faltaba: el bug no estaba en la logica sino en el arch, y
        ningun test de comportamiento lo habria visto. Se exige <group> o <label for>.
        """
        from lxml import etree
        vista = self.env.ref('meli_oerp_multiple.view_product_product_add_to_mercadolibre')
        arbol = etree.fromstring(vista.arch)
        for campo in ('meli_id', 'meli_id_variation'):
            nodos = arbol.xpath('//field[@name="%s"]' % campo)
            self.assertTrue(nodos, "la vista no tiene el campo %s" % campo)
            nodo = nodos[0]
            tiene_group = any(a.tag == 'group' for a in nodo.iterancestors())
            tiene_label = bool(arbol.xpath('//label[@for="%s"]' % campo))
            self.assertTrue(
                tiene_group or tiene_label,
                "%s se renderiza sin etiqueta: ponelo en un <group> o agregale <label for>" % campo)

    def test_las_cuatro_vistas_de_vinculacion_etiquetan_su_meli_id(self):
        """Control cruzado: el bug era que UNA de las cuatro no etiquetaba. Si vuelve a
        pasar en cualquiera de ellas, este test lo dice."""
        from lxml import etree
        vistas = [
            'view_product_template_add_to_mercadolibre',
            'view_product_template_remove_from_mercadolibre',
            'view_product_product_add_to_mercadolibre',
            'view_product_product_remove_from_mercadolibre',
        ]
        sin_etiqueta = []
        for xmlid in vistas:
            vista = self.env.ref('meli_oerp_multiple.%s' % xmlid, raise_if_not_found=False)
            if not vista:
                continue
            arbol = etree.fromstring(vista.arch)
            nodos = arbol.xpath('//field[@name="meli_id"]')
            if not nodos:
                continue
            nodo = nodos[0]
            tiene_group = any(a.tag == 'group' for a in nodo.iterancestors())
            tiene_label = bool(arbol.xpath('//label[@for="meli_id"]'))
            if not (tiene_group or tiene_label):
                sin_etiqueta.append(xmlid)
        self.assertFalse(sin_etiqueta, "vistas con meli_id sin etiqueta: %s" % sin_etiqueta)

    # ---------------------------------------------------------------- 409: exito falso
    def _bind_con_copy(self, copy_fn, meli_id):
        """Corre el bind REAL de la variante con la red cortada: el item viene dado (rjson),
        el SKU y la plantilla se simulan, y `copy_from_rjson` hace lo que le pasemos."""
        cuenta = self._cuenta()
        prod = self._producto()
        Acc = type(cuenta)
        Tmpl = type(prod.product_tmpl_id)
        MP = type(self.env['mercadolibre.product'])
        rjson = {'error': 'forbidden', 'status': 403, 'message': 'invalid access token'}
        with patch.object(Acc, 'fetch_meli_sku', lambda *a, **k: prod.default_code), \
             patch.object(Tmpl, 'mercadolibre_bind_to', lambda *a, **k: self.env['mercadolibre.product_template']), \
             patch.object(MP, 'copy_from_rjson', copy_fn):
            res = prod.mercadolibre_bind_to(cuenta, meli_id=meli_id, rjson=rjson, meli=object(), bind_only=False)
        filas = self.env['mercadolibre.product'].search([('conn_id', '=', meli_id)])
        return res, filas

    def test_bind_que_revienta_no_devuelve_una_vinculacion_deshecha(self):
        """[caso-K34] ML responde error -> copy_from_rjson revienta (KeyError 'title') dentro del
        savepoint: la fila se deshace. Antes se devolvia igual el registro deshecho (truthy) y
        el asistente decia "Vinculacion creada" sin que existiera ninguna fila."""
        def _revienta(self_mp, rjson=None, meli=None):
            raise KeyError('title')
        with self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='ERROR'):
            res, filas = self._bind_con_copy(_revienta, 'MLA433294652')
        self.assertFalse(filas, "el savepoint tenia que deshacer la fila")
        self.assertFalse(res, "no se puede informar como vinculada una fila que no existe")

    def test_bind_que_anda_devuelve_la_vinculacion(self):
        """Control positivo del anterior: mismo camino sin fallo => fila creada y devuelta."""
        res, filas = self._bind_con_copy(lambda self_mp, rjson=None, meli=None: True, 'MLA475441293')
        self.assertEqual(len(filas), 1, "el bind tenia que crear la fila")
        self.assertEqual(res, filas, "el bind tiene que devolver la fila creada")

    def test_wizard_no_dice_exito_si_el_bind_revento(self):
        """[caso-K34] De punta a punta: el asistente de variante con ML respondiendo error."""
        cuenta = self._cuenta()
        prod = self._producto()
        wiz = self.env['mercadolibre.variant.binder.wiz'].create({
            'meli_id': 'MLA406801003',
            'connectors': [(6, 0, cuenta.ids)],
        })
        Acc = type(cuenta)
        rjson = {'error': 'forbidden', 'status': 403}
        def _revienta(self_mp, rjson=None, meli=None):
            raise KeyError('title')
        with patch.object(Acc, 'fetch_meli_product', lambda *a, **k: rjson), \
             patch.object(Acc, 'fetch_meli_sku', lambda *a, **k: prod.default_code), \
             patch.object(type(self.env['meli.util']), 'get_new_instance', lambda *a, **k: object()), \
             patch.object(type(prod.product_tmpl_id), 'mercadolibre_bind_to', lambda *a, **k: self.env['mercadolibre.product_template']), \
             patch.object(type(self.env['mercadolibre.product']), 'copy_from_rjson', _revienta), \
             self.assertLogs('odoo.addons.meli_oerp_multiple.models.product', level='ERROR'):
            res = wiz.with_context(active_ids=[prod.id]).product_product_add_to_connector()
        self.assertEqual(res['params']['type'], 'danger',
                         "con la vinculacion deshecha el aviso no puede ser de exito: %s" % res['params'])
