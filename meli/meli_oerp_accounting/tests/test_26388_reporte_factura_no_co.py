# -*- coding: utf-8 -*-
"""26.388 (caso-K80 cliente E1 #caso-K79, UY): fuera de Colombia, `orders_post_invoice` llamaba
`inv.crear_facturas()` SIN config, asi que el "Reporte de factura" elegido en la configuracion
(`mercadolibre_invoice_journal_report_id`, en res.company o en mercadolibre.configuration de la cuenta)
se ignoraba y el PDF que subia a ML salia con el reporte estandar `account.account_invoices`.
La unica rama que pasaba config exige estado_dian/zipped_file (l10n_co_cei). 16.0 lo corrigio en 26.45
(#caso-K34 cliente D, 7c8832d) y nunca se porto a 17+.

Sin red: `report_render` registra el reporte que se renderiza y `meli` es un doble que registra el upload.
`crear_facturas` corre de verdad (es la decision del reporte lo que se mide).

Correr:  odoo-bin ... -i meli_oerp_accounting --test-enable --test-tags meli_26388 --stop-after-init
"""
import base64
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

_INV_MOD = 'odoo.addons.meli_oerp_accounting.models.invoice'


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _Meli:
    access_token = 'TEST'

    def __init__(self):
        self.calls = []

    def uploadfiles(self, path, files=None, params=None):
        self.calls.append(('upload', path, [f[1][0] for f in (files or [])]))
        return _Resp({'pack_id': 1, 'fiscal_documents': [{'id': 'x', 'filename': files[0][1][0]}]})

    def __getattr__(self, name):  # cualquier otra llamada de red es un error del test
        raise AssertionError("llamada inesperada a meli.%s" % name)


@tagged('post_install', '-at_install', 'meli_26388')
class TestReporteFacturaNoColombia(TransactionCase):

    def setUp(self):
        super().setUp()
        co = self.env.company
        if 'mercadolibre_post_invoice' in co._fields:
            co.mercadolibre_post_invoice = True
        partner = self.env['res.partner'].create({'name': 'Comprador ML (408)'})
        Product = self.env['product.product']
        pvals = {'name': 'Producto ML 408', 'list_price': 100.0, 'invoice_policy': 'order'}
        pvals['detailed_type' if 'detailed_type' in Product._fields else 'type'] = 'service'
        product = Product.create(pvals)
        line_tax = 'tax_id' if 'tax_id' in self.env['sale.order.line']._fields else 'tax_ids'
        self.so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1, 'price_unit': 100.0,
                                   line_tax: [(6, 0, [])]})],
        })
        self.so.action_confirm()
        self.mo = self.env['mercadolibre.orders'].create({
            'order_id': '2000004441550313', 'pack_id': '2000400201603932', 'sale_order': self.so.id,
        })
        # 16.0 sin plan de cuentas no tiene diario de ventas: se arma uno minimo.
        if not self.env['account.journal'].search([('type', '=', 'sale'), ('company_id', '=', co.id)], limit=1):
            income = self.env['account.account'].create({
                'name': 'Ventas 408', 'code': '408001', 'account_type': 'income', 'company_id': co.id})
            self.env['account.account'].create({
                'name': 'Deudores 408', 'code': '408002', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_id': co.id})
            self.env['account.journal'].create({
                'name': 'Ventas 408', 'code': 'VK80', 'type': 'sale', 'company_id': co.id,
                'default_account_id': income.id})
        invs = self.so._create_invoices()
        # 18+: un borrador nace con name=False y crear_facturas arma el nombre del PDF con
        # `self.name or self.number` (number no existe desde 16). En prod se sube publicada; aca
        # se le da nombre sin publicar (publicar en 16 sin plan de cuentas no es posible).
        for inv in invs:
            if not inv.name:
                inv.name = 'INV/%s/00408' % fields.Date.today().year
        self.estandar = self.env.ref('account.account_invoices')
        self.fiscal = self.estandar.copy({'name': 'Factura fiscal 408'})
        self.rendered = []

        def _render(report, res_ids=None, data=None):
            self.rendered.append(report.id)
            return (b'%PDF-1.4 408', 'pdf')

        p = patch(_INV_MOD + '.report_render', _render)
        p.start()
        self.addCleanup(p.stop)

    def _post(self, config):
        meli = _Meli()
        self.mo.orders_post_invoice(meli=meli, config=config)
        self.assertTrue(any(c[0] == 'upload' for c in meli.calls), "no subio nada a ML")
        return meli

    def test_1_compania_reporte_configurado_se_usa(self):
        """El caso 408: config = compania con 'Reporte de factura' elegido => ese reporte, no el estandar."""
        co = self.env.company
        co.mercadolibre_invoice_journal_report_id = self.fiscal
        self._post(co)
        self.assertEqual(self.rendered, [self.fiscal.id],
                         "fuera de Colombia se ignoro el reporte configurado (salio %s)" %
                         self.env['ir.actions.report'].browse(self.rendered).mapped('name'))

    def test_2_configuracion_de_la_cuenta_de_la_orden_se_usa(self):
        """Multiple: sin config explicita, la config sale de la cuenta de la orden (connection_account)
        y su 'Reporte de factura' es el que se usa."""
        env = self.env
        if 'mercadolibre.account' not in env or 'connection_account' not in self.mo._fields:
            self.skipTest('sin meli_oerp_multiple')
        wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
        pl = env['product.pricelist'].search([], limit=1) or env['product.pricelist'].create({'name': 'PK80'})
        cvals = {'name': 'CK80', 'mode': 'test', 'company_id': env.company.id, 'mercadolibre_pricelist': pl.id,
                 'mercadolibre_buying_mode': 'buy_it_now', 'mercadolibre_currency': 'UYU',
                 'mercadolibre_stock_warehouse': wh.id, 'mercadolibre_stock_warehouse_full': wh.id,
                 'mercadolibre_listing_type': 'gold_special'}
        Conf = env['mercadolibre.configuration']
        conf = Conf.create({k: v for k, v in cvals.items() if k in Conf._fields})
        account = env['mercadolibre.account'].create({
            'name': 'AK80', 'type': 'custom', 'company_id': env.company.id, 'configuration': conf.id,
            'country_id': env.ref('base.uy').id, 'meli_login_id': 'AK80', 'client_id': 'AK80',
            'secret_key': 'x', 'seller_id': '408408', 'redirect_uri': 'http://localhost/meli_login'})
        conf.mercadolibre_invoice_journal_report_id = self.fiscal
        # la compania NO tiene reporte: si sale el fiscal, vino de la cuenta de la orden
        env.company.mercadolibre_invoice_journal_report_id = False
        self.mo.connection_account = account
        meli = _Meli()
        self.mo.orders_post_invoice(meli=meli, config=None)
        self.assertTrue(any(c[0] == 'upload' for c in meli.calls), "no subio nada a ML")
        self.assertEqual(self.rendered, [self.fiscal.id],
                         "no se uso el reporte de la configuracion de la cuenta (salio %s)" %
                         env['ir.actions.report'].browse(self.rendered).mapped('name'))

    def test_3_sin_reporte_configurado_cae_al_estandar(self):
        """Guarda: sin reporte elegido sigue saliendo el estandar (no se rompe el default)."""
        co = self.env.company
        co.mercadolibre_invoice_journal_report_id = False
        self._post(co)
        self.assertEqual(self.rendered, [self.estandar.id])
