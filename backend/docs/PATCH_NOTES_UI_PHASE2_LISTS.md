# PATCH NOTES - UI Phase 2: Chuẩn hóa template danh mục/nền

Ngày: 2026-06-30
Nền giao diện: Tabler Core 1.4.0 + Tabler Icons 3.35.0

## 1. Mục tiêu

Giai đoạn này chuẩn hóa các trang danh sách nền trước khi đi vào nhóm màn hình chấm công phức tạp. Mục tiêu là tạo mẫu ổn định cho:

- Header trang `bo-page-header`
- Filter card `bo-filter-card`
- Bảng trong card `bo-table-card`
- Font bảng `bo-table`, `bo-table-compact`
- Badge trạng thái `bo-badge-*`
- Alert `bo-alert-*`
- Empty state `bo-empty-cell`, `bo-empty-state`
- Bỏ inline style/badge khó đọc ở các trang đã sửa

## 2. File đã sửa

```text
static/backoffice/css/app-ui.css
apps/backoffice/templates/backoffice/org/units/list.html
apps/backoffice/templates/backoffice/org/jobtitles/list.html
apps/backoffice/templates/backoffice/org/shifts/list.html
apps/backoffice/templates/backoffice/hr/employees/list.html
apps/backoffice/templates/backoffice/hr/assignments/list.html
apps/backoffice/templates/backoffice/users/list.html
apps/backoffice/templates/backoffice/roles/list.html
apps/backoffice/templates/backoffice/audit/list.html
apps/backoffice/templates/backoffice/notifications/list.html
```

## 3. Class CSS bổ sung

```text
bo-action-bar
bo-list-meta
bo-table-card
bo-scroll-box
bo-pre-wrap
bo-pagination
bo-muted-dash
bo-text-nowrap
```

## 4. Nội dung chuẩn hóa chính

### 4.1. Nhóm Tổ chức - Nhân sự

Đã chuẩn hóa:

- Cơ cấu tổ chức
- Chức danh
- Ca làm việc
- Nhân sự
- Điều động tạm thời

Các trang này hiện dùng chung cấu trúc:

```html
<div class="bo-page-header">
  <div class="bo-page-heading">
    <div class="bo-page-pretitle">...</div>
    <h2 class="bo-page-title">...</h2>
    <div class="bo-page-subtitle">...</div>
  </div>
  <div class="bo-page-actions">...</div>
</div>
```

### 4.2. Nhóm Quản trị hệ thống

Đã chuẩn hóa:

- Người dùng
- Vai trò
- Nhật ký hệ thống
- Thông báo

Các trang này trước còn dùng `h2`, `h6`, `input-group`, table không có card. Nay đã đưa về chuẩn `bo-*`.

### 4.3. Badge và màu trạng thái

Đã thay các kiểu cũ:

```html
<span class="badge bg-success">...</span>
<span class="badge bg-warning text-dark">...</span>
<span class="badge" style="background:#fff3cd;color:#664d03;">...</span>
```

bằng:

```html
<span class="bo-badge bo-badge-success">...</span>
<span class="bo-badge bo-badge-warning">...</span>
<span class="bo-badge bo-badge-danger">...</span>
<span class="bo-badge bo-badge-primary">...</span>
<span class="bo-badge bo-badge-info">...</span>
<span class="bo-badge bo-badge-secondary">...</span>
```

## 5. Kiểm tra sau khi áp dụng

Chạy tại project root:

```bash
python manage.py check
python manage.py collectstatic --noinput
```

Mở kiểm tra các trang:

```text
/backoffice/org/units/
/backoffice/org/jobtitles/
/backoffice/org/shifts/
/backoffice/hr/employees/
/backoffice/hr/assignments/
/backoffice/users/
/backoffice/roles/
/backoffice/audit/
/backoffice/notifications/
```

Checklist giao diện:

- Title cùng kiểu, không lệch cỡ chữ.
- Nút hành động nằm ở góc phải header hoặc trong filter đúng ngữ cảnh.
- Filter không bị lệch dòng ở desktop/tablet/mobile.
- Badge dễ đọc, không còn nền/chữ cùng tông khó nhìn.
- Bảng có card bao ngoài, header bảng thống nhất.
- Empty state căn giữa, không còn text trôi ở góc trái.
- Bảng nhân sự và điều động vẫn đọc được khi có nhiều cột.

## 6. Ghi chú kỹ thuật

- Patch này không thay đổi model/view/url/backend.
- Patch này chủ yếu thay HTML class và CSS dùng chung.
- Không thêm dependency mới.
- Không dùng CDN.
- Không đổi Tabler version.
- Do môi trường tạo patch không có Django runtime, chưa chạy được `manage.py check`; cần kiểm tra lại trên máy dự án sau khi áp dụng.

## 7. Bước tiếp theo đề xuất

Sau khi kiểm tra giai đoạn này ổn, tiếp tục chuẩn hóa nhóm form/confirm đơn giản:

- Form đơn vị/chức danh/ca
- Form nhân sự
- Form điều động
- Confirm delete/restore/cancel/complete

Sau đó mới chuyển sang nhóm chấm công có bảng lớn.
