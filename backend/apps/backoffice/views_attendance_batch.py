from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from datetime import date, time

from apps.audit.utils import audit_log
from apps.hr.models import Employee
from apps.organization.models import OrgUnit
from apps.attendance.models import AttendanceCode, AttendanceSettings
from apps.attendance.models_batch import (
    AttendanceBatch, AttendanceBatchItem,
    AttendanceCommit, AttendanceCommitItem,
    AttendanceCorrectionRequest
)

# Fallback import TempAssignment ở vị trí đúng (nếu chưa có, vẫn chạy được không có BS đến/đi)
TempAssignment = None
try:
    from apps.organization.models_temp import TempAssignment as TempAssignment  # nếu có module phụ
except Exception:
    try:
        from apps.hr.models import TempAssignment as TempAssignment  # thử trong hr
    except Exception:
        try:
            from apps.organization.models import TempAssignment as TempAssignment  # thử lại trong organization
        except Exception:
            TempAssignment = None

# Helpers: default shift times (cứng theo yêu cầu)
DEFAULT_SHIFT_TIMES = {
    "DAY": {"in1": time(7, 0), "out1": time(11, 0), "in2": time(13, 0), "out2": time(17, 0)},
    "MORNING": {"in1": time(6, 0), "out1": time(14, 0), "in2": None, "out2": None},
    "AFTERNOON": {"in1": time(14, 0), "out1": time(22, 0), "in2": None, "out2": None},
    "NIGHT": {"in1": time(22, 0), "out1": time(6, 0), "in2": None, "out2": None},
}


def _round_to_hour_if_needed(t: time | None, settings: AttendanceSettings | None) -> time | None:
    if not t:
        return t
    if settings and settings.round_registration_to_hour:
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


