# Generated manually for Phase 5B/5C: attendance code standardization + commit snapshots.

from decimal import Decimal
from datetime import time

from django.core.validators import MinValueValidator
from django.db import migrations, models


SYSTEM_ROLES = {
    "LL": {
        "label_vi": "Làm ca ngày",
        "segments_am_type": "WORK", "segments_pm_type": "WORK",
        "is_work": True, "requires_am_work": True, "requires_pm_work": True,
        "default_in1": time(7, 0), "default_out1": time(11, 0),
        "default_in2": time(13, 0), "default_out2": time(17, 0),
        "work_credit": Decimal("1.00"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("1.00"),
        "registered_hours": Decimal("8.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "NORMAL_DAY", "priority": 100,
    },
    "L1": {
        "label_vi": "Làm ca 1",
        "segments_am_type": "WORK", "segments_pm_type": "NONE",
        "is_work": True, "requires_am_work": True, "requires_pm_work": False,
        "default_in1": time(6, 0), "default_out1": time(14, 0),
        "default_in2": None, "default_out2": None,
        "work_credit": Decimal("1.00"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("1.00"),
        "registered_hours": Decimal("8.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "SHIFT_1", "priority": 95,
    },
    "L2": {
        "label_vi": "Làm ca 2",
        "segments_am_type": "WORK", "segments_pm_type": "NONE",
        "is_work": True, "requires_am_work": True, "requires_pm_work": False,
        "default_in1": time(14, 0), "default_out1": time(22, 0),
        "default_in2": None, "default_out2": None,
        "work_credit": Decimal("1.00"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("1.00"),
        "registered_hours": Decimal("8.00"), "meal_allowance_count": Decimal("1.00"),
        "is_system": True, "system_role": "SHIFT_2", "priority": 90,
    },
    "L3": {
        "label_vi": "Làm ca 3",
        "segments_am_type": "WORK", "segments_pm_type": "NONE",
        "is_work": True, "requires_am_work": True, "requires_pm_work": False,
        "default_in1": time(22, 0), "default_out1": time(6, 0),
        "default_in2": None, "default_out2": None,
        "work_credit": Decimal("1.00"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("1.00"),
        "registered_hours": Decimal("8.00"), "meal_allowance_count": Decimal("1.00"),
        "is_system": True, "system_role": "SHIFT_3", "priority": 85,
    },
    "BS": {
        "label_vi": "Bổ sung đi",
        "segments_am_type": "NONE", "segments_pm_type": "NONE",
        "is_work": False, "requires_am_work": False, "requires_pm_work": False,
        "default_in1": None, "default_out1": None, "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.00"), "paid_credit": Decimal("0.00"), "bonus_credit": Decimal("0.00"),
        "registered_hours": Decimal("0.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "SUPPLEMENT_OUT", "priority": 80,
    },
    "CT": {
        "label_vi": "Công tác",
        "segments_am_type": "BUSINESS_TRIP", "segments_pm_type": "BUSINESS_TRIP",
        "is_work": True, "requires_am_work": False, "requires_pm_work": False,
        "default_in1": None, "default_out1": None, "default_in2": None, "default_out2": None,
        "work_credit": Decimal("1.00"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("0.00"),
        "registered_hours": Decimal("8.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "BUSINESS_TRIP", "priority": 70,
    },
    "P": {
        "label_vi": "Nghỉ phép",
        "segments_am_type": "LEAVE_PAID", "segments_pm_type": "LEAVE_PAID",
        "is_work": False, "requires_am_work": False, "requires_pm_work": False,
        "default_in1": None, "default_out1": None, "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.00"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("0.00"),
        "registered_hours": Decimal("0.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "PAID_LEAVE", "priority": 60,
    },
    "O": {
        "label_vi": "Nghỉ ốm",
        "segments_am_type": "LEAVE_SICK", "segments_pm_type": "LEAVE_SICK",
        "is_work": False, "requires_am_work": False, "requires_pm_work": False,
        "default_in1": None, "default_out1": None, "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.00"), "paid_credit": Decimal("0.00"), "bonus_credit": Decimal("0.00"),
        "registered_hours": Decimal("0.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "SICK_LEAVE", "priority": 55,
    },
    "C": {
        "label_vi": "Nghỉ con ốm",
        "segments_am_type": "CHILD_SICK", "segments_pm_type": "CHILD_SICK",
        "is_work": False, "requires_am_work": False, "requires_pm_work": False,
        "default_in1": None, "default_out1": None, "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.00"), "paid_credit": Decimal("0.00"), "bonus_credit": Decimal("0.00"),
        "registered_hours": Decimal("0.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "CHILD_SICK", "priority": 54,
    },
    "B": {
        "label_vi": "Nghỉ bù",
        "segments_am_type": "LEAVE_COMP", "segments_pm_type": "LEAVE_COMP",
        "is_work": False, "requires_am_work": False, "requires_pm_work": False,
        "default_in1": None, "default_out1": None, "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.00"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("0.00"),
        "registered_hours": Decimal("0.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "COMP_LEAVE", "priority": 53,
    },
    "R": {
        "label_vi": "Nghỉ việc riêng",
        "segments_am_type": "LEAVE_UNPAID", "segments_pm_type": "LEAVE_UNPAID",
        "is_work": False, "requires_am_work": False, "requires_pm_work": False,
        "default_in1": None, "default_out1": None, "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.00"), "paid_credit": Decimal("0.00"), "bonus_credit": Decimal("0.00"),
        "registered_hours": Decimal("0.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "PERSONAL_LEAVE", "priority": 52,
    },
    "LP": {
        "label_vi": "Làm sáng - Phép chiều",
        "segments_am_type": "WORK", "segments_pm_type": "LEAVE_PAID",
        "is_work": True, "requires_am_work": True, "requires_pm_work": False,
        "default_in1": time(7, 0), "default_out1": time(11, 0), "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.50"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("0.50"),
        "registered_hours": Decimal("4.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "OTHER", "priority": 50,
    },
    "PL": {
        "label_vi": "Phép sáng - Làm chiều",
        "segments_am_type": "LEAVE_PAID", "segments_pm_type": "WORK",
        "is_work": True, "requires_am_work": False, "requires_pm_work": True,
        "default_in1": None, "default_out1": None, "default_in2": time(13, 0), "default_out2": time(17, 0),
        "work_credit": Decimal("0.50"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("0.50"),
        "registered_hours": Decimal("4.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "OTHER", "priority": 49,
    },
    "LB": {
        "label_vi": "Làm sáng - Bù chiều",
        "segments_am_type": "WORK", "segments_pm_type": "LEAVE_COMP",
        "is_work": True, "requires_am_work": True, "requires_pm_work": False,
        "default_in1": time(7, 0), "default_out1": time(11, 0), "default_in2": None, "default_out2": None,
        "work_credit": Decimal("0.50"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("0.50"),
        "registered_hours": Decimal("4.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "OTHER", "priority": 48,
    },
    "BL": {
        "label_vi": "Bù sáng - Làm chiều",
        "segments_am_type": "LEAVE_COMP", "segments_pm_type": "WORK",
        "is_work": True, "requires_am_work": False, "requires_pm_work": True,
        "default_in1": None, "default_out1": None, "default_in2": time(13, 0), "default_out2": time(17, 0),
        "work_credit": Decimal("0.50"), "paid_credit": Decimal("1.00"), "bonus_credit": Decimal("0.50"),
        "registered_hours": Decimal("4.00"), "meal_allowance_count": Decimal("0.00"),
        "is_system": True, "system_role": "OTHER", "priority": 47,
    },
}


def seed_attendance_codes(apps, schema_editor):
    AttendanceCode = apps.get_model("attendance", "AttendanceCode")
    for code, defaults in SYSTEM_ROLES.items():
        AttendanceCode.objects.update_or_create(code=code, defaults=defaults)

    # Với các mã tự tạo khác, đặt role mặc định OTHER và giữ nguyên các thông tin đã có.
    AttendanceCode.objects.filter(system_role="").update(system_role="OTHER")


def backfill_commit_snapshots(apps, schema_editor):
    AttendanceCommitItem = apps.get_model("attendance", "AttendanceCommitItem")
    for item in AttendanceCommitItem.objects.select_related("code").iterator(chunk_size=1000):
        code = item.code
        item.code_snapshot = code.code if code else ""
        item.label_snapshot = code.label_vi if code else ""
        item.system_role_snapshot = getattr(code, "system_role", "") if code else ""
        item.work_credit_snapshot = getattr(code, "work_credit", Decimal("0.00")) if code else Decimal("0.00")
        item.paid_credit_snapshot = getattr(code, "paid_credit", Decimal("0.00")) if code else Decimal("0.00")
        item.bonus_credit_snapshot = getattr(code, "bonus_credit", Decimal("0.00")) if code else Decimal("0.00")
        item.registered_hours_snapshot = getattr(code, "registered_hours", Decimal("0.00")) if code else Decimal("0.00")
        item.meal_allowance_count_snapshot = getattr(code, "meal_allowance_count", Decimal("0.00")) if code else Decimal("0.00")
        item.is_work_snapshot = bool(getattr(code, "is_work", False)) if code else False
        item.registered_in1_snapshot = item.in1
        item.registered_out1_snapshot = item.out1
        item.registered_in2_snapshot = item.in2
        item.registered_out2_snapshot = item.out2
        item.save(update_fields=[
            "code_snapshot", "label_snapshot", "system_role_snapshot",
            "work_credit_snapshot", "paid_credit_snapshot", "bonus_credit_snapshot",
            "registered_hours_snapshot", "meal_allowance_count_snapshot", "is_work_snapshot",
            "registered_in1_snapshot", "registered_out1_snapshot", "registered_in2_snapshot", "registered_out2_snapshot",
        ])


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0008_attendancecode_default_in1_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancecode",
            name="work_credit",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6, validators=[MinValueValidator(Decimal("0"))], verbose_name="Công làm"),
        ),
        migrations.AddField(
            model_name="attendancecode",
            name="paid_credit",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6, validators=[MinValueValidator(Decimal("0"))], verbose_name="Công hưởng lương"),
        ),
        migrations.AddField(
            model_name="attendancecode",
            name="bonus_credit",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6, validators=[MinValueValidator(Decimal("0"))], verbose_name="Công nhận thưởng"),
        ),
        migrations.AddField(
            model_name="attendancecode",
            name="registered_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6, validators=[MinValueValidator(Decimal("0"))], verbose_name="Giờ đăng ký"),
        ),
        migrations.AddField(
            model_name="attendancecode",
            name="meal_allowance_count",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6, validators=[MinValueValidator(Decimal("0"))], verbose_name="Số suất cơm ca"),
        ),
        migrations.AddField(
            model_name="attendancecode",
            name="is_system",
            field=models.BooleanField(default=False, verbose_name="Mã hệ thống"),
        ),
        migrations.AddField(
            model_name="attendancecode",
            name="system_role",
            field=models.CharField(default="OTHER", max_length=32, verbose_name="Vai trò hệ thống"),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="code_snapshot",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="label_snapshot",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="system_role_snapshot",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="work_credit_snapshot",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="paid_credit_snapshot",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="bonus_credit_snapshot",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="registered_hours_snapshot",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="meal_allowance_count_snapshot",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="is_work_snapshot",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="registered_in1_snapshot",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="registered_out1_snapshot",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="registered_in2_snapshot",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attendancecommititem",
            name="registered_out2_snapshot",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.RunPython(seed_attendance_codes, migrations.RunPython.noop),
        migrations.RunPython(backfill_commit_snapshots, migrations.RunPython.noop),
    ]
