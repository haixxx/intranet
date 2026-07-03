from django.core.management.base import BaseCommand

from apps.approvals.rolemap_health import build_role_mapping_diagnostics


class Command(BaseCommand):
    help = "Kiểm tra cấu hình Role Mapping dùng cho bước Lãnh đạo đơn vị."

    def handle(self, *args, **options):
        report = build_role_mapping_diagnostics()
        self.stdout.write(f"Active mappings: {report['active_count']} / Total: {report['total_count']}")
        self.stdout.write(f"Counts by role: {report['counts_by_role']}")
        if not report["issues"]:
            self.stdout.write(self.style.SUCCESS("Không phát hiện cảnh báo lớn trong Role Mapping."))
            return

        for issue in report["issues"]:
            severity = issue.get("severity", "info").upper()
            line = f"[{severity}] {issue.get('title')}: {issue.get('message')}"
            if issue.get("severity") == "danger":
                self.stdout.write(self.style.ERROR(line))
            elif issue.get("severity") == "warning":
                self.stdout.write(self.style.WARNING(line))
            else:
                self.stdout.write(line)
