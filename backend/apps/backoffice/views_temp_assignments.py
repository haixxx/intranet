from datetime import datetime as dt, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.utils import audit_log
from apps.hr.models import Employee, TempAssignment
from apps.hr.services import allowed_org_ids_for_user
from apps.organization.models import OrgUnit
from .utils.pagination import paginate_queryset

try:
    from apps.attendance.services_bs import scan_impacts_for_temp_assignment
except Exception:
    scan_impacts_for_temp_assignment = None


def _can_manage_assignments(user):
    return user.has_perm("hr.change_employee")


def _parse_date(value: str, label: str, errors: list[str]):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return dt.strptime(value, "%Y-%m-%d").date()
    except Exception:
        errors.append(f"{label} sai định dạng (YYYY-MM-DD).")
        return None


def _allowed_assignment_units(user):
    scope_units = set(allowed_org_ids_for_user(user))
    return OrgUnit.objects.filter(
        id__in=scope_units,
        is_active=True,
        type__in=[OrgUnit.Type.DEPARTMENT, OrgUnit.Type.DIVISION, OrgUnit.Type.WORKSHOP],
    ).order_by("symbol")


def _validate_to_unit(to_unit, scope_units, errors):
    if not to_unit:
        errors.append("Đơn vị nhận không tồn tại.")
        return
    if to_unit.id not in scope_units:
        errors.append("Đơn vị nhận ngoài phạm vi quyền của bạn.")
    if not to_unit.is_active:
        errors.append("Đơn vị nhận đã ngừng hoạt động.")
    if to_unit.type not in [OrgUnit.Type.DEPARTMENT, OrgUnit.Type.DIVISION, OrgUnit.Type.WORKSHOP]:
        errors.append("Đơn vị nhận phải là Phòng/Ban/Phân xưởng.")


def _add_impact_message(request, summary):
    if not summary:
        return
    draft = summary.get("draft_batches", 0)
    committed = summary.get("committed_batches", 0)
    if draft or committed:
        messages.warning(
            request,
            "Điều động này ảnh hưởng tới bảng công: "
            f"{draft} bảng nháp, {committed} bảng đã chốt. "
            "Hệ thống không tự sửa công đã chốt; cần rà soát/cập nhật roster khi sang module chấm công.",
        )


@login_required
@permission_required("hr.view_employee", raise_exception=True)
def temp_assignment_list(request):
    q = request.GET.get("q", "").strip()
    to_unit = request.GET.get("to_unit", "").strip()
    status = request.GET.get("status", "").strip()
    over60 = request.GET.get("over60", "").strip()

    scope_units = set(allowed_org_ids_for_user(request.user))

    qs = (
        TempAssignment.objects.select_related("employee", "from_unit", "to_unit", "completed_by", "cancelled_by")
        .order_by("-start_date", "-id")
        .filter(Q(employee__unit_id__in=scope_units) | Q(to_unit_id__in=scope_units))
    )

    if q:
        qs = qs.filter(
            Q(employee__full_name__icontains=q)
            | Q(employee__employee_code__icontains=q)
            | Q(employee__card_id__icontains=q)
        )
    if to_unit and to_unit.isdigit():
        qs = qs.filter(to_unit_id=int(to_unit))
    if status in [choice[0] for choice in TempAssignment.Status.choices]:
        qs = qs.filter(status=status)

    if over60 == "1":
        cutoff_date = timezone.localdate() - timedelta(days=60)
        qs = qs.filter(status=TempAssignment.Status.ACTIVE, start_date__lte=cutoff_date)

    units = _allowed_assignment_units(request.user)
    context = paginate_queryset(request, qs, default_page_size=50, allowed_page_sizes=(25, 50, 100, 200))
    context.update(
        {
            "items": context["items"],
            "query": q,
            "to_unit_selected": to_unit,
            "status_selected": status,
            "over60": over60,
            "units": units,
            "status_choices": TempAssignment.Status.choices,
            "manage_allowed": _can_manage_assignments(request.user),
        }
    )

    return render(request, "backoffice/hr/assignments/list.html", context)


