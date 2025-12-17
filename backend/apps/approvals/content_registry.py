from typing import Dict, Any, Tuple

def sanitize_html(html: str) -> str:
    """
    Trả về nguyên văn chuỗi HTML đã dựng.
    Nội dung này do hệ thống sinh ra từ dữ liệu kiểm soát (không lấy input tự do).
    """
    return html or ""

def render_attendance_correction_content(payload_changes: list, metadata: Dict[str, Any]) -> Tuple[str, Dict[str, Any], int]:
    """
    Tạo content_html và content_json cho phiếu sửa chấm công.
    Hiển thị tên nhân viên (employee_name) nếu có; fallback mã nếu không có.
    """
    rows = [ch for ch in payload_changes if isinstance(ch, dict) and ch.get("field")]
    html = "<div><strong>Nội dung phê duyệt: Đề nghị sửa chấm công</strong></div>"
    html += "<table class='table table-sm table-bordered'><thead><tr><th>Nhân viên</th><th>Trường</th><th>Cũ</th><th>Mới</th></tr></thead><tbody>"
    if rows:
        for ch in rows:
            emp = ch.get("employee_name") or ch.get("employee_code") or ch.get("employee_id")
            field = ch.get("field")
            old = ch.get("old", "—")
            new = ch.get("new", "—")
            html += f"<tr><td>{emp}</td><td>{field}</td><td>{old}</td><td>{new}</td></tr>"
    else:
        html += "<tr><td colspan='4'>Không có khác biệt</td></tr>"
    html += "</tbody></table>"
    html = sanitize_html(html)
    content_json = {"changes": rows, "meta": metadata or {}}
    return html, content_json, 1

# Registry: object_type -> renderer
RENDERERS = {
    "attendance_correction": render_attendance_correction_content,
}

def render_for_object(object_type: str, payload_changes: list, metadata: Dict[str, Any]) -> Tuple[str, Dict[str, Any], int]:
    fn = RENDERERS.get(object_type)
    if not fn:
        # fallback generic
        html = sanitize_html("<div><em>Nội dung phê duyệt chưa được cấu hình renderer.</em></div>")
        return html, {"raw": payload_changes, "meta": metadata or {}}, 1
    return fn(payload_changes or [], metadata or {})