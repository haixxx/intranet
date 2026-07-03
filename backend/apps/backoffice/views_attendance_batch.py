from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from datetime import date, time
from types import SimpleNamespace
from urllib.parse import urlencode
from django.utils import timezone

from apps.audit.utils import audit_log
from apps.organization.models import OrgUnit
from apps.attendance.models import AttendanceCode, AttendanceSettings
from apps.attendance.models_batch import (
    AttendanceBatch, AttendanceBatchItem,
    AttendanceCommit, AttendanceCommitItem,
    AttendanceCorrectionRequest
)
from apps.attendance_devices_v2.models_master_list import AttendanceDeviceMasterListV2

# Approvals
from apps.approvals.services import create_request
from apps.approvals.services_runtime import activate_next_step_if_any
from apps.approvals.models import ApprovalFlow
from apps.approvals.status_utils import build_approval_status_context

# ROSTER
try:
    from apps.attendance.services_bs import build_expected_roster, compute_roster_diff, apply_roster_diff, scan_impacts_for_temp_assignment
except Exception:
    build_expected_roster = None
    scan_impacts_for_temp_assignment = None

from apps.hr.models import Employee
from apps.backoffice.services.access_scope import get_allowed_attendance_units, unit_in_attendance_scope
try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:
    TempAssignment = None


def _round_to_hour_if_needed(t: time | None, settings: AttendanceSettings | None) -> time | None:
    if not t:
        return t
    if settings and getattr(settings, "round_registration_to_hour", False):
        return time(t.hour, 0, 0)
    return t


