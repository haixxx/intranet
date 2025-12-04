from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
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

# Employee & AccessControl theo repo
from apps.hr.models import Employee, AccessControl
# TempAssignment (điều động tạm thời) nếu có
try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:
    TempAssignment = None

# Ca mặc định (24h)
DEFAULT_SHIFT_TIMES = {
    "DAY": {"in1": time(7, 0), "out1": time(11, 0), "in2": time(13, 0), "out2": time(17, 0)},
    "MORNING": {"in1": time(6, 0), "out1": time(14, 0), "in2": None, "out2": None},
    "AFTERNOON": {"in1": time(14, 0), "out1": time(22, 0), "in2": None, "out2": None},
    "NIGHT": {"in1": time(22, 0), "out1": time(6, 0), "in2": None, "out2": None},
}

def _round_to_hour_if_needed(t: time | None, settings: AttendanceSettings | None) -> time | None:
    if not t:
        return t
    if settings and getattr(settings, "round_registration_to_hour", False):
        return time(t.hour, 0, 0)
    return t

def _populate_default_times(item: AttendanceBatchItem, shift_key: str, settings: AttendanceSettings | None):
    cfg = DEFAULT_SHIFT_TIMES.get(shift_key)
    if not cfg:
        return
    item.in1 = _round_to_hour_if_needed(cfg.get("in1"), settings)
    item.out1 = _round_to_hour_if_needed(cfg.get("out1"), settings)
    item.in2 = _round_to_hour_if_needed(cfg.get("in2"), settings)
    item.out2 = _round_to_hour_if_needed(cfg.get("out2"), settings)

def _units_for_attendance(request):
    """
    Trả về danh sách đơn vị được phép chấm công, giới hạn theo AccessControl của user.
    - Chỉ lấy OrgUnit.is_attendance_unit=True và is_active=True.
    - Scope:
      + ALL_ORG: toàn bộ hệ thống
      + UNIT_SUBTREE: cây con của root_org_unit
      + PLANT_SUBTREE: cây con của nhà máy chứa root_org_unit
    """
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

@login_required
def batch_create_or_load(request):
    """
    Tạo/Xem chấm công:
    - Chỉ lập danh sách nhân sự ACTIVE của đơn vị được chọn (đơn vị chấm công).
    - Lọc tổ theo tên team.name.
    - Dropdown đơn vị hiển thị tên đơn vị.
    - Khi bấm 'Xem' mà chưa có danh sách, hiển thị thông báo gợi ý lập danh sách.
    """
    if not request.user.has_perm("attendance.view_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancebatch",
            "title": "Bạn chưa được cấp quyền xem Tạo/Xem chấm công"
        }, status=403)

    work_date_str = request.GET.get("date", "")
    unit_id = request.GET.get("unit", "")
    q = request.GET.get("q", "").strip()
    team = request.GET.get("team", "").strip()
    page = int(request.GET.get("page", "1") or "1")
    per_page = 50

    units_qs = _units_for_attendance(request)
    batch = None
    items = AttendanceBatchItem.objects.none()
    total_count = 0

    if work_date_str and unit_id:
        # Parse ngày
        try:
            y, m, d = map(int, work_date_str.split("-"))
            work_date = date(y, m, d)
        except Exception:
            messages.warning(request, "Ngày không hợp lệ.")
            work_date = None

        # Lấy unit, kiểm tra cờ chấm công và quyền
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

        if work_date and unit:
            batch = AttendanceBatch.objects.filter(unit=unit, work_date=work_date).first()

            # Nếu bấm 'Xem' mà chưa có danh sách -> gợi ý lập
            if request.GET.get("init") != "1" and not batch:
                messages.info(request, f"Chưa có danh sách điểm danh cho đơn vị {unit.name} ngày {work_date_str}. Vui lòng bấm 'Lập danh sách đăng ký công' để tạo.")

            # Lập danh sách mới
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

                # Nhân sự ACTIVE thuộc đơn vị
                base_qs = Employee.objects.filter(
                    unit=unit,
                    status=Employee.Status.ACTIVE
                )

                # Bổ sung BS đến/đi nếu có TempAssignment
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

                code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
                code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()
                settings = AttendanceSettings.objects.first()

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

                    it.shift = AttendanceBatchItem.Shift.DAY
                    _populate_default_times(it, "DAY", settings)
                    it.save()

                messages.success(request, f"Đã lập danh sách nháp cho {unit.name} ngày {work_date_str}.")

            # Load items + filter + paginate
            if batch:
                qs = batch.items.select_related("employee", "code").order_by("employee__employee_code")
                if q:
                    qs = qs.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
                if team:
                    qs = qs.filter(employee__team__name__icontains=team, employee__unit=unit)
                total_count = qs.count()
                start = (page - 1) * per_page
                end = start + per_page
                items = qs[start:end]

    can_save = request.user.has_perm("attendance.change_attendancebatch")
    can_commit = request.user.has_perm("attendance.add_attendancecommit")
    can_request = request.user.has_perm("attendance.add_attendancecorrectionrequest")

    has_committed = False
    if batch:
        has_committed = AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).exists()

    codes_qs = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code")
    total_pages = (total_count + per_page - 1) // per_page if total_count else 1

    return render(request, "backoffice/attendance/batch_create_or_load.html", {
        "units_qs": units_qs,
        "batch": batch,
        "items": items,
        "work_date": work_date_str,
        "unit_id": unit_id,
        "q": q,
        "team": team,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_count": total_count,
        "can_save": can_save,
        "can_commit": can_commit,
        "can_request": can_request,
        "has_committed": has_committed,
        "codes_qs": codes_qs,
    })

