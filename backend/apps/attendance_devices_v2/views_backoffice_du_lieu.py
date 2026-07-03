from __future__ import annotations

import io
from datetime import datetime, date as date_cls, time as dt_time, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone as dj_timezone

from apps.hr.models import Employee
from apps.organization.models import OrgUnit
from apps.backoffice.services.access_scope import get_allowed_attendance_units, unit_in_attendance_scope

from apps.attendance.models_batch import AttendanceCommit
from apps.attendance.services_bs import build_expected_roster

from .models_manual_punch import AttendanceManualPunch
from .models_master_list import AttendanceDeviceMasterListV2
from .services_master_list_compute import compute_master_list_for_unit_date


OUT2_NEXT_DAY_CUTOFF = dt_time(4, 0)
# Khoảng xem/xóa dữ liệu nhập tay phải bao phủ ca 3: 22:00-06:00 hôm sau.
MANUAL_OVERNIGHT_END_CUTOFF = dt_time(8, 0)
MAX_IMPORT_ERRORS_SHOWN = 30

MANUAL_SOURCE_MAY_HONG = "MAY_HONG"
MANUAL_SOURCE_SUA_DU_LIEU = "SUA_DU_LIEU"
MANUAL_SOURCE_CHOICES = (
    (MANUAL_SOURCE_MAY_HONG, "Bổ sung do máy hỏng/mất log"),
    (MANUAL_SOURCE_SUA_DU_LIEU, "Bổ sung sửa dữ liệu"),
)
MANUAL_SOURCE_LABELS = dict(MANUAL_SOURCE_CHOICES)



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