def _time_to_str(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def _parse_overtime_hours(value, default=0) -> int:
    """Chỉ nhận 0-4 giờ làm thêm theo Phase 6."""
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return default
    return hours if 0 <= hours <= 4 else default


def _parse_work_date(value: str) -> date | None:
    """
    Nhận cả YYYY-MM-DD và DD/MM/YYYY để UI có thể hiển thị ngày kiểu Việt Nam.
    """
    value = (value or "").strip()
    if not value:
        return timezone.localdate()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(value, fmt).date()
        except Exception:
            pass
    return None


def _format_date_vi(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _url_with_query(view_name: str, **params) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    base = reverse(view_name)
    return f"{base}?{urlencode(clean)}" if clean else base


def _units_for_attendance(request):
    return get_allowed_attendance_units(request.user)


def _apply_code_defaults_to_item(it: AttendanceBatchItem, code: AttendanceCode, settings: AttendanceSettings | None):
    def rt(val: time | None) -> time | None:
        if not val:
            return None
        return _round_to_hour_if_needed(val, settings)

    if not code.is_work:
        it.in1 = None
        it.out1 = None
        it.in2 = None
        it.out2 = None
        return

    it.in1 = rt(code.default_in1) if code.requires_am_work else None
    it.out1 = rt(code.default_out1) if code.requires_am_work else None
    it.in2 = rt(code.default_in2) if code.requires_pm_work else None
    it.out2 = rt(code.default_out2) if code.requires_pm_work else None


def _count_full_diff_between_batch_and_commit(batch: AttendanceBatch, commit: AttendanceCommit) -> int:
    if not batch or not commit:
        return 0
    commit_items = {ci.employee_id: ci for ci in commit.items.select_related("code")}
    batch_items = {bi.employee_id: bi for bi in batch.items.select_related("code")}
    count = 0
    for emp_id, bi in batch_items.items():
        # BS đi có include_in_unit=False nhưng vẫn là dòng công hợp lệ.
        # Vì vậy chỉ cần nháp có mà chốt chưa có là ADD, không phụ thuộc include_in_unit.
        if emp_id not in commit_items:
            count += 1
    for emp_id, ci in commit_items.items():
        bi = batch_items.get(emp_id)
        # Chỉ REMOVE khi dòng không còn trong nháp. include_in_unit=False không phải tín hiệu xóa.
        if bi is None:
            count += 1
    for emp_id, bi in batch_items.items():
        ci = commit_items.get(emp_id)
        if not ci:
            continue
        old_code = ci.code.code if ci.code else None
        new_code = bi.code.code if bi.code else None
        if old_code != new_code:
            count += 1
        for old_v, new_v in ((ci.in1, bi.in1), (ci.out1, bi.out1), (ci.in2, bi.in2), (ci.out2, bi.out2)):
            if _time_to_str(old_v) != _time_to_str(new_v):
                count += 1
        if int(getattr(ci, "overtime_hours", 0) or 0) != int(getattr(bi, "overtime_hours", 0) or 0):
            count += 1
        if (ci.notes or "") != (bi.notes or ""):
            count += 1
        if bool(ci.include_in_unit) != bool(bi.include_in_unit):
            count += 1
        if str(ci.bs_direction or "NONE") != str(bi.bs_direction or "NONE"):
            count += 1
        if (ci.bs_peer_unit_id or None) != (bi.bs_peer_unit_id or None):
            count += 1
    return count


def _compare_roster_simple(batch: AttendanceBatch) -> bool:
    if build_expected_roster is None:
        return False
    unit = batch.unit
    work_date = batch.work_date
    expected = build_expected_roster(unit, work_date)
    exp_map = {e.employee_id: (bool(e.include_in_unit), str(e.bs_direction), e.bs_peer_unit_id or None) for e in expected}
    cur_items = list(batch.items.values("employee_id", "include_in_unit", "bs_direction", "bs_peer_unit_id"))
    cur_map = {it["employee_id"]: (bool(it["include_in_unit"]), str(it["bs_direction"]), it["bs_peer_unit_id"] or None) for it in cur_items}
    if len(exp_map) != len(cur_map):
        return True
    for emp_id, exp_tuple in exp_map.items():
        cur_tuple = cur_map.get(emp_id)
        if cur_tuple is None or cur_tuple != exp_tuple:
            return True
    return False


def _pending_acr_qs(unit: OrgUnit, work_date: date):
    """
    Xác định ACR còn “chờ duyệt/thực hiện” để khóa nháp.
    Chỉ coi là pending nếu STATUS ∈ {REQUESTED, APPROVED_BY_UNIT, APPROVED_BY_HR}.
    Các trạng thái đã kết thúc (REJECTED, APPLIED, CANCELLED, ...) sẽ KHÔNG khóa.
    """
    try:
        requested = AttendanceCorrectionRequest.Status.REQUESTED
    except Exception:
        requested = "REQUESTED"
    try:
        approved_unit = AttendanceCorrectionRequest.Status.APPROVED_BY_UNIT
    except Exception:
        approved_unit = "APPROVED_BY_UNIT"
    try:
        approved_hr = AttendanceCorrectionRequest.Status.APPROVED_BY_HR
    except Exception:
        approved_hr = "APPROVED_BY_HR"

    return AttendanceCorrectionRequest.objects.filter(
        unit=unit, work_date=work_date, status__in=[requested, approved_unit, approved_hr]
    )


@login_required
def batch_create_or_load(request):
    if not request.user.has_perm("attendance.view_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancebatch",
            "title": "Bạn chưa được cấp quyền xem Tạo/Xem chấm công"
        }, status=403)

    work_date_str = request.GET.get("date", "").strip()
    work_date_default = _parse_work_date(work_date_str)
    if not work_date_str:
        work_date_str = _format_date_vi(work_date_default) if work_date_default else ''
    elif work_date_default:
        work_date_str = _format_date_vi(work_date_default)
    work_date_iso = work_date_default.isoformat() if work_date_default else ""
    unit_id = request.GET.get("unit", "")
    q = request.GET.get("q", "").strip()
    team_id = request.GET.get("team", "").strip()
    page = request.GET.get("page", "1")
    page_size_raw = request.GET.get("page_size", "").strip()
    try:
        page_size = int(page_size_raw) if page_size_raw else 50
    except ValueError:
        page_size = 50
    if page_size <= 0 or page_size > 500:
        page_size = 50

    units_qs = _units_for_attendance(request)
    if not unit_id:
        first_unit = units_qs.first()
        if first_unit:
            unit_id = str(first_unit.id)
    batch = None
    items_qs = AttendanceBatchItem.objects.none()
    items = AttendanceBatchItem.objects.none()
    total_count = 0
    teams = OrgUnit.objects.none()
    bs_in_list = []
    diff_count = 0
    available_flows = []
    roster_has_diff = False
    pending_locked = False
    pending_acr_count = 0

    if work_date_str and unit_id:
        work_date = _parse_work_date(work_date_str)
        if work_date is None:
            messages.warning(request, "Ngày không hợp lệ. Vui lòng nhập dạng dd/mm/yyyy.")

        try:
            unit = OrgUnit.objects.get(pk=int(unit_id), is_attendance_unit=True, is_active=True)
        except Exception:
            unit = None
            messages.warning(request, "Đơn vị không hợp lệ hoặc không được phép chấm công.")

        if unit and not unit_in_attendance_scope(request.user, unit.id):
            messages.error(request, "Bạn không có quyền thao tác với đơn vị này.")
            unit = None

        if unit:
            teams = OrgUnit.objects.filter(parent=unit, type=OrgUnit.Type.TEAM).order_by("symbol")
            if TempAssignment is not None and work_date:
                try:
                    bs_in_qs = TempAssignment.objects.filter(
                        apply_flag=True, to_unit=unit, status__in=TempAssignment.effective_statuses(),
                        start_date__lte=work_date
                    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=work_date))
                    bs_in_qs = bs_in_qs.select_related("employee").order_by("employee__employee_code")
                    bs_in_list = [f"{ta.employee.employee_code} - {ta.employee.full_name}" for ta in bs_in_qs]
                except Exception:
                    bs_in_list = []

        if work_date and unit:
            batch = AttendanceBatch.objects.filter(unit=unit, work_date=work_date).first()

            if request.GET.get("init") != "1" and not batch:
                messages.info(request, f"Chưa có danh sách điểm danh cho đơn vị {unit.name} ngày {work_date_str}. Vui lòng bấm 'Lập danh sách chấm công' để tạo.")

            if request.GET.get("init") == "1" and not batch:
                if not request.user.has_perm("attendance.add_attendancebatch"):
                    return render(request, "backoffice/no_permission.html", {
                        "perm_codename": "attendance.add_attendancebatch",
                        "title": "Bạn chưa được cấp quyền tạo Batch chấm công"
                    }, status=403)

                batch = AttendanceBatch.objects.create(
                    unit=unit,
                    work_date=work_date,
                    status=AttendanceBatch.Status.DRAFT,
                    created_by_id=request.user.id
                )

                settings = AttendanceSettings.objects.first()
                code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
                if not code_ll:
                    code_ll = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()
                code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()

                expected = build_expected_roster(unit, work_date) if build_expected_roster else []
                if not expected:
                    messages.info(request, f"Đơn vị {unit.name} không có nhân sự trong danh sách chấm công theo ngày {work_date_str}.")

                emp_ids = [e.employee_id for e in expected]
                emp_map = {e.id: e for e in Employee.objects.filter(id__in=emp_ids).order_by("employee_code")}

                for e in expected:
                    emp = emp_map.get(e.employee_id)
                    if not emp:
                        continue
                    it = AttendanceBatchItem(batch=batch, employee=emp)
                    if str(e.bs_direction) == "OUT" and code_bs:
                        it.code = code_bs
                        it.include_in_unit = False
                        it.bs_direction = AttendanceBatchItem.BSDirection.OUT
                        it.bs_peer_unit_id = e.bs_peer_unit_id
                        # BS đi không có thời gian đăng ký.
                        it.in1 = None
                        it.out1 = None
                        it.in2 = None
                        it.out2 = None
                    else:
                        it.code = code_ll
                        it.include_in_unit = bool(e.include_in_unit)
                        it.bs_direction = e.bs_direction
                        it.bs_peer_unit_id = e.bs_peer_unit_id
                        _apply_code_defaults_to_item(it, it.code, settings)
                    it.save()

                messages.success(request, f"Đã lập danh sách nháp (theo roster ngày {work_date_str}) cho {unit.name}.")

            if batch:
                items_qs = batch.items.select_related("employee", "code").order_by("employee__employee_code")
                if q:
                    items_qs = items_qs.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
                if team_id:
                    items_qs = items_qs.filter(employee__team_id=team_id, employee__unit=unit)

                from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
                paginator = Paginator(items_qs, page_size)
                try:
                    page_obj = paginator.page(page)
                except PageNotAnInteger:
                    page_obj = paginator.page(1)
                except EmptyPage:
                    page_obj = paginator.page(paginator.num_pages)

                items = page_obj.object_list
                total_count = paginator.count

                commit_for_day = AttendanceCommit.objects.filter(unit=unit, work_date=work_date).first()
                if commit_for_day:
                    diff_count = _count_full_diff_between_batch_and_commit(batch, commit_for_day)

                # KHÓA nháp nếu còn ACR pending cho đơn vị/ngày
                pending_qs = _pending_acr_qs(unit, work_date)
                pending_acr_count = pending_qs.count()
                pending_locked = pending_acr_count > 0

                # Luồng phê duyệt
                flows_qs = ApprovalFlow.objects.filter(
                    status=ApprovalFlow.Status.PUBLISHED,
                    versions__is_active=True
                ).distinct().order_by("name")
                for f in flows_qs:
                    st = f.settings_json or {}
                    allowed = st.get("request_units") or []
                    if not allowed or batch.unit.id in [int(x) for x in allowed]:
                        available_flows.append(f)

                try:
                    roster_has_diff = _compare_roster_simple(batch)
                except Exception:
                    roster_has_diff = False
            else:
                paginator = None
                page_obj = None
        else:
            paginator = None
            page_obj = None
    else:
        paginator = None
        page_obj = None

    base_can_save = request.user.has_perm("attendance.change_attendancebatch")
    can_commit = request.user.has_perm("attendance.add_attendancecommit")
    can_request = request.user.has_perm("attendance.add_attendancecorrectionrequest")

    has_committed = False
    if batch:
        has_committed = AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).exists()

    codes_qs = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code")
    can_save = bool(base_can_save and not pending_locked)
    can_request_now = bool(can_request and has_committed and diff_count > 0 and not pending_locked)
    roster_can_refresh = bool(batch and can_save)

    return render(request, "backoffice/attendance/batch_create_or_load.html", {
        "units_qs": units_qs,
        "batch": batch,
        "items": items,
        "work_date": work_date_str,
        "work_date_iso": work_date_iso,
        "unit_id": unit_id,
        "q": q,
        "team_id": team_id,
        "teams": teams,
        "paginator": paginator,
        "page_obj": page_obj,
        "current_page": page_obj.number if page_obj else 1,
        "page_size": page_size,
        "page_size_options": [25, 50, 100, 200],
        "total_count": total_count,
        "can_save": can_save,
        "can_commit": can_commit,
        "can_request": can_request,
        "can_request_now": can_request_now,
        "has_committed": has_committed,
        "codes_qs": codes_qs,
        "bs_in_list": bs_in_list,
        "diff_count": diff_count,
        "flows": available_flows,
        "roster_has_diff": roster_has_diff,
        "roster_can_refresh": roster_can_refresh,
        "batch_id": (batch.id if batch else None),
        "pending_locked": pending_locked,
        "pending_acr_count": pending_acr_count,
    })


