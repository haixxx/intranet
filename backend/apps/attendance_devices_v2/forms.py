from __future__ import annotations

from copy import deepcopy

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import AttendanceDeviceAgentV2, AttendanceDeviceAPIKeyV2, AttendanceDeviceV2

from .sync_policy import (
    BACKFILL_RUN_MODE_ALWAYS,
    BACKFILL_RUN_MODE_IF_NEEDED,
    get_default_sync_policy,
    get_device_sync_policy,
    normalize_sync_policy,
)


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
    # SDK cơ bản
    machine_number = forms.IntegerField(
        label=_("Machine number"),
        required=True,
        initial=1,
        min_value=1,
        max_value=255,
        help_text=_("Số máy trong SDK ZKTeco/Ronald Jack. Thường để 1."),
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 255}),
    )
    comm_password = forms.IntegerField(
        label=_("Comm password"),
        required=False,
        initial=0,
        min_value=0,
        max_value=999999999,
        help_text=_("Mật khẩu giao tiếp SDK. Nếu máy không đặt mật khẩu thì để 0."),
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}),
    )

    # Sync policy cho Agent V2
    realtime_enabled = forms.BooleanField(
        label=_("Bật realtime"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    backfill_enabled = forms.BooleanField(
        label=_("Bật backfill"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    BACKFILL_RUN_MODE_CHOICES = (
        (BACKFILL_RUN_MODE_IF_NEEDED, _("Chỉ chạy khi realtime có gián đoạn")),
        (BACKFILL_RUN_MODE_ALWAYS, _("Luôn chạy theo lịch")),
    )

    morning_backfill_enabled = forms.BooleanField(
        label=_("Bật backfill 07:30"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    morning_backfill_time = forms.TimeField(
        label=_("Giờ sáng"),
        required=True,
        initial="07:30",
        input_formats=["%H:%M"],
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    morning_backfill_days = forms.IntegerField(
        label=_("Số ngày"),
        required=True,
        initial=1,
        min_value=1,
        max_value=60,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 60}),
    )
    morning_backfill_run_mode = forms.ChoiceField(
        label=_("Cách chạy"),
        choices=BACKFILL_RUN_MODE_CHOICES,
        initial=BACKFILL_RUN_MODE_IF_NEEDED,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    midday_backfill_enabled = forms.BooleanField(
        label=_("Bật backfill 13:20"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    midday_backfill_time = forms.TimeField(
        label=_("Giờ trưa"),
        required=True,
        initial="13:20",
        input_formats=["%H:%M"],
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    midday_backfill_days = forms.IntegerField(
        label=_("Số ngày"),
        required=True,
        initial=1,
        min_value=1,
        max_value=60,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 60}),
    )
    midday_backfill_run_mode = forms.ChoiceField(
        label=_("Cách chạy"),
        choices=BACKFILL_RUN_MODE_CHOICES,
        initial=BACKFILL_RUN_MODE_IF_NEEDED,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    nightly_backfill_enabled = forms.BooleanField(
        label=_("Bật backfill 22:00"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    nightly_backfill_time = forms.TimeField(
        label=_("Giờ ban đêm"),
        required=True,
        initial="22:00",
        input_formats=["%H:%M"],
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    nightly_backfill_days = forms.IntegerField(
        label=_("Số ngày"),
        required=True,
        initial=15,
        min_value=1,
        max_value=60,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 60}),
    )
    nightly_backfill_run_mode = forms.ChoiceField(
        label=_("Cách chạy"),
        choices=BACKFILL_RUN_MODE_CHOICES,
        initial=BACKFILL_RUN_MODE_ALWAYS,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    backfill_retry_delay_minutes = forms.IntegerField(
        label=_("Phút chờ retry backfill"),
        required=True,
        initial=15,
        min_value=1,
        max_value=240,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 240}),
    )
    backfill_max_retries_per_window = forms.IntegerField(
        label=_("Số lần retry/window"),
        required=True,
        initial=3,
        min_value=0,
        max_value=20,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 20}),
    )
    health_check_seconds = forms.IntegerField(
        label=_("Health-check giây"),
        required=True,
        initial=10,
        min_value=5,
        max_value=300,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 5, "max": 300}),
    )
    reconnect_seconds = forms.IntegerField(
        label=_("Reconnect giây"),
        required=True,
        initial=30,
        min_value=5,
        max_value=600,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 5, "max": 600}),
    )

    time_sync_enabled = forms.BooleanField(
        label=_("Bật tự đồng bộ giờ máy"),
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    time_sync_warn_seconds = forms.IntegerField(
        label=_("Cảnh báo lệch giờ (giây)"),
        required=True,
        initial=120,
        min_value=10,
        max_value=86400,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 10}),
    )
    time_sync_auto_seconds = forms.IntegerField(
        label=_("Ngưỡng auto sync (giây)"),
        required=True,
        initial=300,
        min_value=30,
        max_value=86400,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 30}),
    )
    time_sync_from = forms.TimeField(
        label=_("Cho phép sync từ"),
        required=True,
        initial="22:00",
        input_formats=["%H:%M"],
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    time_sync_to = forms.TimeField(
        label=_("Cho phép sync đến"),
        required=True,
        initial="23:30",
        input_formats=["%H:%M"],
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )

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
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("VD: Máy chấm công khu A")}),
            "brand": forms.Select(attrs={"class": "form-select"}),
            "model": forms.TextInput(attrs={"class": "form-control", "placeholder": "VD: M50VL"}),
            "serial_no": forms.TextInput(attrs={"class": "form-control"}),
            "connect_mode": forms.Select(attrs={"class": "form-select"}),
            "host": forms.TextInput(attrs={"class": "form-control", "placeholder": "VD: 192.168.1.21"}),
            "port": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 65535}),
            "timezone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Asia/Ho_Chi_Minh"}),
            "org_unit": forms.Select(attrs={"class": "form-select"}),
            "assigned_agent": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Default an toàn khi thêm mới để hạn chế nhập liệu thiếu/sai.
        self.fields["brand"].initial = AttendanceDeviceV2.Brand.ZKTECO
        self.fields["connect_mode"].initial = AttendanceDeviceV2.ConnectMode.PULL
        self.fields["port"].initial = 4370
        self.fields["timezone"].initial = "Asia/Ho_Chi_Minh"
        self.fields["is_active"].initial = True

        instance = getattr(self, "instance", None)
        sdk_profile = instance.sdk_profile if instance and isinstance(instance.sdk_profile, dict) else {}
        policy = get_device_sync_policy(instance if instance and instance.pk else None)
        self.default_sync_policy = get_default_sync_policy()

        self.fields["machine_number"].initial = int(sdk_profile.get("machine_number") or 1)
        self.fields["comm_password"].initial = int(sdk_profile.get("comm_password") or 0)
        self.fields["realtime_enabled"].initial = bool(policy.get("realtime_enabled", True))
        self.fields["backfill_enabled"].initial = bool(policy.get("backfill_enabled", True))

        windows = {
            item.get("name"): item
            for item in policy.get("backfill_windows", [])
            if isinstance(item, dict)
        }
        for prefix, name in (
            ("morning", "morning-check"),
            ("midday", "midday-check"),
            ("nightly", "nightly"),
        ):
            window = windows[name]
            self.fields[f"{prefix}_backfill_enabled"].initial = bool(window.get("enabled", True))
            self.fields[f"{prefix}_backfill_time"].initial = window.get("time")
            self.fields[f"{prefix}_backfill_days"].initial = int(window.get("days") or 1)
            self.fields[f"{prefix}_backfill_run_mode"].initial = window.get("run_mode")

        self.fields["backfill_retry_delay_minutes"].initial = int(policy.get("backfill_retry_delay_minutes") or 15)
        self.fields["backfill_max_retries_per_window"].initial = int(policy.get("backfill_max_retries_per_window") or 3)
        self.fields["health_check_seconds"].initial = int(policy.get("health_check_seconds") or 10)
        self.fields["reconnect_seconds"].initial = int(policy.get("reconnect_seconds") or 30)

        self.fields["time_sync_enabled"].initial = bool(policy.get("time_sync_enabled", False))
        self.fields["time_sync_warn_seconds"].initial = int(policy.get("time_sync_warn_seconds") or 120)
        self.fields["time_sync_auto_seconds"].initial = int(policy.get("time_sync_auto_seconds") or 300)
        allowed_window = policy.get("time_sync_allowed_windows", [])[0]
        self.fields["time_sync_from"].initial = allowed_window.get("from") or "22:00"
        self.fields["time_sync_to"].initial = allowed_window.get("to") or "23:30"

    def clean(self):
        cleaned = super().clean()

        # Trim các field text quan trọng.
        for field in ("name", "host", "timezone", "model", "serial_no"):
            if field in cleaned and isinstance(cleaned.get(field), str):
                cleaned[field] = cleaned[field].strip()

        if not cleaned.get("name"):
            raise forms.ValidationError(_("Vui lòng nhập tên thiết bị."))

        host = (cleaned.get("host") or "").strip()
        if not host:
            raise forms.ValidationError(_("Vui lòng nhập IP/host của thiết bị."))

        port = int(cleaned.get("port") or 0)
        if port <= 0 or port > 65535:
            raise forms.ValidationError(_("Port không hợp lệ."))

        timezone = (cleaned.get("timezone") or "").strip()
        if not timezone:
            cleaned["timezone"] = "Asia/Ho_Chi_Minh"

        for field_name in (
            "morning_backfill_days",
            "midday_backfill_days",
            "nightly_backfill_days",
        ):
            days = int(cleaned.get(field_name) or 0)
            if days < 1 or days > 60:
                raise forms.ValidationError(_("Số ngày backfill nên nằm trong khoảng 1–60."))

        warn = int(cleaned.get("time_sync_warn_seconds") or 0)
        auto = int(cleaned.get("time_sync_auto_seconds") or 0)
        if auto < warn:
            raise forms.ValidationError(_("Ngưỡng auto sync phải lớn hơn hoặc bằng ngưỡng cảnh báo lệch giờ."))

        return cleaned

    def _build_sync_policy(self) -> dict:
        cd = self.cleaned_data

        def build_window(prefix: str, name: str, grace_minutes: int) -> dict:
            return {
                "name": name,
                "time": cd[f"{prefix}_backfill_time"].strftime("%H:%M"),
                "days": int(cd.get(f"{prefix}_backfill_days") or 1),
                "run_mode": cd.get(f"{prefix}_backfill_run_mode") or BACKFILL_RUN_MODE_IF_NEEDED,
                "grace_minutes": grace_minutes,
                "enabled": bool(cd.get(f"{prefix}_backfill_enabled")),
            }

        policy = {
            "realtime_enabled": bool(cd.get("realtime_enabled")),
            "backfill_enabled": bool(cd.get("backfill_enabled")),
            "backfill_mode": "SEQUENTIAL",
            "backfill_windows": [
                build_window("morning", "morning-check", 60),
                build_window("midday", "midday-check", 60),
                build_window("nightly", "nightly", 120),
            ],
            "backfill_retry_enabled": True,
            "backfill_retry_delay_minutes": int(cd.get("backfill_retry_delay_minutes") or 15),
            "backfill_max_retries_per_window": int(cd.get("backfill_max_retries_per_window") or 3),
            "backfill_retry_on_device_offline": True,
            "backfill_retry_on_server_error": False,
            "time_sync_enabled": bool(cd.get("time_sync_enabled")),
            "time_sync_warn_seconds": int(cd.get("time_sync_warn_seconds") or 120),
            "time_sync_auto_seconds": int(cd.get("time_sync_auto_seconds") or 300),
            "time_sync_allowed_windows": [
                {
                    "from": cd["time_sync_from"].strftime("%H:%M"),
                    "to": cd["time_sync_to"].strftime("%H:%M"),
                }
            ],
            "time_sync_check_seconds": 600,
            "time_sync_max_retries_per_window": 2,
            "time_sync_retry_delay_minutes": 15,
            "time_sync_verify_tolerance_seconds": 30,
            "health_check_seconds": int(cd.get("health_check_seconds") or 10),
            "reconnect_seconds": int(cd.get("reconnect_seconds") or 30),
            "missed_schedule_grace_minutes": 60,
        }
        return normalize_sync_policy(policy)

    def save(self, commit=True):
        obj = super().save(commit=False)

        # SDK profile giữ các key khác nếu sau này bạn bổ sung; chỉ chuẩn hóa các key phục vụ Agent V2.
        sdk_profile = obj.sdk_profile if isinstance(obj.sdk_profile, dict) else {}
        sdk_profile = deepcopy(sdk_profile)
        sdk_profile["machine_number"] = int(self.cleaned_data.get("machine_number") or 1)
        sdk_profile["comm_password"] = int(self.cleaned_data.get("comm_password") or 0)
        sdk_profile["sync_policy"] = self._build_sync_policy()
        obj.sdk_profile = sdk_profile

        if commit:
            obj.save()
            self.save_m2m()
        return obj


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
