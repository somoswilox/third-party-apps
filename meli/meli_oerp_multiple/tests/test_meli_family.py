# -*- coding: utf-8 -*-
"""Tests de la lógica PURA del modo familia (cuentas user_product_seller) — cliente F #caso-K21, 28-sep-2026.

Corre SIN Odoo:   python3 -m unittest discover -s tests -p 'test_*.py'   (desde la raíz del módulo)
y con Odoo (--test-enable, usa odoo.tests.BaseCase). Los payloads de ML son fixtures con la forma
documentada de GET /categories/{id}/attributes — sin red.
"""
import importlib.util
import os
import unittest

try:  # bajo Odoo
    from odoo.tests import BaseCase as _Base
    from odoo.addons.meli_oerp_multiple.models import meli_family as mf
except Exception:  # python plano
    _Base = unittest.TestCase
    _path = os.path.join(os.path.dirname(__file__), '..', 'models', 'meli_family.py')
    _spec = importlib.util.spec_from_file_location('meli_family', _path)
    mf = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(mf)


# MLA40513 Agendas (forma real de ML; recortado a lo que importa)
CAT_AGENDAS = [
    {"id": "BRAND", "name": "Marca", "tags": {"required": True}},
    {"id": "MODEL", "name": "Modelo", "tags": {"required": True}},
    {"id": "MANUFACTURER", "name": "Fabricante", "tags": {"required": True}},
    {"id": "COVER_COLOR", "name": "Color de la portada", "tags": {"allow_variations": True},
     "values": [{"id": "52049", "name": "Negro"}, {"id": "51993", "name": "Rosa"},
                {"id": "52055", "name": "Amarillo"}, {"id": "52028", "name": "Azul"},
                {"id": "283165", "name": "Azul marino"}]},
    {"id": "GTIN", "name": "Código universal de producto",
     "tags": {"conditional_required": True, "variation_attribute": True, "allow_variations": True}},
    {"id": "EMPTY_GTIN_REASON", "name": "Motivo de GTIN vacío",
     "tags": {"variation_attribute": True},
     "values": [{"id": "17055160", "name": "El producto no tiene código registrado"},
                {"id": "17055158", "name": "Es un kit"}]},
    {"id": "SELLER_SKU", "name": "SKU", "tags": {"variation_attribute": True, "allow_variations": True}},
    {"id": "ITEM_CONDITION", "name": "Condición", "tags": {"hidden": True, "allow_variations": True}},
    {"id": "VALUE_ADDED_TAX", "name": "IVA", "tags": {"required": True}},
    {"id": "IMPORT_DUTY", "name": "Impuesto interno", "tags": {"required": True}},
]

# categoría de ropa: dos atributos de variación posibles
CAT_REMERAS = [
    {"id": "COLOR", "name": "Color", "tags": {"allow_variations": True},
     "values": [{"id": "1", "name": "Rojo"}, {"id": "2", "name": "Azul"}]},
    {"id": "SIZE", "name": "Talle", "tags": {"allow_variations": True}},
    {"id": "GTIN", "name": "GTIN", "tags": {"allow_variations": True}},
]

# categoría sin exigencia de GTIN
CAT_SIN_GTIN = [
    {"id": "COLOR", "name": "Color", "tags": {"allow_variations": True}},
    {"id": "GTIN", "name": "GTIN", "tags": {"allow_variations": True}},
]

# Atributos comunes que el módulo arma para 1000108 (líneas de 1 valor + campos meli_*)
BASE_1000108 = [
    {"id": "BRAND", "value_name": "Acmex"},
    {"id": "MANUFACTURER", "value_name": "Acmex"},
    {"id": "VALUE_ADDED_TAX", "value_name": "21 %"},
    {"id": "IMPORT_DUTY", "value_name": "0 %"},
    {"id": "MODEL", "value_name": "AGENDA MOOD"},
    {"id": "SELLER_PACKAGE_HEIGHT", "value_name": "4 cm"},
    {"id": "SELLER_PACKAGE_WIDTH", "value_name": "18 cm"},
    {"id": "SELLER_PACKAGE_LENGTH", "value_name": "22 cm"},
    {"id": "SELLER_PACKAGE_WEIGHT", "value_name": "666 g"},
]

TALLE_LINE = {"key": 687, "name": "Talle", "n_values": 2, "creates_variant": True, "mapped": None}


