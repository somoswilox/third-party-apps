# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class TaskDailySnapshot(models.Model):
    _name = 'obra.task.daily.snapshot'
    _description = 'Snapshot diario del estado de tareas de obra'
    _order = 'snapshot_date desc, project_id, task_name'
    _rec_name = 'task_name'

    snapshot_date = fields.Date(
        string='Fecha de snapshot',
        required=True,
        index=True,
    )
    task_id = fields.Many2one(
        'project.task',
        string='Tarea',
        required=True,
        ondelete='cascade',
        index=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        required=True,
        index=True,
    )
    task_name = fields.Char(
        string='Nombre de tarea',
        required=True,
        help='Denormalizado: nombre de la tarea al momento del snapshot. '
             'Sobrevive a renombres posteriores.',
    )
    state = fields.Char(
        string='Estado tecnico',
        required=True,
        index=True,
        help='Valor tecnico del campo state de la tarea, ej. 01_in_progress.',
    )
    state_label = fields.Char(
        string='Estado',
        required=True,
        help='Label legible del estado al momento del snapshot.',
    )
    requires_report = fields.Boolean(
        string='Requiere reporte',
        required=True,
        index=True,
        help='True si el estado de la tarea ese dia requeria un reporte de actividad.',
    )
    user_ids_text = fields.Char(
        string='Responsables',
        help='Nombres de los responsables al momento del snapshot, separados por coma.',
    )

    _sql_constraints = [
        (
            'task_date_uniq',
            'UNIQUE(task_id, snapshot_date)',
            'Ya existe un snapshot para esta tarea en esta fecha.',
        ),
    ]

    # ------------------------------------------------------------------
    # Configuracion
    # ------------------------------------------------------------------
    @api.model
    def _get_auditable_states(self):
        """Lee del parametro de sistema la lista de estados auditables.

        El parametro 'obra_audit.auditable_states' contiene los valores
        tecnicos del campo state separados por coma.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        raw = ICP.get_param(
            'obra_audit.auditable_states',
            default='01_in_progress,02_changes_requested,04_waiting_normal',
        )
        return [s.strip() for s in raw.split(',') if s.strip()]

    # ------------------------------------------------------------------
    # Generacion del snapshot
    # ------------------------------------------------------------------
    @api.model
    def _generate_daily_snapshot(self, target_date=None):
        """Genera el snapshot para target_date (por defecto: hoy).

        Idempotente: si ya existen snapshots para target_date, los elimina
        y regenera. De esta forma una segunda corrida del cron en el mismo
        dia no duplica filas y refleja el ultimo estado conocido.

        :param target_date: fecha a snapshotear (date). Default: hoy.
        :return: True
        """
        if target_date is None:
            target_date = fields.Date.context_today(self)

        auditable_states = self._get_auditable_states()
        _logger.info(
            "[obra_audit] Generando snapshot %s. Estados auditables: %s",
            target_date, auditable_states,
        )

        # Idempotencia: borrar snapshots previos del mismo dia
        previous = self.search([('snapshot_date', '=', target_date)])
        if previous:
            _logger.info(
                "[obra_audit] Eliminando %d snapshots previos de %s",
                len(previous), target_date,
            )
            previous.unlink()

        # Tareas activas de proyectos activos
        Task = self.env['project.task'].sudo()
        tasks = Task.search([
            ('active', '=', True),
            ('project_id', '!=', False),
            ('project_id.active', '=', True),
        ])

        if not tasks:
            _logger.warning(
                "[obra_audit] Snapshot %s: no se encontraron tareas activas",
                target_date,
            )
            return True

        # Validacion: el campo state debe existir en project.task
        if 'state' not in Task._fields:
            _logger.error(
                "[obra_audit] El campo 'state' no existe en project.task. "
                "Verificar instalacion del modulo Bryntum Gantt View Pro."
            )
            return False

        # Mapa valor_tecnico -> label legible
        state_labels = dict(
            Task._fields['state']._description_selection(self.env)
        )

        records = []
        for task in tasks:
            user_names = ''
            if task.user_ids:
                user_names = ', '.join(task.user_ids.mapped('name'))

            records.append({
                'snapshot_date': target_date,
                'task_id': task.id,
                'project_id': task.project_id.id,
                'task_name': task.name or '(sin nombre)',
                'state': task.state or '',
                'state_label': state_labels.get(task.state, task.state or ''),
                'requires_report': task.state in auditable_states,
                'user_ids_text': user_names,
            })

        self.create(records)

        requires_count = sum(1 for r in records if r['requires_report'])
        _logger.info(
            "[obra_audit] Snapshot %s: %d filas creadas (%d requieren reporte)",
            target_date, len(records), requires_count,
        )
        return True
