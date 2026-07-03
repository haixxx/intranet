# PATCH_NOTES.md

## Nội dung patch

Patch này thực hiện bước nền tảng cho giao diện Tabler offline:

1. Chuyển vendor asset sang thư mục có version.
2. Bổ sung đúng thư mục font cho Tabler Icons.
3. Tạo `app-ui.css` làm lớp chuẩn hóa giao diện nội bộ.
4. Tạo `app-ui.js` để khởi tạo tooltip/popover dùng chung.
5. Sửa `backoffice/base.html` để load vendor mới và bỏ `bootstrap.bundle.min.js`.
6. Sửa `core/login.html` để bỏ CDN `@latest`, chạy offline hoàn toàn.
7. Chuyển các template đang dùng Chart.js sang đường dẫn `chartjs-4.5.0`.
8. Bổ sung tài liệu `TABLER_STATIC_STANDARD.md` và `VENDOR_MANIFEST.md`.

## Lưu ý khi merge

- Giải nén patch vào project root.
- Không cần xóa ngay các file cũ trong `static/vendor/`; có thể giữ trong giai đoạn kiểm thử.
- Sau khi kiểm thử ổn định, có thể dọn các file cũ không còn được template gọi:
  - `static/vendor/bootstrap.bundle.min.js`
  - `static/vendor/bootstrap.bundle.min.js.map`
  - `static/vendor/tabler.min.css`
  - `static/vendor/tabler.min.js`
  - `static/vendor/tabler-icons.min.css`
  - `static/vendor/chart.umd.min.js`
  - `static/vendor/fonts/*`

## Kiểm tra nhanh

```bash
python manage.py check
python manage.py collectstatic --noinput
```

Kiểm tra Network trên trình duyệt: không được có request ra `cdn.jsdelivr.net`, `tabler.io`, `getbootstrap.com`, `chartjs.org`.
