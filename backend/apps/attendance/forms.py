from django import forms
from .models import AttendanceCode, AttendanceSettings


class AttendanceCodeForm(forms.ModelForm):
    class Meta:
        model = AttendanceCode
        fields = [
            "code", "label_vi", "is_active", "priority", "notes",
            "segments_am_type", "segments_pm_type",
            "is_work",
            "requires_am_work", "requires_pm_work",
            "default_in1", "default_out1", "default_in2", "default_out2",
        ]
        widgets = {
            # Nhập time giống bên chấm công: định dạng HH:MM và step=3600 (nhập theo giờ, phút sẽ tự về 00)
            "default_in1": forms.TimeInput(format="%H:%M", attrs={"step": 3600}),
            "default_out1": forms.TimeInput(format="%H:%M", attrs={"step": 3600}),
            "default_in2": forms.TimeInput(format="%H:%M", attrs={"step": 3600}),
            "default_out2": forms.TimeInput(format="%H:%M", attrs={"step": 3600}),
        }


class AttendanceSettingsForm(forms.ModelForm):
    class Meta:
        model = AttendanceSettings
        fields = ["window_minutes", "cluster_minutes", "round_registration_to_hour"]
        help_texts = {
            "window_minutes": "Cửa sổ tìm log quanh mốc (phút). Mặc định 60.",
            "cluster_minutes": "Ngưỡng gom cụm log để lọc spam (phút). Mặc định 2.",
            "round_registration_to_hour": "NTSK nhập IN/OUT sẽ được làm tròn về phút 00 để thao tác nhanh."
        }