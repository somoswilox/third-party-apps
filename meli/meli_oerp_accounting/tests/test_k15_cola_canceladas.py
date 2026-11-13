# -*- coding: utf-8 -*-
"""#caso-K15 (cliente E, 6-oct-2026; al source en 26.281): una factura CANCELADA que nunca se autorizo
(sin CAE, sin numero, nunca posteada) frenaba meli_create_invoice en silencio (`return {}`),
y la venta quedaba sin facturar (SO 9132/9818).

Ahora esa cancelada no cuenta: se crea la factura nueva. Si la cancelada SI tuvo numero/CAE o
fue posteada antes, se sigue frenando (riesgo de duplicar ante AFIP) pero con el motivo en el chatter.

Borde 16.0/17.0: el PRIMER borrador del periodo en un diario sin documentos LATAM ya recibe numero
(account.move._compute_name -> _set_next_sequence). El predicado lo trata como "tuvo numero" y sigue
frenando, con motivo (conservador). Por eso el setUp emite antes una factura: con historia en el diario
el borrador queda en '/', igual que en 18/19 y que en los diarios AR con documentos.

Correr:  odoo-bin ... -u meli_oerp_accounting --test-enable --test-tags meli_K15_cola_canceladas --stop-after-init
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'meli_K15_cola_canceladas')
class TestColaIgnoraCanceladasK15(TransactionCase):

    def setUp(self):
        super().setUp()
        SO = self.env['sale.order']
        self.partner = self.env['res.partner'].create({'name': 'Comprador ML (K15 canceladas)'})
        pvals = {'name': 'Producto ML K15', 'list_price': 100.0, 'invoice_policy': 'order'}
        Product = self.env['product.product']
        pvals['detailed_type' if 'detailed_type' in Product._fields else 'type'] = 'service'
        self.product = Product.create(pvals)
        self.so = SO.create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100.0,
                                   'tax_id' if 'tax_id' in self.env['sale.order.line']._fields else 'tax_ids': [(6, 0, [])]})],
        })
        self.so.action_confirm()
        co = self.env.company
        sale_journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', co.id)], limit=1)
        if not sale_journal:
            self.skipTest("sin diario de ventas en esta base")
        if 'mercadolibre_invoice_journal_id' in co._fields:
            co.mercadolibre_invoice_journal_id = sale_journal
        # 16/17 no bloquean cr.commit() dentro de un test (18/19 si): el commit post-CAE de
        # meli_create_invoice destruiria el savepoint del test.
        p = patch.object(self.env.cr, 'commit', lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        # Historia en el diario (ver docstring): una factura previa ya emitida.
        prev = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id, 'journal_id': sale_journal.id,
            'invoice_line_ids': [(0, 0, {'name': 'Previa', 'quantity': 1, 'price_unit': 10.0, 'tax_ids': [(6, 0, [])]})],
        })
        prev.action_post()
        # Ni red ni conciliacion de montos con ML: lo que se mide es la decision sobre las facturas.
        cls = type(SO)
        for name, fn in (
            ('_meli_invoice_conditions', lambda s, meli=None, config=None: True),
            ('meli_amount_to_invoice', lambda s, meli=None, config=None: s.amount_total),
            ('_meli_invoice_blocked_cancelled', lambda s: False),
        ):
            p = patch.object(cls, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def _cancelada(self, authorized):
        inv = self.so._create_invoices()
        if authorized:
            inv.action_post()
            inv.button_draft()
        inv.button_cancel()
        self.assertEqual(inv.state, 'cancel')
        return inv

    def _facturar(self):
        return self.so.with_context(invoice_force=True).meli_create_invoice(config=self.env.company)

    def _vivas(self):
        return self.so.invoice_ids.filtered(lambda i: i.state != 'cancel')

    # ---------------------------------------------------------------- predicado --
    def test_predicado(self):
        SO = self.env['sale.order']
        nunca = self._cancelada(authorized=False)
        self.assertTrue(SO._meli_invoice_cancelled_never_authorized(nunca))
        posteada = self._cancelada(authorized=True)
        self.assertTrue(posteada.posted_before)
        self.assertFalse(SO._meli_invoice_cancelled_never_authorized(posteada),
                         "posteada antes (tiene numero): no se ignora")
        viva = self.so._create_invoices()
        self.assertFalse(SO._meli_invoice_cancelled_never_authorized(viva), "borrador: no es cancelada")
        viva.action_post()
        self.assertFalse(SO._meli_invoice_cancelled_never_authorized(viva), "publicada: no es cancelada")

    # ---------------------------------------------------------------- integral --
    def test_cancelada_nunca_autorizada_no_frena(self):
        nunca = self._cancelada(authorized=False)
        res = self._facturar()
        self.assertNotEqual(res, {}, "la cancelada sin CAE/numero no debe frenar la facturacion")
        nuevas = self._vivas()
        self.assertEqual(len(nuevas), 1, "se crea la factura nueva")
        self.assertNotIn(nunca, nuevas)

    def test_cancelada_con_numero_frena_con_motivo(self):
        posteada = self._cancelada(authorized=True)
        with self.assertLogs('odoo.addons.meli_oerp_accounting.models.order', level='ERROR'):
            res = self._facturar()
        self.assertEqual(res, {}, "una cancelada que tuvo numero sigue frenando (duplicado AFIP)")
        self.assertFalse(self._vivas(), "no se crea otra factura")
        bodies = ' '.join(self.so.message_ids.mapped(lambda m: str(m.body)))
        self.assertIn('No se factura', bodies, "el motivo concreto queda en el chatter de la venta")
        self.assertIn(str(posteada.id), bodies)

    def test_control_sin_facturas_factura(self):
        # Control positivo (pasa con y sin el fix).
        res = self._facturar()
        self.assertNotEqual(res, {})
        self.assertEqual(len(self._vivas()), 1)
