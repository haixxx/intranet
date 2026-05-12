from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time, timezone as datetime_timezone
from typing import Literal, Protocol

from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.attendance.models import AttendanceSettings, AttendanceCode
from apps.attendance.models_batch import AttendanceCommit
from apps.hr.models import Employee

from .models import AttendanceNormalizedPunchV2, AttendancePunchMatchV2
from .models_manual_punch import AttendanceManualPunch
from .models_master_list import AttendanceDeviceMasterListV2


SourceMode = Literal["commit"]


@dataclass
class ComputeMasterResult:
    work_date: str
    unit_id: int
    commit_id: int = 0
    employees_scanned: int = 0
    matches_created: int = 0
    master_rows_upserted: int = 0
    exempt_rows: int = 0
    notes: str = ""


def _get_window_minutes() -> int:
    s = AttendanceSettings.objects.first()
    if s and getattr(s, "window_minutes", None):
        return int(s.window_minutes)
    return 60


def _make_local_dt(work_date, t: dt_time) -> datetime:
    tz = dj_timezone.get_current_timezone()
    naive = datetime.combine(work_date, t)
    return dj_timezone.make_aware(naive, tz)


def _expected_flags(code: AttendanceCode) -> dict:
    # WORK ở AM => yêu cầu IN1/OUT1; WORK ở PM => yêu cầu IN2/OUT2
    if not code or not code.is_work:
        return {
            "expected_in1": False, "expected_out1": False, "expected_in2": False, "expected_out2": False, "expected_marks": 0
        }
    expected_in1 = bool(code.requires_am_work)
    expected_out1 = bool(code.requires_am_work)
    expected_in2 = bool(code.requires_pm_work)
    expected_out2 = bool(code.requires_pm_work)
    expected_marks = int(expected_in1) + int(expected_out1) + int(expected_in2) + int(expected_out2)
    return {
        "expected_in1": expected_in1,
        "expected_out1": expected_out1,
        "expected_in2": expected_in2,
        "expected_out2": expected_out2,
        "expected_marks": expected_marks,
    }


class _PunchLike(Protocol):
    """
    Adapter interface để gom NormalizedPunch và ManualPunch vào chung 1 danh sách.
    """
    id: int
    canonical_time_utc: datetime


class _ManualPunchAdapter:
    """
    Chuyển AttendanceManualPunch về interface giống NormalizedPunchV2:
    - canonical_time_utc = thoi_gian_utc
    - id dùng offset để không đụng id NormalizedPunch (chỉ để "used_ids" hoạt động)
    """
    __slots__ = ("id", "canonical_time_utc", "_src")

    def __init__(self, src: AttendanceManualPunch):
        self._src = src
        self.id = 1_000_000_000 + int(src.id)  # offset lớn để tránh trùng
        self.canonical_time_utc = src.thoi_gian_utc


def _pick_nearest_punch(
    *,
    target_local: datetime,
    punches: list[_PunchLike],
    window: timedelta,
    used_ids: set[int],
    min_local: datetime | None = None,
    max_local: datetime | None = None,
) -> _PunchLike | None:
    """
    Chọn punch gần target nhất trong cửa sổ ±window.
    Có ràng buộc [min_local, max_local] để đảm bảo thứ tự IN1 < OUT1 < IN2 < OUT2.
    """
    tz = dj_timezone.get_current_timezone()
    target_utc = target_local.astimezone(datetime_timezone.utc)

    best = None
    best_abs = None
    for p in punches:
        if p.id in used_ids:
            continue
        p_local = p.canonical_time_utc.astimezone(tz)
        if min_local and p_local < min_local:
            continue
        if max_local and p_local > max_local:
            continue

        delta = p.canonical_time_utc - target_utc
        abs_sec = abs(int(delta.total_seconds()))
        if abs_sec <= int(window.total_seconds()):
            if best is None or abs_sec < best_abs:
                best = p
                best_abs = abs_sec
    return best


def _midpoint(a: datetime, b: datetime) -> datetime:
    if a > b:
        a, b = b, a
    return a + (b - a) / 2


