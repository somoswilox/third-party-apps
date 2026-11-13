
import logging
_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UniqueIndex vs _sql_constraints  (Odoo < 17  vs  Odoo 17+)
# ---------------------------------------------------------------------------
HAS_UNIQUE_INDEX = False
_OdooUniqueIndex = None
try:
    from odoo.models import UniqueIndex as _OdooUniqueIndex
    HAS_UNIQUE_INDEX = True
except (ImportError, AttributeError):
    pass

def UniqueIndex(fields_expr, message=None):
    if _OdooUniqueIndex is not None:
        if message is not None:
            return _OdooUniqueIndex('(%s)' % fields_expr, message=message)
        return _OdooUniqueIndex('(%s)' % fields_expr)
    return None

def sql_constraints_if_no_unique_index(constraints):
    if HAS_UNIQUE_INDEX:
        return []
    return [
        (name, 'unique(%s)' % fields, msg)
        for name, fields, msg in constraints
    ]
# ---------------------------------------------------------------------------
# Constraint (arbitrary SQL CHECK constraints)  —  Odoo 19+
# ---------------------------------------------------------------------------
_OdooConstraint = None
try:
    from odoo.models import Constraint as _OdooConstraint
except (ImportError, AttributeError):
    pass

def Constraint(sql_expr, message=None):
    if _OdooConstraint is not None:
        if message is not None:
            return _OdooConstraint(sql_expr, message=message)
        return _OdooConstraint(sql_expr)
    return None

def sql_constraints_if_no_constraint(constraints):
    if _OdooConstraint is not None:
        return []
    return [(name, sql_expr, msg) for name, sql_expr, msg in constraints]
# ---------------------------------------------------------------------------

acc_pay_ref = "memo"
acc_pay_group_ref = "communication"
invoice_origin = "invoice_origin"
report_invoices = "account.account_invoices"
#report_invoices = "l10n_ar_report_fe.account_fe_invoices"
#report_invoices = "l10n_ar_electronic_invoice_report.action_electronic_invoice"
report_invoices_name = ""
#report_invoices_name = "l10n_ar_electronic_invoice_report.report_electronic_invoice_copy_1_copy_1"
report_invoices_id = False
#report_invoices_id = 1517
posted_statuses = ['posted']
# 'canceled' (una ele) = estado de account.payment en Odoo 18/19; 'cancel'/'cancelled' en versiones previas.
cancel_statuses = ['cancel', 'cancelled', 'canceled']
draft_statuses = ['draft']
valid_payment_status = ['paid']
draft_payment_status = ['draft','in_process']
def report_render( report, res_ids=None, data=None):
    #report = self.env['ir.actions.report']._get_report_from_name(REPORT_ID)
    #pdf = report._render_qweb_pdf(report.id,res_ids=self.ids)
    return report._render_qweb_pdf( report_ref=report.id, res_ids=res_ids,data=data)

def order_create_invoices( sale_order, grouped=False, final=False, date=None ):
	return sale_order._create_invoices(grouped=grouped, final=final, date=date)

def payment_post( self ):
    """Validar un account.payment (action_post y, si existe, action_validate).

    caso-K52 (31-oct-2026): antes cada paso iba en `except: pass` SIN savepoint. Un error de base de datos
    (p.ej. IntegrityError account_move_unique_name al numerar el asiento con un talonario de recibos,
    o un choque concurrente) se tragaba en silencio y dejaba la TRANSACCION ABORTADA: lo siguiente
    fallaba con 'current transaction is aborted', el error raiz no quedaba en ningun lado y se perdia
    la venta entera. Ahora cada paso va en savepoint: un error funcional (UserError) se registra y se
    sigue como antes; un error de BASE DE DATOS se propaga para que quien llama (confirm_ml) revierta
    el cobro entero y avise.
    """
    import psycopg2
    for step in ('action_post', 'action_validate'):
        if not hasattr(self, step):
            continue
        try:
            with self.env.cr.savepoint():
                getattr(self, step)()
        except psycopg2.Error:
            raise
        except Exception as e:
            _logger.info("payment_post: %s de %s no aplicado: %s", step, self, e)
    

def payment_group_post( self ):
    """
    Validar un account.payment.group de forma compatible (mismo patron que
    payment_group_cancel):
    - account_payment_group (ingadhoc / odoo-argentina): post()
    - account_payment_group_pro (un cliente 18.0) y similares: action_post() (NO tienen post())
    Antes era self.post() fijo => "'account.payment.group' object has no attribute 'post'"
    en cada pago / comision / envio ML (un cliente). post() va primero: sin cambio para
    quien ya lo tenia.
    """
    if hasattr(self, 'post'):
        return self.post()
    if hasattr(self, 'action_post'):
        return self.action_post()
    from odoo.exceptions import UserError
    raise UserError(
        "No se pudo validar el grupo de pagos (%s): el modelo no tiene 'post' "
        "ni 'action_post'. Revisar el modulo de grupos de pago instalado." % self._name)


# Alias: payments.py post_payment / post_supplier_payment / post_supplier_payment_shipment
# llaman payment_post_group(), que nunca existio (NameError latente).
payment_post_group = payment_group_post


def payment_cancel(payment):
    """
    Cancelar un account.payment de forma compatible:
    - Odoo 13+ : action_cancel()
    - Algunos módulos: cancel()
    """
    if not payment:
        return False

    if hasattr(payment, 'action_cancel'):
        return payment.action_cancel()
    if hasattr(payment, 'cancel'):
        return payment.cancel()

    # Fallback genérico
    return payment.write({'state': 'cancelled'})


def payment_group_cancel(payment_group):
    """
    Cancelar un account.payment.group de forma compatible:
    - OCA payment_group suele tener action_cancel() o cancel()
    """
    if not payment_group:
        return False

    if hasattr(payment_group, 'action_cancel'):
        return payment_group.action_cancel()
    if hasattr(payment_group, 'cancel'):
        return payment_group.cancel()

    return payment_group.write({'state': 'cancelled'})
