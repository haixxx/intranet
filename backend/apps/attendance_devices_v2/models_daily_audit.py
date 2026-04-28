from django.db import models


class AttendanceDailyDeviceAuditV2(models.Model):
    """
    Snapshot per employee/day để làm báo cáo nhanh.

    Commit-only: snapshot chỉ được tạo khi có AttendanceCommit (đã chốt).
    """

    work_date = models.DateField(db_index=True)
    unit_id = models.IntegerField(db_index=True)  # unit của AttendanceCommit
    commit_id = models.IntegerField(db_index=True)

    employee = models.ForeignKey("hr.Employee", on_delete=models.CASCADE, related_name="device_audit_daily_v2")

    # EXEMPT loại khỏi mẫu số
    is_exempt = models.BooleanField(default=False, db_index=True)

    # expected marks theo AttendanceCode.requires_*
    expected_in1 = models.BooleanField(default=False)
    expected_out1 = models.BooleanField(default=False)
    expected_in2 = models.BooleanField(default=False)
    expected_out2 = models.BooleanField(default=False)
    expected_marks = models.PositiveSmallIntegerField(default=0, db_index=True)

    # missing flags (chỉ meaningful nếu expected=True và is_exempt=False)
    missing_in1 = models.BooleanField(default=False, db_index=True)
    missing_out1 = models.BooleanField(default=False, db_index=True)
    missing_in2 = models.BooleanField(default=False, db_index=True)
    missing_out2 = models.BooleanField(default=False, db_index=True)

    matched_marks = models.PositiveSmallIntegerField(default=0)
    missing_marks = models.PositiveSmallIntegerField(default=0, db_index=True)

    # delta minutes (matched - target) cho từng mốc nếu matched, else null
    delta_in1_minutes = models.SmallIntegerField(null=True, blank=True)
    delta_out1_minutes = models.SmallIntegerField(null=True, blank=True)
    delta_in2_minutes = models.SmallIntegerField(null=True, blank=True)
    delta_out2_minutes = models.SmallIntegerField(null=True, blank=True)

    compute_run_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    compute_version = models.PositiveSmallIntegerField(default=1)
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Device audit daily (v2)"
        verbose_name_plural = "Device audit daily (v2)"
        unique_together = (("work_date", "unit_id", "employee"),)
        indexes = [
            models.Index(fields=["work_date", "unit_id"]),
            models.Index(fields=["work_date", "unit_id", "missing_marks"]),
            models.Index(fields=["work_date", "unit_id", "is_exempt"]),
        ]

    def __str__(self):
        return f"{self.work_date} unit={self.unit_id} {self.employee_id} missing={self.missing_marks}/{self.expected_marks}"