# -*- coding: utf-8 -*-
"""Integracion del modo `mercadolibre_cancel_mode = 'por_estado_ml'` (meli_oerp 26.162).

La decision sale de una FOTO FRESCA de ML (orden + pagos + envio). Aca la red se mockea en
`sale.order._meli_cancel_fetch` (el unico punto que hace GET), y se mide lo que queda en Odoo:
estado de la venta, devolucion, notas de credito, flag "esperando retorno" y chatter.

La tabla completa de la decision (sin Odoo) esta en meli_oerp/tests/test_cancel_decision_pure.py.

Correr (Odoo 18):  odoo-bin -c <conf> -d <db> -u meli_oerp_accounting --test-tags /meli_oerp_accounting --stop-after-init
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

ORDER_ID = "2000752432504"
SHIP_ID = "4400009999001"


class _FakeMeli:
    access_token = "TEST"
    needlogin_state = False


def _order(status="cancelled", payments=None, code="buyer_regretted", with_shipping=True):
    oj = {"id": int(ORDER_ID), "status": status, "pack_id": None,
          "cancel_detail": {"code": code, "requested_by": "buyer"},
          "payments": payments or []}
    if with_shipping:
        oj["shipping"] = {"id": int(SHIP_ID)}
    return oj


def _pay(status, refunded=0.0, amount=230.0):
    return {"id": 77, "status": status, "transaction_amount": amount, "total_paid_amount": amount,
            "transaction_amount_refunded": refunded}


def _ship(status, substatus=None, logistic="cross_docking"):
    return {"id": int(SHIP_ID), "status": status, "substatus": substatus, "logistic_type": logistic,
            "status_history": {}}


@tagged("post_install", "-at_install", "meli_cancel_v2")
class TestCancelPorEstadoML(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.co = cls.env.company
        cls.wh = cls.env["stock.warehouse"].search([("company_id", "=", cls.co.id)], limit=1)
        cls.cust = cls.env["res.partner"].create({"name": "Comprador ML v2"})
        cls.co.mercadolibre_return_mode = "done"
        cls.co.mercadolibre_invoice_cancel_mode = "manual"
        cls.co.mercadolibre_cancel_mode = "por_estado_ml"
        if "mercadolibre_notification_mode" in cls.co._fields:
            cls.co.mercadolibre_notification_mode = "internal_note"
        cls.SO = cls.env["sale.order"]
        # Desde meli_oerp 26.221 la devolucion automatica depende del motivo de ML
        # (meli_oerp.cancel_return_reasons, default buyer_cancel_express,fraud). Esta matriz
        # mide la decision por ESTADO de ML, no el filtro de motivos (cubierto en meli_oerp
        # test_26278/test_cancel_decision_pure) => todos los motivos, como antes de 26.221.
        icp = cls.env["ir.config_parameter"].sudo()
        (getattr(icp, "set_str", None) or icp.set_param)("meli_oerp.cancel_return_reasons", "*")  # 20: set_str

    def setUp(self):
        super().setUp()
        self.photo = {}
        self.calls = []
        test = self

        def fake_fetch(so_self, meli, path):
            test.calls.append(path)
            if path.startswith("/orders/"):
                return test.photo.get("order", {"error": "not_found", "status": 404})
            if path.startswith("/shipments/"):
                return test.photo.get("ship", {"error": "not_found", "status": 404})
            return {"error": "unexpected"}

        p = patch.object(type(self.SO), "_meli_cancel_fetch", fake_fetch)
        p.start()
        self.addCleanup(p.stop)

    # -------------------------------------------------------------- helpers --
    def _mkso(self, deliver=True, invoice=None):
        Product = self.env["product.product"]
        pvals = {"name": "P-v2", "list_price": 100.0, "invoice_policy": "order"}
        if "is_storable" in Product._fields:      # 18.0+
            pvals.update(type="consu", is_storable=True)
        elif "detailed_type" in Product._fields:  # 16.0 / 17.0
            pvals.update(detailed_type="product")
        else:
            pvals.update(type="product")
        prod = Product.create(pvals)
        self.env["stock.quant"]._update_available_quantity(prod, self.wh.lot_stock_id, 50)
        so = self.SO.create({"partner_id": self.cust.id, "meli_order_id": ORDER_ID,
                             "meli_status": "cancelled",
                             "order_line": [(0, 0, {"product_id": prod.id, "product_uom_qty": 2, "price_unit": 100})]})
        so.action_confirm()
        if deliver:
            for pk in so.picking_ids:
                so._meli_validate_picking(pk)
        if invoice:
            inv = so._create_invoices()
            if invoice in ("posted", "paid"):
                inv.action_post()
            if invoice == "paid":
                self.env["account.payment.register"].with_context(
                    active_model="account.move", active_ids=inv.ids).create({})._create_payments()
        return so, prod

    def _cancel(self, so, passes=1):
        res = None
        for _ in range(passes):
            res = so.with_context(meli_cancel_ctx_nocache=True).meli_cancel_with_detail(
                "Orden cancelada por MercadoLibre. Motivo: test", meli=_FakeMeli())
        return res

    def _qty(self, prod):
        return prod.with_context(location=self.wh.lot_stock_id.id).qty_available

    def _refunds(self, so):
        return self.env["account.move"].search([("move_type", "=", "out_refund"),
                                                ("reversed_entry_id", "in", so.invoice_ids.ids)])

    def _returns(self, so):
        return so.picking_ids.filtered(lambda p: p.picking_type_code == "incoming")

    def _chatter(self, so):
        return " || ".join(m.body.striptags() if hasattr(m.body, "striptags") else str(m.body)
                           for m in so.message_ids if m.body)

    def _require_accounting(self):
        if not self.env["account.journal"].search([("type", "=", "sale"), ("company_id", "=", self.co.id)], limit=1):
            self.skipTest("sin diario de ventas en la compania de test")

    # ---------------------------------------------------------------- casos --
    def test_p01_nunca_salio_reintegrado_devuelve_nc_y_cancela(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=True, invoice="posted")
        self.photo = {"order": _order(payments=[_pay("refunded", 230.0)]), "ship": _ship("ready_to_ship")}
        self.assertEqual(self._qty(prod), 48)
        res = self._cancel(so, passes=3)
        self.assertTrue(res)
        self.assertEqual(so.state, "cancel")
        self.assertEqual(self._returns(so).mapped("state"), ["done"])
        self.assertEqual(self._qty(prod), 50)
        self.assertEqual(len(self._refunds(so)), 1, "3 pasadas = 1 sola NC")
        self.assertIn("fila:", so.meli_cancel_decision)
        self.assertFalse(so.meli_cancel_waiting_return)

    def test_p02_en_transito_espera_y_devuelve_al_volver(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=True, invoice="posted")
        self.photo = {"order": _order(payments=[_pay("refunded", 230.0)]), "ship": _ship("shipped")}
        self.assertFalse(self._cancel(so, passes=2))
        self.assertEqual(so.state, "sale")
        self.assertTrue(so.meli_cancel_waiting_return)
        self.assertFalse(self._returns(so), "en transito NO se devuelve")
        self.assertEqual(self._qty(prod), 48)
        self.assertEqual(len(self._refunds(so)), 1, "la NC por lo reintegrado sale igual")
        found = self.SO.search([("id", "=", so.id), ("meli_cancel_waiting_return", "=", True)])
        self.assertEqual(found, so, "filtro 'Cancelacion esperando retorno'")
        # el envio vuelve
        self.photo["ship"] = _ship("not_delivered", "returned")
        self.assertTrue(self._cancel(so))
        self.assertEqual(so.state, "cancel")
        self.assertFalse(so.meli_cancel_waiting_return)
        self.assertEqual(self._returns(so).mapped("state"), ["done"])
        self.assertEqual(self._qty(prod), 50)
        self.assertEqual(len(self._refunds(so)), 1)

    def test_p03_entregado_sin_devolucion_nc_sin_stock(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=True, invoice="posted")
        self.photo = {"order": _order(payments=[_pay("refunded", 230.0)]), "ship": _ship("delivered")}
        self.assertTrue(self._cancel(so))
        self.assertFalse(self._returns(so))
        self.assertEqual(self._qty(prod), 48)
        self.assertEqual(len(self._refunds(so)), 1)

    def test_p04_pack_splitted_aprobado_sin_reintegro_manual(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=True, invoice="posted")
        self.photo = {"order": _order(payments=[_pay("approved")], code="pack_splitted"), "ship": _ship("ready_to_ship")}
        self.assertFalse(self._cancel(so, passes=2))
        self.assertEqual(so.state, "sale")
        self.assertFalse(self._returns(so))
        self.assertFalse(self._refunds(so))
        self.assertEqual(self._chatter(so).count("ACCIÓN REQUERIDA (cancelación de ML)"), 1, "aviso una sola vez")

    def test_p05_foto_incompleta_no_acciona(self):
        so, prod = self._mkso(deliver=True, invoice=None)
        self.photo = {"order": _order(payments=[_pay("refunded", 230.0)]),
                      "ship": {"error": "get error", "status": 0, "cause": "request_exception"}}
        with self.assertLogs("odoo.addons.meli_oerp.models.orders", level="WARNING") as cm:
            self.assertFalse(self._cancel(so, passes=2))
        self.assertTrue(any("foto de ML incompleta" in m for m in cm.output))
        self.assertEqual(so.state, "sale")
        self.assertFalse(self._returns(so))
        self.assertEqual(self._chatter(so).count("no se pudo leer el estado actualizado"), 1)
        self.assertFalse(so.meli_cancel_decision, "sin foto no hay decision")

    def test_p06_nunca_acreditado_borrador_cancelado(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=False, invoice="draft")
        self.photo = {"order": _order(payments=[_pay("cancelled")]), "ship": _ship("pending")}
        self.assertTrue(self._cancel(so))
        self.assertEqual(so.state, "cancel")
        self.assertEqual(so.invoice_ids.mapped("state"), ["cancel"])
        self.assertEqual(so.picking_ids.mapped("state"), ["cancel"])

    def test_p07_full_no_devuelve(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=True, invoice="posted")
        self.photo = {"order": _order(payments=[_pay("refunded", 230.0)]),
                      "ship": _ship("shipped", logistic="fulfillment")}
        self.assertTrue(self._cancel(so))
        self.assertFalse(self._returns(so))
        self.assertEqual(len(self._refunds(so)), 1)

    def test_p08_reintegro_parcial_manual(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=True, invoice="posted")
        self.photo = {"order": _order(payments=[_pay("approved", 100.0)]), "ship": _ship("ready_to_ship")}
        self.assertFalse(self._cancel(so))
        self.assertEqual(so.state, "sale")
        self.assertFalse(self._refunds(so), "reintegro parcial: la NC parcial es a mano")
        self.assertIn("reintegro PARCIAL", so.meli_cancel_decision)

    def test_p09_ml_ya_no_dice_cancelada(self):
        so, prod = self._mkso(deliver=True)
        self.photo = {"order": _order(status="paid", payments=[_pay("approved")]), "ship": _ship("ready_to_ship")}
        self.assertFalse(self._cancel(so))
        self.assertEqual(so.state, "sale")
        self.assertFalse(self._returns(so))

    def test_p10_legacy_no_consulta_ml(self):
        self.co.mercadolibre_cancel_mode = "legacy"
        so, prod = self._mkso(deliver=True)
        self.assertTrue(self._cancel(so))
        self.assertEqual(self.calls, [], "legacy no hace red")
        self.assertEqual(self._returns(so).mapped("state"), ["done"])
        self.assertFalse(so.meli_cancel_decision)

    def test_p11_pago_en_mediacion_usa_config_manual(self):
        self._require_accounting()
        so, prod = self._mkso(deliver=True, invoice="posted")
        self.photo = {"order": _order(payments=[_pay("in_mediation")]), "ship": _ship("delivered")}
        self.assertFalse(self._cancel(so))
        self.assertEqual(so.state, "sale")
        self.assertFalse(self._refunds(so), "config manual: no NC")

    def test_p12_parte2_legacy_credit_note_cancela_la_venta(self):
        """Parte 2 (vale en los DOS modos): factura revertida por NC publicada = resuelta."""
        self._require_accounting()
        self.co.mercadolibre_cancel_mode = "legacy"
        self.co.mercadolibre_invoice_cancel_mode = "credit_note"
        so, prod = self._mkso(deliver=True, invoice="paid")
        self.assertTrue(self._cancel(so, passes=3))
        self.assertEqual(so.state, "cancel")
        self.assertEqual(len(self._refunds(so)), 1)

    def test_p13_ya_cancelada_no_hace_red(self):
        so, prod = self._mkso(deliver=False)
        so._meli_action_cancel()
        self.assertEqual(so.state, "cancel")
        self.assertTrue(self._cancel(so))
        self.assertEqual(self.calls, [])

    def test_p14_sin_envio_ml_usa_config(self):
        so, prod = self._mkso(deliver=True)
        self.photo = {"order": _order(payments=[_pay("refunded", 230.0)], with_shipping=False)}
        self.assertTrue(self._cancel(so))
        self.assertEqual([c for c in self.calls if c.startswith("/shipments/")], [])
        self.assertEqual(self._returns(so).mapped("state"), ["done"], "return_mode=done configurado")