@login_required
@permission_required("hr.change_employee", raise_exception=True)
def temp_assignment_create(request):
    scope_units = set(allowed_org_ids_for_user(request.user))
    units = _allowed_assignment_units(request.user)

    if request.method == "POST":
        employee_id = request.POST.get("employee_id", "").strip()
        to_unit_id = request.POST.get("to_unit_id", "").strip()
        start_date_raw = request.POST.get("start_date", "").strip()
        end_date_raw = request.POST.get("end_date", "").strip()
        reason_code = request.POST.get("reason_code", "").strip()
        note = request.POST.get("note", "").strip()
        apply_flag = request.POST.get("apply_flag", "on") in ("on", "true", "1")

        errors = []
        employee = None
        to_unit = None

        if not employee_id or not employee_id.isdigit():
            errors.append("Thiếu hoặc sai employee_id.")
        else:
            employee = Employee.objects.filter(pk=int(employee_id)).select_related("unit").first()
            if not employee:
                errors.append("Nhân sự không tồn tại.")
            elif employee.unit_id not in scope_units:
                errors.append("Nhân sự ngoài phạm vi đơn vị của bạn.")
            elif employee.status != Employee.Status.ACTIVE:
                errors.append("Chỉ được điều động nhân sự đang làm việc.")

        if not to_unit_id or not to_unit_id.isdigit():
            errors.append("Thiếu to_unit_id.")
        else:
            to_unit = OrgUnit.objects.filter(pk=int(to_unit_id)).first()
            _validate_to_unit(to_unit, scope_units, errors)

        parsed_start = _parse_date(start_date_raw, "start_date", errors)
        parsed_end = _parse_date(end_date_raw, "end_date", errors) if end_date_raw else None

        if not parsed_start:
            errors.append("Thiếu start_date.")
        if not reason_code:
            errors.append("Chọn lý do điều động.")
        if employee and to_unit and employee.unit_id == to_unit.id:
            errors.append("Đơn vị nhận không được trùng đơn vị gốc.")

        if errors:
            messages.error(request, "; ".join(errors))
            return redirect("backoffice:temp_assignment_create")

        obj = TempAssignment(
            employee=employee,
            from_unit_id=employee.unit_id,
            to_unit=to_unit,
            start_date=parsed_start,
            end_date=parsed_end,
            planned_end_date=parsed_end,
            reason_code=reason_code,
            note=note,
            status=TempAssignment.Status.ACTIVE,
            apply_flag=apply_flag,
            snapshot_employee_unit_at_create_id=employee.unit_id,
            created_by=request.user,
        )
        try:
            obj.full_clean()
            obj.save()
            summary = scan_impacts_for_temp_assignment(obj) if scan_impacts_for_temp_assignment else None

            audit_log(
                action_verb="CREATE",
                object_type="temp_assignment",
                object_id=obj.id,
                object_repr=f"{employee.employee_code}->{to_unit.symbol}",
                actor=request.user,
                request=request,
                action_code="TEMP_ASSIGNMENT_CREATE",
                extra={"impact_summary": summary or {}},
            )
            messages.success(request, "Đã tạo điều động.")
            _add_impact_message(request, summary)
            return redirect("backoffice:temp_assignment_list")
        except Exception as e:
            messages.error(request, f"Lỗi: {e}")
            return redirect("backoffice:temp_assignment_create")

    employees = (
        Employee.objects.filter(unit_id__in=scope_units, status=Employee.Status.ACTIVE)
        .select_related("unit", "team", "job_title")
        .order_by("employee_code")
    )
    return render(
        request,
        "backoffice/hr/assignments/form.html",
        {
            "employees": employees,
            "units": units,
            "reasons": TempAssignment.Reason.choices,
            "obj": None,
            "is_edit": False,
        },
    )


