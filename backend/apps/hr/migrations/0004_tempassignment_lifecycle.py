# Generated for Phase 3D - TempAssignment lifecycle for attendance roster

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0003_employee_skip_device_attendance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="tempassignment",
            name="planned_end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tempassignment",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tempassignment",
            name="completed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="tempassignment",
            name="completed_note",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tempassignment",
            name="last_impact_scan_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tempassignment",
            name="last_impact_summary",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="tempassignment",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Đang điều động"),
                    ("COMPLETED", "Đã hoàn thành"),
                    ("EXPIRED", "Hết hạn"),
                    ("CANCELLED", "Đã hủy"),
                ],
                default="ACTIVE",
                max_length=16,
            ),
        ),
        migrations.AddIndex(
            model_name="tempassignment",
            index=models.Index(fields=["from_unit", "start_date"], name="hr_tempassi_from_un_5f4c8a_idx"),
        ),
        migrations.AddIndex(
            model_name="tempassignment",
            index=models.Index(fields=["start_date", "end_date"], name="hr_tempassi_start_d_9f6e42_idx"),
        ),
    ]
