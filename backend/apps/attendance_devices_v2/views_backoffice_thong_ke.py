from __future__ import annotations

from datetime import datetime, date as date_cls, time as dt_time, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect
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


def _parse_time(s: str) -> dt_time | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%H:%M").time()
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
    Đồng bộ với báo cáo:
    - DA_SUA: dùng override_* để tính trạng thái/lọc
    - THUC_TE: dùng actual_* để tính trạng thái/lọc
    """
    v = (raw or "").strip().upper()
    if v not in ("DA_SUA", "THUC_TE"):
        v = "DA_SUA"
    return v


def _chon_trang_thai(raw: str) -> str:
    """
    status filter từ báo cáo:
    ALL | CO_MAT | VANG | THIEU_MOC | VI_PHAM | YEU_CAU_SUA
    """
    v = (raw or "").strip().upper()
    if v not in ("", "ALL", "CO_MAT", "VANG", "THIEU_MOC", "VI_PHAM", "YEU_CAU_SUA"):
        v = "ALL"
    return v or "ALL"


def _resolve_date_range(request) -> tuple[date_cls, date_cls]:
    """
    Tương thích cả link cũ và link mới:
    - Link mới từ báo cáo: ?from=YYYY-MM-DD&to=YYYY-MM-DD
    - Link cũ: ?date=YYYY-MM-DD
    - Nếu không có gì: hôm nay
    """
    today = dj_timezone.localdate()
    date_single = _parse_date(request.GET.get("date"))
    from_date = _parse_date(request.GET.get("from"))
    to_date = _parse_date(request.GET.get("to"))

    if from_date or to_date:
        from_date = from_date or to_date or today
        to_date = to_date or from_date
    else:
        from_date = date_single or today
        to_date = date_single or today

    if from_date > to_date:
        from_date, to_date = to_date, from_date

    return from_date, to_date


def _build_local_datetime_from_time(work_date: date_cls, t: dt_time, *, next_day: bool) -> datetime:
    tz = dj_timezone.get_current_timezone()
    d = work_date + timedelta(days=1) if next_day else work_date
    naive = datetime.combine(d, t)
    return dj_timezone.make_aware(naive, tz)


def _is_next_day_for_out2(t: dt_time, gio_cat_qua_ngay: dt_time) -> bool:
    return t < gio_cat_qua_ngay


def _get_effective_dt(row: AttendanceDeviceMasterListV2, field: str, source: str):
    # field: in1/out1/in2/out2
    if source == "THUC_TE":
        return getattr(row, f"actual_{field}_local")
    return getattr(row, f"override_{field}_local")


def _missing_marks_by_source(row: AttendanceDeviceMasterListV2, source: str) -> int:
    """
    Không dùng row.missing_marks (vì có thể đã reset về 0 khi HR sửa).
    Tính thiếu mốc theo source giống báo cáo.
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


def _is_present_by_source(row: AttendanceDeviceMasterListV2, source: str) -> bool:
    """
    Có mặt = có ít nhất 1 mốc theo source, chỉ xét các mốc expected.
    """
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


def _compute_trang_thai_o_may(
    row: AttendanceDeviceMasterListV2,
    *,
    threshold_sec: int,
    source: str,
) -> dict:
    """
    Trạng thái để highlight các ô "Từ máy" (actual):
    - Nhưng việc tô highlight dựa trên TRẠNG THÁI theo `source`.
    - Cột hiển thị vẫn là actual.
    """
    status = {"in1": "", "out1": "", "in2": "", "out2": ""}

    if row.is_exempt or row.expected_marks <= 0:
        return status

    miss = _missing_marks_by_source(row, source)
    if miss > 0:
        if row.expected_in1 and _get_effective_dt(row, "in1", source) is None:
            status["in1"] = "THIEU"
        if row.expected_out1 and _get_effective_dt(row, "out1", source) is None:
            status["out1"] = "THIEU"
        if row.expected_in2 and _get_effective_dt(row, "in2", source) is None:
            status["in2"] = "THIEU"
        if row.expected_out2 and _get_effective_dt(row, "out2", source) is None:
            status["out2"] = "THIEU"
        return status

    def check_muon(target_dt, eff_dt):
        if target_dt and eff_dt:
            return int((eff_dt - target_dt).total_seconds()) > threshold_sec
        return False

    def check_som(target_dt, eff_dt):
        if target_dt and eff_dt:
            return int((eff_dt - target_dt).total_seconds()) < -threshold_sec
        return False

    if row.expected_in1 and check_muon(row.target_in1_local, _get_effective_dt(row, "in1", source)):
        status["in1"] = "MUON"
    if row.expected_in2 and check_muon(row.target_in2_local, _get_effective_dt(row, "in2", source)):
        status["in2"] = "MUON"

    if row.expected_out1 and check_som(row.target_out1_local, _get_effective_dt(row, "out1", source)):
        status["out1"] = "SOM"
    if row.expected_out2 and check_som(row.target_out2_local, _get_effective_dt(row, "out2", source)):
        status["out2"] = "SOM"

    return status


