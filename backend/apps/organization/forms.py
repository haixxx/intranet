from django import forms
from .models import OrgUnit, JobTitle, ShiftTemplate

class OrgUnitForm(forms.ModelForm):
    class Meta:
        model = OrgUnit
        fields = ['symbol', 'name', 'type', 'parent', 'is_active']

class JobTitleForm(forms.ModelForm):
    class Meta:
        model = JobTitle
        fields = ['name', 'code', 'is_active']

class ShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = ShiftTemplate
        fields = ['code', 'name', 'type', 'start_time', 'end_time', 'breaks', 'crosses_midnight', 'is_active']