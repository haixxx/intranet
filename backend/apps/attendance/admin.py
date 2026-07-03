from django.contrib import admin
from .models import AttendanceCode, AttendanceSettings
from .models_batch import (
    AttendanceBatch,
    AttendanceBatchItem,
    AttendanceCommit,
    AttendanceCommitItem,
    AttendanceCorrectionRequest,
)
try:
    from .models_registration import AttendanceRegistration
except Exception:  # pragma: no cover - giữ admin không lỗi nếu model legacy chưa nạp
    AttendanceRegistration = None


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


@admin.register(AttendanceBatch)
class AttendanceBatchAdmin(admin.ModelAdmin):
    list_display = ("work_date", "unit", "status", "item_count", "created_by", "created_at", "updated_at")
    list_filter = ("status", "work_date", "unit")
    search_fields = ("unit__code", "unit__symbol", "unit__name", "created_by__username", "created_by__full_name")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("unit", "created_by")
    list_select_related = ("unit", "created_by")
    date_hierarchy = "work_date"
    ordering = ("-work_date", "unit__symbol")
    list_per_page = 50

    @admin.display(description="Số dòng")
    def item_count(self, obj):
        return obj.items.count()


@admin.register(AttendanceBatchItem)
class AttendanceBatchItemAdmin(admin.ModelAdmin):
    list_display = ("batch", "employee", "employee_code", "code", "shift", "time_summary", "bs_direction", "bs_peer_unit", "include_in_unit", "overtime_hours")
    list_filter = ("batch__work_date", "batch__unit", "code", "shift", "bs_direction", "include_in_unit")
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "batch__unit__symbol", "notes")
    raw_id_fields = ("batch", "employee", "code", "bs_peer_unit")
    list_select_related = ("batch", "batch__unit", "employee", "code", "bs_peer_unit")
    ordering = ("-batch__work_date", "batch__unit__symbol", "employee__employee_code")
    list_per_page = 100

    @admin.display(description="Mã NV")
    def employee_code(self, obj):
        return getattr(obj.employee, "employee_code", "")

    @admin.display(description="Mốc đăng ký")
    def time_summary(self, obj):
        def fmt(value):
            return value.strftime("%H:%M") if value else "-"
        return f"{fmt(obj.in1)} / {fmt(obj.out1)} / {fmt(obj.in2)} / {fmt(obj.out2)}"


@admin.register(AttendanceCommit)
class AttendanceCommitAdmin(admin.ModelAdmin):
    list_display = ("work_date", "unit", "item_count", "committed_by", "committed_at", "updated_at")
    list_filter = ("work_date", "unit")
    search_fields = ("unit__code", "unit__symbol", "unit__name", "committed_by__username", "committed_by__full_name")
    readonly_fields = ("committed_at", "updated_at")
    raw_id_fields = ("unit", "committed_by")
    list_select_related = ("unit", "committed_by")
    date_hierarchy = "work_date"
    ordering = ("-work_date", "unit__symbol")
    list_per_page = 50

    @admin.display(description="Số dòng")
    def item_count(self, obj):
        return obj.items.count()


@admin.register(AttendanceCommitItem)
class AttendanceCommitItemAdmin(admin.ModelAdmin):
    list_display = ("commit", "employee", "employee_code", "effective_code", "shift", "registered_time_summary", "snapshot_summary", "bs_direction", "bs_peer_unit", "overtime_hours")
    list_filter = ("commit__work_date", "commit__unit", "code", "shift", "bs_direction", "include_in_unit", "is_work_snapshot")
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "commit__unit__symbol", "notes", "code_snapshot", "label_snapshot")
    raw_id_fields = ("commit", "employee", "code", "bs_peer_unit")
    list_select_related = ("commit", "commit__unit", "employee", "code", "bs_peer_unit")
    ordering = ("-commit__work_date", "commit__unit__symbol", "employee__employee_code")
    list_per_page = 100

    fieldsets = (
        ("Dòng chốt", {"fields": ("commit", "employee", "code", "shift", "in1", "out1", "in2", "out2", "overtime_hours", "notes")} ),
        ("Bổ sung", {"fields": ("bs_direction", "bs_peer_unit", "include_in_unit")} ),
        ("Snapshot mã chế độ khi chốt", {"fields": ("code_snapshot", "label_snapshot", "system_role_snapshot", "work_credit_snapshot", "paid_credit_snapshot", "bonus_credit_snapshot", "registered_hours_snapshot", "meal_allowance_count_snapshot", "is_work_snapshot", "registered_in1_snapshot", "registered_out1_snapshot", "registered_in2_snapshot", "registered_out2_snapshot"), "classes": ("collapse",)} ),
    )

    @admin.display(description="Mã NV")
    def employee_code(self, obj):
        return getattr(obj.employee, "employee_code", "")

    @admin.display(description="Mã")
    def effective_code(self, obj):
        return obj.effective_code_text

    @admin.display(description="Mốc đăng ký")
    def registered_time_summary(self, obj):
        def fmt(value):
            return value.strftime("%H:%M") if value else "-"
        return f"{fmt(obj.in1)} / {fmt(obj.out1)} / {fmt(obj.in2)} / {fmt(obj.out2)}"

    @admin.display(description="Snapshot")
    def snapshot_summary(self, obj):
        code = obj.code_snapshot or "-"
        return f"{code} · công {obj.work_credit_snapshot} · lương {obj.paid_credit_snapshot}"


@admin.register(AttendanceCorrectionRequest)
class AttendanceCorrectionRequestAdmin(admin.ModelAdmin):
    list_display = ("work_date", "unit", "status", "requested_by", "requested_at", "approved_unit_by", "approved_hr_by", "applied_at", "payload_size")
    list_filter = ("status", "work_date", "unit", "requested_at", "applied_at")
    search_fields = ("unit__code", "unit__symbol", "unit__name", "requested_by__username", "requested_by__full_name")
    readonly_fields = ("requested_at", "approved_unit_at", "approved_hr_at", "applied_at")
    raw_id_fields = ("unit", "requested_by", "approved_unit_by", "approved_hr_by")
    list_select_related = ("unit", "requested_by", "approved_unit_by", "approved_hr_by")
    date_hierarchy = "requested_at"
    ordering = ("-requested_at", "unit__symbol")
    list_per_page = 50

    @admin.display(description="Số thay đổi")
    def payload_size(self, obj):
        return len(obj.payload_json or [])


if AttendanceRegistration is not None:
    @admin.register(AttendanceRegistration)
    class AttendanceRegistrationAdmin(admin.ModelAdmin):
        list_display = ("work_date", "employee", "employee_code", "unit_accounting", "code", "shift_code", "time_summary", "status", "updated_at")
        list_filter = ("status", "work_date", "unit_accounting", "code", "shift_code")
        search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "unit_accounting__symbol", "notes")
        raw_id_fields = ("employee", "unit_accounting", "code")
        list_select_related = ("employee", "unit_accounting", "code")
        date_hierarchy = "work_date"
        ordering = ("-work_date", "employee__employee_code")
        list_per_page = 100

        @admin.display(description="Mã NV")
        def employee_code(self, obj):
            return getattr(obj.employee, "employee_code", "")

        @admin.display(description="Mốc đăng ký")
        def time_summary(self, obj):
            def fmt(value):
                return value.strftime("%H:%M") if value else "-"
            return f"{fmt(obj.in1)} / {fmt(obj.out1)} / {fmt(obj.in2)} / {fmt(obj.out2)}"