def _parse_excel_date(value) -> date_cls | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    if isinstance(value, (int, float)):
        # Excel serial date. 1899-12-30 is the epoch used by openpyxl/from_excel behavior.
        # Ví dụ 46162 -> 2026-05-20.
        try:
            return (datetime(1899, 12, 30) + timedelta(days=int(value))).date()
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    # Nếu người dùng paste serial date thành chuỗi, vẫn cố parse.
    if s.isdigit():
        try:
            return (datetime(1899, 12, 30) + timedelta(days=int(s))).date()
        except Exception:
            pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _parse_excel_time(value) -> dt_time | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, dt_time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, (int, float)):
        # Excel time as fraction of a day, e.g. 0.5 = 12:00.
        if 0 <= float(value) < 1:
            total_minutes = int(round(float(value) * 24 * 60))
            total_minutes %= 24 * 60
            return dt_time(total_minutes // 60, total_minutes % 60)
        return None
    s = str(value).strip()
    if not s:
        return None
    # Cho phép nhập 700, 0700, 7:00, 07:00
    if s.isdigit() and len(s) in (3, 4):
        s = s.zfill(4)
        s = f"{s[:2]}:{s[2:]}"
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            return datetime.strptime(s, fmt).time().replace(second=0, microsecond=0)
        except Exception:
            pass
    return None


def _is_next_day_for_out2(t: dt_time, gio_cat_qua_ngay: dt_time) -> bool:
    """
    OUT2 ca đêm có thể qua ngày. Quy ước giống màn thống kê:
    nếu giờ OUT2 nhỏ hơn 04:00 thì hiểu là ngày hôm sau.
    """
    return t < gio_cat_qua_ngay


def _build_local_datetime_from_time(work_date: date_cls, t: dt_time, *, next_day: bool = False) -> datetime:
    tz = dj_timezone.get_current_timezone()
    d = work_date + timedelta(days=1) if next_day else work_date
    naive = datetime.combine(d, t)
    return dj_timezone.make_aware(naive, tz)


def _manual_window_for_work_date(work_date: date_cls) -> tuple[datetime, datetime]:
    """
    Khoảng hiển thị/xóa dữ liệu nhập tay cho một ngày công.

    Mở rộng tới 08:00 ngày hôm sau để bao phủ ca 3 dạng IN1=22:00, OUT1=06:00.
    Trước đây chỉ mở tới 04:00 nên mốc OUT1=05:47 của L3 dễ bị hiểu sai ngày.
    """
    start_of_day = _build_local_datetime_from_time(work_date, dt_time(0, 0), next_day=False)
    overnight_end_next_day = _build_local_datetime_from_time(
        work_date + timedelta(days=1),
        MANUAL_OVERNIGHT_END_CUTOFF,
        next_day=False,
    )
    return start_of_day, overnight_end_next_day


def _manual_note_field(note: str) -> str:
    raw = (note or "").strip().upper()
    for field in ("IN1", "OUT1", "IN2", "OUT2"):
        if raw.startswith(field):
            return field
    return ""


def _infer_work_date_from_manual_punch(punch: AttendanceManualPunch) -> date_cls:
    """
    Suy ra ngày công từ mốc nhập tay.

    Chỉ mốc OUT qua ngày mới được lùi về ngày công hôm trước. IN1=05:47 của L1
    vẫn là ngày hiện tại, nhưng OUT1=05:47 của L3 phải thuộc ngày công hôm trước.
    """
    local_dt = dj_timezone.localtime(punch.thoi_gian_local)
    field = _manual_note_field(punch.ghi_chu)
    if field in ("OUT1", "OUT2") and local_dt.time() < MANUAL_OVERNIGHT_END_CUTOFF:
        return local_dt.date() - timedelta(days=1)
    return local_dt.date()


def _redirect_url(
    *,
    request,
    work_date: date_cls,
    unit: str,
    q: str,
    employee_id: str = "",
) -> str:
    params = {
        "date": f"{work_date:%Y-%m-%d}",
        "unit": unit,
        "q": q,
    }
    if employee_id:
        params["employee_id"] = employee_id
    return request.path + "?" + urlencode(params)


def _them_du_lieu_url(*, work_date: date_cls, unit: str, q: str = "", employee_id: str = "") -> str:
    params = {
        "date": f"{work_date:%Y-%m-%d}",
        "unit": unit,
        "q": q,
    }
    if employee_id:
        params["employee_id"] = employee_id
    return reverse("attendance_devices_v2:them_du_lieu") + "?" + urlencode(params)


def _thong_ke_day_url(*, work_date: date_cls, unit: str, source: str = "DA_SUA", status: str = "ALL") -> str:
    params = {
        "from": f"{work_date:%Y-%m-%d}",
        "to": f"{work_date:%Y-%m-%d}",
        "unit": unit,
        "source": source,
        "status": status,
        "page_size": "100",
    }
    return reverse("attendance_devices_v2:thong_ke") + "?" + urlencode(params)


def _recompute_unit_date(*, unit_id: int, work_date: date_cls, reason: str) -> str:
    compute_run_id = f"manual-{reason}-{work_date:%Y%m%d}-{unit_id}-{uuid4().hex[:8]}"
    res = compute_master_list_for_unit_date(
        unit_id=unit_id,
        work_date=work_date,
        compute_run_id=compute_run_id,
        compute_version=1,
    )
    if res.master_rows_upserted > 0:
        return f"Đã tính lại MasterList: {res.master_rows_upserted} dòng."
    return f"Chưa cập nhật MasterList: {res.notes}"


def _recompute_many(unit_date_pairs: set[tuple[int, date_cls]], *, reason: str) -> tuple[int, list[str]]:
    ok = 0
    notes: list[str] = []
    for unit_id, work_date in sorted(unit_date_pairs, key=lambda x: (x[1], x[0])):
        try:
            notes.append(_recompute_unit_date(unit_id=unit_id, work_date=work_date, reason=reason))
            ok += 1
        except Exception as exc:
            notes.append(f"{work_date:%Y-%m-%d}/unit {unit_id}: lỗi tính lại MasterList: {exc}")
    return ok, notes


def _normalize_manual_source(raw: str) -> str:
    v = (raw or "").strip().upper()
    if v not in MANUAL_SOURCE_LABELS:
        return MANUAL_SOURCE_MAY_HONG
    return v


def _base_note(*, source_type: str, ly_do: str = "", ghi_chu: str = "") -> str:
    """
    Ghi chú có cấu trúc để compute phân biệt:
    - SOURCE:MAY_HONG -> tham gia actual như dữ liệu thay thế máy
    - SOURCE:SUA_DU_LIEU -> không vào actual, ghi đè override
    """
    source_type = _normalize_manual_source(source_type)
    note_parts = [f"SOURCE:{source_type}"]
    if ly_do:
        note_parts.append(f"Lý do: {ly_do}")
    if ghi_chu:
        note_parts.append(f"Ghi chú: {ghi_chu}")
    return " | ".join(note_parts)


def _dt_is_next_day_for_work_date(work_date: date_cls, value: datetime | None) -> bool:
    if not value:
        return False
    return dj_timezone.localtime(value).date() > work_date


def _commit_item_for_manual_context(*, emp: Employee, unit_id: int | None, work_date: date_cls):
    if not unit_id:
        return None
    commit = AttendanceCommit.objects.filter(unit_id=unit_id, work_date=work_date).first()
    if not commit:
        return None
    return commit.items.filter(employee=emp).select_related("code").first()


def _commit_pair_is_next_day(item, field: str) -> bool:
    if field == "OUT1":
        in_t = getattr(item, "registered_in1_snapshot", None) or getattr(item, "in1", None)
        out_t = getattr(item, "registered_out1_snapshot", None) or getattr(item, "out1", None)
    elif field == "OUT2":
        in_t = getattr(item, "registered_in2_snapshot", None) or getattr(item, "in2", None)
        out_t = getattr(item, "registered_out2_snapshot", None) or getattr(item, "out2", None)
    else:
        return False
    return bool(in_t and out_t and out_t <= in_t)


def _manual_field_should_be_next_day(
    *,
    emp: Employee,
    unit_id: int | None,
    work_date: date_cls,
    field: str,
    t: dt_time,
) -> bool:
    """
    Xác định mốc nhập tay có thuộc ngày hôm sau không.

    Không dùng quy tắc cứng "chỉ OUT2 trước 04:00" nữa vì L3 đang dùng OUT1=06:00.
    Ưu tiên target đã compute; nếu chưa có MasterList thì dùng snapshot/cặp giờ trong công chốt.
    """
    if field not in ("OUT1", "OUT2"):
        return False

    if unit_id:
        master = AttendanceDeviceMasterListV2.objects.filter(
            employee=emp,
            unit_id=unit_id,
            work_date=work_date,
        ).first()
        if master:
            target = getattr(master, f"target_{field.lower()}_local", None)
            if target:
                return _dt_is_next_day_for_work_date(work_date, target)

    item = _commit_item_for_manual_context(emp=emp, unit_id=unit_id, work_date=work_date)
    if item:
        return _commit_pair_is_next_day(item, field)

    # Fallback chỉ dùng khi chưa có công chốt/target: mốc OUT rất sớm có khả năng là ca qua ngày.
    # Quy tắc chính xác vẫn là công chốt/snapshot ở trên.
    return t < MANUAL_OVERNIGHT_END_CUTOFF


def _save_manual_punch(
    *,
    emp: Employee,
    work_date: date_cls,
    field: str,
    t: dt_time,
    base_note: str,
    user,
    unit_id: int | None = None,
) -> tuple[int, int]:
    """Ghi đè 1 mốc nhập tay cũ rồi tạo mốc mới. Trả về (created, replaced)."""
    start_of_day = _build_local_datetime_from_time(work_date, dt_time(0, 0), next_day=False)
    start_next_day = _build_local_datetime_from_time(work_date + timedelta(days=1), dt_time(0, 0), next_day=False)
    overnight_end_next_day = _build_local_datetime_from_time(
        work_date + timedelta(days=1),
        MANUAL_OVERNIGHT_END_CUTOFF,
        next_day=False,
    )

    # OUT1/OUT2 có thể qua ngày. Dùng khoảng rộng để xóa cả dữ liệu cũ từng bị lưu sai
    # cùng ngày và dữ liệu đúng ở sáng hôm sau. IN1/IN2 vẫn chỉ xóa trong ngày công.
    old_end = overnight_end_next_day if field in ("OUT1", "OUT2") else start_next_day
    old_qs = AttendanceManualPunch.objects.filter(
        employee=emp,
        ghi_chu__startswith=field,
        thoi_gian_local__gte=start_of_day,
        thoi_gian_local__lt=old_end,
    )

    old_count = old_qs.count()
    if old_count:
        old_qs.delete()

    next_day = _manual_field_should_be_next_day(
        emp=emp,
        unit_id=unit_id,
        work_date=work_date,
        field=field,
        t=t,
    )
    local_dt = _build_local_datetime_from_time(work_date, t, next_day=next_day)
    utc_dt = local_dt.astimezone(timezone.utc)

    note = f"{field}"
    if base_note:
        note += f" | {base_note}"

    AttendanceManualPunch.objects.create(
        employee=emp,
        thoi_gian_local=local_dt,
        thoi_gian_utc=utc_dt,
        ghi_chu=note,
        tao_boi=user,
    )
    return 1, old_count





def _scope_employee_label(emp: Employee) -> str:
    code = getattr(emp, "employee_code", "") or ""
    name = getattr(emp, "full_name", "") or ""
    return f"{code} - {name}".strip(" -")


def _manual_scope_for_unit_date(*, unit_id: int | None, work_date: date_cls) -> dict:
    """
    Xác định danh sách nhân sự được phép nhập dữ liệu chấm công bổ sung cho một
    ngày/đơn vị.

    Nguyên tắc nghiệp vụ:
    - Nếu đã có công chốt: lấy theo AttendanceCommitItem của đơn vị/ngày đó.
      Chỉ cho nhập với dòng include_in_unit=True, gồm người thường và BS đến.
      Dòng BS đi/include_in_unit=False thuộc đơn vị gốc nhưng không nhập giờ ở
      đơn vị gốc vì đơn vị gốc không biết người đó làm gì tại đơn vị nhận.
    - Nếu chưa có công chốt: dựng danh sách dự kiến từ điều động hiệu lực qua
      build_expected_roster().
    """
    empty = {
        "unit": None,
        "source": "NO_UNIT",
        "source_label": "Chưa chọn đơn vị",
        "commit": None,
        "commit_exists": False,
        "allowed_ids": set(),
        "allowed_notes": {},
        "blocked": [],
    }
    if not unit_id:
        return empty

    unit = OrgUnit.objects.filter(id=unit_id).first()
    if not unit:
        return empty

    scope = {
        **empty,
        "unit": unit,
        "source": "ROSTER",
        "source_label": "Theo điều động/danh sách dự kiến",
    }

    commit = (
        AttendanceCommit.objects.filter(unit_id=unit_id, work_date=work_date)
        .select_related("unit")
        .prefetch_related("items__employee", "items__employee__unit", "items__bs_peer_unit", "items__code")
        .first()
    )
    if commit:
        scope["source"] = "COMMIT"
        scope["source_label"] = "Theo công chốt"
        scope["commit"] = commit
        scope["commit_exists"] = True

        for item in commit.items.all():
            emp = item.employee
            if not emp:
                continue
            direction = str(getattr(item, "bs_direction", "NONE") or "NONE")
            peer = getattr(item, "bs_peer_unit", None)
            peer_symbol = getattr(peer, "symbol", "") or ""

            if bool(getattr(item, "include_in_unit", True)):
                scope["allowed_ids"].add(emp.id)
                if direction == "IN":
                    scope["allowed_notes"][emp.id] = f"BS đến từ {peer_symbol}" if peer_symbol else "BS đến"
                else:
                    scope["allowed_notes"].setdefault(emp.id, "")
            else:
                scope["blocked"].append({
                    "employee": emp,
                    "reason": f"BS đi sang {peer_symbol}" if peer_symbol else "BS đi",
                    "peer_unit": peer,
                    "source": "COMMIT",
                })
        return scope

    entries = build_expected_roster(unit, work_date)
    peer_unit_ids = {e.bs_peer_unit_id for e in entries if e.bs_peer_unit_id}
    peer_map = {u.id: u for u in OrgUnit.objects.filter(id__in=peer_unit_ids)}
    emp_map = {e.id: e for e in Employee.objects.filter(id__in=[x.employee_id for x in entries]).select_related("unit", "team")}

    for entry in entries:
        emp = emp_map.get(entry.employee_id)
        if not emp:
            continue
        direction = str(entry.bs_direction or "NONE")
        peer = peer_map.get(entry.bs_peer_unit_id)
        peer_symbol = getattr(peer, "symbol", "") or ""
        if entry.include_in_unit:
            scope["allowed_ids"].add(emp.id)
            if direction == "IN":
                scope["allowed_notes"][emp.id] = f"BS đến từ {peer_symbol}" if peer_symbol else "BS đến"
            else:
                scope["allowed_notes"].setdefault(emp.id, "")
        else:
            scope["blocked"].append({
                "employee": emp,
                "reason": f"BS đi sang {peer_symbol}" if peer_symbol else "BS đi",
                "peer_unit": peer,
                "source": "ROSTER",
            })

    return scope


def _manual_scope_error_labels(employee_ids: list[int], allowed_ids: set[int]) -> list[str]:
    invalid_ids = [eid for eid in employee_ids if eid not in allowed_ids]
    if not invalid_ids:
        return []
    employees = Employee.objects.filter(id__in=invalid_ids).order_by("employee_code", "full_name")
    return [_scope_employee_label(emp) for emp in employees]


def _commit_exists(*, unit_id: int | None, work_date: date_cls) -> bool:
    if not unit_id:
        return False
    return AttendanceCommit.objects.filter(unit_id=unit_id, work_date=work_date).exists()


def _master_exists(*, employee_id: int, unit_id: int | None, work_date: date_cls) -> bool:
    if not unit_id:
        return False
    return AttendanceDeviceMasterListV2.objects.filter(
        employee_id=employee_id,
        unit_id=unit_id,
        work_date=work_date,
    ).exists()


def _manual_punch_compute_status(punch: AttendanceManualPunch, *, unit_id: int | None = None) -> dict:
    """
    Trạng thái hiển thị cho từng mốc nhập bổ sung.

    Lưu ý: AttendanceManualPunch hiện chưa lưu unit, nên với người điều động đến
    phải kiểm tra trạng thái theo đơn vị đang lọc, không dùng employee.unit gốc.
    """
    work_date = _infer_work_date_from_manual_punch(punch)
    effective_unit_id = unit_id or getattr(punch.employee, "unit_id", None)
    if not _commit_exists(unit_id=effective_unit_id, work_date=work_date):
        return {
            "code": "CHO_CONG_CHOT",
            "label": "Chờ công chốt",
            "badge": "status-cho-cong-chot",
            "work_date": work_date,
        }
    if _master_exists(employee_id=punch.employee_id, unit_id=effective_unit_id, work_date=work_date):
        return {
            "code": "DA_TINH",
            "label": "Đã tính",
            "badge": "status-da-tinh",
            "work_date": work_date,
        }
    return {
        "code": "CHUA_TINH",
        "label": "Chưa tính",
        "badge": "status-chua-tinh",
        "work_date": work_date,
    }


def _warn_if_missing_commit(request, unit_date_pairs: set[tuple[int, date_cls]]) -> None:
    missing = []
    for unit_id, work_date in sorted(unit_date_pairs, key=lambda x: (x[1], x[0])):
        if not _commit_exists(unit_id=unit_id, work_date=work_date):
            missing.append((unit_id, work_date))
    if missing:
        sample = ", ".join([f"unit {u}/{d:%Y-%m-%d}" for u, d in missing[:5]])
        more = f" và {len(missing) - 5} mục khác" if len(missing) > 5 else ""
        messages.warning(
            request,
            "Đã lưu dữ liệu bổ sung nhưng chưa có công chốt nên chưa tính được: " + sample + more + ".",
        )

def _handle_excel_import(request, *, today: date_cls):
    work_date_fallback = _parse_date(request.POST.get("date")) or today
    unit_raw = (request.POST.get("unit") or "").strip()
    q = (request.POST.get("q") or "").strip()
    recompute = (request.POST.get("excel_recompute") or "1").strip() == "1"
    source_type = _normalize_manual_source(request.POST.get("excel_source_type") or MANUAL_SOURCE_MAY_HONG)
    uploaded = request.FILES.get("excel_file")

    if not unit_raw.isdigit():
        messages.error(request, "Bạn cần chọn đơn vị trước khi import Excel để hệ thống kiểm tra đúng điều động/ngày công.")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))
    unit_id = int(unit_raw)
    if not unit_in_attendance_scope(request.user, unit_id):
        messages.error(request, "Bạn không có quyền nhập dữ liệu cho đơn vị này.")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))
    scope_cache: dict[date_cls, dict] = {}

    if not uploaded:
        messages.error(request, "Bạn cần chọn file Excel để import.")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))

    try:
        from openpyxl import load_workbook
    except Exception:
        messages.error(request, "Máy chủ chưa cài thư viện openpyxl. Cài: pip install openpyxl rồi thử lại.")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))

    try:
        wb = load_workbook(uploaded, data_only=True, read_only=True)
    except Exception as exc:
        messages.error(request, f"Không đọc được file Excel: {exc}")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))

    if "NhapDuLieu" in wb.sheetnames:
        ws = wb["NhapDuLieu"]
    else:
        ws = wb[wb.sheetnames[0]]

    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if not header_row:
        messages.error(request, "File Excel không có dòng tiêu đề.")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))

    headers = {str(v).strip().lower(): idx for idx, v in enumerate(header_row) if v not in (None, "")}
    required_any = {"ma_nhan_su", "ma_the"}
    required_headers = {"ngay", "in1", "out1", "in2", "out2"}
    missing = [h for h in required_headers if h not in headers]
    if not required_any.intersection(headers):
        missing.append("ma_nhan_su hoặc ma_the")
    if missing:
        messages.error(request, "File Excel thiếu cột: " + ", ".join(missing))
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))

    parsed_rows: list[dict] = []
    errors: list[str] = []

    def get(row, name: str):
        idx = headers.get(name)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    for excel_row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not any(v not in (None, "") for v in row):
            continue

        work_date = _parse_excel_date(get(row, "ngay"))
        ma_nv = str(get(row, "ma_nhan_su") or "").strip()
        ma_the = str(get(row, "ma_the") or "").strip()
        ly_do = str(get(row, "ly_do") or "").strip()
        ghi_chu = str(get(row, "ghi_chu") or "").strip()

        if not work_date:
            errors.append(f"Dòng {excel_row_no}: ngày không hợp lệ.")
            continue
        if not ma_nv and not ma_the:
            errors.append(f"Dòng {excel_row_no}: thiếu ma_nhan_su hoặc ma_the.")
            continue

        emp_qs = Employee.objects.all()
        if ma_nv:
            emp_qs = emp_qs.filter(employee_code=ma_nv)
        else:
            emp_qs = emp_qs.filter(card_id=ma_the)
        emp = emp_qs.first()
        if not emp:
            errors.append(f"Dòng {excel_row_no}: không tìm thấy nhân sự ma_nhan_su='{ma_nv}' ma_the='{ma_the}'.")
            continue
        if work_date not in scope_cache:
            scope_cache[work_date] = _manual_scope_for_unit_date(unit_id=unit_id, work_date=work_date)
        scope = scope_cache[work_date]
        if emp.id not in scope["allowed_ids"]:
            unit_label = getattr(scope.get("unit"), "symbol", unit_raw) or unit_raw
            errors.append(
                f"Dòng {excel_row_no}: nhân sự {emp.employee_code} không thuộc phạm vi nhập dữ liệu của đơn vị {unit_label} ngày {work_date:%Y-%m-%d}. "
                "Nếu là người đi bổ sung, đơn vị nhận mới nhập dữ liệu chấm công."
            )
            continue

        times = {
            "IN1": _parse_excel_time(get(row, "in1")),
            "OUT1": _parse_excel_time(get(row, "out1")),
            "IN2": _parse_excel_time(get(row, "in2")),
            "OUT2": _parse_excel_time(get(row, "out2")),
        }

        # Báo lỗi nếu ô giờ có giá trị nhưng không parse được.
        for col_name, field in (("in1", "IN1"), ("out1", "OUT1"), ("in2", "IN2"), ("out2", "OUT2")):
            raw_val = get(row, col_name)
            if raw_val not in (None, "") and times[field] is None:
                errors.append(f"Dòng {excel_row_no}: cột {col_name} không đúng định dạng giờ HH:MM.")

        if not any(times.values()):
            errors.append(f"Dòng {excel_row_no}: chưa nhập mốc giờ nào.")
            continue

        parsed_rows.append({
            "row_no": excel_row_no,
            "employee": emp,
            "work_date": work_date,
            "times": times,
            "base_note": _base_note(source_type=source_type, ly_do=ly_do, ghi_chu=ghi_chu),
        })

    if errors:
        for err in errors[:MAX_IMPORT_ERRORS_SHOWN]:
            messages.error(request, err)
        if len(errors) > MAX_IMPORT_ERRORS_SHOWN:
            messages.error(request, f"Còn {len(errors) - MAX_IMPORT_ERRORS_SHOWN} lỗi khác. Hãy sửa file rồi import lại.")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))

    if not parsed_rows:
        messages.info(request, "File Excel không có dòng dữ liệu hợp lệ để import.")
        return redirect(_them_du_lieu_url(work_date=work_date_fallback, unit=unit_raw, q=q))

    created = 0
    replaced = 0
    affected_unit_dates: set[tuple[int, date_cls]] = set()
    with transaction.atomic():
        for item in parsed_rows:
            emp = item["employee"]
            work_date = item["work_date"]
            for field, t in item["times"].items():
                if not t:
                    continue
                c, r = _save_manual_punch(
                    emp=emp,
                    work_date=work_date,
                    field=field,
                    t=t,
                    base_note=item["base_note"],
                    user=request.user,
                    unit_id=unit_id,
                )
                created += c
                replaced += r
            affected_unit_dates.add((unit_id, work_date))

    _warn_if_missing_commit(request, affected_unit_dates)

    compute_text = ""
    if recompute and affected_unit_dates:
        ok, notes = _recompute_many(affected_unit_dates, reason="excel")
        compute_text = f" Đã tính lại {ok} ngày/đơn vị."
        failed_notes = [n for n in notes if "lỗi" in n.lower()]
        if failed_notes:
            compute_text += " Một số lỗi: " + " | ".join(failed_notes[:3])

    messages.success(
        request,
        f"Đã import {created} mốc từ Excel ({MANUAL_SOURCE_LABELS[source_type]}) cho {len(parsed_rows)} dòng dữ liệu. Đã ghi đè {replaced} mốc cũ.{compute_text}"
    )

    # Nếu file chỉ có một ngày, quay về ngày đó; nếu nhiều ngày thì giữ ngày đang lọc.
    distinct_dates = sorted({item["work_date"] for item in parsed_rows})
    redirect_date = distinct_dates[0] if len(distinct_dates) == 1 else work_date_fallback
    redirect_unit = unit_raw
    if not redirect_unit and len(affected_unit_dates) == 1:
        redirect_unit = str(next(iter(affected_unit_dates))[0])
    return redirect(_them_du_lieu_url(work_date=redirect_date, unit=redirect_unit, q=q))


