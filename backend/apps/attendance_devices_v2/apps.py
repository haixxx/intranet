from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AttendanceDevicesV2Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.attendance_devices_v2"
    verbose_name = _("Quản lý chấm công")