from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.hr.models import Employee
from .constants import ReasonCode


class AttendanceManualAdjustment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="att_manual_adjustments")
    work_date = models.DateField()

    # chỉ lưu mốc được sửa (optional)
    in1 = models.TimeField(null=True, blank=True)
    out1 = models.TimeField(null=True, blank=True)
    in2 = models.TimeField(null=True, blank=True)
    out2 = models.TimeField(null=True, blank=True)

    reason_code = models.CharField(max_length=32, choices=ReasonCode.choices)
    note = models.TextField(blank=True, default="")

    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    applied_at = models.DateTimeField(default=timezone.now)

    is_active = models.BooleanField(default=True)  # có thể vô hiệu hóa điều chỉnh
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Điều chỉnh thủ công (mốc ngày)"
        verbose_name_plural = "Điều chỉnh thủ công (mốc ngày)"
        indexes = [
            models.Index(fields=["employee", "work_date"]),
            models.Index(fields=["applied_at"]),
        ]

    def __str__(self):
        return f"ManualAdjust {self.employee_id} {self.work_date} ({self.reason_code})"


class AttendanceImportBatch(models.Model):
    class Mode(models.TextChoices):
        FILL_MISSING_ONLY = "FILL_MISSING_ONLY", "Chỉ bù mốc thiếu"
        OVERWRITE_EXPLICIT = "OVERWRITE_EXPLICIT", "Ghi đè rõ ràng"

    batch_id = models.CharField(max_length=64, unique=True)
    file_name = models.CharField(max_length=255, blank=True, default="")
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    imported_at = models.DateTimeField(default=timezone.now)

    mode = models.CharField(max_length=32, choices=Mode.choices, default=Mode.FILL_MISSING_ONLY)
    reason_code = models.CharField(max_length=32, choices=ReasonCode.choices, blank=True, default="")
    note = models.TextField(blank=True, default="")

    summary_json = models.JSONField(blank=True, null=True)  # created/updated/errors,…

    class Meta:
        verbose_name = "Đợt import Excel/CSV (mốc ngày)"
        verbose_name_plural = "Đợt import Excel/CSV (mốc ngày)"
        indexes = [
            models.Index(fields=["imported_at"]),
            models.Index(fields=["mode"]),
        ]

    def __str__(self):
        return f"ImportBatch {self.batch_id} ({self.mode})"


class AttendanceImportLine(models.Model):
    batch = models.ForeignKey(AttendanceImportBatch, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="+")
    work_date = models.DateField()

    in1 = models.TimeField(null=True, blank=True)
    out1 = models.TimeField(null=True, blank=True)
    in2 = models.TimeField(null=True, blank=True)
    out2 = models.TimeField(null=True, blank=True)

    reason_code = models.CharField(max_length=32, choices=ReasonCode.choices, blank=True, default="")  # override nếu cần
    note = models.TextField(blank=True, default="")

    valid = models.BooleanField(default=True)
    error_msg = models.TextField(blank=True, default="")
    applied = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Dòng import Excel/CSV"
        verbose_name_plural = "Dòng import Excel/CSV"
        unique_together = ("batch", "employee", "work_date")
        indexes = [
            models.Index(fields=["employee", "work_date"]),
        ]

    def __str__(self):
        return f"ImportLine {self.batch_id if hasattr(self, 'batch_id') else self.batch_id} {self.employee_id} {self.work_date}"