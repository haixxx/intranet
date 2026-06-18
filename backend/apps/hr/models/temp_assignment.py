from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TempAssignment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Đang điều động"
        COMPLETED = "COMPLETED", "Đã hoàn thành"
        EXPIRED = "EXPIRED", "Hết hạn"
        CANCELLED = "CANCELLED", "Đã hủy"

    class Reason(models.TextChoices):
        HT_SX = "HT_SX", "Hỗ trợ sản xuất"
        HT_BCVP = "HT_BCVP", "Hỗ trợ công việc VP"
        THIEU_NGUON = "THIEU_NGUON", "Thiếu nguồn"
        DAO_TAO = "DAO_TAO", "Đào tạo / học việc"
        DU_AN = "DU_AN", "Dự án"
        KHAC = "KHAC", "Khác"

    # Dữ liệu chính
    employee = models.ForeignKey("hr.Employee", on_delete=models.CASCADE, related_name="temp_assignments")
    from_unit = models.ForeignKey("organization.OrgUnit", on_delete=models.PROTECT, related_name="+")
    to_unit = models.ForeignKey("organization.OrgUnit", on_delete=models.PROTECT, related_name="+")

    # Khoảng hiệu lực thực tế của điều động.
    # Chấm công dùng start_date/end_date để xác định nhân sự thuộc đơn vị nào theo từng ngày.
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    # Khi hoàn thành sớm/muộn, lưu lại end_date dự kiến cũ để truy vết.
    planned_end_date = models.DateField(null=True, blank=True)

    reason_code = models.CharField(max_length=32, choices=Reason.choices)
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    apply_flag = models.BooleanField(default=True)

    # Snapshot đơn vị gốc tại thời điểm tạo phiếu.
    snapshot_employee_unit_at_create = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.PROTECT,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    completed_note = models.TextField(blank=True, default="")

    # Kết quả scan ảnh hưởng tới bảng công, dùng để hiển thị/cảnh báo.
    last_impact_scan_at = models.DateTimeField(null=True, blank=True)
    last_impact_summary = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["employee", "start_date"]),
            models.Index(fields=["to_unit", "start_date"]),
            models.Index(
                fields=["from_unit", "start_date"],
                name="hr_tempassi_from_un_5f4c8a_idx",
            ),
            models.Index(fields=["status"]),
            models.Index(
                fields=["start_date", "end_date"],
                name="hr_tempassi_start_d_9f6e42_idx",
            ),
        ]
        ordering = ["-start_date", "-id"]
        verbose_name = "Điều động tạm thời"
        verbose_name_plural = "Điều động tạm thời"

    @classmethod
    def effective_statuses(cls) -> list[str]:
        """
        Các trạng thái vẫn có hiệu lực lịch sử trong khoảng start_date/end_date.

        Lưu ý rất quan trọng:
        - ACTIVE: đang còn hiệu lực hoặc chưa đến hạn.
        - EXPIRED: đã quá hạn nhưng vẫn phải được tính cho các ngày trong quá khứ.
        - COMPLETED: đã hoàn thành nhưng vẫn phải được tính cho các ngày trong khoảng điều động.
        - CANCELLED: coi như phiếu bị hủy/không còn hiệu lực cho chấm công.
        """
        return [cls.Status.ACTIVE, cls.Status.EXPIRED, cls.Status.COMPLETED]

    def clean(self):
        from django.apps import apps

        OrgUnit = apps.get_model("organization", "OrgUnit")
        Employee = apps.get_model("hr", "Employee")

        if self.end_date and self.end_date < self.start_date:
            raise ValidationError("Ngày kết thúc phải >= ngày bắt đầu.")

        if self.employee_id:
            if self.employee.status != Employee.Status.ACTIVE:
                raise ValidationError("Chỉ được điều động nhân sự đang làm việc.")

        if self.to_unit_id:
            allowed_unit_types = [OrgUnit.Type.DEPARTMENT, OrgUnit.Type.DIVISION, OrgUnit.Type.WORKSHOP]
            if self.to_unit.type not in allowed_unit_types:
                raise ValidationError("Đơn vị nhận điều động phải là Phòng/Ban/Phân xưởng.")
            if not self.to_unit.is_active:
                raise ValidationError("Đơn vị nhận điều động đã ngừng hoạt động.")

        # Khi tạo mới, from_unit phải là đơn vị gốc hiện tại.
        # Khi sửa phiếu cũ, giữ snapshot from_unit, không ép theo Employee.unit hiện tại
        # để tránh làm sai lịch sử.
        if not self.pk and self.employee_id and self.from_unit_id and self.employee.unit_id != self.from_unit_id:
            raise ValidationError("from_unit phải trùng với đơn vị gốc hiện tại của nhân sự khi tạo mới.")

        if self.from_unit_id and self.to_unit_id and self.from_unit_id == self.to_unit_id:
            raise ValidationError("Đơn vị nhận điều động không được trùng đơn vị gốc.")

        # Chỉ chặn chồng chéo với các phiếu có hiệu lực cho chấm công.
        if self.employee_id and self.status != self.Status.CANCELLED:
            overlapping = TempAssignment.objects.filter(
                employee_id=self.employee_id,
                status__in=self.effective_statuses(),
            ).exclude(pk=self.pk)

            new_end = self.end_date
            if new_end:
                overlapping = overlapping.filter(start_date__lte=new_end).filter(
                    models.Q(end_date__gte=self.start_date) | models.Q(end_date__isnull=True)
                )
            else:
                # Phiếu mới mở vô hạn: chồng với mọi phiếu đã bắt đầu trước/vào tương lai
                # mà chưa kết thúc trước start_date.
                overlapping = overlapping.filter(
                    models.Q(end_date__isnull=True) | models.Q(end_date__gte=self.start_date)
                )

            if overlapping.exists():
                raise ValidationError("Nhân sự đã có điều động chồng chéo trong khoảng thời gian này.")

    def save(self, *args, **kwargs):
        if not self.pk:
            if self.employee_id:
                if not self.from_unit_id:
                    self.from_unit_id = self.employee.unit_id
                if not self.snapshot_employee_unit_at_create_id:
                    self.snapshot_employee_unit_at_create_id = self.employee.unit_id
            if not self.status:
                self.status = self.Status.ACTIVE
        super().save(*args, **kwargs)

    @property
    def is_open_ended(self):
        return self.end_date is None

    @property
    def is_active_today(self):
        return self.is_effective_on(timezone.localdate())

    def is_effective_on(self, work_date):
        if self.status not in self.effective_statuses():
            return False
        if self.start_date > work_date:
            return False
        if self.end_date and self.end_date < work_date:
            return False
        return True

    def duration_days(self):
        end = self.end_date or timezone.localdate()
        return (end - self.start_date).days + 1

    def over_duration_warning(self, threshold_days: int = 60) -> bool:
        return self.status == self.Status.ACTIVE and self.duration_days() > threshold_days

    def complete(self, *, actual_end_date, user=None, note: str = ""):
        """
        Hoàn thành điều động.

        Quy tắc:
        - Không xóa phiếu.
        - Không sửa Employee.unit.
        - end_date trở thành ngày kết thúc hiệu lực thực tế.
        - planned_end_date lưu lại end_date cũ để truy vết nếu có.
        - status chuyển COMPLETED.
        """
        if self.status != self.Status.ACTIVE:
            raise ValidationError("Chỉ được hoàn thành điều động đang ACTIVE.")

        if actual_end_date < self.start_date:
            raise ValidationError("Ngày hoàn thành không được trước ngày bắt đầu.")

        if self.planned_end_date is None:
            self.planned_end_date = self.end_date

        self.end_date = actual_end_date
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.completed_by = user
        self.completed_note = note or ""
        self.full_clean()
        self.save(
            update_fields=[
                "planned_end_date",
                "end_date",
                "status",
                "completed_at",
                "completed_by",
                "completed_note",
            ]
        )

    def cancel(self, *, user=None):
        if self.status != self.Status.ACTIVE:
            raise ValidationError("Chỉ được hủy điều động đang ACTIVE.")
        self.status = self.Status.CANCELLED
        self.cancelled_at = timezone.now()
        self.cancelled_by = user
        self.save(update_fields=["status", "cancelled_at", "cancelled_by"])

    def affected_range_after_completion(self, old_end_date=None):
        """
        Khoảng ngày có thể bị ảnh hưởng khi hoàn thành sớm.

        Nếu trước đây phiếu mở vô hạn, chỉ có thể scan các batch/commit đã tồn tại
        từ ngày sau end_date mới trở đi.
        """
        if not self.end_date:
            return None, None
        start = self.end_date + timedelta(days=1)
        return start, old_end_date

    def __str__(self):
        seg = f"{self.start_date}" + ("" if self.end_date is None else f" - {self.end_date}")
        return f"{self.employee.employee_code} -> {self.to_unit.symbol} ({seg})"
