"""
HR service layer: quyền truy cập đơn vị, đồng bộ policy group cho user theo nhân sự,
và các tiện ích hỗ trợ phân quyền.

Không import trực tiếp model từ app khác khi module load để tránh vòng import.
Dùng apps.get_model để lấy model khi cần.
"""

from typing import List, Set
from functools import lru_cache
from django.apps import apps
from django.contrib.auth.models import Group
from django.db import transaction

from apps.audit.utils import audit_log


# === Constants nhóm quyền chính sách ===
# Nhóm mới dùng cho vận hành.
GROUP_DIRECTOR = "DIRECTOR"
GROUP_UNIT_COMMANDER = "UNIT_COMMANDER"
GROUP_EMPLOYEE = "EMPLOYEE"
GROUP_UNIT_STATISTICIAN = "UNIT_STATISTICIAN"
GROUP_HR_MANAGER = "HR_MANAGER"
GROUP_ATTENDANCE_DEVICE_OPERATOR = "ATTENDANCE_DEVICE_OPERATOR"
GROUP_SYSTEM_ADMIN = "SYSTEM_ADMIN"

# Nhóm cũ giữ tương thích dữ liệu/code cũ. Không khuyến nghị gán mới thủ công.
GROUP_SUPERADMIN = "SUPERADMIN"
GROUP_BACKOFFICE_MANAGER = "BACKOFFICE_MANAGER"
GROUP_BACKOFFICE_STAFF = "BACKOFFICE_STAFF"
GROUP_HR_ADMIN = "HR_ADMIN"
GROUP_EMPLOYEE_VIEWER = "EMPLOYEE_VIEWER"

LEADERSHIP_TITLES: Set[str] = {
    "Giám Đốc", "Chủ Tịch", "Phó Giám đốc"
}
MANAGER_TITLES: Set[str] = {
    "Trưởng Phòng", "Phó Trưởng Phòng", "Trưởng Ban", "Phó Ban",
    "Trưởng Phân xưởng", "Phó Phân xưởng"
}


def ensure_groups_exist():
    """Đảm bảo các group policy tồn tại."""
    for name in [
        GROUP_EMPLOYEE,
        GROUP_UNIT_STATISTICIAN,
        GROUP_UNIT_COMMANDER,
        GROUP_DIRECTOR,
        GROUP_HR_MANAGER,
        GROUP_ATTENDANCE_DEVICE_OPERATOR,
        GROUP_SYSTEM_ADMIN,
        # legacy aliases
        GROUP_SUPERADMIN,
        GROUP_BACKOFFICE_MANAGER,
        GROUP_BACKOFFICE_STAFF,
        GROUP_HR_ADMIN,
        GROUP_EMPLOYEE_VIEWER,
    ]:
        Group.objects.get_or_create(name=name)


@lru_cache(maxsize=1024)
def _all_orgunit_ids() -> List[int]:
    OrgUnit = apps.get_model('organization', 'OrgUnit')
    return list(OrgUnit.objects.values_list('id', flat=True))


@lru_cache(maxsize=1024)
def _subtree_ids(root_id: int) -> List[int]:
    """
    Cache toàn bộ cây con của một OrgUnit root (bao gồm root).
    Dùng BFS đơn giản.
    """
    OrgUnit = apps.get_model('organization', 'OrgUnit')
    root = OrgUnit.objects.filter(pk=root_id).first()
    if not root:
        return []
    ids = [root.id]
    queue = [root]
    while queue:
        parent = queue.pop()
        children = list(parent.children.filter(is_active=True))
        for c in children:
            ids.append(c.id)
            queue.append(c)
    return ids


def clear_org_scope_cache():
    """
    Xóa cache phạm vi đơn vị sau khi cơ cấu tổ chức thay đổi.

    Lý do: allowed_org_ids_for_user() dùng cache để giảm truy vấn. Nếu vừa tạo/sửa/xóa
    OrgUnit trong cùng tiến trình web rồi import nhân sự ngay, cache cũ có thể chưa chứa
    đơn vị mới, kể cả với superuser.
    """
    _all_orgunit_ids.cache_clear()
    _subtree_ids.cache_clear()


