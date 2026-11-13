# Test #caso-K11/#caso-K10 (cron de tokens multicompañia, 401 de ML, tokens en el chatter, IVA de todas las compañias) —
# `odoo shell -d <db_de_prueba> < este_archivo`. Bloquea la red y hace ROLLBACK. NO correr contra produccion.
env = globals()["env"]  # lo inyecta `odoo shell`: declarado para el lint de Odoo (undefined-variable)
import requests, glob, os, importlib.util
from datetime import timedelta
from odoo import fields as F
requests.Session.request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("RED BLOQUEADA"))
R = []
def check(n, c):
    R.append((n, bool(c))); print(("OK   " if c else "FAIL ") + n)
def fill(model, vals):
    M = env[model]
    for fn, f in M._fields.items():
        if f.required and fn not in vals and f.store and not f.default and not f.compute and not f.related:
            if f.type == 'many2one':
                vals[fn] = env[f.comodel_name].search([], limit=1).id
            elif f.type in ('char', 'text'):
                vals[fn] = 'banco'
            elif f.type == 'selection':
                vals[fn] = f.get_values(env)[0]
    return M.create(vals)
def tax(name, comp, amount=21.0):
    vals = {'name': name, 'amount': amount, 'amount_type': 'percent', 'type_tax_use': 'sale', 'company_id': comp.id, 'price_include': False}
    if 'price_include_override' in env['account.tax']._fields:
        vals.pop('price_include'); vals['price_include_override'] = 'tax_excluded'
    if 'country_id' in env['account.tax']._fields:
        if not comp.country_id: comp.country_id = env.ref('base.ar')
        vals['country_id'] = comp.country_id.id
    if 'tax_group_id' in env['account.tax']._fields:
        _gc = 'company_id' in env['account.tax.group']._fields
        g = env['account.tax.group'].search([('company_id', '=', comp.id)] if _gc else [], limit=1)
        if not g:
            gv = {'name': 'IVA banco', 'company_id': comp.id} if _gc else {'name': 'IVA banco'}
            if 'country_id' in env['account.tax.group']._fields: gv['country_id'] = comp.country_id.id
            g = env['account.tax.group'].sudo().create(gv)
        vals['tax_group_id'] = g.id
    return env['account.tax'].with_company(comp).create(vals)

A = env.company
B = env['res.company'].create({'name': 'Cia B banco K11m', 'currency_id': A.currency_id.id, 'country_id': (A.country_id or env.ref('base.ar')).id})
env.user.company_ids = [(4, B.id)]
SELLER = '2624932094'
soon = F.Datetime.now() + timedelta(minutes=5)
CONF = env['mercadolibre.configuration'].search([], limit=1) or fill('mercadolibre.configuration', {'name': 'conf banco', 'mercadolibre_pricelist': env['product.pricelist'].search([], limit=1).id or env['product.pricelist'].create({'name': 'PL banco'}).id})
accB = fill('mercadolibre.account', {'name': 'producto 1 banco', 'configuration': CONF.id, 'company_id': B.id, 'seller_id': SELLER, 'client_id': '999',
                                     'access_token': 'APP_USR-999-101917-abcdefabcdef-' + SELLER, 'refresh_token': 'TG-abcdefabcdef123-' + SELLER,
                                     'access_token_expires_at': soon})

# --- Bug 1: el cron (self vacio) tiene que visitar la cuenta de la cia B ---
Util = type(env['meli.util'])
_orig_gni = Util.get_new_instance
calls = []
def _fake_gni(self, company=None, account=None, refresh_force=False):
    calls.append((account and account.id, refresh_force)); return None
Util.get_new_instance = _fake_gni
try:
    env['res.company'].get_meli_state()      # lo que corre el ir.cron "Get Meli State"
finally:
    Util.get_new_instance = _orig_gni
check('B1-1 cron get_meli_state (self vacio) refresca la cuenta de la cia B (no solo la del usuario) %s' % calls,
      (accB.id, True) in calls)

