# -*- coding: utf-8 -*-
"""Lógica PURA (sin Odoo, sin red) del modo FAMILIA de Mercado Libre (#caso-K21 cliente F, 28-sep-2026).

En una cuenta `user_product_seller` ML ya no acepta `variations[]`: cada variante de Odoo es una
PUBLICACIÓN propia y ML las agrupa por `family_name`. Entonces cada publicación necesita, a nivel
item, lo que antes iba por variación:
  - SELLER_SKU y GTIN de ESA variante,
  - el atributo que la diferencia (el de la categoría con tag `allow_variations`, ej. COVER_COLOR),
  - los atributos comunes del producto (BRAND, MODEL, IVA, II, paquete…).

Este módulo arma eso a partir de datos planos, para poder testearlo sin base de datos.
Lo usan `models/product.py` y `models/connection_binding.py`.
"""

NEVER_VARIANT = ("GTIN", "SELLER_SKU")
PER_VARIANT_IDS = ("GTIN", "SELLER_SKU")


def is_never_variant(att_id):
    return bool(att_id) and str(att_id).strip().upper() in NEVER_VARIANT


def _has_tag(att, tag):
    tags = (att or {}).get("tags") or {}
    if isinstance(tags, dict):
        return bool(tags.get(tag))
    if isinstance(tags, (list, tuple, set)):
        return tag in tags
    return False


def variation_candidates(category_attributes, exclude_ids=()):
    """Atributos de la categoría que pueden DEFINIR variantes (`allow_variations`), sin los ocultos
    ni GTIN/SELLER_SKU. `category_attributes` = lista cruda de GET /categories/{id}/attributes.
    Devuelve [{id, name, values}] en el orden de ML."""
    out = []
    excl = set(str(x) for x in (exclude_ids or ()))
    for att in (category_attributes or []):
        if not isinstance(att, dict):
            continue
        att_id = str(att.get("id") or "")
        if not att_id or att_id in excl or is_never_variant(att_id):
            continue
        if _has_tag(att, "hidden") or _has_tag(att, "read_only") or _has_tag(att, "fixed"):
            continue
        if not _has_tag(att, "allow_variations"):
            continue
        out.append({"id": att_id, "name": att.get("name") or att_id,
                    "values": [v for v in (att.get("values") or []) if isinstance(v, dict)]})
    return out


def normalize_value(value_name, allowed_values):
    """Lleva el valor de Odoo al valor de ML si se puede determinar SIN ambigüedad.
    1) igual (sin mayúsculas/espacios) a un valor de ML → ese valor;
    2) exactamente UN valor de ML aparece como palabra(s) completa(s) dentro del de Odoo
       ('MOOV ROSA' → 'Rosa') → ese valor;
    3) si no, el texto de Odoo tal cual (ML lo toma como valor libre).
    Devuelve (value_name, value_id|None)."""
    raw = (value_name or "").strip()
    if not raw or not allowed_values:
        return raw, None
    norm = " ".join(raw.lower().split())
    words = norm.split()
    for v in allowed_values:
        name = " ".join(str(v.get("name") or "").lower().split())
        if name and name == norm:
            return v.get("name"), v.get("id")
    hits = []
    for v in allowed_values:
        name = " ".join(str(v.get("name") or "").lower().split())
        if not name:
            continue
        nw = name.split()
        for i in range(0, len(words) - len(nw) + 1):
            if words[i:i + len(nw)] == nw:
                hits.append(v)
                break
    if len(hits) == 1:
        return hits[0].get("name"), hits[0].get("id")
    return raw, None


