# -*- coding: utf-8 -*-
"""[un caso fase 3] El host alternativo por cuenta (mercadolibre.account.http_proxy) pasa a la compañía.

Desde 26.210 la URL de la API es UNA por compañía (res.company.meli_api_url, validada y con registro
de uso). http_proxy de la cuenta queda como alias sin almacenar; su columna sigue en la base y acá se
copia a la compañía de la cuenta, para que quien usa el proxy de rescate siga exactamente igual.
- La compañía ya tiene una URL no oficial (propia o de otra cuenta): gana esa y se avisa si difiere.
- Cuenta sin compañía: se avisa y no se toca.
- Valor inválido: se avisa y queda la oficial (con un valor sin https:// requests ya fallaba).
Idempotente.
"""
import logging

_logger = logging.getLogger(__name__)

API_HOST_DEFAULT = "https://api.mercadolibre.com"


def _column_exists(cr, table, column):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
               (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _column_exists(cr, 'mercadolibre_account', 'http_proxy') \
            or not _column_exists(cr, 'mercadolibre_account', 'company_id') \
            or not _column_exists(cr, 'res_company', 'meli_api_url'):
        return
    from odoo.addons.meli_oerp.models.meli_util import meli_normalize_api_url
    cr.execute("""
        SELECT a.id, a.company_id, a.http_proxy FROM mercadolibre_account a
         WHERE coalesce(trim(a.http_proxy), '') <> ''
         ORDER BY a.id
    """)
    for account_id, company_id, old in cr.fetchall():
        if not company_id:
            _logger.warning("MELI multiple 26.210: cuenta %s con proxy %r y SIN compañía: no se migra",
                            account_id, old)
            continue
        try:
            url = meli_normalize_api_url(old)
        except ValueError as e:
            _logger.warning("MELI multiple 26.210: cuenta %s: proxy viejo %r inválido (%s); no se migra",
                            account_id, old, e)
            continue
        cr.execute("SELECT meli_api_url FROM res_company WHERE id=%s", (company_id,))
        row = cr.fetchone()
        current = (row and row[0] or '').rstrip('/') or API_HOST_DEFAULT
        if current == API_HOST_DEFAULT:
            cr.execute("UPDATE res_company SET meli_api_url=%s WHERE id=%s", (url, company_id))
            _logger.warning("MELI multiple 26.210: compañía %s: URL de la API = %s (copiada de la cuenta %s)",
                            company_id, url, account_id)
        elif current != url:
            _logger.warning("MELI multiple 26.210: cuenta %s tenía proxy %s pero la compañía %s ya usa %s: "
                            "queda el de la compañía", account_id, url, company_id, current)