def _ids(atts):
    return [a["id"] for a in atts]


def _val(atts, aid):
    for a in atts:
        if a["id"] == aid:
            return a.get("value_name")
    return None


class TestResolveVariationAttribute(_Base):

    def test_cliente_f_talle_sin_mapeo_va_al_unico_allow_variations_de_la_categoria(self):
        mapping, unresolved, _c = mf.resolve_variant_lines([TALLE_LINE], CAT_AGENDAS)
        self.assertEqual(unresolved, [])
        self.assertEqual(mapping[687]["id"], "COVER_COLOR")

    def test_gtin_sku_ocultos_nunca_son_candidatos(self):
        ids = [c["id"] for c in mf.variation_candidates(CAT_AGENDAS)]
        self.assertEqual(ids, ["COVER_COLOR"])

    def test_dos_candidatos_no_se_adivina(self):
        mapping, unresolved, cands = mf.resolve_variant_lines([dict(TALLE_LINE, name="Modelo X")], CAT_REMERAS)
        self.assertEqual(mapping, {})
        self.assertEqual(unresolved, ["Modelo X"])
        msg = mf.missing_mapping_message(unresolved, cands, "MLA1234")
        self.assertIn("Color (COLOR)", msg)
        self.assertIn("Talle (SIZE)", msg)
        self.assertIn("No se publicó nada", msg)

    def test_mapeo_global_de_variacion_aceptado_por_la_categoria_gana(self):
        line = dict(TALLE_LINE, mapped={"id": "SIZE", "name": "Talle", "variation": True})
        mapping, unresolved, _c = mf.resolve_variant_lines([line], CAT_REMERAS)
        self.assertEqual(mapping[687]["id"], "SIZE")
        self.assertEqual(unresolved, [])

    def test_mapeo_global_que_la_categoria_no_acepta_cae_al_de_la_categoria(self):
        # 'Talle' mapeado a SIZE (sirve para ropa) usado en una agenda: SIZE no existe en MLA40513
        line = dict(TALLE_LINE, mapped={"id": "SIZE", "name": "Talle", "variation": True})
        mapping, unresolved, _c = mf.resolve_variant_lines([line], CAT_AGENDAS)
        self.assertEqual(mapping[687]["id"], "COVER_COLOR")

    def test_mapeo_sin_categoria_conocida_se_respeta(self):
        line = dict(TALLE_LINE, mapped={"id": "SIZE", "name": "Talle", "variation": True})
        mapping, unresolved, _c = mf.resolve_variant_lines([line], [])
        self.assertEqual(mapping[687]["id"], "SIZE")

    def test_lineas_de_un_valor_o_no_variante_no_cuentan(self):
        lines = [{"key": 1, "name": "Fabricante", "n_values": 1, "creates_variant": False, "mapped": None},
                 {"key": 2, "name": "IVA", "n_values": 2, "creates_variant": False, "mapped": None}]
        mapping, unresolved, _c = mf.resolve_variant_lines(lines, CAT_AGENDAS)
        self.assertEqual((mapping, unresolved), ({}, []))

    def test_categoria_sin_candidatos(self):
        mapping, unresolved, cands = mf.resolve_variant_lines([TALLE_LINE], [{"id": "GTIN", "tags": {}}])
        self.assertEqual(unresolved, ["Talle"])
        self.assertIn("no tiene en Mercado Libre ningún atributo", mf.missing_mapping_message(unresolved, cands))


class TestNormalizeValue(_Base):
    VALS = CAT_AGENDAS[3]["values"]

    def test_valor_de_cliente_f_con_prefijo(self):
        self.assertEqual(mf.normalize_value("MOOV ROSA", self.VALS), ("Rosa", "51993"))
        self.assertEqual(mf.normalize_value("MOOV AMARILLO", self.VALS), ("Amarillo", "52055"))

    def test_igual_gana_sobre_contenido(self):
        self.assertEqual(mf.normalize_value("azul  MARINO", self.VALS), ("Azul marino", "283165"))

    def test_ambiguo_queda_el_texto_de_odoo(self):
        self.assertEqual(mf.normalize_value("ROSA Y AMARILLO", self.VALS), ("ROSA Y AMARILLO", None))

    def test_sin_valores_de_ml(self):
        self.assertEqual(mf.normalize_value("Verde agua", []), ("Verde agua", None))

    def test_no_matchea_pedazos_de_palabra(self):
        self.assertEqual(mf.normalize_value("ROSADO", self.VALS), ("ROSADO", None))


