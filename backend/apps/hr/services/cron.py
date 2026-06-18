"""
Hàm nghiệp vụ cho tác vụ định kỳ liên quan đến HR.
"""

from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.audit.utils import audit_log
from apps.hr.models import TempAssignment


def expire_due_temp_assignments(run_date: date | None = None) -> dict:
    """
    Chuyển các điều động ACTIVE có end_date < hôm nay sang EXPIRED.

    Lưu ý nghiệp vụ:
    - EXPIRED chỉ là trạng thái hiển thị/vận hành.
    - Phiếu EXPIRED vẫn có hiệu lực lịch sử trong khoảng start_date/end_date
      để phục vụ chấm công các ngày đã qua.
    - Không tự sửa bảng chấm công.
    """
    today = run_date or timezone.localdate()

    qs = TempAssignment.objects.filter(
        status=TempAssignment.Status.ACTIVE,
        end_date__isnull=False,
        end_date__lt=today,
    ).select_related("employee", "to_unit")

    checked = qs.count()
    expired_count = 0

    if not checked:
        return {"checked": 0, "expired": 0, "skipped": 0, "date": today}

    with transaction.atomic():
        for ta in qs:
            old_status = ta.status
            ta.status = TempAssignment.Status.EXPIRED
            ta.save(update_fields=["status"])
            expired_count += 1

            audit_log(
                action_verb="UPDATE",
                object_type="temp_assignment",
                object_id=ta.id,
                object_repr=f"{ta.employee.employee_code}->{ta.to_unit.symbol}",
                actor=None,
                changes={"status": {"old": old_status, "new": ta.status}},
                request=None,
                action_code="TEMP_ASSIGNMENT_AUTO_EXPIRE",
                extra={"end_date": str(ta.end_date)},
            )

    return {
        "checked": checked,
        "expired": expired_count,
        "skipped": checked - expired_count,
        "date": today,
    }