@login_required
@permission_required("hr.change_employee", raise_exception=True)
def temp_assignment_edit(request, pk: int):
    obj = get_object_or_404(
        TempAssignment.objects.select_related("employee", "from_unit", "to_unit"),
        pk=pk,
    )

    scope_units = set(allowed_org_ids_for_user(request.user))
    if obj.employee.unit_id not in scope_units and obj.to_unit_id not in scope_units:
        messages.error(request, "Bạn không có quyền sửa điều động này.")
        return redirect("backoffice:temp_assignment_list")

    if obj.status != TempAssignment.Status.ACTIVE:
        messages.warning(request, "Chỉ được sửa phiếu đang ACTIVE. Phiếu đã hoàn thành/hết hạn/hủy chỉ dùng để tra cứu.")
        return redirect("backoffice:temp_assignment_list")

    units = _allowed_assignment_units(request.user)

    if request.method == "POST":
        to_unit_id = request.POST.get("to_unit_id", "").strip()
        start_date_raw = request.POST.get("start_date", "").strip()
        end_date_raw = request.POST.get("end_date", "").strip()
        reason_code = request.POST.get("reason_code", "").strip()
        note = request.POST.get("note", "").strip()
        apply_flag = request.POST.get("apply_flag", "on") in ("on", "true", "1")

        errors = []
        to_unit = None

        if not to_unit_id or not to_unit_id.isdigit():
            errors.append("Thiếu to_unit_id.")
        else:
            to_unit = OrgUnit.objects.filter(pk=int(to_unit_id)).first()
            _validate_to_unit(to_unit, scope_units, errors)

        parsed_start = _parse_date(start_date_raw, "start_date", errors)
        parsed_end = _parse_date(end_date_raw, "end_date", errors) if end_date_raw else None

        if not parsed_start:
            errors.append("Thiếu start_date.")
        if not reason_code:
            errors.append("Chọn lý do điều động.")
        if to_unit and obj.from_unit_id == to_unit.id:
            errors.append("Đơn vị nhận không được trùng đơn vị gốc.")

        if errors:
            messages.error(request, "; ".join(errors))
            return redirect("backoffice:temp_assignment_edit", pk=obj.id)

        old = {
            "to_unit_id": obj.to_unit_id,
            "start_date": obj.start_date.isoformat() if obj.start_date else None,
            "end_date": obj.end_date.isoformat() if obj.end_date else None,
            "reason_code": obj.reason_code,
            "note": obj.note,
            "apply_flag": obj.apply_flag,
        }

        obj.to_unit = to_unit
        obj.start_date = parsed_start
        obj.end_date = parsed_end
        if obj.planned_end_date is None:
            obj.planned_end_date = parsed_end
        obj.reason_code = reason_code
        obj.note = note
        obj.apply_flag = apply_flag

        try:
            obj.full_clean()
            obj.save()
            summary = scan_impacts_for_temp_assignment(obj) if scan_impacts_for_temp_assignment else None

            audit_log(
                action_verb="UPDATE",
                object_type="temp_assignment",
                object_id=obj.id,
                object_repr=str(obj.id),
                actor=request.user,
                request=request,
                action_code="TEMP_ASSIGNMENT_UPDATE",
                changes={
                    "to_unit_id": {"old": old["to_unit_id"], "new": obj.to_unit_id},
                    "start_date": {"old": old["start_date"], "new": obj.start_date.isoformat() if obj.start_date else None},
                    "end_date": {"old": old["end_date"], "new": obj.end_date.isoformat() if obj.end_date else None},
                    "reason_code": {"old": old["reason_code"], "new": obj.reason_code},
                    "note": {"old": old["note"], "new": obj.note},
                    "apply_flag": {"old": old["apply_flag"], "new": obj.apply_flag},
                },
                extra={"impact_summary": summary or {}},
            )
            messages.success(request, "Đã cập nhật điều động.")
            _add_impact_message(request, summary)
            return redirect("backoffice:temp_assignment_list")
        except Exception as e:
            messages.error(request, f"Lỗi: {e}")
            return redirect("backoffice:temp_assignment_edit", pk=obj.id)

    employees = Employee.objects.filter(id=obj.employee_id)
    return render(
        request,
        "backoffice/hr/assignments/form.html",
        {
            "employees": employees,
            "units": units,
            "reasons": TempAssignment.Reason.choices,
            "obj": obj,
            "is_edit": True,
        },
    )