@transaction.atomic
def compute_master_list_for_unit_date(
    *,
    unit_id: int,
    work_date,
    source: SourceMode = "commit",
    compute_run_id: str = "",
    compute_version: int = 1,
) -> ComputeMasterResult:
    window = timedelta(minutes=_get_window_minutes())

    commit = AttendanceCommit.objects.filter(unit_id=unit_id, work_date=work_date).select_related("unit").first()
    if not commit:
        return ComputeMasterResult(
            work_date=str(work_date),
            unit_id=unit_id,
            notes="Không có AttendanceCommit cho unit/date này => không compute (commit-only).",
        )

    res = ComputeMasterResult(
        work_date=str(work_date),
        unit_id=unit_id,
        commit_id=commit.id,
        notes=f"commit_id={commit.id}",
    )

    items = list(commit.items.select_related("employee", "code").all())
    res.employees_scanned = len(items)

    tz = dj_timezone.get_current_timezone()

    # Lấy punches trong khoảng ngày +/- window (UTC) để đối chiếu
    day_start_local = dj_timezone.make_aware(datetime.combine(work_date, dt_time(0, 0, 0)), tz) - window
    day_end_local = dj_timezone.make_aware(datetime.combine(work_date, dt_time(23, 59, 59)), tz) + window
    start_utc = day_start_local.astimezone(datetime_timezone.utc)
    end_utc = day_end_local.astimezone(datetime_timezone.utc)

    emp_ids = [it.employee_id for it in items]

    # 1) Punch từ máy (đã chuẩn hoá)
    normalized_qs = (
        AttendanceNormalizedPunchV2.objects
        .filter(employee_id__in=emp_ids, canonical_time_utc__gte=start_utc, canonical_time_utc__lte=end_utc)
        .select_related("best_device")
        .order_by("employee_id", "canonical_time_utc")
    )

    # 2) Punch thêm tay (chỉ thêm mới)
    manual_qs = (
        AttendanceManualPunch.objects
        .filter(employee_id__in=emp_ids, thoi_gian_utc__gte=start_utc, thoi_gian_utc__lte=end_utc)
        .select_related("employee")
        .order_by("employee_id", "thoi_gian_utc")
    )

    punches_by_emp: dict[int, list[_PunchLike]] = {}

    for p in normalized_qs:
        punches_by_emp.setdefault(p.employee_id, []).append(p)

    for mp in manual_qs:
        punches_by_emp.setdefault(mp.employee_id, []).append(_ManualPunchAdapter(mp))

    # Đảm bảo danh sách theo thời gian tăng dần
    for emp_id, arr in punches_by_emp.items():
        arr.sort(key=lambda x: x.canonical_time_utc)

    now = dj_timezone.now()

    def create_match(*, emp: Employee, field: str, target_local: datetime, matched: _PunchLike | None, status: str, notes: str = ""):
        nonlocal res

        # Lưu PunchMatchV2 chỉ tham chiếu được NormalizedPunchV2.
        # Với punch thêm tay: không set matched_punch (null) nhưng vẫn set matched_time_local + delta để audit.
        matched_punch_fk = matched if isinstance(matched, AttendanceNormalizedPunchV2) else None

        if matched:
            matched_local = matched.canonical_time_utc.astimezone(tz)
            delta_seconds = int((matched_local - target_local).total_seconds())
        else:
            matched_local = None
            delta_seconds = None

        AttendancePunchMatchV2.objects.create(
            work_date=work_date,
            employee=emp,
            target_field=field,
            target_time_local=target_local,
            matched_punch=matched_punch_fk,
            matched_time_local=matched_local,
            delta_seconds=delta_seconds,
            status=status,
            notes=notes,
            compute_run_id=compute_run_id,
            compute_version=compute_version,
            created_at=now,
        )
        res.matches_created += 1
        return matched_local, delta_seconds

    # Upsert master:
    # - xóa rows cũ unit/date để dễ code
    # - nhưng vẫn giữ override (nếu đã sửa) và giữ thông tin yêu cầu sửa
    old_rows = {
        r.employee_id: r
        for r in AttendanceDeviceMasterListV2.objects.filter(work_date=work_date, unit_id=unit_id)
        .select_related("override_by", "yeu_cau_sua_tao_boi", "yeu_cau_sua_xu_ly_boi")
    }
    AttendanceDeviceMasterListV2.objects.filter(work_date=work_date, unit_id=unit_id).delete()

    for it in items:
        if hasattr(it, "include_in_unit") and not bool(it.include_in_unit):
            continue

        emp: Employee = it.employee
        code: AttendanceCode = it.code
        exp = _expected_flags(code)
        expected_marks = exp["expected_marks"]
        if expected_marks == 0:
            continue

        is_exempt = bool(getattr(emp, "skip_device_attendance", False))
        used: set[int] = set()
        punches = punches_by_emp.get(emp.id, [])

        # build targets (nullable)
        t_in1 = _make_local_dt(work_date, it.in1) if exp["expected_in1"] and it.in1 else None
        t_out1 = _make_local_dt(work_date, it.out1) if exp["expected_out1"] and it.out1 else None
        t_in2 = _make_local_dt(work_date, it.in2) if exp["expected_in2"] and it.in2 else None
        t_out2 = _make_local_dt(work_date, it.out2) if exp["expected_out2"] and it.out2 else None

        # midpoint bounds (only when both exist)
        mid_1_2 = _midpoint(t_out1, t_in2) if (t_out1 and t_in2) else None

        # Actual results placeholders
        a_in1 = a_out1 = a_in2 = a_out2 = None
        d_in1 = d_out1 = d_in2 = d_out2 = None
        s_in1 = s_out1 = s_in2 = s_out2 = ""

        if is_exempt:
            # create punchmatch exempt for each expected target
            for fld, tgt in [("IN1", t_in1), ("OUT1", t_out1), ("IN2", t_in2), ("OUT2", t_out2)]:
                if tgt:
                    create_match(
                        emp=emp,
                        field=fld,
                        target_local=tgt,
                        matched=None,
                        status=AttendancePunchMatchV2.Status.EXEMPT,
                        notes="Nhân sự đặc cách, không yêu cầu chấm máy.",
                    )
                    res.exempt_rows += 1
            s_in1 = AttendancePunchMatchV2.Status.EXEMPT if t_in1 else ""
            s_out1 = AttendancePunchMatchV2.Status.EXEMPT if t_out1 else ""
            s_in2 = AttendancePunchMatchV2.Status.EXEMPT if t_in2 else ""
            s_out2 = AttendancePunchMatchV2.Status.EXEMPT if t_out2 else ""
        else:
            # IN1
            if t_in1:
                m = _pick_nearest_punch(target_local=t_in1, punches=punches, window=window, used_ids=used, max_local=mid_1_2)
                if m:
                    used.add(m.id)
                    a_in1, d_in1 = create_match(emp=emp, field="IN1", target_local=t_in1, matched=m, status=AttendancePunchMatchV2.Status.MATCHED)
                    s_in1 = AttendancePunchMatchV2.Status.MATCHED
                else:
                    create_match(emp=emp, field="IN1", target_local=t_in1, matched=None, status=AttendancePunchMatchV2.Status.MISSING)
                    s_in1 = AttendancePunchMatchV2.Status.MISSING

            # OUT1
            if t_out1:
                m = _pick_nearest_punch(
                    target_local=t_out1, punches=punches, window=window, used_ids=used,
                    min_local=a_in1 or None, max_local=mid_1_2
                )
                if m:
                    used.add(m.id)
                    a_out1, d_out1 = create_match(emp=emp, field="OUT1", target_local=t_out1, matched=m, status=AttendancePunchMatchV2.Status.MATCHED)
                    s_out1 = AttendancePunchMatchV2.Status.MATCHED
                else:
                    create_match(emp=emp, field="OUT1", target_local=t_out1, matched=None, status=AttendancePunchMatchV2.Status.MISSING)
                    s_out1 = AttendancePunchMatchV2.Status.MISSING

            # IN2
            if t_in2:
                m = _pick_nearest_punch(
                    target_local=t_in2, punches=punches, window=window, used_ids=used,
                    min_local=mid_1_2, max_local=None
                )
                if m:
                    used.add(m.id)
                    a_in2, d_in2 = create_match(emp=emp, field="IN2", target_local=t_in2, matched=m, status=AttendancePunchMatchV2.Status.MATCHED)
                    s_in2 = AttendancePunchMatchV2.Status.MATCHED
                else:
                    create_match(emp=emp, field="IN2", target_local=t_in2, matched=None, status=AttendancePunchMatchV2.Status.MISSING)
                    s_in2 = AttendancePunchMatchV2.Status.MISSING

            # OUT2
            if t_out2:
                m = _pick_nearest_punch(
                    target_local=t_out2, punches=punches, window=window, used_ids=used,
                    min_local=a_in2 or mid_1_2, max_local=None
                )
                if m:
                    used.add(m.id)
                    a_out2, d_out2 = create_match(emp=emp, field="OUT2", target_local=t_out2, matched=m, status=AttendancePunchMatchV2.Status.MATCHED)
                    s_out2 = AttendancePunchMatchV2.Status.MATCHED
                else:
                    create_match(emp=emp, field="OUT2", target_local=t_out2, matched=None, status=AttendancePunchMatchV2.Status.MISSING)
                    s_out2 = AttendancePunchMatchV2.Status.MISSING

        # missing_marks summary (exclude exempt)
        missing_marks = 0
        if not is_exempt:
            for expected, status in [
                (exp["expected_in1"], s_in1),
                (exp["expected_out1"], s_out1),
                (exp["expected_in2"], s_in2),
                (exp["expected_out2"], s_out2),
            ]:
                if expected and status == AttendancePunchMatchV2.Status.MISSING:
                    missing_marks += 1

        # preserve overrides if already edited
        old = old_rows.get(emp.id)
        preserve_override = bool(old and old.override_at)

        def pick_override(old_val, actual_val):
            if preserve_override:
                return old_val
            return actual_val

        # preserve "yêu cầu sửa" luôn giữ lại khi recompute (HR xử lý ở UI)
        AttendanceDeviceMasterListV2.objects.create(
            work_date=work_date,
            unit=commit.unit,
            employee=emp,
            commit=commit,
            commit_updated_at_at_compute=getattr(commit, "updated_at", None),

            compute_state=AttendanceDeviceMasterListV2.ComputeState.COMPUTED,
            compute_run_id=compute_run_id,
            compute_version=compute_version,
            computed_at=now,

            is_exempt=is_exempt,
            expected_in1=exp["expected_in1"],
            expected_out1=exp["expected_out1"],
            expected_in2=exp["expected_in2"],
            expected_out2=exp["expected_out2"],
            expected_marks=expected_marks,

            target_in1_local=t_in1,
            target_out1_local=t_out1,
            target_in2_local=t_in2,
            target_out2_local=t_out2,

            status_in1=s_in1,
            status_out1=s_out1,
            status_in2=s_in2,
            status_out2=s_out2,

            actual_in1_local=a_in1,
            actual_out1_local=a_out1,
            actual_in2_local=a_in2,
            actual_out2_local=a_out2,

            delta_in1_seconds=d_in1,
            delta_out1_seconds=d_out1,
            delta_in2_seconds=d_in2,
            delta_out2_seconds=d_out2,

            override_in1_local=pick_override(getattr(old, "override_in1_local", None), a_in1),
            override_out1_local=pick_override(getattr(old, "override_out1_local", None), a_out1),
            override_in2_local=pick_override(getattr(old, "override_in2_local", None), a_in2),
            override_out2_local=pick_override(getattr(old, "override_out2_local", None), a_out2),
            override_by=getattr(old, "override_by", None) if preserve_override else None,
            override_at=getattr(old, "override_at", None) if preserve_override else None,
            override_note=getattr(old, "override_note", "") if preserve_override else "",

            missing_marks=0 if is_exempt else missing_marks,

            # ---- giữ yêu cầu sửa khi recompute ----
            yeu_cau_sua_trang_thai=getattr(old, "yeu_cau_sua_trang_thai", AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.NONE),
            yeu_cau_sua_noi_dung=getattr(old, "yeu_cau_sua_noi_dung", ""),
            yeu_cau_sua_tao_boi=getattr(old, "yeu_cau_sua_tao_boi", None),
            yeu_cau_sua_tao_luc=getattr(old, "yeu_cau_sua_tao_luc", None),
            yeu_cau_sua_xu_ly_boi=getattr(old, "yeu_cau_sua_xu_ly_boi", None),
            yeu_cau_sua_xu_ly_luc=getattr(old, "yeu_cau_sua_xu_ly_luc", None),
        )
        res.master_rows_upserted += 1

    return res