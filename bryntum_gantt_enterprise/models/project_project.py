import json
import logging
import re
from datetime import datetime
from json import loads

from odoo import api, fields, models
from odoo.tools.misc import format_duration

_logger = logging.getLogger(__name__)


class ProjectProject(models.Model):
    _inherit = "project.project"

    project_start_date = fields.Datetime(default=datetime.today())
    bryntum_auto_scheduling = fields.Boolean(
        "Auto scheduling", compute="_compute_bryntum_settings"
    )
    bryntum_user_assignment = fields.Boolean(
        "User assignment", compute="_compute_bryntum_settings"
    )
    duration_unit = fields.Selection(
        [
            ("h", "Hours"),
            ("d", "Days"),
            ("w", "Weeks"),
        ],
        default="d",
        required=True,
    )
    bryntum_dont_load_done_tasks = fields.Boolean("Dont load done tasks", default=False)
    bryntum_percent100_done = fields.Boolean(
        "Percent Done 100% and State done synced",
        default=False,
        help="""When 100% percentage is done on a task, task is set to done, and
                    vice-versa""",
    )

    def _compute_bryntum_settings(self):
        res = self.get_bryntum_values()
        self.bryntum_user_assignment = res.get("bryntum_user_assignment")
        self.bryntum_auto_scheduling = res.get("bryntum_auto_scheduling")

    @api.onchange("bryntum_percent100_done")
    def _onchange_percent_update(self):
        for this in self:
            if this.bryntum_percent100_done:
                tasks = this.env["project.task"].search([("project_id", "=", this.id)])
                for task in tasks:
                    task.write({"percent_done": task.percent_done, "state": task.state})

    @api.model
    def convert_if_string_calendar(self, calendar):
        # calendar string means coming from user config.
        if isinstance(calendar, str):
            # calendar is certainly in JSON after mig.
            # will error out if user uses invalid
            calendar = json.loads(calendar)
        return calendar

    @api.model
    def validate_calendar_config(self, calendar):
        # TODO support children intervals when they will be supported /added and
        # validate those too
        if not calendar:
            return (False, "no calendar provided", calendar)
        try:
            calendar = self.convert_if_string_calendar(calendar)
        except Exception as err:
            return (False, err, calendar)
        # cover the habit of users to put calendar dicts in a list
        if isinstance(calendar, list) and len(calendar) == 1:
            calendar = calendar[0]
        if not isinstance(calendar, dict):
            return (False, "Converting calendar to valid dict failed", calendar)
        # Not valid if no interval keys
        if not calendar.get("hoursPerDay"):
            return (False, "Calendar should have a hoursPerDay entry", calendar)
        if not calendar.get("intervals"):
            return (False, "Calendar should have an intervals entry", calendar)
        if "unspecifiedTimeIsWorking" not in calendar.keys():
            return (
                False,
                "Calendar should have an unspecifiedTimeIsWorking entry",
                calendar,
            )
        return (True, "success", calendar)

    def convert_odoo_to_gantt(self, calendar):
        day_of_week = {
            "0": "Mon",
            "1": "Tue",
            "2": "Wed",
            "3": "Thu",
            "4": "Fri",
            "5": "Sat",
            "6": "Sun",
        }
        res = {
            "id": str(calendar.id),
            "name": calendar.name,
            "company_id": calendar.company_id.id,
            "expanded": True,
            "hoursPerDay": calendar.hours_per_day,
            "daysPerWeek": len(
                set(
                    calendar.attendance_ids.filtered(
                        lambda x: x.day_period != "lunch"
                    ).mapped("dayofweek")
                )
            ),
            "unspecifiedTimeIsWorking": False,
            "intervals": [
                {
                    "recurrentStartDate": "on %s at %s"
                    % (
                        day_of_week[interval.dayofweek],
                        format_duration(interval.hour_from),
                    ),
                    "recurrentEndDate": "on %s at %s"
                    % (
                        day_of_week[interval.dayofweek],
                        format_duration(interval.hour_to),
                    ),
                    "isWorking": True,
                }
                for interval in calendar.attendance_ids.filtered(
                    lambda x: x.day_period != "lunch"
                )
            ]
            + [
                {
                    "recurrentStartDate": "on %s at %s"
                    % (
                        day_of_week[interval.dayofweek],
                        format_duration(interval.hour_from),
                    ),
                    "recurrentEndDate": "on %s at %s"
                    % (
                        day_of_week[interval.dayofweek],
                        format_duration(interval.hour_to),
                    ),
                    "isWorking": False,
                }
                for interval in calendar.attendance_ids.filtered(
                    lambda x: x.day_period == "lunch"
                )
            ],
        }
        return res

    def get_calendars(self):
        calendar_env = self.env["resource.calendar"]
        calendars = calendar_env.search([])
        default_id = self.get_default_calendar_id()
        # get all except default one, because default will be merged in one array with
        # this dict in libs/projectModel.js
        calendars_objs = [
            self.convert_odoo_to_gantt(calendar)
            for calendar in calendars
            if str(calendar.id) != default_id
        ]
        return calendars_objs

    def get_default_calendar_id(self):
        return self.get_default_calendar()[0].get("id")

    def get_default_calendar(self):
        su = self.env["ir.config_parameter"].sudo()
        bryntum_default_calendar = su.get_param("bryntum.default_calendar")
        # 1. if available , we load explicit calendar in calendar_config.
        bryntum_default_config = (
            su.get_param("bryntum.calendar_config")
            if bryntum_default_calendar == "user_defined"
            else {}
        )
        # the bryntum_default_config will be a string, so we safe_eval it into a dict
        if bool(bryntum_default_config):
            valid, reason, bryntum_calendar_config = self.validate_calendar_config(
                bryntum_default_config
            )
            if valid:
                return [bryntum_default_config]
        # 2. otherwise we load selected odoo calendar
        # it is a selection field:
        elif bryntum_default_calendar:
            calendar = (
                self.env["resource.calendar"]
                .sudo()
                .browse(int(bryntum_default_calendar))
            )
            return [self.convert_odoo_to_gantt(calendar)]
        # 3. if neither of the two are set, the default calendar is company calendar
        user = self.env.user
        if user and user.company_id.resource_calendar_id:
            return [
                self.convert_odoo_to_gantt(
                    self.env.user.company_id.resource_calendar_id
                )
            ]
        # 4. keeping old hardcoded calendar for reference
        return [
            {
                "id": "general",
                "name": "General",
                "intervals": [],
                "expanded": True,
                "children": [
                    {
                        "id": "business",
                        "name": "Business",
                        "intervals": [
                            {
                                "recurrentStartDate": "every weekday at 12:00",
                                "recurrentEndDate": "every weekday at 13:00",
                                "isWorking": False,
                            },
                            {
                                "recurrentStartDate": "every weekday at 17:00",
                                "recurrentEndDate": "every weekday at 08:00",
                                "isWorking": False,
                            },
                        ],
                    },
                    {
                        "id": "night",
                        "name": "Night shift",
                        "intervals": [
                            {
                                "recurrentStartDate": "every weekday at 6:00",
                                "recurrentEndDate": "every weekday at 22:00",
                                "isWorking": False,
                            }
                        ],
                    },
                ],
            }
        ]

    @api.model
    def get_lib_version(self):
        module = self.env.ref(
            "base.module_bryntum_gantt_enterprise", raise_if_not_found=False
        )
        if module and module.latest_version:
            return "v" + module.latest_version
        return "v0"

    @staticmethod
    def _odoo_to_bryntum_date_format(odoo_fmt):
        """
        Convert Python/Odoo strftime-like format to  format tokens.
        """
        token_map = {
            "%d": "DD",
            "%m": "MM",
            "%Y": "YYYY",
            "%y": "YY",
            "%H": "HH",
            "%M": "mm",  # minutes
            "%S": "ss",
            "%I": "hh",  # 12-hour
            "%p": "A",
            "%a": "ddd",
            "%A": "dddd",
            "%b": "MMM",
            "%B": "MMMM",
            # Useful additions (common in locales)
            "%e": "D",  # day of month (space-padded -> non-padded)
            "%-d": "D",
            "%-m": "M",
            "%-H": "H",
            "%-I": "h",
        }
        fmt = odoo_fmt or "%d/%m/%Y"
        fmt = fmt.replace("%%", "__PERCENT__")
        pattern = re.compile(r"%\-?[A-Za-z]")

        unsupported = set()

        def repl(match):
            token = match.group(0)
            if token in token_map:
                return token_map[token]
            unsupported.add(token)
            return token  # keep as-is (or return "" if you want strict behavior)

        result = pattern.sub(repl, fmt).replace("__PERCENT__", "%")
        if unsupported:
            return False
        return result

    @api.model
    def get_bryntum_values(self):

        lang_env = self.env["res.lang"]
        lang = self.env.user.lang
        lang_rec = lang_env.search([("code", "=", lang)])
        user = self.env.user

        su = self.env["ir.config_parameter"].sudo()
        user_config = user.bryntum_user_config
        allow_user_edit = su.get_param(
            "bryntum.bryntum_enable_user_config_edit", default="False"
        )
        colors_env = self.env["gantt.event.color"].sudo()

        res = {
            "lib_version": self.get_lib_version(),
            "lang": lang,
            "week_start": lang_rec.week_start,
            "date_format": self._odoo_to_bryntum_date_format(lang_rec.date_format),
            "bryntum_auto_scheduling": su.get_param("bryntum.auto_scheduling")
            == "True",
            "bryntum_user_assignment": su.get_param("bryntum.user_assignment")
            == "True",
            "bryntum_readonly_project": su.get_param("bryntum.readonly_projects")
            == "True",
            "bryntum_save_wbs": su.get_param("bryntum.save_wbs") == "True",
            "bryntum_gantt_config": su.get_param("bryntum.gantt_config") or "{}",
            "bryntum_copy_dependencies": su.get_param("bryntum.copy_dependencies"),
            "bryntum_gantt_user_config": loads(user_config),
            "allow_user_view_edit": allow_user_edit == "True",
            "bryntum_css": self.env.user.bryntum_css,
            "bryntum_default_calendar": self.get_default_calendar(),
            "bryntum_odoo_colors": [
                {"id": x.id, "color": x.color, "text": x.name}
                for x in colors_env.search([])
            ],
        }
        return res
