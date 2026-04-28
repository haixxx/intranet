from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

# Employee
class Employee(models.Model):
    class WorkforceType(models.TextChoices):
        INDIRECT = 'INDIRECT', 'Gián tiếp'
        WORKER = 'WORKER', 'Người lao động'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Đang làm'
        INACTIVE = 'INACTIVE', 'Tạm ngưng'
        LEFT = 'LEFT', 'Đã nghỉ'

    employee_code = models.CharField(max_length=10, unique=True)
    full_name = models.CharField(max_length=150)
    workforce_type = models.CharField(max_length=16, choices=WorkforceType.choices, db_index=True)
    job_title = models.ForeignKey('organization.JobTitle', on_delete=models.PROTECT, related_name='employees', db_index=True)
    unit = models.ForeignKey('organization.OrgUnit', on_delete=models.PROTECT, related_name='unit_employees', db_index=True)
    team = models.ForeignKey('organization.OrgUnit', on_delete=models.PROTECT, related_name='team_employees', null=True, blank=True, db_index=True)
    card_id = models.CharField(max_length=32, unique=True)
    skip_device_attendance = models.BooleanField(default=False,db_index=True,help_text="Đặc cách: không yêu cầu đối chiếu chấm công máy (v2).")
    citizen_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    tax_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    bank_account = models.CharField(max_length=34, null=True, blank=True)
    bank_name = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    joined_date = models.DateField(null=True, blank=True)
    left_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    note = models.TextField(null=True, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['employee_code']
        indexes = [
            models.Index(fields=['unit']),
            models.Index(fields=['team']),
            models.Index(fields=['job_title']),
            models.Index(fields=['workforce_type']),
            models.Index(fields=['status']),
            models.Index(fields=['employee_code']),
            models.Index(fields=['card_id']),
            models.Index(fields=['citizen_id']),
            models.Index(fields=['tax_code']),
        ]

    def __str__(self):
        return f"{self.employee_code} - {self.full_name}"

    def clean(self):
        from django.apps import apps
        OrgUnit = apps.get_model('organization', 'OrgUnit')
        if self.unit and self.unit.type not in [OrgUnit.Type.DEPARTMENT, OrgUnit.Type.DIVISION, OrgUnit.Type.WORKSHOP]:
            raise ValidationError("Đơn vị (unit) phải là Phòng/Ban/Phân xưởng.")
        if self.team:
            if self.team.type != OrgUnit.Type.TEAM:
                raise ValidationError("Tổ (team) phải có loại TEAM.")
            parent = self.team.parent
            ok = False
            while parent:
                if parent.id == self.unit.id:
                    ok = True
                    break
                parent = parent.parent
            if not ok:
                raise ValidationError("Tổ phải thuộc cùng cây con của đơn vị.")

# AccessControl
class AccessControl(models.Model):
    class Scope(models.TextChoices):
        UNIT_SUBTREE = 'UNIT_SUBTREE', 'Đơn vị và tất cả tổ trực thuộc'
        PLANT_SUBTREE = 'PLANT_SUBTREE', 'Nhà máy và toàn bộ bên dưới'
        ALL_ORG = 'ALL_ORG', 'Toàn hệ thống'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='access_control')
    root_org_unit = models.ForeignKey('organization.OrgUnit', on_delete=models.PROTECT, related_name='access_controls')
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.UNIT_SUBTREE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['scope']),
        ]

    def __str__(self):
        return f"{self.user.username} -> {self.root_org_unit.symbol} ({self.scope})"

# Import TempAssignment (sau khi Employee định nghĩa)
from .temp_assignment import TempAssignment