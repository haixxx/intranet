from django.contrib import admin
from .models import AttendanceCode, AttendanceSettings


@admin.register(AttendanceCode)
class AttendanceCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "label_vi", "segments_am_type", "segments_pm_type", "requires_shift", "priority", "is_active")
    list_filter = ("segments_am_type", "segments_pm_type", "requires_shift", "is_active")
    search_fields = ("code", "label_vi")
    ordering = ("-priority", "code")
    fieldsets = (
        (None, {
            "fields": ("code", "label_vi", "is_active", "priority", "requires_shift", "notes")
        }),
        ("Ca ngày (AM/PM)", {
            "fields": ("segments_am_type", "segments_pm_type", "requires_am_work", "requires_pm_work")
        }),
    )


@admin.register(AttendanceSettings)
class AttendanceSettingsAdmin(admin.ModelAdmin):
    list_display = ("window_minutes", "cluster_minutes", "round_registration_to_hour")
    fields = ("window_minutes", "cluster_minutes", "round_registration_to_hour")