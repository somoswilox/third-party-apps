# -*- coding: utf-8 -*-
"""26.382 — caso-K51 cliente U (7-nov-2026): re-apuntar una vinculación mantiene las listas "Bindings".

Caso real: binding 7006 / tmplbind 949 (Deville 555 Avellana 90) re-apuntado de DEVK18AVE90 (tmpl 601) a
DEV555AVE90 (tmpl 555) escribiendo product_id/product_tmpl_id: la M2M product.product.mercadolibre_bindings y
product.template.mercadolibre_bindings quedaban en el 601 => Publicar desde el 555 y el post por movimiento de
stock de DEV555AVE90 no le llegaban. Sin red.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli', 'meli_bind_rels')
class TestBindRels(TransactionCase):

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
        super(TestBindRels, self).setUp()
        try:
            self.account = self.env['mercadolibre.account'].search([], limit=1) \
                or self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("no se pudo obtener una mercadolibre.account: %s" % e)
        Tmpl = self.env['product.template']
        self.t601 = Tmpl.create({'name': 'Deville 601 (test 26382)', 'default_code': 'T382-K18'})
        self.t555 = Tmpl.create({'name': 'Deville 555 (test 26382)', 'default_code': 'T382-555'})
        self.p601 = self.t601.product_variant_ids[:1]
        self.p555 = self.t555.product_variant_ids[:1]
        self.bt = self.env['mercadolibre.product_template'].create({
            'name': 'Av90', 'connection_account': self.account.id, 'conn_id': 'MLA9377230465',
            'product_tmpl_id': self.t601.id})
        self.bv = self.env['mercadolibre.product'].create({
            'name': 'Av90', 'connection_account': self.account.id, 'conn_id': 'MLA9377230465',
            'product_tmpl_id': self.t601.id, 'product_id': self.p601.id, 'binding_product_tmpl_id': self.bt.id})
        self.t601.mercadolibre_bindings = [(4, self.bt.id)]
        self.p601.mercadolibre_bindings = [(4, self.bv.id)]

    def test_01_reapuntar_variante_mueve_m2m(self):
        self.bv.write({'product_id': self.p555.id, 'product_tmpl_id': self.t555.id})
        self.assertNotIn(self.bv, self.p601.mercadolibre_bindings)
        self.assertIn(self.bv, self.p555.mercadolibre_bindings)

    def test_02_reapuntar_plantilla_mueve_m2m(self):
        self.bt.write({'product_tmpl_id': self.t555.id})
        self.assertNotIn(self.bt, self.t601.mercadolibre_bindings)
        self.assertIn(self.bt, self.t555.mercadolibre_bindings)

    def test_03_write_sin_cambio_de_dueno_no_toca(self):
        self.bv.write({'name': 'Av90 bis', 'product_id': self.p601.id})
        self.bt.write({'name': 'Av90 bis'})
        self.assertIn(self.bv, self.p601.mercadolibre_bindings)
        self.assertIn(self.bt, self.t601.mercadolibre_bindings)
        self.assertNotIn(self.bv, self.p555.mercadolibre_bindings)

    def test_04_opt_out_por_contexto(self):
        self.bv.with_context(meli_skip_bind_rels=True).write({'product_id': self.p555.id})
        self.assertIn(self.bv, self.p601.mercadolibre_bindings)
        self.assertNotIn(self.bv, self.p555.mercadolibre_bindings)