@login_required
def them_du_lieu_view(request):
    """
    Nhập bổ sung dữ liệu chấm công khi:
    - máy chấm công hỏng/mất dữ liệu;
    - cần bổ sung dữ liệu của ngày trước;
    - nhập tay một hoặc nhiều nhân sự;
    - import Excel nhiều dòng.
    """
    if not request.user.has_perm("attendance_devices_v2.add_attendancemanualpunch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance_devices_v2.add_attendancemanualpunch",
            "title": "Bạn chưa được cấp quyền thêm dữ liệu chấm công"
        }, status=403)

    today = dj_timezone.localdate()

    if request.method == "POST" and (request.POST.get("action") or "") == "recompute_day":
        work_date = _parse_date(request.POST.get("date")) or today
        unit_raw = (request.POST.get("unit") or "").strip()
        q = (request.POST.get("q") or "").strip()
        if not unit_raw.isdigit():
            messages.error(request, "Bạn cần chọn đơn vị trước khi tính lại ngày/đơn vị.")
            return redirect(_them_du_lieu_url(work_date=work_date, unit=unit_raw, q=q))
        unit_id = int(unit_raw)
        if not unit_in_attendance_scope(request.user, unit_id):
            messages.error(request, "Bạn không có quyền tính lại dữ liệu đơn vị này.")
            return redirect(_them_du_lieu_url(work_date=work_date, unit=unit_raw, q=q))
        if not _commit_exists(unit_id=unit_id, work_date=work_date):
            messages.warning(request, "Ngày/đơn vị này chưa có công chốt nên chưa thể tính MasterList. Dữ liệu bổ sung vẫn được lưu và đang chờ công chốt.")
            return redirect(_them_du_lieu_url(work_date=work_date, unit=unit_raw, q=q))
        try:
            note = _recompute_unit_date(unit_id=unit_id, work_date=work_date, reason="manual-button")
            messages.success(request, "Đã tính lại ngày/đơn vị. " + note)
        except Exception as exc:
            messages.error(request, f"Tính lại MasterList bị lỗi: {exc}")
        return redirect(_them_du_lieu_url(work_date=work_date, unit=unit_raw, q=q))

    if request.method == "POST" and (request.POST.get("action") or "") == "import_excel":
        return _handle_excel_import(request, today=today)

    if request.method == "POST":
        work_date = _parse_date(request.POST.get("date")) or today
        unit_raw = (request.POST.get("unit") or "").strip()
        q = (request.POST.get("q") or "").strip()
        legacy_employee_id = (request.POST.get("employee_id") or "").strip()
        ly_do = (request.POST.get("ly_do") or "").strip()
        ghi_chu = (request.POST.get("ghi_chu") or "").strip()
        recompute = (request.POST.get("recompute") or "1").strip() == "1"
        source_type = _normalize_manual_source(request.POST.get("manual_source_type") or MANUAL_SOURCE_MAY_HONG)

        # Hỗ trợ cả bản cũ (employee_id) và bản mới (employee_ids nhiều người).
        raw_employee_ids = request.POST.getlist("employee_ids")
        if legacy_employee_id:
            raw_employee_ids.append(legacy_employee_id)

        employee_ids: list[int] = []
        for raw_id in raw_employee_ids:
            raw_id = (raw_id or "").strip()
            if not raw_id.isdigit():
                continue
            emp_id = int(raw_id)
            if emp_id not in employee_ids:
                employee_ids.append(emp_id)

        selected_employee_id = str(employee_ids[0]) if len(employee_ids) == 1 else ""

        if not unit_raw.isdigit():
            messages.error(request, "Bạn cần chọn đơn vị để hệ thống tính lại dữ liệu chấm công.")
            return redirect(_redirect_url(request=request, work_date=work_date, unit=unit_raw, q=q, employee_id=selected_employee_id))

        unit_id = int(unit_raw)
        if not unit_in_attendance_scope(request.user, unit_id):
            messages.error(request, "Bạn không có quyền nhập dữ liệu cho đơn vị này.")
            return redirect(_redirect_url(request=request, work_date=work_date, unit=unit_raw, q=q, employee_id=selected_employee_id))

        if not employee_ids:
            messages.error(request, "Bạn cần chọn ít nhất một nhân sự.")
            return redirect(_redirect_url(request=request, work_date=work_date, unit=unit_raw, q=q, employee_id=selected_employee_id))

        employees_qs = Employee.objects.filter(id__in=employee_ids).order_by("employee_code", "full_name")
        employees = list(employees_qs)
        if not employees:
            messages.error(request, "Không tìm thấy nhân sự.")
            return redirect(_redirect_url(request=request, work_date=work_date, unit=unit_raw, q=q, employee_id=selected_employee_id))

        missing_ids = sorted(set(employee_ids) - {e.id for e in employees})
        if missing_ids:
            messages.warning(request, f"Có {len(missing_ids)} nhân sự không tồn tại nên đã bỏ qua.")

        scope = _manual_scope_for_unit_date(unit_id=unit_id, work_date=work_date)
        invalid_labels = _manual_scope_error_labels([e.id for e in employees], scope["allowed_ids"])
        if invalid_labels:
            sample = ", ".join(invalid_labels[:5])
            more = f" và {len(invalid_labels) - 5} nhân sự khác" if len(invalid_labels) > 5 else ""
            messages.error(
                request,
                "Không thể nhập dữ liệu tại đơn vị đang chọn cho: " + sample + more +
                ". Danh sách nhập dữ liệu V2 được xác định theo công chốt hoặc điều động trong ngày; người đi bổ sung phải nhập tại đơn vị nhận."
            )
            return redirect(_redirect_url(request=request, work_date=work_date, unit=unit_raw, q=q, employee_id=selected_employee_id))

        times = {
            "IN1": _parse_time(request.POST.get("in1")),
            "OUT1": _parse_time(request.POST.get("out1")),
            "IN2": _parse_time(request.POST.get("in2")),
            "OUT2": _parse_time(request.POST.get("out2")),
        }

        if not any(times.values()):
            messages.error(request, "Bạn cần nhập ít nhất một mốc giờ.")
            return redirect(_redirect_url(request=request, work_date=work_date, unit=unit_raw, q=q, employee_id=selected_employee_id))

        created = 0
        replaced = 0
        base_note = _base_note(source_type=source_type, ly_do=ly_do, ghi_chu=ghi_chu)
        affected_unit_dates: set[tuple[int, date_cls]] = {(unit_id, work_date)}

        with transaction.atomic():
            for emp in employees:
                for field, t in times.items():
                    if not t:
                        continue
                    c, r = _save_manual_punch(
                        emp=emp,
                        work_date=work_date,
                        field=field,
                        t=t,
                        base_note=base_note,
                        user=request.user,
                        unit_id=unit_id,
                    )
                    created += c
                    replaced += r

        _warn_if_missing_commit(request, affected_unit_dates)

        compute_note = ""
        if recompute:
            try:
                compute_note = " " + _recompute_unit_date(unit_id=unit_id, work_date=work_date, reason="save")
            except Exception as exc:
                compute_note = f" Nhưng tính lại MasterList bị lỗi: {exc}"

        if len(employees) == 1:
            emp = employees[0]
            msg = f"Đã lưu {created} mốc chấm công bổ sung ({MANUAL_SOURCE_LABELS[source_type]}) cho {emp.employee_code} - {emp.full_name}."
        else:
            msg = f"Đã lưu {created} mốc chấm công bổ sung ({MANUAL_SOURCE_LABELS[source_type]}) cho {len(employees)} nhân sự."
        if replaced:
            msg += f" Đã ghi đè {replaced} mốc cũ."
        msg += compute_note
        messages.success(request, msg)

        # Sau khi nhập xong, mở thống kê ngày để kiểm tra kết quả.
        return redirect(_thong_ke_day_url(work_date=work_date, unit=unit_raw, source="DA_SUA", status="ALL"))

    # GET
    work_date = _parse_date(request.GET.get("date")) or today
    unit_raw = (request.GET.get("unit") or "").strip()
    q = (request.GET.get("q") or "").strip()
    selected_employee_id = (request.GET.get("employee_id") or "").strip()
    selected_employee_ids = [selected_employee_id] if selected_employee_id.isdigit() else []
    try:
        page = int(request.GET.get("page") or 1)
    except Exception:
        page = 1
    if page < 1:
        page = 1
    try:
        page_size = int(request.GET.get("page_size") or 50)
    except Exception:
        page_size = 50
    if page_size not in (25, 50, 100, 200):
        page_size = 50

    units = get_allowed_attendance_units(request.user)

    # Trang thêm dữ liệu bắt buộc thao tác theo một đơn vị cụ thể.
    # Nếu URL chưa truyền unit, mặc định chọn đơn vị chấm công đầu tiên để tránh trạng thái "Tất cả".
    if not unit_raw and units.exists():
        unit_raw = str(units.first().id)

    selected_unit_id = int(unit_raw) if unit_raw.isdigit() else None
    if selected_unit_id is not None and not unit_in_attendance_scope(request.user, selected_unit_id):
        selected_unit_id = None
        unit_raw = ""
    manual_scope = _manual_scope_for_unit_date(unit_id=selected_unit_id, work_date=work_date)
    allowed_employee_ids = manual_scope["allowed_ids"]

    window_start, window_end = _manual_window_for_work_date(work_date)
    rows = AttendanceManualPunch.objects.select_related("employee", "employee__unit", "tao_boi").filter(
        thoi_gian_local__gte=window_start,
        thoi_gian_local__lt=window_end,
    )

    if selected_unit_id is not None:
        if allowed_employee_ids:
            rows = rows.filter(employee_id__in=allowed_employee_ids)
        else:
            rows = rows.none()

    if q:
        rows = rows.filter(
            Q(employee__employee_code__icontains=q) |
            Q(employee__full_name__icontains=q) |
            Q(employee__card_id__icontains=q)
        )

    rows = rows.order_by("-tao_luc", "-id")
    paginator = Paginator(rows, page_size)
    page_obj = paginator.get_page(page)

    row_items = []
    for punch in page_obj.object_list:
        row_items.append({
            "obj": punch,
            "compute_status": _manual_punch_compute_status(punch, unit_id=selected_unit_id),
        })

    if selected_unit_id is not None and allowed_employee_ids:
        employees_qs = Employee.objects.filter(id__in=allowed_employee_ids)
    else:
        employees_qs = Employee.objects.none()
    if q:
        employees_qs = employees_qs.filter(
            Q(employee_code__icontains=q) |
            Q(full_name__icontains=q) |
            Q(card_id__icontains=q)
        )
    employees = list(employees_qs.select_related("unit", "team").order_by("employee_code", "full_name")[:2000])
    for emp in employees:
        emp.manual_scope_note = manual_scope["allowed_notes"].get(emp.id, "")

    selected_employee = None
    if selected_employee_id.isdigit():
        selected_employee = Employee.objects.filter(id=int(selected_employee_id)).first()

    thong_ke_url = _thong_ke_day_url(work_date=work_date, unit=unit_raw, source="DA_SUA", status="ALL")

    return render(request, "backoffice/attendance_devices_v2/them_du_lieu.html", {
        "work_date": work_date.strftime("%Y-%m-%d"),
        "unit": unit_raw,
        "q": q,
        "units": units,
        "employees": employees,
        "selected_employee_id": selected_employee_id,
        "selected_employee_ids": selected_employee_ids,
        "selected_employee": selected_employee,
        "rows": row_items,
        "page_obj": page_obj,
        "paginator": paginator,
        "page_size": page_size,
        "thong_ke_url": thong_ke_url,
        "co_quyen_xoa": request.user.has_perm("attendance_devices_v2.delete_attendancemanualpunch"),
        "manual_source_choices": MANUAL_SOURCE_CHOICES,
        "default_manual_source_type": MANUAL_SOURCE_MAY_HONG,
        "commit_exists": manual_scope["commit_exists"],
        "manual_scope_source_label": manual_scope["source_label"],
        "manual_scope_blocked": manual_scope["blocked"][:50],
        "manual_scope_blocked_count": len(manual_scope["blocked"]),
        "allowed_employee_count": len(allowed_employee_ids),
    })


