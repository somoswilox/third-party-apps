
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
cancel_statuses = ['cancel', 'cancelled']
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
    try:
        #state in process
        self.action_post()
    except:
        pass;
    
    try:
        #state in paid
        self.action_validate()
    except:
        pass;
    

def payment_group_post( self ):
    return self.post()


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
