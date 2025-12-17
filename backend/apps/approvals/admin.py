from django.contrib import admin
from .models_config import RoleTitleMapping

@admin.register(RoleTitleMapping)
class RoleTitleMappingAdmin(admin.ModelAdmin):
    list_display = ("role_key", "title_code", "is_active")
    list_filter = ("role_key", "is_active")
    search_fields = ("role_key", "title_code")
    ordering = ("role_key", "title_code")