from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from apps.backoffice.utils.permissions import permission_or_message
from apps.hr.models import Employee, AccessControl
from apps.hr.forms import EmployeeForm
from apps.hr.services import allowed_org_ids_for_user
from apps.organization.models import OrgUnit, JobTitle
from apps.audit.utils import audit_log
import re

User = get_user_model()

# Chuẩn hóa (bỏ dấu, chữ thường, bỏ ký tự đặc biệt) để tạo username
VN_MAP = {
    ord('á'): 'a', ord('à'): 'a', ord('ả'): 'a', ord('ã'): 'a', ord('ạ'): 'a',
    ord('ă'): 'a', ord('ắ'): 'a', ord('ằ'): 'a', ord('ẳ'): 'a', ord('ẵ'): 'a', ord('ặ'): 'a',
    ord('â'): 'a', ord('ấ'): 'a', ord('ầ'): 'a', ord('ẩ'): 'a', ord('ẫ'): 'a', ord('ậ'): 'a',
    ord('đ'): 'd',
    ord('é'): 'e', ord('è'): 'e', ord('ẻ'): 'e', ord('ẽ'): 'e', ord('ẹ'): 'e',
    ord('ê'): 'e', ord('ế'): 'e', ord('ề'): 'e', ord('ể'): 'e', ord('ễ'): 'e', ord('ệ'): 'e',
    ord('í'): 'i', ord('ì'): 'i', ord('ỉ'): 'i', ord('ĩ'): 'i', ord('ị'): 'i',
    ord('ó'): 'o', ord('ò'): 'o', ord('ỏ'): 'o', ord('õ'): 'o', ord('ọ'): 'o',
    ord('ô'): 'o', ord('ố'): 'o', ord('ồ'): 'o', ord('ổ'): 'o', ord('ỗ'): 'o', ord('ộ'): 'o',
    ord('ơ'): 'o', ord('ớ'): 'o', ord('ờ'): 'o', ord('ở'): 'o', ord('ỡ'): 'o', ord('ợ'): 'o',
    ord('ú'): 'u', ord('ù'): 'u', ord('ủ'): 'u', ord('ũ'): 'u', ord('ụ'): 'u',
    ord('ư'): 'u', ord('ứ'): 'u', ord('ừ'): 'u', ord('ử'): 'u', ord('ữ'): 'u', ord('ự'): 'u',
    ord('ý'): 'y', ord('ỳ'): 'y', ord('ỷ'): 'y', ord('ỹ'): 'y', ord('ỵ'): 'y',
    # Uppercase
    ord('Á'): 'a', ord('À'): 'a', ord('Ả'): 'a', ord('Ã'): 'a', ord('Ạ'): 'a',
    ord('Ă'): 'a', ord('Ắ'): 'a', ord('Ằ'): 'a', ord('Ẳ'): 'a', ord('Ẵ'): 'a', ord('Ặ'): 'a',
    ord('Â'): 'a', ord('Ấ'): 'a', ord('Ầ'): 'a', ord('Ẩ'): 'a', ord('Ẫ'): 'a', ord('Ậ'): 'a',
    ord('Đ'): 'd',
    ord('É'): 'e', ord('È'): 'e', ord('Ẻ'): 'e', ord('Ẽ'): 'e', ord('Ẹ'): 'e',
    ord('Ê'): 'e', ord('Ế'): 'e', ord('Ề'): 'e', ord('Ể'): 'e', ord('Ễ'): 'e', ord('Ệ'): 'e',
    ord('Í'): 'i', ord('Ì'): 'i', ord('Ỉ'): 'i', ord('Ĩ'): 'i', ord('Ị'): 'i',
    ord('Ó'): 'o', ord('Ò'): 'o', ord('Ỏ'): 'o', ord('Õ'): 'o', ord('Ọ'): 'o',
    ord('Ô'): 'o', ord('Ố'): 'o', ord('Ồ'): 'o', ord('Ổ'): 'o', ord('Ỗ'): 'o', ord('Ộ'): 'o',
    ord('Ơ'): 'o', ord('Ớ'): 'o', ord('Ờ'): 'o', ord('Ở'): 'o', ord('Ỡ'): 'o', ord('Ợ'): 'o',
    ord('Ú'): 'u', ord('Ù'): 'u', ord('Ủ'): 'u', ord('Ũ'): 'u', ord('Ụ'): 'u',
    ord('Ư'): 'u', ord('Ứ'): 'u', ord('Ừ'): 'u', ord('Ử'): 'u', ord('Ữ'): 'u', ord('Ự'): 'u',
    ord('Ý'): 'y', ord('Ỳ'): 'y', ord('Ỷ'): 'y', ord('Ỹ'): 'y', ord('Ỵ'): 'y',
}