def _compute_late_early_seconds(row: AttendanceDeviceMasterListV2, *, source: str, threshold_sec: int) -> tuple[int, int]:
    """
    Trả về (muộn_seconds, sớm_seconds), đều là số dương.
    Chỉ tính khi đủ các mốc expected theo source.
    """
    if row.is_exempt or row.expected_marks <= 0:
        return 0, 0
    if _missing_marks_by_source(row, source) != 0:
        return 0, 0

    late_sec = 0
    early_sec = 0

    def add_late(target_dt, eff_dt):
        nonlocal late_sec
        if target_dt and eff_dt:
            delta = int((eff_dt - target_dt).total_seconds())
            if delta > threshold_sec:
                late_sec += delta

    def add_early(target_dt, eff_dt):
        nonlocal early_sec
        if target_dt and eff_dt:
            delta = int((eff_dt - target_dt).total_seconds())
            if delta < -threshold_sec:
                early_sec += -delta

    if row.expected_in1:
        add_late(row.target_in1_local, _get_effective_dt(row, "in1", source))
    if row.expected_in2:
        add_late(row.target_in2_local, _get_effective_dt(row, "in2", source))
    if row.expected_out1:
        add_early(row.target_out1_local, _get_effective_dt(row, "out1", source))
    if row.expected_out2:
        add_early(row.target_out2_local, _get_effective_dt(row, "out2", source))

    return late_sec, early_sec


def _has_violation_by_source(row: AttendanceDeviceMasterListV2, *, source: str, threshold_sec: int) -> bool:
    """
    Vi phạm = đủ các mốc expected theo source và có ít nhất một mốc:
    - IN đi muộn quá ngưỡng
    - OUT về sớm quá ngưỡng

    Không bắt buộc đủ 4 mốc; chỉ bắt buộc đủ các mốc expected của dòng đó.
    Vì vậy người làm nửa ngày vẫn được lọc VI_PHAM chính xác.
    """
    late_sec, early_sec = _compute_late_early_seconds(row, source=source, threshold_sec=threshold_sec)
    return late_sec > 0 or early_sec > 0


def _match_status_filter(
    row: AttendanceDeviceMasterListV2,
    *,
    source: str,
    status: str,
    threshold_sec: int,
) -> bool:
    """
    Lọc trạng thái chính xác theo source + expected_*.

    Quy ước đồng bộ với báo cáo:
    - CO_MAT: có ít nhất 1 mốc expected có dữ liệu theo source
    - VANG: không có mốc expected nào có dữ liệu theo source
    - THIEU_MOC: có mặt nhưng thiếu ít nhất 1 mốc expected
    - VI_PHAM: đủ mốc expected và có đi muộn/về sớm quá ngưỡng
    """
    if status in ("", "ALL"):
        return True

    if status == "CO_MAT":
        return _is_present_by_source(row, source)

    if status == "VANG":
        return not _is_present_by_source(row, source)

    if status == "THIEU_MOC":
        return _is_present_by_source(row, source) and _missing_marks_by_source(row, source) > 0

    if status == "VI_PHAM":
        return _has_violation_by_source(row, source=source, threshold_sec=threshold_sec)

    return True


