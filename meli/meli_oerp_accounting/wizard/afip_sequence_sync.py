# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError
import logging
import re

_logger = logging.getLogger(__name__)


class AfipSequenceSyncWizard(models.TransientModel):
    """Wizard to consult AFIP's FECompUltimoAutorizado for every document type
    in an Argentine journal and realign Odoo's internal sequence so the next
    invoice gets the number AFIP expects (avoids error 10016 at post time).

    Workflow:
      1. User clicks "Sincronizar secuencia con AFIP" on an Argentine journal.
      2. action_open_wizard gathers all document types configured for the
         journal (from l10n_ar_edi/l10n_ar conventions) and for each one
         calls FECompUltimoAutorizado, comparing with Odoo's last posted
         move for the same (journal, doc_type).
      3. The wizard opens showing a line per doc_type with the gap.
      4. User reviews and clicks "Aplicar" — we set `sequence_number` on
         the last posted move so the next one computes to `afip_last + 1`.
         No historical data is touched.
    """

    _name = "meli.afip.sequence.sync.wizard"
    _description = "Sincronizar secuencia de diario con AFIP"

    journal_id = fields.Many2one(
        "account.journal", string="Diario", required=True, readonly=True,
    )
    company_id = fields.Many2one(
        "res.company", string="Compañía",
        related="journal_id.company_id", readonly=True,
    )
    pos_number = fields.Integer(
        string="Punto de Venta",
        compute="_compute_pos_number",
        store=False,
    )

    def _compute_pos_number(self):
        for wizard in self:
            wizard.pos_number = getattr(wizard.journal_id, 'l10n_ar_afip_pos_number', 0) or 0

    def _has_latam(self):
        """True si l10n_latam está instalado y account.move tiene el campo de tipo de documento."""
        return 'l10n_latam_document_type_id' in self.env['account.move']._fields
    line_ids = fields.One2many(
        "meli.afip.sequence.sync.line", "wizard_id",
        string="Tipos de documento",
    )
    status_message = fields.Html(string="Estado", readonly=True)

    # ------------------------------------------------------------------
    # AFIP SOAP helper — try multiple call patterns since the connection
    # object's interface varies between Odoo versions and l10n_ar_edi
    # implementations.
    # ------------------------------------------------------------------
    @staticmethod
    def _call_fe_comp_ultimo_autorizado(connection, pto_vta, cbte_tipo):
        """Call FECompUltimoAutorizado on an AFIP connection object.

        The `connection` may be:
          a) A pyafipws WSFEv1 instance (has .FECompUltimoAutorizado method)
          b) An Odoo l10n_ar.afipws.connection record (has ._get_client() →
             zeep client + auth tuple)
          c) Some other wrapper with ._ws or .client attribute

        Returns the last authorized invoice number (int) or raises.
        """
        # Pattern A: pyafipws direct method
        if hasattr(connection, 'FECompUltimoAutorizado'):
            connection.FECompUltimoAutorizado(pto_vta, cbte_tipo)
            return int(getattr(connection, 'CbteNro', 0) or 0)

        if hasattr(connection, 'CompUltimoAutorizado'):
            result = connection.CompUltimoAutorizado(pto_vta, cbte_tipo)
            if isinstance(result, int):
                return result
            return int(getattr(connection, 'CbteNro', 0) or 0)

        # Pattern B: Odoo l10n_ar_edi zeep client (_get_client returns client, auth)
        if hasattr(connection, '_get_client'):
            client_result = connection._get_client()
            if isinstance(client_result, tuple) and len(client_result) >= 2:
                client, auth = client_result[0], client_result[1]
            else:
                client = client_result
                auth = getattr(connection, '_get_auth', lambda: {})()
                if not auth and hasattr(connection, 'token') and hasattr(connection, 'sign'):
                    auth = {
                        'Token': connection.token,
                        'Sign': connection.sign,
                        'Cuit': connection.l10n_ar_afip_ws_crt_id.sudo().l10n_ar_afip_ws_cuit
                              if hasattr(connection, 'l10n_ar_afip_ws_crt_id') else '',
                    }

            if hasattr(client, 'service'):
                response = client.service.FECompUltimoAutorizado(
                    Auth=auth, PtoVta=pto_vta, CbteTipo=cbte_tipo,
                )
                return int(response.CbteNro or 0)

        # Pattern C: connection wraps a ._ws pyafipws instance
        ws = getattr(connection, '_ws', None) or getattr(connection, 'ws', None)
        if ws and hasattr(ws, 'FECompUltimoAutorizado'):
            ws.FECompUltimoAutorizado(pto_vta, cbte_tipo)
            return int(getattr(ws, 'CbteNro', 0) or 0)

        raise AttributeError(
            "No se pudo encontrar el método FECompUltimoAutorizado en el objeto "
            "de conexión AFIP (%s). Métodos disponibles: %s" % (
                type(connection).__name__,
                [m for m in dir(connection) if not m.startswith('_')][:30],
            )
        )

    # ------------------------------------------------------------------
    # Launch / refresh
    # ------------------------------------------------------------------
    @api.model
    def action_open_from_journal(self, journal_id):
        """Entry point from the journal's button. Creates the wizard and
        populates line_ids by querying AFIP for every doc type seen on
        this journal's posted moves."""
        journal = self.env["account.journal"].browse(journal_id)
        if not journal:
            raise UserError(_("Diario no encontrado."))
        if "l10n_ar_afip_pos_number" not in journal._fields or not journal.l10n_ar_afip_pos_number:
            raise UserError(_(
                "Este diario no tiene un Punto de Venta AFIP configurado. "
                "Esta acción sólo aplica a diarios argentinos con facturación electrónica."
            ))

        wizard = self.create({"journal_id": journal.id})
        wizard._populate_lines()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sincronizar secuencia con AFIP"),
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_refresh(self):
        self.ensure_one()
        self.line_ids.unlink()
        self._populate_lines()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sincronizar secuencia con AFIP"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Populate lines by consulting AFIP per doc type used in this journal
    # ------------------------------------------------------------------
    def _populate_lines(self):
        self.ensure_one()
        journal = self.journal_id
        company = journal.company_id

        # Discover all document types ever used on this journal (posted moves)
        if not self._has_latam():
            self.status_message = _(
                "<b>l10n_latam no está disponible en este entorno.</b><br/>"
                "Esta función requiere la localización latinoamericana instalada "
                "(Argentina, Colombia, Chile, Uruguay, etc.)."
            )
            return
        doc_types = self.env["account.move"].search([
            ("journal_id", "=", journal.id),
            ("state", "=", "posted"),
        ]).mapped("l10n_latam_document_type_id")

        # Also include document types explicitly wired on the journal when
        # available (l10n_ar_edi exposes this association on certain Odoo
        # versions). Fallback: what we discovered above is enough.
        if hasattr(journal, "l10n_latam_document_type_ids"):
            try:
                doc_types = doc_types | journal.l10n_latam_document_type_ids
            except Exception:
                pass

        if not doc_types:
            self.status_message = _(
                "<b>No hay facturas posteadas en este diario todavía.</b><br/>"
                "La secuencia se inicializa al postear la primera factura; "
                "asegurate de poner el número correcto a mano en ese momento."
            )
            return

        # Try to get a live AFIP connection
        afip_ws = None
        try:
            if hasattr(company, "_l10n_ar_get_connection"):
                afip_ws = company._l10n_ar_get_connection("wsfe")
        except Exception as e:
            _logger.warning("AFIP seq sync: could not open connection: %s", e)
            afip_ws = None

        Line = self.env["meli.afip.sequence.sync.line"]
        line_vals = []
        global_errors = []

        for doc_type in doc_types:
            # Skip doc types without a numeric AFIP code (internal-only types)
            doc_code = getattr(doc_type, "code", False)
            if not doc_code or not str(doc_code).isdigit():
                continue

            # Odoo side: the last posted move of this (journal, doc_type)
            last_move_domain = [
                ("journal_id", "=", journal.id),
                ("l10n_latam_document_type_id", "=", doc_type.id),
                ("state", "=", "posted"),
            ]
            if self._has_latam():
                last_move_domain.append(("l10n_latam_document_type_id", "=", doc_type.id))
            last_move = self.env["account.move"].search(
                last_move_domain, order="sequence_number desc, id desc", limit=1)

            odoo_last_number = 0
            if last_move:
                # account.move.sequence_number is the integer tail of `name`
                odoo_last_number = int(last_move.sequence_number or 0)
                if not odoo_last_number:
                    # Fallback: parse the last numeric chunk of the name
                    m = re.findall(r"\d+", last_move.name or "")
                    if m:
                        odoo_last_number = int(m[-1])

            # AFIP side: FECompUltimoAutorizado
            afip_last_number = False
            afip_error = ""
            if afip_ws is not None:
                try:
                    afip_last_number = self._call_fe_comp_ultimo_autorizado(
                        afip_ws, int(self.pos_number), int(doc_code),
                    )
                except Exception as e:
                    afip_error = str(e)[:250]
                    _logger.warning(
                        "AFIP seq sync: FECompUltimoAutorizado(%s, %s) failed: %s",
                        self.pos_number, doc_code, afip_error,
                    )
            else:
                afip_error = _("No se pudo abrir conexión con AFIP")

            line_vals.append({
                "wizard_id": self.id,
                "doc_type_id": doc_type.id,
                "doc_type_name": doc_type.name,
                "doc_code": doc_code,
                "last_move_id": last_move.id if last_move else False,
                "odoo_last_number": odoo_last_number,
                "afip_last_number": afip_last_number or 0,
                "afip_error": afip_error,
            })

        if line_vals:
            Line.create(line_vals)

        # Summary
        self.status_message = self._render_summary(global_errors)

    def _render_summary(self, errors):
        ok_count = sum(1 for l in self.line_ids if not l.afip_error and l.gap == 0)
        gap_count = sum(1 for l in self.line_ids if not l.afip_error and l.gap != 0)
        err_count = sum(1 for l in self.line_ids if l.afip_error)

        draft_count = self.env['account.move'].search_count([
            ('journal_id', '=', self.journal_id.id),
            ('state', '=', 'draft'),
            ('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')),
            ('name', '!=', '/'),
            ('name', '!=', False),
        ])

        parts = []
        parts.append("<b>Resumen:</b>")
        parts.append("• %d tipo(s) de documento alineado(s) con AFIP" % ok_count)
        if gap_count:
            parts.append("• <b>%d tipo(s) de documento desalineado(s)</b> — requieren ajuste" % gap_count)
        if err_count:
            parts.append("• %d tipo(s) con error al consultar AFIP (ver columna 'Error')" % err_count)
        if draft_count:
            parts.append(
                "• <b>%d factura(s) borrador con número asignado</b> — listas para confirmar con AFIP "
                "(usá el botón <i>Confirmar borradores</i> luego de aplicar)" % draft_count
            )
        parts.append("")
        parts.append(
            "Al aplicar, se renombran las <b>facturas borrador</b> pendientes de este diario "
            "con el número que AFIP espera. Luego hacé clic en <b>Confirmar borradores</b> "
            "para enviarlas a AFIP. "
            "Si no hay borradores, se ajusta la secuencia interna como fallback. "
            "<b>No se modifican facturas ya posteadas ni se emiten nuevas desde acá.</b>"
        )
        return "<br/>".join(parts)

    # ------------------------------------------------------------------
    # Apply: realign the sequence so the next invoice gets afip_last + 1.
    #
    # In Odoo 19 the next invoice number is derived by parsing the `name`
    # of the last posted move (via _get_last_sequence) and incrementing
    # the numeric tail. Writing `sequence_number` alone does NOT work —
    # the `name` text is what controls the next number.
    #
    # Strategy (in priority order):
    #   1. Find DRAFT invoices for this (journal, doc_type) and set their
    #      `name` to the correct next number. This is the safest path —
    #      the user just clicks Confirm and AFIP accepts.
    #   2. If no drafts exist, update `sequence_number` on the last posted
    #      move as a hint (works on some Odoo builds where
    #      _get_last_sequence orders by sequence_number).
    #   3. As an extra safety net, also update sequence_number so both
    #      mechanisms are covered.
    # ------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        applied = []
        skipped = []

        for line in self.line_ids:
            if line.afip_error:
                skipped.append("• %s: error AFIP — %s" % (line.doc_type_name, line.afip_error[:120]))
                continue
            if not line.last_move_id:
                skipped.append("• %s: sin factura posteada previa, no se puede ajustar desde acá" % line.doc_type_name)
                continue
            if line.gap == 0:
                continue
            if line.gap < 0:
                skipped.append(
                    "• %s: Odoo va adelante de AFIP por %d — retroceder es riesgoso, revisar manualmente" % (
                        line.doc_type_name, abs(line.gap),
                    )
                )
                continue

            afip_next = line.afip_last_number + 1

            try:
                # Build the target name from the last posted move's name pattern.
                # E.g. last posted = "FA-B 00002-00026388" → target = "FA-B 00002-00027447"
                last_name = line.last_move_id.name or ''
                target_name = self._build_target_name(last_name, afip_next)

                if not target_name:
                    skipped.append(
                        "• %s: no se pudo construir el nombre destino desde '%s'" % (
                            line.doc_type_name, last_name,
                        )
                    )
                    continue

                # Strategy 1: find draft invoices for this (journal, doc_type) and rename them
                draft_domain = [
                    ('journal_id', '=', self.journal_id.id),
                    ('state', '=', 'draft'),
                    ('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')),
                ]
                if self._has_latam():
                    draft_domain.append(('l10n_latam_document_type_id', '=', line.doc_type_id))
                drafts = self.env['account.move'].search(draft_domain, order='id asc')

                draft_renamed = 0
                for draft in drafts:
                    try:
                        draft_target = self._build_target_name(last_name, afip_next + draft_renamed)
                        draft.sudo().write({'name': draft_target})
                        draft_renamed += 1
                    except Exception as draft_err:
                        _logger.warning("Could not set name on draft %s: %s", draft.id, draft_err)

                # Strategy 2: also update sequence_number on last posted (covers builds
                # where _get_last_sequence uses sequence_number for ordering)
                try:
                    line.last_move_id.sudo().write({
                        'sequence_number': line.afip_last_number,
                    })
                except Exception:
                    pass  # non-critical

                if draft_renamed:
                    applied.append(
                        "• %s: %d factura(s) borrador renombrada(s) → próxima: %s (confirmá para que AFIP la acepte)" % (
                            line.doc_type_name,
                            draft_renamed,
                            target_name,
                        )
                    )
                else:
                    applied.append(
                        "• %s: sequence_number ajustado a %d en la última factura posteada. "
                        "La próxima factura borrador que crees debería salir como %s. "
                        "Si no, editá el campo 'Número' manualmente en debug mode antes de confirmar." % (
                            line.doc_type_name,
                            line.afip_last_number,
                            target_name,
                        )
                    )

            except Exception as e:
                _logger.exception("AFIP seq sync apply failed for %s", line.doc_type_name)
                skipped.append("• %s: error al aplicar — %s" % (line.doc_type_name, str(e)[:120]))

        msg_parts = [_("<b>Resultado de la sincronización</b>")]
        if applied:
            msg_parts.append(_("Aplicado:"))
            msg_parts.extend(applied)
        if skipped:
            msg_parts.append(_("Omitido:"))
            msg_parts.extend(skipped)
        if not applied and not skipped:
            msg_parts.append(_("No había nada para ajustar — todas las secuencias ya estaban alineadas con AFIP."))

        # Post a note on the journal for audit trail
        try:
            self.journal_id.sudo().message_post(
                body="<br/>".join(msg_parts),
                subject=_("Sincronización de secuencia con AFIP"),
            )
        except Exception:
            pass

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sincronización completada"),
                "message": _(
                    "%d tipo(s) ajustado(s), %d omitido(s). Ver nota en el diario para detalles."
                ) % (len(applied), len(skipped)),
                "type": "success" if applied else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_confirm_drafts(self):
        """Post all draft invoices of this journal that already have a proper name
        (i.e. were renamed by action_apply). Reports per-invoice results."""
        self.ensure_one()
        draft_domain = [
            ('journal_id', '=', self.journal_id.id),
            ('state', '=', 'draft'),
            ('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')),
            ('name', '!=', '/'),
            ('name', '!=', False),
        ]
        drafts = self.env['account.move'].search(draft_domain, order='name asc')

        if not drafts:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Sin borradores"),
                    "message": _("No hay facturas borrador con nombre asignado para confirmar en este diario."),
                    "type": "info",
                    "sticky": False,
                },
            }

        posted_ok = []
        errors = []
        bank_sanitized = []

        for draft in drafts:
            try:
                # GUARD (flota AR/AFIP): sanear partner_bank_id archivado antes de postear.
                # Odoo bloquea action_post() cuando la cuenta bancaria del receptor esta
                # archivada ("The recipient bank account linked to this invoice is archived. So
                # you cannot confirm the invoice."). En Factura B de venta el partner_bank_id no
                # es requerido y no afecta a AFIP -> si el banco esta archivado (active=False) se
                # limpia en el borrador (no se reactiva el banco global). Generico para toda la
                # flota AR con AFIP. Caso Mocoroa (409): 1.309/1.319 borradores B apuntaban a la
                # cuenta propia archivada -> el wizard halteaba en el 1er draft antes de AFIP.
                if draft.partner_bank_id and not draft.partner_bank_id.active:
                    draft.sudo().write({'partner_bank_id': False})
                    bank_sanitized.append(draft.name)
                draft.sudo().action_post()
                posted_ok.append(draft.name)
            except Exception as e:
                errors.append("• %s: %s" % (draft.name, str(e)[:150]))
                _logger.warning(
                    "AFIP seq sync confirm_drafts: could not post %s (id=%d): %s",
                    draft.name, draft.id, e,
                )

        msg_parts = ["<b>Confirmación de borradores post-sincronización AFIP</b>"]
        if posted_ok:
            msg_parts.append("<b>%d factura(s) confirmada(s) exitosamente:</b>" % len(posted_ok))
            for name in posted_ok[:30]:
                msg_parts.append("• " + name)
            if len(posted_ok) > 30:
                msg_parts.append("• … y %d más" % (len(posted_ok) - 30))
        if bank_sanitized:
            msg_parts.append(
                "<b>%d con cuenta bancaria archivada saneada (partner_bank_id → vacío) antes de postear:</b>"
                % len(bank_sanitized)
            )
            for name in bank_sanitized[:30]:
                msg_parts.append("• " + name)
            if len(bank_sanitized) > 30:
                msg_parts.append("• … y %d más" % (len(bank_sanitized) - 30))
        if errors:
            msg_parts.append("<b>%d con error al confirmar:</b>" % len(errors))
            msg_parts.extend(errors[:20])

        try:
            self.journal_id.sudo().message_post(
                body="<br/>".join(msg_parts),
                subject=_("Confirmación de borradores post-sincronización AFIP"),
            )
        except Exception:
            pass

        notif_type = "success" if posted_ok and not errors else ("warning" if posted_ok else "danger")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Confirmación completada"),
                "message": _("%d confirmada(s), %d con error. Ver nota en el diario.") % (
                    len(posted_ok), len(errors)
                ),
                "type": notif_type,
                "sticky": bool(errors),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @staticmethod
    def _build_target_name(template_name, target_number):
        """Given a template name like 'FA-B 00002-00026388' and a target
        number like 27447, return 'FA-B 00002-00027447'.

        Replaces only the LAST numeric group in the name, preserving the
        prefix, zero-padding, and separators.
        """
        if not template_name:
            return ''
        # Find the last numeric group and its position
        match = list(re.finditer(r'\d+', template_name))
        if not match:
            return ''
        last_match = match[-1]
        # Preserve zero-padding width
        width = len(last_match.group())
        new_num = str(target_number).zfill(width)
        return template_name[:last_match.start()] + new_num + template_name[last_match.end():]


