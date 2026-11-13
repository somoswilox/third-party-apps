# -*- coding: utf-8 -*-
"""26.329 (#caso-K50 cliente D caso-K07, bus 2026-10-28T15:21:43Z): pagos ML creados N veces y anulados.

Lazo medido en codigo: republish_invoice_payments cancela el pago (partner != factura), pone
account_payment_id=False por ORM y llama create_payment. create_payment lee account_payment_id por
SQL crudo (SELECT ... FOR UPDATE NOWAIT) SIN flush: ve el pago VIEJO, sale con "Pago ya creado" y
no crea nada. La siguiente confirm_ml lo crea con el partner que la sync de la orden volvio a
poner (meli_oerp < 26.282) y republish lo vuelve a cancelar: un pago anulado por actualizacion.

Fix (port de 2952eaa, 8-oct, nunca landeado): flush del vinculo antes del SQL crudo.
Control: contra origin (sin el fix) test_create_payment_ve_el_vinculo_limpiado falla.
"""
import logging
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models import versions as acc_versions

LOGGER = 'odoo.addons.meli_oerp_accounting.models.payments'


@tagged('post_install', '-at_install', 'meli', 'meli_26329')
class TestPagoRecrea26329(TransactionCase):

    def _crear_minimo(self, model, extra=None, _visitados=None):
        _visitados = _visitados or set()
        Model = self.env[model]
        vals = {}
        for name, f in Model._fields.items():
            if not f.required or f.compute or f.related or f.readonly:
                continue
            if f.type in ('char', 'text', 'html'):
                vals[name] = 'TEST'
            elif f.type == 'integer':
                vals[name] = 1
            elif f.type in ('float', 'monetary'):
                vals[name] = 1.0
            elif f.type == 'boolean':
                vals[name] = False
            elif f.type == 'date':
                vals[name] = fields.Date.today()
            elif f.type == 'datetime':
                vals[name] = fields.Datetime.now()
            elif f.type == 'selection':
                sel = f.selection(Model) if callable(f.selection) else f.selection
                vals[name] = sel[0][0] if sel else False
            elif f.type == 'many2one':
                rec = self.env[f.comodel_name].search([], limit=1)
                if not rec and f.comodel_name not in _visitados:
                    _visitados.add(f.comodel_name)
                    rec = self._crear_minimo(f.comodel_name, None, _visitados)
                vals[name] = rec.id if rec else False
        vals.update(extra or {})
        return Model.create(vals)

    def test_cancel_statuses_incluye_canceled(self):
        # account.payment en Odoo 18/19 usa 'canceled' (una ele): sin esto confirm_ml no recreaba.
        self.assertIn('canceled', acc_versions.cancel_statuses)
        self.assertIn('cancel', acc_versions.cancel_statuses)

    def test_create_payment_ve_el_vinculo_limpiado(self):
        if not self.env['account.account'].search([('account_type', '=', 'asset_receivable')], limit=1):
            self.skipTest("sin plan de cuentas en esta base")
        journal = self.env['account.journal'].create({
            'name': 'MercadoPago 26329', 'code': 'M329', 'type': 'bank', 'company_id': self.env.company.id})
        partner = self.env['res.partner'].create({'name': 'Cliente 26329'})
        ap = self.env['account.payment'].create({
            'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': partner.id,
            'amount': 10.0, 'journal_id': journal.id})
        pay = self._crear_minimo('mercadolibre.payments', {
            'payment_id': '26329000001', 'status': 'approved', 'account_payment_id': ap.id,
            'transaction_amount': 10.0})
        self.env.flush_all() if hasattr(self.env, 'flush_all') else self.env['base'].flush()
        # lo que hace republish_invoice_payments: limpia el vinculo por ORM (queda pendiente de flush)
        pay.account_payment_id = False
        with patch.object(type(pay), '_get_ml_journal', lambda self, config=None: False), \
                self.assertLogs(LOGGER, level='INFO') as logs:
            logging.getLogger(LOGGER).info('26329 marca')
            pay.create_payment(config=self.env.company)
        txt = '\n'.join(logs.output)
        self.assertNotIn('Pago ya creado', txt,
                         "create_payment leyo el pago viejo por SQL sin flush: no recrea (lazo #caso-K50)")
        self.assertIn('Debe configurar el diario', txt, "paso el chequeo del lock y llego a crear")
        self.env.cr.execute("SELECT account_payment_id FROM mercadolibre_payments WHERE id=%s", [pay.id])
        self.assertIsNone(self.env.cr.fetchone()[0])
