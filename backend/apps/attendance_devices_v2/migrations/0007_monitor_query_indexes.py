from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance_devices_v2", "0006_attendancemanualpunch_and_more"),
    ]

    operations = [
        # Tối ưu màn Giám sát thiết bị: đếm raw pending theo device + normalized_at.
        migrations.AddIndex(
            model_name="attendancerawpunchv2",
            index=models.Index(fields=["device", "normalized_at"], name="adv2_raw_dev_norm_idx"),
        ),
        # Dự phòng các màn lọc theo giờ local; monitor bản mới dùng UTC nhưng một số view khác có thể vẫn dùng local.
        migrations.AddIndex(
            model_name="attendancerawpunchv2",
            index=models.Index(fields=["device", "event_time_local"], name="adv2_raw_dev_local_idx"),
        ),
        # Tối ưu đếm normalized punch theo thiết bị/ngày.
        migrations.AddIndex(
            model_name="attendancenormalizedpunchv2",
            index=models.Index(fields=["best_device", "canonical_time_utc"], name="adv2_norm_dev_time_idx"),
        ),
        # Tối ưu lấy ingest log mới nhất theo thiết bị.
        migrations.AddIndex(
            model_name="attendanceingestlogv2",
            index=models.Index(fields=["device", "-started_at", "-id"], name="adv2_ing_dev_latest_idx"),
        ),
    ]
