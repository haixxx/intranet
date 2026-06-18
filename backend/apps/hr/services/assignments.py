"""
Service tính đơn vị hiệu lực (effective unit) dựa trên điều động tạm thời.

Nguyên tắc cho chấm công:
- Employee.unit luôn là đơn vị gốc.
- TempAssignment quyết định đơn vị hiệu lực theo từng ngày.
- Trạng thái ACTIVE/COMPLETED/EXPIRED vẫn có hiệu lực lịch sử trong khoảng start_date/end_date.
- CANCELLED không có hiệu lực.
"""

from datetime import date

from django.db.models import Q

from apps.hr.models import Employee, TempAssignment


def effective_assignment_qs(on_date: date):
    """
    QuerySet các điều động có hiệu lực tại ngày on_date.
    """
    return (
        TempAssignment.objects.filter(
            status__in=TempAssignment.effective_statuses(),
            apply_flag=True,
            start_date__lte=on_date,
        )
        .filter(Q(end_date__gte=on_date) | Q(end_date__isnull=True))
    )


def effective_assignment_for(employee_id: int, on_date: date) -> TempAssignment | None:
    """
    Lấy phiếu điều động có hiệu lực cho một nhân sự tại ngày on_date.
    Do model đã chặn chồng chéo, thông thường chỉ có tối đa một phiếu.
    """
    return (
        effective_assignment_qs(on_date)
        .filter(employee_id=employee_id)
        .select_related("from_unit", "to_unit")
        .order_by("-start_date", "-id")
        .first()
    )


def effective_unit_for(employee_id: int, on_date: date) -> tuple[int, str]:
    """
    Trả về (unit_id, source='TEMP' | 'PRIMARY') cho employee_id tại ngày on_date.
    """
    assignment = effective_assignment_for(employee_id, on_date)
    if assignment:
        return assignment.to_unit_id, "TEMP"

    unit_id = Employee.objects.only("unit_id").get(pk=employee_id).unit_id
    return unit_id, "PRIMARY"


def employee_ids_effective_in_units(unit_ids: list[int] | set[int], on_date: date) -> set[int]:
    """
    Tập id nhân sự có effective unit thuộc unit_ids tại ngày on_date.

    Quy tắc chống đếm đôi:
    - Nhân sự đang có điều động hiệu lực không được tính ở đơn vị gốc.
    - Nhân sự đó chỉ tính ở to_unit nếu to_unit thuộc unit_ids.
    """
    unit_ids = set(unit_ids)

    active_assignments = effective_assignment_qs(on_date).values("employee_id", "to_unit_id")
    assigned_employee_ids = {row["employee_id"] for row in active_assignments}
    temp_ids = {row["employee_id"] for row in active_assignments if row["to_unit_id"] in unit_ids}

    primary_ids = set(
        Employee.objects.filter(
            unit_id__in=unit_ids,
            status=Employee.Status.ACTIVE,
        )
        .exclude(id__in=assigned_employee_ids)
        .values_list("id", flat=True)
    )

    return primary_ids | temp_ids