def vn_slug(s: str) -> str:
    if not s:
        return ""
    basic = s.translate(VN_MAP).lower()
    return re.sub(r'[^a-z0-9]+', '', basic)

def scope_guard_or_message(request, emp: Employee):
    """
    Kiểm tra bản ghi có thuộc phạm vi AccessControl của user hay không.
    Nếu không, trả về trang 'Bạn chưa được cấp quyền'; nếu có, trả về None.
    """
    allowed = set(allowed_org_ids_for_user(request.user))
    if emp.unit_id not in allowed:
        return render(request, 'backoffice/no_permission.html', {
            'perm_codename': 'scope:UNIT_SUBTREE/PLANT_SUBTREE/ALL_ORG',
            'title': 'Bạn chưa được cấp quyền'
        }, status=200)
    return None

# ========================== LIST (multi-unit + team) ==========================

@login_required
@permission_or_message('hr.view_employee')
def employee_list(request):
    q = request.GET.get('q', '').strip()
    units_param = request.GET.get('units', '').strip()  # "1,2,3"
    jt_filter = request.GET.get('job_title', '').strip()
    team_filter = request.GET.get('team', '').strip()

    # Parse units list
    units_selected = []
    if units_param:
        for part in units_param.split(','):
            part = part.strip()
            if part.isdigit():
                units_selected.append(int(part))

    # Pagination
    page = request.GET.get('page', '1')
    page_size_raw = request.GET.get('page_size', '').strip()
    try:
        page_size = int(page_size_raw) if page_size_raw else 25
    except ValueError:
        page_size = 25
    if page_size <= 0 or page_size > 500:
        page_size = 25

    # Scope theo AccessControl
    scope_unit_ids = set(allowed_org_ids_for_user(request.user))

    # Base queryset
    qs = Employee.objects.select_related('job_title', 'unit', 'team').filter(unit_id__in=scope_unit_ids)

    # Apply filters
    if units_selected:
        chosen = [u for u in units_selected if u in scope_unit_ids]
        if chosen:
            qs = qs.filter(unit_id__in=chosen)
        else:
            qs = qs.none()
    if jt_filter:
        qs = qs.filter(job_title_id=jt_filter)
    if team_filter:
        qs = qs.filter(team_id=team_filter)
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(employee_code__icontains=q) | Q(card_id__icontains=q))

    qs = qs.order_by('employee_code')

    # Dữ liệu filter
    units = OrgUnit.objects.filter(id__in=scope_unit_ids, type__in=['DEPARTMENT', 'DIVISION', 'WORKSHOP']).order_by('symbol')
    if len(units_selected) == 1:
        teams = OrgUnit.objects.filter(type='TEAM', parent_id=units_selected[0]).order_by('symbol')
    elif len(units_selected) > 1:
        teams = OrgUnit.objects.filter(type='TEAM', parent_id__in=units_selected).order_by('symbol')
    else:
        teams = OrgUnit.objects.filter(type='TEAM', id__in=scope_unit_ids).order_by('symbol')
    job_titles = JobTitle.objects.order_by('name')

    is_privileged = request.user.is_superuser or request.user.groups.filter(name__in=['HR_ADMIN']).exists()

    paginator = Paginator(qs, page_size)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    units_csv = ",".join(str(x) for x in units_selected)

    return render(request, 'backoffice/hr/employees/list.html', {
        'items': page_obj.object_list,
        'query': q,
        'units': units,
        'teams': teams,
        'job_titles': job_titles,
        'units_selected': units_selected,
        'units_csv': units_csv,
        'team_selected': team_filter,
        'jt_selected': jt_filter,
        'is_privileged': is_privileged,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_page': page_obj.number,
        'page_size': page_size,
        'total_count': paginator.count,
        'page_size_options': [25, 50, 100, 200],
    })

