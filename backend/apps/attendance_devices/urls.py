from django.urls import path
from .api_views import ingest_raw_events_batch
from .api_views_agents import agent_register, agent_devices, agent_heartbeat, device_cursor_update
from .views_backoffice import device_list, device_create, device_edit, device_delete, device_logs
from .views_user_map import user_map_list, user_map_create, user_map_edit, user_map_deactivate, user_map_bulk_import
from .views_adjustments import day_adjust_select, day_adjust_form
from .views_adjust_bulk import day_adjust_bulk
from .views_import import dayfacts_import
from .views_compare import compare_committed_day

app_name = "attendance_devices"

urlpatterns = [
    # API cho Windows agent push (miễn CSRF trong view)
    path("api/attendance/raw-events/batch", ingest_raw_events_batch, name="ingest_raw_events_batch"),

    # API agent (miễn CSRF trong các view POST)
    path("api/attendance/agents/register", agent_register, name="agent_register"),
    path("api/attendance/agents/<int:agent_id>/devices", agent_devices, name="agent_devices"),
    path("api/attendance/agents/<int:agent_id>/heartbeat", agent_heartbeat, name="agent_heartbeat"),
    path("api/attendance/devices/<int:device_id>/cursor", device_cursor_update, name="device_cursor_update"),

    # Backoffice: quản lý thiết bị
    path("backoffice/att-devices/", device_list, name="backoffice_device_list"),
    path("backoffice/att-devices/new", device_create, name="backoffice_device_new"),
    path("backoffice/att-devices/<int:device_id>/edit", device_edit, name="backoffice_device_edit"),
    path("backoffice/att-devices/<int:device_id>/delete", device_delete, name="backoffice_device_delete"),
    path("backoffice/att-devices/<int:device_id>/logs", device_logs, name="backoffice_device_logs"),
    path("backoffice/att-devices/<int:device_id>/logs", device_logs, name="device_logs"),  # alias để tương thích ngược

    # Backoffice: mapping UID -> Employee
    path("backoffice/att-devices/<int:device_id>/user-map", user_map_list, name="user_map_list"),
    path("backoffice/att-devices/<int:device_id>/user-map/new", user_map_create, name="user_map_create"),
    path("backoffice/att-devices/<int:device_id>/user-map/<int:map_id>/edit", user_map_edit, name="user_map_edit"),
    path("backoffice/att-devices/<int:device_id>/user-map/<int:map_id>/deactivate", user_map_deactivate, name="user_map_deactivate"),
    path("backoffice/att-devices/<int:device_id>/user-map/bulk-import", user_map_bulk_import, name="user_map_bulk_import"),

    # Backoffice: điều chỉnh mốc ngày
    path("backoffice/day-facts/adjust", day_adjust_select, name="day_adjust_select"),
    path("backoffice/day-facts/adjust/<str:employee_code>/<str:work_date>", day_adjust_form, name="day_adjust_form"),
    path("backoffice/day-facts/adjust-bulk", day_adjust_bulk, name="day_adjust_bulk"),

    # Backoffice: import mốc ngày
    path("backoffice/day-facts/import", dayfacts_import, name="dayfacts_import"),

    # So sánh giờ máy vs công đã chốt
    path("backoffice/day-facts/compare-committed", compare_committed_day, name="compare_committed_day"),
]