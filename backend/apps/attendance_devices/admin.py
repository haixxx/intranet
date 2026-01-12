from django.contrib import admin
from .models import (
    AttendanceDevice,
    AttendanceEventIngestLog,
    AttendanceDeviceUserMap,
    AttendanceRawEvent,
    AttendanceDayFacts,
)
from .models_adjustments import AttendanceManualAdjustment, AttendanceImportBatch, AttendanceImportLine


@admin.register(AttendanceDevice)
class AttendanceDeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "host", "port", "brand", "connect_mode", "is_active", "status", "last_pull_at")
    list_filter = ("brand", "connect_mode", "is_active", "status")
    search_fields = ("name", "host", "model", "serial_no")
    readonly_fields = ("last_pull_at", "last_cursor_json", "status", "created_at", "updated_at")


@admin.register(AttendanceEventIngestLog)
class AttendanceEventIngestLogAdmin(admin.ModelAdmin):
    list_display = ("device", "started_at", "finished_at", "count", "duplicates", "rejected", "success")
    list_filter = ("success", "device")
    search_fields = ("device__name", "error_message")
    readonly_fields = ("created_at",)


@admin.register(AttendanceDeviceUserMap)
class AttendanceDeviceUserMapAdmin(admin.ModelAdmin):
    list_display = ("device", "device_user_id", "employee", "is_active", "linked_at")
    list_filter = ("device", "is_active")
    search_fields = ("device_user_id", "employee__employee_code", "employee__full_name")
    readonly_fields = ("linked_at",)


@admin.register(AttendanceRawEvent)
class AttendanceRawEventAdmin(admin.ModelAdmin):
    list_display = ("device", "device_user_id", "employee", "event_time_local", "method", "direction", "device_event_id")
    list_filter = ("device", "method", "direction")
    search_fields = ("device_user_id", "device_event_id")
    readonly_fields = ("imported_at",)


@admin.register(AttendanceDayFacts)
class AttendanceDayFactsAdmin(admin.ModelAdmin):
    date_hierarchy = "work_date"
    list_display = (
        "employee", "work_date",
        "in1", "out1", "in2", "out2",
        "effective_in1", "effective_out1", "effective_in2", "effective_out2",
        "source_in1", "source_out1", "source_in2", "source_out2",
        "raw_count", "computed_at", "overlay_version", "last_overlay_at",
    )
    list_filter = ("work_date", "source_in1", "source_out1", "source_in2", "source_out2")
    search_fields = ("employee__employee_code", "employee__full_name")
    readonly_fields = ("computed_at", "last_overlay_at")


@admin.register(AttendanceManualAdjustment)
class AttendanceManualAdjustmentAdmin(admin.ModelAdmin):
    date_hierarchy = "work_date"
    list_display = ("employee", "work_date", "reason_code", "in1", "out1", "in2", "out2", "applied_by", "applied_at", "is_active")
    list_filter = ("reason_code", "is_active")
    search_fields = ("employee__employee_code", "employee__full_name", "note")


@admin.register(AttendanceImportBatch)
class AttendanceImportBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "file_name", "mode", "reason_code", "imported_by", "imported_at")
    list_filter = ("mode", "reason_code")
    search_fields = ("batch_id", "file_name", "note")


@admin.register(AttendanceImportLine)
class AttendanceImportLineAdmin(admin.ModelAdmin):
    date_hierarchy = "work_date"
    list_display = ("batch", "employee", "work_date", "in1", "out1", "in2", "out2", "valid", "applied")
    list_filter = ("valid", "applied")
    search_fields = ("employee__employee_code", "employee__full_name")