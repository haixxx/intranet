from django.contrib import admin
from .models import AttendanceCode, AttendanceSettings


@admin.register(AttendanceCode)
class AttendanceCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code", "label_vi",
        "segments_am_type", "segments_pm_type",
        "is_work", "requires_am_work", "requires_pm_work",
        "default_in1", "default_out1", "default_in2", "default_out2",
        "priority", "is_active",
    )
    list_filter = ("segments_am_type", "segments_pm_type", "is_work", "is_active")
    search_fields = ("code", "label_vi")
    ordering = ("-priority", "code")
    fieldsets = (
        (None, {
            "fields": ("code", "label_vi", "is_active", "priority", "is_work", "notes")
        }),
        ("Thiết lập buổi sáng/chiều", {
            "fields": ("segments_am_type", "segments_pm_type", "requires_am_work", "requires_pm_work")
        }),
        ("Thời gian mặc định", {
            "fields": ("default_in1", "default_out1", "default_in2", "default_out2"),
            "description": "Điền khi is_work=True và buổi tương ứng có requires_*_work=True."
        }),
    )


@admin.register(AttendanceSettings)
class AttendanceSettingsAdmin(admin.ModelAdmin):
    list_display = ("window_minutes", "cluster_minutes", "round_registration_to_hour")
    fields = ("window_minutes", "cluster_minutes", "round_registration_to_hour")