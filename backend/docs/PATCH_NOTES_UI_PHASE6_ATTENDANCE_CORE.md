# PATCH NOTES - UI Phase 6: Core Attendance Screens

Ngày: 2026-07-01

## Mục tiêu

Chuẩn hóa tiếp nhóm module **Quản lý công lõi** sau khi đã hoàn thành nền Tabler offline, danh mục/form cơ bản, thiết bị/Agent v2 và 3 màn hình lớn của chấm công thiết bị.

## File đã sửa

```text
static/backoffice/css/app-ui.css

apps/backoffice/templates/backoffice/attendance/bao_cao.html
apps/backoffice/templates/backoffice/attendance/batch_create_or_load.html
apps/backoffice/templates/backoffice/attendance/code_confirm_delete.html
apps/backoffice/templates/backoffice/attendance/code_form.html
apps/backoffice/templates/backoffice/attendance/code_list.html
apps/backoffice/templates/backoffice/attendance/committed_view.html
apps/backoffice/templates/backoffice/attendance/monthly_view.html
apps/backoffice/templates/backoffice/attendance/settings_form.html
```

## Nội dung chính

- Chuẩn hóa page header theo `bo-page-header`, `bo-page-title`, `bo-page-subtitle`.
- Bổ sung icon Tabler cho title/nút chính.
- Chuẩn hóa filter của báo cáo, công chốt, công tháng và danh sách mã chế độ.
- Với filter dạng thanh ngang lớn: dùng `min-width` + `width:max-content` + scroll ngang trong filter card, tránh lỗi tự xuống nhiều dòng do sidebar/laptop nhỏ.
- Với form nhập liệu: cho phép responsive xuống dòng theo breakpoint.
- Chuyển chú thích/hướng dẫn trong form mã chế độ sang icon `?` tooltip.
- Gom style rải rác của báo cáo/công tháng/công chốt về `app-ui.css`.
- Chuẩn hóa KPI về `bo-kpi-*`, bảng về `bo-table-*`, cảnh báo về `bo-alert-*`, badge về `bo-badge-*`.
- Bỏ hiển thị kiểu thô/inline style ở các màn công tháng, công chốt và đăng ký/chốt công.

## Lưu ý responsive đã rút kinh nghiệm từ lỗi Phase 5

- Không ép filter toolbar lớn xuống 2 cột ở breakpoint sớm.
- Các filter nghiệp vụ lớn nên giữ một hàng ngang trên desktop/laptop và scroll ngang nếu thiếu chiều rộng.
- Chỉ form nhập liệu mới được chuyển nhiều dòng ở tablet/mobile.
- Khi test phải kiểm tra trong layout có sidebar, vì vùng content thực tế nhỏ hơn viewport.

## Cách áp dụng

Giải nén patch vào project root:

```bash
unzip z115_ui_phase6_attendance_core_patch_20260701.zip -d <PROJECT_ROOT>
```

Sau đó chạy:

```bash
python manage.py check
python manage.py collectstatic --noinput
```

Nếu trình duyệt vẫn hiển thị CSS cũ, nhấn `Ctrl + F5`.

## Trang nên test kỹ

```text
Báo cáo quản lý công
Đăng ký / Chốt công
Xem công chốt
Xem công theo tháng
Mã chế độ: danh sách / tạo / sửa / xóa / cấu hình
```

## Checklist tương thích thiết bị

- Desktop rộng: filter nằm một hàng, bảng không bị vỡ.
- Laptop có sidebar: filter lớn không tự xuống nhiều dòng; nếu hẹp thì scroll ngang trong card.
- Tablet: form nhập liệu xếp lại hợp lý; filter lớn vẫn có thể scroll ngang.
- Mobile: các form chuyển một cột, bảng lớn có scroll ngang.

## Chưa làm trong phase này

- Chưa chuẩn hóa sâu nhóm phê duyệt/admin flow.
- Chưa đổi logic backend, view, form Python, JS nghiệp vụ hiện có.
