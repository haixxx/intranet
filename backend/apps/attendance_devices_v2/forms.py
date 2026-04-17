from django import forms
from django.utils.translation import gettext_lazy as _

from .models import AttendanceDeviceAgentV2, AttendanceDeviceAPIKeyV2, AttendanceDeviceV2


class AttendanceDeviceAgentV2Form(forms.ModelForm):
    class Meta:
        model = AttendanceDeviceAgentV2
        fields = ["name", "hostname", "ip_address", "version", "org_unit", "status", "notes"]
        labels = {
            "name": _("Tên agent"),
            "hostname": _("Hostname"),
            "ip_address": _("IP"),
            "version": _("Phiên bản"),
            "org_unit": _("Đơn vị/Phân xưởng"),
            "status": _("Trạng thái"),
            "notes": _("Ghi chú"),
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "hostname": forms.TextInput(attrs={"class": "form-control"}),
            "ip_address": forms.TextInput(attrs={"class": "form-control"}),
            "version": forms.TextInput(attrs={"class": "form-control"}),
            "org_unit": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class AttendanceDeviceV2Form(forms.ModelForm):
    class Meta:
        model = AttendanceDeviceV2
        fields = [
            "name",
            "brand",
            "model",
            "serial_no",
            "connect_mode",
            "host",
            "port",
            "timezone",
            "org_unit",
            "assigned_agent",
            "is_active",
            "notes",
        ]
        labels = {
            "name": _("Tên thiết bị"),
            "brand": _("Hãng"),
            "model": _("Model"),
            "serial_no": _("Serial"),
            "connect_mode": _("Chế độ kết nối"),
            "host": _("Host/IP"),
            "port": _("Port"),
            "timezone": _("Múi giờ"),
            "org_unit": _("Đơn vị/Phân xưởng"),
            "assigned_agent": _("Agent phụ trách"),
            "is_active": _("Hoạt động"),
            "notes": _("Ghi chú"),
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "brand": forms.Select(attrs={"class": "form-select"}),
            "model": forms.TextInput(attrs={"class": "form-control"}),
            "serial_no": forms.TextInput(attrs={"class": "form-control"}),
            "connect_mode": forms.Select(attrs={"class": "form-select"}),
            "host": forms.TextInput(attrs={"class": "form-control", "placeholder": "VD: 192.168.1.21"}),
            "port": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 65535}),
            "timezone": forms.TextInput(attrs={"class": "form-control"}),
            "org_unit": forms.Select(attrs={"class": "form-select"}),
            "assigned_agent": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        host = (cleaned.get("host") or "").strip()
        if not host:
            raise forms.ValidationError(_("Vui lòng nhập IP/host của thiết bị."))

        port = int(cleaned.get("port") or 0)
        if port <= 0 or port > 65535:
            raise forms.ValidationError(_("Port không hợp lệ."))

        return cleaned


class AgentAPIKeyCreateForm(forms.Form):
    """
    Form tạo key nhanh trong backoffice (v2).
    """
    expires_at = forms.DateTimeField(
        label=_("Hết hạn lúc (tuỳ chọn)"),
        required=False,
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
    )
    is_active = forms.BooleanField(
        label=_("Kích hoạt ngay"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def create_key(self, agent: AttendanceDeviceAgentV2) -> AttendanceDeviceAPIKeyV2:
        key = AttendanceDeviceAPIKeyV2.generate_key()
        return AttendanceDeviceAPIKeyV2.objects.create(
            agent=agent,
            key=key,
            is_active=bool(self.cleaned_data.get("is_active")),
            expires_at=self.cleaned_data.get("expires_at"),
        )