def allowed_org_ids_for_user(user) -> List[int]:
    """
    Tính danh sách OrgUnit IDs user được phép xem dựa vào AccessControl.
    SUPERUSER → tất cả.
    Không có access_control → [].
    Scope:
      - ALL_ORG: tất cả
      - PLANT_SUBTREE / UNIT_SUBTREE: toàn bộ cây con của root_org_unit
    """
    if user.is_superuser:
        return _all_orgunit_ids()

    AccessControl = apps.get_model('hr', 'AccessControl')
    ac = getattr(user, 'access_control', None)
    if not ac:
        try:
            ac = AccessControl.objects.select_related('root_org_unit').get(user=user)
        except AccessControl.DoesNotExist:
            return []

    if ac.scope == AccessControl.Scope.ALL_ORG:
        return _all_orgunit_ids()
    if ac.root_org_unit_id is None:
        return []

    root = ac.root_org_unit
    if ac.scope == AccessControl.Scope.PLANT_SUBTREE:
        root = _get_plant_ancestor(root)

    if not root:
        return []
    return _subtree_ids(root.id)


def _get_plant_ancestor(unit):
    """
    Tìm ancestor có type=PLANT. Nếu không thấy trả về unit hiện tại.
    """
    OrgUnit = apps.get_model('organization', 'OrgUnit')
    p = unit
    while p and p.type != OrgUnit.Type.PLANT:
        p = p.parent
    return p or unit


@transaction.atomic
def sync_user_policy_for_employee(emp, request=None):
    """
    Đồng bộ Group và AccessControl cho user của employee theo job_title và đơn vị.
    Chính sách:
      - Leadership titles -> scope PLANT_SUBTREE + group DIRECTOR
      - Manager titles -> scope UNIT_SUBTREE + group UNIT_COMMANDER
      - Khác -> scope UNIT_SUBTREE + group EMPLOYEE
    Giữ group nghiệp vụ gán tay (VD UNIT_STATISTICIAN/HR_MANAGER) không xóa.
    """
    ensure_groups_exist()

    user = emp.user
    if not user:
        return

    AccessControl = apps.get_model('hr', 'AccessControl')

    title_name = (emp.job_title.name if getattr(emp, 'job_title', None) else "") or ""
    scope = AccessControl.Scope.UNIT_SUBTREE
    target_group_name = GROUP_EMPLOYEE

    if title_name in LEADERSHIP_TITLES:
        scope = AccessControl.Scope.PLANT_SUBTREE
        target_group_name = GROUP_DIRECTOR
    elif title_name in MANAGER_TITLES:
        scope = AccessControl.Scope.UNIT_SUBTREE
        target_group_name = GROUP_UNIT_COMMANDER
    else:
        target_group_name = GROUP_EMPLOYEE

    root_unit = emp.unit
    if scope == AccessControl.Scope.PLANT_SUBTREE:
        root_unit = _get_plant_ancestor(root_unit)

    ac, _created = AccessControl.objects.update_or_create(
        user=user,
        defaults={'root_org_unit': root_unit, 'scope': scope}
    )

    audit_actor = request.user if request and hasattr(request, 'user') else None
    audit_log(
        action_verb="UPDATE",
        object_type="accesscontrol",
        object_id=ac.id,
        object_repr=f"{user.username}->{root_unit.symbol}",
        actor=audit_actor,
        changes={"scope": scope, "root": root_unit.symbol},
        request=request,
        action_code="ACCESSCONTROL_UPDATE",
    )

    # Chỉ xóa các group policy tự động theo chức danh. Không xóa các group nghiệp vụ
    # được gán tay như UNIT_STATISTICIAN, HR_MANAGER, ATTENDANCE_DEVICE_OPERATOR.
    policy_groups = {
        GROUP_DIRECTOR,
        GROUP_UNIT_COMMANDER,
        GROUP_EMPLOYEE,
        # legacy policy aliases
        GROUP_SUPERADMIN,
        GROUP_BACKOFFICE_MANAGER,
        GROUP_BACKOFFICE_STAFF,
        GROUP_EMPLOYEE_VIEWER,
    }
    current_groups = set(user.groups.values_list('name', flat=True))
    remove_these = current_groups & policy_groups
    for gname in remove_these:
        user.groups.remove(Group.objects.get(name=gname))
    user.groups.add(Group.objects.get(name=target_group_name))

    audit_log(
        action_verb="UPDATE",
        object_type="employee",
        object_id=emp.id,
        object_repr=emp.full_name,
        actor=audit_actor,
        extra={"policy_group": target_group_name, "scope": scope, "root": root_unit.symbol},
        request=request,
        action_code="ROLEPOLICY_SYNC",
    )