from django.db import models
from django.utils import timezone
from datetime import time
from apps.hr.models import Employee
from apps.organization.models import OrgUnit
from .models import AttendanceCode, AttendanceSettings


class AttendanceRegistration(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Nháp"
        SUBMITTED = "SUBMITTED", "Đã chốt"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attend_regs")
    work_date = models.DateField()
    unit_accounting = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="attend_regs")  # quân số thực tế (sẽ set khi đối chiếu)
    code = models.ForeignKey(AttendanceCode, on_delete=models.PROTECT, related_name="attend_regs")

    # Ca để auto điền mốc mặc định (không ép cứng giờ ca)
    shift_code = models.CharField(max_length=32, blank=True, default="")  # ví dụ: DAY, SHIFT1, SHIFT2, SHIFT3

    # Mốc thời gian ca ngày (4 mốc). Ca 1/2/3 dùng IN1/OUT1, để trống IN2/OUT2.
    in1 = models.TimeField(null=True, blank=True)
    out1 = models.TimeField(null=True, blank=True)
    in2 = models.TimeField(null=True, blank=True)
    out2 = models.TimeField(null=True, blank=True)

    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Đăng ký công"
        verbose_name_plural = "Đăng ký công"
        unique_together = ("employee", "work_date")  # mỗi nhân sự mỗi ngày một đăng ký
        ordering = ["-work_date", "employee_id"]

    def __str__(self):
        return f"{self.employee.employee_code} {self.work_date} {self.code.code}"

    def round_times_if_needed(self):
        settings = AttendanceSettings.objects.first()
        if settings and settings.round_registration_to_hour:
            def round_to_hour(t: time | None) -> time | None:
                if not t:
                    return t
                return time(hour=t.hour, minute=0, second=0)
            self.in1 = round_to_hour(self.in1)
            self.out1 = round_to_hour(self.out1)
            self.in2 = round_to_hour(self.in2)
            self.out2 = round_to_hour(self.out2)

    def clean(self):
        # Validate mốc theo code segments
        # WORK ở Phần 1 yêu cầu in1/out1; WORK ở Phần 2 yêu cầu in2/out2
        if self.code.segments_am_type == AttendanceCode.SegmentType.WORK and self.code.requires_am_work:
            if not self.in1 or not self.out1:
                from django.core.exceptions import ValidationError
                raise ValidationError("Thiếu mốc 1 (Giờ vào 1/Giờ ra 1) cho mã chế độ yêu cầu WORK ở Phần 1.")
        if self.code.segments_pm_type == AttendanceCode.SegmentType.WORK and self.code.requires_pm_work:
            if not self.in2 or not self.out2:
                from django.core.exceptions import ValidationError
                raise ValidationError("Thiếu mốc 2 (Giờ vào 2/Giờ ra 2) cho mã chế độ yêu cầu WORK ở Phần 2.")