@login_required
def batch_save(request, batch_id):
    """
    Lưu đúng thời gian người dùng nhập, KHÔNG revert về mặc định.
    Guard: KHÔNG cho lưu nếu đang có ACR pending cho cùng đơn vị/ngày.
    """
    batch = get_object_or_404(AttendanceBatch.objects.select_related("unit"), pk=batch_id)
    if not request.user.has_perm("attendance.change_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.change_attendancebatch",
            "title": "Bạn chưa được cấp quyền lưu Batch"
        }, status=403)

    # Lock khi ACR còn pending
    if _pending_acr_qs(batch.unit, batch.work_date).exists():
        messages.warning(request, "Danh sách nháp đang bị khóa do có Phiếu đề nghị sửa chấm công đang chờ duyệt.")
        return redirect(f"/backoffice/attendance/batch/?date={batch.work_date.strftime('%Y-%m-%d')}&unit={batch.unit_id}")

    settings = AttendanceSettings.objects.first()
    code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()

    def parse_time(val):
        if val is None or val == "":
            return None
        try:
            hh, mm = map(int, val.split(":"))
            return _round_to_hour_if_needed(time(hh, mm), settings)
        except Exception:
            return None

    item_ids_in_form = set()
    for k in request.POST.keys():
        if "_" in k:
            _, suffix = k.split("_", 1)
            if suffix.isdigit():
                item_ids_in_form.add(int(suffix))

    updated = 0
    if item_ids_in_form:
        qs = batch.items.filter(id__in=item_ids_in_form).select_related("code")
        for it in qs:
            key_code = f"code_{it.id}"
            key_in1 = f"in1_{it.id}"
            key_out1 = f"out1_{it.id}"
            key_in2 = f"in2_{it.id}"
            key_out2 = f"out2_{it.id}"
            key_overtime = f"overtime_hours_{it.id}"
            key_notes = f"notes_{it.id}"

            in1_val = request.POST.get(key_in1, None)
            out1_val = request.POST.get(key_out1, None)
            in2_val = request.POST.get(key_in2, None)
            out2_val = request.POST.get(key_out2, None)

            code_changed = False
            if key_code in request.POST:
                code_val = request.POST.get(key_code)
                if code_val:
                    new_code = AttendanceCode.objects.filter(pk=int(code_val)).first()
                    if new_code and (not it.code or new_code.id != it.code_id):
                        it.code = new_code
                        code_changed = True

            if it.code and not it.code.is_work:
                it.in1 = None
                it.out1 = None
                it.in2 = None
                it.out2 = None
            else:
                if it.code and it.code.requires_am_work:
                    if code_changed:
                        it.in1 = parse_time(in1_val) if (key_in1 in request.POST and in1_val) else _round_to_hour_if_needed(it.code.default_in1, settings)
                        it.out1 = parse_time(out1_val) if (key_out1 in request.POST and out1_val) else _round_to_hour_if_needed(it.code.default_out1, settings)
                    else:
                        if key_in1 in request.POST:
                            it.in1 = parse_time(in1_val)
                        if key_out1 in request.POST:
                            it.out1 = parse_time(out1_val)
                else:
                    it.in1 = None
                    it.out1 = None

                if it.code and it.code.requires_pm_work:
                    if code_changed:
                        it.in2 = parse_time(in2_val) if (key_in2 in request.POST and in2_val) else _round_to_hour_if_needed(it.code.default_in2, settings)
                        it.out2 = parse_time(out2_val) if (key_out2 in request.POST and out2_val) else _round_to_hour_if_needed(it.code.default_out2, settings)
                    else:
                        if key_in2 in request.POST:
                            it.in2 = parse_time(in2_val)
                        if key_out2 in request.POST:
                            it.out2 = parse_time(out2_val)
                else:
                    it.in2 = None
                    it.out2 = None

            if key_overtime in request.POST:
                it.overtime_hours = _parse_overtime_hours(request.POST.get(key_overtime), default=getattr(it, "overtime_hours", 0) or 0)

            if key_notes in request.POST:
                it.notes = request.POST.get(key_notes, "")

            # Quy tắc nghiệp vụ: BS đi/OUT không có thời gian đăng ký,
            # kể cả khi trình duyệt vẫn gửi các input time cũ.
            if str(it.bs_direction) == str(AttendanceBatchItem.BSDirection.OUT):
                if code_bs:
                    it.code = code_bs
                it.in1 = None
                it.out1 = None
                it.in2 = None
                it.out2 = None
                it.overtime_hours = 0
            elif it.code and not it.code.is_work:
                it.overtime_hours = 0

            it.save()
            updated += 1

    audit_log(action_verb="SAVE", object_type="attendance_batch", object_id=batch.id,
              object_repr=f"{batch.unit.code}-{batch.work_date}", actor=request.user,
              changes={"updated_rows": updated}, request=request, action_code="ATT_BATCH_SAVE")
    messages.success(request, f"Đã lưu {updated} dòng (trang hiện tại).")

    date_arg = request.POST.get("date", "")
    unit_arg = request.POST.get("unit", "")
    q_arg = request.POST.get("q", "")
    team_arg = request.POST.get("team", "")
    page_arg = request.POST.get("page", "1")
    page_size_arg = request.POST.get("page_size", "50")

    return redirect(f"/backoffice/attendance/batch/?date={date_arg}&unit={unit_arg}&q={q_arg}&team={team_arg}&page={page_arg}&page_size={page_size_arg}")



