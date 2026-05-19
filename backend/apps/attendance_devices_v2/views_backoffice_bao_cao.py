from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date as date_cls, timedelta
from math import ceil

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone as dj_timezone

from apps.organization.models import OrgUnit

from .models_master_list import AttendanceDeviceMasterListV2


def _parse_date(s: str) -> date_cls | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _threshold_min(raw: str) -> int:
    try:
        v = int(raw)
    except Exception:
        v = 5
    if v not in (5, 10, 15):
        v = 5
    return v


def _chon_du_lieu(raw: str) -> str:
    """
    - DA_SUA: dùng giờ đã sửa (override)
    - THUC_TE: dùng giờ thực tế từ máy (actual)
    """
    v = (raw or "").strip().upper()
    if v not in ("DA_SUA", "THUC_TE"):
        v = "DA_SUA"
    return v


def _safe_int(s: str, default: int = 1) -> int:
    try:
        v = int(s)
        return v if v > 0 else default
    except Exception:
        return default


def _get_effective_dt(row: AttendanceDeviceMasterListV2, field: str, source: str):
    if source == "THUC_TE":
        return getattr(row, f"actual_{field}_local")
    return getattr(row, f"override_{field}_local")


def _is_present(row: AttendanceDeviceMasterListV2, source: str) -> bool:
    if row.is_exempt or row.expected_marks <= 0:
        return False

    checks = []
    if row.expected_in1:
        checks.append(_get_effective_dt(row, "in1", source))
    if row.expected_out1:
        checks.append(_get_effective_dt(row, "out1", source))
    if row.expected_in2:
        checks.append(_get_effective_dt(row, "in2", source))
    if row.expected_out2:
        checks.append(_get_effective_dt(row, "out2", source))

    return any(x is not None for x in checks)


def _missing_marks_by_source(row: AttendanceDeviceMasterListV2, source: str) -> int:
    """
    ĐÃ CHỐT:
    - THUC_TE: thiếu mốc theo actual
    - DA_SUA: thiếu mốc theo override
    Không dùng row.missing_marks
    """
    if row.is_exempt or row.expected_marks <= 0:
        return 0

    missing = 0
    if row.expected_in1 and _get_effective_dt(row, "in1", source) is None:
        missing += 1
    if row.expected_out1 and _get_effective_dt(row, "out1", source) is None:
        missing += 1
    if row.expected_in2 and _get_effective_dt(row, "in2", source) is None:
        missing += 1
    if row.expected_out2 and _get_effective_dt(row, "out2", source) is None:
        missing += 1
    return missing


def _compute_late_early_seconds(row: AttendanceDeviceMasterListV2, source: str, threshold_sec: int) -> tuple[int, int]:
    """
    Trả về (muộn_seconds, sớm_seconds) (đều là số dương)
    Chỉ tính khi đủ mốc theo source.
    """
    if row.is_exempt or row.expected_marks <= 0:
        return 0, 0

    if _missing_marks_by_source(row, source) != 0:
        return 0, 0

    muon_sec = 0
    som_sec = 0

    def add_muon(target_attr: str, eff_field: str):
        nonlocal muon_sec
        target = getattr(row, target_attr)
        eff = _get_effective_dt(row, eff_field, source)
        if target and eff:
            delta = int((eff - target).total_seconds())
            if delta > threshold_sec:
                muon_sec += delta

    def add_som(target_attr: str, eff_field: str):
        nonlocal som_sec
        target = getattr(row, target_attr)
        eff = _get_effective_dt(row, eff_field, source)
        if target and eff:
            delta = int((eff - target).total_seconds())
            if delta < -threshold_sec:
                som_sec += (-delta)

    if row.expected_in1:
        add_muon("target_in1_local", "in1")
    if row.expected_in2:
        add_muon("target_in2_local", "in2")

    if row.expected_out1:
        add_som("target_out1_local", "out1")
    if row.expected_out2:
        add_som("target_out2_local", "out2")

    return muon_sec, som_sec


def _pct(n: int, d: int) -> float:
    if not d:
        return 0.0
    return (n / d) * 100.0


def _pct1(n: int, d: int) -> float:
    if not d:
        return 0.0
    return round((n / d) * 100.0, 1)


def _daterange(from_date: date_cls, to_date: date_cls):
    d = from_date
    while d <= to_date:
        yield d
        d += timedelta(days=1)


