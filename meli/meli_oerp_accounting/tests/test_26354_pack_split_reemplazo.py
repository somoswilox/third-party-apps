# -*- coding: utf-8 -*-
"""26.354 (caso-K52 cliente X, 2-nov-2026): reemplazo de un pack dividido por ML => no doble factura.

ML canceló 3 órdenes con cancel_detail internal/pack_splitted/meli y las re-creó con otro número
(mismo comprador, ítem MLA2231281162, 68.890, segundos después, tag `splitted_order`). Las originales
ya tenían factura publicada (CAE) y el reemplazo se facturó encima => doble factura al mismo comprador.

Casos reales (original -> reemplazo):
    2000943282592071 -> 2000494514158496
    2000332843537930 -> 2000443231111575
    2000315470262033 -> 2000470648571032

Se mide: meli_create_invoice del reemplazo NO crea factura y deja UNA actividad nombrando la factura
original; con NC publicada sobre la original factura normal; un comprador recurrente sin pack_splitted
factura normal; la carrera (la original todavía no figura cancelada) difiere y a las 24 h pide revisión;
nunca se crea una nota de crédito automática.

Correr:  odoo-bin ... -i meli_oerp_accounting --test-enable --test-tags /meli_oerp_accounting:TestPackSplitReemplazo --stop-after-init
"""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

ITEM = "MLA2231281162"
AMOUNT = 68890.0
CASES = [
    ("2000943282592071", "2000494514158496", "202800992"),
    ("2000332843537930", "2000443231111575", "47381496"),
    ("2000315470262033", "2000470648571032", "166078168"),
]
SUMMARY = "Factura: venta de reemplazo de un pack dividido"


