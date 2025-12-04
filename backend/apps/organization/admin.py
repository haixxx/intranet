from django.contrib import admin
from .models import OrgUnit, JobTitle, ShiftTemplate

@admin.register(OrgUnit)
class OrgUnitAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'name', 'type', 'parent', 'is_active', 'is_attendance_unit')
    list_filter = ('type', 'is_active', 'is_attendance_unit')
    search_fields = ('symbol', 'name', 'code')
    ordering = ('type', 'symbol')

@admin.register(JobTitle)
class JobTitleAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')

@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'type', 'start_time', 'end_time', 'crosses_midnight', 'is_active')
    list_filter = ('type', 'is_active')
    search_fields = ('code', 'name')