@login_required
def xoa_du_lieu_view(request, punch_id: int):
    """Xóa một mốc AttendanceManualPunch đã nhập tay và tính lại MasterList ngày liên quan."""
    if request.method != "POST":
        return redirect("attendance_devices_v2:them_du_lieu")

    if not request.user.has_perm("attendance_devices_v2.delete_attendancemanualpunch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance_devices_v2.delete_attendancemanualpunch",
            "title": "Bạn chưa được cấp quyền xóa dữ liệu chấm công bổ sung"
        }, status=403)

    unit_raw = (request.POST.get("unit") or "").strip()
    q = (request.POST.get("q") or "").strip()

    punch = AttendanceManualPunch.objects.select_related("employee", "employee__unit").filter(id=punch_id).first()
    if not punch:
        messages.error(request, "Không tìm thấy mốc dữ liệu bổ sung cần xóa.")
        fallback_date = _parse_date(request.POST.get("date")) or dj_timezone.localdate()
        return redirect(_them_du_lieu_url(work_date=fallback_date, unit=unit_raw, q=q))

    work_date = _infer_work_date_from_manual_punch(punch)
    unit_id = int(unit_raw) if unit_raw.isdigit() else punch.employee.unit_id
    if unit_id and not unit_in_attendance_scope(request.user, unit_id):
        messages.error(request, "Bạn không có quyền xóa dữ liệu của đơn vị này.")
        return redirect(_them_du_lieu_url(work_date=work_date, unit=unit_raw, q=q))
    if not unit_raw and unit_id:
        unit_raw = str(unit_id)

    emp_label = f"{punch.employee.employee_code} - {punch.employee.full_name}"
    punch_time = dj_timezone.localtime(punch.thoi_gian_local).strftime("%H:%M")
    note = punch.ghi_chu or ""

    punch.delete()

    compute_note = ""
    if unit_id:
        try:
            compute_note = " " + _recompute_unit_date(unit_id=unit_id, work_date=work_date, reason="delete")
        except Exception as exc:
            compute_note = f" Nhưng tính lại MasterList bị lỗi: {exc}"

    messages.success(request, f"Đã xóa mốc {punch_time} của {emp_label}. {note}{compute_note}")
    return redirect(_them_du_lieu_url(work_date=work_date, unit=unit_raw, q=q))