@login_required
def batch_bulk_apply(request, batch_id):
    """
    Áp dụng hàng loạt theo BỘ LỌC HIỆN TẠI của batch, không phụ thuộc pagination.

    Ví dụ:
    - Phân xưởng A1 có 65 người.
    - Đang lọc Tổ 1 rồi bấm áp dụng: chỉ áp dụng toàn bộ Tổ 1, kể cả nhiều trang.
    - Không lọc Tổ/tìm kiếm: áp dụng toàn bộ batch.

    Quy tắc:
    - BS đi/OUT: luôn giữ/ép mã BS nếu có và xóa toàn bộ mốc giờ.
    - Dòng thường/BS đến: áp dụng mã chế độ và/hoặc mốc giờ được nhập.
    - Mã không đi làm: xóa mốc giờ.
    """
    batch = get_object_or_404(AttendanceBatch.objects.select_related("unit"), pk=batch_id)
    if not request.user.has_perm("attendance.change_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.change_attendancebatch",
            "title": "Bạn chưa được cấp quyền áp dụng hàng loạt"
        }, status=403)

    if _pending_acr_qs(batch.unit, batch.work_date).exists():
        messages.warning(request, "Danh sách nháp đang bị khóa do có Phiếu đề nghị sửa chấm công đang chờ duyệt.")
        return redirect(f"/backoffice/attendance/batch/?date={batch.work_date.isoformat()}&unit={batch.unit_id}")

    settings = AttendanceSettings.objects.first()
    code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()

    bulk_code_id = request.POST.get("bulk_code", "").strip()
    bulk_code = AttendanceCode.objects.filter(pk=int(bulk_code_id)).first() if bulk_code_id.isdigit() else None

    q_arg = request.POST.get("q", "").strip()
    team_arg = request.POST.get("team", "").strip()
    page_arg = request.POST.get("page", "1")
    page_size_arg = request.POST.get("page_size", "50")
    date_arg = request.POST.get("date", batch.work_date.isoformat())
    unit_arg = request.POST.get("unit", str(batch.unit_id))

    def parse_time(val):
        if val is None or val == "":
            return None
        try:
            hh, mm = map(int, val.split(":"))
            return _round_to_hour_if_needed(time(hh, mm), settings)
        except Exception:
            return None

    bulk_in1 = parse_time(request.POST.get("bulk_in1", ""))
    bulk_out1 = parse_time(request.POST.get("bulk_out1", ""))
    bulk_in2 = parse_time(request.POST.get("bulk_in2", ""))
    bulk_out2 = parse_time(request.POST.get("bulk_out2", ""))
    bulk_overtime_raw = request.POST.get("bulk_overtime_hours", "").strip()
    has_overtime_override = bulk_overtime_raw != ""
    bulk_overtime_hours = _parse_overtime_hours(bulk_overtime_raw, default=0) if has_overtime_override else None

    has_time_override = any(v is not None for v in [bulk_in1, bulk_out1, bulk_in2, bulk_out2])
    if not bulk_code and not has_time_override and not has_overtime_override:
        messages.info(request, "Chưa chọn mã chế độ hoặc mốc giờ để áp dụng.")
        return redirect(f"/backoffice/attendance/batch/?date={date_arg}&unit={unit_arg}&q={q_arg}&team={team_arg}&page={page_arg}&page_size={page_size_arg}")

    target_qs = batch.items.select_related("code", "employee", "employee__team").all()
    scope_parts = []

    if team_arg and team_arg.isdigit():
        target_qs = target_qs.filter(employee__team_id=int(team_arg))
        scope_parts.append(f"tổ id={team_arg}")

    if q_arg:
        target_qs = target_qs.filter(
            Q(employee__full_name__icontains=q_arg)
            | Q(employee__employee_code__icontains=q_arg)
            | Q(employee__card_id__icontains=q_arg)
        )
        scope_parts.append(f"tìm kiếm='{q_arg}'")

    target_items = list(target_qs)
    if not target_items:
        messages.warning(request, "Bộ lọc hiện tại không có dòng nào để áp dụng hàng loạt.")
        return redirect(f"/backoffice/attendance/batch/?date={date_arg}&unit={unit_arg}&q={q_arg}&team={team_arg}&page={page_arg}&page_size={page_size_arg}")

    updated = 0
    for it in target_items:
        is_out = str(it.bs_direction) == str(AttendanceBatchItem.BSDirection.OUT)

        if is_out:
            # Bổ sung đi luôn giữ mã BS và không có mốc đăng ký.
            if code_bs:
                it.code = code_bs
            it.in1 = None
            it.out1 = None
            it.in2 = None
            it.out2 = None
            it.overtime_hours = 0
        else:
            if bulk_code:
                # Khi đổi mã hàng loạt, luôn nạp lại mặc định của mã mới trước,
                # sau đó mới ghi đè các mốc người dùng nhập. Tránh sót giờ cũ
                # của LL/L1/L2 khi chuyển sang mã khác nhưng chỉ nhập một vài mốc.
                it.code = bulk_code
                _apply_code_defaults_to_item(it, bulk_code, settings)

            if it.code and it.code.is_work:
                if request.POST.get("bulk_in1", ""):
                    it.in1 = bulk_in1 if it.code.requires_am_work else None
                if request.POST.get("bulk_out1", ""):
                    it.out1 = bulk_out1 if it.code.requires_am_work else None
                if request.POST.get("bulk_in2", ""):
                    it.in2 = bulk_in2 if it.code.requires_pm_work else None
                if request.POST.get("bulk_out2", ""):
                    it.out2 = bulk_out2 if it.code.requires_pm_work else None
            elif it.code and not it.code.is_work:
                it.in1 = None
                it.out1 = None
                it.in2 = None
                it.out2 = None

        if has_overtime_override and not is_out and it.code and it.code.is_work:
            it.overtime_hours = bulk_overtime_hours
        elif it.code and not it.code.is_work:
            it.overtime_hours = 0

        it.save()
        updated += 1

    scope_label = ", ".join(scope_parts) if scope_parts else "toàn bộ danh sách chấm công nháp"

    audit_log(
        action_verb="BULK_APPLY",
        object_type="attendance_batch",
        object_id=batch.id,
        object_repr=f"{batch.unit.code}-{batch.work_date}",
        actor=request.user,
        changes={
            "updated_rows": updated,
            "scope": "filtered_batch_items",
            "scope_label": scope_label,
            "q": q_arg,
            "team": team_arg,
            "bulk_code_id": bulk_code_id or None,
            "bulk_overtime_hours": bulk_overtime_hours if has_overtime_override else None,
        },
        request=request,
        action_code="ATT_BATCH_BULK_APPLY_FILTERED",
    )
    messages.success(request, f"Đã áp dụng hàng loạt cho {updated} dòng thuộc phạm vi: {scope_label}.")

    return redirect(f"/backoffice/attendance/batch/?date={date_arg}&unit={unit_arg}&q={q_arg}&team={team_arg}&page={page_arg}&page_size={page_size_arg}")

