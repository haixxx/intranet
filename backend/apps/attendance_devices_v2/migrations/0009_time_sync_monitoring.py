from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("attendance_devices_v2", "0008_agent_v2_reports"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="agent_config_version",
            field=models.CharField(blank=True, default="", max_length=128, verbose_name="Phiên bản cấu hình Agent đã nhận"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="device_time_at_check",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Giờ thiết bị khi kiểm tra"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="last_time_check_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Kiểm tra giờ gần nhất"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="last_time_sync_after_drift_seconds",
            field=models.IntegerField(blank=True, null=True, verbose_name="Độ lệch sau đồng bộ (giây)"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="last_time_sync_attempt_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Lần thử đồng bộ giờ gần nhất"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="last_time_sync_before_drift_seconds",
            field=models.IntegerField(blank=True, null=True, verbose_name="Độ lệch trước đồng bộ (giây)"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="last_time_sync_error",
            field=models.TextField(blank=True, default="", verbose_name="Lỗi đồng bộ giờ gần nhất"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="last_time_sync_status",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="Kết quả đồng bộ giờ gần nhất"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="last_time_sync_success_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Đồng bộ giờ thành công gần nhất"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="time_sync_enabled",
            field=models.BooleanField(default=False, verbose_name="Bật đồng bộ giờ"),
        ),
        migrations.AddField(
            model_name="attendancedevicestatusreportv2",
            name="time_sync_state",
            field=models.CharField(choices=[("DISABLED", "Đã tắt"), ("NOT_CHECKED", "Chưa kiểm tra"), ("CHECKING", "Đang kiểm tra"), ("NORMAL", "Bình thường"), ("WARNING", "Cảnh báo"), ("SYNC_REQUIRED", "Cần đồng bộ"), ("WAITING_WINDOW", "Chờ cửa sổ"), ("SYNCING", "Đang đồng bộ"), ("SUCCESS", "Thành công"), ("FAILED", "Thất bại"), ("FAILED_VERIFY", "Xác minh thất bại"), ("DEVICE_UNREACHABLE", "Không đọc được giờ"), ("SKIPPED_ALREADY_SUCCESS", "Đã đồng bộ trong cửa sổ"), ("SKIPPED_CANNOT_PAUSE", "Không dừng được realtime")], db_index=True, default="NOT_CHECKED", max_length=32, verbose_name="Trạng thái đồng bộ giờ"),
        ),
        migrations.CreateModel(
            name="AttendanceDeviceTimeSyncReportV2",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("run_id", models.CharField(blank=True, db_index=True, default="", max_length=160, verbose_name="Run ID")),
                ("window_key", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="Cửa sổ")),
                ("attempt_no", models.PositiveIntegerField(default=1, verbose_name="Lần thử")),
                ("status", models.CharField(choices=[("SUCCESS", "Thành công"), ("FAILED", "Thất bại"), ("FAILED_VERIFY", "Xác minh thất bại"), ("SKIPPED_CANNOT_PAUSE", "Không dừng được realtime")], db_index=True, default="FAILED", max_length=32, verbose_name="Trạng thái")),
                ("started_at", models.DateTimeField(blank=True, null=True, verbose_name="Bắt đầu")),
                ("finished_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Kết thúc")),
                ("agent_time_before", models.DateTimeField(blank=True, null=True, verbose_name="Giờ Agent trước sync")),
                ("device_time_before", models.DateTimeField(blank=True, null=True, verbose_name="Giờ thiết bị trước sync")),
                ("agent_time_after", models.DateTimeField(blank=True, null=True, verbose_name="Giờ Agent sau sync")),
                ("device_time_after", models.DateTimeField(blank=True, null=True, verbose_name="Giờ thiết bị sau sync")),
                ("before_drift_seconds", models.IntegerField(blank=True, null=True, verbose_name="Độ lệch trước sync (giây)")),
                ("after_drift_seconds", models.IntegerField(blank=True, null=True, verbose_name="Độ lệch sau sync (giây)")),
                ("error_code", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="Mã lỗi")),
                ("error_message", models.TextField(blank=True, default="", verbose_name="Thông báo lỗi")),
                ("payload_json", models.JSONField(blank=True, null=True, verbose_name="Payload gốc")),
                ("reported_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name="Server nhận lúc")),
                ("agent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="time_sync_reports_v2", to="attendance_devices_v2.attendancedeviceagentv2", verbose_name="Agent")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="time_sync_reports_v2", to="attendance_devices_v2.attendancedevicev2", verbose_name="Thiết bị")),
            ],
            options={
                "verbose_name": "Báo cáo đồng bộ giờ thiết bị (v2)",
                "verbose_name_plural": "Báo cáo đồng bộ giờ thiết bị (v2)",
            },
        ),
        migrations.AddIndex(
            model_name="attendancedevicestatusreportv2",
            index=models.Index(fields=["time_sync_state", "reported_at"], name="adv2_st_tsync_time_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicetimesyncreportv2",
            index=models.Index(fields=["device", "-reported_at", "-id"], name="adv2_ts_dev_latest_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicetimesyncreportv2",
            index=models.Index(fields=["agent", "-reported_at"], name="adv2_ts_agent_time_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicetimesyncreportv2",
            index=models.Index(fields=["status", "reported_at"], name="adv2_ts_status_time_idx"),
        ),
    ]
