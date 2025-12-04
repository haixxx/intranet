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
        TRAINING = "TRAINING", "Học"
        CHILD_SICK = "CHILD_SICK", "Con ốm"
        NONE = "NONE", "Không áp dụng"

    code = models.CharField(max_length=16, unique=True, help_text="Ví dụ: LL, LP, PL, BB, ...")
    label_vi = models.CharField(max_length=128, help_text="Nhãn hiển thị tiếng Việt")
    segments_am_type = models.CharField(max_length=32, choices=SegmentType.choices, default=SegmentType.WORK)
    segments_pm_type = models.CharField(max_length=32, choices=SegmentType.choices, default=SegmentType.WORK)

    # Ca ngày: yêu cầu 4 mốc nếu WORK ở AM/PM; các loại LEAVE_* không yêu cầu mốc
    requires_am_work = models.BooleanField(default=True, help_text="AM yêu cầu mốc IN1/OUT1 nếu là WORK")
    requires_pm_work = models.BooleanField(default=True, help_text="PM yêu cầu mốc IN2/OUT2 nếu là WORK")

    # Thuộc tính yêu cầu ca: Đi làm thì có ca, nghỉ thì không có ca
    requires_shift = models.BooleanField(default=True, help_text="Yêu cầu chọn ca khi dùng mã này. Mã nghỉ không yêu cầu ca.")

    # Ưu tiên hiển thị trong các select (số càng lớn càng ưu tiên)
    priority = models.PositiveIntegerField(default=0, help_text="Ưu tiên hiển thị (số lớn hiển thị trước)")

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mã chế độ"
        verbose_name_plural = "Mã chế độ"
        ordering = ["-priority", "code"]  # ưu tiên trước, rồi theo mã

    def __str__(self):
        return f"{self.code} - {self.label_vi}"


class AttendanceSettings(models.Model):
    """
    Cấu hình đối chiếu chung (global). Một bản ghi duy nhất.
    - window_minutes: cửa sổ tìm log quanh mốc (mặc định 60)
    - cluster_minutes: ngưỡng gom cụm log để lọc spam (mặc định 2)
    - round_registration_to_hour: NTSK nhập giờ sẽ round theo giờ (00 phút)
    """
    window_minutes = models.PositiveIntegerField(default=60)
    cluster_minutes = models.PositiveIntegerField(default=2)
    round_registration_to_hour = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Cấu hình chấm công"
        verbose_name_plural = "Cấu hình chấm công"

    def __str__(self):
        return f"Attendance settings (window={self.window_minutes}, cluster={self.cluster_minutes})"