@login_required
@require_POST
def batch_commit(request, batch_id):
    batch = get_object_or_404(AttendanceBatch, pk=batch_id)
    if not request.user.has_perm("attendance.add_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.add_attendancecommit",
            "title": "Bạn chưa được cấp quyền chốt Batch"
        }, status=403)

    if AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).exists():
        messages.warning(request, "Ngày + đơn vị này đã có danh sách đã chốt.")
        return redirect(_url_with_query(
            "backoffice:attendance_batch_create_or_load",
            date=request.POST.get("date") or _format_date_vi(batch.work_date),
            unit=batch.unit_id,
        ))

    if not batch.items.exists():
        messages.error(request, "Danh sách nháp đang trống, không thể chốt.")
        return redirect(_url_with_query(
            "backoffice:attendance_batch_create_or_load",
            date=request.POST.get("date") or _format_date_vi(batch.work_date),
            unit=batch.unit_id,
        ))

    try:
        if _compare_roster_simple(batch):
            messages.error(
                request,
                "Danh sách chấm công nháp đang khác danh sách dự kiến theo điều động/nhân sự hiện tại. "
                "Vui lòng bấm 'Cập nhật lại danh sách chấm công' trước khi chốt."
            )
            return redirect(_url_with_query(
                "backoffice:attendance_batch_create_or_load",
                date=request.POST.get("date") or _format_date_vi(batch.work_date),
                unit=batch.unit_id,
            ))
    except Exception:
        # Không để lỗi so sánh danh sách chặn toàn bộ, nhưng vẫn ưu tiên cảnh báo ở UI.
        pass

    errors = []
    code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()
    for it in batch.items.select_related("code", "employee"):
        # BS đi tại đơn vị gốc không có mốc giờ, không yêu cầu vân tay/chốt mốc.
        if str(it.bs_direction) == str(AttendanceBatchItem.BSDirection.OUT):
            if code_bs and it.code_id != code_bs.id:
                it.code = code_bs
                it.in1 = None
                it.out1 = None
                it.in2 = None
                it.out2 = None
                it.overtime_hours = 0
                it.save(update_fields=["code", "in1", "out1", "in2", "out2", "overtime_hours"])
            continue
        if not it.code or not it.code.is_work:
            continue
        if it.code.requires_am_work and (not it.in1 or not it.out1):
            errors.append(f"{it.employee.employee_code} thiếu mốc 1 (Giờ vào 1/Giờ ra 1).")
        if it.code.requires_pm_work and (not it.in2 or not it.out2):
            errors.append(f"{it.employee.employee_code} thiếu mốc 2 (Giờ vào 2/Giờ ra 2).")

    if errors:
        messages.error(request, "Không thể chốt. Vui lòng bổ sung mốc cho các dòng sau:\n" + "\n".join(errors))
        return redirect(_url_with_query(
            "backoffice:attendance_batch_create_or_load",
            date=request.POST.get("date") or _format_date_vi(batch.work_date),
            unit=batch.unit_id,
        ))

    commit = AttendanceCommit.objects.create(
        unit=batch.unit, work_date=batch.work_date, committed_by_id=request.user.id
    )
    for it in batch.items.select_related("employee", "code", "bs_peer_unit").all():
        commit_item = AttendanceCommitItem(
            commit=commit,
            employee=it.employee,
            code=it.code,
            shift=it.shift,
            in1=it.in1, out1=it.out1, in2=it.in2, out2=it.out2,
            overtime_hours=getattr(it, "overtime_hours", 0) or 0,
            notes=it.notes,
            bs_direction=it.bs_direction,
            bs_peer_unit=it.bs_peer_unit,
            include_in_unit=it.include_in_unit
        )
        # Snapshot lấy mốc giờ từ BatchItem vì người dùng có thể sửa riêng từng dòng nháp.
        commit_item.apply_code_snapshot(source_item=it)
        commit_item.save()

    batch.status = AttendanceBatch.Status.LOCKED_DRAFT
    batch.save()

    audit_log(action_verb="COMMIT", object_type="attendance_batch", object_id=batch.id,
              object_repr=f"{batch.unit.code}-{batch.work_date}", actor=request.user,
              changes={"commit_id": commit.id}, request=request, action_code="ATT_BATCH_COMMIT")
    messages.success(request, f"Đã chốt danh sách chấm công cho {batch.unit.name}.")
    return redirect(_url_with_query(
        "backoffice:attendance_committed_view",
        date=request.POST.get("date") or _format_date_vi(batch.work_date),
        unit=batch.unit_id,
    ))


def _effective_temp_assignment_qs_for_date(work_date: date):
    """Điều động có hiệu lực trong ngày, dùng làm nguồn nghiệp vụ gốc cho BS đi/đến."""
    if TempAssignment is None or not work_date:
        return None
    return (
        TempAssignment.objects.filter(
            apply_flag=True,
            status__in=TempAssignment.effective_statuses(),
            start_date__lte=work_date,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=work_date))
        .select_related("employee", "employee__team", "from_unit", "to_unit")
    )


def _matching_received_commit_item(employee_id: int, work_date: date, from_unit: OrgUnit, to_unit: OrgUnit):
    """Dòng BS đến tương ứng tại đơn vị nhận, nếu đơn vị nhận đã chốt."""
    return (
        AttendanceCommitItem.objects.select_related("code", "commit", "commit__unit")
        .filter(
            commit__unit=to_unit,
            commit__work_date=work_date,
            employee_id=employee_id,
            bs_direction=AttendanceCommitItem.BSDirection.IN,
            include_in_unit=True,
            bs_peer_unit=from_unit,
        )
        .first()
    )


def _virtual_bs_out_items_from_temp_assignment(unit: OrgUnit, work_date: date, existing_employee_ids=None):
    """
    Trả về các dòng hiển thị BS đi dựa trên điều động nhân sự.

    TempAssignment là nguồn nghiệp vụ gốc để xác định ai đi bổ sung. Công chốt
    của đơn vị nhận chỉ được dùng làm căn cứ công thực tế/cảnh báo, không dùng
    để tự suy luận nghiệp vụ BS đi.
    """
    existing_employee_ids = set(existing_employee_ids or [])
    ta_qs = _effective_temp_assignment_qs_for_date(work_date)
    if ta_qs is None:
        return []

    rows = []
    for ta in ta_qs.filter(from_unit=unit).order_by("employee__employee_code", "id"):
        if ta.employee_id in existing_employee_ids:
            continue
        received_item = _matching_received_commit_item(ta.employee_id, work_date, unit, ta.to_unit)
        notes = f"Bổ sung đi sang {ta.to_unit.code if ta.to_unit else ''}".strip()
        if received_item is None:
            notes = (notes + " - Chưa có công chốt tương ứng ở đơn vị nhận").strip()
        rows.append(SimpleNamespace(
            id=f"virtual-bs-out-ta-{ta.id}-{work_date.isoformat()}",
            employee=ta.employee,
            employee_id=ta.employee_id,
            code=None,
            code_id=None,
            effective_code_text="BS",
            label_snapshot="Bổ sung đi",
            in1=None,
            out1=None,
            in2=None,
            out2=None,
            overtime_hours=0,
            notes=notes,
            bs_direction=AttendanceCommitItem.BSDirection.OUT,
            bs_peer_unit=ta.to_unit,
            bs_peer_unit_id=ta.to_unit_id,
            include_in_unit=False,
            is_virtual_bs_out=True,
            source_temp_assignment_id=ta.id,
            received_commit_item=received_item,
        ))
    return rows


