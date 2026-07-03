# VENDOR_MANIFEST.md

Tài liệu này ghi lại các asset giao diện đang được đóng gói offline cho hệ thống Backoffice.

Nguyên tắc:

- Không dùng CDN.
- Không dùng `@latest`.
- Vendor phải có version rõ ràng trong đường dẫn.
- Khi nâng cấp vendor, tạo thư mục version mới thay vì ghi đè trực tiếp.
- Sau khi kiểm thử ổn định mới xóa version cũ.

| Thành phần | Version | Đường dẫn | Size | SHA-256 | License | Nguồn |
|---|---:|---|---:|---|---|---|
| Tabler Core CSS | 1.4.0 | `static/vendor/tabler-1.4.0/css/tabler.min.css` | 536099 | `e2f5c542d00f15513e80d527655e82a2e12573799ea278a8b298206edb4b9ff3` | MIT | https://tabler.io |
| Tabler Core JS | 1.4.0 | `static/vendor/tabler-1.4.0/js/tabler.min.js` | 83517 | `f5ca44ee5ffb40f2ad571b4f988e28ed760f4e4a5e4025231a76d741444ba6e1` | MIT | https://tabler.io |
| Tabler Icons CSS | 3.35.0 | `static/vendor/tabler-icons-3.35.0/css/tabler-icons.min.css` | 251549 | `954571c93048445811bc2d7519de588ccfc825939fd57e15787151e3ceff8406` | MIT | https://tabler.io/icons |
| Tabler Icons font WOFF2 | 3.35.0 | `static/vendor/tabler-icons-3.35.0/css/fonts/tabler-icons.woff2` | 778812 | `0586ae822d8eaddd62b354da7ecbdeb1b22c49b78e054616bb8ab06f560c792d` | MIT | https://tabler.io/icons |
| Tabler Icons font WOFF | 3.35.0 | `static/vendor/tabler-icons-3.35.0/css/fonts/tabler-icons.woff` | 1102184 | `99a345f8f28af2f030c530eff75be14698728b5ca55ff83f43a562de9123ac1b` | MIT | https://tabler.io/icons |
| Tabler Icons font TTF | 3.35.0 | `static/vendor/tabler-icons-3.35.0/css/fonts/tabler-icons.ttf` | 2413932 | `62cb919c55d75478dd4205c1f66db36f00f606e7c548bb7c993eff17c0666665` | MIT | https://tabler.io/icons |
| Chart.js UMD | 4.5.0 | `static/vendor/chartjs-4.5.0/chart.umd.min.js` | 208299 | `6af6a460d96b79ab29c1ba441720389fe9b4d049db9f20783f41504fc7d26548` | MIT | https://www.chartjs.org |
| Backoffice UI CSS | project | `static/backoffice/css/app-ui.css` | 8455 | `7c4623e9b5d3f57f5d08c97974857a8c1631fd271ed0012a5400176067984d1f` | internal | - |
| Backoffice UI JS | project | `static/backoffice/js/app-ui.js` | 979 | `b3fd4d4312b0a457c01b89856fc6ba870ec2ed6509fc0ee63ea26b1338b82f37` | internal | - |

## Ghi chú quan trọng

`tabler.min.js` bản 1.4.0 đã bundle Bootstrap 5.3.7. Vì vậy không load thêm `bootstrap.bundle.min.js` trong `base.html`. Nếu load cả hai, modal/dropdown/tooltip có thể bị khởi tạo trùng hoặc khó debug.

`tabler-icons.min.css` dùng đường dẫn font tương đối `./fonts/...`. Vì file CSS được đặt tại `static/vendor/tabler-icons-3.35.0/css/`, thư mục font phải nằm tại `static/vendor/tabler-icons-3.35.0/css/fonts/`.
