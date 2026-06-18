from html import escape
from typing import Dict, Any, Tuple


def sanitize_html(html: str) -> str:
    """
    Trả về HTML do hệ thống dựng sau khi đã escape các giá trị động.
    Không đưa trực tiếp input người dùng vào HTML nếu chưa escape.
    """
    return html or ""


FIELD_LABELS = {
    "code": "Mã công",
    "in1": "Giờ vào 1",
    "out1": "Giờ ra 1",
    "in2": "Giờ vào 2",
    "out2": "Giờ ra 2",
    "overtime_hours": "Thêm giờ",
    "notes": "Ghi chú",
    "include_in_unit": "Tính trong đơn vị",
    "bs_direction": "Hướng bổ sung",
    "bs_peer_unit_id": "Đơn vị đối ứng",
    "ADD_EMPLOYEE": "Thêm nhân sự",
    "REMOVE_EMPLOYEE": "Xóa nhân sự",
    "NOTE": "Lý do đề nghị",
}

BS_DIRECTION_LABELS = {
    "NONE": "Không bổ sung",
    "IN": "Bổ sung đến",
    "OUT": "Bổ sung đi",
    "": "Không bổ sung",
    None: "Không bổ sung",
}


def _safe(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Có" if value else "Không"
    return escape(str(value))


def _format_field_name(field: str) -> str:
    return FIELD_LABELS.get(field, field or "—")


def _format_value(field: str, value: Any) -> str:
    if field == "bs_direction":
        return _safe(BS_DIRECTION_LABELS.get(value, value))
    if field == "include_in_unit":
        return _safe(value)
    if field == "bs_peer_unit_id":
        return f"OU#{_safe(value)}" if value not in (None, "") else "—"
    if field == "overtime_hours":
        return f"{_safe(value)} giờ" if value not in (None, "") else "—"
    return _safe(value)


def _employee_display(ch: Dict[str, Any]) -> str:
    code = ch.get("employee_code") or ""
    name = ch.get("employee_name") or ""
    if code and name:
        return f"{escape(str(code))} - {escape(str(name))}"
    return _safe(name or code or ch.get("employee_id"))


def _summarize_added_employee(ch: Dict[str, Any]) -> str:
    bits = []
    code = ch.get("code")
    if code:
        bits.append(f"Mã: {_safe(code)}")
    times = []
    for a, b in (("in1", "out1"), ("in2", "out2")):
        if ch.get(a) or ch.get(b):
            times.append(f"{_safe(ch.get(a))}-{_safe(ch.get(b))}")
    if times:
        bits.append("Giờ: " + "; ".join(times))
    if "overtime_hours" in ch:
        bits.append("Thêm giờ: " + _format_value("overtime_hours", ch.get("overtime_hours")))
    if "include_in_unit" in ch:
        bits.append("Tính trong đơn vị: " + _format_value("include_in_unit", ch.get("include_in_unit")))
    if ch.get("bs_direction"):
        bits.append("Bổ sung: " + _format_value("bs_direction", ch.get("bs_direction")))
    if ch.get("bs_peer_unit_id"):
        bits.append("Đơn vị đối ứng: " + _format_value("bs_peer_unit_id", ch.get("bs_peer_unit_id")))
    if ch.get("notes"):
        bits.append("Ghi chú: " + _safe(ch.get("notes")))
    return "<br>".join(bits) if bits else "—"


def render_attendance_correction_content(payload_changes: list, metadata: Dict[str, Any]) -> Tuple[str, Dict[str, Any], int]:
    """
    Tạo content_html và content_json cho phiếu sửa chấm công.

    Hiển thị đủ:
    - NOTE/lý do đề nghị.
    - ADD_EMPLOYEE/REMOVE_EMPLOYEE.
    - Các thay đổi trường: mã, giờ, thêm giờ, BS đi/đến, đơn vị đối ứng...
    """
    changes = [ch for ch in (payload_changes or []) if isinstance(ch, dict)]
    meta = metadata or {}

    unit_code = _safe(meta.get("unit_code"))
    work_date = _safe(meta.get("work_date"))
    requester = _safe(meta.get("requester_username"))

    html = "<div class='approval-content attendance-correction-content'>"
    html += "<div class='mb-2'><strong>Nội dung phê duyệt: Đề nghị sửa chấm công</strong></div>"
    html += "<div class='small text-muted mb-2'>"
    html += f"Đơn vị: <strong>{unit_code}</strong> &nbsp; Ngày: <strong>{work_date}</strong> &nbsp; Người gửi: <strong>{requester}</strong>"
    html += "</div>"

    html += "<div class='table-responsive'>"
    html += "<table class='table table-sm table-bordered align-middle mb-0'>"
    html += "<thead class='table-light'><tr><th style='width:220px'>Nhân viên</th><th style='width:160px'>Nội dung</th><th>Cũ</th><th>Mới</th></tr></thead><tbody>"

    rendered_rows = 0
    for ch in changes:
        op_type = (ch.get("type") or "").upper()

        if op_type == "NOTE":
            note = ch.get("value") or meta.get("reason") or ""
            if note:
                html += f"<tr class='table-warning'><td>—</td><td><strong>{FIELD_LABELS['NOTE']}</strong></td><td>—</td><td>{_safe(note)}</td></tr>"
                rendered_rows += 1
            continue

        if op_type == "ADD_EMPLOYEE":
            html += "<tr class='table-success'>"
            html += f"<td>{_employee_display(ch)}</td>"
            html += f"<td><strong>{FIELD_LABELS['ADD_EMPLOYEE']}</strong></td>"
            html += "<td>—</td>"
            html += f"<td>{_summarize_added_employee(ch)}</td>"
            html += "</tr>"
            rendered_rows += 1
            continue

        if op_type == "REMOVE_EMPLOYEE":
            old_code = ch.get("old") or ch.get("code") or "Đã có trong công chốt"
            html += "<tr class='table-danger'>"
            html += f"<td>{_employee_display(ch)}</td>"
            html += f"<td><strong>{FIELD_LABELS['REMOVE_EMPLOYEE']}</strong></td>"
            html += f"<td>{_safe(old_code)}</td>"
            html += "<td>—</td>"
            html += "</tr>"
            rendered_rows += 1
            continue

        field = ch.get("field")
        if field:
            html += "<tr>"
            html += f"<td>{_employee_display(ch)}</td>"
            html += f"<td>{_safe(_format_field_name(field))}</td>"
            html += f"<td>{_format_value(field, ch.get('old'))}</td>"
            html += f"<td>{_format_value(field, ch.get('new'))}</td>"
            html += "</tr>"
            rendered_rows += 1

    if rendered_rows == 0:
        html += "<tr><td colspan='4' class='text-muted'>Không có khác biệt</td></tr>"

    html += "</tbody></table></div></div>"
    html = sanitize_html(html)
    content_json = {"changes": changes, "meta": meta}
    return html, content_json, 2


# Registry: object_type -> renderer
RENDERERS = {
    "attendance_correction": render_attendance_correction_content,
}


def render_for_object(object_type: str, payload_changes: list, metadata: Dict[str, Any]) -> Tuple[str, Dict[str, Any], int]:
    fn = RENDERERS.get(object_type)
    if not fn:
        html = sanitize_html("<div><em>Nội dung phê duyệt chưa được cấu hình renderer.</em></div>")
        return html, {"raw": payload_changes, "meta": metadata or {}}, 1
    return fn(payload_changes or [], metadata or {})
