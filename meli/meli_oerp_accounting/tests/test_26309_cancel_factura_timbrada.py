# -*- coding: utf-8 -*-
"""26.309 (#caso-K45 cliente S, MX): venta cancelada en ML con la factura YA TIMBRADA (CFDI).

Antes: `_meli_cancel_invoices` en modo 'cancel' llamaba `button_draft()`; el core lo rechaza
("You can't reset to draft those journal entries. You need to request a cancellation instead.")
=> ERROR + traceback + aviso SIN once_key en cada pasada y la venta quedaba aprobada sin marca.

Ahora: no se intenta borrador. La venta queda marcada (`meli_cancel_fiscal_review`), con UNA
actividad y UN aviso en el chatter, sin ERROR; la segunda pasada no repite nada. La solicitud de
cancelacion ante el SAT es opcional (`meli_oerp_accounting.mx_sat_cancel_request`, default off).

El banco es community (sin l10n_mx_edi): "CFDI timbrado" se simula con el hook del core que usa
l10n_mx_edi (`_need_cancel_request`, 17+; `_edi_allow_button_draft` de account_edi en 16) y un
`button_draft` que falla como en produccion.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

LOGGER = "odoo.addons.meli_oerp_accounting.models.order"
MSG_CORE = "You can't reset to draft those journal entries. You need to request a cancellation instead."


@tagged("post_install", "-at_install", "meli_26309")
class TestCancelFacturaTimbrada(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.co = cls.env.company
        cls.co.mercadolibre_invoice_cancel_mode = "cancel"
        if "mercadolibre_notification_mode" in cls.co._fields:
            cls.co.mercadolibre_notification_mode = "internal_note"
        cls.cust = cls.env["res.partner"].create({"name": "Comprador ML 26309"})
        Product = cls.env["product.product"]
        pvals = {"name": "P-26309", "list_price": 100.0, "invoice_policy": "order"}
        if "is_storable" in Product._fields:
            pvals.update(type="consu")
        elif "detailed_type" in Product._fields:
            pvals.update(detailed_type="consu")
        else:
            pvals.update(type="consu")
        cls.prod = Product.create(pvals)
        cls.Move = cls.env.registry["account.move"]
        if not cls.env["account.journal"].search([("type", "=", "sale"), ("company_id", "=", cls.co.id)], limit=1):
            cls.skipTest(cls, "sin diario de ventas en esta base (16.0 sin plan contable)")

    def _mkso(self, n):
        so = self.env["sale.order"].create({
            "partner_id": self.cust.id, "meli_order_id": "20000263090%02d" % n, "meli_status": "cancelled",
            "order_line": [(0, 0, {"product_id": self.prod.id, "product_uom_qty": 1, "price_unit": 100})]})
        so.action_confirm()
        inv = so._create_invoices()
        inv.action_post()
        return so, inv

    def _timbrada(self, stamped_ids):
        """Las facturas de `stamped_ids` se comportan como CFDI timbrado."""
        orig_draft = self.Move.button_draft

        def fake_draft(moves):
            if any(m.id in stamped_ids for m in moves):
                raise UserError(MSG_CORE)
            return orig_draft(moves)

        patches = [patch.object(self.Move, "button_draft", fake_draft)]
        if hasattr(self.Move, "_need_cancel_request"):
            orig_need = self.Move._need_cancel_request
            patches.append(patch.object(self.Move, "_need_cancel_request",
                                        lambda m: m.id in stamped_ids or orig_need(m)))
        else:  # 16.0: account_edi
            patches.append(patch.object(self.Move, "_edi_allow_button_draft",
                                        lambda m: m.id not in stamped_ids, create=True))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _acts(self, so):
        return self.env["mail.activity"].search([("res_model", "=", "sale.order"), ("res_id", "=", so.id)])

    def _avisos(self, so):
        return self.env["mail.message"].search([
            ("model", "=", "sale.order"), ("res_id", "=", so.id),
            ("body", "like", "meli-once:cancel-fiscal-review-")])

    def test_01_timbrada_no_draft_marca_revision_una_vez(self):
        so, inv = self._mkso(1)
        self._timbrada({inv.id})
        with self.assertLogs(LOGGER, level="WARNING") as cm:
            so._meli_cancel_invoices(config=self.co)
        self.assertFalse([l for l in cm.output if "ERROR" in l],
                         "no debe loguear ERROR por la factura timbrada: %s" % cm.output)
        self.assertTrue(any("MELI_CANCEL_FISCAL_REVIEW" in l for l in cm.output), cm.output)
        self.assertEqual(inv.state, "posted", "la factura timbrada NO se toca")
        self.assertTrue(so.meli_cancel_fiscal_review, "la venta queda marcada para revision")
        self.assertEqual(len(self._acts(so)), 1, "una actividad para resolverla")
        self.assertEqual(len(self._avisos(so)), 1, "un aviso en el chatter")
        # segunda y tercera pasada (cron / notificacion): silencio, nada nuevo
        with self.assertNoLogs(LOGGER, level="WARNING"):
            so._meli_cancel_invoices(config=self.co)
            so._meli_cancel_invoices(config=self.co)
        self.assertEqual(len(self._acts(so)), 1)
        self.assertEqual(len(self._avisos(so)), 1)
        self.assertEqual(inv.state, "posted")

    def test_02_modo_draft_tambien(self):
        so, inv = self._mkso(2)
        self._timbrada({inv.id})
        so._meli_cancel_invoices(config=self.co, mode="draft")
        self.assertEqual(inv.state, "posted")
        self.assertTrue(so.meli_cancel_fiscal_review)

    def test_03_sin_timbrar_se_cancela_como_antes(self):
        so, inv = self._mkso(3)
        self._timbrada(set())
        so._meli_cancel_invoices(config=self.co)
        self.assertEqual(inv.state, "cancel", "factura sin timbrar: modo cancel igual que siempre")
        self.assertFalse(so.meli_cancel_fiscal_review)
        self.assertFalse(self._acts(so))

    def test_04_pedido_sat_opcional_default_off(self):
        so, inv = self._mkso(4)
        self._timbrada({inv.id})
        calls = []
        with patch.object(type(so), "_meli_request_fiscal_cancel",
                          lambda s, i, config=None: calls.append(i.id) or True):
            so._meli_cancel_invoices(config=self.co)
            self.assertEqual(calls, [], "sin el parametro NO se pide nada al SAT")
            self.env["ir.config_parameter"].sudo().set_param("meli_oerp_accounting.mx_sat_cancel_request", "1")
            so._meli_cancel_invoices(config=self.co)
            self.assertEqual(calls, [inv.id], "con el parametro se pide la cancelacion de esa factura")

    def test_05_pedido_sat_sin_l10n_mx_no_hace_nada(self):
        so, inv = self._mkso(5)
        self.assertFalse(so._meli_request_fiscal_cancel(inv, config=self.co),
                         "sin l10n_mx_edi / sin UUID no hay a quien pedirle")

    def test_06_marca_se_limpia_cuando_se_resuelve(self):
        so, inv = self._mkso(6)
        stamped = {inv.id}
        self._timbrada(stamped)
        so._meli_cancel_invoices(config=self.co)
        self.assertTrue(so.meli_cancel_fiscal_review)
        stamped.clear()  # p.ej. el SAT acepto la cancelacion / ya no exige pedido
        so._meli_cancel_invoices(config=self.co)
        self.assertFalse(so.meli_cancel_fiscal_review)

    def test_07_dos_ventas_solo_la_timbrada_se_marca(self):
        so, inv = self._mkso(7)
        so2, inv2 = self._mkso(8)
        self._timbrada({inv.id})
        so._meli_cancel_invoices(config=self.co)
        so2._meli_cancel_invoices(config=self.co)
        self.assertEqual(inv.state, "posted")
        self.assertEqual(inv2.state, "cancel")
        self.assertTrue(so.meli_cancel_fiscal_review)
        self.assertFalse(so2.meli_cancel_fiscal_review)

    def test_08_camino_real_meli_cancel_with_detail_legacy(self):
        """Por donde entra en caso-K45: meli_cancel_with_detail (modo legacy) => la venta NO se cancela,
        queda marcada, sin ERROR; la segunda pasada no agrega avisos ni actividades."""
        if "mercadolibre_cancel_mode" in self.co._fields:
            self.co.mercadolibre_cancel_mode = "legacy"
        so, inv = self._mkso(9)
        self._timbrada({inv.id})
        msg = "Orden cancelada por MercadoLibre. Motivo: test 26309"
        with self.assertLogs(LOGGER, level="WARNING") as cm:
            res = so.meli_cancel_with_detail(msg)
        self.assertFalse([l for l in cm.output if l.startswith("ERROR")], cm.output)
        self.assertFalse(res, "con la factura timbrada sin resolver la venta no se cancela")
        self.assertEqual(so.state, "sale")
        self.assertEqual(inv.state, "posted")
        self.assertTrue(so.meli_cancel_fiscal_review)
        n_msgs = self.env["mail.message"].search_count([("model", "=", "sale.order"), ("res_id", "=", so.id)])
        so.meli_cancel_with_detail(msg)
        self.assertEqual(self.env["mail.message"].search_count(
            [("model", "=", "sale.order"), ("res_id", "=", so.id)]), n_msgs, "la 2da pasada no postea nada")
        self.assertEqual(len(self._acts(so)), 1)
