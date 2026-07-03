# Bản sửa Dashboard filter và icon tiêu đề

Áp dụng sau bản `apps_static_ui_standardization_patch_01072026.zip`.

## Nội dung sửa

1. Sửa Dashboard chế độ theo ngày: nút `Xem` và `Xóa lọc` không còn xếp chồng dọc.
2. Thêm icon cho title Dashboard.
3. Bổ sung icon cho title các trang nhân sự/tổ chức chính:
   - Nhân sự
   - Chi tiết nhân sự
   - Điều động tạm thời
   - Cơ cấu tổ chức
   - Chức danh
   - Ca làm việc
4. Bổ sung icon cho một số trang quản trị còn thiếu để UI đồng bộ hơn:
   - Người dùng
   - Vai trò
   - Ma trận quyền
   - Nhật ký hệ thống
   - Thông báo
   - Quản trị luồng duyệt
   - Phiên bản luồng
   - Import chung
5. Sửa lỗi phụ phát hiện khi rà lại: `hr/assignments/list.html` đang bị chèn nhầm `pagination.html` vào `{% block title %}`.

## File thay đổi

Xem `dashboard_icons_fix.diff`.