def _bs_consistency_warnings(unit: OrgUnit, work_date: date, commit: AttendanceCommit | None):
    """
    Cảnh báo lệch giữa điều động nhân sự và công đã chốt trong ngày.
    Không ghi dữ liệu, chỉ giúp thống kê biết cần kiểm tra đơn vị nào.
    """
    warnings = []
    ta_qs = _effective_temp_assignment_qs_for_date(work_date)
    if ta_qs is None:
        return warnings

    real_by_emp = {}
    if commit:
        real_by_emp = {it.employee_id: it for it in commit.items.select_related("employee", "code", "bs_peer_unit").all()}

    # Điều động đi khỏi đơn vị đang xem.
    for ta in ta_qs.filter(from_unit=unit).order_by("employee__employee_code", "id"):
        emp_label = f"{ta.employee.employee_code} - {ta.employee.full_name}"
        it = real_by_emp.get(ta.employee_id)
        if it:
            is_valid_out = (
                str(it.bs_direction) == str(AttendanceCommitItem.BSDirection.OUT)
                and not bool(it.include_in_unit)
                and (it.bs_peer_unit_id or None) == ta.to_unit_id
            )
            if not is_valid_out:
                warnings.append(
                    f"{emp_label}: có điều động đi sang {ta.to_unit.code}, nhưng dòng chốt đơn vị gốc chưa phải BS đi đúng đơn vị đến."
                )
        received_item = _matching_received_commit_item(ta.employee_id, work_date, unit, ta.to_unit)
        if received_item is None:
            warnings.append(
                f"{emp_label}: có điều động đi sang {ta.to_unit.code}, nhưng chưa thấy công chốt BS đến tương ứng ở đơn vị nhận."
            )

    # Điều động đến đơn vị đang xem.
    for ta in ta_qs.filter(to_unit=unit).order_by("employee__employee_code", "id"):
        emp_label = f"{ta.employee.employee_code} - {ta.employee.full_name}"
        it = real_by_emp.get(ta.employee_id)
        if it is None:
            warnings.append(
                f"{emp_label}: có điều động đến từ {ta.from_unit.code}, nhưng chưa có dòng công chốt ở đơn vị nhận."
            )
            continue
        is_valid_in = (
            str(it.bs_direction) == str(AttendanceCommitItem.BSDirection.IN)
            and bool(it.include_in_unit)
            and (it.bs_peer_unit_id or None) == ta.from_unit_id
        )
        if not is_valid_in:
            warnings.append(
                f"{emp_label}: có điều động đến từ {ta.from_unit.code}, nhưng dòng chốt chưa phải BS đến đúng đơn vị gốc."
            )

    # Dòng công chốt có đánh dấu BS nhưng không còn điều động tương ứng.
    if commit:
        for it in commit.items.select_related("employee", "bs_peer_unit").filter(
            bs_direction__in=[AttendanceCommitItem.BSDirection.IN, AttendanceCommitItem.BSDirection.OUT]
        ):
            if str(it.bs_direction) == str(AttendanceCommitItem.BSDirection.IN):
                exists = ta_qs.filter(employee_id=it.employee_id, from_unit_id=it.bs_peer_unit_id, to_unit=unit).exists()
                if not exists:
                    warnings.append(
                        f"{it.employee.employee_code} - {it.employee.full_name}: công chốt có BS đến nhưng không tìm thấy điều động tương ứng."
                    )
            elif str(it.bs_direction) == str(AttendanceCommitItem.BSDirection.OUT):
                exists = ta_qs.filter(employee_id=it.employee_id, from_unit=unit, to_unit_id=it.bs_peer_unit_id).exists()
                if not exists:
                    warnings.append(
                        f"{it.employee.employee_code} - {it.employee.full_name}: công chốt có BS đi nhưng không tìm thấy điều động tương ứng."
                    )

    return warnings


@login_required
def committed_view(request):
    """
    Xem công đã chốt (read-only). Hiển thị cả dòng trong quân số, BS đến và BS đi.
    """
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem Công đã chốt"
        }, status=403)

    work_date_str = request.GET.get("date", "").strip()
    work_date_default = _parse_work_date(work_date_str)
    if not work_date_str:
        work_date_str = _format_date_vi(work_date_default) if work_date_default else ''
    elif work_date_default:
        work_date_str = _format_date_vi(work_date_default)
    work_date_iso = work_date_default.isoformat() if work_date_default else ""
    unit_id = request.GET.get("unit", "")
    q = request.GET.get("q", "").strip()
    team = request.GET.get("team", "").strip()
    try:
        page = int(request.GET.get("page", "1") or "1")
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    per_page = 50

    units_qs = _units_for_attendance(request)
    if not unit_id:
        first_unit = units_qs.first()
        if first_unit:
            unit_id = str(first_unit.id)
    items = AttendanceCommitItem.objects.none()
    total_count = 0
    latest_acr = None
    latest_acr_status = ""
    latest_acr_status_label = ""
    latest_acr_status_class = "bo-badge-secondary"
    latest_acr_status_note = ""
    latest_acr_request_url = ""
    bs_warnings = []
    device_v2_stale_count = 0
    device_v2_stale_url = ""

    if work_date_str and unit_id:
        work_date = _parse_work_date(work_date_str)

        try:
            unit = OrgUnit.objects.get(pk=int(unit_id), is_attendance_unit=True, is_active=True)
        except Exception:
            unit = None

        if unit and not unit_in_attendance_scope(request.user, unit.id):
            unit = None
            messages.error(request, "Bạn không có quyền xem đơn vị này.")

        if work_date and unit:
            commit = AttendanceCommit.objects.filter(unit=unit, work_date=work_date).first()
            real_items = []
            if commit:
                qs = commit.items.select_related("employee", "employee__team", "code", "bs_peer_unit").order_by("employee__employee_code")
                if q:
                    qs = qs.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
                if team:
                    qs = qs.filter(employee__team__name__icontains=team)
                # Không lọc include_in_unit=True để vẫn thấy người bổ sung đi (BS OUT).
                real_items = list(qs)

            # Cảnh báo/BS đi bổ sung dựa trên điều động nhân sự, không suy luận nghiệp vụ từ công chốt.
            try:
                bs_warnings = _bs_consistency_warnings(unit, work_date, commit)
            except Exception:
                bs_warnings = []

            try:
                device_v2_stale_count = AttendanceDeviceMasterListV2.objects.filter(
                    work_date=work_date,
                    unit=unit,
                    expected_marks__gt=0,
                    compute_state=AttendanceDeviceMasterListV2.ComputeState.STALE,
                ).count()
                if device_v2_stale_count:
                    device_v2_stale_url = _url_with_query(
                        "attendance_devices_v2:thong_ke",
                        **{
                            "from": work_date.isoformat(),
                            "to": work_date.isoformat(),
                            "unit": unit.id,
                            "status": "CAN_TINH_LAI",
                            "source": "DA_SUA",
                            "page": 1,
                        }
                    )
            except Exception:
                device_v2_stale_count = 0
                device_v2_stale_url = ""

            # Bảng công chốt chỉ hiển thị AttendanceCommitItem thật.
            # Điều động chưa/thiếu công chốt được đưa vào khối cảnh báo, không trộn thành dòng chốt ảo.
            combined_items = real_items
            combined_items.sort(key=lambda it: (getattr(it.employee, "employee_code", "") or "", getattr(it.employee, "full_name", "") or ""))
            total_count = len(combined_items)
            start = (page - 1) * per_page
            end = start + per_page
            items = combined_items[start:end]

            latest_acr = AttendanceCorrectionRequest.objects.filter(
                unit=unit, work_date=work_date
            ).order_by("-requested_at").first()
            if latest_acr:
                latest_acr_status = latest_acr.status
                latest_acr_status_label = latest_acr.get_status_display()
                try:
                    from apps.approvals.models import ApprovalRequest
                    approval_req = ApprovalRequest.objects.filter(
                        object_type="attendance_correction",
                        object_id=str(latest_acr.id),
                    ).order_by("-created_at").first()
                    if approval_req:
                        latest_acr_request_url = reverse("backoffice:approvals_request_detail", args=[approval_req.id])
                        status_ctx = build_approval_status_context(approval_req, acr=latest_acr)
                        latest_acr_status_label = status_ctx.get("label") or latest_acr_status_label
                        latest_acr_status_class = status_ctx.get("bo_badge_class") or latest_acr_status_class
                        latest_acr_status_note = status_ctx.get("note") or ""
                    else:
                        latest_acr_status_class = {
                            AttendanceCorrectionRequest.Status.APPLIED: "bo-badge-success",
                            AttendanceCorrectionRequest.Status.REJECTED: "bo-badge-danger",
                            AttendanceCorrectionRequest.Status.CANCELLED: "bo-badge-secondary",
                            AttendanceCorrectionRequest.Status.APPROVED_BY_HR: "bo-badge-info",
                            AttendanceCorrectionRequest.Status.APPROVED_BY_UNIT: "bo-badge-warning",
                            AttendanceCorrectionRequest.Status.REQUESTED: "bo-badge-warning",
                        }.get(latest_acr.status, "bo-badge-secondary")
                except Exception:
                    latest_acr_request_url = ""
    total_pages = (total_count + per_page - 1) // per_page if total_count else 1
    return render(request, "backoffice/attendance/committed_view.html", {
        "units_qs": units_qs,
        "items": items,
        "work_date": work_date_str,
        "work_date_iso": work_date_iso,
        "unit_id": unit_id,
        "q": q,
        "team": team,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_count": total_count,
        "latest_acr": latest_acr,
        "latest_acr_status": latest_acr_status,
        "latest_acr_status_label": latest_acr_status_label,
        "latest_acr_status_class": latest_acr_status_class,
        "latest_acr_status_note": latest_acr_status_note,
        "latest_acr_request_url": latest_acr_request_url,
        "bs_warnings": bs_warnings,
        "device_v2_stale_count": device_v2_stale_count,
        "device_v2_stale_url": device_v2_stale_url,
    })


