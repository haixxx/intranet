from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

GROUPS = [
    "SUPERADMIN",
    "BACKOFFICE_MANAGER",
    "BACKOFFICE_STAFF",
    "HR_ADMIN",
    "EMPLOYEE_VIEWER",
]

class Command(BaseCommand):
    help = "Tạo các nhóm quyền mặc định và gán quyền cơ bản."

    def handle(self, *args, **options):
        for g in GROUPS:
            Group.objects.get_or_create(name=g)

        # Gán quyền cơ bản (tối thiểu) cho HR_ADMIN: quản lý nhân sự, cơ cấu, chức vụ, ca làm việc
        from apps.hr.models import Employee
        from apps.organization.models import OrgUnit, JobTitle, ShiftTemplate

        def grant(group_name, perms):
            grp = Group.objects.get(name=group_name)
            for model in perms:
                ct = ContentType.objects.get_for_model(model)
                for codename in ["view", "add", "change", "delete"]:
                    perm = Permission.objects.get(content_type=ct, codename=f"{codename}_{ct.model}")
                    grp.permissions.add(perm)

        grant("HR_ADMIN", [Employee, OrgUnit, JobTitle, ShiftTemplate])

        # EMPLOYEE_VIEWER: chỉ view Employee
        viewer = Group.objects.get(name="EMPLOYEE_VIEWER")
        ct_emp = ContentType.objects.get_for_model(Employee)
        viewer.permissions.add(Permission.objects.get(content_type=ct_emp, codename=f"view_{ct_emp.model}"))

        self.stdout.write(self.style.SUCCESS("Đã tạo nhóm và gán quyền cơ bản."))