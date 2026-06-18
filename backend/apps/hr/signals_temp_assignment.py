"""
Signal điều động tạm thời.

Không scan ảnh hưởng trong post_save/post_delete nữa.
View tạo/sửa/hoàn thành/hủy điều động đã gọi scan có kiểm soát.
Nếu scan trong signal, mỗi lần save TempAssignment sẽ dễ chạy lặp và gây chậm,
đặc biệt vì scan_impacts_for_temp_assignment() có lưu last_impact_summary.
"""

try:
    from apps.hr.models.temp_assignment import TempAssignment
except Exception:
    TempAssignment = None

# Giữ file để apps.py import không lỗi.
# Không đăng ký receiver tự động tại đây.
