import dateutil.parser

from odoo import api, fields, models


def check_gantt_date(value):
    if isinstance(value, str):
        return dateutil.parser.parse(value, ignoretz=True)
    else:
        return value


class ProjectTask(models.Model):
    _inherit = "project.task"  # pylint: disable=R8180
    duration = fields.Integer(string="Duration (days)", default=-1, copy=True)
    duration_unit = fields.Selection(related="project_id.duration_unit", readonly=True)
    percent_done = fields.Integer(string="Done %", default=0, copy=True)
    parent_index = fields.Integer(default=0)
    assigned_ids = fields.Many2many(
        "res.users", relation="assigned_resources", string="Assigned resources"
    )
    assigned_resources = fields.One2many(
        "project.task.assignment", inverse_name="task", string="Assignments"
    )
    baselines = fields.One2many("project.task.baseline", inverse_name="task")
    segments = fields.One2many("project.task.segment", inverse_name="task")
    effort = fields.Integer(string="Effort (hours)", default=0, copy=True)
    gantt_calendar_flex = fields.Char(string="Gantt Calendar Ids", copy=True)
    # linked_ids are the predecessors
    linked_ids = fields.One2many(
        "project.task.linked",
        inverse_name="to_id",
        string="Predecessors",
        domain="[('from_id', '=', id)]",
    )
    successor_ids = fields.One2many(
        "project.task.linked",
        inverse_name="from_id",
        string="Successors",
        domain="[('to_id', '=', id)]",
    )
    scheduling_mode = fields.Selection(
        [
            ("Normal", "Normal"),
            ("FixedDuration", "Fixed Duration"),
            ("FixedEffort", "Fixed Effort"),
            ("FixedUnits", "Fixed Units"),
        ],
        copy=True,
    )
    constraint_type = fields.Selection(
        [
            ("assoonaspossible", "As soon as possible"),
            ("aslateaspossible", "As late as possible"),
            ("muststarton", "Must start on"),
            ("mustfinishon", "Must finish on"),
            ("startnoearlierthan", "Start no earlier than"),
            ("startnolaterthan", "Start no later than"),
            ("finishnoearlierthan", "Finish no earlier than"),
            ("finishnolaterthan", "Finish no later than"),
        ],
        copy=True,
    )
    constraint_date = fields.Datetime(copy=True)
    effort_driven = fields.Boolean(default=False, copy=True)
    manually_scheduled = fields.Boolean(default=False, copy=True, readonly=True)
    bryntum_rollup = fields.Boolean(string="Rollup", default=True, copy=True)
    force_auto = fields.Boolean(
        string="Force Automatically Scheduled",
        default=False,
        required=True,
        help="""Ignore Global Manually/auto Scheduled Settings
                and apply for this task and force to Auto""",
    )
    force_manual = fields.Boolean(
        string="Force Manually Scheduled",
        default=False,
        required=True,
        help="""Ignore Global Manually/auto Scheduled Settings
                and apply for this task and force to Manual""",
    )
    wbs_value = fields.Char(string="WBS Value")

    employee_ids = fields.Many2many(
        "hr.employee",
        string="Employees",
        compute="_compute_employee_ids",
        inverse="_inverse_employee_ids",
        search="_search_employee_ids",
        store=False,
        help="Employees assigned to this task (Bryntum Gantt field)",
    )
    replace_user_by_employee = fields.Boolean(compute="_compute_has_view_users_group")
    inactive = fields.Boolean(default=False, copy=True)
    show_in_timeline = fields.Boolean(default=True, copy=True)
    milestone = fields.Boolean(string="Bryntum Milestone", default=False, copy=True)
    project_constraint_resolution = fields.Selection(
        [
            ("honor", "honor"),
            ("ignore", "ignore"),
            ("conflict", "ask user"),
        ],
        default="honor",
        copy=True,
    )
    html_color_bryntum_id = fields.Many2one(
        "gantt.event.color", string="Color in Bryntum"
    )
    planned_date_begin = fields.Datetime("Start date", copy=True)
    date_deadline = fields.Datetime(copy=True)

    @api.depends("assigned_resources")
    def _compute_employee_ids(self):
        for this in self:
            resources = this.assigned_resources.mapped("resource_base")
            employees = self.env["hr.employee"].search(
                [("resource_id", "in", resources.ids)]
            )
            this.employee_ids = employees

    def _inverse_employee_ids(self):
        for this in self:
            new_resources_emp = this.employee_ids.mapped("resource_id")
            old_resources_all = this.assigned_resources.mapped("resource_base")
            old_resources_emp = (
                self.env["hr.employee"]
                .search([("resource_id", "in", old_resources_all.ids)])
                .mapped("resource_id")
            )
            res_to_add = set(new_resources_emp.ids).difference(
                set(old_resources_emp.ids)
            )
            res_to_unlink = set(old_resources_emp.ids).difference(
                set(new_resources_emp.ids)
            )
            ass_to_delete = this.assigned_resources.filtered(
                lambda a: a.resource_base.id in res_to_unlink
            ).ids
            this.assigned_resources = [(2, _id) for _id in list(ass_to_delete)] + [
                (0, False, {"units": 100, "resource_base": _id})
                for _id in list(res_to_add)
            ]

    @api.model
    def _search_employee_ids(self, operator, value):
        employees = self.env["hr.employee"].search([("name", operator, value)])
        resources = employees.mapped("resource_id")
        return [("assigned_resources.resource_base", "in", resources.ids)]

    @api.returns("self", lambda value: value.id)
    def copy(self, default=None):
        copied_tasks = super().copy(default)
        self._resolve_gantt_copied_dependencies(copied_tasks)
        return copied_tasks

    def _resolve_gantt_copied_dependencies(self, copied_tasks):
        TaskLinked = self.env["project.task.linked"]
        TaskSegment = self.env["project.task.segment"]
        (
            task_mapping,
            task_successors,
            task_linked_ids,
            task_segments,
        ) = self._create_gantt_task_mapping(copied_tasks)

        for linked in task_linked_ids:
            # the correct now we write
            linked_ids = task_linked_ids[linked]
            for dep in linked_ids.filtered("dep_active"):
                from_id = task_mapping.get(dep.from_id.id)
                to_id = task_mapping.get(dep.to_id.id)
                if from_id and to_id:
                    TaskLinked.create(
                        {
                            "from_id": from_id,
                            "to_id": to_id,
                            "lag": dep.lag,
                            "lag_unit": dep.lag_unit,
                            "dep_active": True,
                            "type": dep.type,
                        }
                    )
        for successor in task_successors:
            successors = task_successors[successor]
            for dep in successors.filtered("dep_active"):
                from_id = task_mapping.get(dep.from_id.id)
                to_id = task_mapping.get(dep.to_id.id)

                if from_id and to_id:
                    TaskLinked.create(
                        {
                            "from_id": from_id,
                            "to_id": to_id,
                            "lag": dep.lag,
                            "lag_unit": dep.lag_unit,
                            "dep_active": True,
                            "type": dep.type,
                        }
                    )

        for original_task_id, segments in task_segments.items():
            new_task_id = task_mapping[original_task_id]
            for segment in segments:
                TaskSegment.create(
                    {
                        "task": new_task_id,
                        "name": segment.name,
                        "planned_date_begin": segment.planned_date_begin,
                        "planned_date_end": segment.planned_date_end,
                    }
                )

    def _create_gantt_task_mapping(self, copied_tasks):
        task_mapping, task_linked_ids, task_successors, task_segments = {}, {}, {}, {}
        for original_task, copied_task in zip(self, copied_tasks):
            task_mapping[original_task.id] = copied_task.id
            if (
                original_task.linked_ids
                or original_task.successor_ids
                or original_task.segments
            ):
                task_successors[original_task.id] = original_task.successor_ids
                task_linked_ids[original_task.id] = original_task.linked_ids
                task_segments[original_task.id] = original_task.segments
            if original_task.child_ids:
                (
                    children_mapping,
                    children_successors,
                    children_linked_ids,
                    children_segments,
                ) = original_task.child_ids._create_gantt_task_mapping(
                    copied_task.child_ids
                )

                task_mapping.update(children_mapping)
                task_linked_ids.update(children_linked_ids)
                task_successors.update(children_successors)
                task_segments.update(children_segments)
        return task_mapping, task_successors, task_linked_ids, task_segments

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_percent_done_and_state()
        return records

    def write(self, vals):
        res = super().write(vals)
        from_bryntum = self.env.context.get("from_bryntum", False)
        # no sync needed if coming from bryntum, the values are already synced.
        if any(val in vals for val in ["percent_done", "state"]) and not from_bryntum:
            self._sync_percent_done_and_state(vals)
        return res

    def _sync_percent_done_and_state(self, vals=None):
        for task in self:
            percent_changed = vals and "percent_done" in vals
            state_changed = vals and "state" in vals
            if percent_changed:
                if task.percent_done == 100 and task.state != "1_done":
                    task.state = "1_done"
                elif task.percent_done < 100 and task.state == "1_done":
                    task.state = "01_in_progress"
            elif state_changed:
                if task.state == "1_done" and task.percent_done < 100:
                    task.percent_done = 100
                elif task.state != "1_done" and task.percent_done == 100:
                    task.percent_done = 0
            for child in task.child_ids:
                child_vals = {}
                if task.state == "1_done":
                    if child.state != "1_done":
                        child_vals["state"] = "1_done"
                    if child.percent_done != 100:
                        child_vals["percent_done"] = 100
                else:
                    if child.state != task.state:
                        child_vals["state"] = task.state
                    if task.state != "1_done" and child.percent_done == 100:
                        child_vals["percent_done"] = 0
                if child_vals:
                    child.write(child_vals)

    @api.onchange("constraint_type")
    def _onchange_constraint_type(self):
        if not self.constraint_type:
            self.constraint_date = None
        else:
            self.constraint_date = {
                "assoonaspossible": self.planned_date_begin,
                "aslateaspossible": self.date_deadline,
                "muststarton": self.planned_date_begin,
                "mustfinishon": self.date_deadline,
                "startnoearlierthan": self.planned_date_begin,
                "startnolaterthan": self.planned_date_begin,
                "finishnoearlierthan": self.date_deadline,
                "finishnolaterthan": self.date_deadline,
            }[self.constraint_type]

    def _get_replace_user_by_employee_value(self):
        su = self.env["ir.config_parameter"].sudo()
        return su.get_param("bryntum.replace_user_by_employee_in_views")

    def _compute_has_view_users_group(self):
        self.env["ir.config_parameter"].sudo()
        self.replace_user_by_employee = self._get_replace_user_by_employee_value()

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        # conditionally hide user_ids, it is impossible to hide the column conditionally in a
        # non-form treeview.
        if view_type == "list" and self._get_replace_user_by_employee_value():
            for node in arch.xpath("//field[@name='user_ids']"):
                node.set("column_invisible", "True")
        return arch, view

    _sql_constraints = [
        (
            "no_double_force",
            "CHECK ((force_auto is false  or  force_manual is false))",
            "We cannot force both auto and manual",
        ),
    ]

    def _read_start_date(self, default_date):
        _date = None
        if self.planned_date_begin and self.date_deadline:
            _date = min(self.planned_date_begin, self.date_deadline)
        elif self.planned_date_begin and not self.date_deadline:
            _date = self.planned_date_begin
        elif self.date_deadline and not self.planned_date_begin:
            _date = self.date_deadline
        else:
            _date = default_date
        return _date

    def _read_end_date(self, default_date):
        _date = None
        if self.planned_date_begin and self.date_deadline:
            _date = max(self.planned_date_begin, self.date_deadline)
        elif self.planned_date_begin and not self.date_deadline:
            _date = self.planned_date_begin
        elif self.date_deadline and not self.planned_date_begin:
            _date = self.date_deadline
        else:
            _date = default_date
        return _date


