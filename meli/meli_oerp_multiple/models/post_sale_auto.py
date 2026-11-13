# -*- coding: utf-8 -*-
"""26.370 (#caso-K67, caso-K39 cliente B1) -- mensaje postventa AUTOMÁTICO según el estado del envío.

Opt-in por cuenta (Configuración › «Mensaje postventa automático»). Usa el MISMO texto y liga que los
botones «Mensaje Postventa» (26.351/26.355). Reglas «logistic_type:estado», p.ej. la de Aztec:
    fulfillment:delivered, xd_drop_off:shipped
El estado de una regla se toma como «alcanzado o posterior» en pending < handling < ready_to_ship <
shipped < delivered (si el refresco del envío ya lo ve entregado, la regla «shipped» también aplica).

Garantías:
- NINGUNA llamada de red dentro de la importación de órdenes (lección caso-K07): lo hace un cron propio.
- A lo sumo UNA vez por orden y por pack: la orden se marca «sending» y se COMMITEA antes del POST;
  un «sending» que queda huérfano (caída a mitad) nunca se reintenta. Si otra orden del mismo pack ya
  está enviada/enviándose, se omite. Un envío manual exitoso con el botón también la marca «sent».
- Respeta el cupo de ML: sin SEND_INVOICE_LINK disponible (p.ej. ya enviado a mano) se omite, sin POST.
- Al activarlo, las órdenes que YA cumplen la regla quedan «skipped» (no se manda en masa lo viejo),
  y nunca se mira una orden de más de N días (default 30). Tope de órdenes por corrida.
"""
import logging
import threading
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

POST_SALE_AUTO_DEFAULT_RULES = "fulfillment:delivered, xd_drop_off:shipped"
_SHIP_ORDER = ['pending', 'handling', 'ready_to_ship', 'shipped', 'delivered']
_LT_ALIASES = {'fullfilment': 'fulfillment', 'fullfillment': 'fulfillment', 'full': 'fulfillment'}


def _in_test():
    """En tests no se commitea (TransactionCase lo prohíbe). 16-20: odoo.modules.module.current_test."""
    if getattr(threading.current_thread(), 'testing', False):
        return True
    try:
        from odoo.modules import module as odoo_module
        return bool(getattr(odoo_module, 'current_test', False))
    except Exception:
        return False


def parse_post_sale_rules(raw):
    """'fulfillment:delivered, xd_drop_off:shipped' => {'fulfillment': {'delivered'},
    'xd_drop_off': {'shipped', 'delivered'}} (el estado pedido y los posteriores)."""
    rules = {}
    for chunk in (raw or '').replace(';', ',').replace('\n', ',').split(','):
        if ':' not in chunk:
            continue
        lt, st = [x.strip().lower() for x in chunk.split(':', 1)]
        lt = _LT_ALIASES.get(lt, lt)
        if not lt or not st:
            continue
        sts = set(_SHIP_ORDER[_SHIP_ORDER.index(st):]) if st in _SHIP_ORDER else {st}
        rules.setdefault(lt, set()).update(sts)
    return rules


