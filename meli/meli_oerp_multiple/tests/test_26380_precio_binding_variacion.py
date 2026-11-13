# -*- coding: utf-8 -*-
"""26.380 (caso-K21 cliente F): en multivariante el precio de cada variacion lo decide SU binding.

`x_product_post_price` armaba el payload `variations` con `set_meli_price()` del PRODUCTO de
cada variante e ignoraba el precio resuelto por el binding (`mercadolibre.product.update_price()`:
precio fijo / lista de precios / plantilla de binding). Pisaba incluso a la variante empujada,
que llega con `meli_price=bindv.meli_price`. Caso: MLA1568564491, binding fijado a 25398, ML
recibio 24649 en las 3 variaciones.

El test no toca ML ni la base: recorre el metodo real con dobles (meli, bindings, variantes).
"""

from unittest.mock import MagicMock

from odoo.tests import TransactionCase, tagged

from ..models import product as product_mod

PRECIO_PRODUCTO = 24649.0
PRECIO_BINDING = "25398"


def _variante(precio=PRECIO_PRODUCTO):
    v = MagicMock(name="variante")
    v.set_meli_price.return_value = precio
    v.meli_price = precio
    return v


def _binding(var_id, precio_fijo=PRECIO_BINDING, falla=False):
    b = MagicMock(name="binding-%s" % var_id)
    b.id = var_id
    b.conn_variation_id = str(var_id)
    b.product_id = _variante()
    b.meli_price = False

    def _update_price(*a, **k):
        if falla:
            raise RuntimeError("boom")
        b.meli_price = precio_fijo
    b.update_price.side_effect = _update_price
    return b


@tagged('post_install', '-at_install', 'meli_26380')
class TestPrecioBindingVariacion26380(TransactionCase):

    def test_helper_usa_precio_del_binding(self):
        b = _binding(1)
        self.assertEqual(product_mod._meli_precio_de_variacion(b, b.product_id), 25398.0)
        b.product_id.set_meli_price.assert_not_called()

    def test_helper_sin_precio_en_binding_cae_al_producto(self):
        b = _binding(1, precio_fijo=False)
        self.assertEqual(product_mod._meli_precio_de_variacion(b, b.product_id), PRECIO_PRODUCTO)

    def test_helper_binding_que_falla_cae_al_producto(self):
        b = _binding(1, falla=True)
        self.assertEqual(product_mod._meli_precio_de_variacion(b, b.product_id), PRECIO_PRODUCTO)

    def test_payload_variaciones_lleva_precio_del_binding(self):
        bindings = [_binding(i) for i in (101, 102, 103)]
        enviado = {}

        meli = MagicMock(name="meli")
        meli.client_id = "x"
        meli.access_token = "t"
        meli.get.return_value.json.return_value = {
            "currency_id": "ARS",
            "variations": [{"id": 101}, {"id": 102}, {"id": 103}],
        }

        def _put(path, fields, params=None):
            enviado.update(fields)
            r = MagicMock()
            r.json.return_value = {"id": "MLA1568564491"}
            return r
        meli.put_mini.side_effect = _put

        modelo_bind = MagicMock(name="mercadolibre.product")
        modelo_bind.search.return_value = bindings
        fake = MagicMock(name="product.product")
        modelos = {"meli.warning": MagicMock(), "product.product": MagicMock(),
                   "mercadolibre.product": modelo_bind}
        fake.env = MagicMock(name="env")
        fake.env.__getitem__.side_effect = modelos.__getitem__
        fake.meli_price = PRECIO_PRODUCTO
        fake.meli_currency = "ARS"
        fake._meli_resolve_account.return_value = MagicMock(id=7)

        Prod = type(self.env["product.product"])
        Prod.x_product_post_price(fake, meli_price=PRECIO_BINDING, meli_currency="ARS",
                                  meli=meli, config=MagicMock(),
                                  meli_id="MLA1568564491", meli_id_variation="101")

        self.assertIn("variations", enviado)
        self.assertEqual([v["price"] for v in enviado["variations"]], [25398.0] * 3)
