from typing import List
from django.contrib.auth.models import Group
from django.db import transaction
from apps.audit.utils import audit_log
from apps.organization.models import OrgUnit, JobTitle
from .models import Employee, AccessControl

GROUP_SUPERADMIN = "SUPERADMIN"
GROUP_BACKOFFICE_MANAGER = "BACKOFFICE_MANAGER"
GROUP_BACKOFFICE_STAFF = "BACKOFFICE_STAFF"
GROUP_HR_ADMIN = "HR_ADMIN"
GROUP_EMPLOYEE_VIEWER = "EMPLOYEE_VIEWER"

LEADERSHIP_TITLES = {
    "Giám Đốc", "Chủ Tịch", "Phó Giám đốc"
}
MANAGER_TITLES = {
    "Trưởng Phòng", "Phó Trưởng Phòng", "Trưởng Ban", "Phó Ban", "Trưởng Phân xưởng", "Phó Phân xưởng"
}

def ensure_groups_exist():
    for name in [GROUP_SUPERADMIN, GROUP_BACKOFFICE_MANAGER, GROUP_BACKOFFICE_STAFF, GROUP_HR_ADMIN, GROUP_EMPLOYEE_VIEWER]:
        Group.objects.get_or_create(name=name)

def allowed_org_ids_for_user(user) -> List[int]:
    """
    Tính danh sách OrgUnit ids user được phép xem (theo AccessControl).
    """
    from apps.organization.utils import get_subtree_unit_ids
    if user.is_superuser:
        return list(OrgUnit.objects.values_list('id', flat=True))
    ac = getattr(user, 'access_control', None)
    if not ac:
        return []
    if ac.scope == AccessControl.Scope.ALL_ORG:
        return list(OrgUnit.objects.values_list('id', flat=True))
    if ac.scope == AccessControl.Scope.PLANT_SUBTREE:
        return get_subtree_unit_ids(ac.root_org_unit)
    if ac.scope == AccessControl.Scope.UNIT_SUBTREE:
        return get_subtree_unit_ids(ac.root_org_unit)
    return []

@transaction.atomic
def sync_user_policy_for_employee(emp: Employee, request=None):
    """
    Đồng bộ Group và AccessControl cho user của employee theo job_title và unit.
    - Lãnh đạo: PLANT_SUBTREE + SUPERADMIN
    - Quản lý cấp đơn vị: UNIT_SUBTREE + BACKOFFICE_MANAGER
    - Trợ lý/Nhân viên (INDIRECT): UNIT_SUBTREE + BACKOFFICE_STAFF
    - WORKER: không tạo user, không sync.
    - Nếu user đã có group khác ngoài bộ policy (ví dụ HR_ADMIN), giữ nguyên.
    - Nếu không tìm được group phù hợp, mặc định BACKOFFICE_STAFF (theo yêu cầu).
    """
    ensure_groups_exist()
    user = emp.user
    if not user:
        return

    # Determine scope and group by job title name
    title = (emp.job_title.name if emp.job_title_id else "") or ""
    scope = AccessControl.Scope.UNIT_SUBTREE
    target_group_name = GROUP_BACKOFFICE_STAFF

    if title in LEADERSHIP_TITLES:
        scope = AccessControl.Scope.PLANT_SUBTREE
        target_group_name = GROUP_SUPERADMIN
    elif title in MANAGER_TITLES:
        scope = AccessControl.Scope.UNIT_SUBTREE
        target_group_name = GROUP_BACKOFFICE_MANAGER
    else:
        # workforce_type INDIRECT -> staff; WORKER: typically no user, but fallback staff
        target_group_name = GROUP_BACKOFFICE_STAFF

    # Root unit:
    root = emp.unit
    if scope == AccessControl.Scope.PLANT_SUBTREE:
        # Find plant ancestor
        p = root
        while p and p.type != OrgUnit.Type.PLANT:
            p = p.parent
        root = p or root

    # Update AccessControl
    ac, created = AccessControl.objects.update_or_create(
        user=user,
        defaults={'root_org_unit': root, 'scope': scope}
    )
    audit_log(
        action_verb="UPDATE",
        object_type="accesscontrol",
        object_id=ac.id,
        object_repr=f"{user.username}->{root.symbol}",
        actor=request.user if request else None,
        changes={"scope": scope, "root": root.symbol},
        request=request,
        action_code="ACCESSCONTROL_UPDATE",
    )

    # Update Groups (override only policy groups; keep others like HR_ADMIN)
    policy_groups = {GROUP_SUPERADMIN, GROUP_BACKOFFICE_MANAGER, GROUP_BACKOFFICE_STAFF}
    current_groups = set(user.groups.values_list('name', flat=True))
    # Remove policy groups
    for g in (current_groups & policy_groups):
        user.groups.remove(Group.objects.get(name=g))
    # Add target policy group
    user.groups.add(Group.objects.get(name=target_group_name))

    audit_log(
        action_verb="UPDATE",
        object_type="employee",
        object_id=emp.id,
        object_repr=emp.full_name,
        actor=request.user if request else None,
        extra={"policy_group": target_group_name, "scope": scope, "root": root.symbol},
        request=request,
        action_code="ROLEPOLICY_SYNC",
    )