class MercadoLibreConfigurationPostSaleAuto(models.Model):

    _inherit = "mercadolibre.configuration"

    mercadolibre_post_sale_auto = fields.Boolean(
        string="Mensaje postventa automático", default=False,
        help="Manda solo el «Mensaje postventa» (el mismo de los botones) cuando el envío de la venta "
             "llega al estado indicado para su tipo de logística. Una sola vez por venta/pack. Al "
             "activarlo, las ventas que ya estaban en ese estado no reciben el mensaje.")
    mercadolibre_post_sale_auto_rules = fields.Char(
        string="Disparadores postventa (logística:estado)", default=POST_SALE_AUTO_DEFAULT_RULES,
        help="Pares tipo_de_logística:estado_del_envío separados por coma. Ej.: "
             "«fulfillment:delivered, xd_drop_off:shipped» = Full al quedar entregado, "
             "Agencia/drop-off al quedar enviado. El estado vale «ese o posterior» "
             "(pending < handling < ready_to_ship < shipped < delivered).")
    mercadolibre_post_sale_auto_days = fields.Integer(
        string="Antigüedad máxima (días)", default=30,
        help="Ventas creadas en ML hace más de estos días no reciben el mensaje automático.")
    mercadolibre_post_sale_auto_since = fields.Datetime(
        string="Postventa automático activo desde", readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs.filtered('mercadolibre_post_sale_auto')._meli_post_sale_auto_baseline()
        return recs

    def write(self, vals):
        turning_on = self.browse()
        if vals.get('mercadolibre_post_sale_auto'):
            turning_on = self.filtered(lambda c: not c.mercadolibre_post_sale_auto)
        res = super().write(vals)
        if turning_on:
            turning_on._meli_post_sale_auto_baseline()
        elif 'mercadolibre_post_sale_auto_rules' in vals:
            # cambiar las reglas con el automático prendido tampoco dispara lo que ya estaba en ese estado
            self.filtered('mercadolibre_post_sale_auto')._meli_post_sale_auto_baseline(stamp=False)
        return res

    def _meli_post_sale_auto_accounts(self):
        self.ensure_one()
        return self.env['mercadolibre.account'].sudo().search([('configuration', '=', self.id)])

    def _meli_post_sale_auto_domain(self, accounts=None):
        """Órdenes que cumplen alguna regla de esta configuración (sin mirar estado postventa)."""
        self.ensure_one()
        rules = parse_post_sale_rules(self.mercadolibre_post_sale_auto_rules)
        accounts = accounts if accounts is not None else self._meli_post_sale_auto_accounts()
        if not rules or not accounts:
            return None
        ors = []
        for lt, sts in rules.items():
            ors.append(['&', ('shipment_logistic_type', '=', lt), ('shipment_status', 'in', sorted(sts))])
        dom = ['|'] * (len(ors) - 1)
        for o in ors:
            dom += o
        return [('connection_account', 'in', accounts.ids), ('sale_order', '!=', False)] + dom

    def _meli_post_sale_auto_baseline(self, stamp=True):
        """Lo que YA cumple la regla al activar no se manda: queda «skipped» (una sola UPDATE)."""
        Orders = self.env['mercadolibre.orders'].sudo()
        for config in self:
            if stamp:
                super(MercadoLibreConfigurationPostSaleAuto, config).write(
                    {'mercadolibre_post_sale_auto_since': fields.Datetime.now()})
            dom = config._meli_post_sale_auto_domain()
            if not dom:
                continue
            ids = Orders.search(dom + [('meli_post_sale_state', '=', False)]).ids
            if ids:
                self.env.flush_all()
                self.env.cr.execute(
                    "UPDATE mercadolibre_orders SET meli_post_sale_state='skipped' "
                    "WHERE id = ANY(%s) AND meli_post_sale_state IS NULL", (ids,))
                Orders.invalidate_model(['meli_post_sale_state'])
                _logger.info("postventa auto: config %s activada, %s ordenes previas quedan omitidas",
                             config.id, len(ids))


class MercadoLibreOrderPostSaleAuto(models.Model):

    _inherit = "mercadolibre.orders"

    meli_post_sale_state = fields.Selection([
        ('sending', 'Enviando'), ('sent', 'Enviado'), ('skipped', 'Omitido'), ('error', 'Error')],
        string="Mensaje postventa", index=True, copy=False, readonly=True,
        help="Estado del mensaje postventa automático/manual de esta venta. Vacío = todavía no.")
    meli_post_sale_date = fields.Datetime(string="Mensaje postventa (fecha)", copy=False, readonly=True)

    # -- helpers ------------------------------------------------------------------------------
    def _meli_post_sale_commit(self):
        """Commit entre órdenes (el POST no se repite aunque caiga el cron). No en tests."""
        if not _in_test():
            self.env.cr.commit()

    def _meli_post_sale_set(self, state, note=None):
        self.ensure_one()
        self.write({'meli_post_sale_state': state, 'meli_post_sale_date': fields.Datetime.now()})
        if note and self.sale_order:
            self.sale_order.message_post(body="Mensaje postventa automático: %s" % note)

    def _meli_post_sale_mark_manual(self, rjson):
        """Llamado por send_post_message tras el POST del botón: si ML lo aceptó, la venta queda «sent»
        y el automático ya no la toca."""
        try:
            ok = isinstance(rjson, dict) and not rjson.get('error') and rjson.get('status') not in (400, 403, 404)
            if ok and self and not self.meli_post_sale_state:
                self.write({'meli_post_sale_state': 'sent', 'meli_post_sale_date': fields.Datetime.now()})
        except Exception as e:  # nunca romper el botón por esto
            _logger.warning("postventa: no se pudo marcar el envio manual de %s: %s", self.ids, e)

    def _meli_post_sale_auto_send(self, config):
        """Un envío. Devuelve (estado, detalle): 'sent' | 'skipped' | 'error' | 'retry' (nada se mandó,
        se puede volver a intentar en la próxima corrida)."""
        self.ensure_one()
        account = self.connection_account
        message = self._meli_post_sale_custom_message(config) \
            or (config and 'autoinvoice_message' in config._fields and config.autoinvoice_message) or None
        base_url = account.company_id.get_base_url()
        text, why = self._meli_post_sale_invoice_text(message=message, base_url=base_url, config=config)
        if not text:
            return 'skipped', why
        meli = self.env['meli.util'].get_new_instance(account.company_id, account)
        if not meli or getattr(meli, 'needlogin_state', False):
            return 'retry', "la cuenta no está conectada con ML"
        pack_id = self.pack_id or self.order_id
        resp = meli.get("/messages/action_guide/packs/%s/caps_available?tag=post_sale" % pack_id,
                        {'access_token': meli.access_token})
        caps = resp and resp.json()
        if not isinstance(caps, list):
            return 'retry', "ML no devolvió las opciones de mensaje: %s" % (caps,)
        cap = next((c for c in caps if isinstance(c, dict) and c.get('option_id') == 'SEND_INVOICE_LINK'), None)
        if not cap or (cap.get('cap_available') or 0) < 1:
            return 'skipped', "ML no permite enviar la liga de factura en esta venta (cupo agotado o ya enviada)"
        resp2 = meli.post("/messages/action_guide/packs/%s/option" % pack_id,
                          body={'option_id': 'SEND_INVOICE_LINK', 'text': text},
                          params={'access_token': meli.access_token})
        rjson2 = resp2 and resp2.json()
        if isinstance(rjson2, dict) and not rjson2.get('error') and rjson2.get('status') not in (400, 403, 404):
            return 'sent', "enviado: %s" % text
        return 'error', "ML rechazó el mensaje: %s" % (rjson2,)

    # -- cron ---------------------------------------------------------------------------------
    @api.model
    def cron_meli_post_sale_auto(self, limit=50):
        """Cron «Meli Mensaje Postventa Automático». Sólo cuentas con el automático activo."""
        Orders = self.sudo()
        configs = self.env['mercadolibre.configuration'].sudo().search([('mercadolibre_post_sale_auto', '=', True)])
        done = 0
        for config in configs:
            dom = config._meli_post_sale_auto_domain()
            if not dom:
                continue
            days = config.mercadolibre_post_sale_auto_days or 30
            dom += [('meli_post_sale_state', '=', False),
                    ('date_created', '>=', fields.Datetime.now() - timedelta(days=days))]
            for mo in Orders.search(dom, order='id', limit=max(0, limit - done)):
                done += 1
                mo._meli_post_sale_auto_process(config)
            if done >= limit:
                break
        return done

    def _meli_post_sale_auto_process(self, config):
        self.ensure_one()
        # 1) reclamar la orden (atómico) y verificar el pack, y COMMIT antes de cualquier red
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mercadolibre_orders SET meli_post_sale_state='sending', meli_post_sale_date=now() at time zone 'UTC' "
            "WHERE id=%s AND meli_post_sale_state IS NULL RETURNING id", (self.id,))
        if not self.env.cr.fetchone():
            return
        self.invalidate_recordset(['meli_post_sale_state', 'meli_post_sale_date'])
        if self.pack_id:
            twin = self.search([('pack_id', '=', self.pack_id), ('id', '!=', self.id),
                                ('meli_post_sale_state', 'in', ('sending', 'sent'))], limit=1)
            if twin:
                self._meli_post_sale_set('skipped')
                self._meli_post_sale_commit()
                return
        self._meli_post_sale_commit()
        # 2) red (fuera de cualquier importación; la orden ya está tomada)
        try:
            state, note = self._meli_post_sale_auto_send(config)
        except Exception as e:
            _logger.warning("postventa auto %s: excepción: %s", self.order_id, e)
            if not _in_test():
                self.env.cr.rollback()
            # no sabemos si el POST salió => NO se reintenta (a lo sumo una vez)
            state, note = 'error', "error inesperado: %s" % e
        if state == 'retry':
            # nada se mandó: se libera para la próxima corrida
            self.write({'meli_post_sale_state': False})
            _logger.info("postventa auto %s: se reintenta: %s", self.order_id, note)
        else:
            self._meli_post_sale_set(state, note)
            if state == 'sent' and self.pack_id:
                self.search([('pack_id', '=', self.pack_id), ('id', '!=', self.id),
                             ('meli_post_sale_state', '=', False)]).write({'meli_post_sale_state': 'skipped'})
        self._meli_post_sale_commit()
