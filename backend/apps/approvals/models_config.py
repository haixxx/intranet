from django.db import models

class RoleTitleMapping(models.Model):
    """
    Cấu hình mapping chức danh cho resolver DEPT_HEADS_FROM_EMPLOYEE_UNIT.
    Ví dụ:
      role_key = "HEAD", title_code = "TruongPhong"
      role_key = "DEPUTY", title_code = "PhoTruongPhong"
      role_key = "IN_CHARGE", title_code = "QuanDoc"
    """
    role_key = models.CharField(max_length=64)  # HEAD, DEPUTY, IN_CHARGE
    title_code = models.CharField(max_length=128)  # mã chức danh trong HR (CSV bạn đã import)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("role_key", "title_code")
        indexes = [
            models.Index(fields=["role_key", "is_active"]),
        ]