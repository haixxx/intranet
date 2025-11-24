from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission

ROLE_DEF = {
    # Toàn quyền
    "SUPERADMIN": {"all": True},

    # Quản trị người dùng cơ bản
    "ADMIN": {
        "permissions": [
            # User
            "view_user", "add_user", "change_user",
            # Group (Role)
            "view_group", "add_group", "change_group",
        ]
    },

    # Nhân sự (ví dụ): chỉ xem/sửa user, không đụng group
    "HR_ADMIN": {
        "permissions": ["view_user", "change_user"],
    },

    # Xem là chủ yếu
    "VIEWER": {
        "permissions": ["view_user", "view_group"],
    },
    # Có thể bổ sung ATTENDANCE_ADMIN, CANTEEN_ADMIN sau khi có models tương ứng
}


class Command(BaseCommand):
    help = "Tạo/cập nhật các Role (Group) và gán Permission mặc định."

    def handle(self, *args, **options):
        total_groups = 0
        for role_name, cfg in ROLE_DEF.items():
            group, _ = Group.objects.get_or_create(name=role_name)
            total_groups += 1

            if cfg.get("all"):
                perms = Permission.objects.all()
            else:
                codenames = set(cfg.get("permissions", []))
                perms = Permission.objects.filter(codename__in=codenames)

            group.permissions.set(perms)
            group.save()
            self.stdout.write(self.style.SUCCESS(
                f"Role {role_name}: {group.permissions.count()} permissions"
            ))

        self.stdout.write(self.style.SUCCESS(f"Done. Updated {total_groups} roles."))