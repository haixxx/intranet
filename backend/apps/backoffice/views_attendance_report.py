from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.attendance.models_batch import (
    AttendanceBatch,
    AttendanceBatchItem,
    AttendanceCommit,
    AttendanceCommitItem,
    AttendanceCorrectionRequest,
)
from apps.hr.models import Employee
from apps.backoffice.services.access_scope import get_allowed_attendance_units
try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:  # pragma: no cover - an toàn khi app chưa sẵn sàng trong migration shell
    TempAssignment = None
from apps.organization.models import OrgUnit

try:
    from apps.approvals.models import ApprovalRequest
    from apps.approvals.status_utils import build_approval_status_context
except Exception:  # pragma: no cover - dashboard vẫn chạy nếu module approvals chưa sẵn sàng
    ApprovalRequest = None
    build_approval_status_context = None


PENDING_CORRECTION_STATUSES = [
    AttendanceCorrectionRequest.Status.REQUESTED,
    AttendanceCorrectionRequest.Status.APPROVED_BY_UNIT,
]
WAITING_APPLY_CORRECTION_STATUSES = [
    AttendanceCorrectionRequest.Status.APPROVED_BY_HR,
]
FINAL_CORRECTION_STATUSES = [
    AttendanceCorrectionRequest.Status.APPLIED,
    AttendanceCorrectionRequest.Status.REJECTED,
    AttendanceCorrectionRequest.Status.CANCELLED,
]
OPEN_CORRECTION_STATUSES = PENDING_CORRECTION_STATUSES + WAITING_APPLY_CORRECTION_STATUSES


