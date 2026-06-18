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

MANUAL_SOURCE_MAY_HONG = "MAY_HONG"
MANUAL_SOURCE_SUA_DU_LIEU = "SUA_DU_LIEU"
MANUAL_SOURCE_DEFAULT = MANUAL_SOURCE_MAY_HONG

# Lấy log qua ngày đến sau giờ ra ca 3.
# Target qua ngày được xác định theo từng cặp IN/OUT: nếu OUT <= IN thì OUT thuộc ngày hôm sau.
OVERNIGHT_END_CUTOFF = dt_time(8, 0)


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


def _make_target_dt(work_date, t: dt_time | None, *, next_day: bool = False) -> datetime | None:
    """Tạo datetime local cho một mốc đăng ký đã biết có thuộc ngày hôm sau hay không."""
    if not t:
        return None
    target_date = work_date + timedelta(days=1) if next_day else work_date
    return _make_local_dt(target_date, t)


def _pair_targets(work_date, in_time: dt_time | None, out_time: dt_time | None, in_field: str, out_field: str):
    """
    Tạo target cho một cặp vào/ra. Nếu giờ ra <= giờ vào thì hiểu giờ ra là ngày hôm sau.
    Quy tắc này xử lý đúng L3 dạng 22:00-06:00 ở mốc 1, không chỉ riêng OUT2.
    """
    out_next_day = bool(in_time and out_time and out_time <= in_time)
    return {
        in_field: _make_target_dt(work_date, in_time),
        out_field: _make_target_dt(work_date, out_time, next_day=out_next_day),
    }


def _expected_flags_and_targets(code: AttendanceCode, item, work_date) -> tuple[dict, dict[str, datetime | None], list[str]]:
    """
    Xác định mốc kỳ vọng và target thực tế.

    Ưu tiên snapshot của AttendanceCommitItem nếu đã có Phase 5C:
    - Mốc đăng ký đã chốt nằm ở registered_*_snapshot.
    - Có mốc nào thì đối chiếu mốc đó; không join ngược AttendanceCode hiện tại để quyết định lịch sử.

    Với dữ liệu cũ chưa có snapshot, fallback theo code.requires_* + item.in/out như trước.
    """
    targets: dict[str, datetime | None] = {
        "IN1": None,
        "OUT1": None,
        "IN2": None,
        "OUT2": None,
    }
    missing_required: list[str] = []
    empty_expected = {
        "expected_in1": False,
        "expected_out1": False,
        "expected_in2": False,
        "expected_out2": False,
        "expected_marks": 0,
    }

    has_snapshot = bool(getattr(item, "code_snapshot", ""))
    is_work = bool(getattr(item, "is_work_snapshot", False)) if has_snapshot else bool(code and code.is_work)
    if not is_work:
        return empty_expected, targets, missing_required

    if has_snapshot:
        item_times = {
            "IN1": getattr(item, "registered_in1_snapshot", None),
            "OUT1": getattr(item, "registered_out1_snapshot", None),
            "IN2": getattr(item, "registered_in2_snapshot", None),
            "OUT2": getattr(item, "registered_out2_snapshot", None),
        }
        pair_target_map = {}
        pair_target_map.update(_pair_targets(work_date, item_times["IN1"], item_times["OUT1"], "IN1", "OUT1"))
        pair_target_map.update(_pair_targets(work_date, item_times["IN2"], item_times["OUT2"], "IN2", "OUT2"))
        expected: dict[str, bool] = {}
        for field, t in item_times.items():
            expected[field] = bool(t)
            if t:
                targets[field] = pair_target_map.get(field)
        expected_marks = sum(1 for v in expected.values() if v)
        return {
            "expected_in1": expected["IN1"],
            "expected_out1": expected["OUT1"],
            "expected_in2": expected["IN2"],
            "expected_out2": expected["OUT2"],
            "expected_marks": expected_marks,
        }, targets, missing_required

    if not code:
        return empty_expected, targets, missing_required

    requires = {
        "IN1": bool(code.requires_am_work),
        "OUT1": bool(code.requires_am_work),
        "IN2": bool(code.requires_pm_work),
        "OUT2": bool(code.requires_pm_work),
    }
    item_times = {
        "IN1": getattr(item, "in1", None),
        "OUT1": getattr(item, "out1", None),
        "IN2": getattr(item, "in2", None),
        "OUT2": getattr(item, "out2", None),
    }

    pair_target_map = {}
    pair_target_map.update(_pair_targets(work_date, item_times["IN1"], item_times["OUT1"], "IN1", "OUT1"))
    pair_target_map.update(_pair_targets(work_date, item_times["IN2"], item_times["OUT2"], "IN2", "OUT2"))

    expected: dict[str, bool] = {}
    for field, required in requires.items():
        t = item_times[field]
        if required and t:
            expected[field] = True
            targets[field] = pair_target_map.get(field)
        elif required and not t:
            expected[field] = False
            missing_required.append(field)
        else:
            expected[field] = False

    expected_marks = sum(1 for v in expected.values() if v)
    return {
        "expected_in1": expected["IN1"],
        "expected_out1": expected["OUT1"],
        "expected_in2": expected["IN2"],
        "expected_out2": expected["OUT2"],
        "expected_marks": expected_marks,
    }, targets, missing_required

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