@login_required
def tai_mau_excel_view(request):
    """Tải file mẫu import dữ liệu chấm công bổ sung. Cột ngày để dạng Text để tránh Excel ép thành serial date."""
    if not request.user.has_perm("attendance_devices_v2.add_attendancemanualpunch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance_devices_v2.add_attendancemanualpunch",
            "title": "Bạn chưa được cấp quyền tải file mẫu import chấm công"
        }, status=403)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except Exception:
        messages.error(request, "Máy chủ chưa cài thư viện openpyxl. Cài: pip install openpyxl rồi thử lại.")
        return redirect("attendance_devices_v2:them_du_lieu")

    wb = Workbook()
    ws = wb.active
    ws.title = "NhapDuLieu"

    headers = ["ngay", "ma_nhan_su", "ma_the", "ho_ten", "don_vi", "in1", "out1", "in2", "out2", "ly_do", "ghi_chu"]
    ws.append(headers)

    sample_rows = [
        ["2026-05-20", "NV001", "12345", "Nguyễn Văn A", "PX1", "07:00", "11:30", "13:00", "17:00", "Máy hỏng vật lý", "Biên bản PX1"],
        ["2026-05-20", "NV002", "12346", "Trần Văn B", "PX1", "07:05", "11:31", "13:02", "17:01", "Quên chấm công", "Có xác nhận tổ trưởng"],
    ]
    for row in sample_rows:
        ws.append(row)

    # Ép các cột ngày/giờ/mã thẻ về Text để Excel không tự đổi sang ngày hoặc số.
    text_cols = ["A", "B", "C", "F", "G", "H", "I"]
    for col in text_cols:
        for cell in ws[col]:
            cell.number_format = "@"

    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    widths = {
        "A": 14, "B": 14, "C": 14, "D": 24, "E": 14,
        "F": 10, "G": 10, "H": 10, "I": 10, "J": 24, "K": 34,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    ws2 = wb.create_sheet("HuongDan")
    ws2.append(["Hướng dẫn import dữ liệu chấm công bổ sung"])
    ws2.append(["1. Chọn loại bổ sung trên màn hình import: MAY_HONG hoặc SUA_DU_LIEU."])
    ws2.append(["2. File chỉ dùng ma_nhan_su hoặc ma_the để tìm nhân sự; ho_ten/don_vi chỉ để kiểm tra."])
    ws2.append(["3. Cột ngay nhập dạng Text yyyy-mm-dd, ví dụ 2026-05-20."])
    ws2.append(["4. Giờ nhập dạng HH:MM; R2 nhỏ hơn 04:00 được hiểu là ngày hôm sau."])
    ws2.append(["5. Nếu file có lỗi, hệ thống dừng toàn bộ và không import dòng nào."])
    ws2.column_dimensions["A"].width = 100
    ws2["A1"].font = Font(bold=True)

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="MauImportChamCongBoSung_{ts}.xlsx"'
    return resp