class ProjectTaskLinked(models.Model):
    _name = "project.task.linked"
    _description = "Project Task Linked"

    from_id = fields.Many2one("project.task", ondelete="cascade", string="From")
    to_id = fields.Many2one("project.task", ondelete="cascade", string="To")
    lag = fields.Integer(default=0)
    lag_unit = fields.Char(default="d")
    type = fields.Integer(default=2)
    dep_active = fields.Boolean(string="Active", default=True)
    from_name = fields.Char(related="from_id.name", string="From Name", readonly=True)
    to_name = fields.Char(related="to_id.name", string="To name", readonly=True)
    # if a record does not have a name field it will be shown as record(x,) in listview

    @api.depends("from_id.name", "to_id.name")
    def _compute_display_name(self):
        for record in self:
            if record.from_id and record.to_id:
                record.display_name = f"{record.from_id.name} to {record.to_id.name}"
            else:
                record.display_name = ""


class ProjectTaskAssignmentUser(models.Model):
    _name = "project.task.assignment"
    _description = "Project Task User Assignment"

    task = fields.Many2one("project.task", ondelete="cascade")
    resource = fields.Many2one("res.users", ondelete="cascade", string="User")
    resource_base = fields.Many2one(
        "resource.resource", ondelete="cascade", string="Resource"
    )
    units = fields.Integer(default=0)


class ProjectTaskBaseline(models.Model):
    _name = "project.task.baseline"
    _description = "Project Task User Assignment"

    task = fields.Many2one("project.task", ondelete="cascade")
    name = fields.Char(default="")
    planned_date_begin = fields.Datetime("Start date")
    planned_date_end = fields.Datetime("End date")


class ProjectTaskSegment(models.Model):
    _name = "project.task.segment"
    _description = "Project Task Segment"

    task = fields.Many2one("project.task", ondelete="cascade")
    name = fields.Char(default="")
    planned_date_begin = fields.Datetime("Start date")
    planned_date_end = fields.Datetime("End date")
