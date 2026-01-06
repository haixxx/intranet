from django.apps import AppConfig


class HrConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hr"
    label = "hr"
    verbose_name = "Nhân sự"

    def ready(self):
        # Import signals để đăng ký handlers
        try:
            from apps.hr import signals_temp_assignment  # noqa
        except Exception:
            pass