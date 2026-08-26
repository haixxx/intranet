import io
import json
from datetime import date as date_cls
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Max, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from openpyxl import Workbook, load_workbook

from apps.audit.utils import audit_log
from apps.hr.models import Employee
from apps.hr.services import allowed_org_ids_for_user
from apps.hr.services.assignments import effective_unit_for, employee_ids_effective_in_units
from apps.organization.models import JobTitle, OrgUnit, ShiftTemplate


# ==================== COMMON ====================

def _xlsx_response(wb: Workbook, filename_prefix: str) -> HttpResponse:
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{ts}.xlsx"'
    return resp


def _to_bool(value, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"true", "1", "yes", "y", "on", "x"}


def _to_str(value):
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _to_intlike_str(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, int):
            return str(value)
        s = str(value).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s
    except Exception:
        return str(value).strip()


def _to_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date_cls):
        return value
    if isinstance(value, datetime):
        return value.date()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except Exception:
            pass
    return None




def _can_export_sensitive_employee_data(user) -> bool:
    """
    Quyền xuất Excel có thông tin nhạy cảm của nhân sự.
    Quản trị nhóm trong DB/admin, không cần migration:
    - HR_ADMIN
    - HR_SENSITIVE_EXPORTER
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=["HR_MANAGER", "HR_ADMIN", "HR_SENSITIVE_EXPORTER"]).exists()


def _team_belongs_to_unit(team: OrgUnit | None, unit: OrgUnit | None) -> bool:
    if not team or not unit:
        return True
    parent = team.parent
    while parent:
        if parent.id == unit.id:
            return True
        parent = parent.parent
    return False


# ==================== ORGUNIT EXPORT/IMPORT ====================

@login_required
@permission_required("organization.view_orgunit", raise_exception=True)
def export_orgunits(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "OrgUnits"

    # is_attendance_unit là cờ quan trọng cho module chấm công.
    headers = ["type", "name", "symbol", "parent_symbol", "is_active", "is_attendance_unit"]
    ws.append(headers)

    for u in OrgUnit.objects.select_related("parent").order_by("type", "symbol"):
        ws.append(
            [
                u.type,
                u.name,
                u.symbol,
                (u.parent.symbol if u.parent_id else ""),
                "true" if u.is_active else "false",
                "true" if u.is_attendance_unit else "false",
            ]
        )
    return _xlsx_response(wb, "OrgUnits")


@login_required
@permission_required("organization.add_orgunit", raise_exception=True)
def import_orgunits(request):
    if request.method == "POST" and request.FILES.get("file"):
        wb = load_workbook(request.FILES["file"])
        ws = wb.active
        headers = [str(c.value or "").strip() for c in ws[1]]

        required_old = ["type", "name", "symbol", "parent_symbol", "is_active"]
        required_new = ["type", "name", "symbol", "parent_symbol", "is_active", "is_attendance_unit"]

        if headers[: len(required_new)] == required_new:
            has_attendance_col = True
        elif headers[: len(required_old)] == required_old:
            has_attendance_col = False
        else:
            messages.error(
                request,
                "Header không đúng định dạng. Cần: type,name,symbol,parent_symbol,is_active,is_attendance_unit",
            )
            return redirect("backoffice:orgunit_list")

        created, updated, errors = 0, 0, []
        symbols_cache = {u.symbol: u for u in OrgUnit.objects.all()}

        for i in range(2, ws.max_row + 1):
            try:
                typ = (ws.cell(i, 1).value or "").strip()
                name = (ws.cell(i, 2).value or "").strip()
                symbol = (ws.cell(i, 3).value or "").strip().upper()
                parent_symbol = (ws.cell(i, 4).value or "").strip().upper()
                is_active = _to_bool(ws.cell(i, 5).value, default=True)
                is_attendance_unit = _to_bool(ws.cell(i, 6).value, default=False) if has_attendance_col else False

                if not typ or not name or not symbol:
                    continue

                if typ == OrgUnit.Type.PLANT:
                    parent = None
                else:
                    if not parent_symbol:
                        raise ValueError("parent_symbol bắt buộc với đơn vị con.")
                    parent = symbols_cache.get(parent_symbol) or OrgUnit.objects.filter(symbol=parent_symbol).first()
                    if not parent:
                        raise ValueError(f"parent_symbol '{parent_symbol}' không tồn tại.")

                obj = OrgUnit.objects.filter(symbol=symbol).first()
                if obj:
                    if obj.type != typ:
                        has_employee = Employee.objects.filter(unit=obj).exists() or Employee.objects.filter(team=obj).exists()
                        has_children = OrgUnit.objects.filter(parent=obj).exists()
                        if has_employee or has_children:
                            raise ValueError(
                                f"Không thể đổi type của '{symbol}' vì đang có nhân sự hoặc đơn vị con."
                            )

                    obj.name = name
                    obj.type = typ
                    obj.parent = parent
                    obj.is_active = is_active
                    obj.is_attendance_unit = is_attendance_unit
                    obj.full_clean()
                    obj.save()
                    updated += 1
                else:
                    max_code = OrgUnit.objects.aggregate(m=Max("code"))["m"]
                    next_num = (int(max_code[2:]) + 1) if (max_code and max_code.startswith("OU")) else 1
                    code = f"OU{next_num:04d}"
                    obj = OrgUnit(
                        code=code,
                        symbol=symbol,
                        name=name,
                        type=typ,
                        parent=parent,
                        is_active=is_active,
                        is_attendance_unit=is_attendance_unit,
                    )
                    obj.full_clean()
                    obj.save()
                    symbols_cache[symbol] = obj
                    created += 1
            except Exception as e:
                errors.append(f"Dòng {i}: {e}")

        audit_log(
            action_verb="UPDATE",
            object_type="orgunit",
            object_id="bulk",
            object_repr="IMPORT",
            actor=request.user,
            extra={"created": created, "updated": updated, "errors": len(errors)},
            request=request,
            action_code="ORGUNIT_IMPORT",
        )
        if errors:
            messages.warning(request, f"Tạo mới: {created}, Cập nhật: {updated}, Lỗi: {len(errors)}. {errors[:5]}")
        else:
            messages.success(request, f"Tạo mới: {created}, Cập nhật: {updated}.")
        return redirect("backoffice:orgunit_list")

    return render(
        request,
        "backoffice/common/import.html",
        {
            "title": "Nhập Excel - Cơ cấu tổ chức",
            "note": "File .xlsx: header type,name,symbol,parent_symbol,is_active,is_attendance_unit",
            "post_url": "backoffice:import_orgunits",
        },
    )


# ==================== JOBTITLE EXPORT/IMPORT ====================

@login_required
@permission_required("organization.view_jobtitle", raise_exception=True)
def export_jobtitles(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "JobTitles"
    ws.append(["name", "code", "is_active"])
    for jt in JobTitle.objects.order_by("name"):
        ws.append([jt.name, jt.code or "", "true" if jt.is_active else "false"])
    return _xlsx_response(wb, "JobTitles")


@login_required
@permission_required("organization.add_jobtitle", raise_exception=True)
def import_jobtitles(request):
    if request.method == "POST" and request.FILES.get("file"):
        wb = load_workbook(request.FILES["file"])
        ws = wb.active
        headers = [c.value for c in ws[1]]
        if headers[:3] != ["name", "code", "is_active"]:
            messages.error(request, "Header không đúng định dạng.")
            return redirect("backoffice:jobtitle_list")

        created, updated, errors = 0, 0, []
        for i in range(2, ws.max_row + 1):
            try:
                name = (ws.cell(i, 1).value or "").strip()
                code = ((ws.cell(i, 2).value or "") or None)
                if isinstance(code, str):
                    code = code.strip().upper() or None
                is_active = _to_bool(ws.cell(i, 3).value, default=True)

                if not name:
                    continue

                obj = None
                if code:
                    obj = JobTitle.objects.filter(code=code).first()
                if not obj:
                    obj = JobTitle.objects.filter(name=name).first()

                if obj:
                    obj.name = name
                    if code:
                        obj.code = code
                    obj.is_active = is_active
                    obj.full_clean()
                    obj.save()
                    updated += 1
                else:
                    obj = JobTitle(name=name, code=code, is_active=is_active)
                    obj.full_clean()
                    obj.save()
                    created += 1
            except Exception as e:
                errors.append(f"Dòng {i}: {e}")

        audit_log(
            action_verb="UPDATE",
            object_type="jobtitle",
            object_id="bulk",
            object_repr="IMPORT",
            actor=request.user,
            extra={"created": created, "updated": updated, "errors": len(errors)},
            request=request,
            action_code="JOBTITLE_IMPORT",
        )
        if errors:
            messages.warning(request, f"Tạo mới: {created}, Cập nhật: {updated}, Lỗi: {len(errors)}. {errors[:5]}")
        else:
            messages.success(request, f"Tạo mới: {created}, Cập nhật: {updated}.")
        return redirect("backoffice:jobtitle_list")

    return render(
        request,
        "backoffice/common/import.html",
        {
            "title": "Nhập Excel - Chức danh",
            "note": "File .xlsx: header name,code,is_active",
            "post_url": "backoffice:import_jobtitles",
        },
    )


# ==================== SHIFT EXPORT/IMPORT ====================

@login_required
@permission_required("organization.view_shifttemplate", raise_exception=True)
def export_shifts(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "ShiftTemplates"
    ws.append(["code", "name", "type", "start_time", "end_time", "breaks_json", "crosses_midnight", "is_active"])
    for s in ShiftTemplate.objects.order_by("code"):
        ws.append(
            [
                s.code,
                s.name,
                s.type,
                s.start_time.strftime("%H:%M"),
                s.end_time.strftime("%H:%M"),
                json.dumps(s.breaks or [], ensure_ascii=False),
                "true" if s.crosses_midnight else "false",
                "true" if s.is_active else "false",
            ]
        )
    return _xlsx_response(wb, "ShiftTemplates")


@login_required
@permission_required("organization.add_shifttemplate", raise_exception=True)
def import_shifts(request):
    if request.method == "POST" and request.FILES.get("file"):
        wb = load_workbook(request.FILES["file"])
        ws = wb.active
        headers = [c.value for c in ws[1]]
        required = ["code", "name", "type", "start_time", "end_time", "breaks_json", "crosses_midnight", "is_active"]
        if headers[: len(required)] != required:
            messages.error(request, "Header không đúng định dạng.")
            return redirect("backoffice:shift_list")

        from datetime import datetime as dt

        created, updated, errors = 0, 0, []
        for i in range(2, ws.max_row + 1):
            try:
                code = (ws.cell(i, 1).value or "").strip().upper()
                name = (ws.cell(i, 2).value or "").strip()
                typ = (ws.cell(i, 3).value or "").strip()
                st_raw = (ws.cell(i, 4).value or "").strip()
                et_raw = (ws.cell(i, 5).value or "").strip()
                breaks_json = (ws.cell(i, 6).value or "").strip()
                crosses_midnight = _to_bool(ws.cell(i, 7).value, default=False)
                is_active = _to_bool(ws.cell(i, 8).value, default=True)

                if not code:
                    continue
                stime = dt.strptime(st_raw, "%H:%M").time()
                etime = dt.strptime(et_raw, "%H:%M").time()
                brks = json.loads(breaks_json) if breaks_json else []

                obj, is_new = ShiftTemplate.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "type": typ,
                        "start_time": stime,
                        "end_time": etime,
                        "breaks": brks,
                        "crosses_midnight": crosses_midnight,
                        "is_active": is_active,
                    },
                )
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                errors.append(f"Dòng {i}: {e}")

        audit_log(
            action_verb="UPDATE",
            object_type="shift",
            object_id="bulk",
            object_repr="IMPORT",
            actor=request.user,
            extra={"created": created, "updated": updated, "errors": len(errors)},
            request=request,
            action_code="SHIFT_IMPORT",
        )
        if errors:
            messages.warning(request, f"Tạo mới: {created}, Cập nhật: {updated}, Lỗi: {len(errors)}. {errors[:5]}")
        else:
            messages.success(request, f"Tạo mới: {created}, Cập nhật: {updated}.")
        return redirect("backoffice:shift_list")

    return render(
        request,
        "backoffice/common/import.html",
        {
            "title": "Nhập Excel - Ca làm việc",
            "note": "File .xlsx: header code,name,type,start_time,end_time,breaks_json,crosses_midnight,is_active",
            "post_url": "backoffice:import_shifts",
        },
    )


# ==================== EMPLOYEE EXPORT ====================

@login_required
@permission_required("hr.view_employee", raise_exception=True)
def export_employees(request):
    q = request.GET.get("q", "").strip()
    units_param = request.GET.get("units", "").strip()
    jt_filter = request.GET.get("job_title", "").strip()
    team_filter = request.GET.get("team", "").strip()
    effective_mode = request.GET.get("effective_mode", "").strip() == "1"
    effective_date_param = request.GET.get("effective_date", "").strip()

    include_sensitive = _can_export_sensitive_employee_data(request.user)

    if effective_date_param:
        try:
            effective_date = date_cls.fromisoformat(effective_date_param)
        except ValueError:
            effective_date = date_cls.today()
    else:
        effective_date = date_cls.today()

    units_selected = []
    if units_param:
        for p in units_param.split(","):
            p = p.strip()
            if p.isdigit():
                units_selected.append(int(p))

    unit_ids_scope = set(allowed_org_ids_for_user(request.user))
    qs_base = Employee.objects.select_related("job_title", "unit", "team").filter(unit_id__in=unit_ids_scope)

    if effective_mode and units_selected:
        effective_ids = employee_ids_effective_in_units(units_selected, effective_date)
        qs = qs_base.filter(id__in=effective_ids)
    else:
        if units_selected:
            valid_units = [u for u in units_selected if u in unit_ids_scope]
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

    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"

    headers = [
        "employee_code",
        "full_name",
        "workforce_type",
        "job_title",
        "unit_symbol",
        "team_symbol",
        "card_id",
        "status",
        "skip_device_attendance",
        "joined_date",
    ]

    if effective_mode:
        headers.insert(6, "effective_unit_symbol")

    if include_sensitive:
        headers.extend(["citizen_id", "tax_code", "bank_account", "bank_name", "email", "phone"])

    headers.append("note")
    ws.append(headers)

    for e in qs.order_by("employee_code"):
        row = [
            e.employee_code,
            e.full_name,
            e.workforce_type,
            e.job_title.name if e.job_title_id else "",
            e.unit.symbol if e.unit_id else "",
            e.team.symbol if e.team_id else "",
        ]

        if effective_mode:
            eff_unit_id, source = effective_unit_for(e.id, effective_date)
            eff_symbol = OrgUnit.objects.filter(pk=eff_unit_id).values_list("symbol", flat=True).first() or ""
            row.append(eff_symbol)

        row.extend(
            [
                e.card_id or "",
                e.status,
                "true" if e.skip_device_attendance else "false",
                (e.joined_date.isoformat() if e.joined_date else ""),
            ]
        )

        if include_sensitive:
            row.extend(
                [
                    e.citizen_id or "",
                    e.tax_code or "",
                    e.bank_account or "",
                    e.bank_name or "",
                    e.email or "",
                    e.phone or "",
                ]
            )

        row.append(e.note or "")
        ws.append(row)

    filename = "EmployeesSensitive" if include_sensitive else "Employees"
    return _xlsx_response(wb, filename)

# ==================== EMPLOYEE IMPORT ====================

@login_required
@permission_required("hr.add_employee", raise_exception=True)
def import_employees(request):
    """
    Import nhân sự nâng cao:
      match_by: employee_code | card_id
      mode: update_only | create_only | upsert
      dry_run: xem trước
    """
    if request.method == "POST" and request.FILES.get("file"):
        match_by = request.POST.get("match_by", "employee_code").strip() or "employee_code"
        mode = request.POST.get("mode", "upsert").strip() or "upsert"
        # Checkbox không được tick sẽ không gửi field; template có hidden=false để backend nhận đúng ý người dùng.
        dry_run = str(request.POST.get("dry_run", "true")).lower() in ("1", "true", "yes", "on")

        wb = load_workbook(request.FILES["file"])
        ws = wb.active
        headers = [str(c.value or "").strip() for c in ws[1]]

        def norm(h):
            return "".join(str(h).strip().lower().split())

        header_norm = [norm(h) for h in headers]
        alias_map = {
            "full_name": {"fullname", "hoten", "full_name"},
            "workforce_type": {"workforcetype", "workforce", "loainghiepvu", "workforce_type"},
            "job_title": {"jobtitle", "title", "chucvu", "job_title"},
            "unit_symbol": {"unitsymbol", "unit", "donvi", "unit_symbol"},
            "team_symbol": {"teamsymbol", "team", "to", "tosymbol", "team_symbol"},
            "employee_code": {"employeecode", "empcode", "manv", "employee_code"},
            "citizen_id": {"citizenid", "cccd", "citizen_id"},
            "tax_code": {"taxcode", "mst", "tax_code"},
            "card_id": {"cardid", "card", "machamcong", "card_id"},
            "bank_account": {"bankaccount", "stk", "account", "bank_account"},
            "bank_name": {"bankname", "nganhang", "bank_name"},
            "email": {"email", "mail"},
            "phone": {"phone", "sdt"},
            "joined_date": {"joineddate", "joined_dat", "joined_date", "joindate", "join_date"},
            "status": {"status", "trangthai", "trang_thai"},
            "skip_device_attendance": {"skipdeviceattendance", "skip_device_attendance", "dac_cach_cham_may", "daccachchammay"},
            "note": {"note", "ghichu", "ghi_chu"},
        }

        col_index = {}
        for idx, hn in enumerate(header_norm, start=1):
            for std, aliases in alias_map.items():
                if hn in aliases and std not in col_index:
                    col_index[std] = idx

        mandatory = ["full_name", "workforce_type", "job_title", "unit_symbol", "status"]
        missing = [m for m in mandatory if m not in col_index]
        if missing:
            messages.error(request, f"Thiếu cột bắt buộc: {missing}.")
            return redirect("backoffice:employee_list")

        jt_cache_by_name = {j.name: j for j in JobTitle.objects.all()}
        jt_cache_by_code = {j.code: j for j in JobTitle.objects.exclude(code__isnull=True).exclude(code="")}
        unit_cache = {u.symbol: u for u in OrgUnit.objects.all()}
        # Superuser phải thấy ngay cả đơn vị vừa tạo trong request/tiến trình hiện tại.
        # allowed_org_ids_for_user() có cache để tối ưu cho user thường, nên không dùng cache cho superuser tại màn import.
        if request.user.is_superuser:
            allowed_unit_ids = {u.id for u in unit_cache.values()}
        else:
            allowed_unit_ids = set(allowed_org_ids_for_user(request.user))

        def cell(row, key):
            c = col_index.get(key)
            return row[c - 1].value if c else None

        key_field = "employee_code" if match_by == "employee_code" else "card_id"

        existing_codes = set(Employee.objects.exclude(employee_code__isnull=True).values_list("employee_code", flat=True))
        existing_cards = set(Employee.objects.exclude(card_id__isnull=True).values_list("card_id", flat=True))
        existing_citizens = set(Employee.objects.exclude(citizen_id__isnull=True).values_list("citizen_id", flat=True))
        existing_emails = set(Employee.objects.exclude(email__isnull=True).values_list("email", flat=True))
        existing_phones = set(Employee.objects.exclude(phone__isnull=True).values_list("phone", flat=True))

        seen_keys_in_file = set()
        seen_cards_in_file = set()
        created = updated = skipped = 0
        errors = []

        max_code = Employee.objects.aggregate(m=Max("employee_code"))["m"]
        next_emp_num = (int(max_code[1:]) + 1) if (max_code and isinstance(max_code, str) and max_code.startswith("E")) else 1

        commit = not dry_run
        ctx = transaction.atomic() if commit else None
        if commit:
            ctx.__enter__()

        try:
            for r in range(2, ws.max_row + 1):
                row = ws[r]
                try:
                    full_name = _to_str(cell(row, "full_name"))
                    workforce_type = _to_str(cell(row, "workforce_type"))
                    jt_value = _to_str(cell(row, "job_title"))
                    unit_symbol = (_to_str(cell(row, "unit_symbol")) or "").upper()
                    team_symbol = (_to_str(cell(row, "team_symbol")) or "").upper()
                    emp_code = _to_str(cell(row, "employee_code"))
                    citizen_id = _to_intlike_str(cell(row, "citizen_id"))
                    tax_code = _to_intlike_str(cell(row, "tax_code"))
                    card_id = _to_intlike_str(cell(row, "card_id"))
                    bank_account = _to_intlike_str(cell(row, "bank_account"))
                    bank_name = _to_str(cell(row, "bank_name"))
                    email = _to_str(cell(row, "email"))
                    phone = _to_intlike_str(cell(row, "phone"))
                    joined_date = _to_date(cell(row, "joined_date"))
                    status = _to_str(cell(row, "status")) or "ACTIVE"
                    note = _to_str(cell(row, "note"))
                    skip_device_attendance = _to_bool(cell(row, "skip_device_attendance"), default=False)

                    if not full_name:
                        continue
                    if not workforce_type or not jt_value or not unit_symbol:
                        raise ValueError("Thiếu workforce_type / job_title / unit_symbol.")

                    match_val = emp_code if key_field == "employee_code" else card_id
                    if match_val:
                        if match_val in seen_keys_in_file:
                            errors.append(f"Dòng {r}: Trùng khóa {key_field}='{match_val}' trong file.")
                            continue
                        seen_keys_in_file.add(match_val)

                    if card_id:
                        if card_id in seen_cards_in_file:
                            errors.append(f"Dòng {r}: Trùng card_id='{card_id}' trong file.")
                            continue
                        seen_cards_in_file.add(card_id)

                    jt = jt_cache_by_code.get(jt_value) or jt_cache_by_name.get(jt_value)
                    if not jt:
                        raise ValueError(f"Chức danh '{jt_value}' không tồn tại.")
                    if not jt.is_active:
                        raise ValueError(f"Chức danh '{jt_value}' đã ngừng hoạt động.")

                    unit = unit_cache.get(unit_symbol)
                    if not unit:
                        raise ValueError(f"Đơn vị '{unit_symbol}' không tồn tại.")
                    if unit.id not in allowed_unit_ids:
                        raise ValueError(f"Bạn không có quyền nhập nhân sự vào đơn vị '{unit_symbol}'.")
                    if not unit.is_active:
                        raise ValueError(f"Đơn vị '{unit_symbol}' đã ngừng hoạt động.")
                    if unit.type not in [OrgUnit.Type.DEPARTMENT, OrgUnit.Type.DIVISION, OrgUnit.Type.WORKSHOP]:
                        raise ValueError("unit_symbol phải là Phòng/Ban/Phân xưởng; không được là Nhà máy hoặc Tổ.")

                    team = unit_cache.get(team_symbol) if team_symbol else None
                    if team:
                        if team.type != OrgUnit.Type.TEAM:
                            raise ValueError(f"team_symbol '{team_symbol}' không phải loại TEAM.")
                        if not team.is_active:
                            raise ValueError(f"Tổ '{team_symbol}' đã ngừng hoạt động.")
                        if not _team_belongs_to_unit(team, unit):
                            raise ValueError(f"Tổ '{team_symbol}' không thuộc cây đơn vị '{unit_symbol}'.")

                    emp = None
                    if key_field == "employee_code":
                        if emp_code:
                            emp = Employee.objects.filter(employee_code=emp_code).first()
                    else:
                        if card_id:
                            emp = Employee.objects.filter(card_id=card_id).first()

                    if emp:
                        if emp.unit_id not in allowed_unit_ids:
                            raise ValueError(f"Bạn không có quyền cập nhật nhân sự '{emp.employee_code}'.")

                        if mode in ("update_only", "upsert"):
                            if card_id and card_id != emp.card_id:
                                other = Employee.objects.filter(card_id=card_id).exclude(pk=emp.pk).first()
                                if other:
                                    raise ValueError(f"card_id '{card_id}' đã thuộc nhân sự {other.employee_code}.")

                            emp.full_name = full_name
                            emp.workforce_type = workforce_type
                            emp.job_title = jt
                            emp.unit = unit
                            emp.team = team
                            emp.citizen_id = citizen_id
                            emp.tax_code = tax_code
                            if card_id:
                                emp.card_id = card_id
                            emp.bank_account = bank_account
                            emp.bank_name = bank_name
                            emp.email = email
                            emp.phone = phone
                            emp.joined_date = joined_date or emp.joined_date
                            emp.status = status or emp.status
                            emp.skip_device_attendance = skip_device_attendance
                            emp.note = note
                            emp.full_clean()
                            if commit:
                                emp.save()
                            updated += 1
                        else:
                            skipped += 1
                    else:
                        if mode in ("create_only", "upsert"):
                            if card_id and card_id in existing_cards:
                                raise ValueError(f"card_id '{card_id}' đã tồn tại.")
                            if citizen_id and citizen_id in existing_citizens:
                                raise ValueError(f"citizen_id '{citizen_id}' đã tồn tại.")
                            if email and email in existing_emails:
                                raise ValueError(f"email '{email}' đã tồn tại.")
                            if phone and phone in existing_phones:
                                raise ValueError(f"phone '{phone}' đã tồn tại.")

                            if not emp_code:
                                emp_code = f"E{next_emp_num:06d}"
                                next_emp_num += 1
                            else:
                                if emp_code in existing_codes:
                                    raise ValueError(f"employee_code '{emp_code}' đã tồn tại.")

                            new_emp = Employee(
                                employee_code=emp_code,
                                full_name=full_name,
                                workforce_type=workforce_type,
                                job_title=jt,
                                unit=unit,
                                team=team,
                                citizen_id=citizen_id,
                                tax_code=tax_code,
                                card_id=card_id,
                                bank_account=bank_account,
                                bank_name=bank_name,
                                email=email,
                                phone=phone,
                                joined_date=joined_date,
                                status=status,
                                skip_device_attendance=skip_device_attendance,
                                note=note,
                            )
                            new_emp.full_clean()
                            if commit:
                                new_emp.save()
                                existing_codes.add(emp_code)
                                if card_id:
                                    existing_cards.add(card_id)
                                if citizen_id:
                                    existing_citizens.add(citizen_id)
                                if email:
                                    existing_emails.add(email)
                                if phone:
                                    existing_phones.add(phone)
                            created += 1
                        else:
                            skipped += 1

                except Exception as e:
                    errors.append(f"Dòng {r}: {e}")

            audit_log(
                action_verb="UPDATE",
                object_type="employee",
                object_id="bulk",
                object_repr="IMPORT",
                actor=request.user,
                extra={
                    "mode": mode,
                    "match_by": key_field,
                    "dry_run": dry_run,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "errors": len(errors),
                },
                request=request,
                action_code="EMPLOYEE_IMPORT_ADV",
            )

            if errors:
                sample = "; ".join(errors[:10])
                messages.warning(
                    request,
                    f"[{'DRY-RUN' if dry_run else 'COMMIT'}] Tạo: {created}, Cập nhật: {updated}, "
                    f"Bỏ qua: {skipped}, Lỗi: {len(errors)}. {sample}",
                )
            else:
                messages.success(
                    request,
                    f"[{'DRY-RUN' if dry_run else 'COMMIT'}] Tạo: {created}, Cập nhật: {updated}, Bỏ qua: {skipped}.",
                )

        finally:
            if commit:
                ctx.__exit__(None, None, None)

        return redirect("backoffice:employee_list")

    return render(
        request,
        "backoffice/hr/employees/import.html",
        {
            "title": "Nhập Excel - Nhân sự (nâng cao)",
            "note": "Chọn khóa khớp, chế độ nhập và dry-run trước khi tải file.",
            "post_url": "backoffice:import_employees",
            "default_dry_run": True,
        },
    )
