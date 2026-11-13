# -*- coding: utf-8 -*-
"""26.375 (caso-K10 cliente G) — «Stock por depósito: Odoo vs Mercado Libre».

Comparativa como el modal «Stock en tus depósitos» del panel de vendedores de ML, por vinculación de variante:
  Depósito ML | logística (FLEX, …) | ubicación Odoo mapeada | Odoo disponible | ML publicado | estado | Total.

- La lectura de ML (GET /user-products/{id}/stock) se hace SÓLO al abrir el asistente o al «Releer desde ML»:
  una llamada por click, en una transacción corta. Nada de computes que peguen a ML por fila.
- «Odoo disponible» usa el MISMO cálculo que publica 26.363: `_meli_available_quantity` con
  `meli_stock_force_location_ids` = la ubicación mapeada (método de cantidad, kits, reglas de stock).
- El resultado queda GUARDADO en la vinculación (`meli_wh_*`): badge del botón, columna y filtro de la lista.
  También se actualiza al publicar stock por depósito (sin red extra: se usa lo que la publicación ya calculó).

Además (#caso-K69): alcance por depósito ML en las reglas de stock (meli_oerp.sku.rule, meli_oerp_stock).
"""
import logging
from datetime import datetime

from odoo import api, fields, models
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

WH_STATES = [
    ('none', 'Sin comparar'),
    ('ok', 'Igual'),
    ('diff', 'Con diferencias'),
    ('unmapped', 'Depósito sin mapeo'),
    ('error', 'Error al leer ML'),
]

LINE_STATES = [
    ('ok', 'Igual'),
    ('diff', 'Diferencia'),
    ('unmapped_ml', 'Depósito sin mapeo'),
    ('missing_ml', 'No figura en ML'),
    ('unmapped_odoo', 'Ubicación sin depósito ML'),
    ('ml_managed', 'Gestionado por ML'),
]

# services_stock_location del store (GET /users/{id}/stores/search) -> etiqueta de logística.
_SERVICE_LABELS = {
    'self_service': 'FLEX',
    'flex': 'FLEX',
    'xd_drop_off': 'Colecta',
    'cross_docking': 'Colecta',
    'drop_off': 'Drop-off',
    'fulfillment': 'Full',
}

_POST_KEY = 'meli_wh_post'


def _int(v):
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _logistic_label(services):
    out = []
    for tok in (services or '').replace(';', ',').split(','):
        tok = tok.strip()
        if not tok:
            continue
        lab = _SERVICE_LABELS.get(tok.lower(), tok)
        if lab not in out:
            out.append(lab)
    return ' · '.join(out)


def _wh_badge(state, qty):
    if not state or state == 'none':
        return _('Depósitos ML: comparar')
    if state == 'error':
        return _('Depósitos ML: error')
    return _('Depósitos ML: %s u.') % '{:,}'.format(int(qty or 0)).replace(',', '.')


def _post_store(env):
    """Bolsa por transacción para pasar lo que calculó la publicación al binding (sin red extra)."""
    return env.cr.precommit.data.setdefault(_POST_KEY, {})


# ---------------------------------------------------------------------------
# Reglas de stock: alcance por depósito ML (#caso-K69)
# ---------------------------------------------------------------------------
class MeliSkuRuleStockLocation(models.Model):
    _inherit = "meli_oerp.sku.rule"

    meli_stock_location_ids = fields.Many2many(
        'mercadolibre.account.stock_location', 'meli_sku_rule_ml_stock_location_rel', 'rule_id', 'stock_location_id',
        string='Depósitos ML',
        help='Sólo reglas de tipo Stock. Vacío = todos los depósitos. Con depósitos: la regla se aplica sólo al '
             'publicar el stock de esos depósitos, y únicamente si la cuenta tiene «Publicar stock por depósito '
             '(según mapeo)» activo. Un depósito específico gana a «todos».')

    def _meli_stock_rules_in_scope(self):
        """Depósito ML en publicación (contexto `meli_stock_store_location_id`, lo pone
        _meli_stock_locations_by_mapping): primero las reglas de ESE depósito, después las de todos.
        Sin depósito en contexto (flag apagado / publicación total): sólo las reglas sin depósitos."""
        generic = self.filtered(lambda r: not r.meli_stock_location_ids)
        depot_id = self.env.context.get('meli_stock_store_location_id')
        if not depot_id:
            return [generic]
        specific = self.filtered(lambda r: depot_id in r.meli_stock_location_ids.ids)
        return [specific, generic]


