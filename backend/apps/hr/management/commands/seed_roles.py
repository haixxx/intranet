from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Tương thích cũ: gọi seed_backoffice_groups để tạo/cập nhật nhóm quyền chuẩn."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Chỉ in thay đổi dự kiến, không ghi database.")
        parser.add_argument("--keep-extra", action="store_true", help="Giữ lại các quyền đã gán thủ công ngoài ma trận chuẩn.")
        parser.add_argument("--skip-legacy", action="store_true", help="Không tạo/cập nhật các nhóm tương thích cũ.")

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            "seed_roles là command cũ. Đang chuyển sang seed_backoffice_groups."
        ))
        call_command(
            "seed_backoffice_groups",
            dry_run=options.get("dry_run", False),
            keep_extra=options.get("keep_extra", False),
            skip_legacy=options.get("skip_legacy", False),
        )
