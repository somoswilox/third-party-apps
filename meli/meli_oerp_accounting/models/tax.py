from odoo import fields, models, api
import logging

_logger = logging.getLogger(__name__)


class MercadolibreTax(models.Model):
    _name = "mercadolibre.tax"
    _description = "Mapeo de impuestos MercadoLibre a Odoo"
    _order = "sequence, id"

    name = fields.Char(
        string="Nombre",
        required=True,
        help="Nombre descriptivo para esta regla de mapeo de impuesto",
    )
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("confirmed", "Confirmado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        help="Borrador: importado automáticamente, pendiente de asignar impuesto Odoo. "
             "Confirmado: regla lista con impuesto Odoo asignado.",
    )

    # --- Criterios de matching con datos de MercadoPago ---
    meli_charge_type = fields.Selection(
        [
            ("tax", "Tax (Retención / Withholding)"),
            ("fee", "Fee (Comisión)"),
            ("shipping", "Shipping (Envío)"),
        ],
        string="Tipo de cargo MeLi",
        required=True,
        default="tax",
        help="Tipo de cargo en charges_details del JSON de MercadoPago",
    )
    meli_charge_name = fields.Char(
        string="Nombre de cargo MeLi",
        help="Nombre exacto del cargo en charges_details, ej: 'tax_withholding-isr', "
             "'tax_withholding-iva'. Dejar vacío para matchear cualquier cargo del tipo seleccionado.",
    )
    meli_financial_entity = fields.Char(
        string="Entidad financiera MeLi",
        help="Valor de metadata.mov_financial_entity, ej: 'isr', 'iva'. "
             "Dejar vacío para matchear cualquier entidad del tipo seleccionado.",
    )
    meli_source_detail = fields.Char(
        string="Detalle origen MeLi",
        help="Valor de metadata.source_detail, ej: 'isr_charge', 'iva_charge'. "
             "Dejar vacío para no filtrar por este campo.",
    )

    # --- Mapeo a Odoo ---
    account_tax_id = fields.Many2one(
        "account.tax",
        string="Impuesto Odoo",
        help="Impuesto de Odoo que corresponde a esta retención/cargo de MercadoLibre. "
             "Para retenciones ISR/IVA: instalar el módulo 'Withholding Taxes on Payment' "
             "(l10n_account_withholding_tax) y marcar el impuesto como 'Retención al pago' "
             "en Contabilidad > Configuración > Impuestos. Esto permite que la retención se "
             "aplique al registrar el pago en vez de reducir el total de la factura.",
    )
    is_withholding_on_payment = fields.Boolean(
        string="Retención al pago",
        compute="_compute_is_withholding_on_payment",
        store=True,
        help="Indica si el impuesto Odoo está configurado como retención al momento del pago. "
             "Requiere el módulo 'Withholding Taxes on Payment' (l10n_account_withholding_tax) "
             "instalado. Activar desde Contabilidad > Configuración > Impuestos, marcando "
             "'Es retención al pago' en el impuesto correspondiente. "
             "Cuando está activo, la retención se aplica al registrar el pago (reduciendo el "
             "monto en banco) y la factura queda por el total que pagó el cliente.",
    )

    @api.depends('account_tax_id')
    def _compute_is_withholding_on_payment(self):
        has_field = 'is_withholding_tax_on_payment' in self.env['account.tax']._fields
        for rec in self:
            if has_field and rec.account_tax_id:
                rec.is_withholding_on_payment = rec.account_tax_id.is_withholding_tax_on_payment
            else:
                rec.is_withholding_on_payment = False

    def action_confirm(self):
        for rec in self:
            rec.state = "confirmed"

    def action_draft(self):
        for rec in self:
            rec.state = "draft"

    def match_charge(self, charge_type, charge_name, metadata):
        """
        Busca la primera regla de mapeo que coincida con los datos del cargo.
        Solo matchea reglas en estado 'confirmed' que tengan account_tax_id asignado.

        :param charge_type: str - tipo del cargo ('tax', 'fee', 'shipping')
        :param charge_name: str - nombre del cargo (ej: 'tax_withholding-isr')
        :param metadata: dict - metadata del cargo de MercadoPago
        :returns: recordset mercadolibre.tax (puede ser vacío)
        """
        domain = [
            ("meli_charge_type", "=", charge_type),
            ("company_id", "=", self.env.company.id),
            ("state", "=", "confirmed"),
            ("account_tax_id", "!=", False),
        ]
        rules = self.search(domain, order="sequence, id")

        for rule in rules:
            if rule.meli_charge_name and rule.meli_charge_name.lower() != (charge_name or "").lower():
                continue
            if rule.meli_financial_entity:
                entity = metadata.get("mov_financial_entity", "") if metadata else ""
                if rule.meli_financial_entity.lower() != (entity or "").lower():
                    continue
            if rule.meli_source_detail:
                source = metadata.get("source_detail", "") if metadata else ""
                if rule.meli_source_detail.lower() != (source or "").lower():
                    continue
            return rule

        return self.browse()

    @api.model
    def get_or_create_from_charge(self, charge_type, charge_name, metadata, company_id=None):
        """
        Busca una regla existente o crea una nueva en estado draft.
        Usado para auto-importar tipos de impuesto desde charges_details de MercadoPago.

        :param charge_type: str - 'tax', 'fee', 'shipping'
        :param charge_name: str - nombre del cargo (ej: 'tax_withholding-isr')
        :param metadata: dict - metadata del cargo
        :param company_id: int - ID de compañía (default: env.company)
        :returns: recordset mercadolibre.tax
        """
        company_id = company_id or self.env.company.id
        financial_entity = metadata.get("mov_financial_entity", "") if metadata else ""
        source_detail = metadata.get("source_detail", "") if metadata else ""

        # Buscar regla existente por criterios exactos (case-insensitive via =ilike)
        domain = [
            ("meli_charge_type", "=", charge_type),
            ("meli_charge_name", "=ilike", charge_name),
            ("company_id", "=", company_id),
        ]
        if financial_entity:
            domain.append(("meli_financial_entity", "=ilike", financial_entity))
        existing = self.search(domain, order="state, sequence, id", limit=1)
        if existing:
            return existing

        # Crear regla nueva en draft
        display_name = charge_name or charge_type
        if financial_entity:
            display_name = financial_entity.upper()
            if charge_name and "-" in charge_name:
                display_name = charge_name.split("-")[-1].upper()

        vals = {
            "name": display_name,
            "meli_charge_type": charge_type if charge_type in ("tax", "fee", "shipping") else "tax",
            "meli_charge_name": charge_name,
            "meli_financial_entity": financial_entity,
            "meli_source_detail": source_detail,
            "company_id": company_id,
            "state": "draft",
        }
        _logger.info(
            "MELI: Auto-creating tax mapping rule '%s' (type=%s, entity=%s) in draft state",
            display_name, charge_type, financial_entity,
        )
        return self.create(vals)
