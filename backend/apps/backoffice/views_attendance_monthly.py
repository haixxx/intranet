from datetime import date as dt_date, timedelta
import calendar
from typing import Dict, List, Tuple, Set

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponse
from django.contrib import messages
from django.db.models import Q

try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, Border, Side
    from openpyxl.utils import get_column_letter
except Exception:
    openpyxl = None

from apps.organization.models import OrgUnit
from apps.attendance.models_batch import AttendanceCommit, AttendanceCommitItem
from apps.hr.models import Employee, AccessControl


def _units_for_attendance(request):
    """
    Lấy danh sách đơn vị được phép thao tác (nhất quán với phần Tạo/Xem, Xem đã chốt).
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
    from apps.organization.utils import get_subtree_unit_ids
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


def _month_range(year: int, month: int) -> Tuple[dt_date, dt_date, int]:
    """
    Trả về (start_date, end_date, days_in_month)
    """
    days_in_month = calendar.monthrange(year, month)[1]
    start = dt_date(year, month, 1)
    end = dt_date(year, month, days_in_month)
    return start, end, days_in_month


def _weekday_label_precise(d: dt_date) -> str:
    wd = d.weekday()
    return ["T2", "T3", "T4", "T5", "T6", "T7", "CN"][wd]


def _employees_for_month(unit: OrgUnit, team_id: str | None, start: dt_date, end: dt_date):
    """
    Lấy danh sách nhân sự hiển thị cho báo cáo tháng:
    - Base: nhân sự ACTIVE thuộc đơn vị
    - Bổ sung (BS IN): union thêm tất cả employee_id xuất hiện trong AttendanceCommitItem của đơn vị trong tháng
      và có include_in_unit=True (nhân sự bổ sung vào đơn vị).
    - Lọc theo team nếu có.
    """
    base_qs = Employee.objects.filter(unit=unit, status=Employee.Status.ACTIVE)
    team_id_int = None
    if team_id:
        try:
            team_id_int = int(team_id)
            base_qs = base_qs.filter(team_id=team_id_int)
        except Exception:
            team_id_int = None

    base_ids = set(base_qs.values_list("id", flat=True))

    commits = AttendanceCommit.objects.filter(unit=unit, work_date__gte=start, work_date__lte=end).values_list("id", flat=True)
    items_qs = AttendanceCommitItem.objects.select_related("employee").filter(
        commit_id__in=list(commits),
        include_in_unit=True  # chỉ lấy người thuộc quân số đơn vị
    )
    if team_id_int:
        items_qs = items_qs.filter(employee__team_id=team_id_int)

    commit_emp_ids: Set[int] = set(items_qs.values_list("employee_id", flat=True))
    all_ids = base_ids.union(commit_emp_ids)

    return Employee.objects.filter(id__in=list(all_ids)).order_by("employee_code")


def _commit_items_map(unit: OrgUnit, start: dt_date, end: dt_date) -> Dict[Tuple[int, dt_date], AttendanceCommitItem]:
    """
    Tải tất cả commit items theo đơn vị và khoảng ngày -> map (employee_id, work_date) => item
    """
    commits = AttendanceCommit.objects.filter(unit=unit, work_date__gte=start, work_date__lte=end).values_list("id", "work_date")
    commit_ids = [cid for cid, _ in commits]
    work_date_by_commit = {cid: wd for cid, wd in commits}

    items = AttendanceCommitItem.objects.select_related("employee", "code").filter(commit_id__in=commit_ids)
    m: Dict[Tuple[int, dt_date], AttendanceCommitItem] = {}
    for it in items:
        wd = work_date_by_commit.get(it.commit_id)
        if wd:
            m[(it.employee_id, wd)] = it
    return m


@login_required
def monthly_view(request):
    """
    Xem chấm công theo tháng (từ dữ liệu đã chốt).
    Bộ lọc: đơn vị, tổ, tháng, năm.
    Bảng: STT | Họ & tên | ngày 1..n (2 hàng header: ngày | thứ)
    """
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem Công theo tháng"
        }, status=403)

    units_qs = _units_for_attendance(request)

    # Lấy filter
    unit_id = (request.GET.get("unit") or "").strip()
    team_id = (request.GET.get("team") or "").strip()
    month_str = (request.GET.get("month") or "").strip()
    year_str = (request.GET.get("year") or "").strip()

    from django.utils import timezone
    today = timezone.localdate()
    try:
        month = int(month_str) if month_str else today.month
    except Exception:
        month = today.month
    try:
        year = int(year_str) if year_str else today.year
    except Exception:
        year = today.year

    unit = None
    if unit_id:
        try:
            unit = OrgUnit.objects.get(pk=int(unit_id), is_attendance_unit=True, is_active=True)
        except Exception:
            unit = None
            messages.warning(request, "Đơn vị không hợp lệ hoặc không được phép chấm công.")

    # Teams trong đơn vị (hiển thị ngay khi chọn đơn vị)
    teams = OrgUnit.objects.filter(parent=unit, type=OrgUnit.Type.TEAM).order_by("symbol") if unit else OrgUnit.objects.none()

    # Dải ngày trong tháng
    start, end, dim = _month_range(year, month)
    days = [start + timedelta(days=i) for i in range(dim)]

    employees = Employee.objects.none()
    items_map: Dict[Tuple[int, dt_date], AttendanceCommitItem] = {}

    if unit:
        employees = _employees_for_month(unit, team_id, start, end)
        items_map = _commit_items_map(unit, start, end)

    # Dựng rows hiển thị: mỗi row = (employee, [code theo ngày])
    rows: List[Dict] = []
    idx = 0
    for emp in employees:
        idx += 1
        codes_per_day: List[str] = []
        for d in days:
            it = items_map.get((emp.id, d))
            code_text = it.code.code if (it and it.code) else ""
            codes_per_day.append(code_text)
        rows.append({"idx": idx, "emp": emp, "codes": codes_per_day})

    return render(request, "backoffice/attendance/monthly_view.html", {
        "units_qs": units_qs,
        "unit_id": unit_id,
        "month": month,
        "year": year,
        "teams": teams,
        "team_id": team_id,
        "days": [{"d": d.day, "wd": _weekday_label_precise(d)} for d in days],
        "rows": rows,
        "has_data": bool(unit),
    })


@login_required
def monthly_export(request):
    """
    Xuất Excel: BẢNG CHẤM CÔNG CỦA "ĐƠN VỊ"
    Dòng 2: Thời gian (Tháng mm/yyyy)
    Từ dòng 3: dữ liệu (STT, Họ & Tên, ngày 1..n) giống bảng hiển thị.
    """
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xuất Công theo tháng"
        }, status=403)

    if openpyxl is None:
        messages.error(request, "Thiếu thư viện openpyxl để xuất Excel.")
        return render(request, "backoffice/attendance/monthly_view.html", {"has_data": False})

    unit_id = (request.GET.get("unit") or "").strip()
    team_id = (request.GET.get("team") or "").strip()
    from django.utils import timezone
    month = int(request.GET.get("month") or timezone.localdate().month)
    year = int(request.GET.get("year") or timezone.localdate().year)

    try:
        unit = OrgUnit.objects.get(pk=int(unit_id), is_attendance_unit=True, is_active=True)
    except Exception:
        messages.error(request, "Đơn vị không hợp lệ.")
        return render(request, "backoffice/attendance/monthly_view.html", {"has_data": False})

    start, end, dim = _month_range(year, month)
    days = [start + timedelta(days=i) for i in range(dim)]

    employees = _employees_for_month(unit, team_id, start, end)
    items_map = _commit_items_map(unit, start, end)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bang cham cong"

    thin = Side(style="thin", color="000000")
    border = Border(top=thin, left=thin, right=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Title (row 1)
    total_cols = 2 + dim
    title_text = f'BẢNG CHẤM CÔNG CỦA "{unit.name}"'
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    ws.cell(row=1, column=1, value=title_text).font = Font(bold=True, size=14)
    ws.cell(row=1, column=1).alignment = center

    # Timeline (row 2): "Tháng mm/yyyy" ở cột A
    ws.cell(row=2, column=1, value=f"Tháng {month:02d}/{year}").font = Font(bold=True)
    ws.cell(row=2, column=1).alignment = Alignment(horizontal="left")
    ws.cell(row=2, column=2, value="")  # cột Họ & Tên giữ trống ở dòng timeline

    # Header cột ngày (dd (Th)) từ cột C
    for i, d in enumerate(days, start=1):
        col = 2 + i
        ws.cell(row=2, column=col, value=f"{d.day:02d} ({_weekday_label_precise(d)})").alignment = center
        ws.cell(row=2, column=col).font = Font(bold=True)

    # Data từ row 3
    row_idx = 3
    stt = 0
    for emp in employees:
        stt += 1
        ws.cell(row=row_idx, column=1, value=stt).alignment = center
        ws.cell(row=row_idx, column=2, value=f"{emp.full_name}").alignment = Alignment(horizontal="left")

        for i, d in enumerate(days, start=1):
            it = items_map.get((emp.id, d))
            code_text = it.code.code if (it and it.code) else ""
            col = 2 + i
            c = ws.cell(row=row_idx, column=col, value=code_text)
            c.alignment = center

        row_idx += 1

    # Styling: borders + column widths
    for r in range(1, row_idx):
        for c in range(1, total_cols + 1):
            ws.cell(row=r, column=c).border = border

    ws.column_dimensions[get_column_letter(1)].width = 6   # STT
    ws.column_dimensions[get_column_letter(2)].width = 28  # Họ & Tên
    for i in range(dim):
        ws.column_dimensions[get_column_letter(3 + i)].width = 6  # ngày

    ws.freeze_panes = ws["A3"]

    # Response
    from django.utils.encoding import iri_to_uri
    filename = f"bang-cham-cong-{unit.symbol or unit.code}-{year}-{month:02d}.xlsx"
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{iri_to_uri(filename)}"'
    wb.save(response)
    return response