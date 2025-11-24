from django.db import models
from django.conf import settings

class AuditLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs'
    )

    # Hành động tách 2 chiều:
    # - action_verb: CREATE / UPDATE / DELETE / LOGIN / LOGOUT / ASSIGN / UNASSIGN ...
    # - object_type: user / group / permission / auth ...
    action_verb = models.CharField(max_length=32, db_index=True)
    object_type = models.CharField(max_length=64, db_index=True)

    # Mã chi tiết tùy chọn, ví dụ: ROLE_PERMISSIONS_UPDATE
    action_code = models.CharField(max_length=64, blank=True, default="", db_index=True)

    object_id = models.CharField(max_length=64, blank=True, default="")
    object_repr = models.CharField(max_length=255, blank=True, default="")

    changes = models.JSONField(blank=True, null=True)
    extra = models.JSONField(blank=True, null=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    severity = models.CharField(max_length=16, default='INFO', db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['object_type', 'object_id']),
            models.Index(fields=['action_verb']),
            models.Index(fields=['action_code']),
        ]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M:%S}] {self.action_verb} {self.object_type}:{self.object_id}"