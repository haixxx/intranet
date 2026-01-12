from django import forms
from .models import AttendanceDevice, AttendanceDeviceUserMap
from apps.hr.models import Employee

TIMEZONE_CHOICES = [
    ("Asia/Ho_Chi_Minh", "Asia/Ho_Chi_Minh"),
    ("Asia/Bangkok", "Asia/Bangkok"),
    ("Asia/Singapore", "Asia/Singapore"),
    ("UTC", "UTC"),
]

class AttendanceDeviceForm(forms.ModelForm):
    class Meta:
        model = AttendanceDevice
        fields = [
            "name", "brand", "model", "serial_no",
            "connect_mode", "host", "port",
            "timezone", "is_active",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "brand": forms.Select(attrs={"class": "form-select"}),
            "model": forms.TextInput(attrs={"class": "form-control"}),
            "serial_no": forms.TextInput(attrs={"class": "form-control"}),
            "connect_mode": forms.Select(attrs={"class": "form-select"}),
            "host": forms.TextInput(attrs={"class": "form-control", "placeholder": "VD: 192.168.1.21"}),
            "port": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 65535}),
            "timezone": forms.Select(choices=TIMEZONE_CHOICES, attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("host"):
            raise forms.ValidationError("Vui lòng nhập IP/host của thiết bị.")
        port = cleaned.get("port") or 0
        if port <= 0 or port > 65535:
            raise forms.ValidationError("Port không hợp lệ.")
        return cleaned


class DeviceUserMapForm(forms.ModelForm):
    """
    Form thêm/sửa mapping UID -> Employee theo thiết bị.
    Nhập bằng employee_code để người dùng dễ dùng; server resolve sang Employee.
    """
    employee_code = forms.CharField(
        label="Mã nhân sự",
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "VD: NV001"})
    )

    class Meta:
        model = AttendanceDeviceUserMap
        fields = ["device_user_id", "employee", "is_active", "notes"]
        labels = {
            "device_user_id": "UID trên máy",
            "employee": "Nhân viên (ẩn, dùng employee_code)",
            "is_active": "Hoạt động",
            "notes": "Ghi chú",
        }
        widgets = {
            "device_user_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "VD: 10023"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.device = kwargs.pop("device", None)
        super().__init__(*args, **kwargs)
        # Ẩn field employee, chỉ dùng nội bộ
        self.fields["employee"].widget = forms.HiddenInput()
        if self.instance and self.instance.pk and self.instance.employee_id:
            emp = Employee.objects.filter(pk=self.instance.employee_id).first()
            if emp:
                self.fields["employee_code"].initial = emp.employee_code

    def clean_employee_code(self):
        code = (self.cleaned_data.get("employee_code") or "").strip()
        emp = Employee.objects.filter(employee_code=code).first()
        if not emp:
            raise forms.ValidationError("Không tìm thấy nhân viên theo Mã nhân sự.")
        self.cleaned_data["employee"] = emp
        return code

    def clean(self):
        cleaned = super().clean()
        uid = (cleaned.get("device_user_id") or "").strip()
        if not uid:
            raise forms.ValidationError("Vui lòng nhập UID trên máy.")
        if not self.device:
            raise forms.ValidationError("Thiếu thông tin thiết bị.")
        # Không cho trùng UID ở bản ghi active trong cùng device
        exists = AttendanceDeviceUserMap.objects.filter(
            device=self.device, device_user_id=uid, is_active=True
        )
        if self.instance and self.instance.pk:
            exists = exists.exclude(pk=self.instance.pk)
        if exists.exists() and bool(cleaned.get("is_active")):
            raise forms.ValidationError("UID này đã được map (đang active) trong thiết bị.")
        return cleaned


class DeviceUserMapBulkImportForm(forms.Form):
    """
    Upload CSV: device_user_id,employee_code
    """
    csv_file = forms.FileField(label="Tệp CSV", required=True)
    deactivate_existing = forms.BooleanField(
        label="Tự động vô hiệu hóa mapping active cũ nếu trùng UID",
        required=False
    )

    def clean_csv_file(self):
        f = self.cleaned_data.get("csv_file")
        if not f:
            raise forms.ValidationError("Vui lòng chọn tệp CSV.")
        # Kích thước hợp lý (< 2MB)
        if f.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Tệp quá lớn (>2MB).")
        return f