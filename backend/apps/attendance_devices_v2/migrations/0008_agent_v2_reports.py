from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("attendance_devices_v2", "0007_monitor_query_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceDeviceStatusReportV2",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("realtime_status", models.CharField(choices=[("ONLINE", "Online"), ("OFFLINE", "Offline"), ("RECONNECTING", "Đang kết nối lại"), ("PAUSED_BACKFILL", "Tạm dừng để backfill"), ("PAUSED_TIME_SYNC", "Tạm dừng để đồng bộ giờ"), ("REALTIME_UNAVAILABLE", "Không hỗ trợ realtime"), ("ERROR", "Lỗi")], db_index=True, default="ONLINE", max_length=32, verbose_name="Trạng thái realtime")),
                ("last_realtime_at", models.DateTimeField(blank=True, null=True, verbose_name="Realtime cuối")),
                ("last_event_time_local", models.DateTimeField(blank=True, null=True, verbose_name="Event cuối trên máy")),
                ("last_device_seen_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Lần thấy máy")),
                ("pending_backfill_required", models.BooleanField(db_index=True, default=False, verbose_name="Cần backfill")),
                ("drift_seconds", models.IntegerField(blank=True, null=True, verbose_name="Lệch giờ máy (giây)")),
                ("last_error", models.TextField(blank=True, default="", verbose_name="Lỗi cuối")),
                ("payload_json", models.JSONField(blank=True, null=True, verbose_name="Payload gốc")),
                ("reported_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name="Server nhận lúc")),
                ("agent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="device_status_reports_v2", to="attendance_devices_v2.attendancedeviceagentv2", verbose_name="Agent")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_reports_v2", to="attendance_devices_v2.attendancedevicev2", verbose_name="Thiết bị")),
            ],
            options={
                "verbose_name": "Báo cáo trạng thái thiết bị (v2)",
                "verbose_name_plural": "Báo cáo trạng thái thiết bị (v2)",
            },
        ),
        migrations.CreateModel(
            name="AttendanceDeviceBackfillReportV2",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("window_name", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="Window")),
                ("status", models.CharField(choices=[("SUCCESS", "Thành công"), ("PARTIAL_PENDING", "Một phần đang pending"), ("FAILED", "Thất bại"), ("SKIPPED", "Bỏ qua")], db_index=True, default="SUCCESS", max_length=32, verbose_name="Trạng thái")),
                ("started_at", models.DateTimeField(blank=True, null=True, verbose_name="Bắt đầu")),
                ("finished_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Kết thúc")),
                ("duration_seconds", models.IntegerField(blank=True, null=True, verbose_name="Thời gian chạy (giây)")),
                ("days", models.PositiveIntegerField(default=0, verbose_name="Số ngày backfill")),
                ("from_local", models.DateTimeField(blank=True, null=True, verbose_name="Từ local")),
                ("to_local", models.DateTimeField(blank=True, null=True, verbose_name="Đến local")),
                ("read_total", models.PositiveIntegerField(default=0, verbose_name="Tổng log đọc")),
                ("filtered", models.PositiveIntegerField(default=0, verbose_name="Log sau lọc")),
                ("sent_batches", models.PositiveIntegerField(default=0, verbose_name="Batch đã gửi")),
                ("pending_batches", models.PositiveIntegerField(default=0, verbose_name="Batch pending")),
                ("processed", models.PositiveIntegerField(default=0, verbose_name="Server ghi")),
                ("duplicates", models.PositiveIntegerField(default=0, verbose_name="Trùng")),
                ("rejected", models.PositiveIntegerField(default=0, verbose_name="Bị loại")),
                ("errors", models.PositiveIntegerField(default=0, verbose_name="Số lỗi")),
                ("error_code", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="Mã lỗi")),
                ("error_message", models.TextField(blank=True, default="", verbose_name="Thông báo lỗi")),
                ("need_retry", models.BooleanField(db_index=True, default=False, verbose_name="Cần retry")),
                ("need_backfill", models.BooleanField(db_index=True, default=False, verbose_name="Cần backfill")),
                ("payload_json", models.JSONField(blank=True, null=True, verbose_name="Payload gốc")),
                ("reported_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name="Server nhận lúc")),
                ("agent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="backfill_reports_v2", to="attendance_devices_v2.attendancedeviceagentv2", verbose_name="Agent")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="backfill_reports_v2", to="attendance_devices_v2.attendancedevicev2", verbose_name="Thiết bị")),
            ],
            options={
                "verbose_name": "Báo cáo backfill thiết bị (v2)",
                "verbose_name_plural": "Báo cáo backfill thiết bị (v2)",
            },
        ),
        migrations.AddIndex(
            model_name="attendancedevicestatusreportv2",
            index=models.Index(fields=["device", "-reported_at", "-id"], name="adv2_st_dev_latest_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicestatusreportv2",
            index=models.Index(fields=["agent", "-reported_at"], name="adv2_st_agent_time_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicestatusreportv2",
            index=models.Index(fields=["realtime_status", "reported_at"], name="adv2_st_status_time_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicebackfillreportv2",
            index=models.Index(fields=["device", "-reported_at", "-id"], name="adv2_bf_dev_latest_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicebackfillreportv2",
            index=models.Index(fields=["agent", "-reported_at"], name="adv2_bf_agent_time_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicebackfillreportv2",
            index=models.Index(fields=["status", "reported_at"], name="adv2_bf_status_time_idx"),
        ),
        migrations.AddIndex(
            model_name="attendancedevicebackfillreportv2",
            index=models.Index(fields=["need_retry", "reported_at"], name="adv2_bf_retry_time_idx"),
        ),
    ]