@dataclass
class _ManualOverrideValue:
    local_dt: datetime
    user: object | None
    at: datetime | None
    note: str


def _manual_source_type(mp: AttendanceManualPunch) -> str:
    note = (mp.ghi_chu or "").upper()
    if "SOURCE:SUA_DU_LIEU" in note:
        return MANUAL_SOURCE_SUA_DU_LIEU
    if "SOURCE:MAY_HONG" in note:
        return MANUAL_SOURCE_MAY_HONG
    # Backward compatible: dữ liệu nhập tay cũ trước khi có SOURCE vẫn giữ hành vi cũ, tức tham gia actual.
    return MANUAL_SOURCE_DEFAULT


def _manual_target_field(mp: AttendanceManualPunch) -> str:
    note = (mp.ghi_chu or "").strip().upper()
    for field in ("IN1", "OUT1", "IN2", "OUT2"):
        if note.startswith(field):
            return field
    return ""


def _manual_clean_note(mp: AttendanceManualPunch) -> str:
    note = (mp.ghi_chu or "").strip()
    # Giữ nguyên để audit, chỉ thêm prefix dễ hiểu khi đưa vào override_note.
    return note


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

    # Lấy punches trong khoảng đủ rộng cho ngày công:
    # - 00:00 work_date - window_minutes;
    # - 08:00 ngày hôm sau + window_minutes để không mất giờ ra ca 3 (22:00-06:00).
    # Đây là window đối chiếu ca, khác hoàn toàn với cluster_minutes của normalize.
    day_start_local = dj_timezone.make_aware(datetime.combine(work_date, dt_time(0, 0, 0)), tz) - window
    day_end_local = dj_timezone.make_aware(datetime.combine(work_date + timedelta(days=1), OVERNIGHT_END_CUTOFF), tz) + window
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

    # 2) Punch thêm tay. Phân 2 loại theo marker trong ghi_chu:
    # - SOURCE:MAY_HONG: dữ liệu thay thế máy khi máy hỏng/mất log => tham gia actual_* như punch máy.
    # - SOURCE:SUA_DU_LIEU: dữ liệu HR dùng để sửa kết quả => KHÔNG vào actual_*, chỉ ghi đè override_*.
    # - Dữ liệu cũ chưa có SOURCE được giữ hành vi cũ: coi như MAY_HONG.
    manual_qs = (
        AttendanceManualPunch.objects
        .filter(employee_id__in=emp_ids, thoi_gian_utc__gte=start_utc, thoi_gian_utc__lte=end_utc)
        .select_related("employee", "tao_boi")
        .order_by("employee_id", "thoi_gian_utc", "tao_luc")
    )

    punches_by_emp: dict[int, list[_PunchLike]] = {}
    manual_override_by_emp: dict[int, dict[str, _ManualOverrideValue]] = {}

    for p in normalized_qs:
        punches_by_emp.setdefault(p.employee_id, []).append(p)

    for mp in manual_qs:
        source_type = _manual_source_type(mp)
        if source_type == MANUAL_SOURCE_SUA_DU_LIEU:
            field = _manual_target_field(mp)
            if field:
                current = manual_override_by_emp.setdefault(mp.employee_id, {}).get(field)
                # Nếu có nhiều mốc sửa cùng field, lấy bản tạo mới nhất.
                if current is None or (mp.tao_luc and current.at and mp.tao_luc >= current.at):
                    manual_override_by_emp.setdefault(mp.employee_id, {})[field] = _ManualOverrideValue(
                        local_dt=mp.thoi_gian_local,
                        user=getattr(mp, "tao_boi", None),
                        at=getattr(mp, "tao_luc", None),
                        note=_manual_clean_note(mp),
                    )
        else:
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

    missing_target_warnings: list[str] = []
    skipped_include_false = 0
    skipped_expected_zero = 0

    for it in items:
        if hasattr(it, "include_in_unit") and not bool(it.include_in_unit):
            skipped_include_false += 1
            continue

        emp: Employee = it.employee
        code: AttendanceCode = it.code
        exp, targets, missing_required = _expected_flags_and_targets(code, it, work_date)
        if missing_required:
            emp_code = getattr(emp, "employee_code", "") or str(emp.id)
            missing_target_warnings.append(f"{emp_code}: thiếu {','.join(missing_required)}")
        expected_marks = exp["expected_marks"]
        if expected_marks == 0:
            skipped_expected_zero += 1
            continue

        is_exempt = bool(getattr(emp, "skip_device_attendance", False))
        used: set[int] = set()
        punches = punches_by_emp.get(emp.id, [])
        manual_overrides = manual_override_by_emp.get(emp.id, {})

        # target đã được build từ công chốt, trong đó OUT nhỏ hơn/ bằng IN thì thuộc ngày hôm sau.
        t_in1 = targets["IN1"]
        t_out1 = targets["OUT1"]
        t_in2 = targets["IN2"]
        t_out2 = targets["OUT2"]

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

        # Override rules:
        # 1) Manual SOURCE:SUA_DU_LIEU ghi đè override theo từng mốc, kể cả trước đó HR đã sửa.
        # 2) Nếu không có manual sửa dữ liệu, giữ override cũ nếu đã từng sửa (old.override_at).
        # 3) Nếu chưa từng sửa, override mặc định = actual mới.
        old = old_rows.get(emp.id)
        old_override_note = getattr(old, "override_note", "") if old else ""
        old_override_is_manual_sua = bool(old_override_note.startswith("Bổ sung sửa dữ liệu:"))
        preserve_override = bool(old and old.override_at and not old_override_is_manual_sua)

        def pick_override(field: str, old_val, actual_val):
            mo = manual_overrides.get(field)
            if mo:
                return mo.local_dt
            if preserve_override:
                return old_val
            return actual_val

        manual_override_values = [v for v in manual_overrides.values() if v]
        latest_manual_override = None
        if manual_override_values:
            latest_manual_override = max(manual_override_values, key=lambda x: x.at or now)

        if latest_manual_override:
            final_override_by = latest_manual_override.user
            final_override_at = latest_manual_override.at or now
            final_override_note = "Bổ sung sửa dữ liệu: " + " ; ".join(v.note for v in manual_override_values if v.note)
        elif preserve_override:
            final_override_by = getattr(old, "override_by", None)
            final_override_at = getattr(old, "override_at", None)
            final_override_note = getattr(old, "override_note", "")
        else:
            final_override_by = None
            final_override_at = None
            final_override_note = ""

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

            override_in1_local=pick_override("IN1", getattr(old, "override_in1_local", None), a_in1),
            override_out1_local=pick_override("OUT1", getattr(old, "override_out1_local", None), a_out1),
            override_in2_local=pick_override("IN2", getattr(old, "override_in2_local", None), a_in2),
            override_out2_local=pick_override("OUT2", getattr(old, "override_out2_local", None), a_out2),
            override_by=final_override_by,
            override_at=final_override_at,
            override_note=final_override_note,

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

    note_parts = [res.notes] if res.notes else []
    if skipped_include_false:
        note_parts.append(f"bỏ qua include_in_unit=False: {skipped_include_false}")
    if skipped_expected_zero:
        note_parts.append(f"bỏ qua expected_marks=0/thiếu toàn bộ target: {skipped_expected_zero}")
    if missing_target_warnings:
        sample = "; ".join(missing_target_warnings[:20])
        if len(missing_target_warnings) > 20:
            sample += f"; ... còn {len(missing_target_warnings) - 20} dòng"
        note_parts.append("mốc công chốt bị thiếu giờ target: " + sample)
    res.notes = " | ".join(note_parts)

    return res