# -*- coding: utf-8 -*-
"""#caso-K20: al importar una publicacion con oferta activa, la lista de precios toma
`original_price` (precio de lista) y no `price` (precio con descuento).

ML con una oferta/campana activa devuelve en `price` el precio rebajado y en
`original_price` el de lista. Antes product_meli_get_product copiaba `price` a la
lista de precios de ML ⇒ Odoo quedaba con el precio de oferta como precio normal.
El `meli_price` (lo publicado hoy en ML) sigue siendo `price`: publicar el de lista
sobre un item con campana podria levantar la promocion.

Sin red: `requests` queda bloqueado (cualquier llamada falla el test) y el objeto
`meli` es un doble que registra todo; ninguna escritura puede salir a ML.
"""

from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


class _Resp:
    status_code = 200

    def json(self):
        return {}


class _FakeMeli:
    """Doble de meli.util: registra cada llamada y nunca sale a la red."""

    access_token = 'TEST'

    def __init__(self):
        self.calls = []

    def get(self, path, params=None, *a, **kw):
        self.calls.append(('GET', path))
        return _Resp()

    def post(self, path, body=None, params=None, *a, **kw):
        self.calls.append(('POST', path))
        return _Resp()

    def put(self, path, body=None, params=None, *a, **kw):
        self.calls.append(('PUT', path))
        return _Resp()

    def delete(self, path, params=None, *a, **kw):
        self.calls.append(('DELETE', path))
        return _Resp()


