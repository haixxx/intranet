from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
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
from .models_master_list import AttendanceDeviceMasterListV2
from .models_manual_punch import AttendanceManualPunch
from .sync_policy import get_device_sync_policy

try:
    from .models import AttendanceDeviceStatusReportV2, AttendanceDeviceBackfillReportV2, AttendanceDeviceTimeSyncReportV2
except Exception:  # pragma: no cover - Phase 2 chưa migrate/model chưa có
    AttendanceDeviceStatusReportV2 = None
    AttendanceDeviceBackfillReportV2 = None
    AttendanceDeviceTimeSyncReportV2 = None


def _bool_badge(value, true_text="Có", false_text="Không"):
    if value:
        return format_html('<span style="color:#198754;font-weight:600;">{}</span>', true_text)
    return format_html('<span style="color:#6c757d;">{}</span>', false_text)


def _status_badge(value: str | None):
    value = value or "-"
    colors = {
        "ACTIVE": "#198754", "ONLINE": "#198754", "SUCCESS": "#198754", "OK": "#198754",
        "COMPUTED": "#198754", "MATCHED": "#198754",
        "PENDING": "#fd7e14", "STALE": "#fd7e14", "PARTIAL_PENDING": "#fd7e14",
        "RECONNECTING": "#fd7e14", "PAUSED_BACKFILL": "#fd7e14", "PAUSED_TIME_SYNC": "#fd7e14",
        "DISABLED": "#6c757d", "UNKNOWN": "#6c757d", "SKIPPED": "#6c757d", "EXEMPT": "#6c757d",
        "OFFLINE": "#dc3545", "ERROR": "#dc3545", "FAILED": "#dc3545", "MISSING": "#dc3545",
        "REALTIME_UNAVAILABLE": "#dc3545",
    }
    color = colors.get(str(value).upper(), "#0d6efd")
    return format_html('<span style="color:{};font-weight:600;">{}</span>', color, value)


def _short_text(value, length: int = 80):
    value = str(value or "")
    return value if len(value) <= length else value[:length] + "..."


