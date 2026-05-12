from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _


class AttendanceManualPunch(models.Model):
    """
    Dữ liệu chấm công thêm tay (chỉ thêm mới, không sửa/xóa theo yêu cầu hiện tại).

    Mục đích:
    - xử lý sự cố máy chấm công (bị hỏng, mất dữ liệu)
    - tạo dữ liệu để test

    Lưu ý:
    - thoi_gian_local: giờ nhập theo local timezone.
    - thoi_gian_utc: giờ UTC tương ứng, dùng để compute chung với NormalizedPunch.
    """

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="manual_punches",
        verbose_name=_("Nhân sự"),
    )

    thoi_gian_local = models.DateTimeField(db_index=True, verbose_name=_("Thời gian (local)"))
    thoi_gian_utc = models.DateTimeField(db_index=True, verbose_name=_("Thời gian (UTC)"))

    ghi_chu = models.TextField(blank=True, default="", verbose_name=_("Ghi chú"))

    tao_boi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Tạo bởi"),
    )
    tao_luc = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Tạo lúc"))

    class Meta:
        verbose_name = _("Dữ liệu chấm công thêm tay")
        verbose_name_plural = _("Dữ liệu chấm công thêm tay")
        indexes = [
            models.Index(fields=["employee", "thoi_gian_utc"]),
            models.Index(fields=["employee", "thoi_gian_local"]),
        ]
        ordering = ["-thoi_gian_local", "employee_id"]

    def __str__(self) -> str:
        return f"ManualPunch emp={self.employee_id} {self.thoi_gian_local}"