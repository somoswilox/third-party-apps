# -*- coding: utf-8 -*-
"""[#caso-K60 un cliente] Monto del recibo del ULTIMO pago de un pedido con varios pagos ML.

Sin dependencias de Odoo: lo usa payments.py y lo prueba tests/test_meli_receipt.py.

El caso (medido 5-oct-2026 en la base del cliente): en un carrito, cada sub-orden trae su pago SOLO
por el producto; el envio que pago el comprador no viene en ningun pago (shipping_amount 0) y en
una venta suelta con dos pagos, el cupon que pago ML (transaction_amount - total_paid_amount) no
entra en el recibo. Con un solo pago el recibo se lleva al total del pedido; con varios, el
ultimo solo se ajustaba si la diferencia era <= 5 x tolerancia. Resultado: la factura quedaba
"cancelada parcialmente" y el cliente corrigio a mano los 5 ejemplos del ticket (recibos
"TOT (CORREGIDO)" = total de la factura).
"""


def uncovered_by_payments(so_shipping_amount, payments):
    """Lo que el pedido cobra y NINGUN pago trae en su monto de recibo.

    :param so_shipping_amount: envio del pedido (sale.order.meli_shipping_amount).
    :param payments: iterable de (transaction_amount, total_paid_amount, shipping_amount).
    :return: envio no cubierto + cupones pagados por ML. Nunca negativo.
    """
    ship_in_payments = 0.0
    ml_coupons = 0.0
    for transaction_amount, total_paid_amount, shipping_amount in payments:
        ship_in_payments += max(float(shipping_amount or 0.0), 0.0)
        ml_coupons += max(float(transaction_amount or 0.0) - float(total_paid_amount or 0.0), 0.0)
    shipping_gap = max(float(so_shipping_amount or 0.0) - ship_in_payments, 0.0)
    return shipping_gap + ml_coupons


def last_payment_amount(so_amount, already_paid, raw_amount, uncovered, tolerance=1.0):
    """Monto del recibo del ultimo pago aprobado de un pedido con varios pagos.

    Devuelve (monto, ajustado, motivo). Reglas:
      * diferencia chica (<= 5 x tolerancia): redondeo, se cierra al total (comportamiento previo);
      * el recibo queda CORTO y la diferencia la explica `uncovered` (envio del carrito / cupon
        pagado por ML): se cierra al total del pedido, igual que con un pago unico;
      * cualquier otra cosa: monto crudo del pago, sin tocar (no se inventa plata: si falta un
        pago entero o el pedido esta mal, el recibo no lo tapa).
    La suma de recibos NUNCA supera el total del pedido por este ajuste.
    """
    remaining = float(so_amount or 0.0) - float(already_paid or 0.0)
    raw = float(raw_amount or 0.0)
    gap = remaining - raw
    if abs(gap) <= 0.001:
        return raw, False, 'exact'
    if abs(gap) <= tolerance * 5:
        return remaining, True, 'rounding'
    if gap > 0 and gap <= float(uncovered or 0.0) + tolerance * 5:
        return remaining, True, 'uncovered'
    return raw, False, 'raw'
