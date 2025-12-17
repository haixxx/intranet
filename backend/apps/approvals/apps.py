from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class ApprovalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.approvals"
    label = "approvals"
    verbose_name = _("Phê duyệt")