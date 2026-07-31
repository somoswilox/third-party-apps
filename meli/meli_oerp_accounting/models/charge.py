from odoo import fields, models, api
import json
import logging

_logger = logging.getLogger(__name__)


class MercadolibrePaymentCharge(models.Model):
    _name = "mercadolibre.payment.charge"
    _description = "Cargos de pago MercadoPago (charges_details)"
    _order = "id"

    payment_id = fields.Many2one(
        "mercadolibre.payments",
        string="Pago MeLi",
        required=True,
        ondelete="cascade",
        index=True,
    )
    order_id = fields.Many2one(
        related="payment_id.order_id",
        string="Orden MeLi",
        store=True,
    )

    # --- Datos directos del JSON de MercadoPago charges_details ---
    charge_id = fields.Char(
        string="Charge ID",
        help="ID del cargo en MercadoPago (ej: '153001226550-001')",
        index=True,
    )
    external_charge_id = fields.Char(string="External Charge ID")
    name = fields.Char(string="Nombre del cargo", help="Ej: 'tax_withholding-isr', 'meli_fee'")
    charge_type = fields.Selection(
        [
            ("tax", "Tax (Retención)"),
            ("fee", "Fee (Comisión)"),
            ("shipping", "Shipping (Envío)"),
            ("coupon", "Coupon (Cupón)"),
            ("other", "Otro"),
        ],
        string="Tipo",
    )
    amount_original = fields.Float(string="Monto original", digits=(16, 2))
    amount_refunded = fields.Float(string="Monto reembolsado", digits=(16, 2))
    base_amount = fields.Float(
        string="Monto base",
        digits=(16, 2),
        help="Monto base sobre el cual se calcula el cargo",
    )
    rate = fields.Float(
        string="Tasa (%)",
        digits=(16, 4),
        help="Porcentaje aplicado sobre el monto base",
    )
    date_created = fields.Datetime(string="Fecha creación")

    # --- Metadata del cargo ---
    mov_detail = fields.Char(string="Detalle movimiento", help="metadata.mov_detail")
    mov_financial_entity = fields.Char(
        string="Entidad financiera",
        help="metadata.mov_financial_entity (ej: 'isr', 'iva')",
    )
    mov_type = fields.Char(string="Tipo movimiento", help="metadata.mov_type (ej: 'expense')")
    source = fields.Char(string="Origen", help="metadata.source")
    source_detail = fields.Char(
        string="Detalle origen",
        help="metadata.source_detail (ej: 'isr_charge', 'iva_charge')",
    )
    tax_status = fields.Char(string="Estado impuesto", help="metadata.tax_status (ej: 'applied')")

    # --- Cuentas ---
    account_from = fields.Char(string="Cuenta origen", help="accounts.from")
    account_to = fields.Char(string="Cuenta destino", help="accounts.to")

    # --- Mapeo a Odoo ---
    meli_tax_id = fields.Many2one(
        "mercadolibre.tax",
        string="Regla de mapeo",
        help="Regla de mercadolibre.tax que mapeó este cargo a un impuesto Odoo",
    )
    account_tax_id = fields.Many2one(
        "account.tax",
        string="Impuesto Odoo",
        help="Impuesto de Odoo aplicado según la regla de mapeo",
    )

    # --- JSON completo para referencia ---
    raw_json = fields.Text(string="JSON original", help="JSON completo del cargo para referencia")

    @api.model
    def create_from_charge_detail(self, payment, charge_detail):
        """
        Crea un registro de cargo a partir de un dict de charges_details de MercadoPago.

        :param payment: recordset mercadolibre.payments
        :param charge_detail: dict con la estructura de un elemento de charges_details
        :returns: recordset mercadolibre.payment.charge creado
        """
        metadata = charge_detail.get("metadata") or {}
        accounts = charge_detail.get("accounts") or {}
        amounts = charge_detail.get("amounts") or {}

        charge_type = charge_detail.get("type", "other")
        if charge_type not in ("tax", "fee", "shipping", "coupon"):
            charge_type = "other"

        vals = {
            "payment_id": payment.id,
            "charge_id": charge_detail.get("id", ""),
            "external_charge_id": charge_detail.get("external_charge_id", ""),
            "name": charge_detail.get("name", ""),
            "charge_type": charge_type,
            "amount_original": amounts.get("original", 0),
            "amount_refunded": amounts.get("refunded", 0),
            "base_amount": charge_detail.get("base_amount", 0),
            "rate": charge_detail.get("rate", 0),
            "date_created": charge_detail.get("date_created") and charge_detail["date_created"][:19].replace("T", " ") or False,
            # Metadata
            "mov_detail": metadata.get("mov_detail", ""),
            "mov_financial_entity": metadata.get("mov_financial_entity", ""),
            "mov_type": metadata.get("mov_type", ""),
            "source": metadata.get("source", ""),
            "source_detail": metadata.get("source_detail", ""),
            "tax_status": metadata.get("tax_status", ""),
            # Accounts
            "account_from": accounts.get("from", ""),
            "account_to": accounts.get("to", ""),
            # Raw JSON
            "raw_json": json.dumps(charge_detail, indent=2, default=str),
        }

        # Buscar o crear regla de mapeo de impuestos
        charge_name = charge_detail.get("name", "")
        if charge_type in ("tax", "fee", "shipping"):
            # Auto-crear regla en draft si no existe
            tax_rule = self.env["mercadolibre.tax"].get_or_create_from_charge(
                charge_type=charge_type,
                charge_name=charge_name,
                metadata=metadata,
            )
            if tax_rule:
                vals["meli_tax_id"] = tax_rule.id
                if tax_rule.account_tax_id:
                    vals["account_tax_id"] = tax_rule.account_tax_id.id

        return self.create(vals)