class TestBodyPorVariante(_Base):
    """El body de cada publicación de la familia (lo que antes iba en variations[])."""

    def _rosa(self, base=BASE_1000108):
        return mf.build_variant_attributes(
            base, sku="48147_1246", gtin="7799133038112",
            combination=[{"id": "COVER_COLOR", "value_name": "Rosa", "value_id": "51993"}])

    def test_1000108_rosa_lleva_todo(self):
        atts = self._rosa()
        for aid in ("BRAND", "MANUFACTURER", "MODEL", "VALUE_ADDED_TAX", "IMPORT_DUTY",
                    "SELLER_PACKAGE_WEIGHT", "SELLER_SKU", "GTIN", "COVER_COLOR"):
            self.assertIn(aid, _ids(atts))
        self.assertEqual(_val(atts, "GTIN"), "7799133038112")
        self.assertEqual(_val(atts, "SELLER_SKU"), "48147_1246")
        self.assertEqual(_val(atts, "VALUE_ADDED_TAX"), "21 %")
        self.assertEqual(len(_ids(atts)), len(set(_ids(atts))))

    def test_no_arrastra_gtin_sku_de_otra_variante(self):
        base = BASE_1000108 + [{"id": "GTIN", "value_name": "7799133038112"},
                               {"id": "SELLER_SKU", "value_name": "48147_1246"}]
        atts = mf.build_variant_attributes(
            base, sku="48147_1410", gtin="7799133038105",
            combination=[{"id": "COVER_COLOR", "value_name": "Amarillo"}])
        self.assertEqual(_val(atts, "GTIN"), "7799133038105")
        self.assertEqual(_val(atts, "SELLER_SKU"), "48147_1410")
        self.assertEqual(_ids(atts).count("GTIN"), 1)

    def test_la_combinacion_pisa_al_comun(self):
        base = BASE_1000108 + [{"id": "COVER_COLOR", "value_name": "Negro"}]
        self.assertEqual(_val(self._rosa(base), "COVER_COLOR"), "Rosa")

    def test_con_gtin_se_quita_el_motivo_de_gtin_vacio(self):
        base = BASE_1000108 + [{"id": "EMPTY_GTIN_REASON", "value_name": "El producto no tiene código registrado"}]
        self.assertNotIn("EMPTY_GTIN_REASON", _ids(self._rosa(base)))

    def test_sin_gtin_se_conserva_el_motivo(self):
        base = BASE_1000108 + [{"id": "EMPTY_GTIN_REASON", "value_id": "17055160"}]
        atts = mf.build_variant_attributes(base, sku="201460-1", gtin=None)
        self.assertIn("EMPTY_GTIN_REASON", _ids(atts))
        self.assertNotIn("GTIN", _ids(atts))

    def test_family_name_sin_variations(self):
        body = {"family_name": "Agenda Mood 10x15", "attributes": self._rosa(),
                "variations": [{"attribute_combinations": []}]}
        body2, removed = mf.strip_variations_for_family(body)
        self.assertTrue(removed)
        self.assertNotIn("variations", body2)
        self.assertEqual(body2["family_name"], "Agenda Mood 10x15")
        self.assertIn("GTIN", _ids(body2["attributes"]))  # lo que antes se perdía (caso b)

    def test_cuenta_clasica_no_se_toca(self):
        body = {"title": "x", "variations": [{}]}
        self.assertEqual(mf.strip_variations_for_family(body), (body, False))


