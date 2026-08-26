from datetime import date as date_cls
import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.utils import audit_log
from apps.backoffice.utils.permissions import permission_or_message
from apps.hr.forms import EmployeeForm
from apps.hr.models import AccessControl, Employee, TempAssignment
from apps.hr.services import allowed_org_ids_for_user
from apps.organization.models import JobTitle, OrgUnit

User = get_user_model()

# Mật khẩu mặc định khi tạo tài khoản từ danh sách nhân sự.
# Lưu ý: Django vẫn lưu dạng hash, không lưu plain-text trong DB.
DEFAULT_EMPLOYEE_USER_PASSWORD = "123456"

VN_MAP = {
    ord("á"): "a", ord("à"): "a", ord("ả"): "a", ord("ã"): "a", ord("ạ"): "a",
    ord("ă"): "a", ord("ắ"): "a", ord("ằ"): "a", ord("ẳ"): "a", ord("ẵ"): "a", ord("ặ"): "a",
    ord("â"): "a", ord("ấ"): "a", ord("ầ"): "a", ord("ẩ"): "a", ord("ẫ"): "a", ord("ậ"): "a",
    ord("đ"): "d",
    ord("é"): "e", ord("è"): "e", ord("ẻ"): "e", ord("ẽ"): "e", ord("ẹ"): "e",
    ord("ê"): "e", ord("ế"): "e", ord("ề"): "e", ord("ể"): "e", ord("ễ"): "e", ord("ệ"): "e",
    ord("í"): "i", ord("ì"): "i", ord("ỉ"): "i", ord("ĩ"): "i", ord("ị"): "i",
    ord("ó"): "o", ord("ò"): "o", ord("ỏ"): "o", ord("õ"): "o", ord("ọ"): "o",
    ord("ô"): "o", ord("ố"): "o", ord("ồ"): "o", ord("ổ"): "o", ord("ỗ"): "o", ord("ộ"): "o",
    ord("ơ"): "o", ord("ớ"): "o", ord("ờ"): "o", ord("ở"): "o", ord("ỡ"): "o", ord("ợ"): "o",
    ord("ú"): "u", ord("ù"): "u", ord("ủ"): "u", ord("ũ"): "u", ord("ụ"): "u",
    ord("ư"): "u", ord("ứ"): "u", ord("ừ"): "u", ord("ử"): "u", ord("ữ"): "u", ord("ự"): "u",
    ord("ý"): "y", ord("ỳ"): "y", ord("ỷ"): "y", ord("ỹ"): "y", ord("ỵ"): "y",
    ord("Á"): "a", ord("À"): "a", ord("Ả"): "a", ord("Ã"): "a", ord("Ạ"): "a",
    ord("Ă"): "a", ord("Ắ"): "a", ord("Ằ"): "a", ord("Ẳ"): "a", ord("Ẵ"): "a", ord("Ặ"): "a",
    ord("Â"): "a", ord("Ấ"): "a", ord("Ầ"): "a", ord("Ẩ"): "a", ord("Ẫ"): "a", ord("Ậ"): "a",
    ord("Đ"): "d",
    ord("É"): "e", ord("È"): "e", ord("Ẻ"): "e", ord("Ẽ"): "e", ord("Ẹ"): "e",
    ord("Ê"): "e", ord("Ế"): "e", ord("Ề"): "e", ord("Ể"): "e", ord("Ễ"): "e", ord("Ệ"): "e",
    ord("Í"): "i", ord("Ì"): "i", ord("Ỉ"): "i", ord("Ĩ"): "i", ord("Ị"): "i",
    ord("Ó"): "o", ord("Ò"): "o", ord("Ỏ"): "o", ord("Õ"): "o", ord("Ọ"): "o",
    ord("Ô"): "o", ord("Ố"): "o", ord("Ồ"): "o", ord("Ổ"): "o", ord("Ỗ"): "o", ord("Ộ"): "o",
    ord("Ơ"): "o", ord("Ớ"): "o", ord("Ờ"): "o", ord("Ở"): "o", ord("Ỡ"): "o", ord("Ợ"): "o",
    ord("Ú"): "u", ord("Ù"): "u", ord("Ủ"): "u", ord("Ũ"): "u", ord("Ụ"): "u",
    ord("Ư"): "u", ord("Ứ"): "u", ord("Ừ"): "u", ord("Ử"): "u", ord("Ữ"): "u", ord("Ự"): "u",
    ord("Ý"): "y", ord("Ỳ"): "y", ord("Ỷ"): "y", ord("Ỹ"): "y", ord("Ỵ"): "y",
}



