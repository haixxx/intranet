from decimal import Decimal
from datetime import time

from django.apps import apps
from django.core.validators import MinValueValidator
from django.db import models


class AttendanceCode(models.Model):
    class SegmentType(models.TextChoices):
        WORK = "WORK", "Đi làm"
        LEAVE_PAID = "LEAVE_PAID", "Nghỉ phép"
        LEAVE_SICK = "LEAVE_SICK", "Nghỉ ốm"
        LEAVE_COMP = "LEAVE_COMP", "Nghỉ bù"
        LEAVE_UNPAID = "LEAVE_UNPAID", "Nghỉ không lương"
        BUSINESS_TRIP = "BUSINESS_TRIP", "Công tác"
        MATERNITY = "MATERNITY", "Thai sản"
        TRAINING = "TRAINING", "Học/đào tạo"
        CHILD_SICK = "CHILD_SICK", "Con ốm"
        NONE = "NONE", "Không áp dụng"

    class SystemRole(models.TextChoices):
        NORMAL_DAY = "NORMAL_DAY", "Làm ca ngày"
        SHIFT_1 = "SHIFT_1", "Làm ca 1"
        SHIFT_2 = "SHIFT_2", "Làm ca 2"
        SHIFT_3 = "SHIFT_3", "Làm ca 3"
        SUPPLEMENT_OUT = "SUPPLEMENT_OUT", "Bổ sung đi"
        PAID_LEAVE = "PAID_LEAVE", "Nghỉ phép"
        SICK_LEAVE = "SICK_LEAVE", "Nghỉ ốm"
        CHILD_SICK = "CHILD_SICK", "Nghỉ con ốm"
        COMP_LEAVE = "COMP_LEAVE", "Nghỉ bù"
        BUSINESS_TRIP = "BUSINESS_TRIP", "Công tác"
        PERSONAL_LEAVE = "PERSONAL_LEAVE", "Nghỉ việc riêng"
        TRAINING = "TRAINING", "Đào tạo"
        OTHER = "OTHER", "Khác"

    code = models.CharField(
        "Mã",
        max_length=16,
        unique=True,
        help_text="Ví dụ: LL, L1, L2, LP, ...",
    )
    label_vi = models.CharField("Tên mã", max_length=128, help_text="Tên hiển thị tiếng Việt")

    # Giữ tên field cũ để không phá code/migration; UI hiển thị theo khái niệm Phần 1/Phần 2.
    segments_am_type = models.CharField(
        "Phần 1",
        max_length=32,
        choices=SegmentType.choices,
        default=SegmentType.WORK,
    )
    segments_pm_type = models.CharField(
        "Phần 2",
        max_length=32,
        choices=SegmentType.choices,
        default=SegmentType.WORK,
    )

    # is_work = có đi làm hay không; không dùng một mình để quyết định chấm máy.
    is_work = models.BooleanField(
        "Có đi làm",
        default=True,
        help_text="Có đi làm/có trạng thái làm việc. Việc cần chấm máy suy ra từ mốc đăng ký.",
    )

    # Giữ field cũ; UI gọi là Yêu cầu mốc 1/mốc 2.
    requires_am_work = models.BooleanField(
        "Yêu cầu mốc 1",
        default=True,
        help_text="Yêu cầu đủ Giờ vào 1/Giờ ra 1 khi có đi làm.",
    )
    requires_pm_work = models.BooleanField(
        "Yêu cầu mốc 2",
        default=True,
        help_text="Yêu cầu đủ Giờ vào 2/Giờ ra 2 khi có đi làm.",
    )

    default_in1 = models.TimeField("Giờ vào 1", null=True, blank=True)
    default_out1 = models.TimeField("Giờ ra 1", null=True, blank=True)
    default_in2 = models.TimeField("Giờ vào 2", null=True, blank=True)
    default_out2 = models.TimeField("Giờ ra 2", null=True, blank=True)

    work_credit = models.DecimalField(
        "Công làm",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Số công lao động thực tế theo mã.",
    )
    paid_credit = models.DecimalField(
        "Công hưởng lương",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Số công được tính hưởng lương/chế độ.",
    )
    bonus_credit = models.DecimalField(
        "Công nhận thưởng",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Số công phục vụ báo cáo/tính thưởng riêng.",
    )
    registered_hours = models.DecimalField(
        "Giờ đăng ký",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Số giờ đăng ký theo mã; không phải giờ thực tế lấy từ máy.",
    )
    meal_allowance_count = models.DecimalField(
        "Số suất cơm ca",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="0 = không thanh toán; 1 = một suất; có thể mở rộng 0.5/2 nếu quy chế cần.",
    )

    is_system = models.BooleanField(
        "Mã hệ thống",
        default=False,
        help_text="Mã nền của hệ thống; không nên xóa hoặc đổi vai trò sau khi đã dùng.",
    )
    system_role = models.CharField(
        "Vai trò hệ thống",
        max_length=32,
        choices=SystemRole.choices,
        default=SystemRole.OTHER,
        help_text="Vai trò ổn định để báo cáo/code không phụ thuộc hoàn toàn vào chữ mã.",
    )

    # Ưu tiên hiển thị
    priority = models.PositiveIntegerField("Thứ tự hiển thị", default=0, help_text="Số lớn hiển thị trước")
    is_active = models.BooleanField("Kích hoạt", default=True)
    notes = models.TextField("Ghi chú", blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mã chế độ"
        verbose_name_plural = "Mã chế độ"
        ordering = ["-priority", "code"]

    def __str__(self):
        return f"{self.code} - {self.label_vi}"

    @property
    def has_registered_marks(self) -> bool:
        """Có mốc đăng ký IN/OUT thì mới cần đối chiếu vân tay."""
        return bool(self.default_in1 or self.default_out1 or self.default_in2 or self.default_out2)

    def usage_summary(self) -> dict:
        """
        Đếm nhanh số dòng đã dùng mã này trong nháp/chốt.
        Dùng để bảo vệ không xóa/đổi code khi đã phát sinh dữ liệu.
        """
        if not self.pk:
            return {"batch_items": 0, "commit_items": 0, "total": 0}
        try:
            BatchItem = apps.get_model("attendance", "AttendanceBatchItem")
            CommitItem = apps.get_model("attendance", "AttendanceCommitItem")
            batch_count = BatchItem.objects.filter(code_id=self.pk).count()
            commit_count = CommitItem.objects.filter(code_id=self.pk).count()
        except Exception:
            batch_count = 0
            commit_count = 0
        return {
            "batch_items": batch_count,
            "commit_items": commit_count,
            "total": batch_count + commit_count,
        }

    def is_used(self) -> bool:
        return self.usage_summary()["total"] > 0

    def clean(self):
        """
        Ràng buộc nhập thời gian mặc định:
        - is_work=False: không được khai mốc giờ đăng ký.
        - is_work=True:
          + Yêu cầu mốc 1 => phải đủ Giờ vào 1/Giờ ra 1.
          + Không yêu cầu mốc 1 => không khai Giờ vào 1/Giờ ra 1.
          + Tương tự mốc 2.
        """
        from django.core.exceptions import ValidationError

        if not self.is_work:
            if self.default_in1 or self.default_out1 or self.default_in2 or self.default_out2:
                raise ValidationError("Mã không đi làm thì không được khai giờ đăng ký.")
            return

        # Mốc 1
        if self.requires_am_work:
            if not self.default_in1 or not self.default_out1:
                raise ValidationError("Yêu cầu mốc 1 nhưng chưa nhập đủ Giờ vào 1/Giờ ra 1.")
        else:
            if self.default_in1 or self.default_out1:
                raise ValidationError("Không yêu cầu mốc 1 thì không được khai Giờ vào 1/Giờ ra 1.")

        # Mốc 2
        if self.requires_pm_work:
            if not self.default_in2 or not self.default_out2:
                raise ValidationError("Yêu cầu mốc 2 nhưng chưa nhập đủ Giờ vào 2/Giờ ra 2.")
        else:
            if self.default_in2 or self.default_out2:
                raise ValidationError("Không yêu cầu mốc 2 thì không được khai Giờ vào 2/Giờ ra 2.")


class AttendanceSettings(models.Model):
    window_minutes = models.PositiveIntegerField(default=60)
    cluster_minutes = models.PositiveIntegerField(default=2)
    round_registration_to_hour = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Cấu hình chấm công"
        verbose_name_plural = "Cấu hình chấm công"

    def __str__(self):
        return f"Attendance settings (window={self.window_minutes}, cluster={self.cluster_minutes})"

# ---------------------------------------------------------------------
# Import các model được tách file để Django đăng ký đầy đủ trong app
# ---------------------------------------------------------------------
try:
    from apps.attendance.models_batch import (  # noqa: F401
        AttendanceBatch,
        AttendanceBatchItem,
        AttendanceCommit,
        AttendanceCommitItem,
        AttendanceCorrectionRequest,
    )
except Exception:
    pass

try:
    from apps.attendance.models_registration import AttendanceRegistration  # noqa: F401
except Exception:
    pass
