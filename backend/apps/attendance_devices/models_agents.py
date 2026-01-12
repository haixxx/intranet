from __future__ import annotations
import secrets
from django.db import models
from django.utils import timezone as dj_timezone

from .models import AttendanceDevice


class AttendanceDeviceAgent(models.Model):
    name = models.CharField(max_length=128)
    hostname = models.CharField(max_length=128, blank=True, default="")
    ip_address = models.CharField(max_length=64, blank=True, default="")
    version = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=dj_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Windows Agent"
        verbose_name_plural = "Windows Agents"
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["hostname"]),
            models.Index(fields=["ip_address"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.hostname})"


class DeviceAPIKey(models.Model):
    agent = models.ForeignKey(AttendanceDeviceAgent, on_delete=models.CASCADE, related_name="api_keys")
    key = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        verbose_name = "Agent API Key"
        verbose_name_plural = "Agent API Keys"
        indexes = [
            models.Index(fields=["agent", "is_active"]),
        ]

    def __str__(self):
        return f"Key for {self.agent_id} active={self.is_active}"

    @staticmethod
    def generate_key() -> str:
        return secrets.token_hex(32)


# Thêm trường assigned_agent cho AttendanceDevice (migrate cần ALTER)
if not hasattr(AttendanceDevice, "assigned_agent"):
    AttendanceDevice.add_to_class(
        "assigned_agent",
        models.ForeignKey(AttendanceDeviceAgent, on_delete=models.SET_NULL, blank=True, null=True, related_name="assigned_devices")
    )