# ========================== DETAIL ==========================

@login_required
@permission_or_message('hr.view_employee')
def employee_detail(request, pk):
    emp = get_object_or_404(Employee.objects.select_related('job_title', 'unit', 'team', 'user'), pk=pk)
    guard = scope_guard_or_message(request, emp)
    if guard:
        return guard
    is_privileged = request.user.is_superuser or request.user.groups.filter(name__in=['HR_ADMIN']).exists()
    return render(request, 'backoffice/hr/employees/detail.html', {
        'emp': emp,
        'is_privileged': is_privileged
    })

# ========================== CREATE USER (tối thiểu) ==========================

@login_required
@permission_or_message('auth.add_user')
def employee_create_user(request, pk):
    emp = get_object_or_404(Employee.objects.select_related('unit', 'job_title'), pk=pk)
    guard = scope_guard_or_message(request, emp)
    if guard:
        return guard

    if emp.user_id:
        messages.warning(request, "Nhân sự này đã có tài khoản.")
        return redirect('backoffice:employee_detail', pk=pk)

    unit_part = vn_slug(emp.unit.symbol)
    name_part = vn_slug(emp.full_name)
    base_username = f"{unit_part}_{name_part}" if unit_part else name_part

    if request.method == 'POST':
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
        user.set_password("123456")
        user.save()

        emp.user = user
        emp.save(update_fields=['user'])

        viewer_group, _ = Group.objects.get_or_create(name="EMPLOYEE_VIEWER")
        user.groups.add(viewer_group)

        AccessControl.objects.update_or_create(
            user=user,
            defaults={'root_org_unit': emp.unit, 'scope': AccessControl.Scope.UNIT_SUBTREE}
        )

        audit_log(action_verb="CREATE",
                  object_type="user",
                  object_id=user.id,
                  object_repr=user.username,
                  actor=request.user,
                  changes={"fields": {"username": user.username, "employee_code": emp.employee_code}},
                  request=request,
                  action_code="USER_CREATE")

        audit_log(action_verb="UPDATE",
                  object_type="employee",
                  object_id=emp.id,
                  object_repr=emp.full_name,
                  actor=request.user,
                  changes={"link_user": {"new": user.username}},
                  request=request,
                  action_code="EMPLOYEE_LINK_USER")

        messages.success(request, f"Đã tạo tài khoản: {username} (mật khẩu 123456).")
        return redirect('backoffice:employee_detail', pk=pk)

    return render(request, 'backoffice/hr/employees/create_user_confirm.html', {
        'emp': emp,
        'proposed_username': base_username
    })

# ========================== CREATE / EDIT ==========================