# ---------------------------------------------------------------------------
# Vinculación de variante: estado guardado + comparación + asistente
# ---------------------------------------------------------------------------
class MercadoLibreProductWhStock(models.Model):
    _inherit = "mercadolibre.product"

    meli_wh_state = fields.Selection(WH_STATES, string='Depósitos', default='none', index=True, copy=False,
        help='Comparación por depósito Odoo vs Mercado Libre. Se actualiza al abrir «Depósitos ML», al releer '
             'o al publicar stock por depósito.')
    meli_wh_qty_ml = fields.Integer(string='Depósitos ML: unidades en ML', copy=False)
    meli_wh_qty_odoo = fields.Integer(string='Depósitos ML: unidades en Odoo', copy=False)
    meli_wh_diff_count = fields.Integer(string='Depósitos con diferencia', copy=False)
    meli_wh_date = fields.Datetime(string='Depósitos: comparado el', copy=False)
    meli_wh_badge = fields.Char(string='Depósitos ML (botón)', compute='_compute_meli_wh_badge')

    @api.depends('meli_wh_state', 'meli_wh_qty_ml')
    def _compute_meli_wh_badge(self):
        for b in self:
            b.meli_wh_badge = _wh_badge(b.meli_wh_state, b.meli_wh_qty_ml)

    # ---- comparación (sin red) ----------------------------------------------
    def _meli_wh_publishable_locations(self):
        """Ubicaciones Odoo desde las que la configuración publica (sin consultar ML: no-Full)."""
        self.ensure_one()
        account = self.connection_account
        config = account.configuration or account.company_id
        company = account.company_id or self.env.company
        Loc = self.env['stock.location'].sudo()
        locs = Loc
        if 'publish_stock' in config._fields and config.publish_stock and 'publish_stock_locations' in config._fields:
            locs = config.publish_stock_locations
        if not locs and 'mercadolibre_stock_location_to_post_many' in config._fields:
            locs = config.mercadolibre_stock_location_to_post_many
        if not locs and 'mercadolibre_stock_location_to_post' in config._fields:
            locs = config.mercadolibre_stock_location_to_post
        if not locs and 'mercadolibre_active' in Loc._fields:
            locs = Loc.search([('mercadolibre_active', '=', True), ('company_id', '=', company.id)])
        lt = 'mercadolibre_logistic_type' in Loc._fields
        return locs.filtered(lambda l: l.usage == 'internal'
                             and not (lt and l.mercadolibre_logistic_type and 'fulfillment' in l.mercadolibre_logistic_type))

    def _meli_wh_odoo_qty(self, locations, depot=None):
        """Lo que publicaría Odoo para `locations` (mismo cálculo que 26.363)."""
        self.ensure_one()
        account = self.connection_account
        ctx = {'meli_stock_force_location_ids': locations.ids}
        if depot and account.meli_stock_by_location_mapping:
            ctx['meli_stock_store_location_id'] = depot.id
        qty = self.product_id.with_context(**ctx)._meli_available_quantity(
            meli_id=self.conn_id, meli=False, config=account.configuration)
        return max(0, _int(qty))

    def _meli_wh_compare(self, data):
        """Filas de la comparación a partir del JSON del GET /user-products/{id}/stock (sin red)."""
        self.ensure_one()
        account = self.connection_account
        SL = self.env['mercadolibre.account.stock_location'].sudo()
        depots = SL.search([('account_id', '=', account.id)])
        by_store = {str(d.meli_store_id): d for d in depots if d.meli_store_id}
        by_node = {str(d.network_node_id): d for d in depots if d.network_node_id}
        lines = []
        seen = SL
        has_seller_wh = False
        seq = 0
        for loc in (data or {}).get('locations') or []:
            seq += 10
            ltype = loc.get('type') or ''
            store = loc.get('store_id')
            node = loc.get('network_node_id')
            qty_ml = _int(loc.get('quantity'))
            vals = {'sequence': seq, 'loc_type': ltype, 'store_id': store and str(store) or False,
                    'network_node_id': node and str(node) or False, 'qty_ml': qty_ml, 'has_ml': True}
            if ltype == 'meli_facility':
                vals.update(name=_('Full (depósito de Mercado Libre)'), logistic='Full', state='ml_managed')
            elif ltype == 'seller_warehouse':
                has_seller_wh = True
                depot = (store and by_store.get(str(store))) or (node and by_node.get(str(node))) or SL
                seen |= depot
                vals.update(name=depot.name or str(store or node or '?'),
                            logistic=_logistic_label(depot.services_stock_location),
                            stock_location_id=depot.id or False)
                if depot and depot.odoo_location_id:
                    q = self._meli_wh_odoo_qty(depot.odoo_location_id, depot)
                    vals.update(odoo_location_id=depot.odoo_location_id.id, qty_odoo=q, has_odoo=True,
                                state='ok' if q == qty_ml else 'diff')
                else:
                    vals.update(state='unmapped_ml')
            else:
                # selling_address (vendedor de un solo origen): Odoo = el total publicable de siempre.
                q = max(0, _int(self.product_id._meli_available_quantity(
                    meli_id=self.conn_id, meli=False, config=account.configuration)))
                vals.update(name=_('Stock propio (dirección de venta)'), logistic='',
                            qty_odoo=q, has_odoo=True, state='ok' if q == qty_ml else 'diff')
            vals['diff'] = (vals['qty_odoo'] - qty_ml) if vals.get('has_odoo') else 0
            lines.append(vals)
        if has_seller_wh:
            # depósitos mapeados de la cuenta que ML no lista para esta publicación
            for depot in (depots - seen).filtered(lambda d: d.odoo_location_id and d.status != 'inactive'):
                seq += 10
                q = self._meli_wh_odoo_qty(depot.odoo_location_id, depot)
                lines.append({'sequence': seq, 'loc_type': 'seller_warehouse', 'name': depot.name,
                              'store_id': depot.meli_store_id, 'network_node_id': depot.network_node_id,
                              'logistic': _logistic_label(depot.services_stock_location),
                              'stock_location_id': depot.id, 'odoo_location_id': depot.odoo_location_id.id,
                              'qty_odoo': q, 'has_odoo': True, 'qty_ml': 0, 'has_ml': False, 'diff': 0,
                              'state': 'missing_ml'})
            # ubicaciones desde las que se publica que no tienen depósito ML asignado
            mapped_locs = depots.mapped('odoo_location_id')
            for l in self._meli_wh_publishable_locations() - mapped_locs:
                seq += 10
                q = self._meli_wh_odoo_qty(l)
                lines.append({'sequence': seq, 'loc_type': 'odoo', 'name': l.display_name, 'logistic': '',
                              'odoo_location_id': l.id, 'qty_odoo': q, 'has_odoo': True,
                              'qty_ml': 0, 'has_ml': False, 'diff': 0, 'state': 'unmapped_odoo'})
        return lines

    @api.model
    def _meli_wh_summary(self, lines, error=None):
        if error:
            return {'meli_wh_state': 'error', 'meli_wh_diff_count': 0}
        own = [l for l in lines if l.get('has_ml') and l['state'] != 'ml_managed']
        mapped = [l for l in own if l.get('has_odoo')]
        states = {l['state'] for l in lines}
        n_diff = len([l for l in lines if l['state'] == 'diff'])
        if n_diff:
            st = 'diff'
        elif states & {'unmapped_ml', 'missing_ml'}:
            st = 'unmapped'
        elif own:
            st = 'ok'
        else:
            st = 'none'
        return {
            'meli_wh_state': st,
            'meli_wh_qty_ml': sum(l['qty_ml'] for l in own),
            'meli_wh_qty_odoo': sum(l['qty_odoo'] for l in mapped),
            'meli_wh_diff_count': n_diff,
        }

    def _meli_wh_write_summary(self, vals):
        vals = dict(vals, meli_wh_date=fields.Datetime.now())
        self.sudo().write(vals)

    # ---- lectura de ML (UNA llamada, sólo por click) --------------------------
    def _meli_wh_read_ml(self):
        """(data, error). GET /user-products/{id}/stock."""
        self.ensure_one()
        account = self.connection_account
        if not self.meli_user_product_id:
            return None, _('La vinculación no tiene «Product User Id» (user_product_id): usá «Check & Test '
                           'Multiwarehouse» en la cuenta para completarlo.')
        try:
            meli = self.env['meli.util'].get_new_instance(account.company_id, account)
            if meli.need_login():
                return None, _('La cuenta %s no está conectada a Mercado Libre.') % account.name
            data, _xver = meli.get_user_product_stock_with_version(self.meli_user_product_id, meli.access_token)
        except Exception as e:
            _logger.warning("meli_wh: GET stock %s: %s", self.meli_user_product_id, e)
            return None, str(e)
        if not isinstance(data, dict):
            return None, _('Respuesta inesperada de Mercado Libre: %s') % str(data)[:300]
        if data.get('error') or (isinstance(data.get('status'), int) and data['status'] >= 400):
            return None, '%s %s' % (data.get('error') or data.get('status'), data.get('message') or '')
        return data, None

    def _meli_wh_refresh(self):
        """Lee ML, compara, guarda el estado. Devuelve (lines, error)."""
        self.ensure_one()
        data, error = self._meli_wh_read_ml()
        lines = [] if error else self._meli_wh_compare(data)
        self._meli_wh_write_summary(self._meli_wh_summary(lines, error))
        return lines, error

    def action_meli_wh_stock_open(self):
        self.ensure_one()
        lines, error = self._meli_wh_refresh()
        wiz = self.env['mercadolibre.product.wh.stock'].create({
            'binding_id': self.id,
            'error': error or False,
            'line_ids': [(0, 0, l) for l in lines],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock en depósitos: Odoo vs Mercado Libre'),
            'res_model': 'mercadolibre.product.wh.stock',
            'res_id': wiz.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, dialog_size='extra-large'),
        }

    # ---- al publicar: usar lo que ya calculó la publicación (sin red extra) ----
    def _product_post_stock_one(self, context=None, meli=None, optimize=False):
        if len(self) != 1:
            return super()._product_post_stock_one(context=context, meli=meli, optimize=optimize)
        bag = _post_store(self.env)
        key = self.product_id.id
        bag.pop(key, None)
        res = super()._product_post_stock_one(context=context, meli=meli, optimize=optimize)
        info = bag.pop(key, None)
        try:
            self._meli_wh_after_post(res, info)
        except Exception as e:  # nunca romper la publicación por el indicador
            _logger.warning("meli_wh: no pude actualizar el estado de depósitos de %s: %s", self.conn_id, e)
        return res

    def _meli_wh_after_post(self, res, info):
        failed = isinstance(res, dict) and (res.get('error') or res.get('warning')
                                            or (isinstance(res.get('status'), int) and res['status'] >= 400))
        if failed:
            return
        if info:
            self._meli_wh_write_summary({
                'meli_wh_state': 'unmapped' if info.get('unmapped') else 'ok',
                'meli_wh_qty_ml': sum(_int(l.get('quantity')) for l in info.get('out') or []),
                'meli_wh_qty_odoo': _int(info.get('qty_odoo')),
                'meli_wh_diff_count': 0,
            })
        elif self.meli_wh_state not in ('none', 'error') and self.connection_account.multiwarehouse:
            # se publicó el total (reparto proporcional): la comparación guardada ya no vale
            self.sudo().write({'meli_wh_state': 'none'})