def can_view_sensitive_employee_data(user) -> bool:
    """
    Quyền xem thông tin nhạy cảm của nhân sự trên giao diện.

    Không tạo migration trong giai đoạn này. Quản trị có thể cấu hình bằng nhóm:
    - HR_ADMIN
    - HR_SENSITIVE_VIEWER
    - HR_SENSITIVE_EXPORTER

    HR_SENSITIVE_EXPORTER cũng được xem để đối chiếu trước khi xuất.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(
        name__in=["HR_MANAGER", "HR_ADMIN", "HR_SENSITIVE_VIEWER", "HR_SENSITIVE_EXPORTER"]
    ).exists()


def can_export_sensitive_employee_data(user) -> bool:
    """
    Quyền tải về thông tin nhạy cảm của nhân sự.

    Nhóm đề xuất:
    - HR_ADMIN
    - HR_SENSITIVE_EXPORTER
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=["HR_MANAGER", "HR_ADMIN", "HR_SENSITIVE_EXPORTER"]).exists()


def vn_slug(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "", s.translate(VN_MAP).lower())


def _no_scope_permission(request):
    return render(
        request,
        "backoffice/no_permission.html",
        {
            "perm_codename": "scope:UNIT_SUBTREE/PLANT_SUBTREE/ALL_ORG",
            "title": "Bạn chưa được cấp quyền",
        },
        status=200,
    )


@login_required
@permission_or_message("hr.view_employee")
def employee_list(request):
    q = request.GET.get("q", "").strip()
    units_param = request.GET.get("units", "").strip()
    jt_filter = request.GET.get("job_title", "").strip()
    team_filter = request.GET.get("team", "").strip()

    units_selected = []
    if units_param:
        for part in units_param.split(","):
            if part.strip().isdigit():
                units_selected.append(int(part.strip()))

    page = request.GET.get("page", "1")
    page_size_raw = request.GET.get("page_size", "").strip()
    try:
        page_size = int(page_size_raw) if page_size_raw else 25
    except ValueError:
        page_size = 25
    if page_size <= 0 or page_size > 500:
        page_size = 25

    scope_unit_ids = set(allowed_org_ids_for_user(request.user))
    qs_base = Employee.objects.select_related("job_title", "unit", "team").filter(unit_id__in=scope_unit_ids)

    if units_selected:
        valid_units = [u for u in units_selected if u in scope_unit_ids]
        qs = qs_base.filter(unit_id__in=valid_units) if valid_units else qs_base.none()
    else:
        qs = qs_base

    if jt_filter:
        qs = qs.filter(job_title_id=jt_filter)
    if team_filter:
        qs = qs.filter(team_id=team_filter)
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q)
            | Q(employee_code__icontains=q)
            | Q(card_id__icontains=q)
        )

    qs = qs.order_by("employee_code")

    units = OrgUnit.objects.filter(
        id__in=scope_unit_ids,
        type__in=[
            OrgUnit.Type.DEPARTMENT,
            OrgUnit.Type.DIVISION,
            OrgUnit.Type.WORKSHOP,
        ],
    ).order_by("symbol")

    if len(units_selected) == 1:
        teams = OrgUnit.objects.filter(type=OrgUnit.Type.TEAM, parent_id=units_selected[0]).order_by("symbol")
    elif len(units_selected) > 1:
        teams = OrgUnit.objects.filter(type=OrgUnit.Type.TEAM, parent_id__in=units_selected).order_by("symbol")
    else:
        teams = OrgUnit.objects.filter(type=OrgUnit.Type.TEAM, id__in=scope_unit_ids).order_by("symbol")

    job_titles = JobTitle.objects.filter(is_active=True).order_by("name")

    is_privileged = can_view_sensitive_employee_data(request.user)
    can_export_sensitive = can_export_sensitive_employee_data(request.user)

    paginator = Paginator(qs, page_size)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    units_csv = ",".join(str(x) for x in units_selected)

    today = date_cls.today()
    employee_ids_page = [e.id for e in page_obj.object_list]
    active_assignments = (
        TempAssignment.objects.filter(
            employee_id__in=employee_ids_page,
            status=TempAssignment.Status.ACTIVE,
            apply_flag=True,
            start_date__lte=today,
        )
        .filter(Q(end_date__gte=today) | Q(end_date__isnull=True))
        .select_related("to_unit")
    )
    supplement_map = {a.employee_id: a.to_unit.symbol for a in active_assignments}

    return render(
        request,
        "backoffice/hr/employees/list.html",
        {
            "items": page_obj.object_list,
            "query": q,
            "units": units,
            "teams": teams,
            "job_titles": job_titles,
            "units_selected": units_selected,
            "units_csv": units_csv,
            "team_selected": team_filter,
            "jt_selected": jt_filter,
            "is_privileged": is_privileged,
            "can_export_sensitive": can_export_sensitive,
            "page_obj": page_obj,
            "paginator": paginator,
            "current_page": page_obj.number,
            "page_size": page_size,
            "total_count": paginator.count,
            "page_size_options": [25, 50, 100, 200],
            "supplement_map": supplement_map,
        },
    )


