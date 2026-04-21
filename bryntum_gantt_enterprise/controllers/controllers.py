import logging
from json import loads

import pytz

from odoo import fields, http
from odoo.http import request

from ..tools.controller_utils import (
    field_related,
    gantt_id,
    get_assignment,
    get_assignments,
    get_baselines,
    get_resource_id,
    get_segments,
    is_gantt_new_id,
    to_project_id,
    to_task_id,
)
from ..tools.date_utils import from_gantt_date, get_gantt_date

_logger = logging.getLogger(__name__)


class BryntumGantt(http.Controller):
    task_id_template = "project-task_%d"

    def get_tz(self):
        tz = pytz.utc
        try:
            if type(request.env.user.partner_id.tz) == str:
                tz = pytz.timezone(request.env.user.partner_id.tz) or pytz.utc
        except Exception:
            return tz
        return tz

    @property
    def default_fields(self):
        return [
            ("name", "name", None),
            ("planned_date_begin", "startDate", from_gantt_date),
            ("date_deadline", "endDate", from_gantt_date),
            ("duration", "duration", None),
            ("duration_unit", "durationUnit", None),
            ("parent_id", "parentId", to_task_id),
            ("project_id", "project_id", to_project_id),
            ("parent_index", "parentIndex", None),
            ("percent_done", "percentDone", None),
            ("assigned_ids", "assignedList", None),
            ("description", "note", None),
            ("effort", "effort", None),
            ("gantt_calendar_flex", "calendar", None),
            ("scheduling_mode", "schedulingMode", None),
            ("constraint_type", "constraintType", None),
            ("constraint_date", "constraintDate", from_gantt_date),
            ("effort_driven", "effortDriven", None),
            ("bryntum_rollup", "rollup", None),
            ("force_manual", "forceManuallyScheduledSetting", None),
            ("force_auto", "forceAutoScheduledSetting", None),
            ("manually_scheduled", "manuallyScheduled", None),
            ("stage_id", "stageId", None),
            ("state", "state", None),
            # wbs value and wbs static wiull never be both in dict
            ("wbs_value", "wbsValue", None),
            ("wbs_value", "wbsStatic", None),
            ("tag_ids", "tagIds", None),
            ("inactive", "inactive", None),
            ("milestone", "milestone", None),
            ("show_in_timeline", "showInTimeline", None),
            ("project_constraint_resolution", "projectConstraintResolution", None),
            ("html_color_bryntum_id", "odooColor", None),
        ]

    @http.route("/bryntum_gantt/load", type="json", auth="user")
    def bryntum_gantt_load(self, data=None, **kw):
        """Provide task data from Odoo to Bryntum Gantt widget"""
        data_json = loads(data)
        project_env = request.env["project.project"]
        project_ids = data_json.get("project_ids")
        if "all" in project_ids:
            project_ids = [str(x.id) for x in project_env.search([])]

        # when we use odoo-action reload may be triggered on projects that are
        # not already loaded. we need the full project list.
        only_projects = False

        tz = self.get_tz()
        # user = request.env.user
        project_env = request.env["project.project"]
        task_env = request.env["project.task"]
        resource_env = request.env["resource.resource"]
        project_tag_env = request.env["project.tags"]
        colors_env = request.env["gantt.event.color"]

        # default_calendar_id always returns something
        default_calendar_id = project_env.get_default_calendar_id()

        users = []
        resources = []
        assignments = []
        dependencies = []
        projects = []
        project_nodes = []
        calendar = []
        calendars = []

        use_user_ids = False

        for project_id in project_ids:
            if project_id:
                project_id = int(project_id)
            else:
                continue

            project = project_env.search([("id", "=", project_id)])
            task_objs = project.tasks

            if not project.id:
                continue
            task_domain = [("project_id", "=", project_id)]
            if project.bryntum_dont_load_done_tasks:
                task_domain.append(("state", "in", task_env.OPEN_STATES))
            task_objs = task_env.search(task_domain)

            # This parameter is still needed to pass wbs value to app, it must be on
            # if we use do_not_compute_wbs
            save_wbs = (
                request.env["ir.config_parameter"].sudo().get_param("bryntum.save_wbs")
                == "True"
            )
            # have some default date, it's also used as default task date
            default_date = project.project_start_date or fields.Date.context_today(
                project
            )
            project_id = "project_%d" % project.id

            tasks = [
                {
                    "id": self.task_id_template % task.id,
                    "name": task.name,
                    "parentId": self.task_id_template % task.parent_id,
                    "parentIndex": task.parent_index,
                    "startDate": get_gantt_date(
                        task._read_start_date(default_date), tz
                    ),
                    "endDate": get_gantt_date(task._read_end_date(default_date), tz),
                    "expanded": True,
                    "project_id": project_id,
                    "note": task.description,
                    "effort": task.effort,
                    "duration": task.duration,
                    "durationUnit": task.project_id.duration_unit,
                    "calendar": task.gantt_calendar_flex,
                    "schedulingMode": task.scheduling_mode,
                    "constraintType": task.constraint_type or None,
                    "constraintDate": get_gantt_date(task.constraint_date, tz),
                    "effortDriven": task.effort_driven,
                    "rollup": task.bryntum_rollup,
                    "manuallyScheduled": (
                        False
                        if task.force_auto
                        else (
                            True
                            if task.force_manual
                            else not project.bryntum_auto_scheduling
                        )
                    ),
                    "forceManuallyScheduledSetting": task.force_manual,
                    "forceAutoScheduledSetting": task.force_auto,
                    "baselines": get_baselines(task, tz, get_gantt_date),
                    "segments": get_segments(task, tz, get_gantt_date),
                    "stageId": task.stage_id.id,
                    "state": task.state,
                    "percentDone": task.percent_done,
                    "tagIds": task.tag_ids.ids,
                    "odooColor": task.html_color_bryntum_id.color,
                    "inactive": task.inactive,
                    "milestone": task.milestone,
                    "showInTimeline": task.show_in_timeline,
                    "projectConstraintResolution": task.project_constraint_resolution,
                    "wbsValue": task.wbs_value if save_wbs else "",
                }
                for task in task_objs
            ]

            if project.bryntum_user_assignment:
                use_user_ids = True

            assignments = assignments + [
                {
                    "id": assignment.get("id"),
                    "event": self.task_id_template % assignment.get("event"),
                    "resource": assignment.get("resource"),
                    "units": assignment.get("units"),
                }
                for task in task_objs
                for assignment in get_assignments(task, get_assignment) or []
            ]
            # we cannot leave links to non existant tasks, or we will have strange lines.
            dependencies = dependencies + [
                {
                    "id": link.id,
                    "fromTask": self.task_id_template % link.from_id,
                    "toTask": self.task_id_template % link.to_id,
                    "lag": link.lag,
                    "lagUnit": link.lag_unit,
                    "active": link.dep_active,
                    "type": link.type,
                }
                for task in task_objs
                for link in task.linked_ids
                if link.to_id in task_objs and link.from_id in task_objs
            ]

            project_nodes.append(
                {
                    "id": project_id,
                    "startDate": get_gantt_date(default_date, tz),
                    "name": project.name,
                    "project_id": project_id,
                    "bryntum_percent100_done": project.bryntum_percent100_done,
                    # top level project always auto
                    "manuallyScheduled": False,
                    "realManuallyScheduled": not project.bryntum_auto_scheduling,
                    "durationUnit": project.duration_unit,
                    "expanded": True,
                    "children": tasks,
                }
            )

        if not bool(only_projects):
            all_projects = project_env.search([])
            all_tags = project_tag_env.search([])
            all_colors = colors_env.search([])
            projects = [
                {
                    "id": "all",
                    "name": "All projects",
                    "manuallyScheduled": False,
                    "realManuallyScheduled": False,
                    "taskTypes": [],
                    "taskTags": [{"id": tag.id, "name": tag.name} for tag in all_tags],
                }
            ]
            projects += [
                {
                    "id": "project_%d" % project.id,
                    "name": project.name,
                    "bryntum_percent100_done": project.bryntum_percent100_done,
                    # top level project always auto
                    "manuallyScheduled": False,
                    "realManuallyScheduled": not project.bryntum_auto_scheduling,
                    "taskTypes": [
                        {
                            "id": tp.id,
                            "name": tp.name,
                            "color": tp.html_color_bryntum_id
                            and tp.html_color_bryntum_id.color
                            or False,
                        }
                        for tp in project.type_ids
                    ],
                    "taskColors": [
                        {"id": color.id, "name": color.name, "color": color.color}
                        for color in all_colors
                    ],
                    "taskStates": [
                        {"id": state[0], "name": state[1]}
                        for state in task_env._fields["state"].selection
                    ],
                    "taskTags": [{"id": tag.id, "name": tag.name} for tag in all_tags],
                }
                for project in all_projects
            ]
            resources = []
            resource_ids = resource_env.search([])
            employee_map = dict(
                request.env["hr.employee"]
                .search([])
                .mapped(lambda e: (e.resource_id.id, e.id))
            )
            for resource_id in resource_ids:
                employee_id = employee_map.get(resource_id.id, None)
                if employee_id:
                    avatar = "/web/image/hr.employee/{}/avatar_128".format(employee_id)
                else:
                    avatar = ""
                resources.append(
                    {
                        "id": "r_" + str(resource_id.id),
                        "name": resource_id.name,
                        "avatar": avatar,
                    }
                )

            if use_user_ids:
                user_env = request.env["res.users"]
                user_ids = user_env.search([])
                users = [
                    {
                        "id": "u_" + str(user.id),
                        "name": user.name,
                        "city": user.partner_id.city,
                        "avatar": "/web/image/res.users/{}/avatar_128".format(user.id),
                    }
                    for user in user_ids
                ]

        tag_ids = project_tag_env.search([])
        tagIds = [
            {
                "id": str(tag.id),
                "name": tag.name,
            }
            for tag in tag_ids
        ]
        calendar = project_env.get_default_calendar()
        calendars = project_env.get_calendars()
        params = {
            "success": True,
            "project": {
                "id": "bryntum_gantt_project",
                "hoursPerDay": calendar[0].get("hoursPerDay") or 8,
                "calendar": default_calendar_id,
            },
            "projects": {"rows": projects},
            "calendars": {"rows": calendar, "toProcess": calendars},
            "tasks": {"rows": project_nodes},
            "dependencies": {
                "rows": dependencies,
            },
            "resources": {"rows": users + resources},
            "assignments": {"rows": assignments},
            "timeRanges": {"rows": []},
            "tagIds": {"rows": tagIds},
        }
        return params

    @http.route("/bryntum_gantt/send/update", type="json", auth="user")
    def bryntum_gantt_update(self, data=None, **kw):  # noqa: C901
        data_json = loads(data)
        task_env = request.env["project.task"]
        project_env = request.env["project.project"]
        task_linked_env = request.env["project.task.linked"]
        task_assignments_env = request.env["project.task.assignment"]
        task_baselines_env = request.env["project.task.baseline"]
        task_segments_env = request.env["project.task.segment"]
        task_records = []
        try:
            for el in data_json:
                gantt_model_id = el["model"]["id"]
                model, int_id = gantt_id(gantt_model_id)

                if not int_id:
                    continue
                new_data = el.get("newData", {})
                if model == "project-task":

                    task = task_env.search([("id", "=", int_id)])
                    task_assignments = new_data.get("assignedResources")
                    if task_assignments is not None:
                        task.assigned_resources.unlink()
                        for assignment in task_assignments:
                            resource_id = get_resource_id(assignment.get("resource_id"))
                            task_assignments_env.create(
                                {
                                    "task": to_task_id(assignment.get("task_id")),
                                    "resource": resource_id[0],
                                    "resource_base": resource_id[1],
                                    "units": int(assignment.get("units")),
                                }
                            )
                    task_tags = new_data.pop("tagIds", None)
                    # Our form controller may pass data as a dict instead of a list of
                    # ids in the one case of single tag. we repair this here.
                    if type(task_tags).__name__ == "dict":
                        task_tags = [task_tags.get("id")]
                    tag_ids = []
                    if task_tags is not None:
                        for tag in task_tags:
                            tag_ids += [int(tag)]
                        task.write({"tag_ids": [(6, 0, tag_ids)]})
                    task_color = new_data.pop("odooColor", None)
                    if task_color is not None:
                        task.write({"html_color_bryntum_id": task_color})
                    baselines = new_data.get("baselines")
                    if baselines is not None:
                        task.baselines.unlink()
                        for baseline in baselines:
                            task_baselines_env.create(
                                {
                                    "task": task.id,
                                    "name": baseline.get("name"),
                                    "planned_date_begin": from_gantt_date(
                                        baseline.get("startDate")
                                    ),
                                    "planned_date_end": from_gantt_date(
                                        baseline.get("endDate")
                                    ),
                                }
                            )

                    segments = new_data.get("segments")
                    if segments is not None:
                        task.segments.unlink()
                        for segment in segments:
                            task_segments_env.create(
                                {
                                    "task": task.id,
                                    "name": segment.get("name"),
                                    "planned_date_begin": from_gantt_date(
                                        segment.get("startDate")
                                    ),
                                    "planned_date_end": from_gantt_date(
                                        segment.get("endDate")
                                    ),
                                }
                            )

                    data = field_related(new_data, self.default_fields)
                    task.with_context(from_bryntum=True).write(data)
                    # we need to create tasklinks after the write,
                    # sometimes the to or from fields may not exist in the
                    # case of undo and redo commands.
                    task_records.append(task)
                    task_gantt_ids = new_data.get("taskLinks")
                    if task_gantt_ids is not None:
                        task.linked_ids.unlink()
                        for link in task_gantt_ids:
                            task_linked_env.create(
                                {
                                    "from_id": to_task_id(link.get("from")),
                                    "to_id": to_task_id(link.get("to")),
                                    "lag": int(link.get("lag")),
                                    "lag_unit": link.get("lagUnit"),
                                    "dep_active": link.get("active"),
                                    "type": link.get("type"),
                                }
                            )

                elif model in ("project", "project-project"):
                    project = project_env.sudo().search([("id", "=", int_id)])
                    start_date = new_data.get("startDate")
                    if project and start_date:
                        project.with_context(from_bryntum=True).sudo().write(
                            {"project_start_date": from_gantt_date(start_date)}
                        )
            for task_rec in task_records:
                # we must trigger this for store computed field display_in_project
                # manually, because it is triggered only by form-onchange and
                # project_id. problem exclusively in V18, not needed for v19 and <18.
                task_rec._compute_display_in_project()
            return {"success": True, "status": "updated"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @http.route("/bryntum_gantt/send/log_remove_attempt", type="json", auth="user")
    def bryntum_gantt_remove(self, data=None, **kw):
        data_json = loads(data)
        task_gantt_ids = [item for outer in data_json for item in outer]
        task_int_ids = [to_task_id(el) for el in task_gantt_ids]
        _logger.info("Rem. requested from GVP transport on ids:" + str(task_int_ids))
        # do not return success if GVP taskStore wants to delete tasks, it should never
        # think it was successful.
        return {"success": False, "status": "logged"}

    @http.route("/bryntum_gantt/send/create", type="json", auth="user")
    def bryntum_gantt_create(self, data=None, project_id=None, **kw):
        data_json = loads(data)
        task_env = request.env["project.task"]
        create_int_ids = []
        id_map = {}
        if project_id and not data.get("project_id"):
            data["project_id"] = int(project_id)
        for rec in data_json:
            if not is_gantt_new_id(rec.get("id")):
                continue
            data = field_related(rec, self.default_fields)

            if data["parent_id"] is None:
                data["parent_id"] = id_map.get(rec.get("parentId")) or None

            # color is passed as hex
            if "html_color_bryntum_id" in data.keys() and str(
                data["html_color_bryntum_id"]
            ).startswith("#"):
                data["html_color_bryntum_id"] = (
                    request.env["gantt.event.color"]
                    .search([("color", "=", data["html_color_bryntum_id"])], limit=1)
                    .id
                )
            task = task_env.create(data)
            generated_id = task.id
            id_map[rec.get("id")] = generated_id
            create_int_ids.append((rec.get("id"), self.task_id_template % generated_id))

        return {"success": True, "status": "created", "ids": create_int_ids}

    @http.route("/bryntum_gantt/save_user_config", type="json", auth="user")
    def save_user_config(self, **kwargs):
        config_data = request.httprequest.get_json()
        user = request.env.user.sudo()
        if user.has_group("bryntum_gantt_enterprise.group_save_own_settings"):
            if user:
                # no need to do dumps on config data, data is already string
                request.env["bryntum.gantt.user.config"].sudo().create(
                    {
                        "user_id": user.id,
                        "config_data": config_data["bryntum_user_config"],
                    }
                )
                return {"status": "success"}
            else:
                return {"error": "User %s configs not saved!" % user.name}

    @http.route("/bryntum_gantt/fetch_user_config", type="json", auth="user")
    def fetch_user_config(self, **kw):
        user = request.env.user.sudo()
        if user and user.has_group("bryntum_gantt_enterprise.group_save_own_settings"):
            last_config = (
                request.env["bryntum.gantt.user.config"]
                .sudo()
                .search([("user_id", "=", user.id)], order="create_date desc", limit=1)
            )
            if last_config:
                return {"status": "success", "saved_config": last_config.config_data}
        return {"status": "error", "result": "Settings for user not loaded"}

    @http.route("/bryntum_gantt/switch_theme", type="json", auth="user")
    def switch_theme(self, data=None, **kw):
        data_json = loads(data)
        curr_user = request.env.user
        curr_user.write({"bryntum_css": data_json["theme"]})
        return {}