def _row_status_label(row: AttendanceDeviceMasterListV2, *, source: str, threshold_sec: int) -> str:
    if not _is_present_by_source(row, source):
        return "Vắng"
    if _missing_marks_by_source(row, source) > 0:
        return "Thiếu mốc"
    if _has_violation_by_source(row, source=source, threshold_sec=threshold_sec):
        return "Vi phạm"
    return "Bình thường"


def _thong_ke_url(params: dict) -> str:
    return "/backoffice/attendance-devices-v2/thong-ke/?" + urlencode(params)


def _redirect_thong_ke_url(
    *,
    from_date: date_cls,
    to_date: date_cls,
    unit: str,
    q: str,
    nguong: str,
    source: str,
    status: str,
    page: str = "1",
    page_size: str = "100",
) -> str:
    params = {
        "from": f"{from_date:%Y-%m-%d}",
        "to": f"{to_date:%Y-%m-%d}",
        "unit": unit,
        "q": q,
        "nguong": nguong,
        "source": source,
        "status": status,
        "page": page,
        "page_size": page_size,
    }
    return _thong_ke_url(params)


@login_required
def thong_ke_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem thống kê chấm công"
        }, status=403)

    from_date, to_date = _resolve_date_range(request)
    is_range_mode = from_date != to_date
    allow_inline_edit = not is_range_mode
    work_date = from_date

    unit_raw = (request.GET.get("unit") or "").strip()
    q = (request.GET.get("q") or "").strip()

    nguong = _threshold_min(request.GET.get("nguong") or "5")
    threshold_sec = nguong * 60

    source = _chon_du_lieu(request.GET.get("source") or request.GET.get("chon_du_lieu") or "DA_SUA")
    status = _chon_trang_thai(request.GET.get("status") or "ALL")

    try:
        page = int(request.GET.get("page") or 1)
    except Exception:
        page = 1
    if page < 1:
        page = 1

    try:
        page_size = int(request.GET.get("page_size") or 100)
    except Exception:
        page_size = 100
    if page_size not in (50, 100, 200):
        page_size = 100

    qs = AttendanceDeviceMasterListV2.objects.select_related("employee", "unit").filter(
        work_date__gte=from_date,
        work_date__lte=to_date,
        expected_marks__gt=0,
    )

    if unit_raw.isdigit():
        qs = qs.filter(unit_id=int(unit_raw))

    if q:
        qs = qs.filter(
            Q(employee__full_name__icontains=q) |
            Q(employee__card_id__icontains=q) |
            Q(employee__employee_code__icontains=q)
        )

    if status == "YEU_CAU_SUA":
        qs = qs.filter(yeu_cau_sua_trang_thai__in=[
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DA_YEU_CAU,
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DANG_XU_LY,
        ])

    qs = qs.order_by("work_date", "unit_id", "employee__full_name", "employee_id")

    # Các trạng thái CO_MAT/VANG/THIEU_MOC/VI_PHAM phải lọc theo expected_* từng dòng.
    # Nếu lọc SQL đơn giản theo 4 cột actual/override sẽ sai với ca nửa ngày/chỉ sáng/chỉ chiều.
    # Với quy mô ~1000 người/ngày, 1 tháng ~30k dòng: lọc Python trước paginate vẫn phù hợp
    # và giúp paginator.count đúng với số dòng thực sự khớp bộ lọc.
    if status in ("CO_MAT", "VANG", "THIEU_MOC", "VI_PHAM"):
        object_list = [
            r for r in qs
            if _match_status_filter(r, source=source, status=status, threshold_sec=threshold_sec)
        ]
        paginator = Paginator(object_list, page_size)
    else:
        paginator = Paginator(qs, page_size)

    page_obj = paginator.get_page(page)

    rows = []
    for r in page_obj.object_list:
        late_sec, early_sec = _compute_late_early_seconds(r, source=source, threshold_sec=threshold_sec)
        open_day_url = _thong_ke_url({
            "from": f"{r.work_date:%Y-%m-%d}",
            "to": f"{r.work_date:%Y-%m-%d}",
            "unit": unit_raw,
            "q": q,
            "nguong": nguong,
            "source": source,
            "status": status,
            "page_size": page_size,
            "page": 1,
        })
        rows.append({
            "obj": r,
            "trang_thai_o_may": _compute_trang_thai_o_may(
                r,
                threshold_sec=threshold_sec,
                source=source,
            ),
            "is_present": _is_present_by_source(r, source),
            "missing_marks_by_source": _missing_marks_by_source(r, source),
            "is_violation": late_sec > 0 or early_sec > 0,
            "late_min": int(late_sec // 60),
            "early_min": int(early_sec // 60),
            "status_label": _row_status_label(r, source=source, threshold_sec=threshold_sec),
            "open_day_url": open_day_url,
        })

    units = OrgUnit.objects.filter(is_attendance_unit=True).order_by("symbol")
    co_quyen_sua = request.user.has_perm("attendance_devices_v2.change_attendancedevicemasterlistv2")

    return render(request, "backoffice/attendance_devices_v2/thong_ke.html", {
        "work_date": work_date.strftime("%Y-%m-%d"),  # giữ tương thích template/POST cũ
        "from_date": from_date.strftime("%Y-%m-%d"),
        "to_date": to_date.strftime("%Y-%m-%d"),
        "is_range_mode": is_range_mode,
        "allow_inline_edit": allow_inline_edit,
        "unit": unit_raw,
        "q": q,
        "nguong": nguong,
        "page_size": page_size,
        "rows": rows,
        "units": units,
        "co_quyen_sua": co_quyen_sua,
        "page_obj": page_obj,
        "paginator": paginator,
        "source": source,
        "status": status,
    })


@login_required
def luu_du_lieu_view(request):
    if request.method != "POST":
        return redirect("attendance_devices_v2:thong_ke")

    if not request.user.has_perm("attendance_devices_v2.change_attendancedevicemasterlistv2"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance_devices_v2.change_attendancedevicemasterlistv2",
            "title": "Bạn chưa được cấp quyền lưu dữ liệu đã sửa"
        }, status=403)

    # Lưu inline chỉ dành cho chế độ 1 ngày.
    work_date = _parse_date(request.POST.get("date")) or _parse_date(request.POST.get("from")) or dj_timezone.localdate()
    from_date = _parse_date(request.POST.get("from")) or work_date
    to_date = _parse_date(request.POST.get("to")) or work_date
    if from_date != to_date:
        messages.error(request, "Chế độ khoảng ngày chỉ dùng để xem. Muốn sửa dữ liệu, hãy mở đúng ngày cần xử lý.")
        return redirect(_redirect_thong_ke_url(
            from_date=from_date,
            to_date=to_date,
            unit=(request.POST.get("unit") or "").strip(),
            q=(request.POST.get("q") or "").strip(),
            nguong=(request.POST.get("nguong") or "5").strip(),
            source=_chon_du_lieu(request.POST.get("source") or request.POST.get("chon_du_lieu") or "DA_SUA"),
            status=_chon_trang_thai(request.POST.get("status") or "ALL"),
            page=(request.POST.get("page") or "1").strip(),
            page_size=(request.POST.get("page_size") or "100").strip(),
        ))

    unit_raw = (request.POST.get("unit") or "").strip()
    q = (request.POST.get("q") or "").strip()
    nguong = (request.POST.get("nguong") or "5").strip()

    source = _chon_du_lieu(request.POST.get("source") or request.POST.get("chon_du_lieu") or "DA_SUA")
    status = _chon_trang_thai(request.POST.get("status") or "ALL")

    page = (request.POST.get("page") or "1").strip()
    page_size = (request.POST.get("page_size") or "100").strip()

    gio_cat_qua_ngay = dt_time(4, 0)

    row_ids = request.POST.getlist("row_ids")
    row_ids = [int(x) for x in row_ids if (x or "").isdigit()]
    if not row_ids:
        messages.info(request, "Không có dòng nào để lưu.")
        return redirect(_redirect_thong_ke_url(
            from_date=work_date,
            to_date=work_date,
            unit=unit_raw,
            q=q,
            nguong=nguong,
            source=source,
            status=status,
            page=page,
            page_size=page_size,
        ))

    qs = AttendanceDeviceMasterListV2.objects.filter(id__in=row_ids, work_date=work_date)

    now = dj_timezone.now()
    updated = 0

    for row in qs:
        prefix = f"row_{row.id}_"

        in1_t = _parse_time(request.POST.get(prefix + "override_in1"))
        out1_t = _parse_time(request.POST.get(prefix + "override_out1"))
        in2_t = _parse_time(request.POST.get(prefix + "override_in2"))
        out2_t = _parse_time(request.POST.get(prefix + "override_out2"))

        new_in1 = _build_local_datetime_from_time(work_date, in1_t, next_day=False) if in1_t else None
        new_out1 = _build_local_datetime_from_time(work_date, out1_t, next_day=False) if out1_t else None
        new_in2 = _build_local_datetime_from_time(work_date, in2_t, next_day=False) if in2_t else None

        if out2_t:
            next_day = _is_next_day_for_out2(out2_t, gio_cat_qua_ngay)
            new_out2 = _build_local_datetime_from_time(work_date, out2_t, next_day=next_day)
        else:
            new_out2 = None

        note = (request.POST.get(prefix + "override_note") or "").strip()

        changed = False
        if row.override_in1_local != new_in1:
            row.override_in1_local = new_in1
            changed = True
        if row.override_out1_local != new_out1:
            row.override_out1_local = new_out1
            changed = True
        if row.override_in2_local != new_in2:
            row.override_in2_local = new_in2
            changed = True
        if row.override_out2_local != new_out2:
            row.override_out2_local = new_out2
            changed = True
        if row.override_note != note:
            row.override_note = note
            changed = True

        if changed:
            row.override_by = request.user
            row.override_at = now

            if row.yeu_cau_sua_trang_thai in (
                AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DA_YEU_CAU,
                AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DANG_XU_LY,
            ):
                row.yeu_cau_sua_trang_thai = AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DA_XU_LY
                row.yeu_cau_sua_xu_ly_boi = request.user
                row.yeu_cau_sua_xu_ly_luc = now

            row.save(update_fields=[
                "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
                "override_note", "override_by", "override_at",
                "yeu_cau_sua_trang_thai", "yeu_cau_sua_xu_ly_boi", "yeu_cau_sua_xu_ly_luc",
            ])
            updated += 1

    messages.success(request, f"Đã lưu dữ liệu: {updated} dòng thay đổi.")
    return redirect(_redirect_thong_ke_url(
        from_date=work_date,
        to_date=work_date,
        unit=unit_raw,
        q=q,
        nguong=nguong,
        source=source,
        status=status,
        page=page,
        page_size=page_size,
    ))


@login_required
def tao_yeu_cau_sua_view(request):
    if request.method != "POST":
        return redirect("attendance_devices_v2:thong_ke")

    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền tạo yêu cầu sửa"
        }, status=403)

    row_id = (request.POST.get("row_id") or "").strip()
    noi_dung = (request.POST.get("noi_dung") or "").strip()
    next_url = (request.POST.get("next") or "").strip() or "/"

    if not row_id.isdigit():
        messages.error(request, "Thiếu dòng dữ liệu (row_id).")
        return redirect(next_url)

    if not noi_dung:
        messages.error(request, "Bạn cần nhập nội dung yêu cầu sửa.")
        return redirect(next_url)

    row = AttendanceDeviceMasterListV2.objects.filter(id=int(row_id)).first()
    if not row:
        messages.error(request, "Không tìm thấy dòng dữ liệu.")
        return redirect(next_url)

    row.yeu_cau_sua_trang_thai = AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DA_YEU_CAU
    row.yeu_cau_sua_noi_dung = noi_dung
    row.yeu_cau_sua_tao_boi = request.user
    row.yeu_cau_sua_tao_luc = dj_timezone.now()
    row.save(update_fields=[
        "yeu_cau_sua_trang_thai",
        "yeu_cau_sua_noi_dung",
        "yeu_cau_sua_tao_boi",
        "yeu_cau_sua_tao_luc",
    ])

    messages.success(request, "Đã gửi yêu cầu sửa.")
    return redirect(next_url)