# --- Bug 2a: get_new_instance con 401 sin "error" dispara el refresh ---
from odoo.addons.meli_oerp_multiple.models import meli_util as MMU
Api = MMU.MeliApi
_g, _r = Api.get, getattr(Api, 'get_refresh_token', None)
refreshed = []
class _Self:
    pass
def _get(self, path, params={}, *a, **k):
    self.rjson = {'code': 'unauthorized', 'message': 'invalid access token'}; self.response = self.rjson; return self
def _refresh(self, *a, **k):
    refreshed.append(1); return None
Api.get = _get; Api.get_refresh_token = _refresh
try:
    env['ir.config_parameter'].sudo().set_param('database.is_neutralized', False)
    try:
        env['meli.util'].get_new_instance(B, accB)
    except Exception as e:
        print('   (get_new_instance termino con %r — se evalua solo si intento refrescar)' % (repr(e)[:120]))
finally:
    Api.get = _g
    if _r: Api.get_refresh_token = _r
check('B2-1 get_new_instance: 401 {"code":"unauthorized"} intenta refrescar el token', bool(refreshed))

# --- Bug 2b: el barrido de ordenes no lo lee como "no hay ordenes" ---
class _Resp:
    def json(self): return {'code': 'unauthorized', 'message': 'invalid access token'}
class _Meli:
    access_token = 'x'; seller_id = SELLER
    def need_login(self): return False
    def get(self, *a, **k): return _Resp()
res = accB.cron_process_unprocessed_orders(meli=_Meli(), days=1, limit=10)
check('B2-2 barrido con 401 => fallo visible (failed=1), no "nuevas=0" %s' % res,
      isinstance(res, dict) and res.get('failed') == 1)

# --- Bug 4: migracion (26.249, landeada como 26.287) enmascara tokens ya posteados en el chatter ---
TOK_A = 'APP_USR-999-101917-abcdefabcdef-' + SELLER; TOK_R = 'TG-abcdefabcdef123-' + SELLER
msg = accB.message_post(body="Refresh result: {'access_token': '%s', 'refresh_token': '%s'}" % (TOK_A, TOK_R))
mig = glob.glob(os.path.join(os.path.dirname(MMU.__file__), '..', 'migrations', '*.26.287', 'post-migrate.py'))
if mig:
    spec = importlib.util.spec_from_file_location('m26249', mig[0]); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    env.flush_all() if hasattr(env, 'flush_all') else env['base'].flush()
    mod.migrate(env.cr, '26.248')
    env.invalidate_all() if hasattr(env, 'invalidate_all') else env.cache.invalidate()
    body = env['mail.message'].browse(msg.id).body or ''
    check('B4-1 migracion: el access_token y el refresh_token quedan enmascarados', TOK_A not in body and TOK_R not in body and 'APP_USR-***' in body and 'TG-***' in body)
    mod.migrate(env.cr, '26.248')
    check('B4-2 migracion idempotente (segunda corrida no toca nada)', env.cr.rowcount == 0)
else:
    check('B4-1 migracion 26.287 presente', False)

# --- Bug 6: importar precio con dos IVA (uno por compañia) ---
tA = tax('IVA 21 A banco m', A); tB = tax('IVA 21 B banco m', B)
prod = env['product.product'].create({'name': 'Prod banco K11m', 'list_price': 100.0})
prod.product_tmpl_id.sudo().write({'taxes_id': [(6, 0, [tA.id, tB.id])]})
A.mercadolibre_tax_included = 'tax_excluded'
conv = prod._meli_price_converted(meli_price=121.0, config=A)
check('B6-1 multiple: importar 121 con tax_excluded => 100 (no 85,21) [%.2f]' % conv, abs(conv - 100.0) < 0.01)

env.cr.rollback()
print('TOTAL', len(R), 'FAIL', len([1 for _n, ok in R if not ok]), [n for n, ok in R if not ok])
