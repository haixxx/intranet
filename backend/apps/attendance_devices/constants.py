from django.db import models

class ReasonCode(models.TextChoices):
    POWER_OUTAGE = "POWER_OUTAGE", "Mất điện"
    NETWORK_ISSUE = "NETWORK_ISSUE", "Sự cố mạng"
    MACHINE_ERROR = "MACHINE_ERROR", "Lỗi máy chấm công"
    FORGOT_CHECK = "FORGOT_CHECK", "Quên chấm công"
    WRONG_CHECK = "WRONG_CHECK", "Chấm nhầm"
    CARD_REISSUED = "CARD_REISSUED", "Đổi/cấp lại thẻ"
    BUSINESS_TRIP = "BUSINESS_TRIP", "Công tác ngoài"
    TRAINING_OFFSITE = "TRAINING_OFFSITE", "Đào tạo ngoài"
    OTHER = "OTHER", "Khác"