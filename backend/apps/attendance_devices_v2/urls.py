from django.urls import path, include

from . import views_backoffice
from . import views_backoffice_audit

app_name = "attendance_devices_v2"

urlpatterns = [
    # Backoffice: Agents
    path("backoffice/attendance-devices-v2/agents/", views_backoffice.agent_list, name="agent_list"),
    path("backoffice/attendance-devices-v2/agents/new/", views_backoffice.agent_create, name="agent_create"),
    path("backoffice/attendance-devices-v2/agents/<int:agent_id>/", views_backoffice.agent_edit, name="agent_edit"),
    path("backoffice/attendance-devices-v2/agents/<int:agent_id>/keys/new/", views_backoffice.agent_create_key, name="agent_create_key"),

    # Backoffice: Devices
    path("backoffice/attendance-devices-v2/devices/", views_backoffice.device_list, name="device_list"),
    path("backoffice/attendance-devices-v2/devices/new/", views_backoffice.device_create, name="device_create"),
    path("backoffice/attendance-devices-v2/devices/<int:device_id>/", views_backoffice.device_edit, name="device_edit"),

    # Backoffice: Audit (giữ lại)
    path("backoffice/attendance-devices-v2/audit/", views_backoffice_audit.audit_matches_view, name="audit_matches"),

    # API
    path("api/attendance-devices-v2/", include(("apps.attendance_devices_v2.api_urls", "attendance_devices_v2_api"))),
]