def _parse_date(value: str):
    """Nhận cả YYYY-MM-DD và DD/MM/YYYY để form Việt hóa vẫn dùng được."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _date_range(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0.00")


def _display_decimal(value):
    value = _to_decimal(value)
    if value == value.to_integral_value():
        return int(value)
    return float(value.normalize())


def _url_with_query(view_name: str, **params) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    base = reverse(view_name)
    return f"{base}?{urlencode(clean)}" if clean else base


def _units_for_attendance(request):
    """Lấy đơn vị chấm công theo AccessControl, không tự mở toàn bộ khi thiếu scope."""
    return get_allowed_attendance_units(request.user)


def _safe_int(raw):
    try:
        return int(raw)
    except Exception:
        return None


def _item_code_text(item) -> str:
    if isinstance(item, AttendanceCommitItem):
        return getattr(item, "code_snapshot", "") or (item.code.code if item.code_id and item.code else "")
    return item.code.code if item and item.code_id and item.code else ""


def _item_code_label(item) -> str:
    if isinstance(item, AttendanceCommitItem):
        return getattr(item, "label_snapshot", "") or (item.code.label_vi if item.code_id and item.code else "")
    return item.code.label_vi if item and item.code_id and item.code else ""


def _commit_credit(item: AttendanceCommitItem, snapshot_field: str, code_field: str) -> Decimal:
    # Nếu đã có code_snapshot thì snapshot là nguồn lịch sử. Dòng cũ chưa backfill snapshot sẽ fallback về mã hiện tại.
    if getattr(item, "code_snapshot", ""):
        return _to_decimal(getattr(item, snapshot_field, 0))
    code = getattr(item, "code", None)
    return _to_decimal(getattr(code, code_field, 0) if code else 0)


def _batch_credit(item: AttendanceBatchItem, code_field: str) -> Decimal:
    code = getattr(item, "code", None)
    return _to_decimal(getattr(code, code_field, 0) if code else 0)


def _source_row_from_commit(item: AttendanceCommitItem) -> dict:
    include_in_unit = bool(getattr(item, "include_in_unit", True))
    return {
        "source": "COMMIT",
        "unit_id": item.commit.unit_id,
        "work_date": item.commit.work_date,
        "employee_id": item.employee_id,
        "employee_code": getattr(item.employee, "employee_code", ""),
        "employee_name": getattr(item.employee, "full_name", ""),
        "team_id": getattr(item.employee, "team_id", None),
        "code": _item_code_text(item),
        "code_label": _item_code_label(item),
        "work_credit": _commit_credit(item, "work_credit_snapshot", "work_credit") if include_in_unit else Decimal("0.00"),
        "paid_credit": _commit_credit(item, "paid_credit_snapshot", "paid_credit") if include_in_unit else Decimal("0.00"),
        "bonus_credit": _commit_credit(item, "bonus_credit_snapshot", "bonus_credit") if include_in_unit else Decimal("0.00"),
        "raw_work_credit": _commit_credit(item, "work_credit_snapshot", "work_credit"),
        "overtime_hours": _to_decimal(getattr(item, "overtime_hours", 0)),
        "meal_count": _commit_credit(item, "meal_allowance_count_snapshot", "meal_allowance_count") if include_in_unit else Decimal("0.00"),
        "bs_direction": str(getattr(item, "bs_direction", AttendanceCommitItem.BSDirection.NONE)),
        "bs_peer_unit_id": getattr(item, "bs_peer_unit_id", None),
        "include_in_unit": include_in_unit,
    }


def _source_row_from_batch(item: AttendanceBatchItem) -> dict:
    include_in_unit = bool(getattr(item, "include_in_unit", True))
    return {
        "source": "BATCH",
        "unit_id": item.batch.unit_id,
        "work_date": item.batch.work_date,
        "employee_id": item.employee_id,
        "employee_code": getattr(item.employee, "employee_code", ""),
        "employee_name": getattr(item.employee, "full_name", ""),
        "team_id": getattr(item.employee, "team_id", None),
        "code": _item_code_text(item),
        "code_label": _item_code_label(item),
        "work_credit": _batch_credit(item, "work_credit") if include_in_unit else Decimal("0.00"),
        "paid_credit": _batch_credit(item, "paid_credit") if include_in_unit else Decimal("0.00"),
        "bonus_credit": _batch_credit(item, "bonus_credit") if include_in_unit else Decimal("0.00"),
        "raw_work_credit": _batch_credit(item, "work_credit"),
        "overtime_hours": _to_decimal(getattr(item, "overtime_hours", 0)),
        "meal_count": _batch_credit(item, "meal_allowance_count") if include_in_unit else Decimal("0.00"),
        "bs_direction": str(getattr(item, "bs_direction", AttendanceBatchItem.BSDirection.NONE)),
        "bs_peer_unit_id": getattr(item, "bs_peer_unit_id", None),
        "include_in_unit": include_in_unit,
    }


def _status_badge(status_key: str) -> dict:
    mapping = {
        "DONE": {"label": "Đã chốt", "class": "bg-success text-white"},
        "DRAFT": {"label": "Đang nháp", "class": "bg-primary text-white"},
        "MISSING": {"label": "Chưa tạo", "class": "badge-soft-neutral"},
        "PARTIAL": {"label": "Chưa hoàn thành", "class": "badge-soft-warning"},
        "WARNING": {"label": "Cần kiểm tra", "class": "badge-soft-danger"},
    }
    return mapping.get(status_key, mapping["MISSING"])


def _unit_label(unit) -> str:
    if not unit:
        return "—"
    symbol = getattr(unit, "symbol", "") or ""
    name = getattr(unit, "name", "") or ""
    return f"{symbol} - {name}" if symbol else name or "—"


def _unit_symbol(unit) -> str:
    if not unit:
        return "—"
    return getattr(unit, "symbol", "") or getattr(unit, "code", "") or getattr(unit, "name", "") or "—"


def _temp_assignment_status_label(status: str) -> str:
    if TempAssignment is None:
        return "Không rõ"
    return dict(TempAssignment.Status.choices).get(status, status or "Không rõ")


def _date_vi(value) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def _assignment_start_label(start_date, fallback_date=None) -> str:
    if start_date:
        return _date_vi(start_date)
    if fallback_date:
        return _date_vi(fallback_date)
    return "—"


def _assignment_end_label(end_date) -> str:
    if end_date:
        return _date_vi(end_date)
    return "Chưa kết thúc"


def _build_effective_assignments(from_date, to_date, unit_ids):
    if TempAssignment is None:
        return []
    return list(
        TempAssignment.objects.filter(
            apply_flag=True,
            status__in=TempAssignment.effective_statuses(),
            start_date__lte=to_date,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=from_date))
        .filter(Q(from_unit_id__in=unit_ids) | Q(to_unit_id__in=unit_ids))
        .select_related("employee", "from_unit", "to_unit")
    )


def _build_bs_assignment_rows(assignments, unit_ids, active_assignment_status):
    """
    Danh sách BS trên dashboard lấy theo phiếu điều động, không lấy theo dòng công.

    Lý do: một phiếu điều động sau khi chốt công thường sinh 2 dòng công đối ứng
    (BS đi ở đơn vị gốc và BS đến ở đơn vị nhận). Nếu lấy từ dòng công, khi xem
    phạm vi gồm cả hai đơn vị sẽ bị nhân đôi. Lấy trực tiếp từ TempAssignment giúp
    mỗi lần bổ sung chỉ hiển thị 1 dòng, đúng với màn Điều động nhân sự.
    """
    rows = []
    seen = set()
    unit_id_set = set(unit_ids)
    for ta in assignments:
        ta_id = getattr(ta, "id", None)
        if ta_id in seen:
            continue
        seen.add(ta_id)
        employee = getattr(ta, "employee", None)
        rows.append({
            "assignment_id": ta_id,
            "employee_id": getattr(ta, "employee_id", None),
            "employee_code": getattr(employee, "employee_code", "") or "—",
            "employee_name": getattr(employee, "full_name", "") or str(employee or "—"),
            "from_unit_label": _unit_symbol(getattr(ta, "from_unit", None)),
            "to_unit_label": _unit_symbol(getattr(ta, "to_unit", None)),
            "assignment_status": getattr(ta, "status", ""),
            "assignment_status_label": _temp_assignment_status_label(getattr(ta, "status", "")),
            "assignment_start_date": getattr(ta, "start_date", None),
            "assignment_end_date": getattr(ta, "end_date", None),
            "assignment_start_label": _assignment_start_label(getattr(ta, "start_date", None)),
            "assignment_end_label": _assignment_end_label(getattr(ta, "end_date", None)),
            "assignment_active_rank": 0 if getattr(ta, "status", "") == active_assignment_status else 1,
            "is_from_selected_scope": getattr(ta, "from_unit_id", None) in unit_id_set,
            "is_to_selected_scope": getattr(ta, "to_unit_id", None) in unit_id_set,
        })
    return rows


def _build_impact_count(assignments, from_date, to_date) -> tuple[int, int]:
    """Đếm ảnh hưởng nháp/chốt đã được scan và còn giao với khoảng đang xem."""
    draft_count = 0
    commit_count = 0
    for ta in assignments:
        summary = getattr(ta, "last_impact_summary", None) or {}
        scan_start = _parse_date(summary.get("scan_start") or "")
        scan_end = _parse_date(summary.get("scan_end") or "")
        if scan_start and scan_end and (scan_end < from_date or scan_start > to_date):
            continue
        draft_count += int(summary.get("draft_batches") or 0)
        commit_count += int(summary.get("committed_batches") or 0)
    return draft_count, commit_count


def _status_display_from_choices(model_cls, value: str) -> str:
    choices = getattr(getattr(model_cls, "Status", None), "choices", []) or []
    return dict(choices).get(value, value or "—")


def _latest_approval_requests_for_corrections(acr_ids: list[int]) -> dict[str, object]:
    if ApprovalRequest is None or not acr_ids:
        return {}
    id_strings = [str(x) for x in acr_ids]
    latest = {}
    qs = (
        ApprovalRequest.objects.filter(object_type="attendance_correction", object_id__in=id_strings)
        .select_related("requester")
        .order_by("object_id", "-created_at")
    )
    for req in qs:
        latest.setdefault(str(req.object_id), req)
    return latest


def _approval_status_context_for_report(req, acr) -> dict:
    if req and build_approval_status_context:
        try:
            return build_approval_status_context(req, acr=acr)
        except Exception:
            pass
    if not req:
        return {
            "label": "Chưa có yêu cầu phê duyệt",
            "bo_badge_class": "bo-badge-danger",
            "note": "",
        }
    return {
        "label": _status_display_from_choices(ApprovalRequest, getattr(req, "status", "")) if ApprovalRequest else getattr(req, "status", ""),
        "bo_badge_class": "bo-badge-secondary",
        "note": "",
    }


def _build_correction_summary(unit_ids, from_date, to_date) -> dict:
    """
    Tính phiếu sửa công theo trạng thái nghiệp vụ thật.

    - Chờ phê duyệt: ACR REQUESTED / APPROVED_BY_UNIT.
    - Chờ áp dụng: ACR APPROVED_BY_HR.
    - Đã kết thúc: APPLIED / REJECTED / CANCELLED, không tính là đang mở.
    - Nếu dữ liệu cũ bị lệch: ApprovalRequest đã CANCELLED/REJECTED nhưng ACR chưa đồng bộ,
      dashboard không tính là đang mở và đưa vào cảnh báo lệch trạng thái để rà soát.
    """
    acrs = list(
        AttendanceCorrectionRequest.objects.filter(
            unit_id__in=unit_ids,
            work_date__gte=from_date,
            work_date__lte=to_date,
        )
        .select_related("unit", "requested_by")
        .order_by("-requested_at")
    )
    latest_req_by_acr = _latest_approval_requests_for_corrections([a.id for a in acrs])

    rows = []
    stale_rows = []
    counts = Counter()

    req_cancelled = getattr(getattr(ApprovalRequest, "Status", None), "CANCELLED", "CANCELLED")
    req_rejected = getattr(getattr(ApprovalRequest, "Status", None), "REJECTED", "REJECTED")

    for acr in acrs:
        acr_status = str(acr.status or "")
        req = latest_req_by_acr.get(str(acr.id))
        req_status = str(getattr(req, "status", "") or "") if req else ""

        # Dữ liệu cũ có thể bị lệch khi ApprovalRequest đã hủy/từ chối nhưng ACR chưa đồng bộ.
        if acr_status not in FINAL_CORRECTION_STATUSES and req_status in {req_cancelled, req_rejected}:
            counts["stale_sync_count"] += 1
            stale_rows.append({
                "acr": acr,
                "approval_request": req,
                "acr_status": acr_status,
                "acr_status_label": _status_display_from_choices(AttendanceCorrectionRequest, acr_status),
                "approval_status": req_status,
                "approval_status_label": _status_display_from_choices(ApprovalRequest, req_status) if ApprovalRequest else req_status,
                "approval_status_class": "bo-badge-warning",
                "approval_note": "ApprovalRequest đã kết thúc nhưng ACR chưa đồng bộ trạng thái.",
                "approval_url": reverse("backoffice:approvals_request_detail", args=[req.id]) if req else "",
            })
            continue

        if acr_status in FINAL_CORRECTION_STATUSES:
            counts[f"final_{acr_status.lower()}"] += 1
            continue

        if acr_status in PENDING_CORRECTION_STATUSES:
            group = "pending_approval"
            status_class = "badge-soft-warning"
            status_label = "Chờ phê duyệt"
        elif acr_status in WAITING_APPLY_CORRECTION_STATUSES:
            group = "waiting_apply"
            status_class = "badge-soft-info"
            status_label = "Đã duyệt, chờ áp dụng"
        else:
            group = "unknown_open"
            status_class = "badge-soft-danger"
            status_label = "Trạng thái mở chưa phân loại"

        counts[group] += 1
        counts["open_total"] += 1
        approval_ctx = _approval_status_context_for_report(req, acr)
        rows.append({
            "id": acr.id,
            "unit_symbol": getattr(acr.unit, "symbol", ""),
            "unit_name": getattr(acr.unit, "name", ""),
            "work_date": acr.work_date,
            "requested_at": acr.requested_at,
            "requested_by": getattr(acr.requested_by, "get_full_name", lambda: "")() or getattr(acr.requested_by, "username", ""),
            "change_count": len(acr.payload_json or []) if isinstance(acr.payload_json, list) else 0,
            "acr_status": acr_status,
            "acr_status_label": _status_display_from_choices(AttendanceCorrectionRequest, acr_status),
            "approval_status": req_status,
            "approval_status_label": approval_ctx.get("label"),
            "approval_status_class": approval_ctx.get("bo_badge_class", "bo-badge-secondary"),
            "approval_note": approval_ctx.get("note", ""),
            "approval_url": reverse("backoffice:approvals_request_detail", args=[req.id]) if req else "",
            "status_label": status_label,
            "status_class": status_class,
            "group": group,
        })

    return {
        "open_total": counts["open_total"],
        "pending_approval": counts["pending_approval"],
        "waiting_apply": counts["waiting_apply"],
        "unknown_open": counts["unknown_open"],
        "stale_sync_count": counts["stale_sync_count"],
        "rows": rows[:20],
        "rows_total": len(rows),
        "stale_rows": stale_rows[:20],
        "stale_rows_total": len(stale_rows),
    }


def _same_dashboard_url(from_date, to_date, unit_id=None, team_id=None, status="", anchor="") -> str:
    url = _url_with_query(
        "backoffice:attendance_report_dashboard",
        **{
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "unit": unit_id or "",
            "team": team_id or "",
            "status": status or "",
        },
    )
    return f"{url}{anchor}" if anchor else url


@login_required
def attendance_report_dashboard(request):
    if not (request.user.has_perm("attendance.view_attendancecommit") or request.user.has_perm("attendance.view_attendancebatch")):
        return render(
            request,
            "backoffice/no_permission.html",
            {"perm_codename": "attendance.view_attendancecommit", "title": "Bạn chưa được cấp quyền xem báo cáo quản lý công"},
            status=403,
        )

    today = timezone.localdate()
    from_date = _parse_date(request.GET.get("from")) or today
    to_date = _parse_date(request.GET.get("to")) or from_date
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    unit_raw = (request.GET.get("unit") or "").strip()
    team_raw = (request.GET.get("team") or "").strip()
    status_raw = (request.GET.get("status") or "").strip().upper()
    if status_raw not in ("", "COMMITTED", "DRAFT", "MISSING", "WARNING"):
        status_raw = ""

    allowed_units_qs = _units_for_attendance(request)
    allowed_unit_ids = list(allowed_units_qs.values_list("id", flat=True))
    selected_unit_id = _safe_int(unit_raw)
    if selected_unit_id and selected_unit_id in allowed_unit_ids:
        units_qs = allowed_units_qs.filter(id=selected_unit_id)
    else:
        selected_unit_id = None
        units_qs = allowed_units_qs
    units = list(units_qs)
    unit_ids = [u.id for u in units]

    selected_team_id = _safe_int(team_raw)
    teams = OrgUnit.objects.none()
    if selected_unit_id:
        teams = OrgUnit.objects.filter(parent_id=selected_unit_id, type=OrgUnit.Type.TEAM, is_active=True).order_by("symbol")
        if selected_team_id and not teams.filter(id=selected_team_id).exists():
            selected_team_id = None
    else:
        selected_team_id = None

    days = list(_date_range(from_date, to_date))
    day_count = len(days)
    unit_day_total = len(unit_ids) * day_count

    commits = list(
        AttendanceCommit.objects.filter(unit_id__in=unit_ids, work_date__gte=from_date, work_date__lte=to_date)
        .select_related("unit")
        .order_by("work_date", "unit__symbol")
    )
    commit_keys = {(c.unit_id, c.work_date) for c in commits}
    commit_ids = [c.id for c in commits]

    all_batches = list(
        AttendanceBatch.objects.filter(unit_id__in=unit_ids, work_date__gte=from_date, work_date__lte=to_date)
        .select_related("unit")
        .order_by("work_date", "unit__symbol")
    )
    draft_batches = [
        b for b in all_batches
        if (b.unit_id, b.work_date) not in commit_keys and b.status == AttendanceBatch.Status.DRAFT
    ]
    locked_without_commit_batches = [
        b for b in all_batches
        if (b.unit_id, b.work_date) not in commit_keys and b.status == AttendanceBatch.Status.LOCKED_DRAFT
    ]
    batch_keys = {(b.unit_id, b.work_date) for b in draft_batches}
    locked_without_commit_keys = {(b.unit_id, b.work_date) for b in locked_without_commit_batches}
    batch_ids = [b.id for b in draft_batches]

    commit_item_qs = AttendanceCommitItem.objects.select_related(
        "commit", "commit__unit", "employee", "employee__team", "code", "bs_peer_unit"
    ).filter(commit_id__in=commit_ids)
    batch_item_qs = AttendanceBatchItem.objects.select_related(
        "batch", "batch__unit", "employee", "employee__team", "code", "bs_peer_unit"
    ).filter(batch_id__in=batch_ids)
    if selected_team_id:
        commit_item_qs = commit_item_qs.filter(employee__team_id=selected_team_id)
        batch_item_qs = batch_item_qs.filter(employee__team_id=selected_team_id)

    source_rows = [_source_row_from_commit(it) for it in commit_item_qs]
    source_rows.extend(_source_row_from_batch(it) for it in batch_item_qs)

    # Map dòng nguồn để tính BS. Lưu ý quan trọng:
    # khi lọc đơn vị gốc A1, source_rows chỉ có dòng A1 nên cần nạp thêm dòng đối ứng ở đơn vị nhận A2;
    # khi lọc đơn vị nhận A2, cũng cần nạp thêm dòng đối ứng ở đơn vị gốc A1 để hiện "mã gốc".
    # Các dòng đối ứng này chỉ dùng để khớp BS, không cộng vào KPI/bảng tổng hợp của đơn vị đang lọc.
    peer_rows = []
    peer_employee_ids = {r["employee_id"] for r in source_rows if r.get("bs_direction") in (AttendanceCommitItem.BSDirection.IN, AttendanceCommitItem.BSDirection.OUT)}
    peer_unit_ids = {r.get("bs_peer_unit_id") for r in source_rows if r.get("bs_peer_unit_id")}
    peer_unit_ids = {uid for uid in peer_unit_ids if uid not in unit_ids}
    if peer_employee_ids and peer_unit_ids:
        peer_commits = list(
            AttendanceCommit.objects.filter(unit_id__in=peer_unit_ids, work_date__gte=from_date, work_date__lte=to_date)
            .select_related("unit")
        )
        peer_commit_keys = {(c.unit_id, c.work_date) for c in peer_commits}
        peer_commit_ids = [c.id for c in peer_commits]

        peer_commit_item_qs = AttendanceCommitItem.objects.select_related(
            "commit", "commit__unit", "employee", "employee__team", "code", "bs_peer_unit"
        ).filter(commit_id__in=peer_commit_ids, employee_id__in=peer_employee_ids)
        peer_rows.extend(_source_row_from_commit(it) for it in peer_commit_item_qs)

        # Nếu đơn vị đối ứng chưa chốt nhưng đã có nháp thì vẫn hiện được trạng thái khớp tạm từ nháp.
        # Batch đối ứng chỉ được lấy khi ngày/đơn vị đó chưa có commit, giống quy tắc thống kê chính.
        peer_batches = list(
            AttendanceBatch.objects.filter(
                unit_id__in=peer_unit_ids,
                work_date__gte=from_date,
                work_date__lte=to_date,
                status=AttendanceBatch.Status.DRAFT,
            )
            .select_related("unit")
        )
        # Lọc bằng Python theo đúng cặp unit/ngày: ngày nào đơn vị đối ứng đã chốt thì không dùng nháp ngày đó.
        peer_batches = [b for b in peer_batches if (b.unit_id, b.work_date) not in peer_commit_keys]
        peer_batch_ids = [b.id for b in peer_batches]
        if peer_batch_ids:
            peer_batch_item_qs = AttendanceBatchItem.objects.select_related(
                "batch", "batch__unit", "employee", "employee__team", "code", "bs_peer_unit"
            ).filter(batch_id__in=peer_batch_ids, employee_id__in=peer_employee_ids)
            peer_rows.extend(_source_row_from_batch(it) for it in peer_batch_item_qs)

    # Map dòng nguồn để tính công BS đi theo công thực tế bên đơn vị nhận.
    source_by_unit_date_emp = {
        (r["unit_id"], r["work_date"], r["employee_id"]): r
        for r in [*source_rows, *peer_rows]
    }

    assignments = _build_effective_assignments(from_date, to_date, unit_ids)
    assignment_by_emp_from_to = {}
    for ta in assignments:
        assignment_by_emp_from_to.setdefault((ta.employee_id, ta.from_unit_id, ta.to_unit_id), ta)

    unit_meta = {u.id: u for u in units}
    all_peer_unit_ids = {r.get("bs_peer_unit_id") for r in source_rows if r.get("bs_peer_unit_id")}
    all_peer_unit_ids.update(unit_ids)
    if all_peer_unit_ids:
        for peer_unit in OrgUnit.objects.filter(id__in=all_peer_unit_ids):
            unit_meta.setdefault(peer_unit.id, peer_unit)
    unit_totals = {
        u.id: {
            "unit": u,
            "employee_count": 0,
            "draft_item_count": 0,
            "commit_item_count": 0,
            "work_total": Decimal("0.00"),
            "paid_total": Decimal("0.00"),
            "bonus_total": Decimal("0.00"),
            "reward_total": Decimal("0.00"),
            "overtime_total": Decimal("0.00"),
            "meal_total": Decimal("0.00"),
            "bs_in_count": 0,
            "bs_out_count": 0,
            "bs_out_credit": Decimal("0.00"),
            "bs_out_unmatched": 0,
        }
        for u in units
    }

    kpi = defaultdict(lambda: Decimal("0.00"))
    kpi_int = Counter()
    code_counter = Counter()
    code_credit = defaultdict(lambda: Decimal("0.00"))
    bs_rows = []
    bs_out_employee_ids = set()
    bs_in_employee_ids = set()
    active_assignment_status = TempAssignment.Status.ACTIVE if TempAssignment else "ACTIVE"

    for r in source_rows:
        unit_total = unit_totals.get(r["unit_id"])
        if not unit_total:
            continue

        if r["source"] == "COMMIT":
            unit_total["commit_item_count"] += 1
        else:
            unit_total["draft_item_count"] += 1

        unit_total["work_total"] += r["work_credit"]
        unit_total["paid_total"] += r["paid_credit"]
        unit_total["bonus_total"] += r["bonus_credit"]
        unit_total["overtime_total"] += r["overtime_hours"]
        unit_total["meal_total"] += r["meal_count"]

        kpi["work_total"] += r["work_credit"]
        kpi["paid_total"] += r["paid_credit"]
        kpi["bonus_code_total"] += r["bonus_credit"]
        kpi["overtime_total"] += r["overtime_hours"]
        kpi["meal_total"] += r["meal_count"]
        kpi_int["total_items"] += 1
        if r["source"] == "BATCH":
            kpi_int["draft_items"] += 1

        code_key = (r["code"] or "Chưa có mã").upper()
        code_counter[code_key] += 1
        code_credit[code_key] += r["work_credit"]

        if r["bs_direction"] == AttendanceCommitItem.BSDirection.IN:
            unit_total["bs_in_count"] += 1
            kpi_int["bs_in_count"] += 1
            bs_in_employee_ids.add(r["employee_id"])
            from_unit_id = r["bs_peer_unit_id"]
            to_unit_id = r["unit_id"]
            ta = assignment_by_emp_from_to.get((r["employee_id"], from_unit_id, to_unit_id))
            bs_rows.append({
                **r,
                "kind": "BS đến",
                "from_unit_label": _unit_symbol(unit_meta.get(from_unit_id)),
                "to_unit_label": _unit_symbol(unit_meta.get(to_unit_id)),
                "source_code": (source_by_unit_date_emp.get((from_unit_id, r["work_date"], r["employee_id"])) or {}).get("code") or "—",
                "peer_code": r["code"] or "—",
                "status_label": "Đã có công tại đơn vị nhận",
                "match_label": "Đã có công tại đơn vị nhận",
                "assignment_status": getattr(ta, "status", ""),
                "assignment_status_label": _temp_assignment_status_label(getattr(ta, "status", "")) if ta else "Không rõ",
                "assignment_start_date": getattr(ta, "start_date", None),
                "assignment_end_date": getattr(ta, "end_date", None),
                "assignment_start_label": _assignment_start_label(getattr(ta, "start_date", None), r.get("work_date")),
                "assignment_end_label": _assignment_end_label(getattr(ta, "end_date", None)),
                "assignment_active_rank": 0 if ta and ta.status == active_assignment_status else 1,
            })
        elif r["bs_direction"] == AttendanceCommitItem.BSDirection.OUT:
            unit_total["bs_out_count"] += 1
            kpi_int["bs_out_count"] += 1
            bs_out_employee_ids.add(r["employee_id"])
            from_unit_id = r["unit_id"]
            to_unit_id = r["bs_peer_unit_id"]
            peer_key = (to_unit_id, r["work_date"], r["employee_id"])
            peer = source_by_unit_date_emp.get(peer_key)
            peer_is_matched = bool(peer and peer.get("bs_direction") == AttendanceCommitItem.BSDirection.IN)
            peer_credit = peer["work_credit"] if peer_is_matched else Decimal("0.00")
            if peer_is_matched:
                unit_total["bs_out_credit"] += peer_credit
                kpi["bs_out_credit"] += peer_credit
                status_label = "Đã khớp công bên đơn vị nhận"
            else:
                unit_total["bs_out_unmatched"] += 1
                kpi_int["bs_out_unmatched"] += 1
                status_label = "Chưa thấy công bên đơn vị nhận"
            ta = assignment_by_emp_from_to.get((r["employee_id"], from_unit_id, to_unit_id))
            bs_rows.append({
                **r,
                "kind": "BS đi",
                "from_unit_label": _unit_symbol(unit_meta.get(from_unit_id)),
                "to_unit_label": _unit_symbol(unit_meta.get(to_unit_id)),
                "source_code": r["code"] or "—",
                "peer_code": peer["code"] if peer and peer.get("code") else "—",
                "peer_work_credit": _display_decimal(peer_credit),
                "status_label": status_label,
                "match_label": status_label,
                "assignment_status": getattr(ta, "status", ""),
                "assignment_status_label": _temp_assignment_status_label(getattr(ta, "status", "")) if ta else "Không rõ",
                "assignment_start_date": getattr(ta, "start_date", None),
                "assignment_end_date": getattr(ta, "end_date", None),
                "assignment_start_label": _assignment_start_label(getattr(ta, "start_date", None), r.get("work_date")),
                "assignment_end_label": _assignment_end_label(getattr(ta, "end_date", None)),
                "assignment_active_rank": 0 if ta and ta.status == active_assignment_status else 1,
            })

    # T.Thưởng theo quy ước công tháng = T.Làm + T.BS đi.
    kpi["reward_total"] = kpi["work_total"] + kpi["bs_out_credit"]
    for uid, totals in unit_totals.items():
        totals["reward_total"] = totals["work_total"] + totals["bs_out_credit"]

    # Đếm nhân sự active hiện tại theo đơn vị/tổ để tham khảo nhanh.
    employee_qs = Employee.objects.filter(unit_id__in=unit_ids, status=Employee.Status.ACTIVE)
    if selected_team_id:
        employee_qs = employee_qs.filter(team_id=selected_team_id)
    employee_counts = Counter(employee_qs.values_list("unit_id", flat=True))
    for uid, cnt in employee_counts.items():
        if uid in unit_totals:
            unit_totals[uid]["employee_count"] = cnt

    commit_days_by_unit = defaultdict(set)
    draft_days_by_unit = defaultdict(set)
    for unit_id, work_date in commit_keys:
        commit_days_by_unit[unit_id].add(work_date)
    for unit_id, work_date in batch_keys:
        draft_days_by_unit[unit_id].add(work_date)

    committed_unit_days = len(commit_keys)
    draft_unit_days = len(batch_keys)
    locked_without_commit_unit_days = len(locked_without_commit_keys)
    missing_unit_days = max(0, unit_day_total - committed_unit_days - draft_unit_days - locked_without_commit_unit_days)

    progress_series = []
    for d in days:
        da_chot = sum(1 for uid in unit_ids if (uid, d) in commit_keys)
        dang_nhap = sum(1 for uid in unit_ids if (uid, d) in batch_keys)
        khoa_loi = sum(1 for uid in unit_ids if (uid, d) in locked_without_commit_keys)
        chua_tao = max(0, len(unit_ids) - da_chot - dang_nhap - khoa_loi)
        progress_series.append({
            "date": d.strftime("%d/%m"),
            "da_chot": da_chot,
            "dang_nhap": dang_nhap,
            "khoa_loi": khoa_loi,
            "chua_tao": chua_tao,
        })

    impacted_draft_count, impacted_commit_count = _build_impact_count(assignments, from_date, to_date)
    correction_summary = _build_correction_summary(unit_ids, from_date, to_date)

    warnings = []
    if draft_unit_days:
        warnings.append({
            "level": "warning",
            "title": "Có bảng công đang nháp, chưa chốt",
            "count": draft_unit_days,
            "note": "Các chỉ tiêu của nhóm này đang tạm tính từ dữ liệu nháp.",
            "url": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, status="DRAFT"),
        })
    if missing_unit_days:
        warnings.append({
            "level": "danger",
            "title": "Có đơn vị/ngày chưa tạo bảng công",
            "count": missing_unit_days,
            "note": "Cần lập danh sách chấm công trước khi tổng hợp.",
            "url": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, status="MISSING"),
        })
    if locked_without_commit_unit_days:
        warnings.append({
            "level": "danger",
            "title": "Nháp đã khóa nhưng không thấy công chốt",
            "count": locked_without_commit_unit_days,
            "note": "Dữ liệu cũ hoặc thao tác chốt bị gián đoạn; cần kiểm tra bảng công trước khi tổng hợp.",
            "url": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, status="WARNING"),
        })
    if kpi_int["bs_out_unmatched"]:
        warnings.append({
            "level": "danger",
            "title": "BS đi chưa khớp công bên đơn vị nhận",
            "count": kpi_int["bs_out_unmatched"],
            "note": "Kiểm tra đơn vị nhận đã lập/chốt công cho người bổ sung đến chưa.",
            "url": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, anchor="#bs-section"),
        })
    if impacted_draft_count:
        warnings.append({
            "level": "warning",
            "title": "Điều động ảnh hưởng bảng công nháp",
            "count": impacted_draft_count,
            "note": "Nên cập nhật lại danh sách nháp trước khi chốt.",
            "url": reverse("backoffice:temp_assignment_list"),
        })
    if impacted_commit_count:
        warnings.append({
            "level": "danger",
            "title": "Điều động ảnh hưởng công đã chốt",
            "count": impacted_commit_count,
            "note": "Không tự sửa công chốt; cần xử lý qua luồng sửa/phê duyệt nếu cần.",
            "url": reverse("backoffice:temp_assignment_list"),
        })
    if correction_summary["pending_approval"]:
        warnings.append({
            "level": "warning",
            "title": "Phiếu sửa công chờ phê duyệt",
            "count": correction_summary["pending_approval"],
            "note": "Chỉ gồm REQUESTED và APPROVED_BY_UNIT; không tính phiếu đã hủy/từ chối/đã áp dụng.",
            "url": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, anchor="#correction-section"),
        })
    if correction_summary["waiting_apply"]:
        warnings.append({
            "level": "warning",
            "title": "Phiếu sửa công đã duyệt nhưng chưa áp dụng",
            "count": correction_summary["waiting_apply"],
            "note": "Trạng thái APPROVED_BY_HR: cần kiểm tra bước áp dụng vào công chốt.",
            "url": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, anchor="#correction-section"),
        })
    if correction_summary["stale_sync_count"]:
        warnings.append({
            "level": "warning",
            "title": "Phiếu sửa công lệch trạng thái cũ",
            "count": correction_summary["stale_sync_count"],
            "note": "ApprovalRequest đã hủy/từ chối nhưng ACR chưa đồng bộ; dashboard không tính là đang mở.",
            "url": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, anchor="#correction-section"),
        })

    unit_rows = []
    for uid, totals in unit_totals.items():
        committed_days = len(commit_days_by_unit.get(uid, set()))
        draft_days = len(draft_days_by_unit.get(uid, set()))
        locked_without_commit_days = sum(1 for d in days if (uid, d) in locked_without_commit_keys)
        missing_days = max(0, day_count - committed_days - draft_days - locked_without_commit_days)
        warning_count = missing_days + locked_without_commit_days + totals["bs_out_unmatched"]
        if impacted_commit_count and selected_unit_id == uid:
            warning_count += impacted_commit_count

        if committed_days == day_count and day_count > 0:
            status_key = "DONE"
        elif committed_days or draft_days:
            status_key = "PARTIAL" if day_count > 1 else "DRAFT"
        else:
            status_key = "MISSING"
        if warning_count:
            status_key = "WARNING" if status_key == "DONE" else status_key

        row = {
            "unit_id": uid,
            "unit_symbol": totals["unit"].symbol,
            "unit_name": totals["unit"].name,
            "employee_count": totals["employee_count"],
            "committed_days": committed_days,
            "draft_days": draft_days,
            "missing_days": missing_days,
            "locked_without_commit_days": locked_without_commit_days,
            "commit_item_count": totals["commit_item_count"],
            "draft_item_count": totals["draft_item_count"],
            "work_total": _display_decimal(totals["work_total"]),
            "paid_total": _display_decimal(totals["paid_total"]),
            "bonus_total": _display_decimal(totals["bonus_total"]),
            "reward_total": _display_decimal(totals["reward_total"]),
            "overtime_total": _display_decimal(totals["overtime_total"]),
            "meal_total": _display_decimal(totals["meal_total"]),
            "bs_in_count": totals["bs_in_count"],
            "bs_out_count": totals["bs_out_count"],
            "bs_out_unmatched": totals["bs_out_unmatched"],
            "warning_count": warning_count,
            "status": _status_badge(status_key),
            "batch_url": _url_with_query(
                "backoffice:attendance_batch_create_or_load",
                date=from_date.strftime("%d/%m/%Y") if day_count == 1 else "",
                unit=uid,
            ),
            "committed_url": _url_with_query(
                "backoffice:attendance_committed_view",
                date=from_date.strftime("%d/%m/%Y") if day_count == 1 else "",
                unit=uid,
            ),
            "monthly_url": _url_with_query(
                "backoffice:attendance_monthly_view",
                month=from_date.month,
                year=from_date.year,
                unit=uid,
            ),
        }
        unit_rows.append(row)

    if status_raw:
        if status_raw == "COMMITTED":
            unit_rows = [r for r in unit_rows if r["committed_days"] == day_count]
        elif status_raw == "DRAFT":
            unit_rows = [r for r in unit_rows if r["draft_days"] > 0]
        elif status_raw == "MISSING":
            unit_rows = [r for r in unit_rows if r["missing_days"] > 0]
        elif status_raw == "WARNING":
            unit_rows = [r for r in unit_rows if r["warning_count"] > 0]

    unit_rows.sort(key=lambda r: (r["warning_count"] == 0, r["unit_symbol"]))

    # Top mã công: lấy 8 mã lớn nhất, còn lại gom Khác để biểu đồ dễ đọc.
    code_items = code_counter.most_common()
    top_code_items = code_items[:8]
    other_count = sum(cnt for _, cnt in code_items[8:])
    code_breakdown = [
        {"label": code, "count": cnt, "work_total": _display_decimal(code_credit[code])}
        for code, cnt in top_code_items
    ]
    if other_count:
        other_credit = sum((code_credit[code] for code, _ in code_items[8:]), Decimal("0.00"))
        code_breakdown.append({"label": "Khác", "count": other_count, "work_total": _display_decimal(other_credit)})

    chart_payload = {
        "code_breakdown": code_breakdown,
        "progress_series": progress_series,
    }

    # Danh sách BS hiển thị theo phiếu điều động để không bị nhân đôi BS đi/BS đến
    # khi phạm vi báo cáo gồm cả đơn vị gốc và đơn vị nhận.
    bs_rows = _build_bs_assignment_rows(assignments, unit_ids, active_assignment_status)
    bs_rows.sort(key=lambda r: (
        r.get("assignment_active_rank", 2),
        0 if r.get("assignment_status") == active_assignment_status else 1,
        -(r.get("assignment_start_date").toordinal() if r.get("assignment_start_date") else 0),
        r.get("employee_code") or "",
        r.get("assignment_id") or 0,
    ))
    bs_rows_page = bs_rows[:10]

    assignment_bs_out_employee_ids = {
        getattr(ta, "employee_id", None) for ta in assignments if getattr(ta, "from_unit_id", None) in set(unit_ids)
    }
    assignment_bs_in_employee_ids = {
        getattr(ta, "employee_id", None) for ta in assignments if getattr(ta, "to_unit_id", None) in set(unit_ids)
    }
    assignment_bs_out_employee_ids.discard(None)
    assignment_bs_in_employee_ids.discard(None)

    kpi_display = {
        "unit_count": len(unit_ids),
        "unit_day_total": unit_day_total,
        "committed_unit_days": committed_unit_days,
        "draft_unit_days": draft_unit_days,
        "missing_unit_days": missing_unit_days,
        "locked_without_commit_unit_days": locked_without_commit_unit_days,
        "total_items": kpi_int["total_items"],
        "draft_items": kpi_int["draft_items"],
        "work_total": _display_decimal(kpi["work_total"]),
        "paid_total": _display_decimal(kpi["paid_total"]),
        "bonus_code_total": _display_decimal(kpi["bonus_code_total"]),
        "reward_total": _display_decimal(kpi["reward_total"]),
        "overtime_total": _display_decimal(kpi["overtime_total"]),
        "meal_total": _display_decimal(kpi["meal_total"]),
        "bs_in_count": kpi_int["bs_in_count"],
        "bs_out_count": kpi_int["bs_out_count"],
        "bs_in_people_count": len(assignment_bs_in_employee_ids),
        "bs_out_people_count": len(assignment_bs_out_employee_ids),
        "bs_out_unmatched": kpi_int["bs_out_unmatched"],
        "open_corrections_count": correction_summary["open_total"],
        "open_corrections_pending": correction_summary["pending_approval"],
        "open_corrections_waiting_apply": correction_summary["waiting_apply"],
        "open_corrections_stale_sync": correction_summary["stale_sync_count"],
        "impacted_draft_count": impacted_draft_count,
        "impacted_commit_count": impacted_commit_count,
    }

    kpi_links = {
        "committed": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, status="COMMITTED", anchor="#unit-summary-section"),
        "draft": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, status="DRAFT", anchor="#unit-summary-section"),
        "missing": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, status="MISSING", anchor="#unit-summary-section"),
        "warnings": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, status="WARNING", anchor="#unit-summary-section"),
        "bs": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, anchor="#bs-section"),
        "corrections": _same_dashboard_url(from_date, to_date, selected_unit_id, selected_team_id, anchor="#correction-section"),
        "monthly": reverse("backoffice:attendance_monthly_view"),
    }

    return render(request, "backoffice/attendance/bao_cao.html", {
        "from_date": from_date.strftime("%Y-%m-%d"),
        "to_date": to_date.strftime("%Y-%m-%d"),
        "from_date_vi": from_date.strftime("%d/%m/%Y"),
        "to_date_vi": to_date.strftime("%d/%m/%Y"),
        "unit": str(selected_unit_id or ""),
        "team": str(selected_team_id or ""),
        "status": status_raw,
        "units": allowed_units_qs,
        "teams": teams,
        "kpi": kpi_display,
        "kpi_links": kpi_links,
        "warnings": warnings,
        "correction_rows": correction_summary["rows"],
        "correction_rows_total": correction_summary["rows_total"],
        "correction_stale_rows": correction_summary["stale_rows"],
        "correction_stale_rows_total": correction_summary["stale_rows_total"],
        "unit_rows": unit_rows,
        "bs_rows": bs_rows_page,
        "bs_rows_total": len(bs_rows),
        "chart_payload": chart_payload,
        "is_daily_mode": from_date == to_date,
        "day_count": day_count,
        "batch_url": reverse("backoffice:attendance_batch_create_or_load"),
        "monthly_url": reverse("backoffice:attendance_monthly_view"),
        "committed_url": reverse("backoffice:attendance_committed_view"),
    })
