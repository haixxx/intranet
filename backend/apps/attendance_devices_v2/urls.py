from django.urls import path, include

from . import views_backoffice
from . import views_backoffice_audit
from . import views_backoffice_thong_ke
from . import views_backoffice_bao_cao
from . import views_backoffice_du_lieu

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

    # Backoffice: Audit theo mốc (chỉ HR_ADMIN qua permission)
    path("backoffice/attendance-devices-v2/audit/", views_backoffice_audit.audit_matches_view, name="audit_matches"),

    # UI 1: Báo cáo
    path("backoffice/attendance-devices-v2/bao-cao/", views_backoffice_bao_cao.bao_cao_view, name="bao_cao"),

    # UI 2: Thêm dữ liệu chấm công (bằng tay)
    path("backoffice/attendance-devices-v2/them-du-lieu/", views_backoffice_du_lieu.them_du_lieu_view, name="them_du_lieu"),

    # UI 3: Thống kê Master List + yêu cầu sửa + lưu override
    path("backoffice/attendance-devices-v2/thong-ke/", views_backoffice_thong_ke.thong_ke_view, name="thong_ke"),
    path("backoffice/attendance-devices-v2/thong-ke/luu-du-lieu/", views_backoffice_thong_ke.luu_du_lieu_view, name="luu_du_lieu"),
    path("backoffice/attendance-devices-v2/yeu-cau-sua/", views_backoffice_thong_ke.tao_yeu_cau_sua_view, name="tao_yeu_cau_sua"),

    # API
    path("api/attendance-devices-v2/", include(("apps.attendance_devices_v2.api_urls", "attendance_devices_v2_api"))),
]