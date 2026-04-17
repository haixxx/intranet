from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from apps.attendance_devices_v2.services_normalize import normalize_raw_punches


class Command(BaseCommand):
    help = "Chuẩn hoá RawPunch (v2) -> NormalizedPunch (v2) theo Employee.card_id và dedupe window."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000, help="Số raw punches xử lý mỗi lần.")
        parser.add_argument("--since-id", type=int, default=None, help="Chỉ xử lý raw punch có id > since-id.")

    def handle(self, *args, **options):
        limit = options["limit"]
        since_id = options.get("since_id")

        res = normalize_raw_punches(limit=limit, since_id=since_id)

        self.stdout.write(self.style.SUCCESS(
            f"OK normalize v2: scanned={res.scanned}, resolved={res.resolved}, "
            f"unresolved={res.unresolved}, created_norm={res.created_norm}, merged={res.merged_into_existing}"
        ))