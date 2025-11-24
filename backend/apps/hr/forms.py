from django import forms
from .models import Employee
from apps.organization.models import OrgUnit

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'full_name', 'workforce_type', 'job_title',
            'unit', 'team',
            'employee_code', 'card_id',
            'citizen_id', 'tax_code',
            'bank_account', 'bank_name',
            'email', 'phone',
            'joined_date', 'status', 'note',
        ]
        labels = {
            'full_name': 'Họ và tên',
            'workforce_type': 'Loại nhân sự',
            'job_title': 'Chức vụ',
            'unit': 'Đơn vị (Phòng/Ban/Phân xưởng)',
            'team': 'Tổ',
            'employee_code': 'Mã nhân sự',
            'card_id': 'Mã chấm công',
            'citizen_id': 'CCCD',
            'tax_code': 'MST',
            'bank_account': 'Số tài khoản',
            'bank_name': 'Ngân hàng',
            'email': 'Email',
            'phone': 'Số điện thoại',
            'joined_date': 'Ngày vào',
            'status': 'Trạng thái',
            'note': 'Ghi chú',
        }
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'workforce_type': forms.Select(attrs={'class': 'form-select'}),
            'job_title': forms.Select(attrs={'class': 'form-select'}),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'team': forms.Select(attrs={'class': 'form-select'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'card_id': forms.TextInput(attrs={'class': 'form-control'}),
            'citizen_id': forms.TextInput(attrs={'class': 'form-control'}),
            'tax_code': forms.TextInput(attrs={'class': 'form-control'}),
            'bank_account': forms.TextInput(attrs={'class': 'form-control'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'joined_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Khóa Mã nhân sự khi EDIT (instance đã tồn tại)
        if self.instance and self.instance.pk:
            f = self.fields.get('employee_code')
            if f:
                f.disabled = True
                # readonly chỉ để người dùng thấy rõ, disabled mới ngăn submit
                f.widget.attrs['readonly'] = True
                f.help_text = "Mã nhân sự cố định, không thể thay đổi."

    def clean_employee_code(self):
        """
        Bảo vệ server-side: nếu đang edit thì luôn giữ nguyên employee_code gốc,
        kể cả khi client cố post thủ công.
        """
        code = self.cleaned_data.get('employee_code')
        if self.instance and self.instance.pk:
            return self.instance.employee_code
        return code

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get('unit')
        team = cleaned.get('team')
        if team and unit:
            # Đảm bảo team thuộc subtree của unit
            parent = team.parent
            ok = False
            while parent:
                if parent.id == unit.id:
                    ok = True
                    break
                parent = parent.parent
            if not ok:
                raise forms.ValidationError("Tổ phải thuộc cùng cây con của đơn vị.")
        return cleaned