@login_required
@permission_or_message('hr.add_employee')
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            emp = form.save(commit=False)
            if not emp.employee_code:
                from django.db.models import Max
                max_code = Employee.objects.aggregate(m=Max('employee_code'))['m']
                next_num = (int(max_code[1:]) + 1) if (max_code and max_code.startswith('E')) else 1
                emp.employee_code = f"E{next_num:06d}"
            emp.save()
            audit_log(action_verb="CREATE", object_type="employee", object_id=emp.id, object_repr=emp.full_name,
                      actor=request.user, changes={'fields': {'employee_code': emp.employee_code, 'unit': emp.unit_id}},
                      request=request, action_code="EMPLOYEE_CREATE")
            messages.success(request, "Đã tạo nhân sự.")
            return redirect('backoffice:employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'backoffice/hr/employees/form.html', {'form': form, 'create': True})

@login_required
@permission_or_message('hr.change_employee')
def employee_edit(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    guard = scope_guard_or_message(request, emp)
    if guard:
        return guard

    if request.method == 'POST':
        old = {
            'full_name': emp.full_name, 'workforce_type': emp.workforce_type,
            'job_title_id': emp.job_title_id, 'unit_id': emp.unit_id, 'team_id': emp.team_id,
            'status': emp.status
        }
        form = EmployeeForm(request.POST, instance=emp)
        if form.is_valid():
            updated = form.save()
            diff = {}
            for k, v in old.items():
                nv = getattr(updated, k)
                if v != nv:
                    diff[k] = {'old': str(v), 'new': str(nv)}
            if diff:
                audit_log(action_verb="UPDATE", object_type="employee", object_id=updated.id, object_repr=updated.full_name,
                          actor=request.user, changes=diff, request=request, action_code="EMPLOYEE_UPDATE")
            messages.success(request, "Đã cập nhật nhân sự.")
            return redirect('backoffice:employee_detail', pk=pk)
    else:
        form = EmployeeForm(instance=emp)
    return render(request, 'backoffice/hr/employees/form.html', {'form': form, 'obj': emp})

# ========================== DEACTIVATE / LEAVE (giữ để khớp URL) ==========================

@login_required
@permission_or_message('hr.change_employee')
def employee_deactivate(request, pk):
    """
    Chuyển trạng thái nhân sự sang INACTIVE.
    Kiểm tra phạm vi AccessControl; nếu không đủ phạm vi, hiển thị trang 'Bạn chưa được cấp quyền'.
    """
    emp = get_object_or_404(Employee, pk=pk)
    guard = scope_guard_or_message(request, emp)
    if guard:
        return guard

    if request.method == 'POST':
        prev = emp.status
        if prev != Employee.Status.INACTIVE:
            emp.status = Employee.Status.INACTIVE
            emp.save(update_fields=['status'])
            audit_log(action_verb="UPDATE", object_type="employee", object_id=emp.id, object_repr=emp.full_name,
                      actor=request.user, changes={'status': {'old': prev, 'new': emp.status}}, request=request,
                      action_code="EMPLOYEE_DEACTIVATE")
        messages.success(request, "Đã chuyển trạng thái nhân sự thành Tạm ngưng.")
        return redirect('backoffice:employee_detail', pk=pk)

    return render(request, 'backoffice/hr/employees/confirm_deactivate.html', {'obj': emp})

@login_required
@permission_or_message('hr.change_employee')
def employee_leave(request, pk):
    """
    Chuyển trạng thái nhân sự sang LEFT và vô hiệu hóa tài khoản (nếu có).
    Kiểm tra phạm vi AccessControl trước khi xử lý.
    """
    emp = get_object_or_404(Employee, pk=pk)
    guard = scope_guard_or_message(request, emp)
    if guard:
        return guard

    if request.method == 'POST':
        prev = emp.status
        if prev != Employee.Status.LEFT:
            emp.status = Employee.Status.LEFT
            emp.save(update_fields=['status'])
            if emp.user_id and emp.user.is_active:
                emp.user.is_active = False
                emp.user.save(update_fields=['is_active'])
            audit_log(action_verb="UPDATE", object_type="employee", object_id=emp.id, object_repr=emp.full_name,
                      actor=request.user, changes={'status': {'old': prev, 'new': emp.status}}, request=request,
                      action_code="EMPLOYEE_LEAVE")
        messages.success(request, "Đã chuyển trạng thái nhân sự thành Đã nghỉ.")
        return redirect('backoffice:employee_detail', pk=pk)

    return render(request, 'backoffice/hr/employees/confirm_leave.html', {'obj': emp})