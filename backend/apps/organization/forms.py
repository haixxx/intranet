from __future__ import annotations

import json

from django import forms
from django.core.exceptions import ValidationError

from .models import JobTitle, OrgUnit, ShiftTemplate


class OrgUnitForm(forms.ModelForm):
    class Meta:
        model = OrgUnit
        fields = ["symbol", "name", "type", "parent", "is_active", "is_attendance_unit"]
        labels = {
            "symbol": "Ký hiệu/Mã đơn vị",
            "name": "Tên đơn vị",
            "type": "Loại đơn vị",
            "parent": "Đơn vị cha",
            "is_active": "Đang hoạt động",
            "is_attendance_unit": "Là đơn vị chấm công",
        }
        widgets = {
            "symbol": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-select"}),
            "parent": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_attendance_unit": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Chỉ cho chọn đơn vị cha đang hoạt động, không cho TEAM làm cha.
        # Nếu đang sửa một đơn vị đã có parent inactive thì vẫn giữ parent hiện tại trong queryset
        # để form không bị mất giá trị.
        parent_qs = OrgUnit.objects.exclude(type=OrgUnit.Type.TEAM).filter(is_active=True)

        if self.instance and self.instance.pk:
            exclude_ids = {self.instance.pk}
            exclude_ids.update(self._descendant_ids(self.instance))
            parent_qs = parent_qs.exclude(pk__in=exclude_ids)

            if self.instance.parent_id:
                parent_qs = parent_qs | OrgUnit.objects.filter(pk=self.instance.parent_id)

        self.fields["parent"].queryset = parent_qs.distinct().order_by("type", "symbol")
        self.fields["symbol"].help_text = "Ký hiệu nên ổn định vì dùng trong import/export và báo cáo."
        self.fields["is_attendance_unit"].help_text = (
            "Bật với đơn vị dùng làm phạm vi chấm công. Không bật cho tổ nếu chưa có nhu cầu riêng."
        )

    @staticmethod
    def _descendant_ids(unit: OrgUnit) -> set[int]:
        """Lấy danh sách id con cháu để tránh chọn parent tạo vòng lặp."""
        result: set[int] = set()
        queue = list(OrgUnit.objects.filter(parent=unit).values_list("id", flat=True))
        while queue:
            current_id = queue.pop(0)
            if current_id in result:
                continue
            result.add(current_id)
            queue.extend(OrgUnit.objects.filter(parent_id=current_id).values_list("id", flat=True))
        return result

    def clean_symbol(self):
        symbol = (self.cleaned_data.get("symbol") or "").strip()
        if not symbol:
            raise ValidationError("Ký hiệu/Mã đơn vị không được để trống.")
        return symbol.upper()

    def clean(self):
        cleaned = super().clean()
        unit_type = cleaned.get("type")
        parent = cleaned.get("parent")

        if unit_type == OrgUnit.Type.PLANT:
            cleaned["parent"] = None
        elif not parent:
            raise ValidationError("Đơn vị con phải có đơn vị cha.")

        if self.instance and self.instance.pk:
            old_type = self.instance.type
            new_type = unit_type

            if old_type != new_type:
                # Không cho đổi type khi đơn vị đang là đơn vị quản lý hoặc tổ của nhân sự.
                # Việc đổi type dễ làm sai chấm công, phân quyền và thống kê.
                from apps.hr.models import Employee

                has_employee = Employee.objects.filter(unit=self.instance).exists()
                has_team_employee = Employee.objects.filter(team=self.instance).exists()
                has_children = OrgUnit.objects.filter(parent=self.instance).exists()

                if has_employee or has_team_employee or has_children:
                    raise ValidationError(
                        "Không thể đổi loại đơn vị vì đơn vị này đang có nhân sự hoặc đơn vị con. "
                        "Nếu không dùng nữa, hãy bỏ chọn 'Đang hoạt động'."
                    )

            if parent and parent.pk == self.instance.pk:
                raise ValidationError("Đơn vị cha không được là chính đơn vị hiện tại.")

        return cleaned


class JobTitleForm(forms.ModelForm):
    class Meta:
        model = JobTitle
        fields = ["name", "code", "is_active"]
        labels = {
            "name": "Tên chức danh",
            "code": "Mã chức danh",
            "is_active": "Đang hoạt động",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise ValidationError("Tên chức danh không được để trống.")
        return name

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip()
        return code.upper() if code else code


class ShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = ShiftTemplate
        fields = ["code", "name", "type", "start_time", "end_time", "breaks", "crosses_midnight", "is_active"]
        labels = {
            "code": "Mã ca",
            "name": "Tên ca",
            "type": "Loại ca",
            "start_time": "Giờ bắt đầu",
            "end_time": "Giờ kết thúc",
            "breaks": "Nghỉ giữa ca (JSON)",
            "crosses_midnight": "Ca qua ngày",
            "is_active": "Đang hoạt động",
        }
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "breaks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "crosses_midnight": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "breaks": 'Ví dụ: [{"start":"11:30","end":"13:00"}]. Để trống nếu không có nghỉ giữa ca.',
        }

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip()
        if not code:
            raise ValidationError("Mã ca không được để trống.")
        return code.upper()

    def clean_breaks(self):
        value = self.cleaned_data.get("breaks")

        if value in (None, "", []):
            return []

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception as exc:
                raise ValidationError("Nghỉ giữa ca phải là JSON hợp lệ.") from exc

        if not isinstance(value, list):
            raise ValidationError("Nghỉ giữa ca phải là danh sách JSON.")

        for item in value:
            if not isinstance(item, dict):
                raise ValidationError("Mỗi khoảng nghỉ phải là object JSON.")
            if "start" not in item or "end" not in item:
                raise ValidationError("Mỗi khoảng nghỉ phải có 'start' và 'end'.")
        return value

    def clean(self):
        cleaned = super().clean()
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        crosses_midnight = cleaned.get("crosses_midnight")

        if start_time and end_time and start_time >= end_time and not crosses_midnight:
            raise ValidationError("Nếu giờ kết thúc nhỏ hơn/bằng giờ bắt đầu thì phải bật 'Ca qua ngày'.")

        return cleaned
