from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings

from apps.hr.models import Employee
from apps.organization.models import OrgUnit


class TempAssignment(models.Model):
    """
    Điều động tạm thời nhân sự sang đơn vị khác theo ngày.
    - ACTIVE: đang hiệu lực
    - CANCELLED: huỷ trước hạn
    - EXPIRED: hết hạn (cron có thể chuyển)
    end_date = null => mở cho đến khi huỷ hoặc đặt kết thúc.
    apply_flag: giai đoạn này gộp (dùng để tính effective unit).
    snapshot_employee_unit_at_create: đơn vị gốc thời điểm tạo (phục vụ lịch sử).
    """
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired"

    class Reason(models.TextChoices):
        HT_SX = "HT_SX", "Hỗ trợ sản xuất"
        HT_BCVP = "HT_BCVP", "Hỗ trợ công việc VP"
        THIEU_NGUON = "THIEU_NGUON", "Thiếu nguồn"
        DAO_TAO = "DAO_TAO", "Đào tạo / học việc"
        DU_AN = "DU_AN", "Dự án"
        KHAC = "KHAC", "Khác"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="temp_assignments")
    from_unit = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="+")
    to_unit = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="+")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    reason_code = models.CharField(max_length=32, choices=Reason.choices)
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    apply_flag = models.BooleanField(default=True)
    snapshot_employee_unit_at_create = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")

    class Meta:
        indexes = [
            models.Index(fields=["employee", "start_date"]),
            models.Index(fields=["to_unit", "start_date"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-start_date", "-id"]
        verbose_name = "Điều động tạm thời"
        verbose_name_plural = "Điều động tạm thời"

    def clean(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError("end_date phải >= start_date.")
        overlapping = TempAssignment.objects.filter(
            employee=self.employee,
            status=self.Status.ACTIVE
        ).exclude(pk=self.pk)

        if self.end_date:
            overlapping = overlapping.filter(start_date__lte=self.end_date).filter(
                models.Q(end_date__gte=self.start_date) | models.Q(end_date__isnull=True)
            )
        else:
            overlapping = overlapping.filter(
                models.Q(end_date__isnull=True) | models.Q(end_date__gte=self.start_date)
            ).filter(start_date__lte=self.start_date)

        if overlapping.exists():
            raise ValidationError("Nhân sự đã có điều động ACTIVE chồng chéo.")

    @property
    def is_open_ended(self):
        return self.end_date is None

    @property
    def is_active_today(self):
        if self.status != self.Status.ACTIVE:
            return False
        today = timezone.localdate()
        if self.end_date and self.end_date < today:
            return False
        return self.start_date <= today

    def duration_days(self):
        end = self.end_date or timezone.localdate()
        return (end - self.start_date).days + 1

    def over_duration_warning(self, threshold_days: int = 60) -> bool:
        return self.duration_days() > threshold_days

    def __str__(self):
        segment = f"{self.start_date}" + ("" if self.end_date is None else f" - {self.end_date}")
        return f"{self.employee.employee_code} -> {self.to_unit.symbol} ({segment})"