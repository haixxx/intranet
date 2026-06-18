from django.contrib import admin
from .models import AttendanceCode, AttendanceSettings


@admin.register(AttendanceCode)
class AttendanceCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code", "label_vi", "system_role", "is_system",
        "segments_am_type", "segments_pm_type",
        "is_work", "requires_am_work", "requires_pm_work",
        "default_in1", "default_out1", "default_in2", "default_out2",
        "work_credit", "paid_credit", "bonus_credit", "registered_hours", "meal_allowance_count",
        "priority", "is_active",
    )
    list_filter = ("system_role", "is_system", "segments_am_type", "segments_pm_type", "is_work", "is_active")
    search_fields = ("code", "label_vi")
    ordering = ("-priority", "code")
    fieldsets = (
        ("Thông tin chung", {
            "fields": ("code", "label_vi", "is_active", "priority", "is_system", "system_role", "notes")
        }),
        ("Phân loại và mốc giờ", {
            "fields": (
                "segments_am_type", "segments_pm_type", "is_work",
                "requires_am_work", "requires_pm_work",
                "default_in1", "default_out1", "default_in2", "default_out2",
            ),
            "description": "Tên field kỹ thuật cũ AM/PM được hiểu nghiệp vụ là Phần 1/Phần 2."
        }),
        ("Chỉ tiêu tính công", {
            "fields": (
                "work_credit", "paid_credit", "bonus_credit",
                "registered_hours", "meal_allowance_count",
            )
        }),
    )


@admin.register(AttendanceSettings)
class AttendanceSettingsAdmin(admin.ModelAdmin):
    list_display = ("window_minutes", "cluster_minutes", "round_registration_to_hour")
    fields = ("window_minutes", "cluster_minutes", "round_registration_to_hour")