class TestGtinPorVariante(_Base):

    def test_201460_boligrafo_4_variantes_sin_ean_se_frena_antes(self):
        vs = [{"label": "201460-%d" % i, "gtin": None} for i in range(1, 5)]
        missing = mf.variants_missing_gtin(vs, CAT_AGENDAS, BASE_1000108)
        self.assertEqual(missing, ["201460-1", "201460-2", "201460-3", "201460-4"])
        msg = mf.missing_gtin_message(missing, CAT_AGENDAS)
        self.assertIn("El producto no tiene código registrado", msg)
        self.assertIn("No se publicó nada", msg)

    def test_701421_sin_ean_pero_con_motivo_declarado_pasa(self):
        vs = [{"label": "701421-1", "gtin": None}, {"label": "701421-2", "gtin": None}]
        base = BASE_1000108 + [{"id": "EMPTY_GTIN_REASON", "value_name": "El producto no tiene código registrado"}]
        self.assertEqual(mf.variants_missing_gtin(vs, CAT_AGENDAS, base), [])

    def test_202298_con_ean_pasa(self):
        vs = [{"label": "202298-1", "gtin": "7791234567895"}, {"label": "202298-2", "gtin": "7791234567888"}]
        self.assertEqual(mf.variants_missing_gtin(vs, CAT_AGENDAS, BASE_1000108), [])

    def test_categoria_que_no_exige_gtin(self):
        vs = [{"label": "x-1", "gtin": None}]
        self.assertEqual(mf.variants_missing_gtin(vs, CAT_SIN_GTIN, []), [])

    def test_categoria_sin_motivos_no_los_ofrece(self):
        cat = [{"id": "GTIN", "tags": {"required": True}}]
        msg = mf.missing_gtin_message(["x-1"], cat)
        self.assertNotIn("EMPTY_GTIN_REASON", msg)


class TestListingPorVariante(_Base):
    """Caso (a): la 2ª variante NUNCA hereda la publicación de la 1ª."""

    def test_cada_variante_su_publicacion(self):
        self.assertEqual(mf.listing_id_for_variant(None, None), None)           # alta nueva
        self.assertEqual(mf.listing_id_for_variant("MLA2", "MLA1"), "MLA2")     # binding manda
        self.assertEqual(mf.listing_id_for_variant(None, "MLA1"), "MLA1")
        self.assertEqual(mf.listing_id_for_variant("MLA2", "MLA1", force_new=True), None)

    def test_principal_primero(self):
        self.assertEqual(mf.order_family_variants([505309, 505310], 505310), [505310, 505309])
        self.assertEqual(mf.order_family_variants([505309, 505310], 999), [505309, 505310])

    def test_resumen_nunca_esconde_lo_publicado(self):
        err, txt = mf.family_post_summary([
            {"variant": "48147_1246", "meli_id": "MLA4399526254", "created": True},
            {"variant": "48147_1410", "meli_id": None, "error": "ML 400 GTIN"}])
        self.assertTrue(err)
        self.assertIn("MLA4399526254", txt)
        self.assertIn("48147_1410: ML 400 GTIN", txt)
        err, txt = mf.family_post_summary([{"variant": "a", "meli_id": "MLA1"}])
        self.assertFalse(err)


class TestPutSinFamilyName(_Base):
    """Etapa 1b: P1 en prod cliente F (28-sep 16:07Z) — PUT de MLA4399526254 con family_name ⇒ ML 400."""

    def test_user_product_no_manda_nombre_en_put(self):
        self.assertEqual(mf.update_name_fields(True, "Agenda Mood 10x15"), {})

    def test_clasica_manda_title(self):
        self.assertEqual(mf.update_name_fields(False, "Agenda Mood"), {"title": "Agenda Mood"})

    def test_guarda_final_quita_family_name_y_title(self):
        body = {"family_name": "Agenda Mood", "title": "x", "price": 27780,
                "attributes": [{"id": "COVER_COLOR", "value_name": "Rosa"}]}
        b2, removed = mf.strip_name_fields_for_update(body, True)
        self.assertEqual(sorted(removed), ["family_name", "title"])
        self.assertNotIn("family_name", b2)
        self.assertNotIn("title", b2)
        self.assertEqual(b2["price"], 27780)
        self.assertIn("family_name", body)  # no muta el original

    def test_guarda_no_toca_cuenta_clasica(self):
        body = {"title": "x"}
        self.assertEqual(mf.strip_name_fields_for_update(body, False), (body, []))


