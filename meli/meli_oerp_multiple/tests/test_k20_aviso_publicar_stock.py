# -*- coding: utf-8 -*-
"""26.268: el boton 'Publicar Stock' de la plantilla avisa al usuario.

Antes: sin vinculaciones no hacia nada y no decia nada; con vinculacion, si el push
cortaba (bloqueo, regla SKU 'Filtro', Full, 403, 404...) el motivo quedaba solo en
stock_error de la vinculacion. Ahora, SOLO con el context que pone el boton
(meli_post_stock_notify), devuelve un meli.warning con el motivo o una notificacion de
exito. Sin el flag (crons, asistentes) devuelve la lista de siempre.

Sin red: el push de la vinculacion queda parcheado y meli.util falla si se lo llama.
"""

from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_K20')
class TestAvisoPublicarStock(TransactionCase):

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
                    rec = self._crear_minimo(f.comodel_name, None, _visitados)
                vals[name] = rec.id if rec else False
        vals.update(extra or {})
        return Model.create(vals)

    def setUp(self):
        super().setUp()
        p = patch.object(type(self.env['meli.util']), 'get_new_instance',
                         side_effect=AssertionError("llamada a ML"))
        p.start()
        self.addCleanup(p.stop)
        try:
            self.conf = self._crear_minimo('mercadolibre.configuration')
            self.account = self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("No se pudo armar cuenta/configuracion en esta base: %s" % e)
        self.account.write({'configuration': self.conf.id, 'company_id': self.env.company.id})
        self.tmpl = self.env['product.template'].create({'name': 'TK20 plantilla'})
        self.prod = self.tmpl.product_variant_ids[:1]
        # Lo que el push "deja" en cada vinculacion de variante (lo setea el parche).
        self.resultado = {}
        test = self

        def _fake_post(bindT, context=None, meli_id=None, meli=None, account=None):
            for bindv in bindT.variant_bindings:
                bindv.stock_error = test.resultado.get(bindv.conn_id, "Ok")
            return {}
        p2 = patch.object(type(self.env['mercadolibre.product_template']),
                          'product_template_post_stock', _fake_post)
        p2.start()
        self.addCleanup(p2.stop)

    def _vincular(self, conn_id, variantes=True):
        bindT = self._crear_minimo('mercadolibre.product_template', {
            'name': self.tmpl.name, 'connection_account': self.account.id,
            'product_tmpl_id': self.tmpl.id, 'conn_id': conn_id})
        if variantes:
            self._crear_minimo('mercadolibre.product', {
                'name': self.prod.name, 'connection_account': self.account.id,
                'product_id': self.prod.id, 'conn_id': conn_id,
                'binding_product_tmpl_id': bindT.id})
        self.tmpl.write({'mercadolibre_bindings': [(4, bindT.id)]})
        return bindT

    def _boton(self):
        return self.tmpl.with_context(meli_post_stock_notify=True).product_template_post_stock()

    def _warning_text(self, action):
        self.assertEqual(action.get('res_model'), 'meli.warning', action)
        w = self.env['meli.warning'].browse(action['res_id'])
        return "%s %s" % (w.message or '', w.message_html or '')

    def test_1_sin_vinculacion_avisa(self):
        """Sin vinculaciones el boton ya no es mudo: dice que hay que vincular."""
        txt = self._warning_text(self._boton())
        self.assertIn("no está vinculado a ninguna publicación", txt)
        self.assertIn("Importar Masivamente", txt)

    def test_2_sin_flag_no_cambia_el_contrato(self):
        """Crons y asistentes (sin el flag) siguen recibiendo la lista de resultados."""
        self.assertEqual(self.tmpl.product_template_post_stock(), [])
        self._vincular('MLA431534459')
        self.assertEqual(self.tmpl.product_template_post_stock(), [{}])

    def test_3_corte_por_stock_error_muestra_el_motivo(self):
        """Si el push corta, el motivo de stock_error llega a la pantalla, por publicacion."""
        self._vincular('MLA443840262')
        self.resultado['MLA443840262'] = str({"error": "product blocked"})
        txt = self._warning_text(self._boton())
        self.assertIn("MLA443840262", txt)
        self.assertIn("bloqueada", txt)

    def test_4_error_desconocido_se_muestra_crudo(self):
        self._vincular('MLA464210643')
        self.resultado['MLA464210643'] = "{'error': 'algo raro de ML'}"
        txt = self._warning_text(self._boton())
        self.assertIn("algo raro de ML", txt)

    def test_5_todo_ok_notifica_exito(self):
        self._vincular('MLA422156214')
        action = self._boton()
        self.assertEqual(action.get('tag'), 'display_notification', action)
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn("1 publicación", action['params']['message'])

    def test_6_vinculacion_sin_variantes(self):
        self._vincular('MLA450906501', variantes=False)
        txt = self._warning_text(self._boton())
        self.assertIn("no tiene variantes vinculadas", txt)
