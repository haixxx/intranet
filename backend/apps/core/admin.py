from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, AppSetting

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # Các nhóm field hiển thị khi xem/sửa user
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email", "full_name", "department")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    # Các field khi tạo mới user trong admin
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "password1", "password2", "email", "full_name", "department", "is_active", "is_staff", "is_superuser", "groups"),
        }),
    )
    list_display = ("username", "email", "full_name", "department", "is_staff", "is_active")
    search_fields = ("username", "full_name", "email", "department")
    ordering = ("username",)

@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value")
    search_fields = ("key",)