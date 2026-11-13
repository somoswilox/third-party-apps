# -*- coding: utf-8 -*-
"""#caso-K33 (cliente B caso-K01, 21-oct-2026): "En mano" / "Disponible" de la lista de vinculaciones.

Eran campos guardados que solo se escribian al ABRIR el formulario (efecto lateral de
_meli_stock_resume) => la lista mostraba 0 o una foto vieja, y el filtro "Disponible > 0"
solo traia las vinculaciones ya abiertas. Ahora se calculan en vivo desde los quants de las
ubicaciones de las que publica la vinculacion (Full aparte), SIN llamadas a Mercado Libre.

Sin red: meli.util.get_new_instance y la API de ML quedan parcheadas para fallar.
"""

from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_K01')
class TestStockResumeVivo(TransactionCase):

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
        # Ninguna llamada a ML: si el calculo la intenta, el test revienta.
        for target in (type(self.env['meli.util']),):
            p = patch.object(target, 'get_new_instance', side_effect=AssertionError("llamada a ML"))
            p.start()
            self.addCleanup(p.stop)
        PP = type(self.env['product.product'])
        if hasattr(PP, '_clear_logistic_type_cache'):
            PP._clear_logistic_type_cache()
            self.addCleanup(PP._clear_logistic_type_cache)
        try:
            self.conf = self._crear_minimo('mercadolibre.configuration')
            self.account = self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("No se pudo armar cuenta/configuracion en esta base: %s" % e)
        company = self.env.company
        self.account.write({'configuration': self.conf.id, 'company_id': company.id})
        wh = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        self.loc_wh = wh.lot_stock_id
        parent = self.env.ref('stock.stock_location_locations', raise_if_not_found=False) or wh.view_location_id.location_id
        self.loc_full = self.env['stock.location'].create({
            'name': 'MLFK01', 'usage': 'internal', 'location_id': parent.id, 'company_id': company.id,
            'mercadolibre_logistic_type': 'fulfillment'})
        self.assertFalse(self.loc_full.parent_path.startswith(self.loc_wh.parent_path))
        for rec in (self.conf, company):
            vals = {}
            if 'publish_stock' in rec._fields:
                vals['publish_stock'] = False
            if 'mercadolibre_stock_location_to_post' in rec._fields:
                vals['mercadolibre_stock_location_to_post'] = self.loc_wh.id
            if 'mercadolibre_stock_location_to_post_full' in rec._fields:
                vals['mercadolibre_stock_location_to_post_full'] = self.loc_full.id
            rec.write(vals)
        tipo = {'type': 'consu', 'is_storable': True} if 'is_storable' in self.env['product.template']._fields else {'type': 'product'}
        P = self.env['product.product']
        self.p_wh = P.create(dict(tipo, name='TK01 WH', default_code='TK01WH'))
        self.p_full = P.create(dict(tipo, name='TK01 FULL', default_code='TK01FULL'))
        self.p_none = P.create(dict(tipo, name='TK01 NADA', default_code='TK01NADA'))
        Q = self.env['stock.quant']
        Q._update_available_quantity(self.p_wh, self.loc_wh, 5.0)
        Q._update_available_quantity(self.p_full, self.loc_full, 3.0)
        self.b_wh = self._binding(self.p_wh, 'MLM501374705', 'xd_drop_off')
        self.b_full_noful = self._binding(self.p_full, 'MLM515901207', 'xd_drop_off')
        self.b_full_ful = self._binding(self.p_full, 'MLM502841403', 'fulfillment')
        self.b_none = self._binding(self.p_none, 'MLM572100132', 'xd_drop_off')
        self.all = self.b_wh | self.b_full_noful | self.b_full_ful | self.b_none
        self.all.invalidate_recordset()

    def _binding(self, product, conn_id, logistic):
        return self._crear_minimo('mercadolibre.product', {
            'name': product.name, 'connection_account': self.account.id, 'product_id': product.id,
            'conn_id': conn_id, 'meli_shipping_logistic_type': logistic})

    def test_1_lista_muestra_existencia_sin_abrir_el_form(self):
        """Sin abrir el formulario, En mano / Disponible = existencia actual de la ubicacion que publica."""
        self.assertEqual(self.b_wh.meli_stock_resume_on_hand, 5.0)
        self.assertEqual(self.b_wh.meli_stock_resume_available, 5.0)
        self.assertEqual(self.b_none.meli_stock_resume_available, 0.0)

    def test_2_full_no_cuenta_para_publicacion_no_full(self):
        """El stock en Full (MLF) no es publicable por una publicacion que no es Full, y si por la Full."""
        self.assertEqual(self.b_full_noful.meli_stock_resume_available, 0.0)
        self.assertEqual(self.b_full_ful.meli_stock_resume_available, 3.0)

    def test_3_filtro_disponible_mayor_a_cero(self):
        """El filtro "Disponible > 0" trae las que tienen existencia aunque nunca se hayan abierto."""
        found = self.env['mercadolibre.product'].search(
            [('id', 'in', self.all.ids), ('meli_stock_resume_available', '>', 0)])
        self.assertEqual(found, self.b_wh | self.b_full_ful)

    def test_4_sigue_la_existencia_actual(self):
        """Un movimiento posterior se ve sin reabrir nada (no hay foto)."""
        self.assertEqual(self.b_wh.meli_stock_resume_on_hand, 5.0)
        self.env['stock.quant']._update_available_quantity(self.p_wh, self.loc_wh, -5.0)
        self.all.invalidate_recordset()
        self.assertEqual(self.b_wh.meli_stock_resume_on_hand, 0.0)
        found = self.env['mercadolibre.product'].search(
            [('id', 'in', self.all.ids), ('meli_stock_resume_on_hand', '=', 0)])
        self.assertIn(self.b_wh, found)