@dataclass
class StatusCounters:
    absent: int = 0
    missing: int = 0
    violation: int = 0
    normal: int = 0


def _status_bucket(row: AttendanceDeviceMasterListV2, source: str, threshold_sec: int) -> str:
    if not _is_present(row, source):
        return "ABSENT"
    if _missing_marks_by_source(row, source) > 0:
        return "MISSING"
    muon_sec, som_sec = _compute_late_early_seconds(row, source, threshold_sec)
    if muon_sec > 0 or som_sec > 0:
        return "VIOLATION"
    return "NORMAL"


def _rate_per_100(numer: float, denom: float) -> float:
    if denom <= 0:
        return 0.0
    return round((numer / denom) * 100.0, 2)


@login_required
def bao_cao_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(
            request,
            "backoffice/no_permission.html",
            {"perm_codename": "attendance.view_attendancecommit", "title": "Bạn chưa được cấp quyền xem báo cáo"},
            status=403,
        )

    today = dj_timezone.localdate()
    from_date = _parse_date(request.GET.get("from")) or today
    to_date = _parse_date(request.GET.get("to")) or today
    if from_date > to_date:
        from_date = to_date

    unit_raw = (request.GET.get("unit") or "").strip()
    source = _chon_du_lieu(request.GET.get("chon_du_lieu") or "DA_SUA")
    threshold_min = _threshold_min(request.GET.get("nguong") or "5")
    threshold_sec = threshold_min * 60

    is_daily_mode = (from_date == to_date)
    units = OrgUnit.objects.filter(is_attendance_unit=True).order_by("symbol")
    unit_id: int | None = int(unit_raw) if unit_raw.isdigit() else None

    # Base: expected_marks>0 ~ is_work=True (theo compute)
    base = AttendanceDeviceMasterListV2.objects.filter(
        work_date__gte=from_date,
        work_date__lte=to_date,
        expected_marks__gt=0,
        is_exempt=False,
    ).select_related("employee", "unit")

    if unit_id is not None:
        base = base.filter(unit_id=unit_id)

    # HR: việc cần làm
    qs_yeu_cau = AttendanceDeviceMasterListV2.objects.filter(
        expected_marks__gt=0,
        is_exempt=False,
        yeu_cau_sua_trang_thai__in=[
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DA_YEU_CAU,
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DANG_XU_LY,
        ],
    )
    if unit_id is not None:
        qs_yeu_cau = qs_yeu_cau.filter(unit_id=unit_id)

    viec_can_lam = list(
        qs_yeu_cau.values("unit_id", "unit__symbol", "unit__name", "yeu_cau_sua_trang_thai")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:20]
    )

    # KPI mẫu số = tổng lượt (person-day)
    total_rows = base.count()
    day_count = (to_date - from_date).days + 1
    avg_per_day = round((total_rows / day_count), 1) if day_count > 0 else 0.0

    present = 0
    absent = 0
    missing = 0
    violation = 0
    normal = 0

    late = 0
    early = 0
    total_late_sec = 0
    total_early_sec = 0

    # incidents daily
    incidents_all: list[dict] = []

    # Aggregations for top/rate (denom = tổng lượt đăng ký)
    unit_total_rows: dict[int, int] = {}
    unit_violation_minutes: dict[int, int] = {}
    unit_missing_rows: dict[int, int] = {}

    emp_total_rows: dict[int, int] = {}
    emp_violation_minutes: dict[int, int] = {}

    rows_iter = base.only(
        "id",
        "work_date",
        "expected_in1", "expected_out1", "expected_in2", "expected_out2", "expected_marks",
        "target_in1_local", "target_out1_local", "target_in2_local", "target_out2_local",
        "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local",
        "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
        "employee__id", "employee__employee_code", "employee__full_name",
        "unit__id", "unit__symbol", "unit__name",
    )

    for r in rows_iter:
        is_present = _is_present(r, source)
        miss = _missing_marks_by_source(r, source)
        muon_sec, som_sec = _compute_late_early_seconds(r, source, threshold_sec)

        vio_min = int((muon_sec + som_sec) // 60)
        late_min = int(muon_sec // 60) if muon_sec > 0 else 0
        early_min = int(som_sec // 60) if som_sec > 0 else 0

        if is_present:
            present += 1
        else:
            absent += 1

        if miss > 0:
            missing += 1

        b = _status_bucket(r, source, threshold_sec)
        if b == "VIOLATION":
            violation += 1
        elif b == "NORMAL":
            normal += 1

        if muon_sec > 0:
            late += 1
            total_late_sec += muon_sec
        if som_sec > 0:
            early += 1
            total_early_sec += som_sec

        # incidents for daily
        if is_daily_mode and (miss > 0 or vio_min > 0):
            incidents_all.append({
                "employee_code": getattr(r.employee, "employee_code", ""),
                "employee_name": getattr(r.employee, "full_name", ""),
                "unit_symbol": getattr(r.unit, "symbol", ""),
                "unit_name": getattr(r.unit, "name", ""),
                "missing_marks": miss,
                "late_min": late_min,
                "early_min": early_min,
                "violation_min": vio_min,
                "suggest_status": "THIEU_MOC" if miss > 0 else "VI_PHAM",
            })

        # top aggregations (ngày & khoảng đều tính được)
        uid = r.unit_id
        unit_total_rows[uid] = unit_total_rows.get(uid, 0) + 1
        if miss > 0:
            unit_missing_rows[uid] = unit_missing_rows.get(uid, 0) + 1
        # phút vi phạm chỉ cộng khi đủ mốc
        if miss == 0 and vio_min > 0:
            unit_violation_minutes[uid] = unit_violation_minutes.get(uid, 0) + vio_min

        eid = r.employee_id
        emp_total_rows[eid] = emp_total_rows.get(eid, 0) + 1
        if miss == 0 and vio_min > 0:
            emp_violation_minutes[eid] = emp_violation_minutes.get(eid, 0) + vio_min

    kpi = {
        "tong_luot_dang_ky": total_rows,
        "so_ngay": day_count,
        "trung_binh_luot_moi_ngay": avg_per_day,

        "so_luot_co_mat": present,
        "so_luot_vang": absent,
        "so_luot_thieu_moc": missing,
        "so_luot_vi_pham": violation,
        "so_luot_binh_thuong": normal,

        "so_luot_di_muon": late,
        "so_luot_ve_som": early,
        "tong_phut_di_muon": int(total_late_sec // 60),
        "tong_phut_ve_som": int(total_early_sec // 60),
        "tong_phut_vi_pham": int((total_late_sec + total_early_sec) // 60),

        "yeu_cau_sua_dang_mo": qs_yeu_cau.count(),

        "pct_co_mat": _pct(present, total_rows),
        "pct_vang": _pct(absent, total_rows),
        "pct_thieu_moc": _pct(missing, total_rows),
        "pct_vi_pham": _pct(violation, total_rows),
    }

    donut = {"absent": absent, "missing": missing, "violation": violation, "normal": normal}

    # Range daily stacked 100% (chỉ khi range để đỡ tốn)
    daily_series = []
    if not is_daily_mode:
        for d in _daterange(from_date, to_date):
            day_qs = AttendanceDeviceMasterListV2.objects.filter(
                work_date=d,
                expected_marks__gt=0,
                is_exempt=False,
            )
            if unit_id is not None:
                day_qs = day_qs.filter(unit_id=unit_id)

            denom = day_qs.count()
            c = StatusCounters()
            for rr in day_qs.only(
                "expected_in1", "expected_out1", "expected_in2", "expected_out2", "expected_marks",
                "target_in1_local", "target_out1_local", "target_in2_local", "target_out2_local",
                "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local",
                "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
                "is_exempt",
            ):
                bb = _status_bucket(rr, source, threshold_sec)
                if bb == "ABSENT":
                    c.absent += 1
                elif bb == "MISSING":
                    c.missing += 1
                elif bb == "VIOLATION":
                    c.violation += 1
                else:
                    c.normal += 1

            daily_series.append({
                "date": d.strftime("%Y-%m-%d"),
                "normal_pct": _pct1(c.normal, denom),
                "violation_pct": _pct1(c.violation, denom),
                "missing_pct": _pct1(c.missing, denom),
                "absent_pct": _pct1(c.absent, denom),
            })

    # ===== Top 5 blocks (ngày & khoảng đều áp dụng) =====

    # Top 5 units by violation rate (minutes/100 rows)
    top_units_vio = []
    if unit_total_rows:
        unit_meta = {u.id: (u.symbol, u.name) for u in OrgUnit.objects.filter(id__in=list(unit_total_rows.keys()))}
        for uid, denom in unit_total_rows.items():
            minutes = unit_violation_minutes.get(uid, 0)
            rate = _rate_per_100(minutes, denom)
            sym, name = unit_meta.get(uid, ("", ""))
            top_units_vio.append({
                "unit_id": uid,
                "unit_symbol": sym,
                "unit_name": name,
                "rate": rate,
                "violation_minutes": minutes,
                "total_rows": denom,
            })
        top_units_vio.sort(key=lambda x: (x["rate"], x["violation_minutes"]), reverse=True)
        top_units_vio = top_units_vio[:5]

    # Top 5 employees by violation rate (minutes/100 rows) - always show (option 1)
    top_employees_vio = []
    if emp_total_rows:
        EmployeeModel = AttendanceDeviceMasterListV2._meta.get_field("employee").remote_field.model
        emp_ids = list(emp_total_rows.keys())
        emp_meta = {
            e.id: (e.employee_code, e.full_name)
            for e in EmployeeModel.objects.filter(id__in=emp_ids).only("id", "employee_code", "full_name")
        }
        for eid, denom in emp_total_rows.items():
            minutes = emp_violation_minutes.get(eid, 0)
            rate = _rate_per_100(minutes, denom)
            code, name = emp_meta.get(eid, ("", ""))
            top_employees_vio.append({
                "employee_id": eid,
                "employee_code": code,
                "employee_name": name,
                "rate": rate,
                "violation_minutes": minutes,
                "total_rows": denom,
            })
        top_employees_vio.sort(key=lambda x: (x["rate"], x["violation_minutes"]), reverse=True)
        top_employees_vio = top_employees_vio[:5]

    # Top 5 units missing marks by rate (% rows missing)
    top_units_missing = []
    if unit_total_rows:
        unit_meta2 = {u.id: (u.symbol, u.name) for u in OrgUnit.objects.filter(id__in=list(unit_total_rows.keys()))}
        for uid, denom in unit_total_rows.items():
            miss_rows = unit_missing_rows.get(uid, 0)
            miss_rate = _pct1(miss_rows, denom)
            sym, name = unit_meta2.get(uid, ("", ""))
            top_units_missing.append({
                "unit_id": uid,
                "unit_symbol": sym,
                "unit_name": name,
                "rate": miss_rate,  # %
                "missing_rows": miss_rows,
                "total_rows": denom,
            })
        top_units_missing.sort(key=lambda x: (x["rate"], x["missing_rows"]), reverse=True)
        top_units_missing = top_units_missing[:5]

    # Paginate daily incidents (10 rows/page)
    inc_page_size = 10
    inc_page = _safe_int(request.GET.get("inc_page") or "1", 1)
    inc_total = len(incidents_all)
    inc_pages = max(1, int(ceil(inc_total / inc_page_size))) if inc_total else 1
    if inc_page > inc_pages:
        inc_page = inc_pages
    start = (inc_page - 1) * inc_page_size
    end = start + inc_page_size
    incidents_page = incidents_all[start:end]

    chart_payload = {"donut": donut, "daily_series": daily_series}

    drill_date = to_date.strftime("%Y-%m-%d")
    base_thong_ke_url = f"/backoffice/attendance-devices-v2/thong-ke/?date={drill_date}&unit={unit_raw}&nguong={threshold_min}&source={source}"

    return render(request, "backoffice/attendance_devices_v2/bao_cao.html", {
        "from_date": from_date.strftime("%Y-%m-%d"),
        "to_date": to_date.strftime("%Y-%m-%d"),
        "is_daily_mode": is_daily_mode,
        "unit": unit_raw,
        "chon_du_lieu": source,
        "nguong": threshold_min,
        "units": units,

        "kpi": kpi,
        "chart_payload": chart_payload,

        "incidents": incidents_page,
        "inc_page": inc_page,
        "inc_pages": inc_pages,
        "inc_total": inc_total,

        "top_units_vio": top_units_vio,
        "top_employees_vio": top_employees_vio,
        "top_units_missing": top_units_missing,

        "viec_can_lam": viec_can_lam,
        "base_thong_ke_url": base_thong_ke_url,
    })