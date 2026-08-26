# Z115 Backoffice - Shell Scripts V2 đúng theo máy đích offline `/opt/z115-backoffice`

## Sửa so với bản trước

Bản trước giả định máy đích có `/mnt/code/intranet`. Điều đó **không đúng** với máy đích của bạn.

Theo tài liệu triển khai máy đích offline ngày 06/07/2026, máy đích dùng cấu trúc:

```text
/opt/z115-backoffice/
├── data/media
├── deploy/docker
└── backups
```

Trong đó compose nằm tại:

```text
/opt/z115-backoffice/deploy/docker/docker-compose.offline.yml
/opt/z115-backoffice/deploy/docker/.env.production
```

Vì vậy bộ script V2 này mặc định dùng đúng các đường dẫn trên.

---

## Danh sách script

```text
source/
├── z115_source_build_nomigration_v2.sh
└── z115_source_build_migration_v2.sh

target/
├── z115_target_apply_nomigration_offline_v2.sh
├── z115_target_apply_migration_offline_v2.sh
├── z115_target_backup_db_offline_v2.sh
├── z115_target_healthcheck_offline_v2.sh
├── z115_target_rollback_tag_offline_v2.sh
└── z115_target_restore_db_offline_v2.sh
```

---

## Cách dùng trên máy nguồn

Máy nguồn vẫn là máy có source code tại:

```text
/mnt/code/intranet
```

Cấp quyền:

```bash
chmod +x source/*.sh
```

Build bản không migration:

```bash
./source/z115_source_build_nomigration_v2.sh
```

Build bản có migration:

```bash
./source/z115_source_build_migration_v2.sh
```

Sau khi chạy xong, release nằm tại:

```text
/mnt/code/intranet/releases/z115_update_xxx.tar.gz
```

Copy sang máy đích:

```bash
scp /mnt/code/intranet/releases/z115_update_xxx.tar.gz \
  appz115@172.17.17.30:/opt/z115-backoffice/releases/
```

Nếu chưa có thư mục releases trên máy đích:

```bash
ssh appz115@172.17.17.30 "mkdir -p /opt/z115-backoffice/releases"
```

---

## Cách dùng trên máy đích

Copy thư mục `target/` hoặc các file `.sh` vào máy đích, ví dụ:

```bash
mkdir -p /opt/z115-backoffice/scripts
cp target/*.sh /opt/z115-backoffice/scripts/
chmod +x /opt/z115-backoffice/scripts/*.sh
```

Healthcheck:

```bash
/opt/z115-backoffice/scripts/z115_target_healthcheck_offline_v2.sh
```

Backup DB:

```bash
/opt/z115-backoffice/scripts/z115_target_backup_db_offline_v2.sh
```

Apply không migration:

```bash
/opt/z115-backoffice/scripts/z115_target_apply_nomigration_offline_v2.sh \
  /opt/z115-backoffice/releases/z115_update_xxx.tar.gz
```

Apply có migration:

```bash
/opt/z115-backoffice/scripts/z115_target_apply_migration_offline_v2.sh \
  /opt/z115-backoffice/releases/z115_update_xxx.tar.gz
```

Rollback code về TAG cũ:

```bash
/opt/z115-backoffice/scripts/z115_target_rollback_tag_offline_v2.sh 20260706-offline01
```

Restore DB từ file dump:

```bash
/opt/z115-backoffice/scripts/z115_target_restore_db_offline_v2.sh \
  /opt/z115-backoffice/backups/prod_db_xxx.dump
```

---

## Biến có thể chỉnh nếu cần

Mặc định:

```bash
TARGET_ROOT=/opt/z115-backoffice
DOCKER_DIR=/opt/z115-backoffice/deploy/docker
COMPOSE_FILE=docker-compose.offline.yml
ENV_FILE=.env.production
BACKUP_DIR=/opt/z115-backoffice/backups
RELEASE_DIR=/opt/z115-backoffice/releases
WEB_IMAGE=z115-backoffice-web
DB_SERVICE=db
WEB_SERVICE=web
NGINX_SERVICE=nginx
```

Nếu sau này đổi đường dẫn, chạy kiểu:

```bash
TARGET_ROOT=/duong/dan/khac \
/opt/z115-backoffice/scripts/z115_target_healthcheck_offline_v2.sh
```

---

## Lưu ý quan trọng

- Script máy đích **không cần source code Django**.
- Script máy đích **không dùng `/mnt/code/intranet`**.
- Script máy đích chỉ thao tác với Docker Compose tại `/opt/z115-backoffice/deploy/docker`.
- Script apply luôn backup DB trước khi update.
- Script không xóa Docker volume.
- Với rollback code-only, script chỉ đổi image tag, không restore DB.
