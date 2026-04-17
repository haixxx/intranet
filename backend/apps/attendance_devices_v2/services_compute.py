from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Optional

from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.attendance.models import AttendanceSettings, AttendanceCode
from apps.attendance.models_registration import AttendanceRegistration
from apps.hr.models import Employee

from .models import AttendanceNormalizedPunchV2, AttendancePunchMatchV2


@dataclass
class ComputeAuditResult:
    work_date: str
    employees_scanned: int = 0
    matches_created: int = 0
    notes: str = ""


def _get_match_window_minutes() -> int:
    s = AttendanceSettings.objects.first()
    if s and s.window_minutes:
        return int(s.window_minutes)
    return 60


def _local_dt(work_date, t: time) -> datetime:
    """
    Tạo datetime local (timezone-aware theo USE_TZ=True).
    Ở đây dùng timezone hiện tại của Django (Asia/Ho_Chi_Minh).
    """
    naive = datetime.combine(work_date, t)
    return dj_timezone.make_aware(naive, dj_timezone.get_current_timezone())


def _pick_nearest(target: datetime, punches: list[AttendanceNormalizedPunchV2], window: timedelta, used_ids: set[int]) -> AttendanceNormalizedPunchV2 | None:
    best = None
    best_abs = None
    for p in punches:
        if p.id in used_ids:
            continue
        delta = p.canonical_time_utc - target.astimezone(dj_timezone.utc)
        abs_sec = abs(int(delta.total_seconds()))
        if abs_sec <= int(window.total_seconds()):
            if best is None or abs_sec < best_abs:
                best = p
                best_abs = abs_sec
    return best


@transaction.atomic
def compute_audit_for_date(
    *,
    work_date,
    employee_ids: list[int] | None = None,
    compute_run_id: str = "",
    compute_version: int = 1,
) -> ComputeAuditResult:
    """
    Tạo AttendancePunchMatchV2 cho 1 work_date dựa trên AttendanceRegistration.

    - Không ghi vào Batch/Commit (audit-only).
    - Phù hợp để debug rule match trước khi áp dụng vào chốt công.
    """
    window_minutes = _get_match_window_minutes()
    window = timedelta(minutes=window_minutes)

    # Lấy registrations đã chốt hoặc nháp đều được; v1 lấy tất cả
    reg_qs = AttendanceRegistration.objects.select_related("employee", "code").filter(work_date=work_date)
    if employee_ids:
        reg_qs = reg_qs.filter(employee_id__in=employee_ids)

    regs = list(reg_qs)

    res = ComputeAuditResult(work_date=str(work_date), employees_scanned=len(regs))

    if not regs:
        res.notes = "Không có AttendanceRegistration cho ngày này."
        return res

    # Xoá audit cũ cùng run_id/version để chạy lại không rác
    # (Nếu bạn muốn giữ lịch sử nhiều lần chạy, bỏ đoạn delete này)
    if compute_run_id:
        AttendancePunchMatchV2.objects.filter(work_date=work_date, compute_run_id=compute_run_id).delete()

    for reg in regs:
        emp: Employee = reg.employee
        code: AttendanceCode = reg.code

        # lấy punches ứng viên theo ngày local mở rộng ±window
        day_start_local = dj_timezone.make_aware(datetime.combine(work_date, time(0, 0, 0)), dj_timezone.get_current_timezone()) - window
        day_end_local = dj_timezone.make_aware(datetime.combine(work_date, time(23, 59, 59)), dj_timezone.get_current_timezone()) + window

        # canonical_time_utc đang là UTC, nên filter theo UTC range
        start_utc = day_start_local.astimezone(dj_timezone.utc)
        end_utc = day_end_local.astimezone(dj_timezone.utc)

        punches = list(
            AttendanceNormalizedPunchV2.objects
            .filter(employee=emp, canonical_time_utc__gte=start_utc, canonical_time_utc__lte=end_utc)
            .order_by("canonical_time_utc")
        )

        used: set[int] = set()

        def create_match(field: str, target_dt_local: datetime, matched: AttendanceNormalizedPunchV2 | None, status: str, notes: str = ""):
            nonlocal res
            if matched:
                matched_local = matched.canonical_time_utc.astimezone(dj_timezone.get_current_timezone())
                delta_seconds = int((matched_local - target_dt_local).total_seconds())
            else:
                matched_local = None
                delta_seconds = None

            AttendancePunchMatchV2.objects.create(
                work_date=work_date,
                employee=emp,
                target_field=field,
                target_time_local=target_dt_local,
                matched_punch=matched,
                matched_time_local=matched_local,
                delta_seconds=delta_seconds,
                status=status,
                notes=notes,
                compute_run_id=compute_run_id,
                compute_version=compute_version,
                created_at=dj_timezone.now(),
            )
            res.matches_created += 1

        # Nếu code không đi làm mà có punches => vẫn ghi audit để dashboard
        if not code.is_work:
            # tạo audit record tổng quát cho 4 mốc nếu có mốc đăng ký; ở đây tạo theo những mốc có trong reg
            for field, tval in [("IN1", reg.in1), ("OUT1", reg.out1), ("IN2", reg.in2), ("OUT2", reg.out2)]:
                if not tval:
                    continue
                target_local = _local_dt(work_date, tval)
                matched = _pick_nearest(target_local, punches, window, used)
                if matched:
                    used.add(matched.id)
                create_match(field, target_local, matched, AttendancePunchMatchV2.Status.PUNCH_WHILE_NONWORK, notes="Có chấm công nhưng chế độ không đi làm.")
            continue

        # Xác định mốc cần theo code segments (AM/PM)
        need_am = (code.segments_am_type == AttendanceCode.SegmentType.WORK and code.requires_am_work)
        need_pm = (code.segments_pm_type == AttendanceCode.SegmentType.WORK and code.requires_pm_work)

        # Với Registration: coi như DAY nếu cần cả AM+PM => 4 mốc, nếu chỉ 1 buổi => 2 mốc tương ứng
        if need_am:
            if reg.in1:
                target = _local_dt(work_date, reg.in1)
                m = _pick_nearest(target, punches, window, used)
                if m:
                    used.add(m.id)
                    create_match("IN1", target, m, AttendancePunchMatchV2.Status.MATCHED)
                else:
                    create_match("IN1", target, None, AttendancePunchMatchV2.Status.MISSING)

            if reg.out1:
                target = _local_dt(work_date, reg.out1)
                m = _pick_nearest(target, punches, window, used)
                if m:
                    used.add(m.id)
                    create_match("OUT1", target, m, AttendancePunchMatchV2.Status.MATCHED)
                else:
                    create_match("OUT1", target, None, AttendancePunchMatchV2.Status.MISSING)

        if need_pm:
            if reg.in2:
                target = _local_dt(work_date, reg.in2)
                m = _pick_nearest(target, punches, window, used)
                if m:
                    used.add(m.id)
                    create_match("IN2", target, m, AttendancePunchMatchV2.Status.MATCHED)
                else:
                    create_match("IN2", target, None, AttendancePunchMatchV2.Status.MISSING)

            if reg.out2:
                target = _local_dt(work_date, reg.out2)
                m = _pick_nearest(target, punches, window, used)
                if m:
                    used.add(m.id)
                    create_match("OUT2", target, m, AttendancePunchMatchV2.Status.MATCHED)
                else:
                    create_match("OUT2", target, None, AttendancePunchMatchV2.Status.MISSING)

    return res