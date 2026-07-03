# PATCH NOTES - UI Phase 5 Filter Layout Fix v2

## Mục tiêu

Sửa triệt để lỗi bộ lọc của 3 màn hình lớn:

- Thống kê chấm công
- Thêm dữ liệu chấm công
- Giám sát thiết bị chấm công

## Nguyên nhân

File `app-ui.css` hiện tại vẫn còn rule ở cuối:

```css
@media (max-width: 768px) {
  .bo-filter-grid-attendance-stat,
  .bo-filter-grid-monitor,
  .bo-filter-grid-manual-filter,
  .bo-manual-form-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
    min-width: 0;
  }
}
```

Khi vùng nội dung bị tính hẹp do sidebar, zoom trình duyệt, laptop nhỏ hoặc layout responsive, rule này ép 3 bộ lọc lớn thành nhiều dòng.

## Đã sửa

1. Khóa 3 filter grid lớn thành một hàng ngang bằng `width: max-content`, `min-width`, `grid-auto-flow: column`.
2. Cho phép scroll ngang bên trong `.bo-filter-card` thay vì tự vỡ thành nhiều dòng.
3. Loại 3 class filter khỏi rule `@media (max-width: 768px)`.
4. Chỉ giữ responsive 2 cột cho `.bo-manual-form-grid` là form nhập liệu, không phải thanh lọc.

## File thay đổi

```text
static/backoffice/css/app-ui.css
```

## Cách áp dụng

Giải nén patch vào project root:

```bash
unzip z115_ui_phase5_filter_layout_fix_v2_patch_20260701.zip -d <PROJECT_ROOT>
python manage.py collectstatic --noinput
```

Sau đó hard refresh trình duyệt bằng `Ctrl + F5`.
