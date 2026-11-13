# -*- coding: utf-8 -*-
"""#caso-K71 (cliente D caso-K07) sobre el diseno K15 26.267 de meli_reconcile.

Prod 502 (26.239) resolvia #caso-K71 con models/meli_ref.py (comparar por id de orden ML). En el source el
mismo caso lo cubre K15 26.267: el cobro del modulo se reconoce por meli_payment_id y el resto por TOKEN
ENTERO de la referencia. El caso real de #caso-K71:
    invoice_origin = 'ML 2000434518350850 | PQRBEW6MHJI2VLYVU4MOCA3PWI'   (venta renombrada por envio)
    memo del cobro = 'ML 2000434518350850 OP 173668603497 TOT'
26.386: los tokens se arman partiendo la referencia por espacios, asi que 'ML' y '|' eran tokens y
CUALQUIER cobro 'ML <otra orden> ...' del mismo partner se tomaba como propio (vuelve el bug del #caso-K46).
Ahora un token tiene que tener al menos 3 caracteres, algun alfanumerico, y no ser una palabra del memo.
"""
from odoo.tests import tagged

from . import test_k15_concilia_por_venta as _k15

REF_524 = 'ML 2000434518350850 | PQRBEW6MHJI2VLYVU4MOCA3PWI'


@tagged('post_install', '-at_install', 'meli_K71', 'meli_26386')
class TestK71RefConTracking(_k15.TestConciliaPorVentaK15):

    def setUp(self):
        super().setUp()
        self.so_524 = self._venta(REF_524, '2000434518350850')
        self.so_otra = self._venta('ML 2000131224024564 | XXRBEW6MHJI2VLYVU4MOCA3PWI', '2000131224024564')
        self.inv_524 = self._factura(REF_524)

    def _cobro_524(self, memo, meli_payment=None):
        vals = {'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': self.partner.id,
                'amount': self.inv_524.amount_total, 'journal_id': self.journal.id}
        if self.memo_field:
            vals[self.memo_field] = memo
        if meli_payment:
            vals['meli_payment_id'] = meli_payment.id
        pay = self.env['account.payment'].create(vals)
        pay.action_post()
        return pay

    def test_k71_memo_de_su_orden_concilia(self):
        """El caso real de #caso-K71: misma orden, sufijos distintos (tracking vs OP/TOT)."""
        self._cobro_524('ML 2000434518350850 OP 173668603497 TOT')
        self.so_524.meli_reconcile(invoice=self.inv_524)
        self.assertTrue(self._conciliada(self.inv_524))

    def test_k71_cobro_ml_propio_concilia(self):
        self._cobro_524('ML 2000434518350850 OP 173668603497 TOT', meli_payment=self.ml_pay[self.so_524.id])
        self.so_524.meli_reconcile(invoice=self.inv_524)
        self.assertTrue(self._conciliada(self.inv_524))

    def test_k71_memo_de_OTRA_orden_ml_no_concilia(self):
        """#caso-K46: un credito de otra orden ML del mismo partner NO es de esta factura (falla con 'ML' como token)."""
        self._cobro_524('ML 2000131224024564 OP 185794538193 TOT')
        self.so_524.meli_reconcile(invoice=self.inv_524)
        self.assertFalse(self._conciliada(self.inv_524), "el token 'ML' no identifica una orden")

    def test_k71_tokens_sin_ruido(self):
        toks = self.env['sale.order']._meli_reconcile_ref_tokens(self.inv_524, self.so_524, REF_524)
        self.assertIn('2000434518350850', toks)
        self.assertNotIn('ML', toks)
        self.assertNotIn('|', toks)