class AttendanceDeviceAPIKeyInline(admin.TabularInline):
    model = AttendanceDeviceAPIKeyV2
    extra = 0
    fields = ("key", "is_active", "expires_at", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(AttendanceDeviceAgentV2)
class AttendanceDeviceAgentV2Admin(admin.ModelAdmin):
    list_display = ("name", "hostname", "ip_address", "version", "status_colored", "org_unit", "last_seen_at", "created_at")
    list_filter = ("status", "org_unit")
    search_fields = ("name", "hostname", "ip_address", "version", "notes")
    readonly_fields = ("created_at", "updated_at", "last_seen_at")
    list_select_related = ("org_unit",)
    date_hierarchy = "created_at"
    inlines = (AttendanceDeviceAPIKeyInline,)

    fieldsets = (
        (_("Thông tin Agent"), {"fields": ("name", "hostname", "ip_address", "version", "org_unit", "status")}),
        (_("Theo dõi"), {"fields": ("last_seen_at", "notes")}),
        (_("Hệ thống"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Trạng thái"), ordering="status")
    def status_colored(self, obj):
        return _status_badge(obj.status)


@admin.register(AttendanceDeviceAPIKeyV2)
class AttendanceDeviceAPIKeyV2Admin(admin.ModelAdmin):
    list_display = ("agent", "masked_key", "is_active_colored", "expires_at", "created_at")
    list_filter = ("is_active", "agent")
    search_fields = ("key", "agent__name", "agent__hostname", "agent__ip_address")
    readonly_fields = ("created_at",)
    list_select_related = ("agent",)
    date_hierarchy = "created_at"

    @admin.display(description=_("Key"))
    def masked_key(self, obj):
        key = obj.key or ""
        return key if len(key) <= 12 else f"{key[:8]}...{key[-6:]}"

    @admin.display(description=_("Hiệu lực"), ordering="is_active")
    def is_active_colored(self, obj):
        return _bool_badge(obj.is_active)


@admin.register(AttendanceDeviceV2)
class AttendanceDeviceV2Admin(admin.ModelAdmin):
    list_display = (
        "name", "host_port", "brand", "model", "serial_no", "connect_mode", "is_active_colored",
        "status_colored", "assigned_agent", "org_unit", "last_pull_at", "sync_policy_summary",
    )
    list_filter = ("brand", "connect_mode", "is_active", "status", "assigned_agent", "org_unit")
    search_fields = ("name", "host", "model", "serial_no", "assigned_agent__name", "org_unit__name", "org_unit__symbol")
    readonly_fields = ("last_pull_at", "last_cursor_json", "status", "created_at", "updated_at")
    list_select_related = ("assigned_agent", "org_unit")
    date_hierarchy = "created_at"

    fieldsets = (
        (_("Thông tin thiết bị"), {"fields": ("name", "brand", "model", "serial_no", "connect_mode", "host", "port", "timezone")}),
        (_("Gán quản lý"), {"fields": ("assigned_agent", "org_unit", "is_active", "status")}),
        (_("Cấu hình SDK / Policy"), {"fields": ("sdk_profile",), "description": _("Có thể cấu hình machine_number, comm_password và sync_policy tại đây nếu cần chỉnh JSON trực tiếp.")}),
        (_("Theo dõi"), {"fields": ("last_pull_at", "last_cursor_json", "notes")}),
        (_("Hệ thống"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Host"))
    def host_port(self, obj):
        return f"{obj.host}:{obj.port}"

    @admin.display(description=_("Active"), ordering="is_active")
    def is_active_colored(self, obj):
        return _bool_badge(obj.is_active)

    @admin.display(description=_("Trạng thái"), ordering="status")
    def status_colored(self, obj):
        return _status_badge(obj.status)

    @admin.display(description=_("Policy"))
    def sync_policy_summary(self, obj):
        policy = get_device_sync_policy(obj)
        realtime = policy.get("realtime_enabled", True)
        backfill = policy.get("backfill_enabled", True)
        windows = [
            f"{window.get('time')}/{window.get('days')}d/{window.get('run_mode')}"
            for window in policy.get("backfill_windows", [])
            if window.get("enabled", True)
        ]
        backfill_text = ", ".join(windows) if windows else "No BF window"
        time_sync = policy.get("time_sync_enabled", False)
        return f"{'RT' if realtime else 'No RT'} / {backfill_text if backfill else 'No BF'} / {'Sync giờ' if time_sync else 'Không sync giờ'}"


@admin.register(AttendanceIngestLogV2)
class AttendanceIngestLogV2Admin(admin.ModelAdmin):
    list_display = ("id", "device", "agent", "started_at", "finished_at", "processed", "duplicates", "rejected", "success_colored", "error_short")
    list_filter = ("success", "device", "agent")
    search_fields = ("device__name", "device__host", "error_message", "agent__name", "agent__hostname")
    readonly_fields = ("device", "agent", "started_at", "finished_at", "processed", "duplicates", "rejected", "success", "error_message", "accepted_cursor_snapshot", "created_at")
    list_select_related = ("device", "agent")
    date_hierarchy = "started_at"
    ordering = ("-started_at", "-id")

    @admin.display(description=_("OK"), ordering="success")
    def success_colored(self, obj):
        return _bool_badge(obj.success, "OK", "Lỗi")

    @admin.display(description=_("Lỗi"))
    def error_short(self, obj):
        return _short_text(obj.error_message, 90)


@admin.register(AttendanceRawPunchV2)
class AttendanceRawPunchV2Admin(admin.ModelAdmin):
    list_display = (
        "id", "device", "agent", "device_user_id", "event_time_local", "event_time_utc", "method",
        "normalized_status", "normalized_punch", "device_event_id_short", "ingested_at",
    )
    list_filter = ("method", "device", "agent", "normalized_at")
    search_fields = ("device_user_id", "device_event_id", "dedup_hash", "batch_id", "device__name", "device__host", "agent__name")
    readonly_fields = ("device", "agent", "batch_id", "device_user_id", "event_time_local", "event_time_utc", "method", "device_event_id", "dedup_hash", "meta_json", "ingested_at", "normalized_punch", "normalized_at")
    list_select_related = ("device", "agent", "normalized_punch")
    date_hierarchy = "event_time_local"
    ordering = ("-event_time_utc", "-id")
    raw_id_fields = ("normalized_punch",)
    list_per_page = 100

    @admin.display(description=_("Normalize"), ordering="normalized_at")
    def normalized_status(self, obj):
        if obj.normalized_at:
            return format_html('<span style="color:#198754;font-weight:600;">Đã chuẩn hóa</span>')
        return format_html('<span style="color:#dc3545;font-weight:600;">Chưa map/chưa xử lý</span>')

    @admin.display(description=_("Event ID"))
    def device_event_id_short(self, obj):
        return _short_text(obj.device_event_id, 48)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or super().has_view_permission(request, obj)


@admin.register(AttendanceNormalizedPunchV2)
class AttendanceNormalizedPunchV2Admin(admin.ModelAdmin):
    list_display = ("id", "employee", "employee_code", "employee_card_id", "canonical_time_utc", "best_device", "method", "source_count", "created_at")
    list_filter = ("method", "best_device")
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "best_device__name", "best_device__host")
    readonly_fields = ("employee", "canonical_time_utc", "best_device", "method", "source_count", "sources_json", "created_at")
    list_select_related = ("employee", "best_device")
    date_hierarchy = "canonical_time_utc"
    ordering = ("-canonical_time_utc", "-id")
    list_per_page = 100

    @admin.display(description=_("Mã NV"))
    def employee_code(self, obj):
        return getattr(obj.employee, "employee_code", "")

    @admin.display(description=_("Mã thẻ"))
    def employee_card_id(self, obj):
        return getattr(obj.employee, "card_id", "")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or super().has_view_permission(request, obj)


@admin.register(AttendanceManualPunch)
class AttendanceManualPunchAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "employee_card_id", "thoi_gian_local", "thoi_gian_utc", "source_type", "tao_boi", "tao_luc")
    list_filter = ("tao_luc",)
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "ghi_chu")
    readonly_fields = ("tao_luc",)
    list_select_related = ("employee", "tao_boi")
    date_hierarchy = "thoi_gian_local"
    ordering = ("-thoi_gian_local", "-id")
    raw_id_fields = ("employee", "tao_boi")

    @admin.display(description=_("Mã thẻ"))
    def employee_card_id(self, obj):
        return getattr(obj.employee, "card_id", "")

    @admin.display(description=_("Nguồn"))
    def source_type(self, obj):
        note = (obj.ghi_chu or "").upper()
        if "SOURCE:SUA_DU_LIEU" in note:
            return "Sửa dữ liệu"
        if "SOURCE:MAY_HONG" in note:
            return "Máy hỏng"
        return "Cũ/khác"


@admin.register(AttendancePunchMatchV2)
class AttendancePunchMatchV2Admin(admin.ModelAdmin):
    list_display = ("id", "work_date", "employee", "employee_card_id", "target_field", "status_colored", "target_time_local", "matched_time_local", "delta_seconds", "compute_version", "compute_run_id", "created_at")
    list_filter = ("work_date", "status", "target_field", "compute_version")
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "compute_run_id", "notes")
    readonly_fields = ("work_date", "employee", "target_field", "target_time_local", "matched_punch", "matched_time_local", "delta_seconds", "status", "notes", "compute_run_id", "compute_version", "created_at")
    list_select_related = ("employee", "matched_punch")
    date_hierarchy = "work_date"
    ordering = ("-work_date", "employee__employee_code", "target_field")
    raw_id_fields = ("employee", "matched_punch")
    list_per_page = 100

    @admin.display(description=_("Mã thẻ"))
    def employee_card_id(self, obj):
        return getattr(obj.employee, "card_id", "")

    @admin.display(description=_("Trạng thái"), ordering="status")
    def status_colored(self, obj):
        return _status_badge(obj.status)

    def has_add_permission(self, request):
        return False


@admin.register(AttendanceDeviceMasterListV2)
class AttendanceDeviceMasterListV2Admin(admin.ModelAdmin):
    list_display = ("work_date", "unit", "employee", "employee_card_id", "compute_state_colored", "missing_marks", "is_exempt", "actual_summary", "override_status", "yeu_cau_sua_trang_thai", "computed_at")
    list_filter = ("work_date", "unit", "compute_state", "is_exempt", "missing_marks", "yeu_cau_sua_trang_thai")
    search_fields = ("employee__employee_code", "employee__full_name", "employee__card_id", "compute_run_id", "override_note", "yeu_cau_sua_noi_dung")
    readonly_fields = (
        "work_date", "unit", "employee", "commit", "commit_updated_at_at_compute", "compute_state", "compute_run_id", "compute_version", "computed_at", "is_exempt",
        "expected_in1", "expected_out1", "expected_in2", "expected_out2", "expected_marks",
        "target_in1_local", "target_out1_local", "target_in2_local", "target_out2_local",
        "status_in1", "status_out1", "status_in2", "status_out2",
        "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local",
        "delta_in1_seconds", "delta_out1_seconds", "delta_in2_seconds", "delta_out2_seconds", "missing_marks",
    )
    list_select_related = ("unit", "employee", "commit", "override_by", "yeu_cau_sua_tao_boi", "yeu_cau_sua_xu_ly_boi")
    date_hierarchy = "work_date"
    ordering = ("-work_date", "unit__symbol", "employee__employee_code")
    raw_id_fields = ("unit", "employee", "commit", "override_by", "yeu_cau_sua_tao_boi", "yeu_cau_sua_xu_ly_boi")
    list_per_page = 100

    fieldsets = (
        (_("Identity"), {"fields": ("work_date", "unit", "employee", "commit")}),
        (_("Compute"), {"fields": ("compute_state", "compute_run_id", "compute_version", "computed_at", "commit_updated_at_at_compute")}),
        (_("Expected / Target"), {"fields": ("is_exempt", "expected_in1", "expected_out1", "expected_in2", "expected_out2", "expected_marks", "target_in1_local", "target_out1_local", "target_in2_local", "target_out2_local")}),
        (_("Actual / Status"), {"fields": ("status_in1", "status_out1", "status_in2", "status_out2", "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local", "delta_in1_seconds", "delta_out1_seconds", "delta_in2_seconds", "delta_out2_seconds", "missing_marks")}),
        (_("Override / HR xử lý"), {"fields": ("override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local", "override_by", "override_at", "override_note")}),
        (_("Yêu cầu sửa"), {"fields": ("yeu_cau_sua_trang_thai", "yeu_cau_sua_noi_dung", "yeu_cau_sua_tao_boi", "yeu_cau_sua_tao_luc", "yeu_cau_sua_xu_ly_boi", "yeu_cau_sua_xu_ly_luc")}),
    )

    @admin.display(description=_("Mã thẻ"))
    def employee_card_id(self, obj):
        return getattr(obj.employee, "card_id", "")

    @admin.display(description=_("Compute"), ordering="compute_state")
    def compute_state_colored(self, obj):
        return _status_badge(obj.compute_state)

    @admin.display(description=_("Actual"))
    def actual_summary(self, obj):
        def fmt(dt):
            return dt.strftime("%H:%M") if dt else "-"
        return f"{fmt(obj.actual_in1_local)} / {fmt(obj.actual_out1_local)} / {fmt(obj.actual_in2_local)} / {fmt(obj.actual_out2_local)}"

    @admin.display(description=_("Override?"))
    def override_status(self, obj):
        return format_html('<span style="color:#0d6efd;font-weight:600;">YES</span>') if obj.override_at else "NO"

    def has_add_permission(self, request):
        return False


if AttendanceDeviceStatusReportV2 is not None:
    @admin.register(AttendanceDeviceStatusReportV2)
    class AttendanceDeviceStatusReportV2Admin(admin.ModelAdmin):
        list_display = ("id", "device", "agent", "realtime_status_colored", "last_realtime_at", "last_event_time_local", "last_device_seen_at", "pending_backfill_required", "drift_seconds", "last_error_short", "reported_at")
        list_filter = ("realtime_status", "pending_backfill_required", "device", "agent")
        search_fields = ("device__name", "device__host", "agent__name", "last_error")
        readonly_fields = [f.name for f in AttendanceDeviceStatusReportV2._meta.fields]
        list_select_related = ("device", "agent")
        date_hierarchy = "reported_at"
        ordering = ("-reported_at", "-id")
        list_per_page = 100

        @admin.display(description=_("Realtime"), ordering="realtime_status")
        def realtime_status_colored(self, obj):
            return _status_badge(obj.realtime_status)

        @admin.display(description=_("Lỗi cuối"))
        def last_error_short(self, obj):
            return _short_text(obj.last_error, 80)

        def has_add_permission(self, request):
            return False


if AttendanceDeviceBackfillReportV2 is not None:
    @admin.register(AttendanceDeviceBackfillReportV2)
    class AttendanceDeviceBackfillReportV2Admin(admin.ModelAdmin):
        list_display = ("id", "device", "agent", "window_name", "status_colored", "started_at", "finished_at", "days", "read_total", "filtered", "processed", "duplicates", "rejected", "pending_batches", "error_code", "reported_at")
        list_filter = ("status", "window_name", "need_retry", "need_backfill", "device", "agent")
        search_fields = ("device__name", "device__host", "agent__name", "window_name", "error_code", "error_message")
        readonly_fields = [f.name for f in AttendanceDeviceBackfillReportV2._meta.fields]
        list_select_related = ("device", "agent")
        date_hierarchy = "reported_at"
        ordering = ("-reported_at", "-id")
        list_per_page = 100

        @admin.display(description=_("Backfill"), ordering="status")
        def status_colored(self, obj):
            return _status_badge(obj.status)

        def has_add_permission(self, request):
            return False

if AttendanceDeviceTimeSyncReportV2 is not None:
    @admin.register(AttendanceDeviceTimeSyncReportV2)
    class AttendanceDeviceTimeSyncReportV2Admin(admin.ModelAdmin):
        list_display = ("id", "device", "agent", "window_key", "attempt_no", "status_colored", "before_drift_seconds", "after_drift_seconds", "started_at", "finished_at", "error_code", "reported_at")
        list_filter = ("status", "window_key", "device", "agent")
        search_fields = ("device__name", "device__host", "agent__name", "run_id", "window_key", "error_code", "error_message")
        readonly_fields = [f.name for f in AttendanceDeviceTimeSyncReportV2._meta.fields]
        list_select_related = ("device", "agent")
        date_hierarchy = "reported_at"
        ordering = ("-reported_at", "-id")
        list_per_page = 100

        @admin.display(description=_("Time Sync"), ordering="status")
        def status_colored(self, obj):
            return _status_badge(obj.status)

        def has_add_permission(self, request):
            return False