@tagged("post_install", "-at_install", "meli_26354")
class TestPackSplitReemplazo(TransactionCase):

    def setUp(self):
        super().setUp()
        self.SO = self.env["sale.order"]
        co = self.env.company
        self.journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", co.id)], limit=1)
        if not self.journal:
            self.skipTest("sin diario de ventas en esta base")
        if "mercadolibre_invoice_journal_id" in co._fields:
            co.mercadolibre_invoice_journal_id = self.journal
        if "mercadolibre_notification_mode" in co._fields:
            co.mercadolibre_notification_mode = "internal_note"
        Product = self.env["product.product"]
        pvals = {"name": "Nescafé 1 kg", "list_price": AMOUNT, "invoice_policy": "order"}
        pvals["detailed_type" if "detailed_type" in Product._fields else "type"] = "service"
        self.product = Product.create(pvals)
        p = patch.object(self.env.cr, "commit", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        cls = type(self.SO)
        for name, fn in (
            ("_meli_invoice_conditions", lambda s, meli=None, config=None: True),
            ("meli_amount_to_invoice", lambda s, meli=None, config=None: s.amount_total),
        ):
            p = patch.object(cls, name, fn)
            p.start()
            self.addCleanup(p.stop)

    # -------------------------------------------------------------- helpers --
    def _buyer(self, bid):
        return self.env["mercadolibre.buyers"].create({"name": "Comprador %s" % bid, "buyer_id": bid})

    def _so(self, oid, status, partner):
        tax_f = "tax_id" if "tax_id" in self.env["sale.order.line"]._fields else "tax_ids"
        so = self.SO.create({
            "partner_id": partner.id, "meli_order_id": oid, "meli_status": status,
            "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 1,
                                   "price_unit": AMOUNT, tax_f: [(6, 0, [])]})],
        })
        so.action_confirm()
        return so

    def _mo(self, so, oid, buyer, status, date, tags="['paid']", item=ITEM):
        mo = self.env["mercadolibre.orders"].create({
            "order_id": oid, "pack_id": "P" + oid, "status": status, "buyer": buyer.id,
            "date_created": date, "sale_order": so.id, "tags": tags})
        self.env["mercadolibre.order_items"].create({"order_id": mo.id, "order_item_id": item})
        so.meli_orders = [(6, 0, mo.ids)]
        return mo

    def _invoice(self, so):
        inv = so._create_invoices()
        inv.action_post()
        self.assertEqual(inv.state, "posted")
        return inv

    def _pair(self, orig_id, repl_id, bid, code="pack_splitted", orig_cancelled=True,
              repl_date=None, repl_tags="['splitted_order', 'paid']"):
        buyer = self._buyer(bid)
        partner = self.env["res.partner"].create({"name": "Comprador ML %s" % bid})
        repl_date = repl_date or fields.Datetime.to_datetime("2026-11-01 19:53:30")
        orig = self._so(orig_id, "cancelled" if orig_cancelled else "paid", partner)
        self._mo(orig, orig_id, buyer, "cancelled" if orig_cancelled else "paid", repl_date - timedelta(hours=6))
        inv = self._invoice(orig)
        if orig_cancelled:
            orig.write({"meli_cancel_reason_code": code,
                        "meli_status_detail": "internal / %s / meli" % code,
                        "meli_cancel_date": repl_date - timedelta(seconds=20)})
        repl = self._so(repl_id, "paid", partner)
        self._mo(repl, repl_id, buyer, "paid", repl_date, tags=repl_tags)
        return orig, inv, repl

    def _invoice_repl(self, repl, **ctx):
        return repl.with_context(invoice_force=True, **ctx).meli_create_invoice(config=self.env.company)

    def _activity(self, so):
        return so.activity_ids.filtered(lambda a: a.summary == SUMMARY)

    def _refunds(self):
        return self.env["account.move"].search_count([("move_type", "=", "out_refund")])

    # ---------------------------------------------------------------- casos --
    def test_tres_casos_reales_no_doble_factura(self):
        refunds0 = self._refunds()
        for orig_id, repl_id, bid in CASES:
            orig, inv, repl = self._pair(orig_id, repl_id, bid)
            res = self._invoice_repl(repl)
            self.assertEqual(res, {"skipped": "meli_pack_split_twin"}, repl_id)
            self.assertFalse(repl.invoice_ids, "%s: el reemplazo no se factura" % repl_id)
            act = self._activity(repl)
            self.assertEqual(len(act), 1, repl_id)
            self.assertIn(inv.name, act.note)
            self.assertIn(orig.name, act.note)
            # Segunda pasada del cron: no duplica la actividad.
            self._invoice_repl(repl)
            self.assertEqual(len(self._activity(repl)), 1)
            self.assertEqual(inv.state, "posted", "la factura original no se toca")
        self.assertEqual(self._refunds(), refunds0, "nunca nota de crédito automática")

    def test_click_manual_avisa_con_userError(self):
        orig, inv, repl = self._pair(*CASES[0])
        with self.assertRaises(UserError):
            repl.with_context(invoice_force=True, source="manual_click").meli_create_invoice(config=self.env.company)
        self.assertFalse(repl.invoice_ids)

    def test_original_con_nota_de_credito_factura_el_reemplazo(self):
        orig, inv, repl = self._pair(*CASES[1])
        inv._reverse_moves(cancel=True)
        self.assertTrue(orig._meli_unresolved_posted_invoices() == self.env["account.move"])
        self.assertIsNone(repl._meli_pack_split_invoice_block())
        self._invoice_repl(repl)
        self.assertTrue(repl.invoice_ids, "con la original revertida, el reemplazo se factura")
        self.assertFalse(self._activity(repl))

    def test_recurrente_sin_pack_splitted_factura(self):
        # Mismo comprador e ítem, la anterior cancelada por OTRO motivo y sin tag splitted_order.
        orig, inv, repl = self._pair(*CASES[2], code="buyer_cancel_express", repl_tags="['paid']")
        self.assertIsNone(repl._meli_pack_split_invoice_block())
        self._invoice_repl(repl)
        self.assertTrue(repl.invoice_ids)
        self.assertFalse(self._activity(repl))

    def test_recurrente_anterior_viva_sin_tag_factura(self):
        orig, inv, repl = self._pair(*CASES[2], orig_cancelled=False, repl_tags="['paid']")
        self.assertIsNone(repl._meli_pack_split_invoice_block())

    def test_carrera_original_aun_no_cancelada_difiere_una_pasada(self):
        now = fields.Datetime.now()
        orig, inv, repl = self._pair(*CASES[0], orig_cancelled=False, repl_date=now - timedelta(hours=1))
        res = self._invoice_repl(repl)
        self.assertEqual(res, {"skipped": "meli_pack_split_wait"})
        self.assertFalse(repl.invoice_ids)
        self.assertFalse(self._activity(repl), "dentro de la ventana sólo se difiere")
        # Llega la cancelación de la original: ahora es el caso gemela.
        orig.write({"meli_status": "cancelled", "meli_cancel_reason_code": "pack_splitted",
                    "meli_cancel_date": now - timedelta(hours=1, seconds=20)})
        orig.meli_orders.status = "cancelled"
        self.assertEqual(self._invoice_repl(repl), {"skipped": "meli_pack_split_twin"})
        self.assertEqual(len(self._activity(repl)), 1)

    def test_carrera_vencida_pide_revision(self):
        now = fields.Datetime.now()
        orig, inv, repl = self._pair(*CASES[1], orig_cancelled=False, repl_date=now - timedelta(hours=30))
        self.assertEqual(self._invoice_repl(repl), {"skipped": "meli_pack_split_wait"})
        self.assertFalse(repl.invoice_ids)
        self.assertEqual(len(self._activity(repl)), 1)
        self.assertIn(inv.name, self._activity(repl).note)