@login_required
def attendance_correction_request_create(request, batch_id):
    """
    Tạo Phiếu đề nghị sửa chấm công từ Batch đã chốt.
    Guard: KHÔNG tạo ACR mới nếu đã có ACR pending cho cùng đơn vị/ngày.
    """
    batch = get_object_or_404(AttendanceBatch.objects.select_related("unit"), pk=batch_id)
    if not request.user.has_perm("attendance.add_attendancecorrectionrequest"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.add_attendancecorrectionrequest",
            "title": "Bạn chưa được cấp quyền tạo Phiếu đề nghị sửa chấm công"
        }, status=403)

    committed = AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).first()
    if not committed:
        messages.warning(request, "Ngày + đơn vị này chưa có danh sách đã chốt. Vui lòng chốt trước khi gửi đề nghị.")
        return redirect("backoffice:attendance_batch_create_or_load")

    if _pending_acr_qs(batch.unit, batch.work_date).exists():
        messages.warning(request, "Đang có Phiếu đề nghị sửa chấm công chờ duyệt cho ngày/đơn vị này. Vui lòng hoàn tất trước khi gửi đề nghị mới.")
        return redirect(f"/backoffice/attendance/batch/?date={batch.work_date.strftime('%Y-%m-%d')}&unit={batch.unit_id}")

    if request.method != "POST":
        return redirect("backoffice:attendance_batch_create_or_load")

    selected_flow_key = (request.POST.get("flow_key") or "").strip()
    if not selected_flow_key:
        messages.error(request, "Vui lòng chọn luồng phê duyệt.")
        return redirect(f"/backoffice/attendance/batch/?date={batch.work_date.strftime('%Y-%m-%d')}&unit={batch.unit.id}")

    reason = request.POST.get("reason", "").strip()
    acr_code = f"ACR-{batch.unit.code}-{batch.work_date.strftime('%Y%m%d')}-{request.user.id}-{int(timezone.now().timestamp())}"

    commit_items = {ci.employee_id: ci for ci in committed.items.select_related("code", "employee")}
    batch_items = {bi.employee_id: bi for bi in batch.items.select_related("employee", "code")}

    changes = []

    # Membership-level
    for emp_id, bi in batch_items.items():
        # BS đi có include_in_unit=False nhưng vẫn là dòng công hợp lệ.
        # Vì vậy ADD không phụ thuộc include_in_unit.
        if emp_id not in commit_items:
            changes.append({
                "type": "ADD_EMPLOYEE",
                "employee_id": emp_id,
                "employee_code": bi.employee.employee_code,
                "employee_name": bi.employee.full_name,
                "code": bi.code.code if bi.code else None,
                "in1": _time_to_str(bi.in1),
                "out1": _time_to_str(bi.out1),
                "in2": _time_to_str(bi.in2),
                "out2": _time_to_str(bi.out2),
                "overtime_hours": int(getattr(bi, "overtime_hours", 0) or 0),
                "notes": bi.notes or "",
                "include_in_unit": bool(bi.include_in_unit),
                "bs_direction": bi.bs_direction,
                "bs_peer_unit_id": bi.bs_peer_unit_id,
            })
    for emp_id, ci in commit_items.items():
        bi = batch_items.get(emp_id)
        # Chỉ REMOVE khi nháp không còn dòng nhân sự. include_in_unit=False là nghiệp vụ BS đi.
        if bi is None:
            changes.append({
                "type": "REMOVE_EMPLOYEE",
                "employee_id": emp_id,
                "employee_code": ci.employee.employee_code,
                "employee_name": ci.employee.full_name,
            })

    # Field-level
    for emp_id, bi in batch_items.items():
        ci = commit_items.get(emp_id)
        if not ci:
            continue
        emp_code = bi.employee.employee_code
        emp_name = bi.employee.full_name
        old_code = ci.code.code if ci.code else None
        new_code = bi.code.code if bi.code else None
        if old_code != new_code:
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "code", "old": old_code, "new": new_code})
        for fname, old_v, new_v in [("in1", ci.in1, bi.in1), ("out1", ci.out1, bi.out1), ("in2", ci.in2, bi.in2), ("out2", ci.out2, bi.out2)]:
            if _time_to_str(old_v) != _time_to_str(new_v):
                changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": fname, "old": _time_to_str(old_v), "new": _time_to_str(new_v)})
        old_ot = int(getattr(ci, "overtime_hours", 0) or 0)
        new_ot = int(getattr(bi, "overtime_hours", 0) or 0)
        if old_ot != new_ot:
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "overtime_hours", "old": old_ot, "new": new_ot})
        if (ci.notes or "") != (bi.notes or ""):
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "notes", "old": ci.notes or "", "new": bi.notes or ""})
        if bool(ci.include_in_unit) != bool(bi.include_in_unit):
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "include_in_unit", "old": bool(ci.include_in_unit), "new": bool(bi.include_in_unit)})
        if str(ci.bs_direction or "NONE") != str(bi.bs_direction or "NONE"):
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "bs_direction", "old": ci.bs_direction or "NONE", "new": bi.bs_direction or "NONE"})
        if (ci.bs_peer_unit_id or None) != (bi.bs_peer_unit_id or None):
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "bs_peer_unit_id", "old": ci.bs_peer_unit_id, "new": bi.bs_peer_unit_id})

    real_changes = [x for x in changes if x.get("field") or x.get("type")]
    if len(real_changes) == 0:
        messages.info(request, "Không có thay đổi nào so với công đã chốt. Vui lòng lưu nháp các chỉnh sửa trước khi gửi đề nghị.")
        date_arg = request.POST.get("date", "")
        unit_arg = request.POST.get("unit", "")
        q_arg = request.POST.get("q", "")
        team_arg = request.POST.get("team", "")
        page_arg = request.POST.get("page", "1")
        page_size_arg = request.POST.get("page_size", "50")
        return redirect(f"/backoffice/attendance/batch/?date={date_arg}&unit={unit_arg}&q={q_arg}&team={team_arg}&page={page_arg}&page_size={page_size_arg}")

    if reason:
        changes.insert(0, {"type": "NOTE", "value": reason, "acr_code": acr_code})

    try:
        with transaction.atomic():
            acr = AttendanceCorrectionRequest.objects.create(
                unit=batch.unit,
                work_date=batch.work_date,
                status=AttendanceCorrectionRequest.Status.REQUESTED,
                requested_by=request.user,
                payload_json=changes
            )

            metadata = {
                "flow": "Phê duyệt sửa chấm công",
                "object_type": "attendance_correction",
                "object_id": str(acr.id),
                "acr_code": acr_code,
                "unit_id": batch.unit.id,
                "unit_code": batch.unit.code,
                "work_date": batch.work_date.strftime("%Y-%m-%d"),
                "requester_username": request.user.username,
                "reason": reason,
                "diff_count": len(real_changes),
                "payload_changes": real_changes,
            }
            req = create_request(
                flow_key=selected_flow_key,
                requester=request.user,
                object_type="attendance_correction",
                object_id=str(acr.id),
                title=f"Đề nghị sửa chấm công {batch.work_date.strftime('%Y-%m-%d')}",
                unit_id=batch.unit.id,
                metadata_json=metadata
            )
            activate_next_step_if_any(req, actor=request.user)
    except Exception as e:
        messages.error(request, f"Không tạo được Phiếu đề nghị sửa chấm công hoặc quy trình phê duyệt: {e}")
        date_arg = request.POST.get("date", "")
        unit_arg = request.POST.get("unit", "")
        q_arg = request.POST.get("q", "")
        team_arg = request.POST.get("team", "")
        page_arg = request.POST.get("page", "1")
        page_size_arg = request.POST.get("page_size", "50")
        return redirect(f"/backoffice/attendance/batch/?date={date_arg}&unit={unit_arg}&q={q_arg}&team={team_arg}&page={page_arg}&page_size={page_size_arg}")

    audit_log(
        action_verb="REQUEST",
        object_type="attendance_correction",
        object_id=acr.id,
        object_repr=f"{acr_code}",
        actor=request.user,
        changes={"unit": batch.unit.code, "work_date": batch.work_date.strftime("%Y-%m-%d"), "reason": reason, "diff_count": len(real_changes), "flow_key": selected_flow_key},
        request=request,
        action_code="ATT_CORRECTION_REQUEST"
    )

    messages.success(request, f"Đã tạo Phiếu đề nghị sửa chấm công cho {batch.unit.name} ngày {batch.work_date}. Mã: {acr_code}")
    date_arg = request.POST.get("date", "")
    unit_arg = request.POST.get("unit", "")
    q_arg = request.POST.get("q", "")
    team_arg = request.POST.get("team", "")
    page_arg = request.POST.get("page", "1")
    page_size_arg = request.POST.get("page_size", "50")

    return redirect(f"/backoffice/attendance/batch/?date={date_arg}&unit={unit_arg}&q={q_arg}&team={team_arg}&page={page_arg}&page_size={page_size_arg}")


