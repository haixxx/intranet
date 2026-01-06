from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from datetime import date, time
from django.utils import timezone

from apps.audit.utils import audit_log
from apps.organization.models import OrgUnit
from apps.organization.utils import get_subtree_unit_ids
from apps.attendance.models import AttendanceCode, AttendanceSettings
from apps.attendance.models_batch import (
    AttendanceBatch, AttendanceBatchItem,
    AttendanceCommit, AttendanceCommitItem,
    AttendanceCorrectionRequest
)

# Approvals
from apps.approvals.services import create_request
from apps.approvals.services_runtime import activate_next_step_if_any
from apps.approvals.models import ApprovalFlow

# ROSTER
try:
    from apps.attendance.services_bs import build_expected_roster
except Exception:
    build_expected_roster = None

from apps.hr.models import Employee, AccessControl
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


def _units_for_attendance(request):
    base_qs = OrgUnit.objects.filter(is_attendance_unit=True, is_active=True)
    ac = getattr(request.user, "access_control", None)
    if not ac:
        return base_qs.order_by("symbol")
    if ac.scope == AccessControl.Scope.ALL_ORG:
        return base_qs.order_by("symbol")
    root = ac.root_org_unit
    if not root:
        return base_qs.none()
    subtree_ids = get_subtree_unit_ids(root)
    if ac.scope == AccessControl.Scope.UNIT_SUBTREE:
        return base_qs.filter(id__in=subtree_ids).order_by("symbol")
    elif ac.scope == AccessControl.Scope.PLANT_SUBTREE:
        plant = root
        while plant and plant.type != OrgUnit.Type.PLANT:
            plant = plant.parent
        if not plant:
            return base_qs.filter(id__in=subtree_ids).order_by("symbol")
        plant_subtree_ids = get_subtree_unit_ids(plant)
        return base_qs.filter(id__in=plant_subtree_ids).order_by("symbol")
    return base_qs.order_by("symbol")


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
        if emp_id not in commit_items and bool(bi.include_in_unit):
            count += 1
    for emp_id, ci in commit_items.items():
        bi = batch_items.get(emp_id)
        if (bi is None) or (bi is not None and not bool(bi.include_in_unit)):
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
        if (ci.notes or "") != (bi.notes or ""):
            count += 1
        if bool(ci.include_in_unit) != bool(bi.include_in_unit):
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
    Chỉ coi là pending nếu STATUS ∈ {REQUESTED, APPROVED_BY_UNIT}.
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

    return AttendanceCorrectionRequest.objects.filter(
        unit=unit, work_date=work_date, status__in=[requested, approved_unit]
    )


