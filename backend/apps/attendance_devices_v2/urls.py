from django.urls import path, include

from . import views_backoffice
from . import views_backoffice_audit
from . import views_backoffice_summary
from . import views_backoffice_dashboard
from . import views_backoffice_report

app_name = "attendance_devices_v2"

urlpatterns = [
    # Backoffice: Dashboard + Report
    path("backoffice/attendance-devices-v2/dashboard/", views_backoffice_dashboard.report_dashboard_view, name="report_dashboard"),
    path("backoffice/attendance-devices-v2/report/units/", views_backoffice_report.report_units_view, name="report_units"),

    # Backoffice: Agents
    path("backoffice/attendance-devices-v2/agents/", views_backoffice.agent_list, name="agent_list"),
    path("backoffice/attendance-devices-v2/agents/new/", views_backoffice.agent_create, name="agent_create"),
    path("backoffice/attendance-devices-v2/agents/<int:agent_id>/", views_backoffice.agent_edit, name="agent_edit"),
    path("backoffice/attendance-devices-v2/agents/<int:agent_id>/keys/new/", views_backoffice.agent_create_key, name="agent_create_key"),

    # Backoffice: Devices
    path("backoffice/attendance-devices-v2/devices/", views_backoffice.device_list, name="device_list"),
    path("backoffice/attendance-devices-v2/devices/new/", views_backoffice.device_create, name="device_create"),
    path("backoffice/attendance-devices-v2/devices/<int:device_id>/", views_backoffice.device_edit, name="device_edit"),

    # Backoffice: Audit
    path("backoffice/attendance-devices-v2/audit/", views_backoffice_audit.audit_matches_view, name="audit_matches"),

    # Backoffice: Summary + Export
    path("backoffice/attendance-devices-v2/summary/", views_backoffice_summary.audit_summary_view, name="audit_summary"),
    path("backoffice/attendance-devices-v2/missing-export.csv", views_backoffice_summary.audit_missing_export_csv, name="audit_missing_export_csv"),

    # API
    path("api/attendance-devices-v2/", include(("apps.attendance_devices_v2.api_urls", "attendance_devices_v2_api"))),
]