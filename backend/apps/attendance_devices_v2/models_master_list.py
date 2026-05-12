from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AttendanceDeviceMasterListV2(models.Model):
    """
    Master List: 1 dòng / employee / work_date / commit.unit

    Lưu:
    - Target (từ AttendanceCommitItem: in1/out1/in2/out2 -> datetime local)
    - Actual (từ compute trên NormalizedPunch + dữ liệu thêm tay)
    - Override (HR sửa; mặc định = actual; recompute không ghi đè override nếu đã sửa)
    - Trạng thái phục vụ báo cáo: thiếu mốc, đi muộn/về sớm, stale, yêu cầu sửa
    """

    class ComputeState(models.TextChoices):
        NOT_COMPUTED = "NOT_COMPUTED", _("Chưa compute")
        COMPUTED = "COMPUTED", _("Đã compute")
        STALE = "STALE", _("Công chốt thay đổi (STALE)")

    class YeuCauSuaTrangThai(models.TextChoices):
        NONE = "NONE", _("Không có")
        DA_YEU_CAU = "DA_YEU_CAU", _("Đã yêu cầu")
        DANG_XU_LY = "DANG_XU_LY", _("Đang xử lý")
        DA_XU_LY = "DA_XU_LY", _("Đã xử lý")
        TU_CHOI = "TU_CHOI", _("Từ chối")

    # Identity
    work_date = models.DateField(db_index=True, verbose_name=_("Ngày làm việc"))
    unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.PROTECT,
        related_name="attendance_device_master_v2",
        db_index=True,
        verbose_name=_("Đơn vị chốt công"),
    )
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_device_master_v2",
        db_index=True,
        verbose_name=_("Nhân sự"),
    )

    # Commit tracking (commit-only)
    commit = models.ForeignKey(
        "attendance.AttendanceCommit",
        on_delete=models.PROTECT,
        related_name="device_master_rows_v2",
        verbose_name=_("Công đã chốt"),
    )
    commit_updated_at_at_compute = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Commit updated_at tại thời điểm compute"),
        help_text=_("Dùng để phát hiện STALE khi công chốt bị sửa sau compute."),
    )

    compute_state = models.CharField(
        max_length=16,
        choices=ComputeState.choices,
        default=ComputeState.NOT_COMPUTED,
        db_index=True,
        verbose_name=_("Trạng thái compute"),
    )
    compute_run_id = models.CharField(max_length=64, blank=True, default="", db_index=True, verbose_name=_("Mã lần compute"))
    compute_version = models.PositiveSmallIntegerField(default=1, verbose_name=_("Phiên bản compute"))
    computed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Compute lúc"))

    # Exempt / Expected
    is_exempt = models.BooleanField(default=False, db_index=True, verbose_name=_("Đặc cách (không yêu cầu chấm máy)"))

    expected_in1 = models.BooleanField(default=False, verbose_name=_("Kỳ vọng IN1"))
    expected_out1 = models.BooleanField(default=False, verbose_name=_("Kỳ vọng OUT1"))
    expected_in2 = models.BooleanField(default=False, verbose_name=_("Kỳ vọng IN2"))
    expected_out2 = models.BooleanField(default=False, verbose_name=_("Kỳ vọng OUT2"))
    expected_marks = models.PositiveSmallIntegerField(default=0, db_index=True, verbose_name=_("Số mốc kỳ vọng"))

    # Target times (datetime local)
    target_in1_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ mục tiêu IN1"))
    target_out1_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ mục tiêu OUT1"))
    target_in2_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ mục tiêu IN2"))
    target_out2_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ mục tiêu OUT2"))

    # Actual times (datetime local) + status + delta
    status_in1 = models.CharField(max_length=16, blank=True, default="", db_index=True, verbose_name=_("Trạng thái IN1"))
    status_out1 = models.CharField(max_length=16, blank=True, default="", db_index=True, verbose_name=_("Trạng thái OUT1"))
    status_in2 = models.CharField(max_length=16, blank=True, default="", db_index=True, verbose_name=_("Trạng thái IN2"))
    status_out2 = models.CharField(max_length=16, blank=True, default="", db_index=True, verbose_name=_("Trạng thái OUT2"))

    actual_in1_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ máy IN1"))
    actual_out1_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ máy OUT1"))
    actual_in2_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ máy IN2"))
    actual_out2_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ máy OUT2"))

    delta_in1_seconds = models.IntegerField(null=True, blank=True, verbose_name=_("Lệch IN1 (giây)"))
    delta_out1_seconds = models.IntegerField(null=True, blank=True, verbose_name=_("Lệch OUT1 (giây)"))
    delta_in2_seconds = models.IntegerField(null=True, blank=True, verbose_name=_("Lệch IN2 (giây)"))
    delta_out2_seconds = models.IntegerField(null=True, blank=True, verbose_name=_("Lệch OUT2 (giây)"))

    # Override times (datetime local) - do HR chỉnh, mặc định = actual
    override_in1_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ đã sửa IN1"))
    override_out1_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ đã sửa OUT1"))
    override_in2_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ đã sửa IN2"))
    override_out2_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ đã sửa OUT2"))

    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Sửa bởi"),
    )
    override_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Sửa lúc"))
    override_note = models.TextField(blank=True, default="", verbose_name=_("Ghi chú sửa"))

    # Summary fields for reporting
    missing_marks = models.PositiveSmallIntegerField(default=0, db_index=True, verbose_name=_("Số mốc thiếu"))

    # =========================
    # YÊU CẦU SỬA (theo employee/day)
    # - Người thống kê phân xưởng tạo yêu cầu.
    # - HR quản lý xử lý yêu cầu và/hoặc sửa giờ override.
    # =========================
    yeu_cau_sua_trang_thai = models.CharField(
        max_length=16,
        choices=YeuCauSuaTrangThai.choices,
        default=YeuCauSuaTrangThai.NONE,
        db_index=True,
        verbose_name=_("Trạng thái yêu cầu sửa"),
    )
    yeu_cau_sua_noi_dung = models.TextField(blank=True, default="", verbose_name=_("Nội dung yêu cầu sửa"))

    yeu_cau_sua_tao_boi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Yêu cầu bởi"),
    )
    yeu_cau_sua_tao_luc = models.DateTimeField(null=True, blank=True, verbose_name=_("Yêu cầu lúc"))

    yeu_cau_sua_xu_ly_boi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Xử lý bởi"),
    )
    yeu_cau_sua_xu_ly_luc = models.DateTimeField(null=True, blank=True, verbose_name=_("Xử lý lúc"))

    class Meta:
        verbose_name = _("Master list chấm công máy (v2)")
        verbose_name_plural = _("Master list chấm công máy (v2)")
        unique_together = (("work_date", "unit", "employee"),)
        indexes = [
            models.Index(fields=["work_date", "unit"]),
            models.Index(fields=["work_date", "unit", "missing_marks"]),
            models.Index(fields=["work_date", "unit", "compute_state"]),
            models.Index(fields=["work_date", "unit", "yeu_cau_sua_trang_thai"]),
        ]

    def __str__(self) -> str:
        return f"{self.work_date} {self.unit_id} emp={self.employee_id} miss={self.missing_marks}/{self.expected_marks}"