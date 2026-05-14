{
    'name': 'Obra Audit - Snapshot diario de tareas',
    'version': '18.0.1.0.0',
    'category': 'Project',
    'summary': 'Snapshot diario del estado de tareas para auditoria de reportes',
    'description': """
Obra Audit - Snapshot diario de tareas
=======================================

Genera diariamente un snapshot del estado de todas las tareas activas,
marcando cuales requieren reporte de actividad ese dia.

Esta disenado para auditar el cumplimiento del registro de timesheets
contra tareas en estados que requieren reporte (en progreso, en espera,
cambios solicitados).

Los estados auditables se configuran via el parametro de sistema:
  obra_audit.auditable_states

Por defecto: 01_in_progress, 02_changes_requested, 04_waiting_normal
    """,
    'author': 'Galpones Modulares',
    'depends': ['project', 'hr_timesheet'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
        'views/task_daily_snapshot_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