@login_required
def batch_create_or_load(request):
    if not request.user.has_perm("attendance.view_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancebatch",
            "title": "Bạn chưa được cấp quyền xem Tạo/Xem chấm công"
        }, status=403)

    work_date_str = request.GET.get("date", "")
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
        try:
            y, m, d = map(int, work_date_str.split("-"))
            work_date = date(y, m, d)
        except Exception:
            messages.warning(request, "Ngày không hợp lệ.")
            work_date = None

        try:
            unit = OrgUnit.objects.get(pk=int(unit_id), is_attendance_unit=True, is_active=True)
        except Exception:
            unit = None
            messages.warning(request, "Đơn vị không hợp lệ hoặc không được phép chấm công.")

        ac = getattr(request.user, "access_control", None)
        if ac and unit:
            allowed_ids = list(units_qs.values_list("id", flat=True))
            if unit.id not in allowed_ids:
                messages.error(request, "Bạn không có quyền thao tác với đơn vị này.")
                unit = None

        if unit:
            teams = OrgUnit.objects.filter(parent=unit, type=OrgUnit.Type.TEAM).order_by("symbol")
            if TempAssignment is not None and work_date:
                try:
                    bs_in_qs = TempAssignment.objects.filter(
                        apply_flag=True, to_unit=unit, status="ACTIVE",
                        start_date__lte=work_date
                    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=work_date))
                    bs_in_qs = bs_in_qs.select_related("employee").order_by("employee__employee_code")
                    bs_in_list = [f"{ta.employee.employee_code} - {ta.employee.full_name}" for ta in bs_in_qs]
                except Exception:
                    bs_in_list = []

        if work_date and unit:
            batch = AttendanceBatch.objects.filter(unit=unit, work_date=work_date).first()

            if request.GET.get("init") != "1" and not batch:
                messages.info(request, f"Chưa có danh sách điểm danh cho đơn vị {unit.name} ngày {work_date_str}. Vui lòng bấm 'Lập danh sách đăng ký công' để tạo.")

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
                    messages.info(request, f"Đơn vị {unit.name} không có nhân sự trong roster theo ngày {work_date_str}.")

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

            if key_notes in request.POST:
                it.notes = request.POST.get(key_notes, "")

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
def batch_commit(request, batch_id):
    batch = get_object_or_404(AttendanceBatch, pk=batch_id)
    if not request.user.has_perm("attendance.add_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.add_attendancecommit",
            "title": "Bạn chưa được cấp quyền chốt Batch"
        }, status=403)

    if AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).exists():
        messages.warning(request, "Ngày + đơn vị này đã có danh sách đã chốt.")
        return redirect("backoffice:attendance_batch_create_or_load")

    if not batch.items.exists():
        messages.error(request, "Danh sách nháp đang trống, không thể chốt.")
        return redirect("backoffice:attendance_batch_create_or_load")

    errors = []
    for it in batch.items.select_related("code", "employee"):
        if not it.code.is_work:
            continue
        if it.code.requires_am_work and (not it.in1 or not it.out1):
            errors.append(f"{it.employee.employee_code} thiếu mốc sáng (IN1/OUT1).")
        if it.code.requires_pm_work and (not it.in2 or not it.out2):
            errors.append(f"{it.employee.employee_code} thiếu mốc chiều (IN2/OUT2).")

    if errors:
        messages.error(request, "Không thể chốt. Vui lòng bổ sung mốc cho các dòng sau:\n" + "\n".join(errors))
        return redirect("backoffice:attendance_batch_create_or_load")

    commit = AttendanceCommit.objects.create(
        unit=batch.unit, work_date=batch.work_date, committed_by_id=request.user.id
    )
    for it in batch.items.all():
        AttendanceCommitItem.objects.create(
            commit=commit,
            employee=it.employee,
            code=it.code,
            shift=it.shift,
            in1=it.in1, out1=it.out1, in2=it.in2, out2=it.out2,
            notes=it.notes,
            bs_direction=it.bs_direction,
            bs_peer_unit=it.bs_peer_unit,
            include_in_unit=it.include_in_unit
        )

    batch.status = AttendanceBatch.Status.LOCKED_DRAFT
    batch.save()

    audit_log(action_verb="COMMIT", object_type="attendance_batch", object_id=batch.id,
              object_repr=f"{batch.unit.code}-{batch.work_date}", actor=request.user,
              changes={"commit_id": commit.id}, request=request, action_code="ATT_BATCH_COMMIT")
    messages.success(request, f"Đã chốt danh sách chấm công cho {batch.unit.name}.")
    return redirect("backoffice:attendance_committed_view")