@login_required
@permission_or_message("hr.view_employee")
def employee_detail(request, pk):
    emp = get_object_or_404(
        Employee.objects.select_related("job_title", "unit", "team", "user"),
        pk=pk,
    )
    allowed = set(allowed_org_ids_for_user(request.user))
    if emp.unit_id not in allowed:
        return _no_scope_permission(request)

    is_privileged = can_view_sensitive_employee_data(request.user)

    assignments = (
        TempAssignment.objects.filter(employee=emp)
        .select_related("from_unit", "to_unit")
        .order_by("-start_date", "-id")
    )

    today = date_cls.today()

    return render(
        request,
        "backoffice/hr/employees/detail.html",
        {
            "emp": emp,
            "is_privileged": is_privileged,
            "assignments": assignments,
            "today": today,
        },
    )


@login_required
@permission_or_message("core.add_user")
def employee_create_user(request, pk):
    emp = get_object_or_404(Employee.objects.select_related("unit", "job_title"), pk=pk)
    allowed = set(allowed_org_ids_for_user(request.user))
    if emp.unit_id not in allowed:
        return _no_scope_permission(request)

    if emp.user_id:
        messages.warning(request, "Nhân sự này đã có tài khoản.")
        return redirect("backoffice:employee_detail", pk=pk)

    base_username = vn_slug(emp.unit.symbol) + "_" + vn_slug(emp.full_name) if emp.unit and emp.unit.symbol else vn_slug(emp.full_name)

    if request.method == "POST":
        username = base_username
        counter = 2
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        user = User(
            username=username,
            email="",
            full_name=emp.full_name,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        temporary_password = DEFAULT_EMPLOYEE_USER_PASSWORD
        user.set_password(temporary_password)
        user.save()

        emp.user = user
        emp.save(update_fields=["user"])

        employee_group, _ = Group.objects.get_or_create(name="EMPLOYEE")
        user.groups.add(employee_group)

        AccessControl.objects.update_or_create(
            user=user,
            defaults={"root_org_unit": emp.unit, "scope": AccessControl.Scope.UNIT_SUBTREE},
        )

        audit_log(
            action_verb="CREATE",
            object_type="user",
            object_id=user.id,
            object_repr=user.username,
            actor=request.user,
            changes={"fields": {"username": user.username, "employee_code": emp.employee_code}},
            request=request,
            action_code="USER_CREATE",
        )

        audit_log(
            action_verb="UPDATE",
            object_type="employee",
            object_id=emp.id,
            object_repr=emp.full_name,
            actor=request.user,
            changes={"link_user": {"new": user.username}},
            request=request,
            action_code="EMPLOYEE_LINK_USER",
        )

        messages.success(
            request,
            f"Đã tạo tài khoản: {username}. Mật khẩu mặc định: {temporary_password}. "
            "Cần yêu cầu người dùng đổi mật khẩu sau khi đăng nhập.",
        )
        return redirect("backoffice:employee_detail", pk=pk)

    return render(
        request,
        "backoffice/hr/employees/create_user_confirm.html",
        {
            "emp": emp,
            "proposed_username": base_username,
            "default_password": DEFAULT_EMPLOYEE_USER_PASSWORD,
        },
    )


@login_required
@permission_or_message("hr.add_employee")
def employee_create(request):
    if request.method == "POST":
        form = EmployeeForm(request.POST, user=request.user)
        if form.is_valid():
            emp = form.save(commit=False)
            if not emp.employee_code:
                from django.db.models import Max

                max_code = Employee.objects.aggregate(m=Max("employee_code"))["m"]
                next_num = (int(max_code[1:]) + 1) if (max_code and max_code.startswith("E")) else 1
                emp.employee_code = f"E{next_num:06d}"
            emp.save()
            audit_log(
                action_verb="CREATE",
                object_type="employee",
                object_id=emp.id,
                object_repr=emp.full_name,
                actor=request.user,
                changes={"fields": {"employee_code": emp.employee_code, "unit": emp.unit_id}},
                request=request,
                action_code="EMPLOYEE_CREATE",
            )
            messages.success(request, "Đã tạo nhân sự.")
            return redirect("backoffice:employee_list")
    else:
        form = EmployeeForm(user=request.user)
    return render(request, "backoffice/hr/employees/form.html", {"form": form, "create": True})


@login_required
@permission_or_message("hr.change_employee")
def employee_edit(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    allowed = set(allowed_org_ids_for_user(request.user))
    if emp.unit_id not in allowed:
        return _no_scope_permission(request)

    if request.method == "POST":
        old = {
            "full_name": emp.full_name,
            "workforce_type": emp.workforce_type,
            "job_title_id": emp.job_title_id,
            "unit_id": emp.unit_id,
            "team_id": emp.team_id,
            "card_id": emp.card_id,
            "skip_device_attendance": emp.skip_device_attendance,
            "status": emp.status,
        }
        form = EmployeeForm(request.POST, instance=emp, user=request.user)
        if form.is_valid():
            updated = form.save()
            diff = {}
            for k, v in old.items():
                nv = getattr(updated, k)
                if v != nv:
                    diff[k] = {"old": str(v), "new": str(nv)}
            if diff:
                audit_log(
                    action_verb="UPDATE",
                    object_type="employee",
                    object_id=updated.id,
                    object_repr=updated.full_name,
                    actor=request.user,
                    changes=diff,
                    request=request,
                    action_code="EMPLOYEE_UPDATE",
                )
            messages.success(request, "Đã cập nhật nhân sự.")
            return redirect("backoffice:employee_detail", pk=pk)
    else:
        form = EmployeeForm(instance=emp, user=request.user)
    return render(request, "backoffice/hr/employees/form.html", {"form": form, "obj": emp})


@login_required
@permission_or_message("hr.change_employee")
def employee_deactivate(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    allowed = set(allowed_org_ids_for_user(request.user))
    if emp.unit_id not in allowed:
        return _no_scope_permission(request)

    if request.method == "POST":
        prev = emp.status
        if prev != Employee.Status.INACTIVE:
            emp.status = Employee.Status.INACTIVE
            emp.save(update_fields=["status"])
            audit_log(
                action_verb="UPDATE",
                object_type="employee",
                object_id=emp.id,
                object_repr=emp.full_name,
                actor=request.user,
                changes={"status": {"old": prev, "new": emp.status}},
                request=request,
                action_code="EMPLOYEE_DEACTIVATE",
            )
        messages.success(request, "Đã chuyển trạng thái nhân sự thành Tạm ngưng.")
        return redirect("backoffice:employee_detail", pk=pk)

    return render(request, "backoffice/hr/employees/confirm_deactivate.html", {"obj": emp})


@login_required
@permission_or_message("hr.change_employee")
def employee_leave(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    allowed = set(allowed_org_ids_for_user(request.user))
    if emp.unit_id not in allowed:
        return _no_scope_permission(request)

    if request.method == "POST":
        prev = emp.status
        if prev != Employee.Status.LEFT:
            emp.status = Employee.Status.LEFT
            emp.save(update_fields=["status"])
            if emp.user_id and emp.user.is_active:
                emp.user.is_active = False
                emp.user.save(update_fields=["is_active"])
            audit_log(
                action_verb="UPDATE",
                object_type="employee",
                object_id=emp.id,
                object_repr=emp.full_name,
                actor=request.user,
                changes={"status": {"old": prev, "new": emp.status}},
                request=request,
                action_code="EMPLOYEE_LEAVE",
            )
        messages.success(request, "Đã chuyển trạng thái nhân sự thành Đã nghỉ.")
        return redirect("backoffice:employee_detail", pk=pk)

    return render(request, "backoffice/hr/employees/confirm_leave.html", {"obj": emp})