class ProductProductWhStock(models.Model):
    _inherit = "product.product"

    meli_wh_state = fields.Selection(WH_STATES, string='Depósitos ML', compute='_compute_meli_wh')
    meli_wh_qty_ml = fields.Integer(string='Depósitos ML: unidades', compute='_compute_meli_wh')
    meli_wh_binding_count = fields.Integer(compute='_compute_meli_wh')
    meli_wh_badge = fields.Char(string='Depósitos ML (botón)', compute='_compute_meli_wh')

    def _meli_wh_bindings(self):
        # sudo: la ficha de producto la abren usuarios sin acceso a las vinculaciones (el botón tiene grupo)
        return self.sudo().mercadolibre_bindings.filtered(lambda b: b.meli_user_product_id)

    @api.depends('mercadolibre_bindings.meli_wh_state', 'mercadolibre_bindings.meli_wh_qty_ml')
    def _compute_meli_wh(self):
        for p in self:
            _meli_wh_aggregate(p, p._meli_wh_bindings())

    def action_meli_wh_stock_open(self):
        return _meli_wh_open_bindings(self, self._meli_wh_bindings().sudo(False))


class ProductTemplateWhStock(models.Model):
    _inherit = "product.template"

    meli_wh_state = fields.Selection(WH_STATES, string='Depósitos ML', compute='_compute_meli_wh')
    meli_wh_qty_ml = fields.Integer(string='Depósitos ML: unidades', compute='_compute_meli_wh')
    meli_wh_binding_count = fields.Integer(compute='_compute_meli_wh')
    meli_wh_badge = fields.Char(string='Depósitos ML (botón)', compute='_compute_meli_wh')

    def _meli_wh_bindings(self):
        return self.product_variant_ids._meli_wh_bindings()

    @api.depends('product_variant_ids.mercadolibre_bindings.meli_wh_state',
                 'product_variant_ids.mercadolibre_bindings.meli_wh_qty_ml')
    def _compute_meli_wh(self):
        for t in self:
            _meli_wh_aggregate(t, t._meli_wh_bindings())

    def action_meli_wh_stock_open(self):
        return _meli_wh_open_bindings(self, self._meli_wh_bindings().sudo(False))


