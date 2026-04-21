from odoo import api, fields, models
from odoo.exceptions import UserError


class BryntumSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Have been requested two Checkboxes, one with "auto" and one with "manual"
    # this would make code very messy and cause regression, a radio button or switch
    # would not do, will manage this with two booleans.
    visualize_auto_scheduling = fields.Boolean(
        "Automatic",
    )
    visualize_manual_scheduling = fields.Boolean(
        "Manual",
    )
    bryntum_auto_scheduling = fields.Boolean("Auto scheduling", default=False)
    bryntum_user_assignment = fields.Boolean("User assignment", default=False)
    bryntum_readonly_projects = fields.Boolean("Readonly projects", default=False)
    bryntum_save_wbs = fields.Boolean(
        "Save WBS values",
        default=False,
        help="""If you don't want the WBS to be auto generated,
            but you want to govern it manually, you should switch this on""",
    )
    bryntum_gantt_config = fields.Text("Gantt configuration object", default="{}")
    bryntum_calendar_config = fields.Text("Calendar configuration object", default="{}")
    bryntum_default_calendar = fields.Selection(
        selection="get_calendar_names", string="Default calendar"
    )
    bryntum_replace_user_by_employee_in_views = fields.Boolean(
        "Replace user_ids by employee_ids in views",
        default=False,
    )
    bryntum_enable_user_config_edit = fields.Boolean(
        string="Allow Users to Modify and Save UI Configs",
        config_parameter="bryntum.bryntum_enable_user_config_edit",
    )
    bryntum_copy_dependencies = fields.Boolean(
        "Copy Dependencies in copy/paste operations",
        default=False,
    )

    @api.onchange("visualize_manual_scheduling")
    def onchange_visualize_man_scheduling(self):
        self.visualize_auto_scheduling = not self.visualize_manual_scheduling

    @api.onchange("visualize_auto_scheduling")
    def onchange_visualize_auto_scheduling(self):
        self.visualize_manual_scheduling = not self.visualize_auto_scheduling

    def get_calendar_names(self):
        calendar_env = self.env["resource.calendar"]
        calendars = calendar_env.search([])
        calendar_names = [("user_defined", "Calendar Configuration Object")] + [
            (str(calendar.id), calendar.name) for calendar in calendars
        ]
        return calendar_names

    def autoschedule_changed(self):
        su = self.env["ir.config_parameter"].sudo()
        return su.get_param("bryntum.auto_scheduling") != self.visualize_auto_scheduling

    def set_values(self):
        previous_default_calendar = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("self.bryntum_default_calendar")
        )
        res = super(BryntumSettings, self).set_values()
        if self.autoschedule_changed():
            self.env.cr.execute(
                "update project_task set force_auto = false, force_manual = false"
            )
        self.env["ir.config_parameter"].set_param(
            "bryntum.auto_scheduling", self.visualize_auto_scheduling
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.user_assignment", self.bryntum_user_assignment
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.readonly_projects", self.bryntum_readonly_projects
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.save_wbs", self.bryntum_save_wbs
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.gantt_config", self.bryntum_gantt_config
        )
        bryntum_calendar_config = self.bryntum_calendar_config
        is_empty = not bryntum_calendar_config or bryntum_calendar_config.replace(
            " ", ""
        ) in ["", "{}"]
        if not is_empty:
            is_valid, reason, bryntum_calendar_config = (
                self.env["project.project"]
                .sudo()
                .validate_calendar_config(bryntum_calendar_config)
            )
            if is_valid:
                # replace the id with "user_defined"
                bryntum_calendar_config["id"] = "user_defined"
                # if the manually inserted calendar was "is valid" default calendar
                # will be set to user_defined
                self.bryntum_default_calendar = "user_defined"
            else:
                # TODO raise validation information , validation would return error and
                # message for end-user.
                raise UserError(reason)
        self.env["ir.config_parameter"].set_param(
            "bryntum.calendar_config", bryntum_calendar_config
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.default_calendar", self.bryntum_default_calendar
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.replace_user_by_employee_in_views",
            self.bryntum_replace_user_by_employee_in_views,
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.bryntum_enable_user_config_edit",
            self.bryntum_enable_user_config_edit,
        )
        self.env["ir.config_parameter"].set_param(
            "bryntum.copy_dependencies",
            self.bryntum_copy_dependencies,
        )
        if str(previous_default_calendar) != str(self.bryntum_default_calendar):
            self.env["project.task"].search([]).write({"gantt_calendar_flex": False})
        return res

    @api.model
    def get_values(self):
        res = super(BryntumSettings, self).get_values()
        su = self.env["ir.config_parameter"].sudo()
        res.update(
            visualize_auto_scheduling=su.get_param("bryntum.auto_scheduling"),
            visualize_manual_scheduling=not su.get_param("bryntum.auto_scheduling")
            == "True",
            bryntum_auto_scheduling=su.get_param("bryntum.auto_scheduling"),
            bryntum_user_assignment=su.get_param("bryntum.user_assignment"),
            bryntum_readonly_projects=su.get_param("bryntum.readonly_projects"),
            bryntum_save_wbs=su.get_param("bryntum.save_wbs"),
            bryntum_gantt_config=su.get_param("bryntum.gantt_config") or "{}",
            bryntum_calendar_config=su.get_param("bryntum.calendar_config"),
            bryntum_default_calendar=su.get_param("bryntum.default_calendar"),
            bryntum_replace_user_by_employee_in_views=su.get_param(
                "bryntum.replace_user_by_employee_in_views"
            ),
            bryntum_enable_user_config_edit=su.get_param(
                "bryntum.bryntum_enable_user_config_edit"
            ),
            bryntum_copy_dependencies=su.get_param("bryntum.copy_dependencies"),
        )
        return res
