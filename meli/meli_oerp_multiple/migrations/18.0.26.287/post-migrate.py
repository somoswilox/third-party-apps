# -*- coding: utf-8 -*-
"""26.287 (caso-K11 cliente L/producto 1; fix 26.249 landeado como 26.287) — enmascarar los tokens de ML que quedaron POSTEADOS en el chatter.

Hasta 26.206 (#caso-K19) el refresh y el login posteaban en el chatter de la cuenta ("Refresh result" /
"Login result") el access_token y el refresh_token en claro. Desde 26.206 ya no se postean, pero lo
ya posteado sigue visible para cualquiera que pueda leer la cuenta (26.213 y 26.238 limpiaron otras
tablas, no mail_message). El refresh_token vigente sirve para sacar tokens nuevos: no puede quedar a la vista.

Idempotente: solo toca mensajes de mercadolibre.account / res.company que todavia tienen un token sin
enmascarar. No cambia nada mas del texto. No loguea valores, solo cantidades.
"""
import logging

_logger = logging.getLogger(__name__)

# APP_USR-<app>-<fecha>-<hash>-<user> (access_token) y TG-<hash>-<user> (refresh_token)
_APP_RE = r"APP_USR-[A-Za-z0-9\-]{8,}"
_TG_RE = r"TG-[A-Za-z0-9\-]{8,}"
_MODELS = ('mercadolibre.account', 'res.company')


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """UPDATE mail_message
              SET body = regexp_replace(regexp_replace(body::text, %s, 'APP_USR-***', 'g'), %s, 'TG-***', 'g')
            WHERE model IN %s
              AND (body::text ~ %s OR body::text ~ %s)""",
        (_APP_RE, _TG_RE, _MODELS, _APP_RE, _TG_RE))
    if cr.rowcount:
        _logger.info("26.287 (caso-K11): tokens de ML enmascarados en %s mensaje(s) del chatter", cr.rowcount)