def resolve_variant_lines(lines, category_attributes):
    """Decide qué atributo de ML lleva cada línea de atributo que DEFINE variantes.

    `lines`: [{key, name, n_values, values, creates_variant, mapped}] donde `mapped` es el atributo de ML
    ya asociado al atributo de Odoo (product.attribute.meli_default_id_attribute) como
    {id, name, variation} o None.

    Reglas (en orden):
      - sólo cuentan las líneas con >1 valor que crean variantes;
      - si la línea tiene mapeo de VARIACIÓN y (no conocemos la categoría o la categoría lo acepta
        como allow_variations) → ese;
      - las que quedan sin mapeo: si hay UNA sola línea y la categoría tiene UN solo candidato
        allow_variations libre → ese (caso cliente F: 'Talle' → COVER_COLOR en Agendas);
      - si no se puede decidir → problema (mensaje claro), NO se adivina.

    Devuelve (mapping {key: {id, name, values}}, unresolved [nombres de línea], candidates [..]).
    """
    cands_all = variation_candidates(category_attributes)
    cand_by_id = dict((c["id"], c) for c in cands_all)
    known_category = bool(category_attributes)
    mapping = {}
    unresolved = []
    for ln in (lines or []):
        if not ln.get("creates_variant") or int(ln.get("n_values") or 0) < 2:
            continue
        m = ln.get("mapped") or None
        m_id = m and str(m.get("id") or "")
        ok = bool(m_id) and bool(m.get("variation")) and not is_never_variant(m_id)
        if ok and known_category and m_id not in cand_by_id:
            ok = False
        if ok:
            c = cand_by_id.get(m_id) or {"id": m_id, "name": m.get("name") or m_id, "values": []}
            mapping[ln.get("key")] = c
        else:
            unresolved.append(ln)
    used = set(c["id"] for c in mapping.values())
    free = [c for c in cands_all if c["id"] not in used]
    if len(unresolved) == 1 and len(free) == 1:
        mapping[unresolved[0].get("key")] = free[0]
        unresolved = []
    # 1d: varios candidatos ⇒ DESEMPATE POR VALORES. Gana el único candidato con lista de valores de ML
    # en la que TODOS los valores de la línea encuentran su valor (normalize_value: 'MOOV LILA' → Lila).
    # Texto libre (sin values, ej. PATTERN_NAME) nunca gana por desempate. 0 o >1 ⇒ sigue sin resolver.
    still = []
    for ln in unresolved:
        free = [c for c in cands_all if c["id"] not in used]
        winner = values_tiebreak(ln.get("values") or [], free)
        if winner:
            mapping[ln.get("key")] = winner
            used.add(winner["id"])
        else:
            still.append(ln)
    unresolved = still
    free = [c for c in cands_all if c["id"] not in used]
    return mapping, [u.get("name") for u in unresolved], free


def values_tiebreak(line_values, candidates):
    """El ÚNICO candidato (con lista de valores) que reconoce TODOS los valores de la línea; si no, None."""
    vals = [v for v in (line_values or []) if v]
    if not vals:
        return None
    hits = []
    for c in (candidates or []):
        allowed = c.get("values") or []
        if not allowed:
            continue
        if all(normalize_value(v, allowed)[1] for v in vals):
            hits.append(c)
    return hits[0] if len(hits) == 1 else None


BASIC_LABELS = (
    ("category", "la Categoría de Mercado Libre (botón 'Sugerir Categoría' o elegirla a mano)"),
    ("title", "el Título de la publicación"),
    ("price", "el Precio"),
    ("listing_type", "el Tipo de publicación (Clásica / Premium)"),
)


def basic_missing(has_category=True, has_title=True, has_price=True, has_listing_type=True):
    """Datos BÁSICOS que faltan para publicar, en el orden en que conviene cargarlos. Se chequean
    ANTES que cualquier otra cosa: sin categoría no hay atributos que resolver y el resto de los
    mensajes confunde (cliente F 28-sep: tpl 202298 sin categoría ⇒ se culpaba a la línea 'Talle')."""
    have = {"category": has_category, "title": has_title, "price": has_price,
            "listing_type": has_listing_type}
    return [label for key, label in BASIC_LABELS if not have[key]]


def basic_missing_message(labels):
    return ("No se puede publicar todavía: falta %s. Completalo en la pestaña MercadoLibre del producto "
            "y volvé a publicar. No se publicó nada." % "; ".join(labels))


