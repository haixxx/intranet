from __future__ import annotations

from typing import Iterable, List, Sequence

from django.db.models import QuerySet

from apps.hr.services import allowed_org_ids_for_user
from apps.organization.models import OrgUnit


def allowed_org_unit_ids(user) -> List[int]:
    """
    Phạm vi đơn vị user được xem theo AccessControl.

    Nguyên tắc chuẩn:
    - superuser: toàn bộ cây tổ chức.
    - user có AccessControl: theo scope/root_org_unit.
    - user không có AccessControl: không có phạm vi dữ liệu.

    Group/Permission quyết định user được làm gì; AccessControl quyết định user
    được xem dữ liệu đơn vị nào.
    """
    return list(allowed_org_ids_for_user(user))


def get_allowed_org_units(user, *, active_only: bool = True) -> QuerySet:
    ids = allowed_org_unit_ids(user)
    qs = OrgUnit.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    if not ids:
        return qs.none()
    return qs.filter(id__in=ids).order_by("symbol")


def get_allowed_attendance_units(user) -> QuerySet:
    ids = allowed_org_unit_ids(user)
    qs = OrgUnit.objects.filter(is_attendance_unit=True, is_active=True)
    if not ids:
        return qs.none()
    return qs.filter(id__in=ids).order_by("symbol")


def get_allowed_attendance_unit_ids(user) -> List[int]:
    return list(get_allowed_attendance_units(user).values_list("id", flat=True))


def unit_in_attendance_scope(user, unit_id) -> bool:
    try:
        uid = int(unit_id)
    except Exception:
        return False
    return uid in set(get_allowed_attendance_unit_ids(user))


def resolve_attendance_unit_scope(user, selected_unit_id: int | None = None):
    allowed_units = list(get_allowed_attendance_units(user))
    allowed_ids = {u.id for u in allowed_units}
    selected = selected_unit_id if selected_unit_id in allowed_ids else None
    units = [u for u in allowed_units if selected in (None, u.id)]
    return allowed_units, selected, units, [u.id for u in units]


def filter_queryset_by_unit_scope(qs, user, *, unit_field: str = "unit_id"):
    """
    Lọc queryset theo phạm vi đơn vị.

    `unit_field` là tên field id đơn vị trong model/queryset, ví dụ:
    - unit_id
    - employee__unit_id
    - org_unit_id
    - batch__unit_id
    - commit__unit_id
    """
    ids = allowed_org_unit_ids(user)
    if not ids:
        return qs.none()
    return qs.filter(**{f"{unit_field}__in": ids})