class AfipSequenceSyncWizardLine(models.TransientModel):
    _name = "meli.afip.sequence.sync.line"
    _description = "Línea de sincronización de secuencia AFIP (por tipo de documento)"

    wizard_id = fields.Many2one(
        "meli.afip.sequence.sync.wizard", required=True, ondelete="cascade",
    )
    doc_type_id = fields.Integer(string="Doc Type ID", readonly=True)
    doc_type_name = fields.Char(string="Tipo de Documento", readonly=True)
    doc_code = fields.Char(string="Código AFIP", readonly=True)
    last_move_id = fields.Many2one(
        "account.move", string="Última factura posteada en Odoo", readonly=True,
    )
    odoo_last_number = fields.Integer(string="Odoo: último Nº", readonly=True)
    afip_last_number = fields.Integer(string="AFIP: último Nº", readonly=True)
    afip_error = fields.Char(string="Error AFIP", readonly=True)

    gap = fields.Integer(
        string="Gap (AFIP − Odoo)",
        compute="_compute_gap", store=False,
    )
    action_summary = fields.Char(
        string="Acción al aplicar",
        compute="_compute_action_summary", store=False,
    )

    @api.depends("odoo_last_number", "afip_last_number", "afip_error")
    def _compute_gap(self):
        for line in self:
            if line.afip_error:
                line.gap = 0
            else:
                line.gap = (line.afip_last_number or 0) - (line.odoo_last_number or 0)

    @api.depends("gap", "afip_last_number", "afip_error", "last_move_id")
    def _compute_action_summary(self):
        for line in self:
            if line.afip_error:
                line.action_summary = _("Saltear (no se pudo consultar AFIP)")
            elif not line.last_move_id:
                line.action_summary = _("Saltear (sin factura posteada previa)")
            elif line.gap == 0:
                line.action_summary = _("Nada — ya está alineado")
            elif line.gap > 0:
                line.action_summary = _("Adelantar Odoo a %d (próxima: %d)") % (
                    line.afip_last_number, line.afip_last_number + 1,
                )
            else:
                line.action_summary = _(
                    "⚠ Odoo va adelante de AFIP por %d. Retroceder es riesgoso; "
                    "revisar manualmente antes de aplicar."
                ) % abs(line.gap)
