# -*- coding: utf-8 -*-
"""26.335 — #caso-K70 (cliente F caso-K21, 29-oct-2026): la vinculacion explicita gana sobre la heuristica GTIN/SKU.

Caso real: MLA2423425801 (combo pizarra + marcadores, Full) vinculada al kit 806090M_COM; en ML la
publicacion trae GTIN = barcode de la pizarra suelta y SELLER_SKU 806090M (la pizarra). El import de
ventas encontraba el binding y lo DESCARTABA (GTIN != barcode del kit y SKU != referencia del kit):
la venta entraba como la pizarra. Y el asistente "Vincular" salteaba el kit sin avisar.

Sin red: get_new_instance y las lecturas de ML del account quedan parcheadas.
"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

SALE_MOD = 'odoo.addons.meli_oerp_multiple.models.sale'
PUB = 'MLA9332983101'
GTIN = '4717480160907'


@tagged('post_install', '-at_install', 'meli', 'meli_binding_prio')
class TestBindingPrioridad(TransactionCase):

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
        try:
            self.account = self.env['mercadolibre.account'].search([], limit=1) \
                or self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("no se pudo obtener una mercadolibre.account: %s" % e)
        Product = self.env['product.product']
        self.pizarra = Product.create({'name': 'Pizarra (test 634)', 'default_code': 'TK70-PIZ', 'barcode': GTIN})
        self.kit = Product.create({'name': 'Combo pizarra + marcadores (test 634)', 'default_code': 'TK70-PIZ_COM'})
        self.otro = Product.create({'name': 'Otro (test 634)', 'default_code': 'TK70-OTRO'})
        self.ml = {'sku': 'TK70-PIZ', 'barcode': GTIN}
        acc_cls = type(self.account)
        for meth, fn in (
            ('fetch_meli_product', lambda s, **kw: {'id': kw.get('meli_id'),
                                                    'official_store_id': s.official_store_id}),
            ('fetch_meli_sku', lambda s, **kw: self.ml['sku']),
            ('fetch_meli_barcode', lambda s, **kw: self.ml['barcode']),
        ):
            pm = patch.object(acc_cls, meth, fn, create=True)
            pm.start()
            self.addCleanup(pm.stop)
        # El camino por SKU re-vincula el producto encontrado: se registra, sin red.
        self.rebinds = []
        pb = patch.object(type(Product), 'mercadolibre_bind_to',
                          lambda s, *a, **kw: self.rebinds.append(s) or s.env['mercadolibre.product'])
        pb.start()
        self.addCleanup(pb.stop)
        pc = patch(SALE_MOD + '.meli_config_account', lambda config, fallback=None: self.account)
        pc.start()
        self.addCleanup(pc.stop)

    def _bind(self, product, variation=False):
        return self.env['mercadolibre.product'].create({
            'name': product.name,
            'connection_account': self.account.id,
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'conn_id': PUB,
            'conn_variation_id': variation,
        })

    def _search(self, variation=False):
        item = {'id': PUB, 'variation_id': variation, 'seller_sku': None}
        return self.env['mercadolibre.orders'].search_meli_product(meli=None, meli_item=item, config=self.env.company)

    # -------------------------------------------------------------- import de ventas
    def test_binding_gana_sobre_gtin_y_sku(self):
        """EL caso #caso-K70: binding -> kit; ML trae GTIN y SKU de la pizarra => entra el KIT."""
        self._bind(self.kit)
        from odoo.addons.meli_oerp_multiple.models import sale as sale_mod
        with patch.object(sale_mod._logger, 'info') as log_info:
            self.assertEqual(self._search(), self.kit)
        self.assertTrue(any('se respeta la vinculacion' in str(c.args[0]) for c in log_info.call_args_list),
                        log_info.call_args_list)
        self.assertFalse(self.rebinds, "no tiene que re-vincular la publicacion a otro producto")

    def test_binding_gana_sin_gtin(self):
        self._bind(self.kit)
        self.ml['barcode'] = False
        self.assertEqual(self._search(), self.kit)

    def test_binding_que_coincide_sigue_igual(self):
        self._bind(self.pizarra)
        self.assertEqual(self._search(), self.pizarra)

    def test_sin_binding_gtin_sku_siguen_resolviendo(self):
        """Clientes sin vinculacion: el SKU de ML sigue siendo el unico vinculo (sin cambio)."""
        self.assertEqual(self._search(), self.pizarra)

    def test_variacion_exacta_gana(self):
        self._bind(self.kit, variation='111')
        self.assertEqual(self._search(variation='111'), self.kit)

    def test_binding_de_otra_variacion_no_gana(self):
        """Solo hay binding de OTRA variacion: el fallback por conn_id se sigue verificando por SKU."""
        self._bind(self.kit, variation='111')
        self.assertEqual(self._search(variation='222'), self.pizarra)

    def test_binding_ambiguo_no_gana(self):
        """Publicacion sin variacion vinculada a DOS productos: decide la heuristica, como antes."""
        self._bind(self.kit)
        self._bind(self.otro)
        self.assertEqual(self._search(), self.pizarra)

    # -------------------------------------------------------------- «Vincular» avisa
    def test_vincular_sin_variante_vinculada_avisa(self):
        from odoo.addons.meli_oerp_multiple.models.wizards import _binder_variant_check
        self._bind(self.pizarra)
        msg = _binder_variant_check(self.env, self.kit.product_tmpl_id, self.account, PUB)
        self.assertIn('TK70-PIZ_COM', msg)
        self.assertIn(self.pizarra.display_name, msg, "tiene que decir a que producto esta vinculada hoy")
        self._bind(self.kit)
        self.assertEqual(_binder_variant_check(self.env, self.kit.product_tmpl_id, self.account, PUB), '')

    def test_wizard_plantilla_no_dice_creada_si_la_variante_no_quedo(self):
        """El bind de plantilla devuelve el binding de PLANTILLA aunque la variante se haya salteado:
        antes el asistente decia 'Vinculacion creada' (success)."""
        tmpl = self.kit.product_tmpl_id
        pt_bind = self.env['mercadolibre.product_template'].create({
            'name': tmpl.name, 'connection_account': self.account.id,
            'product_tmpl_id': tmpl.id, 'conn_id': PUB})
        wiz = self.env['mercadolibre.binder.wiz'].create({
            'meli_id': PUB, 'connectors': [(6, 0, self.account.ids)]})
        with patch.object(type(tmpl), 'mercadolibre_bind_to', lambda s, *a, **kw: pt_bind):
            res = wiz.with_context(active_ids=[tmpl.id]).product_template_add_to_connector()
        self.assertEqual(res['params']['type'], 'danger')
        self.assertIn('TK70-PIZ_COM', res['params']['message'])
