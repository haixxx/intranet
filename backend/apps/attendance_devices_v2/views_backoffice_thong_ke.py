from __future__ import annotations

from datetime import datetime, date as date_cls, time as dt_time, timedelta

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
    - Cột hiển thị vẫn là actual (theo lựa chọn #1).
    """
    status = {"in1": "", "out1": "", "in2": "", "out2": ""}

    if row.is_exempt or row.expected_marks <= 0:
        return status

    # Thiếu mốc theo source: tô đỏ những ô actual bị thiếu tương ứng (hiển thị máy)
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

    # Đủ mốc theo source: tính muộn/sớm theo effective_dt so với target
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


@login_required
def thong_ke_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem thống kê chấm công"
        }, status=403)

    work_date = _parse_date(request.GET.get("date")) or dj_timezone.localdate()
    unit_raw = (request.GET.get("unit") or "").strip()
    q = (request.GET.get("q") or "").strip()

    nguong = _threshold_min(request.GET.get("nguong") or "5")
    threshold_sec = nguong * 60

    # Nhận cả source (mới) lẫn chon_du_lieu (cũ) cho tương thích
    source = _chon_du_lieu(request.GET.get("source") or request.GET.get("chon_du_lieu") or "DA_SUA")
    status = _chon_trang_thai(request.GET.get("status") or "ALL")

    # Phân trang (chặn page <= 0 để tránh EmptyPage)
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
        work_date=work_date,
        expected_marks__gt=0,
    )

    if unit_raw.isdigit():
        qs = qs.filter(unit_id=int(unit_raw))

    if q:
        qs = qs.filter(
            Q(employee__full_name__icontains=q) |
            Q(employee__card_id__icontains=q)
        )

    # status filter (lọc theo source)
    if status == "YEU_CAU_SUA":
        qs = qs.filter(yeu_cau_sua_trang_thai__in=[
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DA_YEU_CAU,
            AttendanceDeviceMasterListV2.YeuCauSuaTrangThai.DANG_XU_LY,
        ])
    elif status in ("CO_MAT", "VANG", "THIEU_MOC", "VI_PHAM"):
        # lọc bằng python sau paginate sẽ sai (mất bản ghi), nên ta lọc trước:
        # -> dùng Q conditions theo fields để lọc thô:
        #
        # present_by_source: any expected mark has effective_dt not null
        # missing_by_source: any expected mark has effective_dt null
        # violation_by_source: đủ mốc + (late or early)
        #
        # Vì expected flags là boolean từng row, filter SQL "any expected" sẽ hơi dài.
        # Ta làm xấp xỉ an toàn bằng cách:
        # - CO_MAT: effective any not null (dựa trên actual/override fields)
        # - VANG: all effective null (4 fields null)
        # - THIEU_MOC: any effective null AND any effective not null (để loại VANG) OR (any effective null with expected marks>0)
        #   -> vì expected flags khác nhau, cách này gần đúng; phần chính xác vẫn là tô màu + người dùng xem.
        #
        # Để chính xác 100% theo expected flags, cần annotate theo expected_*; sẽ làm phase sau nếu cần.
        if source == "THUC_TE":
            f_in1, f_out1, f_in2, f_out2 = "actual_in1_local", "actual_out1_local", "actual_in2_local", "actual_out2_local"
        else:
            f_in1, f_out1, f_in2, f_out2 = "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local"

        any_present = Q(**{f"{f_in1}__isnull": False}) | Q(**{f"{f_out1}__isnull": False}) | Q(**{f"{f_in2}__isnull": False}) | Q(**{f"{f_out2}__isnull": False})
        all_missing = Q(**{f"{f_in1}__isnull": True}) & Q(**{f"{f_out1}__isnull": True}) & Q(**{f"{f_in2}__isnull": True}) & Q(**{f"{f_out2}__isnull": True})
        any_missing = Q(**{f"{f_in1}__isnull": True}) | Q(**{f"{f_out1}__isnull": True}) | Q(**{f"{f_in2}__isnull": True}) | Q(**{f"{f_out2}__isnull": True})

        if status == "CO_MAT":
            qs = qs.filter(any_present)
        elif status == "VANG":
            qs = qs.filter(all_missing)
        elif status == "THIEU_MOC":
            qs = qs.filter(any_missing).exclude(all_missing)
        elif status == "VI_PHAM":
            # Vi phạm cần "đủ mốc theo source" + muộn/sớm.
            # Ở SQL khó chuẩn theo expected flags, nên ta lọc thô "có đủ 4 mốc" để giảm tập,
            # rồi check chính xác bằng python khi build rows (vẫn đúng).
            qs = qs.filter(
                Q(**{f"{f_in1}__isnull": False}),
                Q(**{f"{f_out1}__isnull": False}),
                Q(**{f"{f_in2}__isnull": False}),
                Q(**{f"{f_out2}__isnull": False}),
            )

    qs = qs.order_by("unit_id", "employee__full_name")

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    rows = []
    for r in page_obj.object_list:
        trang_thai_o_may = _compute_trang_thai_o_may(r, threshold_sec=threshold_sec, source=source)

        # Nếu status=VI_PHAM, cần lọc chính xác 100% bằng python (để tránh false positive do expected flags)
        if status == "VI_PHAM":
            miss = _missing_marks_by_source(r, source)
            if miss != 0:
                continue
            # compute violation
            vio = False
            if trang_thai_o_may["in1"] == "MUON" or trang_thai_o_may["in2"] == "MUON" or trang_thai_o_may["out1"] == "SOM" or trang_thai_o_may["out2"] == "SOM":
                vio = True
            if not vio:
                continue

        rows.append({
            "obj": r,
            "trang_thai_o_may": trang_thai_o_may,
        })

    units = OrgUnit.objects.filter(is_attendance_unit=True).order_by("symbol")
    co_quyen_sua = request.user.has_perm("attendance_devices_v2.change_attendancedevicemasterlistv2")

    return render(request, "backoffice/attendance_devices_v2/thong_ke.html", {
        "work_date": work_date.strftime("%Y-%m-%d"),
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

    work_date = _parse_date(request.POST.get("date")) or dj_timezone.localdate()
    unit_raw = (request.POST.get("unit") or "").strip()
    q = (request.POST.get("q") or "").strip()
    nguong = (request.POST.get("nguong") or "5").strip()

    # gi��� lại filter mới để redirect không mất state
    source = _chon_du_lieu(request.POST.get("source") or request.POST.get("chon_du_lieu") or "DA_SUA")
    status = _chon_trang_thai(request.POST.get("status") or "ALL")

    page = (request.POST.get("page") or "1").strip()
    page_size = (request.POST.get("page_size") or "100").strip()

    gio_cat_qua_ngay = dt_time(4, 0)

    row_ids = request.POST.getlist("row_ids")
    row_ids = [int(x) for x in row_ids if (x or "").isdigit()]
    if not row_ids:
        messages.info(request, "Không có dòng nào để lưu.")
        return redirect(
            f"/backoffice/attendance-devices-v2/thong-ke/"
            f"?date={work_date:%Y-%m-%d}&unit={unit_raw}&q={q}&nguong={nguong}&source={source}&status={status}&page={page}&page_size={page_size}"
        )

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
    return redirect(
        f"/backoffice/attendance-devices-v2/thong-ke/"
        f"?date={work_date:%Y-%m-%d}&unit={unit_raw}&q={q}&nguong={nguong}&source={source}&status={status}&page={page}&page_size={page_size}"
    )


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