class TestPreflightBasicos(_Base):
    """Etapa 1c — cliente F 28-sep, tpl 464030 '202298' sin categoría: el mensaje culpaba a 'Talle'."""

    def test_202298_sin_categoria_dice_categoria(self):
        labels = mf.basic_missing(has_category=False)
        self.assertEqual(len(labels), 1)
        msg = mf.basic_missing_message(labels)
        self.assertIn("Categoría de Mercado Libre", msg)
        self.assertNotIn("Talle", msg)
        self.assertIn("No se publicó nada", msg)

    def test_orden_y_todos(self):
        labels = mf.basic_missing(False, False, False, False)
        self.assertEqual(len(labels), 4)
        self.assertIn("Categoría", labels[0])
        self.assertIn("Tipo de publicación", labels[3])

    def test_completo(self):
        self.assertEqual(mf.basic_missing(), [])

    def test_no_se_pudo_leer_la_categoria(self):
        msg = mf.missing_mapping_message(["Talle"], [], "MLA40513", read_error=True)
        self.assertIn("No se pudieron leer", msg)
        self.assertIn("volvé a intentar", msg)

    def test_categoria_sin_atributo_de_variacion(self):
        msg = mf.missing_mapping_message(["Talle"], [], "MLA40513", read_error=False)
        self.assertIn("no tiene en Mercado Libre ningún atributo que permita variantes", msg)
        self.assertNotIn("No se pudieron leer", msg)


# MLA40513 real (28-sep): TRES atributos allow_variations
CAT_AGENDAS_REAL = [
    {"id": "COVER_COLOR", "name": "Color de la portada", "tags": {"allow_variations": True},
     "values": [{"id": "52049", "name": "Negro"}, {"id": "51993", "name": "Rosa"},
                {"id": "52055", "name": "Amarillo"}, {"id": "52019", "name": "Lila"},
                {"id": "2450304", "name": "Beige"}, {"id": "52028", "name": "Azul"}]},
    {"id": "PATTERN_NAME", "name": "Nombre del diseño", "tags": {"allow_variations": True}},
    {"id": "YEAR", "name": "Año", "tags": {"allow_variations": True},
     "values": [{"id": "1", "name": "2026"}, {"id": "2", "name": "2027"}]},
    {"id": "GTIN", "name": "GTIN", "tags": {"allow_variations": True}},
]
# MLA69561 (carpetas): un solo COLOR
CAT_CARPETAS = [
    {"id": "COLOR", "name": "Color", "tags": {"allow_variations": True},
     "values": [{"id": "52051", "name": "Rojo"}, {"id": "52014", "name": "Celeste"}, {"id": "52049", "name": "Negro"}]},
    {"id": "GTIN", "name": "GTIN", "tags": {"allow_variations": True}},
]


def _talle(values):
    return {"key": 687, "name": "Talle", "n_values": len(values), "values": values,
            "creates_variant": True, "mapped": None}


class TestDesempatePorValores(_Base):
    """Etapa 1d — dry-run real en prod: Cuaderno Modelo, 3 candidatos ⇒ se bloqueaba."""

    def test_spring_lila_beige_va_a_cover_color(self):
        mapping, unresolved, _c = mf.resolve_variant_lines([_talle(["MOOV LILA", "MOOV BEIGE"])], CAT_AGENDAS_REAL)
        self.assertEqual(unresolved, [])
        self.assertEqual(mapping[687]["id"], "COVER_COLOR")
        self.assertEqual(mf.normalize_value("MOOV LILA", mapping[687]["values"]), ("Lila", "52019"))
        self.assertEqual(mf.normalize_value("MOOV BEIGE", mapping[687]["values"]), ("Beige", "2450304"))

    def test_mood_rosa_amarillo_va_a_cover_color(self):
        mapping, unresolved, _c = mf.resolve_variant_lines([_talle(["MOOV ROSA", "MOOV AMARILLO"])], CAT_AGENDAS_REAL)
        self.assertEqual(mapping[687]["id"], "COVER_COLOR")

    def test_202298_fw_rojo_celeste_va_a_color(self):
        mapping, unresolved, _c = mf.resolve_variant_lines([_talle(["FW ROJO", "FW CELESTE"])], CAT_CARPETAS)
        self.assertEqual(mapping[687]["id"], "COLOR")
        self.assertEqual(mf.normalize_value("FW CELESTE", mapping[687]["values"]), ("Celeste", "52014"))

    def test_un_valor_sin_match_no_desempata(self):
        # 'MOOV TURQUESA' no está en COVER_COLOR ⇒ no TODOS matchean ⇒ bloquea con los candidatos
        mapping, unresolved, cands = mf.resolve_variant_lines([_talle(["MOOV LILA", "MOOV TURQUESA"])], CAT_AGENDAS_REAL)
        self.assertEqual(unresolved, ["Talle"])
        self.assertEqual(sorted(c["id"] for c in cands), ["COVER_COLOR", "PATTERN_NAME", "YEAR"])

    def test_texto_libre_nunca_gana(self):
        cat = [c for c in CAT_AGENDAS_REAL if c["id"] != "COVER_COLOR"]  # quedan PATTERN_NAME (libre) y YEAR
        mapping, unresolved, _c = mf.resolve_variant_lines([_talle(["MOOV LILA", "MOOV BEIGE"])], cat)
        self.assertEqual(unresolved, ["Talle"])

    def test_dos_candidatos_que_matchean_no_se_adivina(self):
        cat = CAT_REMERAS + [{"id": "MAIN_COLOR", "name": "Color principal", "tags": {"allow_variations": True},
                              "values": [{"id": "9", "name": "Rojo"}, {"id": "8", "name": "Azul"}]}]
        mapping, unresolved, _c = mf.resolve_variant_lines([_talle(["ROJO", "AZUL"])], cat)
        self.assertEqual(unresolved, ["Talle"])


