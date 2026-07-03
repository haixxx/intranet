# Rà soát và chuẩn hóa UI theo Tabler Offline - 01/07/2026

## Phạm vi rà soát

Đã kiểm tra lại bộ code người dùng gửi:

- `apps010720262.zip`
- `static010720262.zip`
- `TABLER_OFFLINE_UI_STANDARD_AND_PLAN(3).md`

Tập trung vào 6 nhóm đã xử lý trước đó và phần chuẩn hóa UI theo file MD:

1. Static offline / Tabler / icon fonts.
2. Phân quyền User custom model.
3. Đồng bộ menu `base.html` và quyền view backend.
4. Phân trang server-side.
5. Tối ưu truy vấn / tránh giới hạn cứng.
6. Chuẩn hóa UI `bo-*`, bỏ CSS inline / style rải rác trong template.

---

## Kết luận nhanh

Code hiện tại đã ổn hơn nhiều so với các bản trước:

- Static offline đã đúng hướng.
- `base.html` đã dùng vendor có version.
- Không còn load trùng `bootstrap.bundle.min.js`.
- Quyền User đã chuyển sang `core.*_user`.
- Các trang quản trị hệ thống chính đã có phân trang.
- `app-ui.css` đã tồn tại và nhiều template đã dùng class `bo-*`.

Tuy nhiên trước khi vá lần này vẫn còn các điểm nên xử lý tiếp:

- `dashboard.html` vẫn còn block `<style>` rất lớn.
- Một số template còn `style=` inline.
- Một số template vẫn dùng header cũ hoặc chưa đồng bộ hoàn toàn theo `bo-page-header`.
- `approvals_inbox`, `approvals_my_requests`, `temp_assignment_list` vẫn còn dạng giới hạn danh sách hoặc chưa có phân trang thật.
- Badge dashboard còn dùng class Bootstrap trực tiếp như `badge bg-*`, chưa đúng định hướng `bo-badge`.

Bản vá lần này xử lý các điểm trên.

---

## Các file đã sửa

### Backend / view

```text
apps/backoffice/views_approvals.py
apps/backoffice/views_temp_assignments.py
apps/backoffice/services/dashboard/daily.py
```

### Template

```text
apps/backoffice/templates/backoffice/dashboard.html
apps/backoffice/templates/backoffice/profile/profile.html
apps/backoffice/templates/backoffice/users/roles.html
apps/backoffice/templates/backoffice/common/import.html
apps/backoffice/templates/backoffice/hr/employees/import.html
apps/backoffice/templates/backoffice/hr/assignments/list.html
apps/backoffice/templates/backoffice/approvals/inbox.html
apps/backoffice/templates/backoffice/approvals/my_requests.html
apps/backoffice/templates/backoffice/approvals/admin/version_form_builder.html
apps/backoffice/templates/backoffice/roles/matrix.html
```

### Static

```text
static/backoffice/css/app-ui.css
```

---

## Nội dung sửa chính

### 1. Static offline

Đã kiểm tra lại:

```text
static/vendor/tabler-1.4.0/css/tabler.min.css
static/vendor/tabler-1.4.0/js/tabler.min.js
static/vendor/tabler-icons-3.35.0/css/tabler-icons.min.css
static/vendor/tabler-icons-3.35.0/css/fonts/tabler-icons.woff2
static/vendor/tabler-icons-3.35.0/css/fonts/tabler-icons.woff
static/vendor/tabler-icons-3.35.0/css/fonts/tabler-icons.ttf
static/vendor/chartjs-4.5.0/chart.umd.min.js
```

Kết luận:

- Đúng chuẩn offline.
- Không thấy CDN trong template/CSS/JS nghiệp vụ.
- `base.html` không load `bootstrap.bundle.min.js` riêng.
- `login.html` dùng asset local.

### 2. Phân quyền User

Đã kiểm tra lại grep:

```text
auth.view_user
auth.add_user
auth.change_user
auth.delete_user
```

Kết quả: không còn trong `apps`.

Kết luận: phần này ổn. User custom model nằm trong app `core`, nên dùng `core.view_user`, `core.add_user`, `core.change_user` là đúng.

### 3. Menu và quyền view

Đã kiểm tra `base.html`:

- Người dùng: `core.view_user`.
- Vai trò: `auth.view_group`.
- Ma trận quyền: `auth.view_permission`.
- Nhật ký: `audit.view_auditlog`.
- Quản trị luồng duyệt: `approvals.view_approvalflow`.
- Role Mapping: `approvals.view_roletitlemapping`.
- Quản lý chấm công: vẫn giữ các quyền liên quan `attendance_devices_v2`, bao gồm quyền đối chiếu cũ.

Kết luận: menu và view hiện đã đồng bộ hơn, không còn lệch nghiêm trọng như bản trước.

### 4. Phân trang

Trước khi vá tiếp, vẫn còn danh sách phê duyệt và điều động dùng dạng cắt cứng / chưa phân trang đầy đủ.

