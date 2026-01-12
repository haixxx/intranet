from __future__ import annotations

from django.db import models
from django.utils import timezone as dj_timezone

try:
    from apps.hr.models import Employee
except Exception:
    Employee = None


class AttendanceDevice(models.Model):
    class Brand(models.TextChoices):
        ZKTECO = "ZKTeco", "ZKTeco"
        OTHER = "Other", "Other"

    class ConnectMode(models.TextChoices):
        PULL = "PULL", "Pull"
        PUSH = "PUSH", "Push"
        IMPORT = "IMPORT", "Import"

    class Status(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        OFFLINE = "OFFLINE", "Offline"
        UNKNOWN = "UNKNOWN", "Unknown"

    name = models.CharField(max_length=128)
    brand = models.CharField(max_length=32, choices=Brand.choices, default=Brand.ZKTECO)
    model = models.CharField(max_length=64, blank=True, default="")
    serial_no = models.CharField(max_length=64, blank=True, default="")
    connect_mode = models.CharField(max_length=16, choices=ConnectMode.choices, default=ConnectMode.PULL)

    host = models.CharField(max_length=128)
    port = models.PositiveIntegerField(default=4370)

    timezone = models.CharField(max_length=64, default="Asia/Ho_Chi_Minh")
    is_active = models.BooleanField(default=True)

    sdk_profile = models.JSONField(blank=True, null=True)
    last_cursor_json = models.JSONField(blank=True, null=True)
    last_pull_at = models.DateTimeField(blank=True, null=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNKNOWN)
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(default=dj_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["host", "port"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.host}:{self.port})"


class AttendanceEventIngestLog(models.Model):
    device = models.ForeignKey(AttendanceDevice, on_delete=models.CASCADE, related_name="ingest_logs")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(blank=True, null=True)
    count = models.PositiveIntegerField(default=0)
    duplicates = models.PositiveIntegerField(default=0)
    rejected = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default="")
    last_cursor_snapshot = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["device", "started_at"]),
        ]

    def __str__(self):
        return f"Log #{self.pk} dev={self.device_id} {self.started_at} -> {self.finished_at}"


class AttendanceDeviceUserMap(models.Model):
    device = models.ForeignKey(AttendanceDevice, on_delete=models.CASCADE, related_name="user_maps")
    device_user_id = models.CharField(max_length=64)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, blank=True, null=True, related_name="device_maps") if Employee else models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(default=dj_timezone.now)
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "device_user_id", "is_active"], name="uniq_device_user_active"),
        ]
        indexes = [
            models.Index(fields=["device", "device_user_id"]),
            models.Index(fields=["employee"]) if Employee else models.Index(fields=["device_user_id"]),
        ]

    def __str__(self):
        return f"{self.device_id}:{self.device_user_id} -> {getattr(self.employee, 'id', self.employee)}"


class AttendanceRawEvent(models.Model):
    class Method(models.TextChoices):
        FP = "FP", "Fingerprint"
        CARD = "CARD", "Card"
        FACE = "FACE", "Face"
        OTHER = "OTHER", "Other"

    class Direction(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Unknown"
        IN = "IN", "In"
        OUT = "OUT", "Out"

    device = models.ForeignKey(AttendanceDevice, on_delete=models.CASCADE, related_name="raw_events")
    device_user_id = models.CharField(max_length=64)

    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, blank=True, null=True, related_name="raw_events") if Employee else models.IntegerField(blank=True, null=True)

    event_time_local = models.DateTimeField()
    event_time_utc = models.DateTimeField()

    method = models.CharField(max_length=16, choices=Method.choices, default=Method.OTHER)
    direction = models.CharField(max_length=16, choices=Direction.choices, default=Direction.UNKNOWN)

    device_event_id = models.CharField(max_length=128, blank=True, null=True)
    dedup_hash = models.CharField(max_length=64)

    imported_at = models.DateTimeField(default=dj_timezone.now)
    meta_json = models.JSONField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "device_event_id"], name="uniq_device_event_id", condition=~models.Q(device_event_id__isnull=True)),
            models.UniqueConstraint(fields=["device", "dedup_hash"], name="uniq_device_dedup_hash"),
        ]
        indexes = [
            models.Index(fields=["device", "event_time_utc"]),
            models.Index(fields=["employee", "event_time_utc"]) if Employee else models.Index(fields=["event_time_utc"]),
            models.Index(fields=["dedup_hash"]),
        ]

    def __str__(self):
        return f"{self.device_id}:{self.device_user_id} @{self.event_time_local}"


class AttendanceDayFacts(models.Model):
    """
    Tổng hợp mốc từ máy (computed_*) và mốc hiệu lực sau điều chỉnh (effective_*).
    Nguồn từng mốc: RAW | IMPORT | MANUAL | DEFAULT.
    """
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="day_facts") if Employee else models.IntegerField()
    work_date = models.DateField()

    # Mốc tính từ máy (đang dùng các field in1/out1/... hiện có như computed_*)
    in1 = models.TimeField(null=True, blank=True)
    out1 = models.TimeField(null=True, blank=True)
    in2 = models.TimeField(null=True, blank=True)
    out2 = models.TimeField(null=True, blank=True)

    raw_count = models.PositiveIntegerField(default=0)
    anomalies_json = models.JSONField(blank=True, null=True)
    computed_at = models.DateTimeField(default=dj_timezone.now)

    # Mốc hiệu lực sau overlay adjustments/import
    effective_in1 = models.TimeField(null=True, blank=True)
    effective_out1 = models.TimeField(null=True, blank=True)
    effective_in2 = models.TimeField(null=True, blank=True)
    effective_out2 = models.TimeField(null=True, blank=True)

    SOURCE_CHOICES = [
        ("RAW", "Máy (RAW)"),
        ("IMPORT", "Import"),
        ("MANUAL", "Thủ công"),
        ("DEFAULT", "Mặc định ca"),
        ("", "—"),
    ]
    source_in1 = models.CharField(max_length=16, choices=SOURCE_CHOICES, blank=True, default="")
    source_out1 = models.CharField(max_length=16, choices=SOURCE_CHOICES, blank=True, default="")
    source_in2 = models.CharField(max_length=16, choices=SOURCE_CHOICES, blank=True, default="")
    source_out2 = models.CharField(max_length=16, choices=SOURCE_CHOICES, blank=True, default="")

    overlay_version = models.PositiveIntegerField(default=0)
    last_overlay_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ("employee", "work_date")
        indexes = [
            models.Index(fields=["employee", "work_date"]),
            models.Index(fields=["work_date"]),
        ]
        verbose_name = "Tổng hợp ngày"
        verbose_name_plural = "Tổng hợp ngày"

    def __str__(self):
        return f"{getattr(self.employee, 'id', self.employee)} @ {self.work_date}"