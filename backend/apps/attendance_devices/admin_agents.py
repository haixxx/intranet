from django.contrib import admin
from .models_agents import AttendanceDeviceAgent, DeviceAPIKey
from .models import AttendanceDevice


@admin.register(AttendanceDeviceAgent)
class AttendanceDeviceAgentAdmin(admin.ModelAdmin):
    list_display = ("name", "hostname", "ip_address", "version", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "hostname", "ip_address", "version")


@admin.register(DeviceAPIKey)
class DeviceAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("agent", "key", "is_active", "expires_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("key", "agent__name")


# Hiển thị agent trong danh sách thiết bị (nếu cần)
class AttendanceDeviceAdminPatched(admin.ModelAdmin):
    list_display = ("name", "host", "port", "brand", "connect_mode", "is_active", "status", "assigned_agent")
    list_filter = ("brand", "connect_mode", "is_active", "status")
    search_fields = ("name", "host", "model", "serial_no")

# Nếu muốn override ở runtime:
# admin.site.unregister(AttendanceDevice)
# admin.site.register(AttendanceDevice, AttendanceDeviceAdminPatched)