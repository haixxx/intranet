from __future__ import annotations

from datetime import datetime, date as date_cls, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
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
    - DA_SUA: dùng giờ đã sửa (override) (mặc định)
    - THUC_TE: dùng giờ thực tế từ máy (actual)
    """
    v = (raw or "").strip().upper()
    if v not in ("DA_SUA", "THUC_TE"):
        v = "DA_SUA"
    return v


def _get_effective_dt(row: AttendanceDeviceMasterListV2, field: str, chon_du_lieu: str):
    if chon_du_lieu == "THUC_TE":
        return getattr(row, f"actual_{field}_local")
    return getattr(row, f"override_{field}_local")


def _is_present(row: AttendanceDeviceMasterListV2, chon_du_lieu: str) -> bool:
    """
    Có mặt = có ít nhất 1 lần chấm trong ngày theo dữ liệu chọn.
    Chỉ xét các mốc expected.
    """
    if row.is_exempt or row.expected_marks <= 0:
        return False

    checks = []
    if row.expected_in1:
        checks.append(_get_effective_dt(row, "in1", chon_du_lieu))
    if row.expected_out1:
        checks.append(_get_effective_dt(row, "out1", chon_du_lieu))
    if row.expected_in2:
        checks.append(_get_effective_dt(row, "in2", chon_du_lieu))
    if row.expected_out2:
        checks.append(_get_effective_dt(row, "out2", chon_du_lieu))

    return any(x is not None for x in checks)


def _compute_late_early_seconds(row: AttendanceDeviceMasterListV2, chon_du_lieu: str, threshold_sec: int) -> tuple[int, int]:
    """
    Trả về (muon_seconds, som_seconds)

    Rule:
    - Chỉ tính nếu đủ mốc (missing_marks == 0) và không exempt.
    - Tính cả IN2 và OUT1.
    """
    if row.is_exempt or row.expected_marks <= 0:
        return 0, 0
    if row.missing_marks != 0:
        return 0, 0

    muon_sec = 0
    som_sec = 0

    def add_muon(target_attr: str, eff_field: str):
        nonlocal muon_sec
        target = getattr(row, target_attr)
        eff = _get_effective_dt(row, eff_field, chon_du_lieu)
        if target and eff:
            delta = int((eff - target).total_seconds())
            if delta > threshold_sec:
                muon_sec += delta

    def add_som(target_attr: str, eff_field: str):
        nonlocal som_sec
        target = getattr(row, target_attr)
        eff = _get_effective_dt(row, eff_field, chon_du_lieu)
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


@login_required
def bao_cao_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem báo cáo"
        }, status=403)

    today = dj_timezone.localdate()

    from_date = _parse_date(request.GET.get("from")) or today
    to_date = _parse_date(request.GET.get("to")) or today
    if from_date > to_date:
        from_date = to_date

    unit_raw = (request.GET.get("unit") or "").strip()
    chon_du_lieu = _chon_du_lieu(request.GET.get("chon_du_lieu") or "DA_SUA")
    threshold_min = _threshold_min(request.GET.get("nguong") or "5")
    threshold_sec = threshold_min * 60

    units = OrgUnit.objects.filter(is_attendance_unit=True).order_by("symbol")

    base = AttendanceDeviceMasterListV2.objects.filter(
        work_date__gte=from_date,
        work_date__lte=to_date,
        expected_marks__gt=0,
        is_exempt=False,
    )
    if unit_raw.isdigit():
        base = base.filter(unit_id=int(unit_raw))

    headcount = base.count()

    present_people = 0
    missing_people = 0
    late_people = 0
    early_people = 0
    total_late_sec = 0
    total_early_sec = 0
    present_but_missing = 0

    for r in base.only(
        "id",
        "work_date",
        "expected_in1", "expected_out1", "expected_in2", "expected_out2", "expected_marks",
        "is_exempt", "missing_marks",
        "target_in1_local", "target_out1_local", "target_in2_local", "target_out2_local",
        "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local",
        "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
    ):
        is_present = _is_present(r, chon_du_lieu)
        if is_present:
            present_people += 1

        if r.missing_marks > 0:
            missing_people += 1
            if is_present:
                present_but_missing += 1
            continue

        muon_sec, som_sec = _compute_late_early_seconds(r, chon_du_lieu, threshold_sec)
        if muon_sec > 0:
            late_people += 1
            total_late_sec += muon_sec
        if som_sec > 0:
            early_people += 1
            total_early_sec += som_sec

    kpi = {
        "tong_quan_so": headcount,
        "so_nguoi_co_mat": present_people,
        "so_nguoi_khong_co_mat": max(headcount - present_people, 0),
        "so_nguoi_thieu_moc": missing_people,
        "so_nguoi_co_mat_nhung_thieu_moc": present_but_missing,
        "so_nguoi_di_muon": late_people,
        "so_nguoi_ve_som": early_people,
        "tong_phut_di_muon": int(total_late_sec // 60),
        "tong_phut_ve_som": int(total_early_sec // 60),
        "tong_phut_vi_pham": int((total_late_sec + total_early_sec) // 60),
        "ty_le_du_moc": _pct(max(headcount - missing_people, 0), headcount),

        "pct_co_mat": _pct(present_people, headcount),
        "pct_khong_co_mat": _pct(max(headcount - present_people, 0), headcount),
        "pct_thieu_moc": _pct(missing_people, headcount),
        "pct_di_muon": _pct(late_people, headcount),
        "pct_ve_som": _pct(early_people, headcount),
    }

    # Việc HR cần làm: từ trước đến nay
    qs_yeu_cau = AttendanceDeviceMasterListV2.objects.filter(
        expected_marks__gt=0,
        is_exempt=False,
        yeu_cau_sua_trang_thai__in=[
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DA_YEU_CAU,
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DANG_XU_LY,
        ],
    )
    if unit_raw.isdigit():
        qs_yeu_cau = qs_yeu_cau.filter(unit_id=int(unit_raw))

    kpi["yeu_cau_sua_dang_mo"] = qs_yeu_cau.count()

    viec_can_lam = list(
        qs_yeu_cau
        .values("unit_id", "unit__symbol", "unit__name", "yeu_cau_sua_trang_thai")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:20]
    )

    # Top 5 đơn vị muộn/sớm
    by_unit = (
        AttendanceDeviceMasterListV2.objects
        .filter(
            work_date__gte=from_date,
            work_date__lte=to_date,
            expected_marks__gt=0,
            is_exempt=False,
        )
        .values("unit_id", "unit__symbol", "unit__name")
        .annotate(ok_people=Count("id", filter=Q(missing_marks=0)))
    )
    if unit_raw.isdigit():
        by_unit = by_unit.filter(unit_id=int(unit_raw))

    top_late = []
    top_early = []
    for u in by_unit:
        unit_id = u["unit_id"]
        ok_people = u["ok_people"] or 0
        if ok_people == 0:
            continue

        rows_ok = AttendanceDeviceMasterListV2.objects.filter(
            work_date__gte=from_date, work_date__lte=to_date,
            unit_id=unit_id,
            expected_marks__gt=0, is_exempt=False,
            missing_marks=0,
        ).only(
            "expected_in1", "expected_out1", "expected_in2", "expected_out2",
            "missing_marks",
            "target_in1_local", "target_out1_local", "target_in2_local", "target_out2_local",
            "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local",
            "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
        )

        late_cnt = 0
        early_cnt = 0
        for r in rows_ok:
            muon_sec, som_sec = _compute_late_early_seconds(r, chon_du_lieu, threshold_sec)
            if muon_sec > 0:
                late_cnt += 1
            if som_sec > 0:
                early_cnt += 1

        top_late.append({
            "unit_id": unit_id,
            "unit_symbol": u["unit__symbol"],
            "unit_name": u["unit__name"],
            "ok_people": ok_people,
            "late_people": late_cnt,
            "late_rate": _pct(late_cnt, ok_people),
        })
        top_early.append({
            "unit_id": unit_id,
            "unit_symbol": u["unit__symbol"],
            "unit_name": u["unit__name"],
            "ok_people": ok_people,
            "early_people": early_cnt,
            "early_rate": _pct(early_cnt, ok_people),
        })

    top_late.sort(key=lambda x: x["late_rate"], reverse=True)
    top_early.sort(key=lambda x: x["early_rate"], reverse=True)
    top_late = top_late[:5]
    top_early = top_early[:5]

    # Daily % chart (list dict python, KHÔNG json.dumps)
    daily = []
    for d in _daterange(from_date, to_date):
        daily_qs = AttendanceDeviceMasterListV2.objects.filter(
            work_date=d,
            expected_marks__gt=0,
            is_exempt=False,
        )
        if unit_raw.isdigit():
            daily_qs = daily_qs.filter(unit_id=int(unit_raw))

        day_headcount = daily_qs.count()

        day_present = 0
        day_missing = 0
        day_late = 0
        day_early = 0

        for r in daily_qs.only(
            "expected_in1", "expected_out1", "expected_in2", "expected_out2", "expected_marks",
            "is_exempt", "missing_marks",
            "target_in1_local", "target_out1_local", "target_in2_local", "target_out2_local",
            "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local",
            "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
        ):
            if _is_present(r, chon_du_lieu):
                day_present += 1

            if r.missing_marks > 0:
                day_missing += 1
                continue

            muon_sec, som_sec = _compute_late_early_seconds(r, chon_du_lieu, threshold_sec)
            if muon_sec > 0:
                day_late += 1
            if som_sec > 0:
                day_early += 1

        daily.append({
            "date": d.strftime("%Y-%m-%d"),
            "headcount": day_headcount,
            "present_pct": _pct1(day_present, day_headcount),
            "missing_pct": _pct1(day_missing, day_headcount),
            "late_pct": _pct1(day_late, day_headcount),
            "early_pct": _pct1(day_early, day_headcount),
        })

    # KPI chart (dict python, KHÔNG json.dumps)
    kpi_chart = {
        "so_nguoi_co_mat": kpi["so_nguoi_co_mat"],
        "so_nguoi_khong_co_mat": kpi["so_nguoi_khong_co_mat"],
    }

    return render(request, "backoffice/attendance_devices_v2/bao_cao.html", {
        "from_date": from_date.strftime("%Y-%m-%d"),
        "to_date": to_date.strftime("%Y-%m-%d"),
        "unit": unit_raw,
        "chon_du_lieu": chon_du_lieu,
        "nguong": threshold_min,
        "units": units,
        "kpi": kpi,
        "kpi_chart": kpi_chart,
        "top_late": top_late,
        "top_early": top_early,
        "viec_can_lam": viec_can_lam,
        "daily": daily,
    })