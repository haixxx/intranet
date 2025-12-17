from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from apps.approvals.services import seed_attendance_correction_flow

User = get_user_model()


class Command(BaseCommand):
    help = "Seed Approval Flow cho 'Phê duyệt sửa chấm công' (attendance_correction_approval)."

    def add_arguments(self, parser):
        parser.add_argument("--admin_unit_id", type=int, required=True, help="ID đơn vị quản trị lãnh đạo (để tham chiếu chung cho flow).")
        parser.add_argument("--hr_user_id", type=int, required=True, help="User ID của HR ký đích danh ở bước 2.")
        parser.add_argument("--actor_user_id", type=int, required=False, help="User ID thực hiện seed (mặc định lấy superuser đầu tiên).")

    def handle(self, *args, **options):
        admin_unit_id = options["admin_unit_id"]
        hr_user_id = options["hr_user_id"]
        actor_user_id = options.get("actor_user_id")

        if actor_user_id:
            actor = User.objects.filter(id=actor_user_id).first()
        else:
            actor = User.objects.filter(is_superuser=True).first() or User.objects.order_by("id").first()

        if not actor:
            raise CommandError("Không tìm thấy actor user để seed flow.")

        res = seed_attendance_correction_flow(admin_unit_id=admin_unit_id, hr_user_id=hr_user_id, actor=actor)
        self.stdout.write(self.style.SUCCESS(f"Seed OK: flow={res.flow.flow_key}, version={res.version.version}"))