from django.contrib import admin
from .models import Employee, AccessControl, TempAssignment

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee_code', 'full_name', 'job_title', 'unit', 'team', 'workforce_type', 'status', 'card_id')
    list_filter = ('workforce_type', 'status', 'job_title', 'unit')
    search_fields = ('employee_code', 'full_name', 'card_id', 'citizen_id', 'tax_code', 'email', 'phone')

@admin.register(AccessControl)
class AccessControlAdmin(admin.ModelAdmin):
    list_display = ('user', 'root_org_unit', 'scope')
    list_filter = ('scope',)
    search_fields = ('user__username', 'root_org_unit__symbol')

@admin.register(TempAssignment)
class TempAssignmentAdmin(admin.ModelAdmin):
    # Ẩn các field auto (from_unit, snapshot, created_by)
    fields = (
        "employee", "to_unit",
        "start_date", "end_date",
        "reason_code", "note",
        "apply_flag",
        # readonly dưới
        "from_unit", "snapshot_employee_unit_at_create",
        "status", "created_at", "cancelled_at"
    )
    readonly_fields = (
        "from_unit", "snapshot_employee_unit_at_create",
        "status", "created_at", "cancelled_at"
    )
    list_display = ("employee", "from_unit", "to_unit", "start_date", "end_date",
                    "status", "reason_code", "apply_flag")
    list_filter = ("status", "reason_code", "to_unit")
    search_fields = ("employee__full_name", "employee__employee_code", "to_unit__symbol")
    autocomplete_fields = ("employee", "to_unit")  # from_unit tự gán

    def save_model(self, request, obj, form, change):
        if not change:
            # Gán created_by khi tạo
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("employee", "from_unit", "to_unit")