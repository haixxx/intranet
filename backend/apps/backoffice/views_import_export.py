import io
from datetime import datetime, date as date_cls
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from openpyxl import Workbook, load_workbook
from apps.organization.models import OrgUnit, JobTitle, ShiftTemplate
from apps.hr.models import Employee
from apps.audit.utils import audit_log
from apps.hr.services import allowed_org_ids_for_user
from apps.hr.services.assignments import employee_ids_effective_in_units, effective_unit_for

# ==================== COMMON ====================

def _xlsx_response(wb: Workbook, filename_prefix: str) -> HttpResponse:
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{ts}.xlsx"'
    return resp

# ==================== ORGUNIT EXPORT/IMPORT ====================

@login_required
@permission_required('organization.view_orgunit', raise_exception=True)
def export_orgunits(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "OrgUnits"
    headers = ["type", "name", "symbol", "parent_symbol", "is_active"]
    ws.append(headers)
    for u in OrgUnit.objects.select_related('parent').order_by('type', 'symbol'):
        ws.append([
            u.type,
            u.name,
            u.symbol,
            (u.parent.symbol if u.parent_id else ""),
            "true" if u.is_active else "false"
        ])
    return _xlsx_response(wb, "OrgUnits")


@login_required
@permission_required('organization.add_orgunit', raise_exception=True)
def import_orgunits(request):
    if request.method == 'POST' and request.FILES.get('file'):
        wb = load_workbook(request.FILES['file'])
        ws = wb.active
        headers = [c.value for c in ws[1]]
        required = ["type", "name", "symbol", "parent_symbol", "is_active"]
        if headers[:len(required)] != required:
            messages.error(request, "Header không đúng định dạng.")
            return redirect('backoffice:orgunit_list')
        created, updated, errors = 0, 0, []
        symbols_cache = {u.symbol: u for u in OrgUnit.objects.all()}
        from django.db.models import Max
        for i in range(2, ws.max_row + 1):
            try:
                typ = (ws.cell(i, 1).value or "").strip()
                name = (ws.cell(i, 2).value or "").strip()
                symbol = (ws.cell(i, 3).value or "").strip()
                parent_symbol = (ws.cell(i, 4).value or "").strip()
                is_active_raw = (ws.cell(i, 5).value or "")
                is_active = str(is_active_raw).lower() in ("true", "1", "yes")

                if not typ or not name or not symbol:
                    continue

                if typ == 'PLANT':
                    parent = None
                else:
                    if not parent_symbol:
                        raise ValueError("parent_symbol bắt buộc với đơn vị con.")
                    parent = symbols_cache.get(parent_symbol) or OrgUnit.objects.filter(symbol=parent_symbol).first()
                    if not parent:
                        raise ValueError(f"parent_symbol '{parent_symbol}' không tồn tại.")

                obj = OrgUnit.objects.filter(symbol=symbol).first()
                if obj:
                    obj.name = name
                    obj.type = typ
                    obj.parent = parent
                    obj.is_active = is_active
                    obj.full_clean()
                    obj.save()
                    updated += 1
                else:
                    max_code = OrgUnit.objects.aggregate(m=Max('code'))['m']
                    next_num = (int(max_code[2:]) + 1) if (max_code and max_code.startswith('OU')) else 1
                    code = f"OU{next_num:04d}"
                    obj = OrgUnit(code=code, symbol=symbol, name=name, type=typ, parent=parent, is_active=is_active)
                    obj.full_clean()
                    obj.save()
                    symbols_cache[symbol] = obj
                    created += 1
            except Exception as e:
                errors.append(f"Dòng {i}: {e}")

        audit_log(action_verb="UPDATE", object_type="orgunit", object_id="bulk", object_repr="IMPORT",
                  actor=request.user, extra={"created": created, "updated": updated, "errors": len(errors)},
                  request=request, action_code="ORGUNIT_IMPORT")
        if errors:
            messages.warning(request, f"Tạo mới: {created}, Cập nhật: {updated}, Lỗi: {len(errors)}. {errors[:5]}")
        else:
            messages.success(request, f"Tạo mới: {created}, Cập nhật: {updated}.")
        return redirect('backoffice:orgunit_list')

    return render(request, 'backoffice/common/import.html', {
        'title': "Nhập Excel - Cơ cấu tổ chức",
        'note': "File .xlsx: header type,name,symbol,parent_symbol,is_active",
        'post_url': 'backoffice:import_orgunits',
    })

# ==================== JOBTITLE EXPORT/IMPORT ====================

@login_required
@permission_required('organization.view_jobtitle', raise_exception=True)
def export_jobtitles(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "JobTitles"
    ws.append(["name", "code", "is_active"])
    for jt in JobTitle.objects.order_by('name'):
        ws.append([jt.name, jt.code or "", "true" if jt.is_active else "false"])
    return _xlsx_response(wb, "JobTitles")


@login_required
@permission_required('organization.add_jobtitle', raise_exception=True)
def import_jobtitles(request):
    if request.method == 'POST' and request.FILES.get('file'):
        wb = load_workbook(request.FILES['file'])
        ws = wb.active
        headers = [c.value for c in ws[1]]
        if headers[:3] != ["name", "code", "is_active"]:
            messages.error(request, "Header không đúng định dạng.")
            return redirect('backoffice:jobtitle_list')
        created, updated, errors = 0, 0, []
        for i in range(2, ws.max_row + 1):
            try:
                name = (ws.cell(i, 1).value or "").strip()
                code = (ws.cell(i, 2).value or "") or None
                is_active_raw = (ws.cell(i, 3).value or "")
                is_active = str(is_active_raw).lower() in ("true", "1", "yes")
                if not name:
                    continue
                obj = JobTitle.objects.filter(name=name).first()
                if obj:
                    obj.code = code or obj.code
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

        audit_log(action_verb="UPDATE", object_type="jobtitle", object_id="bulk", object_repr="IMPORT",
                  actor=request.user, extra={"created": created, "updated": updated, "errors": len(errors)},
                  request=request, action_code="JOBTITLE_IMPORT")
        if errors:
            messages.warning(request, f"Tạo mới: {created}, Cập nhật: {updated}, Lỗi: {len(errors)}. {errors[:5]}")
        else:
            messages.success(request, f"Tạo mới: {created}, Cập nhật: {updated}.")
        return redirect('backoffice:jobtitle_list')

    return render(request, 'backoffice/common/import.html', {
        'title': "Nhập Excel - Chức vụ",
        'note': "File .xlsx: header name,code,is_active",
        'post_url': 'backoffice:import_jobtitles',
    })

# ==================== SHIFT EXPORT/IMPORT ====================

@login_required
@permission_required('organization.view_shifttemplate', raise_exception=True)
def export_shifts(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "ShiftTemplates"
    ws.append(["code", "name", "type", "start_time", "end_time", "breaks_json", "crosses_midnight", "is_active"])
    for s in ShiftTemplate.objects.order_by('code'):
        ws.append([
            s.code, s.name, s.type,
            s.start_time.strftime("%H:%M"),
            s.end_time.strftime("%H:%M"),
            ("" if not s.breaks else str(s.breaks).replace("'", '"')),
            "true" if s.crosses_midnight else "false",
            "true" if s.is_active else "false",
        ])
    return _xlsx_response(wb, "ShiftTemplates")


@login_required
@permission_required('organization.add_shifttemplate', raise_exception=True)
def import_shifts(request):
    if request.method == 'POST' and request.FILES.get('file'):
        wb = load_workbook(request.FILES['file'])
        ws = wb.active
        headers = [c.value for c in ws[1]]
        required = ["code", "name", "type", "start_time", "end_time", "breaks_json", "crosses_midnight", "is_active"]
        if headers[:len(required)] != required:
            messages.error(request, "Header không đúng định dạng.")
            return redirect('backoffice:shift_list')
        from datetime import datetime as dt
        import json
        created, updated, errors = 0, 0, []
        for i in range(2, ws.max_row + 1):
            try:
                code = (ws.cell(i, 1).value or "").strip()
                name = (ws.cell(i, 2).value or "").strip()
                typ = (ws.cell(i, 3).value or "").strip()
                st_raw = (ws.cell(i, 4).value or "").strip()
                et_raw = (ws.cell(i, 5).value or "").strip()
                breaks_json = (ws.cell(i, 6).value or "").strip()
                crosses_raw = (ws.cell(i, 7).value or "")
                active_raw = (ws.cell(i, 8).value or "")
                if not code:
                    continue
                stime = dt.strptime(st_raw, "%H:%M").time()
                etime = dt.strptime(et_raw, "%H:%M").time()
                brks = []
                if breaks_json:
                    brks = json.loads(breaks_json)
                crosses_midnight = str(crosses_raw).lower() in ("true", "1", "yes")
                is_active = str(active_raw).lower() in ("true", "1", "yes")
                obj, is_new = ShiftTemplate.objects.update_or_create(
                    code=code,
                    defaults={
                        'name': name,
                        'type': typ,
                        'start_time': stime,
                        'end_time': etime,
                        'breaks': brks,
                        'crosses_midnight': crosses_midnight,
                        'is_active': is_active,
                    }
                )
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                errors.append(f"Dòng {i}: {e}")

        audit_log(action_verb="UPDATE", object_type="shift", object_id="bulk", object_repr="IMPORT",
                  actor=request.user, extra={"created": created, "updated": updated, "errors": len(errors)},
                  request=request, action_code="SHIFT_IMPORT")
        if errors:
            messages.warning(request, f"Tạo mới: {created}, Cập nhật: {updated}, Lỗi: {len(errors)}. {errors[:5]}")
        else:
            messages.success(request, f"Tạo mới: {created}, Cập nhật: {updated}.")
        return redirect('backoffice:shift_list')

    return render(request, 'backoffice/common/import.html', {
        'title': "Nhập Excel - Ca làm việc",
        'note': "File .xlsx: header code,name,type,start_time,end_time,breaks_json,crosses_midnight,is_active",
        'post_url': 'backoffice:import_shifts',
    })

# ==================== EMPLOYEE EXPORT (thêm chế độ hiệu lực) ====================

@login_required
@permission_required('hr.view_employee', raise_exception=True)
def export_employees(request):
    q = request.GET.get('q', '').strip()
    units_param = request.GET.get('units', '').strip()
    jt_filter = request.GET.get('job_title', '').strip()
    team_filter = request.GET.get('team', '').strip()
    effective_mode = request.GET.get('effective_mode', '').strip() == '1'
    effective_date_param = request.GET.get('effective_date', '').strip()

    if effective_date_param:
        try:
            effective_date = date_cls.fromisoformat(effective_date_param)
        except ValueError:
            effective_date = date_cls.today()
    else:
        effective_date = date_cls.today()

    # Units parse
    units_selected = []
    if units_param:
        for p in units_param.split(','):
            p = p.strip()
            if p.isdigit():
                units_selected.append(int(p))

    unit_ids_scope = set(allowed_org_ids_for_user(request.user))
    qs_base = Employee.objects.select_related('job_title', 'unit', 'team').filter(unit_id__in=unit_ids_scope)

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
            Q(full_name__icontains=q) |
            Q(employee_code__icontains=q) |
            Q(card_id__icontains=q)
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"

    base_headers = [
        "full_name", "workforce_type", "job_title", "unit_symbol", "team_symbol",
        "employee_code", "citizen_id", "tax_code", "card_id", "bank_account", "bank_name",
        "email", "phone", "joined_date", "status", "note"
    ]
    if effective_mode:
        # Thêm cột effective_unit ngay sau team_symbol
        base_headers.insert(5, "effective_unit_symbol")

    ws.append(base_headers)

    for e in qs.order_by('employee_code'):
        row = [
            e.full_name,
            e.workforce_type,
            e.job_title.name if e.job_title_id else "",
            e.unit.symbol if e.unit_id else "",
            e.team.symbol if e.team_id else "",
        ]
        if effective_mode:
            eff_unit_id, source = effective_unit_for(e.id, effective_date)
            from apps.organization.models import OrgUnit
            eff_symbol = OrgUnit.objects.filter(pk=eff_unit_id).values_list('symbol', flat=True).first() or ""
            row.append(eff_symbol)
        row.extend([
            e.employee_code,
            e.citizen_id or "",
            e.tax_code or "",
            e.card_id or "",
            e.bank_account or "",
            e.bank_name or "",
            e.email or "",
            e.phone or "",
            (e.joined_date.isoformat() if e.joined_date else ""),
            e.status,
            e.note or ""
        ])
        ws.append(row)

    return _xlsx_response(wb, "EmployeesFiltered")

# ==================== EMPLOYEE IMPORT (nâng cao – giữ nguyên logic upsert) ====================

@login_required
@permission_required('hr.add_employee', raise_exception=True)
def import_employees(request):
    """
    Import nhân sự nâng cao:
      match_by: employee_code | card_id
      mode: update_only | create_only | upsert
      dry_run: xem trước
    """
    if request.method == 'POST' and request.FILES.get('file'):
        match_by = request.POST.get('match_by', 'employee_code').strip() or 'employee_code'
        mode = request.POST.get('mode', 'upsert').strip() or 'upsert'
        dry_run = request.POST.get('dry_run', 'true').lower() in ('1', 'true', 'yes', 'on')

        wb = load_workbook(request.FILES['file'])
        ws = wb.active
        headers = [str(c.value or "").strip() for c in ws[1]]

        def norm(h): return "".join(str(h).strip().lower().split())
        header_norm = [norm(h) for h in headers]
        ALIAS_MAP = {
            'full_name': {'fullname', 'hoten', 'full_name'},
            'workforce_type': {'workforcetype', 'workforce', 'loainghiepvu', 'workforce_type'},
            'job_title': {'jobtitle', 'title', 'chucvu', 'job_title'},
            'unit_symbol': {'unitsymbol', 'unit', 'donvi', 'unit_symbol'},
            'team_symbol': {'teamsymbol', 'team', 'to', 'tosymbol', 'team_symbol'},
            'employee_code': {'employeecode', 'empcode', 'manv', 'employee_code'},
            'citizen_id': {'citizenid', 'cccd', 'citizen_id'},
            'tax_code': {'taxcode', 'mst', 'tax_code'},
            'card_id': {'cardid', 'card', 'machamcong', 'card_id'},
            'bank_account': {'bankaccount', 'stk', 'account', 'bank_account'},
            'bank_name': {'bankname', 'nganhang', 'bank_name'},
            'email': {'email', 'mail'},
            'phone': {'phone', 'sdt'},
            'joined_date': {'joineddate', 'joined_dat', 'joined_date', 'joindate', 'join_date'},
            'status': {'status', 'trangthai', 'trang_thai'},
            'note': {'note', 'ghichu', 'ghi_chu'},
        }
        col_index = {}
        for idx, hn in enumerate(header_norm, start=1):
            for std, aliases in ALIAS_MAP.items():
                if hn in aliases and std not in col_index:
                    col_index[std] = idx

        mandatory = ['full_name', 'workforce_type', 'job_title', 'unit_symbol', 'status']
        missing = [m for m in mandatory if m not in col_index]
        if missing:
            messages.error(request, f"Thiếu cột bắt buộc: {missing}.")
            return redirect('backoffice:employee_list')

        from datetime import datetime as dt
        jt_cache = {j.name: j.id for j in JobTitle.objects.all()}
        unit_cache = {u.symbol: u for u in OrgUnit.objects.all()}

        def cell(row, key):
            c = col_index.get(key)
            return row[c - 1].value if c else None
        def to_str(v):
            if v is None: return None
            s = str(v).strip()
            return s if s != "" else None
        def to_intlike_str(v):
            if v is None or v == "": return None
            try:
                if isinstance(v, float) and v.is_integer(): return str(int(v))
                if isinstance(v, int): return str(v)
                s = str(v).strip()
                if s.endswith(".0"): s = s[:-2]
                return s
            except Exception:
                return str(v).strip()
        def to_date(v):
            if v in (None, ""): return None
            if isinstance(v, date_cls): return v
            if isinstance(v, datetime): return v.date()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try: return dt.strptime(str(v).strip(), fmt).date()
                except Exception: pass
            return None

        key_field = 'employee_code' if match_by == 'employee_code' else 'card_id'

        existing_codes = set(Employee.objects.exclude(employee_code__isnull=True).values_list('employee_code', flat=True))
        existing_cards = set(Employee.objects.exclude(card_id__isnull=True).values_list('card_id', flat=True))
        existing_citizens = set(Employee.objects.exclude(citizen_id__isnull=True).values_list('citizen_id', flat=True))
        existing_emails = set(Employee.objects.exclude(email__isnull=True).values_list('email', flat=True))
        existing_phones = set(Employee.objects.exclude(phone__isnull=True).values_list('phone', flat=True))

        seen_keys_in_file = set()
        created = updated = skipped = 0
        errors = []

        from django.db.models import Max
        max_code = Employee.objects.aggregate(m=Max('employee_code'))['m']
        next_emp_num = (int(max_code[1:]) + 1) if (max_code and isinstance(max_code, str) and max_code.startswith('E')) else 1

        commit = not dry_run
        ctx = transaction.atomic() if commit else None
        if commit: ctx.__enter__()

        try:
            for r in range(2, ws.max_row + 1):
                row = ws[r]
                try:
                    full_name = to_str(cell(row, 'full_name'))
                    workforce_type = to_str(cell(row, 'workforce_type'))
                    jt_name = to_str(cell(row, 'job_title'))
                    unit_symbol = to_str(cell(row, 'unit_symbol'))
                    team_symbol = to_str(cell(row, 'team_symbol'))
                    emp_code = to_str(cell(row, 'employee_code'))
                    citizen_id = to_intlike_str(cell(row, 'citizen_id'))
                    tax_code = to_intlike_str(cell(row, 'tax_code'))
                    card_id = to_intlike_str(cell(row, 'card_id'))
                    bank_account = to_intlike_str(cell(row, 'bank_account'))
                    bank_name = to_str(cell(row, 'bank_name'))
                    email = to_str(cell(row, 'email'))
                    phone = to_intlike_str(cell(row, 'phone'))
                    joined_date = to_date(cell(row, 'joined_date'))
                    status = to_str(cell(row, 'status')) or "ACTIVE"
                    note = to_str(cell(row, 'note'))

                    if not full_name:
                        continue
                    if not workforce_type or not jt_name or not unit_symbol:
                        raise ValueError("Thiếu workforce_type / job_title / unit_symbol.")

                    match_val = emp_code if key_field == 'employee_code' else card_id
                    if match_val:
                        if match_val in seen_keys_in_file:
                            errors.append(f"Dòng {r}: Trùng khóa {key_field}='{match_val}' trong file.")
                            continue
                        seen_keys_in_file.add(match_val)

                    jt_id = jt_cache.get(jt_name)
                    if not jt_id:
                        raise ValueError(f"Chức vụ '{jt_name}' không tồn tại.")
                    unit = unit_cache.get(unit_symbol)
                    if not unit:
                        raise ValueError(f"Đơn vị '{unit_symbol}' không tồn tại.")
                    team = unit_cache.get(team_symbol) if team_symbol else None

                    emp = None
                    if key_field == 'employee_code':
                        if emp_code:
                            emp = Employee.objects.filter(employee_code=emp_code).first()
                    else:
                        if card_id:
                            emp = Employee.objects.filter(card_id=card_id).first()

                    if emp:
                        if mode in ('update_only', 'upsert'):
                            emp.full_name = full_name
                            emp.workforce_type = workforce_type
                            emp.job_title_id = jt_id
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
                            emp.note = note
                            emp.full_clean()
                            if commit:
                                emp.save()
                            updated += 1
                        else:
                            skipped += 1
                    else:
                        if mode in ('create_only', 'upsert'):
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
                                job_title_id=jt_id,
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
                                note=note
                            )
                            new_emp.full_clean()
                            if commit:
                                new_emp.save()
                                existing_codes.add(emp_code)
                                if card_id: existing_cards.add(card_id)
                                if citizen_id: existing_citizens.add(citizen_id)
                                if email: existing_emails.add(email)
                                if phone: existing_phones.add(phone)
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
                extra={"mode": mode, "match_by": key_field, "dry_run": dry_run,
                       "created": created, "updated": updated, "skipped": skipped, "errors": len(errors)},
                request=request,
                action_code="EMPLOYEE_IMPORT_ADV",
            )

            if errors:
                sample = "; ".join(errors[:10])
                messages.warning(request, f"[{'DRY-RUN' if dry_run else 'COMMIT'}] Tạo: {created}, Cập nhật: {updated}, Bỏ qua: {skipped}, Lỗi: {len(errors)}. {sample}")
            else:
                messages.success(request, f"[{'DRY-RUN' if dry_run else 'COMMIT'}] Tạo: {created}, Cập nhật: {updated}, Bỏ qua: {skipped}.")

        finally:
            if commit:
                ctx.__exit__(None, None, None)

        return redirect('backoffice:employee_list')

    return render(request, 'backoffice/hr/employees/import.html', {
        'title': "Nhập Excel - Nhân sự (nâng cao)",
        'note': "Chọn khóa khớp, chế độ nhập và dry-run trước khi tải file.",
        'post_url': 'backoffice:import_employees',
        'default_dry_run': True,
    })