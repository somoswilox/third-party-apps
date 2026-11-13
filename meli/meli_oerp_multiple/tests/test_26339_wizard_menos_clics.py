# -*- coding: utf-8 -*-
"""26.339 W1-W4/W6/W7 (caso-K21 cliente F, capacitación 29-oct-2026): el asistente «Publicar/Actualizar en ML»
pedía cuenta, tildes y datos típicos a mano, y mostraba un error por intento. Ahora viene preseleccionado
(defaults de la compañía/cuenta) y lista lo que falta de una vez.
Control (código anterior): cuenta vacía, tildes en False, sin campos de IVA ni lista de faltantes.
Sin red: el predictor de categoría y la hidratación quedan parcheados.
Correr: odoo-bin ... -u meli_oerp_multiple --test-enable --test-tags meli_wK21 --stop-after-init
"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_wK21')
class TestWizardMenosClics(TransactionCase):

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

    def setUp(self):
        super().setUp()
        p = patch.object(type(self.env['meli.util']), 'get_new_instance',
                         side_effect=AssertionError("llamada a ML"))
        p.start()
        self.addCleanup(p.stop)
        self.company = self.env.user.company_id
        try:
            self.account = self.env['mercadolibre.account'].search([], limit=1) \
                or self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("no se pudo obtener una mercadolibre.account: %s" % e)
        otra = self.env['res.company'].create({'name': 'WK21 otra'})
        (self.company.mercadolibre_connections - self.account).write({'company_id': otra.id})
        self.pricelist = self.env['product.pricelist'].create({'name': 'Mercado Libre (WK21)'})
        self.account.write({'company_id': self.company.id, 'meli_user_site_id': 'MLA'})
        self.account.configuration.mercadolibre_pricelist = self.pricelist
        self.Wiz = self.env['mercadolibre.product.template.post']

    def _wiz(self, ids=(), **vals):
        return self.Wiz.with_context(active_model='product.template', active_ids=list(ids)).create(vals)

    def test_w1_w2_w3_w4_defaults(self):
        wiz = self._wiz()
        self.assertEqual(wiz.connectors, self.account)                 # W1
        self.assertTrue(wiz.force_meli_pub)                            # W2
        self.assertTrue(wiz.force_meli_active)                         # W2
        self.assertEqual(wiz.force_meli_new_pricelist, self.pricelist) # W3
        self.assertEqual(wiz.meli_vat_default, '21 %')                 # W4
        self.assertEqual(wiz.meli_import_duty_default, '0 %')          # W4

    def test_w1_dos_cuentas_no_preselecciona(self):
        otra = self.account.copy({'name': 'WK21 2da', 'company_id': self.company.id})
        self.assertEqual(len(self.company.mercadolibre_connections), 2)
        self.assertFalse(self.Wiz.default_get(['connectors']).get('connectors'))
        self.assertTrue(otra)

    def test_w4_fuera_de_mla_no_inventa(self):
        self.account.meli_user_site_id = 'MLM'
        d = self.Wiz.default_get(['meli_vat_default', 'meli_import_duty_default'])
        self.assertFalse(d.get('meli_vat_default'))
        self.assertFalse(d.get('meli_import_duty_default'))

    def test_w2_pausar_destilda_activacion(self):
        wiz = self._wiz()
        wiz.action_pause = True
        wiz._onchange_w_action_pause()
        self.assertFalse(wiz.force_meli_active)

    def test_w4_w6_prepara_solo_lo_que_falta(self):
        tmpl = self.env['product.template'].create({'name': 'WK21 prod', 'meli_import_duty': '10,5 %'})
        categ = self.env['mercadolibre.category'].create({'name': 'Cat WK21', 'meli_category_id': 'MLA0462'})
        Tmpl = type(tmpl)
        with patch.object(Tmpl, '_get_meli_category_from_predictor', lambda s: (categ, [])), \
             patch.object(type(self.env['mercadolibre.category']), 'import_category', lambda s, *a, **k: categ):
            self._wiz([tmpl.id])._w_prepare_template(tmpl)
        self.assertEqual(tmpl.meli_vat, '21 %')            # vacío => default
        self.assertEqual(tmpl.meli_import_duty, '10,5 %')  # cargado => no se pisa
        self.assertEqual(tmpl.meli_category, categ)        # W6

    def test_w7_lista_unica_de_faltantes(self):
        a = self.env['product.template'].create({'name': 'WK21 sin marca'})
        b = self.env['product.template'].create({'name': 'WK21 con marca', 'meli_brand': 'cliente F'})
        html = self._wiz([a.id, b.id]).w_precheck_html or ''
        self.assertIn('WK21 sin marca', html)
        self.assertIn('marca', html)
        self.assertIn('categoría', html)
        self.assertIn('WK21 con marca', html)  # le falta categoría/modelo igual