def missing_mapping_message(unresolved_names, candidates, category_label=None, read_error=False):
    """Mensaje para el usuario cuando no se puede decidir qué atributo de ML diferencia las variantes.
    Distingue: la categoría no tiene atributo de variación · no se pudieron leer sus atributos."""
    lineas = ", ".join("'%s'" % n for n in unresolved_names)
    cat = (" (%s)" % category_label) if category_label else ""
    if read_error:
        return ("No se pudieron leer los atributos de la categoría%s en Mercado Libre (error de conexión o "
                "de la API), así que no se puede armar la familia de variantes. No se publicó nada; volvé a "
                "intentar en unos minutos." % cat)
    if candidates:
        opts = ", ".join("%s (%s)" % (c["name"], c["id"]) for c in candidates)
        como = ("Mercado Libre diferencia las variantes de esta categoría%s con: %s. "
                "Asociá el atributo de Odoo a uno de ellos (Inventario > Configuración > Atributos > "
                "'ML Attribute default'), o usá en esta plantilla un atributo propio ya asociado "
                "(ej. 'Color de la portada')." % (cat, opts))
    else:
        como = ("La categoría%s no tiene en Mercado Libre ningún atributo que permita variantes: publicá "
                "cada variante como producto sin variantes o elegí otra categoría." % cat)
    return ("No se puede publicar como familia: no sabemos qué atributo de Mercado Libre corresponde "
            "a la línea de variantes %s. %s No se publicó nada." % (lineas, como))


def build_variant_attributes(base_attributes, sku=None, gtin=None, combination=(), custom=None):
    """Atributos a nivel ITEM de UNA publicación de la familia.

    - parte de los atributos comunes (`base_attributes`), SIN los GTIN/SELLER_SKU que pudieran venir
      de otra variante;
    - agrega SELLER_SKU y GTIN de esta variante (si hay); con GTIN se quita EMPTY_GTIN_REASON
      (ML rechaza los dos juntos);
    - agrega/pisa los de la combinación (lista de {id, value_name[, value_id]}) — lo propio de la
      variante gana sobre lo común.
    Sin ids duplicados; se conserva el orden de primera aparición."""
    order = []
    by_id = {}

    def put(att):
        aid = att.get("id")
        if not aid:
            return
        if aid not in by_id:
            order.append(aid)
        by_id[aid] = att

    for a in (base_attributes or []):
        if isinstance(a, dict) and a.get("id") and a.get("id") not in PER_VARIANT_IDS:
            put(dict(a))
    if sku:
        put({"id": "SELLER_SKU", "value_name": str(sku)})
    if gtin:
        put({"id": "GTIN", "value_name": str(gtin)})
    for c in (combination or ()):
        if isinstance(c, dict) and c.get("id") and (c.get("value_name") or c.get("value_id")):
            att = {"id": c["id"], "value_name": c.get("value_name")}
            if c.get("value_id"):
                att["value_id"] = str(c["value_id"])
            put(att)
    drop = set(["EMPTY_GTIN_REASON"]) if gtin else set()
    out = [by_id[i] for i in order if i not in drop]
    # un custom de la base que repite el valor de la combinación se descarta: ML arma el título con
    # family_name + valores diferenciadores y lo duplicaba ("… Lila Lila", cliente F 28-sep)
    comb_values = set(str(c.get("value_name")).strip().lower() for c in (combination or ())
                      if isinstance(c, dict) and c.get("value_name"))
    customs = [dict(a) for a in (base_attributes or []) if isinstance(a, dict) and not a.get("id") and a.get("name")
               and str(a.get("value_name") or "").strip().lower() not in comb_values]
    if custom and custom.get("name") and custom.get("value_name"):
        customs = [dict(custom)]  # ML acepta UN SOLO atributo custom por item (medido 28-sep)
    return out + customs[:1]


