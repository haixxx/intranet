from django.contrib import admin
from .models import Employee, AccessControl

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