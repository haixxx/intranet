from datetime import date, time
from typing import Optional, Dict

from django.db import transaction
from django.utils import timezone

from .models import AttendanceDayFacts
from .models_adjustments import AttendanceManualAdjustment, AttendanceImportBatch, AttendanceImportLine


def _pick_time(slot: str, obj) -> Optional[time]:
    if not obj:
        return None
    val = getattr(obj, slot, None)
    return val if isinstance(val, time) or val is None else None


@transaction.atomic
def overlay_day(employee_id: int, work_date: date) -> AttendanceDayFacts:
    """
    Áp overlay cho 1 nhân viên/ngày:
    - Base: lấy từ DayFacts (in1/out1/in2/out2) -> source RAW nếu có
    - IMPORT: áp các dòng import theo thứ tự batch.imported_at (FILL_MISSING_ONLY: chỉ bù mốc thiếu; OVERWRITE_EXPLICIT: ghi đè)
    - MANUAL: áp cuối (luôn ghi đè mốc được khai)
    """
    facts = AttendanceDayFacts.objects.filter(employee_id=employee_id, work_date=work_date).first()
    if not facts:
        facts = AttendanceDayFacts.objects.create(employee_id=employee_id, work_date=work_date)

    # Base từ RAW
    eff: Dict[str, Optional[time]] = {
        "in1": facts.in1, "out1": facts.out1, "in2": facts.in2, "out2": facts.out2,
    }
    src: Dict[str, str] = {
        "in1": "RAW" if facts.in1 else "",
        "out1": "RAW" if facts.out1 else "",
        "in2": "RAW" if facts.in2 else "",
        "out2": "RAW" if facts.out2 else "",
    }

    # IMPORT: áp theo thời gian import
    line_qs = AttendanceImportLine.objects.filter(
        employee_id=employee_id, work_date=work_date, valid=True
    ).select_related("batch").order_by("batch__imported_at")

    for line in line_qs:
        mode = line.batch.mode
        for slot in ("in1", "out1", "in2", "out2"):
            val = _pick_time(slot, line)
            if val is None:
                continue
            if mode == AttendanceImportBatch.Mode.FILL_MISSING_ONLY:
                if not eff[slot]:
                    eff[slot] = val
                    src[slot] = "IMPORT"
            elif mode == AttendanceImportBatch.Mode.OVERWRITE_EXPLICIT:
                eff[slot] = val
                src[slot] = "IMPORT"

    # MANUAL: áp cuối cùng, mốc nào có thì ghi đè
    man_qs = AttendanceManualAdjustment.objects.filter(
        employee_id=employee_id, work_date=work_date, is_active=True
    ).order_by("applied_at")

    for adj in man_qs:
        for slot in ("in1", "out1", "in2", "out2"):
            val = _pick_time(slot, adj)
            if val is None:
                continue
            eff[slot] = val
            src[slot] = "MANUAL"

    # Cập nhật facts
    facts.effective_in1 = eff["in1"]
    facts.effective_out1 = eff["out1"]
    facts.effective_in2 = eff["in2"]
    facts.effective_out2 = eff["out2"]

    facts.source_in1 = src["in1"] or ""
    facts.source_out1 = src["out1"] or ""
    facts.source_in2 = src["in2"] or ""
    facts.source_out2 = src["out2"] or ""

    facts.overlay_version = (facts.overlay_version or 0) + 1
    facts.last_overlay_at = timezone.now()
    facts.save(update_fields=[
        "effective_in1", "effective_out1", "effective_in2", "effective_out2",
        "source_in1", "source_out1", "source_in2", "source_out2",
        "overlay_version", "last_overlay_at",
    ])
    return facts


def overlay_day_range(start_date: date, end_date: date, employee_ids: Optional[list[int]] = None) -> int:
    """
    Áp overlay cho dải ngày [start, end]; trả về số facts đã cập nhật.
    """
    if start_date > end_date:
        return 0

    qs = AttendanceDayFacts.objects.filter(work_date__range=(start_date, end_date)).values_list("employee_id", "work_date")
    if employee_ids:
        qs = qs.filter(employee_id__in=employee_ids)

    count = 0
    for emp_id, wd in qs:
        overlay_day(emp_id, wd)
        count += 1
    return count