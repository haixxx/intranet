from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

User = get_user_model()

class UserCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=True, label="Mật khẩu tạm")

    class Meta:
        model = User
        fields = ['username', 'full_name', 'email', 'department', 'is_active', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data['password']
        user.set_password(pwd)
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    reset_password = forms.CharField(
        widget=forms.PasswordInput, required=False, label="Đặt lại mật khẩu",
        help_text="Nhập mật khẩu mới nếu muốn đặt lại."
    )

    class Meta:
        model = User
        fields = ['full_name', 'email', 'department', 'is_active']

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data.get('reset_password')
        if pwd:
            user.set_password(pwd)
        if commit:
            user.save()
        return user


class AssignRolesForm(forms.Form):
    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Vai trò (Groups)"
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user_instance')
        super().__init__(*args, **kwargs)
        self.user_instance = user
        self.fields['roles'].initial = user.groups.all()

    def save(self, user):
        selected = self.cleaned_data['roles']
        user.groups.set(selected)
        user.save()


class RoleUpdateForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related('content_type').all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Permissions"
    )

    class Meta:
        model = Group
        fields = ['name', 'permissions']