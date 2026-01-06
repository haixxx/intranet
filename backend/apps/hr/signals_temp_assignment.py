from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:
    TempAssignment = None

from apps.attendance.services_bs import scan_impacts_for_temp_assignment


if TempAssignment:
    @receiver(post_save, sender=TempAssignment)
    def on_temp_assignment_saved(sender, instance, created, **kwargs):
        """
        Khi tạo/sửa phiếu điều động:
        - Kiểm tra ảnh hưởng tới các ngày đã chốt (commit).
        - Gửi thông báo (nếu có Notification) hoặc chỉ log (tùy service).
        """
        try:
            scan_impacts_for_temp_assignment(instance)
        except Exception:
            # tránh làm vỡ thao tác người dùng
            pass

    @receiver(post_delete, sender=TempAssignment)
    def on_temp_assignment_deleted(sender, instance, **kwargs):
        """
        Khi xóa phiếu điều động:
        - Kiểm tra ảnh hưởng tương tự (thường là giảm ảnh hưởng).
        """
        try:
            scan_impacts_for_temp_assignment(instance)
        except Exception:
            pass