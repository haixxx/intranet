from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    AttendanceDeviceAgentV2,
    AttendanceDeviceAPIKeyV2,
    AttendanceDeviceV2,
    AttendanceIngestLogV2,
    AttendanceRawPunchV2,
    AttendanceNormalizedPunchV2,
    AttendancePunchMatchV2,
)


@admin.register(AttendanceDeviceAgentV2)
class AttendanceDeviceAgentV2Admin(admin.ModelAdmin):
    list_display = ("name", "hostname", "ip_address", "version", "status", "org_unit", "last_seen_at", "created_at")
    list_filter = ("status", "org_unit")
    search_fields = ("name", "hostname", "ip_address", "version")
    readonly_fields = ("created_at", "updated_at", "last_seen_at")


@admin.register(AttendanceDeviceAPIKeyV2)
class AttendanceDeviceAPIKeyV2Admin(admin.ModelAdmin):
    list_display = ("agent", "key", "is_active", "expires_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("key", "agent__name")
    readonly_fields = ("created_at",)


@admin.register(AttendanceDeviceV2)
class AttendanceDeviceV2Admin(admin.ModelAdmin):
    list_display = ("name", "host", "port", "brand", "connect_mode", "is_active", "status", "assigned_agent", "org_unit", "last_pull_at")
    list_filter = ("brand", "connect_mode", "is_active", "status", "assigned_agent", "org_unit")
    search_fields = ("name", "host", "model", "serial_no")
    readonly_fields = ("last_pull_at", "last_cursor_json", "status", "created_at", "updated_at")


@admin.register(AttendanceIngestLogV2)
class AttendanceIngestLogV2Admin(admin.ModelAdmin):
    list_display = ("device", "agent", "started_at", "finished_at", "processed", "duplicates", "rejected", "success")
    list_filter = ("success", "device", "agent")
    search_fields = ("device__name", "error_message", "agent__name")
    readonly_fields = ("created_at",)


@admin.register(AttendanceRawPunchV2)
class AttendanceRawPunchV2Admin(admin.ModelAdmin):
    list_display = ("device", "agent", "device_user_id", "event_time_local", "method", "device_event_id", "ingested_at")
    list_filter = ("device", "method", "agent")
    search_fields = ("device_user_id", "device_event_id", "device__name")
    readonly_fields = ("ingested_at",)


@admin.register(AttendanceNormalizedPunchV2)
class AttendanceNormalizedPunchV2Admin(admin.ModelAdmin):
    list_display = ("employee", "canonical_time_utc", "best_device", "method", "source_count", "created_at")
    list_filter = ("method", "best_device")
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id")
    readonly_fields = ("created_at",)


@admin.register(AttendancePunchMatchV2)
class AttendancePunchMatchV2Admin(admin.ModelAdmin):
    list_display = ("work_date", "employee", "target_field", "status", "delta_seconds", "compute_version", "compute_run_id", "created_at")
    list_filter = ("status", "target_field", "compute_version")
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "compute_run_id")
    readonly_fields = ("created_at",)