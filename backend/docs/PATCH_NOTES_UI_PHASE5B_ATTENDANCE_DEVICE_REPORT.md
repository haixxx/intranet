# PATCH NOTES — UI Phase 5B: Báo cáo chấm công v2

Ngày: 2026-07-01

## Mục tiêu
Chuẩn hóa màn hình báo cáo của module **Quản lý chấm công**:

- `apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/bao_cao.html`

Đây là file còn thiếu sau Phase 5, vì Phase 5 mới tập trung vào 3 màn hình lớn:

- `thong_ke.html`
- `them_du_lieu.html`
- `giam_sat_thiet_bi.html`

## File đã sửa

```text
static/backoffice/css/app-ui.css
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/bao_cao.html
```

## Nội dung đã chuẩn hóa

### 1. Header / title
- Đổi title từ `Báo cáo` thành `Báo cáo chấm công`.
- Dùng chuẩn `bo-page-header`, `bo-page-pretitle`, `bo-page-title`, `bo-page-subtitle`.
- Bổ sung icon Tabler cho tiêu đề.

### 2. Filter
- Chuyển filter từ Bootstrap row/col sang `bo-filter-grid-attdev-report`.
- Giữ filter dạng hàng ngang trên desktop/laptop.
- Dùng `min-width` + `width:max-content` để tránh tự xuống nhiều dòng quá sớm.
- Nếu thiếu chiều rộng, filter scroll ngang trong `bo-filter-card`.
- Mobile nhỏ mới xếp về 1 cột.
- Đổi `Reset` thành `Xóa lọc`.
- Thêm icon cho nút `Xem` và `Xóa lọc`.

### 3. Chú thích / hướng dẫn
- Đưa giải thích `Nguồn dữ liệu` và `Ngưỡng` vào icon `?` tooltip cạnh label.
- Không đặt chú thích dài trực tiếp dưới input.

### 4. KPI
- Chuyển class cũ:
  - `kpi-card`
  - `kpi-label`
  - `kpi-value`
  - `kpi-sub`
  - `kpi-link`
- Sang chuẩn chung:
  - `bo-kpi-card`
  - `bo-kpi-label`
  - `bo-kpi-value`
  - `bo-kpi-sub`
  - `bo-kpi-link`

### 5. Chart / Card
- Chuyển `chart-card` sang `bo-chart-card`.
- Bổ sung icon cho card chart và card xử lý.
- Chart dùng màu từ biến CSS Tabler thay vì hard-code Bootstrap cũ.

### 6. Table / Empty state / Badge
- Bảng sự cố, top đơn vị, top cá nhân, việc cần xử lý dùng `bo-table-compact` và `bo-attdev-report-table`.
- Empty state dùng `bo-empty-state`.
- Trạng thái việc cần làm dùng `bo-badge bo-badge-warning`.

## Ghi chú responsive

Cần test ở 4 ngữ cảnh:

1. Desktop rộng: filter nằm một hàng, KPI 4 ô/hàng.
2. Laptop có sidebar: filter không tự vỡ thành nhiều dòng; nếu thiếu chiều rộng thì scroll ngang trong card.
3. Tablet: card/chart xếp lại theo cột hợp lý.
4. Mobile: filter chuyển 1 cột, bảng/chart không tràn layout chính.

## Trang cần test

```text
/backoffice/attendance-devices-v2/bao-cao/
```

hoặc URL thực tế của route:

```text
/backoffice/attendance-devices-v2/bao-cao/
```

nếu project đang đặt prefix khác, test theo menu **Quản lý chấm công → Báo cáo**.

## Cách áp dụng

```bash
unzip z115_ui_phase5b_attendance_device_report_patch_20260701.zip -d <PROJECT_ROOT>
python manage.py check
python manage.py collectstatic --noinput
```

Sau đó nhấn `Ctrl + F5` trên trình duyệt.
