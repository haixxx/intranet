from __future__ import annotations

from copy import deepcopy

from django.core.management.base import BaseCommand

from ...models import AttendanceDeviceV2
from ...sync_policy import normalize_sync_policy


class Command(BaseCommand):
    help = (
        "Chuẩn hóa sync_policy thiết bị sang policy v3: thêm morning-check 07:30, "
        "midday-check 13:20 và giữ tùy chỉnh nightly hiện có. Mặc định dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Ghi thay đổi vào database. Nếu không có cờ này, command chỉ dry-run.",
        )
        parser.add_argument(
            "--device-id",
            type=int,
            default=None,
            help="Chỉ xử lý một thiết bị cụ thể.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        device_id = options.get("device_id")

        queryset = AttendanceDeviceV2.objects.all().order_by("id")
        if device_id:
            queryset = queryset.filter(id=device_id)

        scanned = 0
        changed = 0

        for device in queryset.iterator():
            scanned += 1
            original_profile = device.sdk_profile if isinstance(device.sdk_profile, dict) else {}
            original_policy = original_profile.get("sync_policy")
            normalized = normalize_sync_policy(original_policy)

            if isinstance(original_policy, dict) and original_policy == normalized:
                self.stdout.write(
                    self.style.SUCCESS(f"[OK] Device #{device.id} {device.name}: policy đã chuẩn.")
                )
                continue

            changed += 1
            windows = ", ".join(
                f"{item['name']}={item['time']}/{item['days']}d/{item['run_mode']}"
                for item in normalized["backfill_windows"]
            )
            prefix = "[APPLY]" if apply_changes else "[DRY-RUN]"
            self.stdout.write(f"{prefix} Device #{device.id} {device.name}: {windows}")

            if apply_changes:
                updated_profile = deepcopy(original_profile)
                updated_profile["sync_policy"] = normalized
                device.sdk_profile = updated_profile
                device.save(update_fields=["sdk_profile", "updated_at"])

        mode = "ĐÃ GHI" if apply_changes else "DRY-RUN"
        self.stdout.write(
            self.style.SUCCESS(
                f"Hoàn tất ({mode}). Đã kiểm tra {scanned} thiết bị, cần thay đổi {changed} thiết bị."
            )
        )
