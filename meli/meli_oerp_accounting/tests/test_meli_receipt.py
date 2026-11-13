# -*- coding: utf-8 -*-
"""[#caso-K60 un cliente] Recibo del ultimo pago en pedidos con varios pagos ML.

Datos: los 5 pedidos del ticket, leidos de la base del cliente el 5-oct-2026. En los 5 el recibo
automatico quedo corto y el cliente lo reemplazo a mano por uno "TOT (CORREGIDO)" igual al total
de la factura. Este test exige que el calculo nuevo llegue a ESE mismo monto.
Corre con Odoo (tag meli_receipt) o suelto: python3 meli_oerp_accounting/tests/test_meli_receipt.py
"""
import os
import unittest

try:
    from odoo.tests import tagged
    from odoo.tests.common import BaseCase as _Base
    from odoo.addons.meli_oerp_accounting.models import meli_receipt as mr
except Exception:  # fuera de Odoo
    import importlib.util
    _Base = unittest.TestCase

    def tagged(*_a):
        return lambda cls: cls
    _p = os.path.join(os.path.dirname(__file__), '..', 'models', 'meli_receipt.py')
    _s = importlib.util.spec_from_file_location('meli_receipt', _p)
    mr = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(mr)

# pedido -> (total factura = recibo corregido por el cliente, envio del pedido,
#            pagos [(transaction_amount, total_paid_amount, shipping_amount)],
#            recibos automaticos que se habian creado, en orden)
CASOS_603 = {
    'ML 2000215602078541 (carrito)': (49271.01, 6357.81,
        [(12012.00, 12012.00, 0.0), (30901.20, 30901.20, 0.0)], [12012.00, 30901.20]),
    'ML 2000184567722740 (carrito)': (48089.01, 18990.00,
        [(25300.00, 25300.00, 0.0), (3799.00, 3799.00, 0.0)], [25300.00, 3799.00]),
    'ML 2000466486562402 (carrito)': (52784.07, 5307.07,
        [(10879.00, 10879.00, 0.0), (36598.00, 36598.00, 0.0)], [10879.00, 36598.00]),
    'ML 2000015323344276 (suelta, 2 pagos, cupon ML)': (69862.44, 0.0,
        [(27336.45, 25000.00, 0.0), (42525.99, 33762.80, 0.0)], [25000.00, 33762.80]),
}


def _c(x):
    return int(round(x * 100))


@tagged('post_install', '-at_install', 'meli', 'meli_receipt')
class TestMeliReceipt(_Base):

    def test_los_recibos_cierran_con_la_factura_como_corrigio_el_cliente(self):
        for name, (total, envio, pagos, recibos) in CASOS_603.items():
            unc = mr.uncovered_by_payments(envio, pagos)
            ya = sum(recibos[:-1])
            monto, ajustado, motivo = mr.last_payment_amount(total, ya, recibos[-1], unc)
            self.assertTrue(ajustado, name)
            self.assertEqual(motivo, 'uncovered', name)
            self.assertEqual(_c(ya + monto), _c(total), name)

    def test_antes_quedaban_cortos(self):
        # el comportamiento viejo: solo |dif| <= 5 x tolerancia
        for name, (total, _envio, _pagos, recibos) in CASOS_603.items():
            self.assertGreater(total - sum(recibos), 5.0, name)

    def test_no_tapa_un_pago_que_falta_entero(self):
        # ML 2000834305304194: el recibo del pago 176543552172 (19.118,19) nunca se creo.
        # Si el unico recibo es el de 12.012, lo que falta (19.118,19 + envio 17.110) NO lo
        # explica el envio solo => no se infla el recibo para tapar un pago ausente.
        unc = mr.uncovered_by_payments(17110.00, [(19118.19, 19118.19, 0.0), (12012.00, 12012.00, 0.0)])
        monto, ajustado, motivo = mr.last_payment_amount(48240.21, 0.0, 12012.00, unc)
        self.assertFalse(ajustado)
        self.assertEqual(monto, 12012.00)

    def test_nunca_supera_el_total_y_respeta_el_redondeo(self):
        self.assertEqual(mr.last_payment_amount(100.0, 60.0, 39.5, 0.0), (40.0, True, 'rounding'))
        self.assertEqual(mr.last_payment_amount(100.0, 60.0, 40.0, 0.0), (40.0, False, 'exact'))
        # recibo que se pasaria (pago mayor que lo que resta) fuera de tolerancia: crudo
        self.assertEqual(mr.last_payment_amount(100.0, 60.0, 80.0, 50.0), (80.0, False, 'raw'))

    def test_uncovered(self):
        self.assertEqual(mr.uncovered_by_payments(0.0, []), 0.0)
        # envio ya incluido en un pago: no cuenta como faltante
        self.assertEqual(mr.uncovered_by_payments(500.0, [(1500.0, 1500.0, 500.0)]), 0.0)
        self.assertEqual(_c(mr.uncovered_by_payments(0.0, [(27336.45, 25000.0, 0.0), (42525.99, 33762.80, 0.0)])),
                         _c(11099.64))


if __name__ == '__main__':
    unittest.main()