class TestFamilyNameDeLaPlantilla(_Base):
    """Etapa 1e — dry-run prod Cuaderno Modelo: la variante -1 tenía un meli_title viejo ⇒ otra familia."""

    TPL = (None, None, None, "Cuaderno Modelo 2027 - 10 x 15 - Dia x Dia", "1000128 Cuaderno Modelo")
    VARIANTES = {"1000128-1": "AGENDA ACMEX 2027 - N.7 - 10 x 15 - SPRING",  # título viejo en la variante
                 "1000128-2": ""}

    def _body(self, variant_title):
        # lo que arma el alta: el título de la variante NO entra al family_name
        return {"family_name": mf.family_name_for_template(*self.TPL), "_variant_title": variant_title}

    def test_dos_variantes_mismo_family_name(self):
        b1 = self._body(self.VARIANTES["1000128-1"])
        b2 = self._body(self.VARIANTES["1000128-2"])
        self.assertEqual(b1["family_name"], b2["family_name"])
        self.assertEqual(b1["family_name"], "Cuaderno Modelo 2027 - 10 x 15 - Dia x Dia")
        self.assertNotIn("N.7", b1["family_name"])

    def test_orden_binding_antes_que_plantilla(self):
        self.assertEqual(mf.family_name_for_template("Fam binding", "Tit binding", "Fam tpl", "Tit tpl", "Nombre"),
                         "Fam binding")
        self.assertEqual(mf.family_name_for_template(None, "  ", "", None, "Nombre"), "Nombre")
        self.assertEqual(mf.family_name_for_template(), "")


class TestImagenYColorExtra(_Base):
    """Etapa 1f — protocolo FCA §AA: (1) foto principal = la de la variante; (2) color como custom extra."""

    def test_foto_principal_es_la_de_la_variante(self):
        comunes = [{"id": "T1"}, {"id": "T2"}]
        rosa = mf.family_pictures([{"id": "R1"}] + comunes, main_id="R1")
        amarillo = mf.family_pictures([{"id": "A1"}] + comunes, main_id="A1")
        self.assertEqual(rosa[0]["id"], "R1")
        self.assertEqual(amarillo[0]["id"], "A1")
        self.assertNotIn({"id": "A1"}, rosa)  # nunca la foto de otra variante

    def test_fotos_sin_duplicados_y_con_tope(self):
        pics = [{"id": "T1"}, {"id": "R1"}, {"id": "T1"}, {"source": "https://x/logo.png"}] + [{"id": "X%d" % i} for i in range(20)]
        out = mf.family_pictures(pics, main_id="R1")
        self.assertEqual([p.get("id") or p.get("source") for p in out[:3]], ["R1", "T1", "https://x/logo.png"])
        self.assertEqual(len(out), 10)

    def test_body_familia_sin_custom_color(self):
        """PROD cliente F 28-sep: ML genera el título con family_name + valores diferenciadores; el custom
        "Color" lo duplicaba ("… Lila Lila"). El body (sin custom=) sólo lleva COVER_COLOR."""
        comb = [{"id": "COVER_COLOR", "name": "Color de la portada", "value_name": "Lila", "value_id": "52019"}]
        atts = mf.build_variant_attributes(BASE_1000108, sku="1000128-1", gtin="7799133038129", combination=comb)
        self.assertEqual(_val(atts, "COVER_COLOR"), "Lila")
        self.assertEqual([a for a in atts if not a.get("id")], [])

    def test_custom_de_la_base_que_repite_la_combinacion_se_descarta(self):
        comb = [{"id": "COVER_COLOR", "value_name": "Lila"}]
        base = BASE_1000108 + [{"name": "Color", "value_name": "lila"}]
        atts = mf.build_variant_attributes(base, combination=comb)
        self.assertEqual([a for a in atts if not a.get("id")], [])
        base = BASE_1000108 + [{"name": "Colección", "value_name": "2027"}]
        atts = mf.build_variant_attributes(base, combination=comb)
        self.assertEqual([a for a in atts if not a.get("id")], [{"name": "Colección", "value_name": "2027"}])

    def test_un_solo_custom_por_item(self):
        base = BASE_1000108 + [{"name": "Diseño", "value_name": "viejo"}, {"name": "Otro", "value_name": "x"}]
        comb = [{"id": "COLOR", "name": "Color", "value_name": "Celeste"}]
        atts = mf.build_variant_attributes(base, combination=comb, custom=mf.custom_attribute_for(comb))
        self.assertEqual([a for a in atts if not a.get("id")], [{"name": "Color", "value_name": "Celeste"}])

    def test_atributo_no_color_usa_su_nombre(self):
        comb = [{"id": "PATTERN_NAME", "name": "Nombre del diseño", "value_name": "Spring"}]
        self.assertEqual(mf.custom_attribute_for(comb), {"name": "Nombre del diseño", "value_name": "Spring"})
        self.assertIsNone(mf.custom_attribute_for([]))


