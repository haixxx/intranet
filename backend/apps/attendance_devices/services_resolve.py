from typing import Optional
from django.db import transaction

from apps.hr.models import Employee
from .models import AttendanceRawEvent, AttendanceDeviceUserMap


def resolve_employee_for_raw_event(ev: AttendanceRawEvent) -> Optional[int]:
    """
    Chính sách resolve:
    1) Ưu tiên: HR.card_id == ev.device_user_id
    2) Fallback: AttendanceDeviceUserMap active cho (device, device_user_id)
    """
    # Ưu tiên card_id
    emp = Employee.objects.filter(card_id=ev.device_user_id).only("id").first()
    if emp:
        return emp.id

    # Fallback: mapping theo thiết bị
    mp = AttendanceDeviceUserMap.objects.filter(
        device=ev.device, device_user_id=ev.device_user_id, is_active=True
    ).select_related("employee").first()
    if mp and mp.employee_id:
        return mp.employee_id

    return None


def resolve_batch(limit: int = 1000) -> int:
    """
    Gán employee_id cho các AttendanceRawEvent chưa resolve theo chính sách ở trên.
    Trả về số lượng bản ghi đã cập nhật.
    """
    updated = 0
    qs = AttendanceRawEvent.objects.filter(employee__isnull=True).order_by("id")[:limit]
    with transaction.atomic():
        for ev in qs:
            emp_id = resolve_employee_for_raw_event(ev)
            if emp_id:
                ev.employee_id = emp_id
                ev.save(update_fields=["employee_id"])
                updated += 1
    return updated