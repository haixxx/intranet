from __future__ import annotations

from datetime import datetime, date as date_cls

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q, F, Case, When, IntegerField
from django.shortcuts import render, redirect
from django.utils import timezone as dj_timezone

from apps.attendance.models_batch import AttendanceCommit
from apps.organization.models import OrgUnit
from apps.backoffice.services.access_scope import get_allowed_attendance_units, get_allowed_attendance_unit_ids

from .models_master_list import AttendanceDeviceMasterListV2


def _parse_date(s: str) -> date_cls | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _threshold_min(raw: str) -> int:
    try:
        v = int(raw)
    except Exception:
        v = 5
    if v not in (5, 10, 15):
        v = 5
    return v


@login_required
def master_summary_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem Master List (v2)"
        }, status=403)

    from_date = _parse_date(request.GET.get("from"))
    to_date = _parse_date(request.GET.get("to"))
    threshold = _threshold_min(request.GET.get("threshold") or "5")
    threshold_sec = threshold * 60

    rows = []
    if from_date and to_date and from_date <= to_date:
        allowed_unit_ids = get_allowed_attendance_unit_ids(request.user)
        base = AttendanceDeviceMasterListV2.objects.filter(
            work_date__gte=from_date,
            work_date__lte=to_date,
            expected_marks__gt=0,
            is_exempt=False,
        )
        base = base.filter(unit_id__in=allowed_unit_ids) if allowed_unit_ids else base.none()

        # late/early people: any delta crosses threshold
        late_q = (
            Q(expected_in1=True, delta_in1_seconds__gt=threshold_sec) |
            Q(expected_in2=True, delta_in2_seconds__gt=threshold_sec)
        )
        early_q = (
            Q(expected_out1=True, delta_out1_seconds__lt=-threshold_sec) |
            Q(expected_out2=True, delta_out2_seconds__lt=-threshold_sec)
        )

        agg = (
            base.values("unit_id")
            .annotate(
                headcount=Count("id"),
                ok_people=Count("id", filter=Q(missing_marks=0)),
                missing_people=Count("id", filter=Q(missing_marks__gt=0)),
                missing_marks=Sum("missing_marks"),
                late_people=Count("id", filter=late_q),
                early_people=Count("id", filter=early_q),
            )
            .order_by("-missing_marks", "-missing_people", "unit_id")
        )

        unit_ids = [x["unit_id"] for x in agg]
        unit_map = {u.id: u for u in OrgUnit.objects.filter(id__in=unit_ids)}

        for x in agg:
            u = unit_map.get(x["unit_id"])
            headcount = x["headcount"] or 0
            ok_people = x["ok_people"] or 0
            rows.append({
                "unit_id": x["unit_id"],
                "unit_symbol": u.symbol if u else f"#{x['unit_id']}",
                "unit_name": u.name if u else "",
                "headcount": headcount,
                "ok_people": ok_people,
                "ok_rate": (ok_people / headcount * 100.0) if headcount else 0.0,
                "missing_people": x["missing_people"] or 0,
                "missing_marks": x["missing_marks"] or 0,
                "late_people": x["late_people"] or 0,
                "early_people": x["early_people"] or 0,
            })

    return render(request, "backoffice/attendance_devices_v2/master_summary.html", {
        "from_date": request.GET.get("from") or "",
        "to_date": request.GET.get("to") or "",
        "threshold_min": threshold,
        "rows": rows,
    })