def custom_attribute_for(combination):
    """Atributo ADICIONAL (custom, sin id) con el valor que diferencia a la variante (FCA §AA-2).
    ⚠️ YA NO SE MANDA en el body de la familia (28-sep 21:2xZ, PROD cliente F): en modo familia ML GENERA el
    title = family_name + valores de los atributos diferenciadores, y este custom se sumaba al de la
    categoría ("Cuaderno Modelo … Lila Lila"). Queda para nombrar lo que hay que LIMPIAR en un UPDATE
    (custom_cleanup_for_update).
    Formato medido con /items/validate 28-sep: {"name": ..., "value_name": ...}; máximo UNO por item.
    Nombre: 'Color' si el atributo de variación es de color (COVER_COLOR, COLOR, MAIN_COLOR…), si no el
    nombre del atributo de ML. Sin combinación ⇒ None."""
    for c in (combination or ()):
        if not isinstance(c, dict) or not c.get("value_name"):
            continue
        att_id = str(c.get("id") or "").upper()
        name = "Color" if "COLOR" in att_id else (c.get("name") or c.get("id"))
        return {"name": name, "value_name": c.get("value_name")}
    return None


def custom_cleanup_for_update(current_attributes, combination, outgoing_attributes=None, category_ids=None):
    """UPDATE de una publicación de la familia: si el item en ML (GET) tiene el custom que agregaba la
    etapa 1f (nombre = custom_attribute_for de la combinación: 'Color' o el nombre del atributo),
    devuelve [{"name": <nombre>, "value_name": None}] para borrarlo (medido 28-sep: ese PUT lo quita y
    el título queda con el color una sola vez). Si no, [].
    Es custom si NO tiene id, o si tiene uno que no es de la categoría (`category_ids`, si se conocen).
    Un atributo de la categoría que se llama igual (COLOR "Color") NO es custom y no se toca.
    Si el body ya lleva un custom propio, no se agrega nada (ML acepta UNO por item)."""
    names = set()
    for c in (combination or ()):
        if isinstance(c, dict) and c.get("value_name"):
            ca = custom_attribute_for([c])
            if ca and ca.get("name"):
                names.add(str(ca["name"]).strip().lower())
    if not names:
        return []
    if any(isinstance(a, dict) and not a.get("id") and a.get("name") for a in (outgoing_attributes or [])):
        return []
    cat_ids = set(category_ids or ())
    for a in (current_attributes or []):
        if not isinstance(a, dict) or not a.get("name"):
            continue
        aid = a.get("id")
        is_custom = (not aid) or (cat_ids and aid not in cat_ids)
        if is_custom and str(a["name"]).strip().lower() in names and a.get("value_name"):
            return [{"name": a["name"], "value_name": None}]
    return []


def family_pictures(pictures, main_id=None, max_pictures=10):
    """Fotos de UNA publicación de la familia: la PRINCIPAL es la de su variante (main_id), después el
    resto sin duplicados, recortado a max_pictures. `pictures` = lista de {id} / {source}."""
    out, seen = [], set()
    items = list(pictures or [])
    if main_id:
        items = [{"id": main_id}] + items
    for p in items:
        if not isinstance(p, dict):
            continue
        key = p.get("id") or p.get("source")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:max_pictures]


def strip_variations_for_family(body):
    """En modo familia ML rechaza `variations` junto con `family_name`. Devuelve (body, quitó?)."""
    if isinstance(body, dict) and body.get("variations") and "family_name" in body:
        body = dict(body)
        del body["variations"]
        return body, True
    return body, False


def order_family_variants(variant_ids, principal_id=None):
    """La principal primero (si está entre las a publicar), el resto en su orden."""
    ids = list(variant_ids or [])
    if principal_id in ids:
        ids.remove(principal_id)
        ids.insert(0, principal_id)
    return ids


def listing_id_for_variant(binding_conn_id=None, variant_meli_id=None, force_new=False):
    """Publicación propia de UNA variante: la de su binding (autoritativo para esa cuenta) o, si no
    tiene, la de la variante. Nunca la de otra variante. `force_new` → ninguna (alta nueva)."""
    if force_new:
        return None
    return binding_conn_id or variant_meli_id or None


def family_post_summary(results):
    """results: [{variant, meli_id, created, error}] → (hubo_error, texto para el usuario).
    Siempre lista lo que QUEDÓ publicado, para que nunca haya una publicación viva sin avisar."""
    ok = [r for r in results if not r.get("error")]
    bad = [r for r in results if r.get("error")]
    parts = []
    if ok:
        parts.append("Publicadas/actualizadas y vinculadas: " + "; ".join(
            "%s → %s%s" % (r.get("variant"), r.get("meli_id") or "?", " (nueva)" if r.get("created") else "")
            for r in ok))
    if bad:
        parts.append("Con error (no se publicaron, el resto sí quedó guardado): " + "; ".join(
            "%s: %s" % (r.get("variant"), r.get("error")) for r in bad))
    return bool(bad), "\n".join(parts)


