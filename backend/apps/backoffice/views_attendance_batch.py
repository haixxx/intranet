from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import date, time

from apps.audit.utils import audit_log
from apps.organization.models import OrgUnit
from apps.organization.utils import get_subtree_unit_ids
from apps.attendance.models import AttendanceCode, AttendanceSettings
from apps.attendance.models_batch import (
    AttendanceBatch, AttendanceBatchItem,
    AttendanceCommit, AttendanceCommitItem,
    AttendanceCorrectionRequest
)

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
    """
    Chỉ dùng khi khởi tạo hoặc khi đổi mã mà KHÔNG có thời gian do người dùng nhập.
    """
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
            if TempAssignment is not None:
                try:
                    bs_in_qs = TempAssignment.objects.filter(
                        apply_flag=True, to_unit=unit, status="ACTIVE"
                    ).select_related("employee").order_by("employee__employee_code")
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

                base_qs = Employee.objects.filter(unit=unit, status=Employee.Status.ACTIVE)

                bs_in_ids, bs_out_ids = [], []
                if TempAssignment is not None:
                    try:
                        bs_in_ids = list(TempAssignment.objects.filter(
                            apply_flag=True, to_unit=unit, status="ACTIVE"
                        ).values_list("employee_id", flat=True))
                        bs_out_ids = list(TempAssignment.objects.filter(
                            apply_flag=True, from_unit=unit, status="ACTIVE"
                        ).values_list("employee_id", flat=True))
                    except Exception:
                        bs_in_ids, bs_out_ids = [], []

                employees = Employee.objects.filter(
                    Q(id__in=base_qs.values_list("id", flat=True)) |
                    Q(id__in=bs_in_ids) |
                    Q(id__in=bs_out_ids)
                ).distinct().order_by("employee_code")

                settings = AttendanceSettings.objects.first()
                code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
                code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()

                if not employees.exists():
                    messages.info(request, f"Đơn vị {unit.name} chưa có nhân sự ACTIVE để lập danh sách.")

                for emp in employees:
                    bs_in = TempAssignment is not None and TempAssignment.objects.filter(
                        apply_flag=True, to_unit=unit, status="ACTIVE", employee=emp
                    ).exists()
                    bs_out = TempAssignment is not None and TempAssignment.objects.filter(
                        apply_flag=True, from_unit=unit, status="ACTIVE", employee=emp
                    ).exists()

                    it = AttendanceBatchItem(batch=batch, employee=emp)
                    if bs_out and not bs_in:
                        it.bs_direction = AttendanceBatchItem.BSDirection.OUT
                        it.include_in_unit = False
                        it.code = code_bs if code_bs else (code_ll or AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first())
                    else:
                        it.bs_direction = AttendanceBatchItem.BSDirection.IN if (bs_in and not bs_out) else AttendanceBatchItem.BSDirection.NONE
                        it.include_in_unit = True
                        it.code = code_ll or AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()

                    _apply_code_defaults_to_item(it, it.code, settings)
                    it.save()

                messages.success(request, f"Đã lập danh sách nháp cho {unit.name} ngày {work_date_str}.")

            if batch:
                items_qs = batch.items.select_related("employee", "code").order_by("employee__employee_code")
                if q:
                    items_qs = items_qs.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
                if team_id:
                    items_qs = items_qs.filter(employee__team_id=team_id, employee__unit=unit)

                paginator = Paginator(items_qs, page_size)
                try:
                    page_obj = paginator.page(page)
                except PageNotAnInteger:
                    page_obj = paginator.page(1)
                except EmptyPage:
                    page_obj = paginator.page(paginator.num_pages)

                items = page_obj.object_list
                total_count = paginator.count
            else:
                paginator = None
                page_obj = None
        else:
            paginator = None
            page_obj = None
    else:
        paginator = None
        page_obj = None

    can_save = request.user.has_perm("attendance.change_attendancebatch")
    can_commit = request.user.has_perm("attendance.add_attendancecommit")
    can_request = request.user.has_perm("attendance.add_attendancecorrectionrequest")

    has_committed = False
    if batch:
        has_committed = AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).exists()

    codes_qs = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code")

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
        "has_committed": has_committed,
        "codes_qs": codes_qs,
        "bs_in_list": bs_in_list,
    })


@login_required
def batch_save(request, batch_id):
    """
    Lưu đúng thời gian người dùng nhập, KHÔNG revert về mặc định.
    Quy tắc:
    - Nếu đổi mã: chỉ lấy mặc định khi ô tương ứng KHÔNG xuất hiện trong POST hoặc để trống; nếu có giá trị -> dùng giá trị người dùng.
    - Nếu không đổi mã: dùng đúng giá trị người dùng theo các key trong POST; không re-apply mặc định.
    - Nếu mã không đi làm: set tất cả IN/OUT = None.
    """
    batch = get_object_or_404(AttendanceBatch, pk=batch_id)
    if not request.user.has_perm("attendance.change_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.change_attendancebatch",
            "title": "Bạn chưa được cấp quyền lưu Batch"
        }, status=403)

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

            # Lấy giá trị người dùng (có thể trống)
            in1_val = request.POST.get(key_in1, None)
            out1_val = request.POST.get(key_out1, None)
            in2_val = request.POST.get(key_in2, None)
            out2_val = request.POST.get(key_out2, None)

            # Đổi mã nếu có
            code_changed = False
            if key_code in request.POST:
                code_val = request.POST.get(key_code)
                if code_val:
                    new_code = AttendanceCode.objects.filter(pk=int(code_val)).first()
                    if new_code and (not it.code or new_code.id != it.code_id):
                        it.code = new_code
                        code_changed = True

            # Nếu mã không đi làm: xoá toàn bộ mốc
            if it.code and not it.code.is_work:
                it.in1 = None
                it.out1 = None
                it.in2 = None
                it.out2 = None
            else:
                # AM
                if it.code and it.code.requires_am_work:
                    if code_changed:
                        # Nếu đổi mã: ưu tiên dữ liệu người dùng; nếu không nhập thì dùng mặc định theo mã mới
                        it.in1 = parse_time(in1_val) if (key_in1 in request.POST and in1_val) else _round_to_hour_if_needed(it.code.default_in1, settings)
                        it.out1 = parse_time(out1_val) if (key_out1 in request.POST and out1_val) else _round_to_hour_if_needed(it.code.default_out1, settings)
                    else:
                        # Không đổi mã: dùng đúng giá trị người dùng; nếu không nhập, giữ nguyên
                        if key_in1 in request.POST:
                            it.in1 = parse_time(in1_val)
                        if key_out1 in request.POST:
                            it.out1 = parse_time(out1_val)
                else:
                    it.in1 = None
                    it.out1 = None

                # PM
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
    Xem công chốt (read-only):
    - Bộ lọc: ngày, đơn vị, q, team (theo tên).
    - Dropdown đơn vị theo is_attendance_unit và AccessControl (nhất quán với Tạo/Xem).
    - Bỏ cột Ca (UI không dùng), hiển thị team.name giống phần tạo/xem.
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
        # parse date
        try:
            y, m, d = map(int, work_date_str.split("-"))
            work_date = date(y, m, d)
        except Exception:
            work_date = None

        # validate unit against access scope
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