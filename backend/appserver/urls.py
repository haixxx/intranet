from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "Quản trị kỹ thuật Z115"
admin.site.site_title = "Z115 Admin"
admin.site.index_title = "Bảng điều khiển Django Admin"
admin.site.site_url = "/backoffice/"

urlpatterns = [
    path("admin/", admin.site.urls),

    # i18n: cung cấp route set_language
    path("i18n/", include("django.conf.urls.i18n")),

    # Auth + backoffice chính
    path("auth/", include(("apps.core.urls", "core"), namespace="core")),
    path("backoffice/", include(("apps.backoffice.urls", "backoffice"), namespace="backoffice")),

    # Module chấm công máy v2 đang vận hành chính.
    # Giữ prefix rỗng để không làm thay đổi các URL/API hiện có của module v2.
    path("", include(("apps.attendance_devices_v2.urls", "attendance_devices_v2"), namespace="attendance_devices_v2")),
]

# Module attendance_devices v1 đã ngừng dùng.
# Mặc định không include URL để tránh người dùng/API gọi nhầm module cũ.
# Chỉ bật lại khi cần kiểm tra legacy bằng ENABLE_ATTENDANCE_DEVICES_V1=True.
if getattr(settings, "ENABLE_ATTENDANCE_DEVICES_V1", False):
    urlpatterns.append(
        path(
            "legacy/attendance-devices-v1/",
            include(("apps.attendance_devices.urls", "attendance_devices"), namespace="attendance_devices"),
        )
    )

# Default redirect to dashboard.
# Đặt cuối cùng để không ảnh hưởng các route/API đã khai báo phía trên.
urlpatterns += [
    path("", RedirectView.as_view(pattern_name="backoffice:dashboard", permanent=False)),
]
