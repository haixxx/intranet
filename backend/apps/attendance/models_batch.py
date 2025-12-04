from django.db import models
from apps.organization.models import OrgUnit
from apps.hr.models import Employee
from apps.attendance.models import AttendanceCode


class AttendanceBatch(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Nháp"
        LOCKED_DRAFT = "LOCKED_DRAFT", "Nháp đã khóa (đã chốt)"

    unit = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="attendance_batches")
    work_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    created_by = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("unit", "work_date")
        verbose_name = "Batch chấm công (Nháp)"
        verbose_name_plural = "Batch chấm công (Nháp)"
        ordering = ["-work_date", "unit_id"]

    def __str__(self):
        return f"{self.unit.code} {self.work_date} ({self.status})"


class AttendanceBatchItem(models.Model):
    class Shift(models.TextChoices):
        DAY = "DAY", "Ca ngày"
        MORNING = "MORNING", "Ca sáng"
        AFTERNOON = "AFTERNOON", "Ca chiều"
        NIGHT = "NIGHT", "Ca tối"

    class BSDirection(models.TextChoices):
        NONE = "NONE", "Không bổ sung"
        IN = "IN", "Bổ sung đến"
        OUT = "OUT", "Bổ sung đi"

    batch = models.ForeignKey(AttendanceBatch, on_delete=models.CASCADE, related_name="items")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="+")
    code = models.ForeignKey(AttendanceCode, on_delete=models.PROTECT, related_name="+")
    shift = models.CharField(max_length=16, choices=Shift.choices, default=Shift.DAY)

    # Ca ngày: 4 mốc; các ca khác dùng in1/out1, in2/out2 để trống
    in1 = models.TimeField(null=True, blank=True)
    out1 = models.TimeField(null=True, blank=True)
    in2 = models.TimeField(null=True, blank=True)
    out2 = models.TimeField(null=True, blank=True)

    notes = models.TextField(blank=True, default="")

    # Bổ sung
    bs_direction = models.CharField(max_length=8, choices=BSDirection.choices, default=BSDirection.NONE)
    bs_peer_unit = models.ForeignKey(OrgUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    include_in_unit = models.BooleanField(default=True)  # False cho BS OUT theo yêu cầu

    class Meta:
        unique_together = ("batch", "employee")
        verbose_name = "Dòng nháp chấm công"
        verbose_name_plural = "Dòng nháp chấm công"
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.batch_id}-{self.employee_id}-{self.code_id}"


class AttendanceCommit(models.Model):
    unit = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="attendance_commits")
    work_date = models.DateField()
    committed_by = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="+")
    committed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("unit", "work_date")
        verbose_name = "Batch chấm công (Đã chốt)"
        verbose_name_plural = "Batch chấm công (Đã chốt)"
        ordering = ["-work_date", "unit_id"]

    def __str__(self):
        return f"{self.unit.code} {self.work_date} (COMMITTED)"


class AttendanceCommitItem(models.Model):
    class Shift(models.TextChoices):
        DAY = "DAY", "Ca ngày"
        MORNING = "MORNING", "Ca sáng"
        AFTERNOON = "AFTERNOON", "Ca chiều"
        NIGHT = "NIGHT", "Ca tối"

    class BSDirection(models.TextChoices):
        NONE = "NONE", "Không bổ sung"
        IN = "IN", "Bổ sung đến"
        OUT = "OUT", "Bổ sung đi"

    commit = models.ForeignKey(AttendanceCommit, on_delete=models.CASCADE, related_name="items")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="+")
    code = models.ForeignKey(AttendanceCode, on_delete=models.PROTECT, related_name="+")
    shift = models.CharField(max_length=16, choices=Shift.choices, default=Shift.DAY)

    in1 = models.TimeField(null=True, blank=True)
    out1 = models.TimeField(null=True, blank=True)
    in2 = models.TimeField(null=True, blank=True)
    out2 = models.TimeField(null=True, blank=True)

    notes = models.TextField(blank=True, default="")

    bs_direction = models.CharField(max_length=8, choices=BSDirection.choices, default=BSDirection.NONE)
    bs_peer_unit = models.ForeignKey(OrgUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    include_in_unit = models.BooleanField(default=True)

    class Meta:
        unique_together = ("commit", "employee")
        verbose_name = "Dòng đã chốt chấm công"
        verbose_name_plural = "Dòng đã chốt chấm công"
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.commit_id}-{self.employee_id}-{self.code_id}"


class AttendanceCorrectionRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Đã gửi đề nghị"
        APPROVED_BY_UNIT = "APPROVED_BY_UNIT", "Đơn vị đã duyệt"
        APPROVED_BY_HR = "APPROVED_BY_HR", "HR đã duyệt"
        APPLIED = "APPLIED", "Đã áp dụng"
        REJECTED = "REJECTED", "Từ chối"

    unit = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="attendance_corrections")
    work_date = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.REQUESTED)

    requested_by = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)

    approved_unit_by = models.ForeignKey("auth.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    approved_unit_at = models.DateTimeField(null=True, blank=True)

    approved_hr_by = models.ForeignKey("auth.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    approved_hr_at = models.DateTimeField(null=True, blank=True)

    applied_at = models.DateTimeField(null=True, blank=True)

    # Danh sách thay đổi dạng JSON: [{employee_id, field, old, new}, ...]
    payload_json = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Phiếu đề nghị sửa chấm công"
        verbose_name_plural = "Phiếu đề nghị sửa chấm công"
        ordering = ["-requested_at", "unit_id", "-work_date"]

    def __str__(self):
        return f"Correction {self.unit.code} {self.work_date} ({self.status})"