from django import forms
from datetime import time
from .constants import ReasonCode
from .models_adjustments import AttendanceImportBatch


class ManualAdjustmentSelectForm(forms.Form):
    employee_code = forms.CharField(
        label="Mã nhân sự",
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "VD: E000001"}),
    )
    work_date = forms.DateField(
        label="Ngày làm việc",
        required=True,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )


class ManualAdjustmentForm(forms.Form):
    in1 = forms.TimeField(label="IN sáng", required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}))
    out1 = forms.TimeField(label="OUT sáng", required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}))
    in2 = forms.TimeField(label="IN chiều", required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}))
    out2 = forms.TimeField(label="OUT chiều", required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}))
    reason_code = forms.ChoiceField(label="Lý do", choices=ReasonCode.choices, required=True, widget=forms.Select(attrs={"class": "form-select"}))
    note = forms.CharField(label="Ghi chú", required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))

    def clean(self):
        cleaned = super().clean()
        # Ít nhất phải chỉnh một mốc
        if not any([cleaned.get("in1"), cleaned.get("out1"), cleaned.get("in2"), cleaned.get("out2")]):
            raise forms.ValidationError("Vui lòng nhập ít nhất một mốc thời gian để điều chỉnh.")
        # Nếu chọn 'OTHER' bắt buộc ghi chú
        if cleaned.get("reason_code") == ReasonCode.OTHER and not (cleaned.get("note") or "").strip():
            raise forms.ValidationError("Lý do 'Khác' yêu cầu ghi chú chi tiết.")
        return cleaned


class DayFactsImportForm(forms.Form):
    file = forms.FileField(label="Tệp CSV/XLSX", required=True)
    mode = forms.ChoiceField(
        label="Chế độ import",
        choices=AttendanceImportBatch.Mode.choices,
        initial=AttendanceImportBatch.Mode.FILL_MISSING_ONLY,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    reason_code = forms.ChoiceField(
        label="Lý do",
        choices=[("", "—")] + list(ReasonCode.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    note = forms.CharField(label="Ghi chú", required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))

    def clean(self):
        cleaned = super().clean()
        f = cleaned.get("file")
        if not f:
            raise forms.ValidationError("Vui lòng chọn tệp CSV/XLSX.")
        # Kiểm tra kích thước hợp lý
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Tệp quá lớn (>5MB).")
        mode = cleaned.get("mode")
        reason = cleaned.get("reason_code", "")
        if mode == AttendanceImportBatch.Mode.OVERWRITE_EXPLICIT and not reason:
            raise forms.ValidationError("Chế độ 'Ghi đè rõ ràng' yêu cầu chọn lý do.")
        if reason == ReasonCode.OTHER and not (cleaned.get("note") or "").strip():
            raise forms.ValidationError("Lý do 'Khác' yêu cầu ghi chú chi tiết.")
        return cleaned