@login_required
def batch_create_or_load(request):
    """
    Menu: Tạo/Xem chấm công (Draft theo ngày + đơn vị)
    - Bộ lọc: work_date, unit (+ q, team khi có batch)
    - Nút 'Lập danh sách đăng ký công' để tạo Draft nếu chưa có; nếu có Draft thì load ra để chỉnh
    - Bộ 'Áp dụng hàng loạt' cho kết quả đang lọc
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

    # Danh sách đơn vị khả dụng (dùng trong dropdown)
    try:
        from apps.hr.services import allowed_org_ids_for_user
        unit_ids = allowed_org_ids_for_user(request.user)
        units_qs = OrgUnit.objects.filter(id__in=list(unit_ids)).order_by("code")
    except Exception:
        units_qs = OrgUnit.objects.all().order_by("code")

    batch = None
    items = AttendanceBatchItem.objects.none()

    if work_date_str and unit_id:
        try:
            y, m, d = map(int, work_date_str.split("-"))
            work_date = date(y, m, d)
        except Exception:
            messages.warning(request, "Ngày không hợp lệ.")
            work_date = None

        try:
            unit = OrgUnit.objects.get(pk=int(unit_id))
        except Exception:
            unit = None
            messages.warning(request, "Đơn vị không hợp lệ.")

        if work_date and unit:
            batch = AttendanceBatch.objects.filter(unit=unit, work_date=work_date).first()
            if request.GET.get("init") == "1" and not batch:
                # Lập danh sách mới (Draft)
                if not request.user.has_perm("attendance.add_attendancebatch"):
                    return render(request, "backoffice/no_permission.html", {
                        "perm_codename": "attendance.add_attendancebatch",
                        "title": "Bạn chưa được cấp quyền tạo Batch chấm công"
                    }, status=403)

                batch = AttendanceBatch.objects.create(
                    unit=unit, work_date=work_date, status=AttendanceBatch.Status.DRAFT, created_by=request.user
                )

                # Tập hợp nhân sự Active đơn vị gốc
                base_qs = Employee.objects.filter(is_active=True, unit=unit)

                # IDs bổ sung đến/đi nếu có TempAssignment
                bs_in_ids = []
                bs_out_ids = []
                if TempAssignment is not None:
                    try:
                        bs_in_ids = list(TempAssignment.objects.filter(
                            apply_flag=True, to_unit=unit, status="ACTIVE"
                        ).values_list("employee_id", flat=True))
                        bs_out_ids = list(TempAssignment.objects.filter(
                            apply_flag=True, from_unit=unit, status="ACTIVE"
                        ).values_list("employee_id", flat=True))
                    except Exception:
                        bs_in_ids = []
                        bs_out_ids = []

                # Hợp nhất: Active + BS đến + BS đi (BS đi chỉ hiển thị quản lý)
                employees = Employee.objects.filter(
                    Q(id__in=base_qs.values_list("id", flat=True)) |
                    Q(id__in=bs_in_ids) |
                    Q(id__in=bs_out_ids)
                ).distinct().order_by("employee_code")

                # LL mặc định, BS_OUT set code "BS"
                code_ll = AttendanceCode.objects.filter(code="LL", is_active=True).first()
                code_bs = AttendanceCode.objects.filter(code="BS", is_active=True).first()
                settings = AttendanceSettings.objects.first()

                for emp in employees:
                    bs_in = TempAssignment is not None and TempAssignment.objects.filter(apply_flag=True, to_unit=unit, status="ACTIVE", employee=emp).exists()
                    bs_out = TempAssignment is not None and TempAssignment.objects.filter(apply_flag=True, from_unit=unit, status="ACTIVE", employee=emp).exists()

                    item = AttendanceBatchItem(batch=batch, employee=emp)
                    if bs_out and not bs_in:
                        # BS đi: chỉ hiển thị quản lý, không tính công tại đơn vị gốc
                        item.bs_direction = AttendanceBatchItem.BSDirection.OUT
                        item.include_in_unit = False
                        item.code = code_bs if code_bs else (code_ll or AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first())
                    else:
                        # Normal hoặc BS đến: tính công tại đơn vị này
                        item.bs_direction = AttendanceBatchItem.BSDirection.IN if (bs_in and not bs_out) else AttendanceBatchItem.BSDirection.NONE
                        item.include_in_unit = True
                        item.code = code_ll or AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code").first()

                    # Gán ca và mốc mặc định (DAY)
                    item.shift = AttendanceBatchItem.Shift.DAY
                    _populate_default_times(item, "DAY", settings)
                    item.save()

                messages.success(request, f"Đã lập danh sách nháp cho {unit.code} ngày {work_date_str}.")

            # Load items và lọc phụ
            if batch:
                items = batch.items.select_related("employee", "code").order_by("employee__employee_code")
                if q:
                    items = items.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
                if team:
                    items = items.filter(employee__team__icontains=team)

    # Quyền nút
    can_save = request.user.has_perm("attendance.change_attendancebatch")
    can_commit = request.user.has_perm("attendance.add_attendancecommit")
    can_request = request.user.has_perm("attendance.add_attendancecorrectionrequest")

    # Kiểm tra đã có committed chưa
    has_committed = False
    if batch:
        has_committed = AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).exists()

    # Query danh sách mã chế độ để dùng trong template (tránh gọi ORM trong template)
    codes_qs = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code")

    return render(request, "backoffice/attendance/batch_create_or_load.html", {
        "units_qs": units_qs,
        "batch": batch,
        "items": items[:2000],
        "work_date": work_date_str,
        "unit_id": unit_id,
        "q": q,
        "team": team,
        "can_save": can_save,
        "can_commit": can_commit,
        "can_request": can_request,
        "has_committed": has_committed,
        "codes_qs": codes_qs,
    })


@login_required
def batch_apply_bulk(request, batch_id):
    """
    Áp dụng hàng loạt cho kết quả đang lọc.
    Fields: code_id, shift_key, in1, out1, in2, out2
    """
    batch = get_object_or_404(AttendanceBatch, pk=batch_id)
    if not request.user.has_perm("attendance.change_attendancebatch"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.change_attendancebatch",
            "title": "Bạn chưa được cấp quyền cập nhật Batch"
        }, status=403)

    code_id = request.POST.get("code_id")
    shift_key = request.POST.get("shift_key", "")
    in1 = request.POST.get("in1") or None
    out1 = request.POST.get("out1") or None
    in2 = request.POST.get("in2") or None
    out2 = request.POST.get("out2") or None

    q = request.POST.get("q", "").strip()
    team = request.POST.get("team", "").strip()

    qs = batch.items.select_related("employee", "code")
    if q:
        qs = qs.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
    if team:
        qs = qs.filter(employee__team__icontains=team)

    settings = AttendanceSettings.objects.first()
    code = AttendanceCode.objects.filter(pk=code_id).first() if code_id else None

    def parse_time(val):
        if not val:
            return None
        try:
            hh, mm = map(int, val.split(":"))
            return _round_to_hour_if_needed(time(hh, mm), settings)
        except Exception:
            return None

    in1_t = parse_time(in1)
    out1_t = parse_time(out1)
    in2_t = parse_time(in2)
    out2_t = parse_time(out2)

    updated = 0
    for it in qs:
        if code:
            it.code = code
        if shift_key:
            it.shift = shift_key
            if not in1 and not out1 and not in2 and not out2:
                _populate_default_times(it, shift_key, settings)
        if in1 is not None:
            it.in1 = in1_t
        if out1 is not None:
            it.out1 = out1_t
        if in2 is not None:
            it.in2 = in2_t
        if out2 is not None:
            it.out2 = out2_t
        it.save()
        updated += 1

    audit_log(action_verb="BULK_APPLY", object_type="attendance_batch", object_id=batch.id,
              object_repr=f"{batch.unit.code}-{batch.work_date}", actor=request.user,
              changes={"count": updated}, request=request, action_code="ATT_BATCH_BULK_APPLY")
    messages.success(request, f"Đã áp dụng hàng loạt cho {updated} dòng.")
    return redirect("backoffice:attendance_batch_create_or_load")


@login_required
def batch_save(request, batch_id):
    """
    Lưu nháp: cập nhật các item gửi từ form (post list)
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
    Chốt: validate mốc theo mã, tạo snapshot Commit và khóa Draft
    """
    batch = get_object_or_404(AttendanceBatch, pk=batch_id)
    if not request.user.has_perm("attendance.add_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.add_attendancecommit",
            "title": "Bạn chưa được cấp quyền chốt Batch"
        }, status=403)

    # Không cho chốt nếu đã có committed
    if AttendanceCommit.objects.filter(unit=batch.unit, work_date=batch.work_date).exists():
        messages.warning(request, "Ngày + đơn vị này đã có danh sách đã chốt.")
        return redirect("backoffice:attendance_batch_create_or_load")

    # Validate theo mã chế độ
    errors = []
    for it in batch.items.select_related("code", "employee"):
        # WORK AM yêu cầu IN1/OUT1 nếu requires_am_work=True
        if it.code.segments_am_type == AttendanceCode.SegmentType.WORK and it.code.requires_am_work:
            if not it.in1 or not it.out1:
                errors.append(f"{it.employee.employee_code} thiếu mốc sáng (IN1/OUT1).")
        # WORK PM yêu cầu IN2/OUT2 nếu requires_pm_work=True
        if it.code.segments_pm_type == AttendanceCode.SegmentType.WORK and it.code.requires_pm_work:
            if not it.in2 or not it.out2:
                errors.append(f"{it.employee.employee_code} thiếu mốc chiều (IN2/OUT2).")

    if errors:
        messages.error(request, "Không thể chốt. Vui lòng bổ sung mốc cho các dòng sau:\n" + "\n".join(errors))
        return redirect("backoffice:attendance_batch_create_or_load")

    # Tạo commit snapshot
    commit = AttendanceCommit.objects.create(
        unit=batch.unit, work_date=batch.work_date, committed_by=request.user
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

    # Khóa draft
    batch.status = AttendanceBatch.Status.LOCKED_DRAFT
    batch.save()

    audit_log(action_verb="COMMIT", object_type="attendance_batch", object_id=batch.id,
              object_repr=f"{batch.unit.code}-{batch.work_date}", actor=request.user,
              changes={"commit_id": commit.id}, request=request, action_code="ATT_BATCH_COMMIT")
    messages.success(request, "Đã chốt danh sách chấm công.")
    return redirect("backoffice:attendance_committed_view")


@login_required
def committed_view(request):
    """
    Menu: Xem công chốt (read-only)
    - Bộ lọc: work_date, unit, q, team
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

    items = AttendanceCommitItem.objects.none()

    if work_date_str and unit_id:
        try:
            y, m, d = map(int, work_date_str.split("-"))
            work_date = date(y, m, d)
        except Exception:
            work_date = None
        try:
            unit = OrgUnit.objects.get(pk=int(unit_id))
        except Exception:
            unit = None

        if work_date and unit:
            commit = AttendanceCommit.objects.filter(unit=unit, work_date=work_date).first()
            if commit:
                items = commit.items.select_related("employee", "code").order_by("employee__employee_code")
                if q:
                    items = items.filter(Q(employee__employee_code__icontains=q) | Q(employee__full_name__icontains=q))
                if team:
                    items = items.filter(employee__team__icontains=team)

    return render(request, "backoffice/attendance/committed_view.html", {
        "units_qs": OrgUnit.objects.all().order_by("code"),  # tiện chọn lại nhanh ở trang xem
        "items": items[:2000],
        "work_date": work_date_str,
        "unit_id": unit_id,
        "q": q,
        "team": team,
    })