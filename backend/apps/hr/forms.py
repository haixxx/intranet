from __future__ import annotations

from django import forms

from .models import Employee
from apps.organization.models import JobTitle, OrgUnit


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "full_name", "workforce_type", "job_title",
            "unit", "team",
            "employee_code", "card_id",

            # Đặc cách không cần đối chiếu chấm công máy
            "skip_device_attendance",

            "citizen_id", "tax_code",
            "bank_account", "bank_name",
            "email", "phone",
            "joined_date", "status", "note",
        ]
        labels = {
            "full_name": "Họ và tên",
            "workforce_type": "Loại nhân sự",
            "job_title": "Chức danh",
            "unit": "Đơn vị (Phòng/Ban/Phân xưởng)",
            "team": "Tổ",
            "employee_code": "Mã nhân sự",
            "card_id": "Mã chấm công",

            "skip_device_attendance": "Đặc cách (không cần chấm công máy)",

            "citizen_id": "CCCD",
            "tax_code": "MST",
            "bank_account": "Số tài khoản",
            "bank_name": "Ngân hàng",
            "email": "Email",
            "phone": "Số điện thoại",
            "joined_date": "Ngày vào",
            "status": "Trạng thái",
            "note": "Ghi chú",
        }
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "workforce_type": forms.Select(attrs={"class": "form-select"}),
            "job_title": forms.Select(attrs={"class": "form-select"}),
            "unit": forms.Select(attrs={"class": "form-select"}),
            "team": forms.Select(attrs={"class": "form-select"}),
            "employee_code": forms.TextInput(attrs={"class": "form-control"}),
            "card_id": forms.TextInput(attrs={"class": "form-control"}),

            "skip_device_attendance": forms.CheckboxInput(attrs={"class": "form-check-input"}),

            "citizen_id": forms.TextInput(attrs={"class": "form-control"}),
            "tax_code": forms.TextInput(attrs={"class": "form-control"}),
            "bank_account": forms.TextInput(attrs={"class": "form-control"}),
            "bank_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "joined_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Danh mục chức danh: chỉ hiện chức danh active.
        # Khi edit nếu nhân sự đang dùng chức danh inactive thì vẫn giữ trong queryset để không mất giá trị.
        job_title_qs = JobTitle.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.job_title_id:
            job_title_qs = job_title_qs | JobTitle.objects.filter(pk=self.instance.job_title_id)
        self.fields["job_title"].queryset = job_title_qs.distinct().order_by("name")

        # Đơn vị quản lý: chỉ chọn đơn vị active thuộc nhóm quản lý chính.
        unit_qs = OrgUnit.objects.filter(
            is_active=True,
            type__in=[
                OrgUnit.Type.DEPARTMENT,
                OrgUnit.Type.DIVISION,
                OrgUnit.Type.WORKSHOP,
            ],
        )

        # Nếu view truyền user, giới hạn theo phạm vi đơn vị được cấp quyền.
        if user is not None and not user.is_superuser:
            try:
                from apps.hr.services import allowed_org_ids_for_user

                allowed_ids = set(allowed_org_ids_for_user(user))
                unit_qs = unit_qs.filter(pk__in=allowed_ids)
            except Exception:
                # Không để form chết vì lỗi phân quyền phụ.
                unit_qs = unit_qs.none()

        if self.instance and self.instance.pk and self.instance.unit_id:
            unit_qs = unit_qs | OrgUnit.objects.filter(pk=self.instance.unit_id)

        self.fields["unit"].queryset = unit_qs.distinct().order_by("type", "symbol")

        # Tổ: chỉ hiện TEAM active. Nếu edit có team inactive thì vẫn giữ được giá trị cũ.
        team_qs = OrgUnit.objects.filter(is_active=True, type=OrgUnit.Type.TEAM)
        if self.instance and self.instance.pk and self.instance.team_id:
            team_qs = team_qs | OrgUnit.objects.filter(pk=self.instance.team_id)
        self.fields["team"].queryset = team_qs.distinct().order_by("parent__symbol", "symbol")

        # Khóa Mã nhân sự khi EDIT.
        if self.instance and self.instance.pk:
            f = self.fields.get("employee_code")
            if f:
                f.disabled = True
                f.widget.attrs["readonly"] = True
                f.help_text = "Mã nhân sự cố định, không thể thay đổi."

        f_card = self.fields.get("card_id")
        if f_card:
            f_card.help_text = (
                "Mã chấm công dùng để map dữ liệu máy chấm công v2 với nhân sự. "
                "Không thay đổi nếu nhân sự đã có dữ liệu chấm công."
            )

        f_ex = self.fields.get("skip_device_attendance")
        if f_ex:
            f_ex.help_text = (
                "Nếu bật: hệ thống đối chiếu v2 sẽ đánh dấu EXEMPT, không báo thiếu mốc chấm máy."
            )

    def clean_employee_code(self):
        """
        Bảo vệ server-side: nếu đang edit thì luôn giữ nguyên employee_code gốc,
        kể cả khi client cố post thủ công.
        """
        code = self.cleaned_data.get("employee_code")
        if self.instance and self.instance.pk:
            return self.instance.employee_code
        return (code or "").strip()

    def clean_card_id(self):
        card_id = (self.cleaned_data.get("card_id") or "").strip()
        return card_id

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        team = cleaned.get("team")

        if team:
            if team.type != OrgUnit.Type.TEAM:
                raise forms.ValidationError("Trường Tổ phải chọn đơn vị loại TEAM.")

            if not team.is_active and not (self.instance and self.instance.pk and self.instance.team_id == team.id):
                raise forms.ValidationError("Tổ đã ngừng hoạt động, không thể gán mới.")

        if unit:
            if unit.type not in {
                OrgUnit.Type.DEPARTMENT,
                OrgUnit.Type.DIVISION,
                OrgUnit.Type.WORKSHOP,
            }:
                raise forms.ValidationError("Đơn vị quản lý phải là Phòng/Ban/Phân xưởng, không được là Nhà máy hoặc Tổ.")

            if not unit.is_active and not (self.instance and self.instance.pk and self.instance.unit_id == unit.id):
                raise forms.ValidationError("Đơn vị đã ngừng hoạt động, không thể gán mới.")

        if team and unit:
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
