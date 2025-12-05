from django.db import models
from datetime import time


class AttendanceCode(models.Model):
    class SegmentType(models.TextChoices):
        WORK = "WORK", "Đi làm"
        LEAVE_PAID = "LEAVE_PAID", "Nghỉ phép"
        LEAVE_SICK = "LEAVE_SICK", "Nghỉ ốm"
        LEAVE_COMP = "LEAVE_COMP", "Nghỉ bù"
        LEAVE_UNPAID = "LEAVE_UNPAID", "Nghỉ không lương"
        BUSINESS_TRIP = "BUSINESS_TRIP", "Công tác"
        MATERNITY = "MATERNITY", "Thai sản"
        TRAINING = "TRAINING", "Học"
        CHILD_SICK = "CHILD_SICK", "Con ốm"
        NONE = "NONE", "Không áp dụng"

    code = models.CharField(max_length=16, unique=True, help_text="Ví dụ: LL, L1, L2, LP, ...")
    label_vi = models.CharField(max_length=128, help_text="Nhãn hiển thị tiếng Việt")

    # Phân loại buổi sáng/chiều
    segments_am_type = models.CharField(max_length=32, choices=SegmentType.choices, default=SegmentType.WORK)
    segments_pm_type = models.CharField(max_length=32, choices=SegmentType.choices, default=SegmentType.WORK)

    # Đi làm / Không đi làm (thay yêu cầu ca)
    is_work = models.BooleanField(default=True, help_text="Đánh dấu mã là 'đi làm'. Nếu không đi làm, disable toàn bộ IN/OUT.")

    # Yêu cầu mốc cho AM/PM nếu là WORK
    requires_am_work = models.BooleanField(default=True, help_text="AM yêu cầu mốc IN1/OUT1 nếu buổi sáng là WORK")
    requires_pm_work = models.BooleanField(default=True, help_text="PM yêu cầu mốc IN2/OUT2 nếu buổi chiều là WORK")

    # Thời gian mặc định dùng để auto đổ nếu yêu cầu mốc
    default_in1 = models.TimeField(null=True, blank=True)
    default_out1 = models.TimeField(null=True, blank=True)
    default_in2 = models.TimeField(null=True, blank=True)
    default_out2 = models.TimeField(null=True, blank=True)

    # Ưu tiên hiển thị
    priority = models.PositiveIntegerField(default=0, help_text="Ưu tiên hiển thị (số lớn hiển thị trước)")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mã chế độ"
        verbose_name_plural = "Mã chế độ"
        ordering = ["-priority", "code"]

    def __str__(self):
        return f"{self.code} - {self.label_vi}"

    def clean(self):
        """
        Ràng buộc nhập thời gian mặc định:
        - Nếu is_work=False: toàn bộ default_* có thể để trống.
        - Nếu is_work=True:
          + Nếu requires_am_work=True: default_in1 và default_out1 bắt buộc.
          + Nếu requires_am_work=False: default_in1/default_out1 phải trống.
          + Tương tự PM.
        """
        from django.core.exceptions import ValidationError

        if not self.is_work:
            # Không đi làm: không yêu cầu default_* bất kỳ
            return

        # AM
        if self.requires_am_work:
            if not self.default_in1 or not self.default_out1:
                raise ValidationError("Yêu cầu mốc AM nhưng chưa nhập thời gian mặc định IN1/OUT1.")
        else:
            if self.default_in1 or self.default_out1:
                raise ValidationError("Không yêu cầu AM thì không được khai IN1/OUT1 mặc định.")

        # PM
        if self.requires_pm_work:
            if not self.default_in2 or not self.default_out2:
                raise ValidationError("Yêu cầu mốc PM nhưng chưa nhập thời gian mặc định IN2/OUT2.")
        else:
            if self.default_in2 or self.default_out2:
                raise ValidationError("Không yêu cầu PM thì không được khai IN2/OUT2 mặc định.")


class AttendanceSettings(models.Model):
    window_minutes = models.PositiveIntegerField(default=60)
    cluster_minutes = models.PositiveIntegerField(default=2)
    round_registration_to_hour = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Cấu hình chấm công"
        verbose_name_plural = "Cấu hình chấm công"

    def __str__(self):
        return f"Attendance settings (window={self.window_minutes}, cluster={self.cluster_minutes})"