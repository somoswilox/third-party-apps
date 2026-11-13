# -*- coding: utf-8 -*-
"""Regresion de meli_sign_invoice (firma CFDI MX) -- fix 26.302, test 26.306 (#caso-K16 cliente S caso-K45).

Antes de 26.302 el metodo usaba `config` sin recibirlo => NameError en CADA venta con CFDI
(448 en un dia en un cliente MX), antes de mandar a firmar. Se prueba sin l10n_mx_edi: una
factura de mentira con los campos que el metodo lee; el envio (wizard/PAC) puede fallar y NO
tiene que cortar la facturacion. `meli_message_post` y el logger se mockean (el ERROR logueado
por un PAC caido es esperado y no debe ensuciar la corrida).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

_MOD = "odoo.addons.meli_oerp_accounting.models.order"


def _fake_invoice(state="pending", failed=None):
    docs = [SimpleNamespace(state="invoice_sent_failed", message=failed)] if failed else []
    return SimpleNamespace(_fields={"l10n_mx_edi_cfdi_state": True}, _name="account.move", ids=[],
                           name="INV/TEST/0001", l10n_mx_edi_cfdi_state=state,
                           l10n_mx_edi_invoice_document_ids=docs)


@tagged("post_install", "-at_install", "meli_26306", "meli_sign_invoice")
class TestMeliSignInvoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env["res.partner"].create({"name": "Comprador CFDI 607"})
        cls.so = cls.env["sale.order"].create({"partner_id": partner.id})

    _NO_CONFIG = object()

    def _run(self, invoice, config=_NO_CONFIG):
        post = MagicMock()
        with patch(_MOD + ".meli_message_post", post), patch(_MOD + "._logger", MagicMock()):
            if config is self._NO_CONFIG:
                # la llamada de antes de 26.302: sin config => ahi estaba el NameError
                self.so.meli_sign_invoice(invoice=invoice)
            else:
                self.so.meli_sign_invoice(invoice=invoice, config=config)
        return post

    def test_01_sin_nameerror_y_config_propagada(self):
        cfg = object()
        post = self._run(_fake_invoice(failed="PAC caido"), cfg)
        self.assertTrue(post.called)
        for call in post.call_args_list:
            self.assertIs(call.kwargs.get("config"), cfg, "todos los avisos usan la config del llamador")
        textos = " ".join(str(c.args[1]) for c in post.call_args_list)
        self.assertIn("Meli mandando a firmar CFDI", textos)
        self.assertIn("PAC caido", textos, "el error del PAC queda en el chatter")

    def test_02_sin_config_no_da_nameerror(self):
        post = self._run(_fake_invoice())
        self.assertTrue(post.called)

    def test_03_ya_firmada_no_hace_nada(self):
        post = self._run(_fake_invoice(state="sent"), object())
        self.assertFalse(post.called)

    def test_04_sin_factura_no_hace_nada(self):
        post = self._run(False, object())
        self.assertFalse(post.called)
