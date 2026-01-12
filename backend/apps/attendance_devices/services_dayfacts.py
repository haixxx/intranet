from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple, List, Dict

from django.db import transaction
from django.utils import timezone

from apps.attendance.models import AttendanceSettings
from .models import AttendanceRawEvent, AttendanceDayFacts


def _cluster_times(times_sorted: List[datetime], cluster_minutes: int) -> List[datetime]:
    """
    Gom các mốc “gần trùng” (ví dụ chấm ở 2 máy trong vòng vài phút) thành một mốc.
    Lấy mốc đầu tiên trong cụm.
    """
    if not times_sorted or cluster_minutes <= 0:
        return times_sorted
    clustered: List[datetime] = []
    last_kept: Optional[datetime] = None
    delta = timedelta(minutes=cluster_minutes)
    for dt in times_sorted:
        if last_kept is None:
            clustered.append(dt)
            last_kept = dt
        else:
            if (dt - last_kept) <= delta:
                # bỏ mốc gần trùng, giữ mốc đầu
                continue
            else:
                clustered.append(dt)
                last_kept = dt
    return clustered


def _assign_inout(times_sorted: List[datetime]) -> Tuple[Optional[time], Optional[time], Optional[time], Optional[time], Dict[str, bool]]:
    in1 = out1 = in2 = out2 = None
    anomalies: Dict[str, bool] = {}

    if len(times_sorted) >= 1:
        in1 = times_sorted[0].time()
    if len(times_sorted) >= 2:
        out1 = times_sorted[1].time()
    if len(times_sorted) >= 3:
        in2 = times_sorted[2].time()
    if len(times_sorted) >= 4:
        out2 = times_sorted[3].time()

    if in1 and not out1 and (in2 or out2):
        anomalies["missing_out1"] = True
    if in2 and not out2:
        anomalies["missing_out2"] = True
    if not in1 and (out1 or in2 or out2):
        anomalies["missing_in1"] = True

    return in1, out1, in2, out2, anomalies


@transaction.atomic
def compute_day_facts_for_employee_date(employee_id: int, work_date: date) -> AttendanceDayFacts:
    evs = AttendanceRawEvent.objects.filter(
        employee_id=employee_id,
        event_time_local__date=work_date,
    ).order_by("event_time_local").only("event_time_local", "id")

    times: List[datetime] = [e.event_time_local for e in evs]

    # Đọc cấu hình cluster_minutes; mặc định 2 phút nếu không có
    settings = AttendanceSettings.objects.first()
    cluster_min = int(getattr(settings, "cluster_minutes", 2) or 2)
    clustered_times = _cluster_times(times, cluster_min)

    in1, out1, in2, out2, anomalies = _assign_inout(clustered_times)

    obj, _created = AttendanceDayFacts.objects.update_or_create(
        employee_id=employee_id,
        work_date=work_date,
        defaults={
            "in1": in1,
            "out1": out1,
            "in2": in2,
            "out2": out2,
            "raw_count": len(times),
            "anomalies_json": anomalies or {},
            "computed_at": timezone.now(),
        },
    )
    return obj


def compute_day_facts_for_date(work_date: date, employee_ids: Optional[List[int]] = None) -> int:
    qs = AttendanceRawEvent.objects.filter(event_time_local__date=work_date, employee__isnull=False).values_list("employee_id", flat=True).distinct()
    if employee_ids:
        qs = qs.filter(employee_id__in=employee_ids)
    count = 0
    for emp_id in qs:
        compute_day_facts_for_employee_date(emp_id, work_date)
        count += 1
    return count