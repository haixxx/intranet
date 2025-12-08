from django.contrib import admin
from .models import (
    ApprovalFlow, ApprovalFlowVersion, ApprovalRequest,
    ApprovalStep, ApprovalSigner, ApprovalAction
)


@admin.register(ApprovalFlow)
class ApprovalFlowAdmin(admin.ModelAdmin):
    list_display = ("flow_key", "name", "status", "current_version", "admin_unit_id", "created_at")
    list_filter = ("status",)
    search_fields = ("flow_key", "name", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ApprovalFlowVersion)
class ApprovalFlowVersionAdmin(admin.ModelAdmin):
    list_display = ("flow", "version", "is_active", "published_at", "published_by")
    list_filter = ("is_active",)
    search_fields = ("flow__flow_key", "flow__name", "notes")
    readonly_fields = ("published_at",)


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "object_type", "object_id", "flow", "status", "requester", "submitted_at", "completed_at")
    list_filter = ("status", "flow")
    search_fields = ("title", "object_type", "object_id")
    readonly_fields = ("created_at", "submitted_at", "completed_at")


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ("request", "order_index", "type", "label", "quorum", "status", "activated_at", "completed_at")
    list_filter = ("type", "quorum", "status")
    search_fields = ("label", "request__title")
    readonly_fields = ("activated_at", "completed_at")


@admin.register(ApprovalSigner)
class ApprovalSignerAdmin(admin.ModelAdmin):
    list_display = ("step", "user", "role_title", "unit_id", "group_key", "source", "status", "acted_at", "delegated_to")
    list_filter = ("source", "status")
    search_fields = ("user__username", "user__first_name", "user__last_name", "role_title", "group_key")
    readonly_fields = ("acted_at",)


@admin.register(ApprovalAction)
class ApprovalActionAdmin(admin.ModelAdmin):
    list_display = ("request", "step", "signer", "actor", "action", "created_at")
    list_filter = ("action",)
    search_fields = ("request__title", "actor__username", "actor__first_name", "actor__last_name")
    readonly_fields = ("created_at",)