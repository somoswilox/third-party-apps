# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date
import logging
_logger = logging.getLogger(__name__)
from datetime import date, datetime


class MercadolibrePublicInvoiceWizard(models.TransientModel):
    _name = 'mercadolibre.public.wizard'
    _description = 'Mercadolibre publicar ordenes - Wizard'


    def _default_count(self):
        context = self.env.context
        if 'active_ids' in context:
            return len(self.env.context['active_ids'])
        else:
            return 1

    count = fields.Integer(default=_default_count)

    def public_product(self,context=None):
        context = context or self.env.context
        active_ids = ('active_ids' in context and context['active_ids']) or []
        model = context['active_model']
        order_ids = self.env[model].sudo().browse(active_ids)
        if order_ids:
            for o in order_ids:
                if o.meli_orders:
                    for mo in o.meli_orders:
                        _logger.info("Orden: %s" % (mo.order_id))
                        if not mo.invoice_posted:
                            _logger.info("Orden a publicar: %s" % (mo.order_id))
                            mo.sudo().orders_post_invoice()

    def republish_invoice_payments(self, context=None):
        """
        Republicar pagos: cuando la factura fue creada manualmente a una razón social
        diferente del partner predeterminado, cancela el pago existente y lo recrea
        con el partner correcto de la factura.
        """
        context = context or self.env.context
        active_ids = ('active_ids' in context and context['active_ids']) or []
        model = context['active_model']
        order_ids = self.env[model].sudo().browse(active_ids)
        count = 0
        if order_ids:
            for o in order_ids:
                if o.meli_orders:
                    for mo in o.meli_orders:
                        for payment in mo.payments:
                            if payment.account_payment_id and payment.status in ['approved']:
                                _logger.info("Republicar pago orden: %s payment: %s" % (mo.order_id, payment.payment_id))
                                payment.sudo().republish_invoice_payments()
                                count += 1
        _logger.info("Republicar pagos: %d pagos procesados" % count)

