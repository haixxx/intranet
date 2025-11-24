from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    full_name = models.CharField(max_length=150, blank=True)
    department = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.username


# Tùy chọn: cài đặt hệ thống (giữ đơn giản, tránh lỗi đánh máy)
class AppSetting(models.Model):
    key = models.CharField(max_length=64, unique=True)
    value = models.TextField(blank=True)

    def __str__(self):
        return self.key