"""
Hàm nghiệp vụ cho tác vụ định kỳ (cron) liên quan đến HR.
"""
from datetime import date
from django.db import transaction
from django.utils import timezone
from apps.hr.models import TempAssignment
from apps.audit.utils import audit_log


def expire_due_temp_assignments(run_date: date | None = None) -> dict:
    """
    Chuyển các điều động ACTIVE có end_date < hôm nay sang EXPIRED.
    - run_date: cho phép test bằng ngày giả lập; mặc định = today (localdate).
    - Chỉ xử lý apply_flag True hay False đều như nhau (vì chỉ là trạng thái hết hạn).
    - Ghi nhật ký audit cho từng bản ghi.

    Trả về dict thống kê:
      {
        'checked': <int tổng số ACTIVE có end_date>,
        'expired': <int số chuyển đổi>,
        'skipped': <int (có end_date >= today hoặc đã không ACTIVE)>,
        'date': <ngày chạy>
      }
    """
    today = run_date or timezone.localdate()
    # Lọc các bản ghi có end_date < today và status=ACTIVE
    qs = TempAssignment.objects.filter(
        status=TempAssignment.Status.ACTIVE,
        end_date__isnull=False,
        end_date__lt=today
    ).select_related('employee', 'to_unit')

    checked = qs.count()
    expired_count = 0

    if not checked:
        return {'checked': 0, 'expired': 0, 'skipped': 0, 'date': today}

    with transaction.atomic():
        for ta in qs:
            old_status = ta.status
            ta.status = TempAssignment.Status.EXPIRED
            ta.save(update_fields=['status'])
            expired_count += 1

            audit_log(
                action_verb="UPDATE",
                object_type="temp_assignment",
                object_id=ta.id,
                object_repr=f"{ta.employee.employee_code}->{ta.to_unit.symbol}",
                actor=None,                # Cron job (không có user)
                changes={'status': {'old': old_status, 'new': ta.status}},
                request=None,
                action_code="TEMP_ASSIGNMENT_AUTO_EXPIRE",
                extra={'end_date': str(ta.end_date)}
            )

    return {
        'checked': checked,
        'expired': expired_count,
        'skipped': checked - expired_count,
        'date': today
    }