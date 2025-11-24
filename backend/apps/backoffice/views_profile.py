from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from django.contrib.auth import get_user_model, update_session_auth_hash
from apps.audit.utils import audit_log

User = get_user_model()

class ProfileForm(forms.ModelForm):
    change_password = forms.BooleanField(
        required=False,
        label="Đổi mật khẩu",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_change_password'})
    )
    new_password = forms.CharField(
        required=False,
        label="Mật khẩu mới",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'minlength': '6', 'id': 'id_new_password'})
    )
    confirm_password = forms.CharField(
        required=False,
        label="Xác nhận mật khẩu mới",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'minlength': '6', 'id': 'id_confirm_password'})
    )

    class Meta:
        model = User
        fields = ['full_name', 'email', 'change_password', 'new_password', 'confirm_password']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned = super().clean()
        change_pw = cleaned.get('change_password')
        new_pw = cleaned.get('new_password') or ""
        confirm_pw = cleaned.get('confirm_password') or ""
        if change_pw:
            if len(new_pw) < 6:
                self.add_error('new_password', "Mật khẩu mới phải có tối thiểu 6 ký tự.")
            if new_pw != confirm_pw:
                self.add_error('confirm_password', "Xác nhận mật khẩu không khớp.")
        return cleaned

@login_required
def profile_view(request):
    user = request.user
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=user)
        if form.is_valid():
            change_pw = form.cleaned_data.get('change_password')
            new_pw = form.cleaned_data.get('new_password')

            # Lưu thay đổi thông tin cơ bản
            old_full = user.full_name
            old_email = user.email
            updated = form.save(commit=False)  # không lưu các field ảo password
            updated.save()

            diff = {}
            if old_full != updated.full_name:
                diff['full_name'] = {'old': old_full, 'new': updated.full_name}
            if old_email != updated.email:
                diff['email'] = {'old': old_email, 'new': updated.email}
            if diff:
                audit_log(
                    action_verb="UPDATE",
                    object_type="user",
                    object_id=updated.pk,
                    object_repr=updated.username,
                    actor=updated,
                    changes=diff,
                    request=request,
                    action_code="USER_SELF_UPDATE",
                )

            # Đổi mật khẩu nếu được chọn
            if change_pw and new_pw:
                user.set_password(new_pw)
                user.save(update_fields=['password'])
                update_session_auth_hash(request, user)  # giữ phiên đăng nhập
                audit_log(
                    action_verb="UPDATE",
                    object_type="user",
                    object_id=user.pk,
                    object_repr=user.username,
                    actor=user,
                    changes={"password": "changed"},
                    request=request,
                    action_code="USER_PASSWORD_CHANGE",
                )

            messages.success(request, "Đã lưu thay đổi.")
            return redirect('backoffice:profile')
    else:
        form = ProfileForm(instance=user)

    return render(request, 'backoffice/profile/profile.html', {
        'form': form,
        'user_obj': user,
    })