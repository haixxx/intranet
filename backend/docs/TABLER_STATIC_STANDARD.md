# TABLER_STATIC_STANDARD.md

## 1. Mục tiêu

Chuẩn hóa nền giao diện Backoffice theo Tabler, bảo đảm:

- Chạy offline hoàn toàn trong mạng nội bộ.
- Không phụ thuộc CDN, Internet hoặc `@latest`.
- Phù hợp nhiều thiết bị: desktop, laptop, tablet, màn hình nhỏ.
- Dễ nâng cấp/rollback vendor.
- Không làm nghiệp vụ Django phụ thuộc quá sâu vào theme bên ngoài.
- Có lớp giao diện nội bộ `bo-*` để đồng bộ title, bảng, filter, badge, alert, KPI.

## 2. Hiện trạng static trước khi chuẩn hóa

Thư mục `static.zip` hiện có:

```text
static/vendor/bootstrap.bundle.min.js
static/vendor/bootstrap.bundle.min.js.map
static/vendor/chart.umd.min.js
static/vendor/fonts/tabler-icons.ttf
static/vendor/fonts/tabler-icons.woff
static/vendor/fonts/tabler-icons.woff2
static/vendor/tabler-icons.min.css
static/vendor/tabler.min.css
static/vendor/tabler.min.js
```

Nhận xét:

- Có đủ Tabler CSS/JS, Tabler Icons CSS và font icon.
- Có Chart.js dùng cho các dashboard/báo cáo.
- Các file đang đặt trực tiếp trong `static/vendor/`, chưa có version trong đường dẫn.
- `core/login.html` vẫn dùng CDN Tabler `@latest`, chưa phù hợp môi trường offline.
- `backoffice/base.html` đang load cả `bootstrap.bundle.min.js` và `tabler.min.js`; bản Tabler đang dùng đã bundle Bootstrap nên không nên load trùng.

## 3. Cấu trúc static chuẩn sau khi áp dụng

```text
static/
  vendor/
    tabler-1.4.0/
      css/
        tabler.min.css
      js/
        tabler.min.js

    tabler-icons-3.35.0/
      css/
        tabler-icons.min.css
        fonts/
          tabler-icons.woff2
          tabler-icons.woff
          tabler-icons.ttf

    chartjs-4.5.0/
      chart.umd.min.js

  backoffice/
    css/
      app-ui.css
    js/
      app-ui.js
```

## 4. Quy tắc load asset

Trong `backoffice/base.html`:

```django
<link href="{% static 'vendor/tabler-1.4.0/css/tabler.min.css' %}" rel="stylesheet">
<link href="{% static 'vendor/tabler-icons-3.35.0/css/tabler-icons.min.css' %}" rel="stylesheet">
<link href="{% static 'backoffice/css/app-ui.css' %}" rel="stylesheet">

<script src="{% static 'vendor/tabler-1.4.0/js/tabler.min.js' %}"></script>
<script src="{% static 'backoffice/js/app-ui.js' %}"></script>
```

Không load thêm:

```django
<script src="{% static 'vendor/bootstrap.bundle.min.js' %}"></script>
```

Lý do: `tabler.min.js` bản hiện tại đã đóng gói Bootstrap 5.3.7.

## 5. Vai trò của từng lớp

| Lớp | Vai trò | Có sửa trực tiếp không? |
|---|---|---|
| Tabler Core | Nền UI: grid, card, form, table, button, modal, dropdown | Không sửa trực tiếp |
| Tabler Icons | Icon font `.ti` | Không sửa trực tiếp |
| Chart.js | Biểu đồ dashboard/báo cáo | Không sửa trực tiếp |
| `app-ui.css` | Chuẩn hóa giao diện nội bộ | Có |
| `app-ui.js` | Khởi tạo tooltip/popover dùng chung | Có |
| Template Django | Hiển thị nghiệp vụ | Có, nhưng dùng class chuẩn |

## 6. Quy tắc `bo-*`

Các template nghiệp vụ không nên tự viết CSS riêng nếu có thể dùng class chuẩn:

```text
bo-page-header
bo-page-pretitle
bo-page-title
bo-page-subtitle
bo-page-actions
bo-filter-card
bo-filter-grid
bo-table
bo-table-compact
bo-table-dense
bo-badge
bo-alert
bo-kpi-card
bo-empty-state
```

Mục tiêu là sau này nếu nâng cấp Tabler hoặc đổi layout, chỉ cần chỉnh `app-ui.css`, không phải sửa toàn bộ template.

## 7. Quy tắc responsive

- Desktop/laptop: sidebar trái, content rộng, `container-fluid`.
- Tablet/màn hình vừa: giảm padding, filter chuyển còn 2 cột.
- Mobile/màn hình nhỏ: sidebar xếp trên, filter một cột, bảng cho phép scroll ngang.
- Bảng thường dùng `bo-table`.
- Bảng nhiều cột dùng `bo-table-compact`.
- Bảng công/thống kê rất dày dùng `bo-table-dense`.

## 8. Các file đã sửa trong patch này

```text
apps/backoffice/templates/backoffice/base.html
apps/core/templates/core/login.html
apps/backoffice/templates/backoffice/dashboard.html
apps/backoffice/templates/backoffice/attendance/bao_cao.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/bao_cao.html
static/backoffice/css/app-ui.css
static/backoffice/js/app-ui.js
static/vendor/tabler-1.4.0/css/tabler.min.css
static/vendor/tabler-1.4.0/js/tabler.min.js
static/vendor/tabler-icons-3.35.0/css/tabler-icons.min.css
static/vendor/tabler-icons-3.35.0/css/fonts/*
static/vendor/chartjs-4.5.0/chart.umd.min.js
docs/VENDOR_MANIFEST.md
```

## 9. Cách áp dụng patch

Giải nén file patch vào thư mục gốc project, cùng cấp với `apps/` và `static/`:

```bash
unzip z115_tabler_offline_static_patch_20260630.zip -d <PROJECT_ROOT>
```

Sau đó chạy:

```bash
python manage.py collectstatic --noinput
python manage.py check
```

Nếu đang chạy local bằng `runserver`, chỉ cần restart server.

## 10. Kiểm tra sau khi áp dụng

Mở các trang sau:

```text
/login/
/backoffice/
/backoffice/attendance/report/
/attendance-devices-v2/bao-cao/
```

Cần kiểm tra:

- Không còn request ra Internet trong tab Network.
- Icon hiển thị bình thường, không lỗi font `.woff2`.
- Dropdown hồ sơ/ngôn ngữ hoạt động.
- Alert có thể đóng.
- Biểu đồ Chart.js vẫn hiển thị ở dashboard/báo cáo.
- Giao diện không bị vỡ trên màn hình nhỏ.

## 11. Việc chưa làm trong patch này

Patch này mới chuẩn hóa nền static và base. Chưa sửa sâu từng template nghiệp vụ.

Các bước tiếp theo:

1. Chuẩn hóa nhóm danh mục đơn giản: đơn vị, chức danh, ca, nhân sự.
2. Chuẩn hóa module chấm công: đăng ký/chốt công, xem công chốt, công tháng.
3. Chuẩn hóa module thiết bị chấm công: đối chiếu, thêm dữ liệu, giám sát thiết bị.
4. Chuẩn hóa approval/admin.
5. Gỡ CSS inline còn lại sau khi từng template đã chuyển sang `bo-*`.
