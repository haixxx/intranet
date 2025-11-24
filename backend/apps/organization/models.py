from django.db import models
from django.core.exceptions import ValidationError

class OrgUnit(models.Model):
    class Type(models.TextChoices):
        PLANT = 'PLANT', 'Nhà máy'
        DEPARTMENT = 'DEPARTMENT', 'Phòng'
        DIVISION = 'DIVISION', 'Ban'
        WORKSHOP = 'WORKSHOP', 'Phân xưởng'
        TEAM = 'TEAM', 'Tổ'

    code = models.CharField(max_length=16, unique=True)
    symbol = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=150)
    type = models.CharField(max_length=16, choices=Type.choices, db_index=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children', db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['type', 'symbol']
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['parent']),
            models.Index(fields=['code']),
            models.Index(fields=['symbol']),
        ]

    def __str__(self):
        return f"{self.symbol} - {self.name}"

    def clean(self):
        # Validate tree rules
        if self.type == self.Type.PLANT:
            if self.parent is not None:
                raise ValidationError("Nhà máy (PLANT) không được có đơn vị cha.")
        elif self.type in [self.Type.DEPARTMENT, self.Type.DIVISION, self.Type.WORKSHOP]:
            if not self.parent or self.parent.type != self.Type.PLANT:
                raise ValidationError("Phòng/Ban/Phân xưởng phải có cha là Nhà máy.")
        elif self.type == self.Type.TEAM:
            if not self.parent or self.parent.type not in [self.Type.DEPARTMENT, self.Type.DIVISION, self.Type.WORKSHOP]:
                raise ValidationError("Tổ phải có cha là Phòng/Ban/Phân xưởng.")

class JobTitle(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=32, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class ShiftTemplate(models.Model):
    class Type(models.TextChoices):
        MORNING = 'MORNING', 'Ca sáng'
        AFTERNOON = 'AFTERNOON', 'Ca chiều'
        NIGHT = 'NIGHT', 'Ca tối'
        DAY = 'DAY', 'Ca ngày'
        CUSTOM = 'CUSTOM', 'Tùy chỉnh'

    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=16, choices=Type.choices, db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    breaks = models.JSONField(null=True, blank=True)  # [{"start":"11:00","end":"13:00"}]
    crosses_midnight = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['code']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"