@login_required
def committed_view(request):
    """
    Xem công đã chốt (read-only). CHỈ hiển thị include_in_unit=True.
    """
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem Công đã chốt"
        }, status=403)

    work_date_str = request.GET.get("date", "")
    unit_id = request.GET.get("unit", "")
    q = request.GET.get("q", "").strip()
    team = request.GET.get("team", "").strip()
    page = int(request.GET.get("page", "1") or "1")
    per_page = 50

    units_qs = _units_for_attendance(request)
    items = AttendanceCommitItem.objects.none()
    total_count = 0

    if work_date_str and unit_id:
        try:
            y, m, d = map(int, work_date_str.split("-"))
            work_date = date(y, m, d)
        except Exception:
            work_date = None

        try:
            unit = OrgUnit.objects.get(pk=int(unit_id), is_attendance_unit=True, is_active=True)
        except Exception:
            unit = None

        ac = getattr(request.user, "access_control", None)
        if ac and unit:
            allowed_ids = list(units_qs.values_list("id", flat=True))
            if unit.id not in allowed_ids:
                unit = None
                messages.error(request, "Bạn không có quyền xem đơn vị này.")

        if work_date and unit:
            commit = AttendanceCommit.objects.filter(unit=unit, work_date=work_date).first()
            if commit:
                qs = commit.items.select_related("employee", "code").order_by("employee__employee_code")
                if q:
                    qs = qs.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
                if team:
                    qs = qs.filter(employee__team__name__icontains=team, employee__unit=unit)
                qs = qs.filter(include_in_unit=True)
                total_count = qs.count()
                start = (page - 1) * per_page
                end = start + per_page
                items = qs[start:end]

    total_pages = (total_count + per_page - 1) // per_page if total_count else 1
    return render(request, "backoffice/attendance/committed_view.html", {
        "units_qs": units_qs,
        "items": items,
        "work_date": work_date_str,
        "unit_id": unit_id,
        "q": q,
        "team": team,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_count": total_count,
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
        if emp_id not in commit_items and bool(bi.include_in_unit):
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
                "notes": bi.notes or "",
                "include_in_unit": True,
            })
    for emp_id, ci in commit_items.items():
        bi = batch_items.get(emp_id)
        if (bi is None) or (bi is not None and not bool(bi.include_in_unit)):
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
        if (ci.notes or "") != (bi.notes or ""):
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "notes", "old": ci.notes or "", "new": bi.notes or ""})
        if bool(ci.include_in_unit) != bool(bi.include_in_unit):
            changes.append({"employee_id": emp_id, "employee_code": emp_code, "employee_name": emp_name, "field": "include_in_unit", "old": bool(ci.include_in_unit), "new": bool(bi.include_in_unit)})

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
        "payload_changes": [c for c in real_changes if c.get("field")],
    }
    try:
        req = create_request(
            flow_key=selected_flow_key,
            requester=request.user,
            object_type="attendance_correction",
            object_id=str(acr.id),
            title=f"Đề nghị sửa chấm công {batch.work_date.strftime('%Y-%m-%d')}",
            unit_id=batch.unit.id,
            metadata_json=metadata
        )
        activate_next_step_if_any(req)
    except Exception as e:
        messages.warning(request, f"Đã tạo Phiếu đề nghị, nhưng mở quy trình phê duyệt gặp lỗi: {e}")

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
    XÓA toàn bộ nháp và tạo lại theo roster kỳ vọng của đúng work_date.
    Guard: KHÔNG refresh nếu còn ACR pending.
    """
    batch = get_object_or_404(AttendanceBatch.objects.select_related("unit"), pk=batch_id)
    if not request.user.has_perm("attendance.change_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.change_attendancebatch",
            "title": "Bạn chưa được cấp quyền cập nhật danh sách nháp"
        }, status=403)

    if _pending_acr_qs(batch.unit, batch.work_date).exists():
        messages.warning(request, "Danh sách nháp đang bị khóa do có Phiếu đề nghị sửa chấm công đang chờ duyệt.")
        return redirect("backoffice:attendance_batch_create_or_load")

    unit = batch.unit
    work_date = batch.work_date

    if build_expected_roster is None:
        messages.error(request, "Thiếu dịch vụ tính roster. Vui lòng liên hệ quản trị.")
        return redirect("backoffice:attendance_batch_create_or_load")

    expected = build_expected_roster(unit, work_date)

    deleted = batch.items.count()
    batch.items.all().delete()

    settings = AttendanceSettings.objects.first()
    code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
    if not code_ll:
        code_ll = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()

    emp_map = {e.id: e for e in Employee.objects.filter(id__in=[x.employee_id for x in expected]).select_related("team")}

    created = 0
    for e in expected:
        emp = emp_map.get(e.employee_id)
        if not emp:
            continue
        it = AttendanceBatchItem(
            batch=batch,
            employee=emp,
            code=code_ll,
            include_in_unit=bool(e.include_in_unit),
            bs_direction=e.bs_direction,
            bs_peer_unit_id=e.bs_peer_unit_id
        )
        _apply_code_defaults_to_item(it, it.code, settings)
        it.save()
        created += 1

    audit_log(action_verb="REFRESH", object_type="attendance_batch", object_id=batch.id,
              object_repr=f"{batch.unit.code}-{batch.work_date}", actor=request.user,
              changes={"deleted": deleted, "created": created}, request=request, action_code="ATT_BATCH_REFRESH")

    messages.success(request, f"Đã cập nhật danh sách nháp theo roster ngày {work_date} (xóa {deleted}, tạo {created}).")
    return redirect(f"/backoffice/attendance/batch/?date={work_date.strftime('%Y-%m-%d')}&unit={unit.id}")