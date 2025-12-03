from django import forms
from django.utils import timezone
from apps.hr.models import Employee
from .models import AttendanceCode
from .models_registration import AttendanceRegistration


class AttendanceRegistrationForm(forms.ModelForm):
    class Meta:
        model = AttendanceRegistration
        fields = [
            "employee", "work_date", "code", "shift_code",
            "in1", "out1", "in2", "out2",
            "notes", "status"
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Order code by priority desc
        self.fields["code"].queryset = AttendanceCode.objects.filter(is_active=True).order_by("-priority", "code")
        # Status choices limited: DRAFT or SUBMITTED
        self.fields["status"].widget = forms.Select(choices=AttendanceRegistration.Status.choices)
        # Time inputs with step=3600 (làm tròn giờ khi nhập)
        for f in ("in1", "out1", "in2", "out2"):
            self.fields[f].widget = forms.TimeInput(format="%H:%M", attrs={"step": 3600})