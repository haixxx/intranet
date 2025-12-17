from django import forms
from django.utils.text import slugify
import random
import string

from apps.approvals.models import ApprovalFlow
try:
    from apps.organization.models import OrgUnit
except Exception:
    OrgUnit = None

def _gen_suffix(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

class ApprovalFlowForm(forms.ModelForm):
    """
    Form tạo/sửa Luồng phê duyệt (đơn giản hoá theo yêu cầu):
    - Bỏ admin_unit_id khỏi UI.
    - Thêm 'Đơn vị được phép tạo yêu cầu' (request_units) -> lưu trong settings_json.request_units.
    - Cấu hình chung trực quan: reject_policy, allow_overrides, SLA.
    """
    # Cấu hình chung - giao diện trực quan
    reject_policy = forms.ChoiceField(
        label="Chính sách khi bị từ chối (reject_policy)",
        choices=(
            ("REJECT_IMMEDIATE", "Từ chối ngay lập tức (dừng luồng)"),
        ),
        initial="REJECT_IMMEDIATE",
        help_text="Khi bất kỳ bước nào bị từ chối, quy trình sẽ dừng lại (REJECT_IMMEDIATE)."
    )
    allow_overrides_global = forms.BooleanField(
        label="Cho phép ghi đè cấu hình ở runtime (allow_overrides)",
        required=False,
        help_text="Khi bật, cho phép thay đổi người ký/ngưỡng ký trong quá trình chạy (theo quyền được cấp)."
    )
    sla_enabled = forms.BooleanField(
        label="Bật SLA theo dõi hạn xử lý (sla.enabled)",
        required=False,
        initial=True,
        help_text="Theo dõi thời hạn xử lý và nhắc việc khi quá hạn."
    )
    sla_default_days = forms.IntegerField(
        label="Số ngày SLA mặc định (sla.default_days)",
        required=False,
        min_value=1,
        initial=2,
        help_text="Thời gian mục tiêu hoàn tất (tính theo ngày)."
    )

    # Đơn vị được phép tạo yêu cầu
    request_units = forms.ModelMultipleChoiceField(
        label="Đơn vị được phép tạo yêu cầu",
        queryset=(OrgUnit.objects.filter(is_active=True).order_by("name") if OrgUnit else []),
        required=False,
        help_text="Chỉ những đơn vị được chọn mới nhìn thấy luồng này khi tạo yêu cầu."
    )

    class Meta:
        model = ApprovalFlow
        fields = ["flow_key", "name", "description", "status"]  # bỏ admin_unit_id khỏi UI
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "flow_key": "Mã luồng (tự sinh nếu để trống)",
            "name": "Tên luồng",
            "description": "Mô tả",
            "status": "Trạng thái",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings = getattr(self.instance, "settings_json", {}) or {}
        self.fields["reject_policy"].initial = settings.get("reject_policy", "REJECT_IMMEDIATE")
        self.fields["allow_overrides_global"].initial = bool(settings.get("allow_overrides", False))
        sla = settings.get("sla") or {}
        self.fields["sla_enabled"].initial = bool(sla.get("enabled", True))
        self.fields["sla_default_days"].initial = sla.get("default_days", 2)

        # request_units initial
        if OrgUnit and settings.get("request_units"):
            self.fields["request_units"].initial = list(settings.get("request_units"))

    def clean_flow_key(self):
        key = (self.cleaned_data.get("flow_key") or "").strip()
        name = (self.cleaned_data.get("name") or "").strip()
        if not key:
            base = slugify(name) or "flow"
            key = base
        qs = ApprovalFlow.objects.filter(flow_key=key)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            base = slugify(name) or "flow"
            key = f"{base}-{_gen_suffix()}"
            while ApprovalFlow.objects.filter(flow_key=key).exists():
                key = f"{base}-{_gen_suffix()}"
        return key

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("sla_enabled"):
            cleaned["sla_default_days"] = None
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        request_units_ids = []
        if OrgUnit:
            req_units = self.cleaned_data.get("request_units")
            if req_units is not None:
                request_units_ids = list(req_units.values_list("id", flat=True))
        settings_json = {
            "reject_policy": self.cleaned_data.get("reject_policy") or "REJECT_IMMEDIATE",
            "allow_overrides": bool(self.cleaned_data.get("allow_overrides_global")),
            "sla": {
                "enabled": bool(self.cleaned_data.get("sla_enabled")),
                "default_days": self.cleaned_data.get("sla_default_days") or 0,
            },
            "request_units": request_units_ids,
        }
        obj.settings_json = settings_json
        if commit:
            obj.save()
        return obj