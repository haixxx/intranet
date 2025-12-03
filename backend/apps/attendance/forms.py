from django import forms
from .models import AttendanceCode, AttendanceSettings


class AttendanceCodeForm(forms.ModelForm):
    class Meta:
        model = AttendanceCode
        fields = [
            "code", "label_vi", "is_active", "priority", "notes",
            "segments_am_type", "segments_pm_type",
            "requires_am_work", "requires_pm_work"
        ]


class AttendanceSettingsForm(forms.ModelForm):
    class Meta:
        model = AttendanceSettings
        fields = ["window_minutes", "cluster_minutes", "round_registration_to_hour"]
        help_texts = {
            "window_minutes": "Cửa sổ tìm log quanh mốc (phút). Mặc định 60.",
            "cluster_minutes": "Ngưỡng gom cụm log để lọc spam (phút). Mặc định 2.",
            "round_registration_to_hour": "NTSK nhập IN/OUT sẽ được làm tròn về phút 00 để thao tác nhanh."
        }