Đã bổ sung phân trang cho:

```text
approvals_inbox
approvals_my_requests
temp_assignment_list
```

Các template tương ứng đã include:

```django
{% include "backoffice/includes/pagination.html" %}
```

Lợi ích:

- Không còn giới hạn cứng `[:500]` ở các danh sách này.
- Giao diện thống nhất với các trang quản trị hệ thống trước đó.
- Dữ liệu lớn không bị dồn toàn bộ ra template.

### 5. Tối ưu truy vấn / hiệu quả

Đã giữ các tối ưu cũ:

- User list: `prefetch_related("groups")`.
- Role list: `Count("permissions")`.
- Permission matrix: phân trang quyền và cache quyền theo group.
- Audit list: phân trang thay vì cắt 500 dòng.

Bổ sung lần này:

- `approvals_inbox`: phân trang theo queryset phù hợp từng scope.
- `approvals_my_requests`: phân trang queryset yêu cầu của chính user.
- `temp_assignment_list`: lọc `over60` bằng điều kiện DB thay vì lấy 500 dòng rồi lọc Python.

### 6. Chuẩn hóa UI theo `bo-*`

Đã xử lý các điểm còn lệch chuẩn:

- Chuyển CSS lớn trong `dashboard.html` sang `app-ui.css`.
- Bỏ `style=` inline trong:
  - `profile.html`
  - `version_form_builder.html`
  - `roles/matrix.html`
- Chuyển header cũ sang `bo-page-header` ở:
  - profile
  - user roles
  - import chung
  - import nhân sự
  - dashboard
- Chuẩn hóa dashboard:
  - bảng dùng `bo-table`, `bo-table-compact`;
  - badge chuyển sang `bo-badge`;
  - filter dùng `bo-filter-card` / grid riêng cho dashboard;
  - empty cell dùng `bo-empty-cell`.
- Bổ sung CSS helper:
  - `.bo-js-hidden`
  - `.bo-modal-scroll`
  - `.approval-steps-count`
  - `.bo-permission-col`
  - nhóm CSS dashboard overview.

---

## Kết quả kiểm tra tự động đã chạy

### 1. Kiểm tra cú pháp Python

```bash
python -m compileall -q apps
```

Kết quả: không có lỗi cú pháp Python.

### 2. Kiểm tra CDN / `@latest`

Đã kiểm tra trong `apps` và `static` với các chuỗi:

```text
cdn.jsdelivr
unpkg
cdnjs
fonts.googleapis
fonts.gstatic
@latest
```

Kết quả: không phát hiện trong template/CSS/JS nghiệp vụ.

### 3. Kiểm tra quyền User sai app label

Đã kiểm tra:

```text
auth.view_user
auth.add_user
auth.change_user
auth.delete_user
```

Kết quả: không còn.

### 4. Kiểm tra inline style / style block trong template backoffice chính

Đã kiểm tra:

```text
<style
style=
```

Kết quả: không còn trong `apps/backoffice/templates` và `apps/attendance_devices_v2/templates`.

---

## Chưa kiểm được trong sandbox

Chưa chạy được:

```bash
python manage.py check
python manage.py collectstatic --noinput
```

Lý do: gói người dùng gửi chỉ có `apps` và `static`; môi trường sandbox hiện không có đầy đủ project settings/requirements Django để chạy `manage.py`.

---

## Checklist test sau khi áp dụng

Nên test nhanh các màn sau:

```text
[ ] Login offline.
[ ] Dashboard tổng quan: daily / period, biểu đồ Chart.js, bảng thiết bị, bảng việc cần xử lý.
[ ] Hồ sơ cá nhân: bật/tắt đổi mật khẩu.
[ ] Người dùng: phân trang, sửa user, gán vai trò.
[ ] Vai trò / Ma trận quyền: lọc app, page_size, phân trang.
[ ] Nhật ký: tìm kiếm, phân trang.
[ ] Phê duyệt: Tôi cần duyệt, Yêu cầu của tôi, lọc scope/status, phân trang.
[ ] Điều động tạm thời: lọc over60, phân trang, nút sửa/hoàn thành/hủy.
[ ] Builder luồng duyệt: thêm bước, đổi loại bước, popup chọn user/đơn vị.
[ ] Responsive: desktop 1366x768, laptop có sidebar, tablet, mobile.
```

---

## Kết luận

Bản hiện tại sau khi áp dụng patch này đã bám sát chuẩn MD hơn:

```text
Tabler = nền giao diện
app-ui.css = lớp chuẩn hóa nội bộ
bo-* = class giao diện nội bộ dùng chung
Django template nghiệp vụ hiện tại = lõi nghiệp vụ
```

Không thấy lỗi lớn còn lại trong 6 nhóm đã rà. Điểm cần tiếp tục sau bản này là rà sâu từng màn nghiệp vụ chấm công theo dữ liệu thực tế, vì phần đó có bảng lớn và trạng thái nghiệp vụ phức tạp hơn nhóm quản trị hệ thống.
