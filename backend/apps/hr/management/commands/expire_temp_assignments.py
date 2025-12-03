from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.hr.services.cron import expire_due_temp_assignments


class Command(BaseCommand):
    help = "Tự động chuyển các điều động tạm thời đã quá hạn sang EXPIRED."

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help="Chạy giả lập theo ngày định dạng YYYY-MM-DD (dùng cho test)."
        )
        parser.add_argument(
            '--silent',
            action='store_true',
            help="Không in chi tiết từng bản ghi."
        )

    def handle(self, *args, **options):
        run_date = None
        if options.get('date'):
            from datetime import date
            try:
                year, month, day = map(int, options['date'].split('-'))
                run_date = date(year, month, day)
            except Exception:
                self.stderr.write(self.style.ERROR("Ngày không đúng định dạng YYYY-MM-DD. Bỏ qua."))

        stats = expire_due_temp_assignments(run_date=run_date)
        date_str = stats['date'].isoformat()

        msg = (
            f"[expire_temp_assignments] Ngày chạy: {date_str} | "
            f"Kiểm tra: {stats['checked']} | "
            f"Chuyển EXPIRED: {stats['expired']} | "
            f"Bỏ qua: {stats['skipped']}"
        )
        self.stdout.write(self.style.SUCCESS(msg))

        if not options.get('silent'):
            if stats['expired'] == 0:
                self.stdout.write("Không có điều động nào cần chuyển trạng thái.")
            else:
                self.stdout.write("Đã ghi audit logs cho các điều động chuyển trạng thái.")