@login_required
def batch_save(request, batch_id):
    """
    Lưu nháp: ghi các thay đổi từ bảng vào DB.
    """
    batch = get_object_or_404(AttendanceBatch, pk=batch_id)
    if not request.user.has_perm("attendance.change_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.change_attendancebatch",
            "title": "Bạn chưa được cấp quyền lưu Batch"
        }, status=403)

    settings = AttendanceSettings.objects.first()

    def parse_time(val):
        if not val:
            return None
        try:
            hh, mm = map(int, val.split(":"))
            return _round_to_hour_if_needed(time(hh, mm), settings)
        except Exception:
            return None

    updated = 0
    for it in batch.items.all():
        code_val = request.POST.get(f"code_{it.id}")
        shift_val = request.POST.get(f"shift_{it.id}")
        in1_val = request.POST.get(f"in1_{it.id}")
        out1_val = request.POST.get(f"out1_{it.id}")
        in2_val = request.POST.get(f"in2_{it.id}")
        out2_val = request.POST.get(f"out2_{it.id}")
        notes_val = request.POST.get(f"notes_{it.id}", "")

        if code_val:
            code_obj = AttendanceCode.objects.filter(pk=int(code_val)).first()
            if code_obj:
                it.code = code_obj
        if shift_val:
            it.shift = shift_val

        it.in1 = parse_time(in1_val)
        it.out1 = parse_time(out1_val)
        it.in2 = parse_time(in2_val)
        it.out2 = parse_time(out2_val)
        it.notes = notes_val
        it.save()
        updated += 1

    audit_log(action_verb="SAVE", object_type="attendance_batch", object_id=batch.id,
              object_repr=f"{batch.unit.code}-{batch.work_date}", actor=request.user,
              changes={"count": updated}, request=request, action_code="ATT_BATCH_SAVE")
    messages.success(request, f"Đã lưu {updated} dòng.")
    return redirect("backoffice:attendance_batch_create_or_load")

@login_required
def batch_commit(request, batch_id):
    """
    Chốt danh sách: kiểm tra mốc theo mã, tạo snapshot Commit, khóa Draft.
    """
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
        if it.code.segments_am_type == AttendanceCode.SegmentType.WORK and it.code.requires_am_work:
            if not it.in1 or not it.out1:
                errors.append(f"{it.employee.employee_code} thiếu mốc sáng (IN1/OUT1).")
        if it.code.segments_pm_type == AttendanceCode.SegmentType.WORK and it.code.requires_pm_work:
            if not it.in2 or not it.out2:
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
    - Dropdown đơn vị theo is_attendance_unit và AccessControl.
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