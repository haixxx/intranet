# PATCH NOTES — UI Phase 5: Attendance v2 big screens

Ngày tạo: 2026-06-30  
Nền giao diện: Tabler Core 1.4.0 + Tabler Icons 3.35.0 + `bo-*` standard layer

## 1. Phạm vi

Phase 5 chuẩn hóa 3 màn hình lớn của module `attendance_devices_v2`:

- `thong_ke.html` — Thống kê chấm công
- `them_du_lieu.html` — Thêm dữ liệu chấm công
- `giam_sat_thiet_bi.html` — Giám sát thiết bị chấm công

Đồng thời cập nhật:

- `static/backoffice/css/app-ui.css`
- `static/backoffice/js/app-ui.js`

## 2. Nguyên tắc đã bám sát

- Không đổi business logic, URL, form action, tên input, biến context, permission hoặc vòng lặp Django.
- Bỏ CSS cục bộ trong từng template và chuyển sang `app-ui.css`.
- Chuẩn hóa header trang bằng `bo-page-header`, `bo-page-title`, `bo-page-subtitle`.
- Chuẩn hóa filter bằng `bo-filter-card`, `bo-filter-grid-*`, `bo-filter-actions-grid`.
- Chuẩn hóa bảng bằng `bo-table-card`, `bo-table-compact`, `bo-table-dense`.
- Chuẩn hóa badge bằng `bo-badge`, `bo-badge-*`, `bo-status-badge`.
- Chuẩn hóa empty state bằng `bo-empty-cell`.
- Bổ sung icon Tabler cho title, nút lọc, xóa lọc, lưu, mở, import/export, tính lại, xóa.
- Các phần hướng dẫn/chú thích dài được đưa về nút `?` và panel ẩn/hiện bằng `.js-help-toggle`.

## 3. File đã sửa

```text
static/backoffice/css/app-ui.css
static/backoffice/js/app-ui.js
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/thong_ke.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/them_du_lieu.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/giam_sat_thiet_bi.html
```

## 4. Nội dung chính theo từng màn

### 4.1. Thống kê chấm công

- Bỏ block `<style>` riêng.
- Thêm page header chuẩn.
- Filter dùng `bo-filter-grid-attendance-stat`.
- Bảng đối chiếu dùng `bo-table-dense bang-thong-ke`.
- Badge trạng thái chuyển sang `bo-badge-*`.
- Cảnh báo MasterList cần tính lại chuyển sang `bo-alert-warning`.
- Nút lưu/tính lại/mở/yêu cầu sửa có icon.

### 4.2. Thêm dữ liệu chấm công

- Bỏ block `<style>` riêng.
- Hướng dẫn nhập dữ liệu đưa vào nút `?` cạnh title.
- Hướng dẫn chọn nhân sự và import Excel dùng `?` + help panel.
- Filter dùng `bo-filter-grid-manual-filter`.
- Form nhập dữ liệu dùng `bo-form-card` + `bo-manual-form-grid`.
- Các scope note chuyển sang `bo-alert-info` / `bo-alert-warning`.
- Bảng dữ liệu đã thêm dùng `bo-table-compact`.
- Bỏ inline width trong `<th>`, thay bằng class cột.

### 4.3. Giám sát thiết bị chấm công

- Bỏ block `<style>` riêng.
- Header + action buttons chuyển sang `bo-page-header` / `bo-page-actions`.
- Quy ước trạng thái và cách xử lý dữ liệu đưa vào nút `?` cạnh title.
- KPI chuyển sang `bo-monitor-kpi-grid` + `bo-kpi-card`.
- Bảng thiết bị và bảng UID chưa map dùng `bo-table-compact`.
- Badge động từ context chuyển sang class `bo-status-dynamic-*`.
- UID pill chuyển sang `bo-uid-pill`.

## 5. Cập nhật JS dùng chung

`app-ui.js` bổ sung hàm `initHelpToggles()` để mọi nút dạng:

```html
<button class="bo-help js-help-toggle" data-help-target="idPanel">?</button>
```

có thể ẩn/hiện panel tương ứng. Việc này giúp các template sau không cần viết lại JS riêng cho tooltip/help panel.

## 6. Kiểm tra tĩnh đã thực hiện

Với 3 template trong Phase 5, đã kiểm tra không còn các mẫu cũ:

- `<style>`
- `style=`
- `class="badge ..."`
- `badge bg-*`
- `alert alert-*`
- `form-hint`
- `page-title-block`
- `filter-compact`
- `monitor-filter`
- `help-btn`
- `hint-box`
- `scope-alert`

Lưu ý: chuỗi `bo-status-badge` và `bo-kpi-card` là class chuẩn mới, không phải class cũ.

## 7. Cách áp dụng

Giải nén patch vào project root:

```bash
unzip z115_ui_phase5_attendance_big_screens_patch_20260630.zip -d <PROJECT_ROOT>
```

Sau đó chạy:

```bash
python manage.py check
python manage.py collectstatic --noinput
```

## 8. Trang cần test

```text
/backoffice/attendance-devices-v2/thong-ke/
/backoffice/attendance-devices-v2/them-du-lieu/
/backoffice/attendance-devices-v2/giam-sat-thiet-bi/
```

Cần test các thao tác:

- Lọc/xóa lọc.
- Phân trang.
- Mở panel `?` hướng dẫn.
- Lưu dữ liệu đã sửa ở thống kê.
- Tạo yêu cầu sửa.
- Thêm dữ liệu thủ công cho nhiều nhân sự.
- Import Excel.
- Tính lại ngày/đơn vị.
- Normalize lại.
- Tính lại MasterList.
- Mở chi tiết UID và lọc UID.
- Xóa raw chưa map trong phạm vi lọc/UID cụ thể nếu đang dùng dữ liệu test.

## 9. Ghi chú

Mình chưa chạy được `manage.py check` thực tế vì môi trường patch không có project root/runtime đầy đủ. Patch này chỉ thay đổi lớp trình bày và JS helper chung, không thay đổi nghiệp vụ backend.
