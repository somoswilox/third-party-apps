# -*- coding: utf-8 -*-
"""#caso-K44 (caso-K21 cliente F, 23-oct-2026; al source en 26.299): `orders_get_invoice` marcaba `invoice_posted=True`
aunque GET /packs/<id>/fiscal_documents devolviera la lista VACIA (`{"fiscal_documents": []}`).
Despues `orders_post_invoice` salteaba la venta como "ya enviada" y la factura nunca subia a ML
(venta 6708 / ML 2000125044459320, FA-B 00029-00000184).

Ahora `invoice_posted` sale True solo si ML devuelve al menos un documento, y `orders_post_invoice`
solo lo marca con respuesta de ML. Sin red: `meli` es un doble que registra las llamadas.

Correr:  odoo-bin ... -u meli_oerp_accounting --test-enable --test-tags meli_K44_posted_vacio --stop-after-init
"""
import base64
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _Meli:
    """Doble de meli.util: GET devuelve `get_data`, uploadfiles devuelve `upload_res`."""
    access_token = 'TEST'

    def __init__(self, get_data=None, upload_res='ok'):
        self.get_data = get_data
        self.upload_res = upload_res
        self.calls = []

    def get(self, path, params=None, **kw):
        self.calls.append(('get', path))
        return _Resp(self.get_data)

    def uploadfiles(self, path, files=None, params=None):
        self.calls.append(('upload', path))
        if self.upload_res == 'ok':
            return _Resp({'pack_id': 1, 'fiscal_documents': [{'id': 'x', 'filename': files[0][1][0]}]})
        return self.upload_res

    def __getattr__(self, name):  # cualquier otra llamada de red es un error del test
        raise AssertionError("llamada inesperada a meli.%s" % name)


@tagged('post_install', '-at_install', 'meli_K44_posted_vacio')
class TestInvoicePostedVacio650(TransactionCase):

    def setUp(self):
        super().setUp()
        co = self.env.company
        if 'mercadolibre_post_invoice' in co._fields:
            co.mercadolibre_post_invoice = True
        partner = self.env['res.partner'].create({'name': 'Comprador ML (650)'})
        Product = self.env['product.product']
        pvals = {'name': 'Producto ML 650', 'list_price': 100.0, 'invoice_policy': 'order'}
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
            'order_id': '2000054136544039', 'pack_id': '2000792625432529', 'sale_order': self.so.id,
        })
        self.config = co
        # 16.0 sin plan de cuentas no tiene diario de ventas: se arma uno minimo (17+ ya trae el generico).
        if not self.env['account.journal'].search([('type', '=', 'sale'), ('company_id', '=', co.id)], limit=1):
            income = self.env['account.account'].create({
                'name': 'Ventas 650', 'code': '650001', 'account_type': 'income', 'company_id': co.id})
            self.env['account.account'].create({
                'name': 'Deudores 650', 'code': '650002', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_id': co.id})
            self.env['account.journal'].create({
                'name': 'Ventas 650', 'code': 'VK44', 'type': 'sale', 'company_id': co.id,
                'default_account_id': income.id})
        # Un PDF fijo: lo que se mide es la decision sobre invoice_posted, no la generacion del PDF.
        pdf = base64.b64encode(b'%PDF-1.4 650')
        p = patch.object(type(self.env['account.move']), 'crear_facturas',
                         lambda s, config=None: (None, None, 'FAB0002900000184.pdf', pdf))
        p.start()
        self.addCleanup(p.stop)

    def _get(self, data):
        meli = _Meli(get_data=data)
        self.mo.orders_get_invoice(meli=meli, config=self.config)
        return meli

    def test_lista_vacia_no_es_enviada(self):
        self._get({'pack_id': 2000792625432529, 'fiscal_documents': []})
        self.assertFalse(self.mo.invoice_posted)

    def test_con_documento_es_enviada(self):
        self._get({'pack_id': 2000792625432529, 'fiscal_documents': [
            {'id': 'ee51', 'filename': 'fab0002900000183.pdf', 'file_type': 'application/pdf'}]})
        self.assertTrue(self.mo.invoice_posted)

    def test_error_no_es_enviada(self):
        with self.assertLogs('odoo.addons.meli_oerp_accounting.models.invoice', level='ERROR'):
            self._get({'error': 'not_found', 'status': 404, 'message': 'pack not found'})
        self.assertFalse(self.mo.invoice_posted)

    def test_vacia_luego_post_sube_la_factura(self):
        """El caso 6708: GET vacio y despues orders_post_invoice TIENE que subir el PDF."""
        self.so._create_invoices()
        self._get({'pack_id': 2000792625432529, 'fiscal_documents': []})
        meli = _Meli(upload_res='ok')
        self.mo.orders_post_invoice(meli=meli, config=self.config)
        self.assertIn(('upload', '/packs/2000792625432529/fiscal_documents'), meli.calls)
        self.assertTrue(self.mo.invoice_posted)

    def test_post_sin_respuesta_no_es_enviada(self):
        self.so._create_invoices()
        meli = _Meli(upload_res=None)
        self.mo.orders_post_invoice(meli=meli, config=self.config)
        self.assertIn(('upload', '/packs/2000792625432529/fiscal_documents'), meli.calls)
        self.assertFalse(self.mo.invoice_posted)