def _meli_wh_aggregate(rec, binds):
    rec.meli_wh_binding_count = len(binds)
    rec.meli_wh_qty_ml = sum(binds.mapped('meli_wh_qty_ml'))
    states = set(binds.mapped('meli_wh_state'))
    for st in ('error', 'diff', 'unmapped', 'none', 'ok'):
        if st in states:
            rec.meli_wh_state = st
            break
    else:
        rec.meli_wh_state = 'none'
    rec.meli_wh_badge = _wh_badge(rec.meli_wh_state, rec.meli_wh_qty_ml)


def _meli_wh_open_bindings(rec, binds):
    rec.ensure_one()
    if len(binds) == 1:
        return binds.action_meli_wh_stock_open()
    return {
        'type': 'ir.actions.act_window',
        'name': _('Depósitos ML'),
        'res_model': 'mercadolibre.product',
        'view_mode': 'list,form',
        'domain': [('id', 'in', binds.ids)],
        'target': 'current',
    }


# ---------------------------------------------------------------------------
# Asistente (transient)
# ---------------------------------------------------------------------------
class MercadoLibreProductWhStockWizard(models.TransientModel):
    _name = "mercadolibre.product.wh.stock"
    _description = "Stock por depósito: Odoo vs Mercado Libre"

    binding_id = fields.Many2one('mercadolibre.product', string='Vinculación', required=True, ondelete='cascade')
    account_id = fields.Many2one(related='binding_id.connection_account', string='Cuenta ML')
    product_id = fields.Many2one(related='binding_id.product_id', string='Producto')
    conn_id = fields.Char(related='binding_id.conn_id', string='Publicación')
    user_product_id = fields.Char(related='binding_id.meli_user_product_id', string='User product')
    by_mapping = fields.Boolean(related='binding_id.connection_account.meli_stock_by_location_mapping',
                                string='Publica por depósito (según mapeo)')
    state = fields.Selection(related='binding_id.meli_wh_state', string='Estado')
    read_date = fields.Datetime(related='binding_id.meli_wh_date', string='Leído de ML')
    error = fields.Char(string='Error')
    line_ids = fields.One2many('mercadolibre.product.wh.stock.line', 'wizard_id', string='Depósitos')
    total_ml = fields.Integer(string='Total ML', compute='_compute_totals')
    total_odoo = fields.Integer(string='Total Odoo', compute='_compute_totals')
    total_diff = fields.Integer(string='Diferencia', compute='_compute_totals')
    total_label = fields.Char(compute='_compute_totals')

    @api.depends('line_ids.qty_ml', 'line_ids.qty_odoo', 'line_ids.state')
    def _compute_totals(self):
        for w in self:
            own = w.line_ids.filtered(lambda l: l.has_ml and l.state != 'ml_managed')
            w.total_ml = sum(own.mapped('qty_ml'))
            w.total_odoo = sum(own.filtered('has_odoo').mapped('qty_odoo'))
            w.total_diff = w.total_odoo - w.total_ml
            w.total_label = _('Total: Odoo %(o)s u. · Mercado Libre %(m)s u.', o=w.total_odoo, m=w.total_ml)

    def _reopen(self):
        return self.binding_id.action_meli_wh_stock_open()

    def action_reload(self):
        self.ensure_one()
        return self._reopen()

    def action_publish(self):
        self.ensure_one()
        self.binding_id.product_post_stock()
        return self._reopen()

    def action_edit_mapping(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('meli_oerp_multiple.action_meli_account_stock_location')
        action['domain'] = [('account_id', '=', self.account_id.id)]
        action['context'] = {'default_account_id': self.account_id.id}
        action['target'] = 'current'
        return action


class MercadoLibreProductWhStockLine(models.TransientModel):
    _name = "mercadolibre.product.wh.stock.line"
    _description = "Stock por depósito: fila"
    _order = "sequence, id"

    wizard_id = fields.Many2one('mercadolibre.product.wh.stock', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Depósito')
    loc_type = fields.Char(string='Tipo ML')
    logistic = fields.Char(string='Logística')
    store_id = fields.Char(string='Store ID')
    network_node_id = fields.Char(string='Nodo')
    stock_location_id = fields.Many2one('mercadolibre.account.stock_location', string='Depósito ML')
    odoo_location_id = fields.Many2one('stock.location', string='Ubicación Odoo')
    has_odoo = fields.Boolean()
    has_ml = fields.Boolean()
    qty_odoo = fields.Integer(string='Odoo disponible')
    qty_ml = fields.Integer(string='ML publicado')
    diff = fields.Integer(string='Diferencia')
    state = fields.Selection(LINE_STATES, string='Estado (código)')
    state_label = fields.Char(string='Estado', compute='_compute_state_label')

    @api.depends('state', 'diff', 'qty_ml', 'has_ml')
    def _compute_state_label(self):
        labels = {
            'ok': '✔ igual',
            'unmapped_ml': 'ⓘ depósito sin ubicación Odoo (no se modifica)',
            'missing_ml': 'ⓘ mapeado, pero ML no lo lista en esta publicación',
            'unmapped_odoo': 'ⓘ ubicación publicable sin depósito ML',
            'ml_managed': 'ⓘ lo gestiona Mercado Libre',
        }
        for l in self:
            if l.state == 'diff':
                l.state_label = '⚠ diferencia %+d' % l.diff
            else:
                l.state_label = labels.get(l.state, '')
            if l.has_ml and l.state != 'ml_managed' and l.qty_ml == 0:
                l.state_label = (l.state_label + ' · ⚠ en 0 en ML').strip(' ·')
