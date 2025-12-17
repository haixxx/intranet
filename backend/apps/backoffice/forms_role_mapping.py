from django import forms
from apps.approvals.models_config import RoleTitleMapping
from apps.organization.models import JobTitle

ROLE_CHOICES = [
    ("HEAD", "HEAD"),
    ("DEPUTY", "DEPUTY"),
    ("IN_CHARGE", "IN_CHARGE"),
]

class RoleTitleMappingForm(forms.ModelForm):
    role_key = forms.ChoiceField(choices=ROLE_CHOICES, label="Role key")
    job_title = forms.ModelChoiceField(
        queryset=JobTitle.objects.filter(is_active=True).order_by("name"),
        label="Chức danh",
        help_text="Chọn chức danh (sẽ lưu mã vào title_code)."
    )

    class Meta:
        model = RoleTitleMapping
        fields = ("role_key", "title_code", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ẩn title_code, set required=False vì sẽ bind từ job_title ở clean()
        self.fields["title_code"].widget = forms.HiddenInput()
        self.fields["title_code"].required = False

        # Nếu đang edit, chọn sẵn job_title theo title_code
        if self.instance and self.instance.pk and self.instance.title_code:
            jt = JobTitle.objects.filter(code=self.instance.title_code).first()
            if not jt:
                # fallback theo id nếu trước đây lưu id thay vì code
                try:
                    jt = JobTitle.objects.filter(id=int(self.instance.title_code)).first()
                except Exception:
                    jt = None
            if jt:
                self.fields["job_title"].initial = jt

    def clean(self):
        cleaned = super().clean()
        jt = cleaned.get("job_title")
        if not jt:
            raise forms.ValidationError("Vui lòng chọn chức danh.")
        # Lấy code từ JobTitle; nếu trống, fallback sang id để tránh lỗi 'required'
        title_code = (jt.code or "").strip()
        if not title_code:
            # Bạn có thể thay bằng raise nếu muốn bắt buộc có code
            title_code = str(jt.id)
        cleaned["title_code"] = title_code
        return cleaned