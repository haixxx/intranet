from django.urls import path

from . import api_views

app_name = "attendance_devices_v2_api"

urlpatterns = [
    path("agents/<int:agent_id>/heartbeat", api_views.agent_heartbeat, name="agent_heartbeat"),
    path("agents/<int:agent_id>/devices", api_views.agent_devices, name="agent_devices"),
    path("agents/<int:agent_id>/device-status", api_views.agent_device_status, name="agent_device_status"),
    path("agents/<int:agent_id>/backfill-report", api_views.agent_backfill_report, name="agent_backfill_report"),
    path("agents/<int:agent_id>/time-sync-report", api_views.agent_time_sync_report, name="agent_time_sync_report"),
    path("raw-punches/batch", api_views.raw_punches_batch, name="raw_punches_batch"),
]