@tagged('post_install', '-at_install', 'meli_K20_precio')
class TestPrecioOriginalAlImportar(TransactionCase):

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
        self.red = []
        test = self

        def _sin_red(*a, **kw):
            test.red.append((a[1:3] if len(a) > 2 else a, kw.get('url')))
            raise AssertionError("llamada de red a ML en un test")
        for target in ('requests.Session.request', 'requests.api.request'):
            p = patch(target, side_effect=_sin_red)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(type(self.env['meli.util']), 'get_new_instance',
                         side_effect=AssertionError("get_new_instance en un test"))
        p.start()
        self.addCleanup(p.stop)
        try:
            self.conf = self._crear_minimo('mercadolibre.configuration')
            self.account = self._crear_minimo('mercadolibre.account')
        except Exception as e:
            self.skipTest("No se pudo armar cuenta/configuracion en esta base: %s" % e)
        self.pl = self.env['product.pricelist'].create({
            'name': 'ML K20', 'currency_id': self.env.company.currency_id.id})
        self.conf.write({'mercadolibre_pricelist': self.pl.id,
                         'mercadolibre_tax_included': 'tax_included'})
        # _crear_minimo toma la PRIMERA compania para el many2one: en una base con demo
        # multi-compania no es env.company y los impuestos de la prueba quedan fuera de la config.
        if 'company_id' in self.conf._fields:
            self.conf.company_id = self.env.company
        self.account.write({'configuration': self.conf.id, 'company_id': self.env.company.id})
        self.meli = _FakeMeli()

    def _rjson(self, price, original_price, variations=None, mid='MLA1011189516'):
        return {
            'id': mid, 'title': 'TK20 %s' % mid, 'category_id': 'MLA1000',
            'price': price, 'original_price': original_price, 'base_price': price,
            'currency_id': 'ARS', 'listing_type_id': 'gold_special', 'buying_mode': 'buy_it_now',
            'condition': 'new', 'available_quantity': 3, 'warranty': '', 'thumbnail': '',
            'permalink': '', 'pictures': [], 'attributes': [], 'status': 'active',
            'variations': variations or [], 'seller_custom_field': None, 'shipping': {},
            'sale_terms': [], 'tags': [],
        }

    def _importar(self, rjson, taxes=None):
        tmpl = self.env['product.template'].create({
            'name': 'TK20 plantilla', 'list_price': 1.0,
            'taxes_id': [(6, 0, taxes.ids if taxes else [])]})
        prod = tmpl.product_variant_ids[:1]
        try:
            # la categoria (atributos/chart) no es objeto de este test: sin red ni instancia real
            # falla adentro de su savepoint y se loguea como ERROR; se silencia ese logger.
            with mute_logger('odoo.addons.meli_oerp.models.category'):
                prod.product_meli_get_product(meli_id=rjson['id'], account=self.account,
                                              meli=self.meli, rjson=rjson, import_images=False)
        except AssertionError:
            raise
        except Exception:
            # lo posterior al precio (atributos, user_product, bindings) no es objeto de este test
            pass
        self.assertFalse(self.red, "hubo llamadas de red: %s" % self.red)
        self.assertFalse([c for c in self.meli.calls if c[0] != 'GET'],
                         "hubo escrituras hacia ML: %s" % self.meli.calls)
        items = self.env['product.pricelist.item'].search([
            ('pricelist_id', '=', self.pl.id), '|',
            ('product_tmpl_id', '=', tmpl.id), ('product_id', '=', prod.id)])
        return tmpl, prod, items

    def test_oferta_activa_toma_original_price(self):
        """MLA1050117037 (caso-K20): price 161405, original_price 169900 ⇒ lista 169900."""
        tmpl, prod, items = self._importar(self._rjson(161405, 169900))
        self.assertTrue(items, "no se creo la regla de precio")
        self.assertEqual(set(items.mapped('fixed_price')), {169900.0})
        # lo publicado en ML no se toca
        self.assertEqual(float(tmpl.meli_price or 0), 161405.0)

    def test_sin_oferta_toma_price(self):
        """000231 MLA1461093530 hoy: price 1899900, original_price None ⇒ 1899900."""
        tmpl, prod, items = self._importar(self._rjson(1899900, None, mid='MLA1245914321'))
        self.assertEqual(set(items.mapped('fixed_price')), {1899900.0})

    def test_original_menor_o_igual_no_se_usa(self):
        tmpl, prod, items = self._importar(self._rjson(47900, 47900, mid='MLA431534459'))
        self.assertEqual(set(items.mapped('fixed_price')), {47900.0})

    def test_con_variaciones_regla_de_plantilla(self):
        """>1 variacion ⇒ regla de plantilla, tambien con el precio de lista."""
        vars_ = [{'id': 1, 'price': 161405, 'attribute_combinations': [], 'available_quantity': 1},
                 {'id': 2, 'price': 161405, 'attribute_combinations': [], 'available_quantity': 1}]
        tmpl, prod, items = self._importar(self._rjson(161405, 169900, variations=vars_, mid='MLA443840262'))
        tpl_items = items.filtered(lambda i: i.product_tmpl_id == tmpl and not i.product_id)
        self.assertTrue(tpl_items, "no se creo la regla de plantilla")
        self.assertEqual(set(tpl_items.mapped('fixed_price')), {169900.0})

    def test_iva_excluido_netea_el_precio_de_lista(self):
        """Config tax_excluded + IVA 21 % ⇒ 169900 / 1,21 = 140413,22 (no 161405 / 1,21)."""
        try:
            with self.env.cr.savepoint():
                Tax = self.env['account.tax']
                tvals = {'name': 'IVA 21 TK20', 'amount': 21.0, 'amount_type': 'percent',
                         'type_tax_use': 'sale', 'company_id': self.env.company.id}
                if 'country_id' in Tax._fields:   # 16+: obligatorio en la tabla
                    tvals['country_id'] = (self.env.company.country_id or self.env.ref('base.ar')).id
                if 'price_include_override' in Tax._fields:   # 18+
                    tvals['price_include_override'] = 'tax_excluded'
                else:
                    tvals['price_include'] = False
                tax = Tax.create(tvals)
                self.assertFalse(tax.price_include)
        except Exception as e:
            self.skipTest("no se pudo crear el impuesto en esta base: %s" % e)
        self.conf.write({'mercadolibre_tax_included': 'tax_excluded'})
        tmpl, prod, items = self._importar(self._rjson(161405, 169900, mid='MLA464210643'), taxes=tax)
        self.assertTrue(items)
        for fp in items.mapped('fixed_price'):
            self.assertAlmostEqual(fp, 169900 / 1.21, places=2)
