"""
Service tính đơn vị hiệu lực (effective unit) dựa trên điều động tạm thời.
"""

from datetime import date
from functools import lru_cache
from django.db.models import Q

from apps.hr.models import Employee, TempAssignment


@lru_cache(maxsize=4096)
def effective_unit_for(employee_id: int, on_date: date) -> tuple[int, str]:
    """
    Trả về (unit_id, source='TEMP' | 'PRIMARY') cho employee_id tại ngày on_date.
    Lấy điều động ACTIVE hợp lệ mới nhất (theo start_date).
    """
    qs = TempAssignment.objects.filter(
        employee_id=employee_id,
        status=TempAssignment.Status.ACTIVE,
        start_date__lte=on_date
    ).filter(
        Q(end_date__gte=on_date) | Q(end_date__isnull=True)
    ).order_by("-start_date", "-id")

    assign = qs.first()
    if assign and assign.apply_flag:
        return assign.to_unit_id, "TEMP"

    unit_id = Employee.objects.only("unit_id").get(pk=employee_id).unit_id
    return unit_id, "PRIMARY"


def employee_ids_effective_in_units(unit_ids: list[int], on_date: date) -> set[int]:
    """
    Tập id nhân sự có effective unit thuộc unit_ids tại ngày on_date.
    - Primary: unit_id ∈ unit_ids
    - TempAssignment: to_unit_id ∈ unit_ids & đang hiệu lực & apply_flag=true
    """
    primary_ids = set(Employee.objects.filter(
        unit_id__in=unit_ids,
        status=Employee.Status.ACTIVE
    ).values_list("id", flat=True))

    temp_ids = set(TempAssignment.objects.filter(
        status=TempAssignment.Status.ACTIVE,
        to_unit_id__in=unit_ids,
        apply_flag=True,
        start_date__lte=on_date
    ).filter(
        Q(end_date__gte=on_date) | Q(end_date__isnull=True)
    ).values_list("employee_id", flat=True))

    return primary_ids | temp_ids