def category_gtin_rules(category_attributes):
    """(gtin_obligatorio, motivos_permitidos) según la categoría.
    GTIN obligatorio = tag `required` o `conditional_required`. Motivos = valores de EMPTY_GTIN_REASON
    si la categoría lo ofrece ([] si no lo ofrece)."""
    required = False
    reasons = None
    for att in (category_attributes or []):
        if not isinstance(att, dict):
            continue
        aid = str(att.get("id") or "")
        if aid == "GTIN":
            required = _has_tag(att, "required") or _has_tag(att, "conditional_required")
        elif aid == "EMPTY_GTIN_REASON":
            reasons = [v for v in (att.get("values") or []) if isinstance(v, dict)]
    return required, (reasons if reasons is not None else [])


def variants_missing_gtin(variants, category_attributes, base_attributes=()):
    """Variantes que NO se pueden publicar por GTIN: la categoría lo exige, la variante no tiene un
    GTIN válido y el producto no declara EMPTY_GTIN_REASON. `variants` = [{label, gtin}]
    (gtin ya validado: None si el código no es un EAN/GTIN válido)."""
    required, _reasons = category_gtin_rules(category_attributes)
    if not required:
        return []
    has_reason = any(isinstance(a, dict) and a.get("id") == "EMPTY_GTIN_REASON"
                     and (a.get("value_name") or a.get("value_id")) for a in (base_attributes or []))
    if has_reason:
        return []
    return [v.get("label") for v in (variants or []) if not v.get("gtin")]


def missing_gtin_message(labels, category_attributes):
    _req, reasons = category_gtin_rules(category_attributes)
    txt = ("No se puede publicar: la categoría exige código universal (GTIN/EAN) y estas variantes no "
           "tienen uno válido: %s. Cargá el EAN en el 'Código de barras' de cada variante" %
           ", ".join(str(x) for x in labels))
    if reasons:
        txt += (", o —si el producto realmente no tiene código— agregá a la plantilla una línea de "
                "atributo asociada a 'Motivo de GTIN vacío' (EMPTY_GTIN_REASON) con uno de estos "
                "valores: %s" % ", ".join(str(r.get("name")) for r in reasons))
    return txt + ". No se publicó nada."


def update_name_fields(is_family_mode, name):
    """Campos de nombre a mandar en un PUT (ACTUALIZACIÓN) de una publicación.
    - cuenta user_product: NINGUNO. ML rechaza family_name en el PUT ("The field family name is
      invalid", 400 BODY_INVALID_FIELDS, medido en cliente F 28-sep sobre MLA4399526254 con 0 ventas) y el
      title lo arma ML desde la familia. family_name va SÓLO en el POST de alta.
    - cuenta clásica: title."""
    if is_family_mode:
        return {}
    return {"title": name or ""}


def strip_name_fields_for_update(body, is_family_mode):
    """Guarda final antes del PUT de un item user_product: quita family_name/title si quedaron.
    Devuelve (body, quitados)."""
    if not is_family_mode or not isinstance(body, dict):
        return body, []
    removed = [k for k in ("family_name", "title") if k in body]
    if removed:
        body = dict((k, v) for k, v in body.items() if k not in removed)
    return body, removed


def family_name_for_template(*template_names):
    """family_name del ALTA en modo familia: el PRIMER nombre no vacío de la PLANTILLA (en orden:
    family_name del binding de plantilla, su título, family_name de la plantilla, meli_title, nombre).
    Es el MISMO para todas las variantes: ML agrupa por family_name, y un meli_title viejo guardado en
    UNA variante armaba otra familia (cliente F 28-sep, Cuaderno Modelo 1000128-1 / -2). El título de la
    variante NO participa."""
    for n in template_names:
        if n and str(n).strip():
            return str(n).strip()
    return ""
