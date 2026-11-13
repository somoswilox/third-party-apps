# -*- coding: utf-8 -*-
import logging

from werkzeug.exceptions import NotFound

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)

# [#caso-K19] Nivel de seguridad: qué funcionalidad expone cada ruta remota (ver res.company.ocapi_security_level).
# El control va acá y no en cada controlador para cubrir también las rutas que otros módulos
# sobreescriben con @http.route() y las que se agreguen después: toda ruta /ocapi/ no listada es 'data'.
_OCAPI_ROUTE_FEATURES = (
    ('/auth', 'status'),
    ('/status', 'status'),
    ('/rebind', 'actions'),
    ('/post_stock', 'actions'),
    ('/post_price', 'actions'),
    ('/githook', 'actions'),
    ('/sales', 'actions'),
    ('/ocapi/publish', 'actions'),
)


def ocapi_route_feature(path):
    if not path or not path.startswith('/ocapi/'):
        return None
    for suffix, feature in _OCAPI_ROUTE_FEATURES:
        if path.endswith(suffix):
            return feature
    return 'data'


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        feature = ocapi_route_feature(getattr(rule, 'rule', None))
        if feature and not request.env['res.company'].sudo()._ocapi_security_allows(feature):
            _logger.info("ocapi: ruta %s cerrada por el Nivel de seguridad (%s)", rule.rule, feature)
            raise NotFound()
