from django import forms
from django.core.exceptions import ValidationError

from .models import AttendanceCode, AttendanceSettings


class AttendanceCodeForm(forms.ModelForm):
    class Meta:
        model = AttendanceCode
        fields = [
            "code", "label_vi", "is_active", "priority",
            "segments_am_type", "segments_pm_type", "is_work",
            "requires_am_work", "requires_pm_work",
            "default_in1", "default_out1", "default_in2", "default_out2",
            "work_credit", "paid_credit", "bonus_credit", "registered_hours", "meal_allowance_count",
            "is_system", "system_role",
            "notes",
        ]
        widgets = {
            "default_in1": forms.TimeInput(format="%H:%M", attrs={"type": "time", "step": 3600}),
            "default_out1": forms.TimeInput(format="%H:%M", attrs={"type": "time", "step": 3600}),
            "default_in2": forms.TimeInput(format="%H:%M", attrs={"type": "time", "step": 3600}),
            "default_out2": forms.TimeInput(format="%H:%M", attrs={"type": "time", "step": 3600}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_used = bool(self.instance and self.instance.pk and self.instance.is_used())
        self._old_code = self.instance.code if self.instance and self.instance.pk else None
        self._old_is_system = bool(self.instance.is_system) if self.instance and self.instance.pk else False
        self._old_system_role = self.instance.system_role if self.instance and self.instance.pk else None

        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs["class"] = (css + " form-check-input").strip()
            elif isinstance(widget, (forms.Select,)):
                widget.attrs["class"] = (css + " form-select form-select-sm").strip()
            elif isinstance(widget, (forms.Textarea,)):
                widget.attrs["class"] = (css + " form-control form-control-sm").strip()
            else:
                widget.attrs["class"] = (css + " form-control form-control-sm").strip()

        for name in ["work_credit", "paid_credit", "bonus_credit", "registered_hours", "meal_allowance_count"]:
            self.fields[name].widget.attrs.update({"step": "0.25", "min": "0"})

        if self._is_used:
            # Không cho đổi mã khi đã dùng trong nháp/chốt; dữ liệu lịch sử đang tham chiếu FK này.
            self.fields["code"].disabled = True
            self.fields["code"].help_text = "Mã đã phát sinh dữ liệu nên không được đổi. Nếu đổi bản chất, hãy tạo mã mới."

        if self._is_used and self._old_is_system:
            # Giữ vai trò hệ thống ổn định để báo cáo lịch sử không đổi nghĩa.
            self.fields["is_system"].disabled = True
            self.fields["system_role"].disabled = True
            self.fields["system_role"].help_text = "Mã hệ thống đã dùng nên không đổi vai trò."

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        if self._is_used and self._old_code and code != self._old_code:
            raise ValidationError("Không được đổi mã khi mã đã phát sinh dữ liệu nháp/chốt.")
        return code

    def clean(self):
        cleaned = super().clean()
        if self._is_used and self._old_is_system:
            if cleaned.get("is_system") != self._old_is_system:
                raise ValidationError("Không được bỏ cờ mã hệ thống khi mã đã phát sinh dữ liệu.")
            if cleaned.get("system_role") != self._old_system_role:
                raise ValidationError("Không được đổi vai trò hệ thống khi mã đã phát sinh dữ liệu.")
        return cleaned


class AttendanceSettingsForm(forms.ModelForm):
    class Meta:
        model = AttendanceSettings
        fields = ["window_minutes", "cluster_minutes", "round_registration_to_hour"]
        help_texts = {
            "window_minutes": "Cửa sổ tìm log quanh mốc (phút). Mặc định 60.",
            "cluster_minutes": "Ngưỡng gom cụm log để lọc spam (phút). Mặc định 2.",
            "round_registration_to_hour": "NTSK nhập IN/OUT sẽ được làm tròn về phút 00 để thao tác nhanh."
        }