@login_required
def batch_refresh_roster(request, batch_id: int):
    """
    Cập nhật lại danh sách chấm công nháp theo điều động/nhân sự hiện tại.

    Không xóa toàn bộ nháp. Chỉ áp dụng diff:
    - Thêm người mới cần có.
    - Xóa người không còn thuộc danh sách nếu đang include_in_unit=True.
    - Cập nhật BS direction / peer unit / include flag.
    - Giữ nguyên mã chế độ, IN/OUT, ghi chú của các dòng không bị ảnh hưởng.
    """
    batch = get_object_or_404(AttendanceBatch.objects.select_related("unit"), pk=batch_id)
    if not request.user.has_perm("attendance.change_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.change_attendancebatch",
            "title": "Bạn chưa được cấp quyền cập nhật danh sách chấm công nháp"
        }, status=403)

    if _pending_acr_qs(batch.unit, batch.work_date).exists():
        messages.warning(request, "Danh sách chấm công nháp đang bị khóa do có Phiếu đề nghị sửa chấm công đang chờ duyệt.")
        return redirect(f"/backoffice/attendance/batch/?date={batch.work_date.strftime('%Y-%m-%d')}&unit={batch.unit_id}")

    if build_expected_roster is None:
        messages.error(request, "Thiếu dịch vụ tính danh sách chấm công. Vui lòng liên hệ quản trị.")
        return redirect(f"/backoffice/attendance/batch/?date={batch.work_date.strftime('%Y-%m-%d')}&unit={batch.unit_id}")

    expected = build_expected_roster(batch.unit, batch.work_date)
    diff = compute_roster_diff(batch, expected)
    result = apply_roster_diff(batch, diff)

    # Sau khi cập nhật danh sách chấm công nháp, scan lại các điều động
    # liên quan để last_impact_summary không còn báo ảnh hưởng cũ.
    if TempAssignment is not None and scan_impacts_for_temp_assignment is not None:
        try:
            affected_qs = TempAssignment.objects.filter(
                apply_flag=True,
                status__in=TempAssignment.effective_statuses(),
                start_date__lte=batch.work_date,
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=batch.work_date)
            ).filter(
                Q(from_unit=batch.unit) | Q(to_unit=batch.unit)
            )
            for ta in affected_qs.select_related("employee", "from_unit", "to_unit"):
                scan_impacts_for_temp_assignment(ta)
        except Exception:
            pass

    audit_log(
        action_verb="REFRESH",
        object_type="attendance_batch",
        object_id=batch.id,
        object_repr=f"{batch.unit.code}-{batch.work_date}",
        actor=request.user,
        changes={"mode": "safe_diff", **result},
        request=request,
        action_code="ATT_BATCH_REFRESH_SAFE",
    )

    messages.success(
        request,
        "Đã cập nhật lại danh sách chấm công nháp: "
        f"thêm {result.get('added', 0)}, xóa {result.get('removed', 0)}, cập nhật {result.get('updated', 0)}. "
        "Dữ liệu đã nhập ở các dòng không bị ảnh hưởng được giữ nguyên."
    )
    return redirect(f"/backoffice/attendance/batch/?date={batch.work_date.strftime('%Y-%m-%d')}&unit={batch.unit_id}")
