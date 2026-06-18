from django.db import models
from django.conf import settings  # ADD: để dùng AUTH_USER_MODEL
from apps.organization.models import OrgUnit
from apps.hr.models import Employee
from apps.attendance.models import AttendanceCode


OVERTIME_HOUR_CHOICES = [(i, f"{i} giờ") for i in range(5)]


class AttendanceBatch(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Nháp"
        LOCKED_DRAFT = "LOCKED_DRAFT", "Nháp đã khóa (đã chốt)"

    unit = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="attendance_batches")
    work_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    # FIX: dùng settings.AUTH_USER_MODEL thay vì "auth.User"
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
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

    in1 = models.TimeField(null=True, blank=True)
    out1 = models.TimeField(null=True, blank=True)
    in2 = models.TimeField(null=True, blank=True)
    out2 = models.TimeField(null=True, blank=True)

    # Phase 6: số giờ làm thêm đăng ký để thống kê đơn giản (0-4 giờ).
    overtime_hours = models.PositiveSmallIntegerField(default=0, choices=OVERTIME_HOUR_CHOICES)

    notes = models.TextField(blank=True, default="")

    bs_direction = models.CharField(max_length=8, choices=BSDirection.choices, default=BSDirection.NONE)
    bs_peer_unit = models.ForeignKey(OrgUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    include_in_unit = models.BooleanField(default=True)

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

    # FIX: dùng settings.AUTH_USER_MODEL
    committed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
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

    # Phase 6: số giờ làm thêm đã chốt, phục vụ thống kê lịch sử.
    overtime_hours = models.PositiveSmallIntegerField(default=0, choices=OVERTIME_HOUR_CHOICES)

    notes = models.TextField(blank=True, default="")

    bs_direction = models.CharField(max_length=8, choices=BSDirection.choices, default=BSDirection.NONE)
    bs_peer_unit = models.ForeignKey(OrgUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    include_in_unit = models.BooleanField(default=True)

    # Snapshot tại thời điểm chốt công. Báo cáo lịch sử và thiết bị v2 ưu tiên dùng các trường này
    # để không bị đổi nghĩa khi AttendanceCode được sửa ở các tháng sau.
    code_snapshot = models.CharField(max_length=16, blank=True, default="")
    label_snapshot = models.CharField(max_length=128, blank=True, default="")
    system_role_snapshot = models.CharField(max_length=32, blank=True, default="")
    work_credit_snapshot = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    paid_credit_snapshot = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    bonus_credit_snapshot = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    registered_hours_snapshot = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    meal_allowance_count_snapshot = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_work_snapshot = models.BooleanField(default=False)
    registered_in1_snapshot = models.TimeField(null=True, blank=True)
    registered_out1_snapshot = models.TimeField(null=True, blank=True)
    registered_in2_snapshot = models.TimeField(null=True, blank=True)
    registered_out2_snapshot = models.TimeField(null=True, blank=True)

    class Meta:
        unique_together = ("commit", "employee")
        verbose_name = "Dòng đã chốt chấm công"
        verbose_name_plural = "Dòng đã chốt chấm công"
        ordering = ["employee_id"]

    @property
    def effective_code_text(self) -> str:
        return self.code_snapshot or (self.code.code if self.code_id and self.code else "")

    def apply_code_snapshot(self, source_item=None):
        """
        Copy thông số mã chế độ và mốc giờ đăng ký vào dòng đã chốt.

        source_item thường là AttendanceBatchItem tại thời điểm chốt, vì người dùng có thể
        sửa giờ riêng trên dòng nháp. Khi sửa công sau chốt, source_item có thể bỏ trống
        để lấy chính in1/out1/in2/out2 hiện tại của commit item.
        """
        code = self.code
        src = source_item or self
        self.code_snapshot = code.code if code else ""
        self.label_snapshot = code.label_vi if code else ""
        self.system_role_snapshot = getattr(code, "system_role", "") if code else ""
        self.work_credit_snapshot = getattr(code, "work_credit", 0) or 0
        self.paid_credit_snapshot = getattr(code, "paid_credit", 0) or 0
        self.bonus_credit_snapshot = getattr(code, "bonus_credit", 0) or 0
        self.registered_hours_snapshot = getattr(code, "registered_hours", 0) or 0
        self.meal_allowance_count_snapshot = getattr(code, "meal_allowance_count", 0) or 0
        self.is_work_snapshot = bool(getattr(code, "is_work", False)) if code else False
        self.registered_in1_snapshot = getattr(src, "in1", None)
        self.registered_out1_snapshot = getattr(src, "out1", None)
        self.registered_in2_snapshot = getattr(src, "in2", None)
        self.registered_out2_snapshot = getattr(src, "out2", None)
        return self

    def save_with_snapshot(self, *args, source_item=None, **kwargs):
        self.apply_code_snapshot(source_item=source_item)
        return self.save(*args, **kwargs)

    def __str__(self):
        return f"{self.commit_id}-{self.employee_id}-{self.code_id}"


class AttendanceCorrectionRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Đã gửi đề nghị"
        APPROVED_BY_UNIT = "APPROVED_BY_UNIT", "Đơn vị đã duyệt"
        APPROVED_BY_HR = "APPROVED_BY_HR", "HR đã duyệt"
        APPLIED = "APPLIED", "Đã áp dụng"
        REJECTED = "REJECTED", "Từ chối"
        CANCELLED = "CANCELLED", "Đã hủy"

    unit = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="attendance_corrections")
    work_date = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.REQUESTED)

    # FIX: dùng settings.AUTH_USER_MODEL cho các user FK
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)

    approved_unit_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    approved_unit_at = models.DateTimeField(null=True, blank=True)

    approved_hr_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
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