# PATCH NOTES - UI Phase 5 Filter Layout Fix

Ngày tạo: 2026-07-01

## Mục tiêu

Sửa lỗi bố cục bộ lọc ở 3 màn hình lớn của module chấm công v2:

- `thong_ke.html`
- `them_du_lieu.html`
- `giam_sat_thiet_bi.html`

Sau Phase 5, CSS responsive tại breakpoint `max-width: 1200px` làm các bộ lọc tự chuyển thành nhiều dòng. Với màn hình desktop/nội bộ có sidebar, vùng content thực tế dễ nhỏ hơn 1200px nên bộ lọc bị xuống dòng quá sớm.

## File đã sửa

```text
static/backoffice/css/app-ui.css
```

## Nội dung sửa

1. Thêm `overflow-x: auto` cho `.bo-filter-card` để các bộ lọc rộng có thể giữ layout theo cột ngang.
2. Thêm `min-width` cho 3 grid filter lớn:
   - `.bo-filter-grid-attendance-stat`: 1098px
   - `.bo-filter-grid-manual-filter`: 752px
   - `.bo-filter-grid-monitor`: 910px
3. Bỏ rule responsive `max-width: 1200px` từng ép các filter này chuyển thành 3-4 cột và nhiều dòng.
4. Giữ responsive mobile tại `max-width: 768px`, nhưng reset `min-width: 0` để màn nhỏ vẫn dùng 2 cột phù hợp.

## Cách áp dụng

Giải nén patch vào project root:

```bash
unzip z115_ui_phase5_filter_layout_fix_patch_20260701.zip -d <PROJECT_ROOT>
```

Sau đó chạy:

```bash
python manage.py collectstatic --noinput
```

Nếu môi trường cache static/browser còn lưu CSS cũ, cần hard refresh trình duyệt bằng `Ctrl + F5`.

## Màn hình cần kiểm tra

- Thống kê chấm công
- Thêm dữ liệu chấm công
- Giám sát thiết bị chấm công

Kỳ vọng: trên desktop/laptop, bộ lọc giữ dạng các cột ngang; không tự tách thành nhiều dòng tại vùng content nhỏ hơn 1200px. Trên màn hình nhỏ/mobile, filter vẫn được xếp lại thành 2 cột để dễ thao tác.
