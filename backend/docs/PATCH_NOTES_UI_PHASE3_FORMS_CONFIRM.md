# Patch UI Phase 3 - Form/Confirm chuẩn Tabler offline

Ngày: 30/06/2026

## Mục tiêu

Chuẩn hóa nhóm form và màn xác nhận đơn giản theo bộ chuẩn `BACKOFFICE_UI_STANDARD.md` và lớp UI nội bộ `bo-*`.

## Nguyên tắc đã áp dụng

- Giữ Tabler 1.4.0 làm nền.
- Không thêm CDN, không thêm thư viện ngoài.
- Không dùng inline style trong nhóm file đã sửa.
- Không đặt chú thích/hướng dẫn dài dưới input nếu có thể chuyển thành icon `?` tooltip.
- Bổ sung icon Tabler cho title và nút hành động chính ở mức vừa đủ.
- Dùng `bo-page-header`, `bo-page-title`, `bo-page-subtitle`, `bo-page-actions` cho header trang.
- Dùng `bo-form-card`, `bo-form-grid`, `bo-form-actions` cho form.
- Dùng `bo-confirm-card`, `bo-confirm-summary`, `bo-alert` cho trang xác nhận.

## File CSS cập nhật

```text
static/backoffice/css/app-ui.css
```

Bổ sung class:

```text
bo-form-card
bo-form-grid
bo-form-field-full
bo-form-actions
bo-section-title
bo-confirm-card
bo-confirm-title
bo-confirm-summary
bo-inline-code
```

## Template đã sửa

```text
apps/backoffice/templates/backoffice/org/units/form.html
apps/backoffice/templates/backoffice/org/jobtitles/form.html
apps/backoffice/templates/backoffice/org/shifts/form.html
apps/backoffice/templates/backoffice/hr/assignments/form.html
apps/backoffice/templates/backoffice/hr/employees/form.html
apps/backoffice/templates/backoffice/users/create.html
apps/backoffice/templates/backoffice/users/edit.html
apps/backoffice/templates/backoffice/roles/edit.html
apps/backoffice/templates/backoffice/org/units/confirm_delete.html
apps/backoffice/templates/backoffice/org/units/confirm_restore.html
apps/backoffice/templates/backoffice/org/jobtitles/confirm_delete.html
apps/backoffice/templates/backoffice/org/jobtitles/confirm_restore.html
apps/backoffice/templates/backoffice/org/shifts/confirm_delete.html
apps/backoffice/templates/backoffice/org/shifts/confirm_restore.html
apps/backoffice/templates/backoffice/hr/assignments/confirm_cancel.html
apps/backoffice/templates/backoffice/hr/assignments/confirm_complete.html
apps/backoffice/templates/backoffice/hr/employees/confirm_deactivate.html
apps/backoffice/templates/backoffice/hr/employees/confirm_leave.html
apps/backoffice/templates/backoffice/hr/employees/create_user_confirm.html
apps/backoffice/templates/backoffice/users/confirm_activate.html
apps/backoffice/templates/backoffice/users/confirm_deactivate.html
apps/backoffice/templates/backoffice/roles/confirm_delete.html
```

## Các màn hình nên test nhanh

```text
Tổ chức - đơn vị: tạo/sửa/ngừng/khôi phục
Chức danh: tạo/sửa/ngừng/khôi phục
Ca làm việc: tạo/sửa/ngừng/khôi phục
Nhân sự: tạo/sửa/tạm ngưng/nghỉ việc/tạo user
Điều động: tạo/sửa/hoàn thành/hủy
Người dùng: tạo/sửa/kích hoạt/vô hiệu hóa
Vai trò: sửa/xóa
```

## Lệnh áp dụng

Giải nén patch vào project root:

```bash
unzip z115_ui_phase3_forms_confirm_patch_20260630.zip -d <PROJECT_ROOT>
```

Sau đó chạy:

```bash
python manage.py check
python manage.py collectstatic --noinput
```

## Ghi chú kiểm tra tĩnh

Đã kiểm tra nhóm file trong patch không còn các mẫu cũ:

```text
style=
alert alert-
badge bg-
page-title-block
form-hint
```

Riêng `app-ui.css` vẫn giữ selector hỗ trợ ngược `.page-title-block` để các template chưa chuyển đổi không bị vỡ bố cục trong thời gian migration.
