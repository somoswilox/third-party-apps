# -*- coding: utf-8 -*-
"""26.329 (caso-K09, bus 2026-09-26T23:32:15Z): pregunta sobre una publicacion SIN vincular = caso normal.
Se loguea WARNING (no ERROR, que disparaba alertas del conector). Sin red."""
from odoo import fields
from odoo.tests import TransactionCase, tagged

LOGGER = 'odoo.addons.meli_oerp_multiple.models.questions'


@tagged('post_install', '-at_install', 'meli', 'meli_26329')
class TestPreguntaSinBinding(TransactionCase):

    def _crear_minimo(self, model, _visitados=None):
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

    def test_warning_no_error(self):
        cuenta = self.env['mercadolibre.account'].search([], limit=1)
        if not cuenta:
            try:
                cuenta = self._crear_minimo('mercadolibre.account')
            except Exception as e:
                self.skipTest("sin mercadolibre.account: %s" % e)
        config = cuenta.configuration
        if 'accounts' in config._fields and cuenta not in config.accounts:
            config.accounts = [(4, cuenta.id)]
        if not cuenta.company_id:
            cuenta.company_id = self.env.company
        Q = self.env['mercadolibre.questions']
        with self.assertLogs(LOGGER, level='WARNING') as logs:
            try:
                Q.prepare_question_fields({'item_id': 'MLM6352301845', 'id': 1, 'text': 'hola', 'status': 'UNANSWERED',
                                           'date_created': '2026-09-26T19:56:00.000-04:00', 'from': {'id': 1}},
                                          config=config)
            except Exception:
                pass  # lo que pase despues del log no es materia de este test
        lineas = [l for l in logs.output if 'Question not binded' in l]
        self.assertTrue(lineas, logs.output)
        self.assertTrue(all(l.startswith('WARNING') for l in lineas), lineas)