@login_required
@permission_required("hr.change_employee", raise_exception=True)
def temp_assignment_complete(request, pk):
    obj = get_object_or_404(
        TempAssignment.objects.select_related("employee", "to_unit", "from_unit"),
        pk=pk,
    )
    scope_units = set(allowed_org_ids_for_user(request.user))
    if obj.employee.unit_id not in scope_units and obj.to_unit_id not in scope_units:
        messages.error(request, "Bạn không có quyền hoàn thành điều động này.")
        return redirect("backoffice:temp_assignment_list")

    if obj.status != TempAssignment.Status.ACTIVE:
        messages.warning(request, "Chỉ được hoàn thành điều động đang ACTIVE.")
        return redirect("backoffice:temp_assignment_list")

    if request.method == "POST":
        actual_end_raw = request.POST.get("actual_end_date", "").strip()
        note = request.POST.get("completed_note", "").strip()
        errors = []
        actual_end_date = _parse_date(actual_end_raw, "Ngày hoàn thành", errors)
        if not actual_end_date:
            errors.append("Thiếu ngày hoàn thành thực tế.")

        if errors:
            messages.error(request, "; ".join(errors))
            return redirect("backoffice:temp_assignment_complete", pk=obj.id)

        old_end_date = obj.end_date
        old_status = obj.status

        try:
            obj.complete(actual_end_date=actual_end_date, user=request.user, note=note)

            # Nếu hoàn thành sớm, vùng bị ảnh hưởng thường là từ ngày sau ngày hoàn thành
            # tới ngày kết thúc dự kiến cũ. Nếu trước đây không có end_date, scan các batch/commit đã tồn tại về sau.
            scan_start, scan_end = obj.affected_range_after_completion(old_end_date=old_end_date)
            summary = scan_impacts_for_temp_assignment(obj, start_date=scan_start, end_date=scan_end) if scan_impacts_for_temp_assignment else None

            audit_log(
                action_verb="UPDATE",
                object_type="temp_assignment",
                object_id=obj.id,
                object_repr=str(obj.id),
                actor=request.user,
                request=request,
                action_code="TEMP_ASSIGNMENT_COMPLETE",
                changes={
                    "status": {"old": old_status, "new": obj.status},
                    "end_date": {"old": old_end_date.isoformat() if old_end_date else None, "new": obj.end_date.isoformat() if obj.end_date else None},
                    "completed_note": {"old": "", "new": note},
                },
                extra={"impact_summary": summary or {}},
            )
            messages.success(request, "Đã hoàn thành điều động.")
            _add_impact_message(request, summary)
            return redirect("backoffice:temp_assignment_list")
        except Exception as e:
            messages.error(request, f"Lỗi: {e}")
            return redirect("backoffice:temp_assignment_complete", pk=obj.id)

    default_actual_end_date = timezone.localdate()
    if obj.end_date and obj.end_date < default_actual_end_date:
        default_actual_end_date = obj.end_date

    return render(
        request,
        "backoffice/hr/assignments/confirm_complete.html",
        {
            "obj": obj,
            "default_actual_end_date": default_actual_end_date,
        },
    )


@login_required
@permission_required("hr.change_employee", raise_exception=True)
def temp_assignment_cancel(request, pk):
    obj = get_object_or_404(
        TempAssignment.objects.select_related("employee", "to_unit", "from_unit"),
        pk=pk,
    )
    scope_units = set(allowed_org_ids_for_user(request.user))
    if obj.employee.unit_id not in scope_units and obj.to_unit_id not in scope_units:
        messages.error(request, "Bạn không có quyền hủy điều động này.")
        return redirect("backoffice:temp_assignment_list")

    if request.method == "POST":
        if obj.status == TempAssignment.Status.ACTIVE:
            old_status = obj.status
            try:
                obj.cancel(user=request.user)
                summary = scan_impacts_for_temp_assignment(obj) if scan_impacts_for_temp_assignment else None

                audit_log(
                    action_verb="UPDATE",
                    object_type="temp_assignment",
                    object_id=obj.id,
                    object_repr=str(obj.id),
                    actor=request.user,
                    request=request,
                    action_code="TEMP_ASSIGNMENT_CANCEL",
                    changes={"status": {"old": old_status, "new": obj.status}},
                    extra={"impact_summary": summary or {}},
                )
                messages.success(request, "Đã hủy điều động.")
                _add_impact_message(request, summary)
            except Exception as e:
                messages.error(request, f"Lỗi: {e}")
        else:
            messages.warning(request, "Trạng thái hiện tại không phải ACTIVE.")
        return redirect("backoffice:temp_assignment_list")

    return render(
        request,
        "backoffice/hr/assignments/confirm_cancel.html",
        {
            "obj": obj,
        },
    )
