# Z115 - Script nguồn build migration V3 Fixed

## Lý do có bản V3

Bản V2 có các điểm dễ lỗi khi tạo release:

- Có `source "$SOURCE_ENV_FILE"` để lấy biến DB. Nếu `.env.production` có nội dung không hợp lệ với Bash hoặc ký tự đặc biệt, script có thể lỗi.
- Lệnh backup DB dùng biến host `POSTGRES_USER/POSTGRES_DB`; bản V3 chuyển sang dùng biến bên trong container `db`.
- Bản V2 chưa kiểm tra quyền ghi `releases/backups` trước khi chạy.
- Bản V2 chưa verify rõ file `images/z115-backoffice-web_TAG.tar` và archive sau khi tạo.

## Cách cài

```bash
cp z115_source_build_migration_v3_fixed.sh /mnt/code/intranet/scripts/source/
chmod +x /mnt/code/intranet/scripts/source/z115_source_build_migration_v3_fixed.sh
```

## Chạy mặc định

```bash
cd /mnt/code/intranet/scripts
./source/z115_source_build_migration_v3_fixed.sh
```

## Nếu chỉ muốn build/package, không chạy makemigrations/migrate DEV

```bash
RUN_DEV_MAKEMIGRATIONS=0 RUN_DEV_MIGRATE=0 ./source/z115_source_build_migration_v3_fixed.sh
```

## Nếu muốn bỏ qua migrate staging

```bash
RUN_STAGING_MIGRATE=0 ./source/z115_source_build_migration_v3_fixed.sh
```

## Nếu compose file máy nguồn không phải docker-compose.yml

```bash
SOURCE_COMPOSE_FILE=docker-compose.yml ./source/z115_source_build_migration_v3_fixed.sh
```

## Kết quả

Sau khi chạy xong, file release nằm tại:

```text
/mnt/code/intranet/releases/z115_update_YYYYMMDD_HHMMSS_YYYYMMDD_HHMMSS-migration.tar.gz
```

Kiểm tra:

```bash
tar -tzf /mnt/code/intranet/releases/z115_update_xxx.tar.gz | head -80
```

Cần thấy:

```text
z115_update_xxx/images/z115-backoffice-web_xxx-migration.tar
z115_update_xxx/RELEASE_INFO.txt
z115_update_xxx/APPLY_ON_TARGET.txt
```
