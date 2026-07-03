from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class ApprovalFlow(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Nháp")
        PUBLISHED = "PUBLISHED", _("Đã công bố")
        ARCHIVED = "ARCHIVED", _("Lưu trữ")

    flow_key = models.CharField(max_length=100, unique=True, help_text=_("Mã luồng (duy nhất)"))
    name = models.CharField(max_length=255, help_text=_("Tên luồng phê duyệt"))
    description = models.TextField(blank=True, default="", help_text=_("Mô tả"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    admin_unit_id = models.IntegerField(null=True, blank=True, help_text=_("Đơn vị quản lý lãnh đạo"))
    settings_json = models.JSONField(default=dict, help_text=_("Cấu hình chung cho luồng"))
    current_version = models.IntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approval_flows_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Luồng phê duyệt")
        verbose_name_plural = _("Luồng phê duyệt")

    def __str__(self):
        return f"{self.name} ({self.flow_key})"


class ApprovalFlowVersion(models.Model):
    flow = models.ForeignKey(ApprovalFlow, on_delete=models.CASCADE, related_name="versions")
    version = models.IntegerField(help_text=_("Phiên bản"))
    steps_json = models.JSONField(help_text=_("Cấu hình các bước (JSON)"))
    is_active = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approval_flow_versions_published")
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("Phiên bản luồng phê duyệt")
        verbose_name_plural = _("Phiên bản luồng phê duyệt")
        unique_together = ("flow", "version")

    def __str__(self):
        return f"{self.flow.flow_key} v{self.version}"


class ApprovalRequest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Nháp")
        SUBMITTED = "SUBMITTED", _("Đã gửi")
        IN_PROGRESS = "IN_PROGRESS", _("Đang xử lý")
        APPROVED = "APPROVED", _("Đã phê duyệt")
        REJECTED = "REJECTED", _("Đã từ chối")
        CANCELLED = "CANCELLED", _("Đã hủy")

    flow = models.ForeignKey(ApprovalFlow, on_delete=models.PROTECT, related_name="requests")
    flow_version = models.ForeignKey(ApprovalFlowVersion, on_delete=models.PROTECT, related_name="requests")
    object_type = models.CharField(max_length=100, help_text=_("Loại đối tượng nguồn"))
    object_id = models.CharField(max_length=100, help_text=_("ID đối tượng nguồn"))
    title = models.CharField(max_length=255, help_text=_("Tiêu đề hiển thị"))
    unit_id = models.IntegerField(null=True, blank=True, help_text=_("Đơn vị đích"))
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_requests_requested")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    metadata_json = models.JSONField(default=dict, help_text=_("Thông tin nguồn cho người ký (snapshot)"))
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # NEW: Snapshot nội dung phê duyệt (render HTML + JSON bất biến tại thời điểm tạo)
    content_html = models.TextField(blank=True, default="")
    content_json = models.JSONField(default=dict, blank=True)
    content_schema_version = models.IntegerField(default=1)

    class Meta:
        verbose_name = _("Yêu cầu phê duyệt")
        verbose_name_plural = _("Yêu cầu phê duyệt")
        indexes = [
            models.Index(fields=["unit_id", "status"]),
            models.Index(fields=["requester_id", "status"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.object_type}:{self.object_id})"


class ApprovalStep(models.Model):
    class Type(models.TextChoices):
        REQUESTER = "REQUESTER", _("Người lập")
        PARTICIPANTS_LIST = "PARTICIPANTS_LIST", _("Người tham gia")
        DEPT_HEADS_FROM_EMPLOYEE_UNIT = "DEPT_HEADS_FROM_EMPLOYEE_UNIT", _("Lãnh đạo đơn vị của NSTK")
        UNIT_LEADERS = "UNIT_LEADERS", _("Lãnh đạo đơn vị")
        STATIC_ROLE = "STATIC_ROLE", _("Chức danh cố định")
        EXPLICIT_USERS = "EXPLICIT_USERS", _("Chỉ định người ký")

    class Quorum(models.TextChoices):
        ALL = "ALL", _("Tất cả phải ký")
        ANY = "ANY", _("Một người ký là đủ")
        GROUP_ANY_ALL = "GROUP_ANY_ALL", _("Theo nhóm: mỗi nhóm ký 1 người, tất cả nhóm hoàn thành")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Chờ kích hoạt")
        ACTIVE = "ACTIVE", _("Đang ký")
        COMPLETED = "COMPLETED", _("Hoàn tất")
        REJECTED = "REJECTED", _("Bị từ chối")

    request = models.ForeignKey(ApprovalRequest, on_delete=models.CASCADE, related_name="steps")
    order_index = models.IntegerField()
    type = models.CharField(max_length=40, choices=Type.choices)
    label = models.CharField(max_length=255, default="", help_text=_("Tên hiển thị bước"))
    quorum = models.CharField(max_length=20, choices=Quorum.choices, default=Quorum.ALL)
    resolver_config = models.JSONField(default=dict, help_text=_("Tham số xác định người ký"))
    allow_overrides = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    activated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Bước phê duyệt")
        verbose_name_plural = _("Bước phê duyệt")
        ordering = ["order_index"]

    def __str__(self):
        return f"Step {self.order_index} - {self.label}"


class ApprovalSigner(models.Model):
    class Source(models.TextChoices):
        RESOLVED = "RESOLVED", _("Suy ra tự động")
        EXPLICIT = "EXPLICIT", _("Chỉ định sẵn")
        OVERRIDE = "OVERRIDE", _("Ghi đè theo yêu cầu")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Chờ ký")
        APPROVED = "APPROVED", _("Đã phê duyệt")
        REJECTED = "REJECTED", _("Đã từ chối")
        DELEGATED = "DELEGATED", _("Đã ủy quyền")

    step = models.ForeignKey(ApprovalStep, on_delete=models.CASCADE, related_name="signers")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_signers")
    role_title = models.CharField(max_length=100, blank=True, default="", help_text=_("Chức danh snapshot"))
    unit_id = models.IntegerField(null=True, blank=True, help_text=_("Đơn vị snapshot"))
    group_key = models.CharField(max_length=100, blank=True, default="", help_text=_("Khóa nhóm"))
    is_required = models.BooleanField(default=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.RESOLVED)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    acted_at = models.DateTimeField(null=True, blank=True)
    delegated_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approval_signers_delegated")

    class Meta:
        verbose_name = _("Người ký")
        verbose_name_plural = _("Người ký")

    def __str__(self):
        return f"{self.user} - {self.step}"


class ApprovalAction(models.Model):
    class Action(models.TextChoices):
        SUBMIT = "SUBMIT", _("Gửi phê duyệt")
        APPROVE = "APPROVE", _("Phê duyệt")
        REJECT = "REJECT", _("Từ chối")
        DELEGATE = "DELEGATE", _("Ủy quyền")
        COMMENT = "COMMENT", _("Bình luận")
        CANCEL = "CANCEL", _("Hủy yêu cầu")

    request = models.ForeignKey(ApprovalRequest, on_delete=models.CASCADE, related_name="actions")
    step = models.ForeignKey(ApprovalStep, null=True, blank=True, on_delete=models.SET_NULL, related_name="actions")
    signer = models.ForeignKey(ApprovalSigner, null=True, blank=True, on_delete=models.SET_NULL, related_name="actions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_actions")
    action = models.CharField(max_length=20, choices=Action.choices)
    comment = models.TextField(blank=True, default="")
    meta_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Lịch sử phê duyệt")
        verbose_name_plural = _("Lịch sử phê duyệt")

    def __str__(self):
        return f"{self.action} by {self.actor} on {self.request}"

# Import model cấu hình nằm ở file riêng để Django app registry/permissions nhận diện ổn định.
from .models_config import RoleTitleMapping  # noqa: F401,E402
