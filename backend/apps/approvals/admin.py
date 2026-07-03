from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalFlowVersion,
    ApprovalRequest,
    ApprovalSigner,
    ApprovalStep,
)
from .models_config import RoleTitleMapping


def _status_badge(value: str | None):
    value = value or "-"
    colors = {
        "DRAFT": ("#475569", "#f1f5f9", "#cbd5e1"),
        "PUBLISHED": ("#047857", "#ecfdf5", "#a7f3d0"),
        "ACTIVE": ("#047857", "#ecfdf5", "#a7f3d0"),
        "APPROVED": ("#047857", "#ecfdf5", "#a7f3d0"),
        "COMPLETED": ("#047857", "#ecfdf5", "#a7f3d0"),
        "SUBMITTED": ("#1d4ed8", "#eff6ff", "#bfdbfe"),
        "IN_PROGRESS": ("#1d4ed8", "#eff6ff", "#bfdbfe"),
        "PENDING": ("#b45309", "#fffbeb", "#fde68a"),
        "REJECTED": ("#b91c1c", "#fef2f2", "#fecaca"),
        "CANCELLED": ("#64748b", "#f8fafc", "#cbd5e1"),
        "ARCHIVED": ("#64748b", "#f8fafc", "#cbd5e1"),
    }
    fg, bg, border = colors.get(str(value).upper(), ("#0f172a", "#f8fafc", "#cbd5e1"))
    return format_html(
        '<span style="display:inline-flex;align-items:center;border:1px solid {};border-radius:999px;padding:2px 8px;background:{};color:{};font-weight:700;font-size:12px;">{}</span>',
        border,
        bg,
        fg,
        value,
    )


@admin.register(ApprovalFlow)
class ApprovalFlowAdmin(admin.ModelAdmin):
    list_display = ("flow_key", "name", "status_colored", "current_version", "admin_unit_id", "created_by", "updated_at")
    list_filter = ("status", "created_at", "updated_at")
    search_fields = ("flow_key", "name", "description")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("created_by",)
    date_hierarchy = "created_at"
    ordering = ("flow_key",)

    fieldsets = (
        (_("Thông tin luồng"), {"fields": ("flow_key", "name", "description", "status", "current_version")} ),
        (_("Phạm vi / cấu hình"), {"fields": ("admin_unit_id", "settings_json")} ),
        (_("Hệ thống"), {"fields": ("created_by", "created_at", "updated_at"), "classes": ("collapse",)} ),
    )

    @admin.display(description=_("Trạng thái"), ordering="status")
    def status_colored(self, obj):
        return _status_badge(obj.status)


@admin.register(ApprovalFlowVersion)
class ApprovalFlowVersionAdmin(admin.ModelAdmin):
    list_display = ("flow", "version", "is_active_colored", "published_at", "published_by", "notes_short")
    list_filter = ("is_active", "published_at", "flow")
    search_fields = ("flow__flow_key", "flow__name", "notes")
    raw_id_fields = ("flow", "published_by")
    date_hierarchy = "published_at"
    ordering = ("flow__flow_key", "-version")

    fieldsets = (
        (_("Phiên bản"), {"fields": ("flow", "version", "is_active", "notes")} ),
        (_("Cấu hình bước"), {"fields": ("steps_json",), "description": _("Nên chỉnh luồng bằng màn hình Backoffice > Luồng duyệt để tránh sai cấu trúc JSON.")} ),
        (_("Công bố"), {"fields": ("published_at", "published_by")} ),
    )

    @admin.display(description=_("Đang dùng"), ordering="is_active")
    def is_active_colored(self, obj):
        return _status_badge("ACTIVE" if obj.is_active else "DRAFT")

    @admin.display(description=_("Ghi chú"))
    def notes_short(self, obj):
        value = obj.notes or ""
        return value if len(value) <= 80 else value[:80] + "..."


class ApprovalStepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 0
    fields = ("order_index", "label", "type", "quorum", "status", "activated_at", "completed_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "flow", "status_colored", "requester", "unit_id", "submitted_at", "completed_at", "created_at")
    list_filter = ("status", "flow", "created_at", "submitted_at", "completed_at")
    search_fields = ("title", "object_type", "object_id", "requester__username", "requester__full_name")
    readonly_fields = (
        "flow", "flow_version", "object_type", "object_id", "title", "unit_id", "requester",
        "status", "metadata_json", "content_html", "content_json", "content_schema_version",
        "created_at", "submitted_at", "completed_at",
    )
    raw_id_fields = ("flow", "flow_version", "requester")
    list_select_related = ("flow", "flow_version", "requester")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")
    inlines = (ApprovalStepInline,)

    @admin.display(description=_("Trạng thái"), ordering="status")
    def status_colored(self, obj):
        return _status_badge(obj.status)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or super().has_view_permission(request, obj)


class ApprovalSignerInline(admin.TabularInline):
    model = ApprovalSigner
    extra = 0
    fields = ("user", "role_title", "unit_id", "group_key", "is_required", "source", "status", "acted_at", "delegated_to")
    readonly_fields = fields
    raw_id_fields = ("user", "delegated_to")
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ("request", "order_index", "label", "type", "quorum", "status_colored", "activated_at", "completed_at")
    list_filter = ("status", "type", "quorum")
    search_fields = ("request__title", "label", "resolver_config")
    readonly_fields = ("request", "order_index", "type", "label", "quorum", "resolver_config", "allow_overrides", "status", "activated_at", "completed_at")
    raw_id_fields = ("request",)
    list_select_related = ("request",)
    ordering = ("-request__created_at", "request_id", "order_index")
    inlines = (ApprovalSignerInline,)

    @admin.display(description=_("Trạng thái"), ordering="status")
    def status_colored(self, obj):
        return _status_badge(obj.status)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or super().has_view_permission(request, obj)


@admin.register(ApprovalSigner)
class ApprovalSignerAdmin(admin.ModelAdmin):
    list_display = ("id", "step", "user", "role_title", "unit_id", "group_key", "is_required", "source", "status_colored", "acted_at")
    list_filter = ("status", "source", "is_required")
    search_fields = ("user__username", "user__full_name", "role_title", "group_key", "step__request__title")
    readonly_fields = ("step", "user", "role_title", "unit_id", "group_key", "is_required", "source", "status", "acted_at", "delegated_to")
    raw_id_fields = ("step", "user", "delegated_to")
    list_select_related = ("step", "step__request", "user", "delegated_to")
    ordering = ("-step__request__created_at", "step__order_index", "id")

    @admin.display(description=_("Trạng thái"), ordering="status")
    def status_colored(self, obj):
        return _status_badge(obj.status)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or super().has_view_permission(request, obj)


@admin.register(ApprovalAction)
class ApprovalActionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "request", "step", "signer", "actor", "action_colored", "comment_short")
    list_filter = ("action", "created_at")
    search_fields = ("request__title", "actor__username", "actor__full_name", "comment")
    readonly_fields = [f.name for f in ApprovalAction._meta.fields]
    raw_id_fields = ("request", "step", "signer", "actor")
    list_select_related = ("request", "step", "signer", "actor")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")

    @admin.display(description=_("Hành động"), ordering="action")
    def action_colored(self, obj):
        return _status_badge(obj.action)

    @admin.display(description=_("Bình luận"))
    def comment_short(self, obj):
        value = obj.comment or ""
        return value if len(value) <= 80 else value[:80] + "..."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RoleTitleMapping)
class RoleTitleMappingAdmin(admin.ModelAdmin):
    list_display = ("role_key", "title_code", "is_active")
    list_filter = ("role_key", "is_active")
    search_fields = ("role_key", "title_code")
    ordering = ("role_key", "title_code")
