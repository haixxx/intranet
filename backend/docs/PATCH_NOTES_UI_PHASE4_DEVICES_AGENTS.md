# PATCH NOTES - UI Phase 4: Thiết bị/Agent chấm công v2

Ngày tạo: 2026-06-30

## Mục tiêu

Chuẩn hóa nhóm template thiết bị, Agent và các màn MasterList/Audit nhỏ của `attendance_devices_v2` theo bộ chuẩn giao diện Backoffice:

- Giữ Tabler làm nền giao diện offline.
- Dùng lớp chuẩn nội bộ `bo-*` thay vì style rải rác trong template.
- Bỏ hiển thị `(v2)` ở title người dùng cuối.
- Chuyển chú thích/hướng dẫn ngắn sang icon `?` tooltip.
- Bổ sung icon Tabler cho title, nút thao tác và badge policy.
- Chuẩn hóa badge theo quy tắc nền nhạt + chữ tương phản rõ.

## File đã sửa

```text
static/backoffice/css/app-ui.css

apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/agents_list.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/agents_form.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/devices_list.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/devices_form.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/audit_matches.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/master_edit.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/master_list.html
apps/attendance_devices_v2/templates/backoffice/attendance_devices_v2/master_summary.html
```

## Nội dung chính

### 1. Agent chấm công

- `Agents máy chấm công (v2)` đổi thành `Agent chấm công`.
- List dùng `bo-page-header`, `bo-filter-card`, `bo-table-card`, `bo-table`.
- Form dùng `bo-form-card`, `bo-form-grid`, `bo-form-actions`.
- API key card dùng icon key, tooltip giải thích, `bo-inline-code` để copy key dễ hơn.
- Trạng thái key dùng `bo-badge-success` / `bo-badge-secondary`.

### 2. Thiết bị chấm công

- `Thiết bị chấm công (v2)` đổi thành `Thiết bị chấm công`.
- List policy dùng badge nội bộ:
  - realtime: `bo-badge-success`
  - backfill: `bo-badge-info`
  - time sync: `bo-badge-warning`
  - tắt luồng: `bo-badge-secondary`
- Form thiết bị chia rõ 4 section:
  - Thông tin thiết bị
  - SDK / kết nối máy
  - Sync Policy cho Agent
  - Time Sync
- Các `form-hint` được chuyển sang icon `?` tooltip ở cạnh label.
- Các khối hướng dẫn dài chuyển sang `bo-alert-info` hoặc `bo-alert-warning`.

### 3. MasterList / Audit nhỏ

- `Master List - Danh sách (v2)` đổi thành `Dữ liệu đối chiếu chấm công`.
- `Master List - Tổng hợp (v2)` đổi thành `Tổng hợp đối chiếu chấm công`.
- `Master List - Chỉnh sửa (v2)` đổi thành `Chỉnh sửa dữ liệu đối chiếu`.
- `Đối chiếu chấm công (v2)` đổi thành `Đối chiếu chấm công`.
- Bảng dùng `bo-table-compact` để phù hợp dữ liệu nhiều cột.
- Badge trạng thái `MATCHED/MISSING/EXEMPT/STALE` chuyển sang `bo-badge-*`.
- Empty state dùng `bo-empty-cell` hoặc `bo-empty-state`.

## CSS bổ sung

Thêm các helper mới trong `app-ui.css`:

```text
.bo-device-policy-list
.bo-key-grid
.bo-edit-note-cell
.bo-time-stack
```

## Kiểm tra tĩnh đã thực hiện

Trong nhóm file Phase 4 đã sửa, không còn các pattern cũ:

```text
style=
form-hint
alert alert-*
badge bg-*
text-bg-*
page-title-block
(v2)
Master List -
<h2 class="mb-...">
```

## Cách áp dụng

Giải nén patch vào project root, cùng cấp với `apps/` và `static/`:

```bash
unzip z115_ui_phase4_devices_agents_patch_20260630.zip -d <PROJECT_ROOT>
```

Sau đó chạy:

```bash
python manage.py check
python manage.py collectstatic --noinput
```

## Màn hình nên test

```text
attendance_devices_v2:agent_list
attendance_devices_v2:agent_create
attendance_devices_v2:agent_edit
attendance_devices_v2:device_list
attendance_devices_v2:device_create
attendance_devices_v2:device_edit
attendance_devices_v2:audit_matches
attendance_devices_v2:master_list
attendance_devices_v2:master_summary
attendance_devices_v2:master_edit
```

## Lưu ý

Phase này chưa sửa 3 màn hình lớn:

```text
attendance_devices_v2/thong_ke.html
attendance_devices_v2/them_du_lieu.html
attendance_devices_v2/giam_sat_thiet_bi.html
```

Ba màn này có nhiều CSS riêng và bảng lớn, nên nên tách sang Phase 5 để rà bố cục kỹ hơn.