@login_required
def master_list_view(request):
    if not request.user.has_perm("attendance.view_attendancecommit"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance.view_attendancecommit",
            "title": "Bạn chưa được cấp quyền xem Master List (v2)"
        }, status=403)

    from_date = _parse_date(request.GET.get("from"))
    to_date = _parse_date(request.GET.get("to"))
    unit_raw = (request.GET.get("unit") or "").strip()
    status_filter = (request.GET.get("filter") or "").strip().lower()  # missing/late/early/stale
    threshold = _threshold_min(request.GET.get("threshold") or "5")
    threshold_sec = threshold * 60
    q = (request.GET.get("q") or "").strip()

    allowed_unit_ids = get_allowed_attendance_unit_ids(request.user)
    requested_unit_id = int(unit_raw) if unit_raw.isdigit() else None
    invalid_unit_filter = requested_unit_id is not None and requested_unit_id not in allowed_unit_ids

    qs = AttendanceDeviceMasterListV2.objects.select_related("employee", "unit", "commit").all()
    qs = qs.filter(unit_id__in=allowed_unit_ids) if allowed_unit_ids else qs.none()

    if from_date:
        qs = qs.filter(work_date__gte=from_date)
    if to_date:
        qs = qs.filter(work_date__lte=to_date)
    if invalid_unit_filter:
        qs = qs.none()
    elif requested_unit_id is not None:
        qs = qs.filter(unit_id=requested_unit_id)
    if q:
        qs = qs.filter(
            Q(employee__employee_code__icontains=q) |
            Q(employee__full_name__icontains=q) |
            Q(employee__card_id__icontains=q)
        )

    # only meaningful rows
    qs = qs.filter(expected_marks__gt=0)

    # derived filters
    late_q = (
        Q(is_exempt=False) &
        (Q(expected_in1=True, delta_in1_seconds__gt=threshold_sec) | Q(expected_in2=True, delta_in2_seconds__gt=threshold_sec))
    )
    early_q = (
        Q(is_exempt=False) &
        (Q(expected_out1=True, delta_out1_seconds__lt=-threshold_sec) | Q(expected_out2=True, delta_out2_seconds__lt=-threshold_sec))
    )

    if status_filter == "missing":
        qs = qs.filter(is_exempt=False, missing_marks__gt=0)
    elif status_filter == "late":
        qs = qs.filter(late_q)
    elif status_filter == "early":
        qs = qs.filter(early_q)
    elif status_filter == "stale":
        qs = qs.filter(compute_state=AttendanceDeviceMasterListV2.ComputeState.STALE)

    qs = qs.order_by("-work_date", "unit_id", "employee__employee_code")[:2000]

    units = get_allowed_attendance_units(request.user)

    return render(request, "backoffice/attendance_devices_v2/master_list.html", {
        "from_date": request.GET.get("from") or "",
        "to_date": request.GET.get("to") or "",
        "unit": unit_raw,
        "filter": status_filter,
        "threshold_min": threshold,
        "q": q,
        "rows": qs,
        "units": units,
    })


@login_required
def master_edit_view(request):
    if not request.user.has_perm("attendance_devices_v2.change_attendancedevicemasterlistv2"):
        return render(request, "backoffice/no_permission.html", {
            "perm_codename": "attendance_devices_v2.change_attendancedevicemasterlistv2",
            "title": "Bạn chưa được cấp quyền sửa Master List (v2)"
        }, status=403)

    work_date = _parse_date(request.GET.get("date")) or _parse_date(request.POST.get("date")) or dj_timezone.localdate()
    unit_raw = (request.GET.get("unit") or request.POST.get("unit") or "").strip()

    allowed_unit_ids = get_allowed_attendance_unit_ids(request.user)
    requested_unit_id = int(unit_raw) if unit_raw.isdigit() else None
    invalid_unit_filter = requested_unit_id is not None and requested_unit_id not in allowed_unit_ids

    qs = AttendanceDeviceMasterListV2.objects.select_related("employee", "unit").filter(work_date=work_date)
    qs = qs.filter(unit_id__in=allowed_unit_ids) if allowed_unit_ids else qs.none()
    if invalid_unit_filter:
        qs = qs.none()
    elif requested_unit_id is not None:
        qs = qs.filter(unit_id=requested_unit_id)

    qs = qs.order_by("employee__employee_code")[:2000]

    if request.method == "POST":
        now = dj_timezone.now()
        # POST fields: override_<id>_<field>
        updated = 0
        for row in qs:
            prefix = f"row_{row.id}_"
            changed = False

            def parse_dt(name):
                raw = (request.POST.get(prefix + name) or "").strip()
                if not raw:
                    return None
                # input type="datetime-local" => "YYYY-MM-DDTHH:MM"
                try:
                    return dj_timezone.make_aware(datetime.strptime(raw, "%Y-%m-%dT%H:%M"), dj_timezone.get_current_timezone())
                except Exception:
                    return None

            for fld in ("override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local"):
                val = parse_dt(fld)
                if getattr(row, fld) != val:
                    setattr(row, fld, val)
                    changed = True

            note = (request.POST.get(prefix + "override_note") or "").strip()
            if row.override_note != note:
                row.override_note = note
                changed = True

            if changed:
                row.override_by = request.user
                row.override_at = now
                row.save(update_fields=[
                    "override_in1_local", "override_out1_local", "override_in2_local", "override_out2_local",
                    "override_note", "override_by", "override_at"
                ])
                updated += 1

        return redirect(f"{request.path}?date={work_date.strftime('%Y-%m-%d')}&unit={unit_raw}")

    units = get_allowed_attendance_units(request.user)
    return render(request, "backoffice/attendance_devices_v2/master_edit.html", {
        "work_date": work_date.strftime("%Y-%m-%d"),
        "unit": unit_raw,
        "rows": qs,
        "units": units,
    })