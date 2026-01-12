from datetime import date, timedelta
from celery import shared_task
from django.utils import timezone

from .services_resolve import resolve_batch  # đã có ở phần trước
from .services_dayfacts import compute_day_facts_for_date


@shared_task(name="attendance_devices.resolve_raw_events_employee")
def resolve_raw_events_employee(limit: int = 2000) -> dict:
    start = timezone.now()
    updated = resolve_batch(limit=limit)
    end = timezone.now()
    return {"updated": updated, "duration_sec": (end - start).total_seconds()}


@shared_task(name="attendance_devices.compute_day_facts_for_date")
def task_compute_day_facts_for_date(work_date_str: str) -> dict:
    """
    work_date_str: 'YYYY-MM-DD'
    """
    y, m, d = [int(x) for x in work_date_str.split("-")]
    wd = date(y, m, d)
    n = compute_day_facts_for_date(wd)
    return {"work_date": work_date_str, "facts_updated": n}


@shared_task(name="attendance_devices.compute_day_facts_range")
def task_compute_day_facts_range(start_date_str: str, end_date_str: str) -> dict:
    """
    Tính facts cho toàn bộ dải ngày [start, end].
    """
    y1, m1, d1 = [int(x) for x in start_date_str.split("-")]
    y2, m2, d2 = [int(x) for x in end_date_str.split("-")]
    s = date(y1, m1, d1)
    e = date(y2, m2, d2)
    cur = s
    total = 0
    while cur <= e:
        total += compute_day_facts_for_date(cur)
        cur += timedelta(days=1)
    return {"start": start_date_str, "end": end_date_str, "facts_updated": total}