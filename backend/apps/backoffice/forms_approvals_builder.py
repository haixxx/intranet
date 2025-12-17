from django import forms
from typing import List, Dict, Any
try:
    from apps.organization.models import OrgUnit
except Exception:
    OrgUnit = None

ALLOWED_TYPES = (
    ("EXPLICIT_USERS", "Người ký đích danh"),
    ("UNIT_LEADERS", "Lãnh đạo đơn vị"),
)

ALLOWED_QUORUM = (
    ("ALL", "Tất cả phải ký"),
    ("ANY", "Một người ký là đủ"),
)

class VersionStepForm(forms.Form):
    """
    Form cho 1 bước trong builder:
    - type: EXPLICIT_USERS | UNIT_LEADERS
    - quorum: ALL | ANY
    Ràng buộc:
    - Nếu EXPLICIT_USERS: bắt buộc có ít nhất 1 User ID hợp lệ.
    - Nếu UNIT_LEADERS: bắt buộc 'use_requester_unit' = True hoặc chọn đúng 1 đơn vị cố định (unit_id).
    """
    order = forms.IntegerField(label="Thứ tự (order)", min_value=1)
    type = forms.ChoiceField(label="Loại bước (type)", choices=ALLOWED_TYPES)
    label = forms.CharField(label="Tên hiển thị (label)", required=False)
    quorum = forms.ChoiceField(label="Ngưỡng ký (quorum)", choices=ALLOWED_QUORUM)
    allow_overrides = forms.BooleanField(label="Cho phép ghi đè", required=False)

    # EXPLICIT_USERS
    user_ids = forms.CharField(
        label="User IDs (EXPLICIT_USERS)",
        required=False,
        help_text="Nhập danh sách ID người dùng, phân tách dấu phẩy. Ví dụ: 12, 34"
    )

    # UNIT_LEADERS
    use_requester_unit = forms.BooleanField(
        label="Dùng đơn vị của người tạo yêu cầu",
        required=False
    )
    unit_id = forms.IntegerField(
        label="Đơn vị cố định (UNIT_LEADERS)",
        required=False,
        min_value=1,
        help_text="Chọn đúng 1 đơn vị lãnh đạo sẽ tham gia ký."
    )

    def clean(self):
        cleaned = super().clean()
        t = cleaned.get("type")

        if t == "EXPLICIT_USERS":
            uids_text = (cleaned.get("user_ids") or "").strip()
            if not uids_text:
                raise forms.ValidationError("EXPLICIT_USERS: Vui lòng nhập ít nhất 1 User ID.")
            try:
                parsed = [int(x.strip()) for x in uids_text.split(",") if x.strip()]
                if not parsed:
                    raise forms.ValidationError("EXPLICIT_USERS: Danh sách User ID không hợp lệ.")
                cleaned["user_ids_parsed"] = parsed
            except Exception:
                raise forms.ValidationError("EXPLICIT_USERS: User IDs phải là số nguyên, phân tách bằng dấu phẩy.")

        elif t == "UNIT_LEADERS":
            use_req = bool(cleaned.get("use_requester_unit"))
            uid = cleaned.get("unit_id")
            if not use_req and not uid:
                raise forms.ValidationError("UNIT_LEADERS: Vui lòng bật 'Dùng đơn vị của người tạo yêu cầu' hoặc chọn 1 đơn vị cố định.")

        return cleaned


class ApprovalFlowVersionBuilderForm(forms.Form):
    version = forms.IntegerField(label="Phiên bản", required=False, min_value=1)
    is_active = forms.BooleanField(label="Kích hoạt (Active)", required=False)
    notes = forms.CharField(label="Ghi chú", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    steps_count = forms.IntegerField(label="Số bước", required=False, min_value=1)

    def build_steps_json(self, raw_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        steps_json: List[Dict[str, Any]] = []
        seen_orders = set()

        if not raw_steps:
            raise forms.ValidationError("Vui lòng thêm ít nhất một bước trước khi lưu.")

        for idx, s in enumerate(raw_steps, start=1):
            f = VersionStepForm(s)
            if not f.is_valid():
                errs = []
                for field, messages in f.errors.items():
                    for msg in messages:
                        errs.append(f"{field}: {msg}")
                raise forms.ValidationError(f"Bước {idx} có lỗi: " + "; ".join(errs))

            c = f.cleaned_data
            order = c["order"]
            if order in seen_orders:
                raise forms.ValidationError(f"Thứ tự 'order' {order} bị trùng lặp.")
            seen_orders.add(order)

            step: Dict[str, Any] = {
                "order": order,
                "type": c["type"],
                "label": c.get("label") or "",
                "quorum": c.get("quorum") or "ALL",
                "allow_overrides": bool(c.get("allow_overrides")),
            }

            if c["type"] == "EXPLICIT_USERS":
                resolver = {"user_ids": c.get("user_ids_parsed") or []}
            elif c["type"] == "UNIT_LEADERS":
                unit_id = c.get("unit_id")
                resolver = {
                    "use_requester_unit": bool(c.get("use_requester_unit")),
                    "unit_ids": ([int(unit_id)] if unit_id else [])
                }
            else:
                resolver = {}

            step["resolver"] = resolver
            steps_json.append(step)

        steps_json.sort(key=lambda x: x["order"])
        return steps_json