class TestCustomCleanupUpdate(_Base):
    """UPDATE: borrar el custom "Color" que dejó la etapa 1f ({"name":"Color","value_name":null}, medido 28-sep)."""
    COMB = [{"id": "COVER_COLOR", "name": "Color de la portada", "value_name": "Lila"}]

    def test_item_con_custom_color_se_limpia(self):
        current = [{"id": "COVER_COLOR", "name": "Color de la portada", "value_name": "Lila"},
                   {"name": "Color", "value_name": "Lila"}]
        self.assertEqual(mf.custom_cleanup_for_update(current, self.COMB),
                         [{"name": "Color", "value_name": None}])

    def test_custom_con_id_ajeno_a_la_categoria_tambien(self):
        current = [{"id": "CUSTOM_123", "name": "Color", "value_name": "Lila"}]
        self.assertEqual(mf.custom_cleanup_for_update(current, self.COMB, category_ids=["COVER_COLOR", "BRAND"]),
                         [{"name": "Color", "value_name": None}])
        # sin conocer la categoría, un atributo con id NO se toca
        self.assertEqual(mf.custom_cleanup_for_update(current, self.COMB), [])

    def test_atributo_de_categoria_llamado_color_no_se_toca(self):
        comb = [{"id": "COLOR", "name": "Color", "value_name": "Celeste"}]
        current = [{"id": "COLOR", "name": "Color", "value_name": "Celeste"}]
        self.assertEqual(mf.custom_cleanup_for_update(current, comb, category_ids=["COLOR"]), [])
        self.assertEqual(mf.custom_cleanup_for_update(current, comb), [])

    def test_sin_custom_o_sin_combinacion_no_hace_nada(self):
        self.assertEqual(mf.custom_cleanup_for_update([{"id": "BRAND", "name": "Marca", "value_name": "X"}], self.COMB), [])
        self.assertEqual(mf.custom_cleanup_for_update([{"name": "Color", "value_name": "Lila"}], []), [])
        self.assertEqual(mf.custom_cleanup_for_update(None, self.COMB), [])
        # custom de otro nombre (del usuario) no se toca
        self.assertEqual(mf.custom_cleanup_for_update([{"name": "Colección", "value_name": "2027"}], self.COMB), [])

    def test_si_el_body_ya_lleva_un_custom_no_se_agrega_otro(self):
        current = [{"name": "Color", "value_name": "Lila"}]
        out = [{"id": "COVER_COLOR", "value_name": "Lila"}, {"name": "Colección", "value_name": "2027"}]
        self.assertEqual(mf.custom_cleanup_for_update(current, self.COMB, outgoing_attributes=out), [])


if __name__ == '__main__':
    unittest.main()
