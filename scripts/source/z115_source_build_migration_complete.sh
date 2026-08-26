#!/usr/bin/env bash
set -Eeuo pipefail

# =============================================================================
# Z115 Backoffice - SOURCE BUILD HOÀN CHỈNH CÓ MIGRATION
# Version: 2026-07-14 COMPLETE
#
# Chạy trên MÁY NGUỒN có source code:
#   /mnt/code/intranet
#
# Mục tiêu:
#   1. Chạy makemigrations/migrate/check trên DEV runserver SQLite nếu bật.
#   2. Build Docker image web mới từ code hiện tại.
#   3. Backup DB PostgreSQL Docker nguồn/staging.
#   4. Đẩy image mới sang Docker nguồn/staging.
#   5. Chạy migrate thử trên Docker nguồn PostgreSQL.
#   6. Đóng gói release .tar.gz có migration để mang sang máy đích offline.
#
# Release hợp lệ BẮT BUỘC phải có:
#   z115_update_xxx/
#   ├── images/z115-backoffice-web_TAG.tar
#   ├── deploy/docker/...
#   ├── RELEASE_INFO.txt
#   ├── APPLY_ON_TARGET.txt
#   └── CHECKSUMS.sha256
#
# Cách chạy:
#   cd /mnt/code/intranet/scripts/source
#   chmod +x z115_source_build_migration_complete.sh
#   ./z115_source_build_migration_complete.sh
#
# Nếu muốn đặt TAG riêng:
#   TAG=20260714_fix_hr_migration ./z115_source_build_migration_complete.sh
#
# Nếu muốn bỏ qua migrate DEV SQLite:
#   RUN_DEV_MAKEMIGRATIONS=0 RUN_DEV_MIGRATE=0 ./z115_source_build_migration_complete.sh
# =============================================================================

# ----------------------------
# 1. Cấu hình mặc định
# ----------------------------

PROJECT_DIR="${PROJECT_DIR:-/mnt/code/intranet}"
BACKEND_DIR="${BACKEND_DIR:-$PROJECT_DIR/backend}"
SOURCE_DOCKER_DIR="${SOURCE_DOCKER_DIR:-$PROJECT_DIR/deploy/docker}"
RELEASE_DIR="${RELEASE_DIR:-$PROJECT_DIR/releases}"
SOURCE_BACKUP_DIR="${SOURCE_BACKUP_DIR:-$PROJECT_DIR/backups}"

WEB_IMAGE="${WEB_IMAGE:-z115-backoffice-web}"
DOCKERFILE="${DOCKERFILE:-$PROJECT_DIR/deploy/docker/Dockerfile}"
SOURCE_ENV_FILE="${SOURCE_ENV_FILE:-$SOURCE_DOCKER_DIR/.env.production}"
SOURCE_COMPOSE_FILE="${SOURCE_COMPOSE_FILE:-}"

VENV_PATH="${VENV_PATH:-/home/appz115/.venvs/app/bin/activate}"
SOURCE_HTTP_URL="${SOURCE_HTTP_URL:-http://127.0.0.1}"

DB_SERVICE="${DB_SERVICE:-db}"
WEB_SERVICE="${WEB_SERVICE:-web}"
NGINX_SERVICE="${NGINX_SERVICE:-nginx}"

RUN_DEV_MAKEMIGRATIONS="${RUN_DEV_MAKEMIGRATIONS:-1}"
RUN_DEV_MIGRATE="${RUN_DEV_MIGRATE:-1}"
RUN_STAGING_DB_UP="${RUN_STAGING_DB_UP:-1}"
RUN_STAGING_BACKUP="${RUN_STAGING_BACKUP:-1}"
RUN_STAGING_WEB_UP="${RUN_STAGING_WEB_UP:-1}"
RUN_STAGING_MIGRATE="${RUN_STAGING_MIGRATE:-1}"
RUN_STAGING_CHECK="${RUN_STAGING_CHECK:-1}"
RESTART_SOURCE_NGINX="${RESTART_SOURCE_NGINX:-1}"

DOCKER_BUILD_NO_CACHE="${DOCKER_BUILD_NO_CACHE:-0}"

# Ngưỡng chống tạo release rác/quá nhỏ.
MIN_IMAGE_TAR_BYTES="${MIN_IMAGE_TAR_BYTES:-10000000}"     # 10 MB
MIN_ARCHIVE_BYTES="${MIN_ARCHIVE_BYTES:-1000000}"          # 1 MB

# TAG mặc định.
TAG="${TAG:-$(date +%Y%m%d_%H%M%S)-migration}"
TS="$(date +%Y%m%d_%H%M%S)"

UPDATE_NAME="z115_update_${TS}_${TAG}"
UPDATE_DIR="$RELEASE_DIR/$UPDATE_NAME"
ARCHIVE="$RELEASE_DIR/${UPDATE_NAME}.tar.gz"

SOURCE_COMPOSE_FILE_PATH=""
STAGING_BACKUP="SKIPPED"

# ----------------------------
# 2. Hàm tiện ích
# ----------------------------

log() {
  echo >&2
  echo "[$(date '+%F %T')] $*" >&2
}

die() {
  echo >&2
  echo "ERROR: $*" >&2
  exit 1
}

on_error() {
  local line="$1"
  echo >&2
  echo "============================================================"
  echo "LỖI: Script dừng tại line $line" >&2
  echo "TAG=$TAG" >&2
  echo "UPDATE_DIR=$UPDATE_DIR" >&2
  echo "ARCHIVE=$ARCHIVE" >&2
  echo "SOURCE_BACKUP_DIR=$SOURCE_BACKUP_DIR" >&2
  echo "Nếu lỗi xảy ra sau bước migrate Docker nguồn, xem backup staging tại:" >&2
  echo "  $STAGING_BACKUP" >&2
  echo "============================================================"
}
trap 'on_error $LINENO' ERR

require_dir() {
  [[ -d "$1" ]] || die "Không thấy thư mục: $1"
}

require_file() {
  [[ -f "$1" ]] || die "Không thấy file: $1"
}

check_write_dir() {
  local dir="$1"
  mkdir -p "$dir"
  local test_file="$dir/.z115_write_test_${TS}"
  touch "$test_file" || die "Không có quyền ghi vào thư mục: $dir"
  rm -f "$test_file"
}

file_size() {
  stat -c%s "$1"
}

detect_compose_file() {
  if [[ -n "$SOURCE_COMPOSE_FILE" ]]; then
    if [[ "$SOURCE_COMPOSE_FILE" = /* ]]; then
      [[ -f "$SOURCE_COMPOSE_FILE" ]] || die "Không thấy SOURCE_COMPOSE_FILE=$SOURCE_COMPOSE_FILE"
      printf '%s\n' "$SOURCE_COMPOSE_FILE"
    else
      [[ -f "$SOURCE_DOCKER_DIR/$SOURCE_COMPOSE_FILE" ]] || die "Không thấy SOURCE_COMPOSE_FILE=$SOURCE_DOCKER_DIR/$SOURCE_COMPOSE_FILE"
      printf '%s\n' "$SOURCE_DOCKER_DIR/$SOURCE_COMPOSE_FILE"
    fi
    return 0
  fi

  for f in \
    "$SOURCE_DOCKER_DIR/docker-compose.yml" \
    "$SOURCE_DOCKER_DIR/docker-compose.yaml" \
    "$SOURCE_DOCKER_DIR/docker-compose.offline.yml" \
    "$SOURCE_DOCKER_DIR/compose.yml" \
    "$SOURCE_DOCKER_DIR/compose.yaml"; do
    if [[ -f "$f" ]]; then
      printf '%s\n' "$f"
      return 0
    fi
  done

  die "Không tìm thấy docker compose file trong $SOURCE_DOCKER_DIR"
}

compose_source() {
  cd "$SOURCE_DOCKER_DIR"

  if [[ -f "$SOURCE_ENV_FILE" ]]; then
    docker compose --env-file "$SOURCE_ENV_FILE" -f "$SOURCE_COMPOSE_FILE_PATH" "$@"
  else
    docker compose -f "$SOURCE_COMPOSE_FILE_PATH" "$@"
  fi
}

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"

  touch "$file"

  if grep -qE "^${key}=" "$file"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|g" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

wait_for_db() {
  log "Chờ PostgreSQL Docker nguồn sẵn sàng"

  local ok=0

  for i in $(seq 1 60); do
    if compose_source exec -T "$DB_SERVICE" \
      sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
      ok=1
      break
    fi

    echo "  DB chưa sẵn sàng, đợi lần $i/60..." >&2
    sleep 2
  done

  [[ "$ok" == "1" ]] || die "PostgreSQL Docker nguồn chưa sẵn sàng sau khi chờ"
}

backup_staging_db() {
  local out_file="$1"

  log "Backup DB Docker nguồn/staging trước khi migrate thử"
  echo "Backup file: $out_file" >&2

  mkdir -p "$(dirname "$out_file")"

  compose_source exec -T "$DB_SERVICE" \
    sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' \
    > "$out_file"

  [[ -f "$out_file" ]] || die "Không tạo được backup DB staging: $out_file"
  [[ -s "$out_file" ]] || die "Backup DB staging bị rỗng: $out_file"

  ls -lh "$out_file" >&2
}

update_source_tag_reference() {
  local tag="$1"

  log "Cập nhật TAG trong Docker nguồn"

  if [[ -f "$SOURCE_ENV_FILE" ]]; then
    cp "$SOURCE_ENV_FILE" "$SOURCE_ENV_FILE.before_${TS}" || true
  fi

  set_env_value "$SOURCE_ENV_FILE" "TAG" "$tag"
  set_env_value "$SOURCE_ENV_FILE" "WEB_IMAGE_TAG" "$tag"

  cp "$SOURCE_COMPOSE_FILE_PATH" "$SOURCE_COMPOSE_FILE_PATH.before_${TS}" || true

  # Nếu compose hard-code dạng image: z115-backoffice-web:oldtag thì sửa trực tiếp.
  sed -i -E "s|(image:[[:space:]]*${WEB_IMAGE}:)[^[:space:]#]+|\1${tag}|g" "$SOURCE_COMPOSE_FILE_PATH" || true

  echo "Compose image lines:" >&2
  grep -nE "image:.*${WEB_IMAGE}" "$SOURCE_COMPOSE_FILE_PATH" >&2 || true

  echo "Env TAG lines:" >&2
  grep -nE "^(TAG|WEB_IMAGE_TAG)=" "$SOURCE_ENV_FILE" >&2 || true
}

docker_build_image() {
  log "Build Docker image: ${WEB_IMAGE}:${TAG}"

  cd "$PROJECT_DIR"

  local build_args=()
  if [[ "$DOCKER_BUILD_NO_CACHE" == "1" ]]; then
    build_args+=(--no-cache)
  fi

  docker build \
    "${build_args[@]}" \
    -t "${WEB_IMAGE}:${TAG}" \
    -f "$DOCKERFILE" \
    "$PROJECT_DIR"

  docker image inspect "${WEB_IMAGE}:${TAG}" >/dev/null 2>&1 \
    || die "Build xong nhưng không thấy image ${WEB_IMAGE}:${TAG}"

  docker images "${WEB_IMAGE}:${TAG}" >&2
}

save_image_strict() {
  local tag="$1"
  local out_file="$2"

  log "Docker save image vào release"
  echo "Image: ${WEB_IMAGE}:${tag}" >&2
  echo "Output: $out_file" >&2

  docker image inspect "${WEB_IMAGE}:${tag}" >/dev/null 2>&1 \
    || die "Không thấy image ${WEB_IMAGE}:${tag}"

  docker save "${WEB_IMAGE}:${tag}" -o "$out_file"

  [[ -f "$out_file" ]] || die "docker save không tạo được file: $out_file"
  [[ -s "$out_file" ]] || die "docker save tạo file rỗng: $out_file"

  local sz
  sz="$(file_size "$out_file")"

  log "Dung lượng image tar: $sz bytes"

  if (( sz < MIN_IMAGE_TAR_BYTES )); then
    die "Image tar quá nhỏ ($sz bytes). Ngưỡng tối thiểu MIN_IMAGE_TAR_BYTES=$MIN_IMAGE_TAR_BYTES. Không tạo release."
  fi
}

write_release_files() {
  local dir="$1"

  cat > "$dir/RELEASE_INFO.txt" <<EOF
Z115 Backoffice Update
Type=Code with migration
TAG=${TAG}
CreatedAt=${TS}
BuiltOn=$(hostname)
SourceProject=${PROJECT_DIR}
SourceBackend=${BACKEND_DIR}
SourceDockerDir=${SOURCE_DOCKER_DIR}
SourceCompose=${SOURCE_COMPOSE_FILE_PATH}
SourceEnv=${SOURCE_ENV_FILE}
StagingBackup=${STAGING_BACKUP}
WebImage=${WEB_IMAGE}:${TAG}

Target default:
- TARGET_ROOT=/opt/z115-backoffice
- COMPOSE=/opt/z115-backoffice/deploy/docker/docker-compose.offline.yml
- ENV=/opt/z115-backoffice/deploy/docker/.env.production

Rules:
- Backup target DB before migrate.
- Load image before changing TAG.
- Run migrate only after image loaded and web started.
- Do not reset PostgreSQL volume.
- Do not import source DB into target production DB.
EOF

  cat > "$dir/APPLY_ON_TARGET.txt" <<EOF
Copy file release sang máy đích:

scp "$ARCHIVE" appz115@172.17.17.30:/home/appz115/

Trên máy đích:

sudo mkdir -p /opt/z115-backoffice/releases
sudo mv /home/appz115/$(basename "$ARCHIVE") /opt/z115-backoffice/releases/
sudo chown -R appz115:appz115 /opt/z115-backoffice/releases

Chạy apply migration:

/opt/z115-backoffice/scripts/z115_target_apply_migration_offline_v3.sh \\
  /opt/z115-backoffice/releases/$(basename "$ARCHIVE")
EOF
}

make_checksums() {
  local dir="$1"

  log "Tạo CHECKSUMS.sha256"

  (
    cd "$dir"
    find . -type f ! -name "CHECKSUMS.sha256" -print0 \
      | sort -z \
      | xargs -0 sha256sum > CHECKSUMS.sha256
  )
}

verify_release_dir() {
  local dir="$1"

  log "Verify thư mục release trước khi nén"

  [[ -d "$dir/images" ]] || die "Thiếu thư mục images trong release"
  [[ -f "$dir/images/${WEB_IMAGE}_${TAG}.tar" ]] || die "Thiếu image tar trong release"
  [[ -s "$dir/images/${WEB_IMAGE}_${TAG}.tar" ]] || die "Image tar trong release rỗng"
  [[ -f "$dir/RELEASE_INFO.txt" ]] || die "Thiếu RELEASE_INFO.txt"
  [[ -f "$dir/APPLY_ON_TARGET.txt" ]] || die "Thiếu APPLY_ON_TARGET.txt"
  [[ -f "$dir/CHECKSUMS.sha256" ]] || die "Thiếu CHECKSUMS.sha256"

  find "$dir" -maxdepth 4 -type f -printf "%p\t%k KB\n" | sort >&2
}

create_archive_strict() {
  local update_name="$1"
  local archive="$2"

  log "Nén release thành tar.gz"
  cd "$RELEASE_DIR"

  rm -f "$archive"
  tar -czf "$archive" "$update_name"

  [[ -f "$archive" ]] || die "Không tạo được archive: $archive"
  [[ -s "$archive" ]] || die "Archive rỗng: $archive"

  local asz
  asz="$(file_size "$archive")"

  log "Dung lượng archive: $asz bytes"

  if (( asz < MIN_ARCHIVE_BYTES )); then
    die "Archive quá nhỏ ($asz bytes). Có khả năng thiếu Docker image. Không cho phát hành."
  fi

  log "Verify archive có image tar"
  tar -tzf "$archive" | grep -E "^${update_name}/images/${WEB_IMAGE}_${TAG}\.tar$" >/dev/null \
    || die "Archive không chứa ${update_name}/images/${WEB_IMAGE}_${TAG}.tar"

  log "Nội dung đầu archive"
  tar -tzf "$archive" | head -100 >&2
}

copy_source_configs_to_release() {
  local dir="$1"

  log "Copy cấu hình deploy/docker vào release"

  cp "$SOURCE_DOCKER_DIR"/*.yml "$dir/deploy/docker/" 2>/dev/null || true
  cp "$SOURCE_DOCKER_DIR"/*.yaml "$dir/deploy/docker/" 2>/dev/null || true

  if [[ -f "$SOURCE_ENV_FILE" ]]; then
    cp "$SOURCE_ENV_FILE" "$dir/deploy/docker/.env.production"
  fi

  if [[ -d "$SOURCE_DOCKER_DIR/nginx" ]]; then
    tar -C "$SOURCE_DOCKER_DIR" -czf "$dir/deploy/docker/nginx_config.tar.gz" nginx
  fi
}

collect_staging_logs() {
  local dir="$1"

  log "Ghi log Docker nguồn/staging vào release/logs"

  compose_source ps > "$dir/logs/docker_compose_ps.txt" 2>&1 || true
  compose_source logs --tail=200 "$WEB_SERVICE" > "$dir/logs/web.log" 2>&1 || true
  compose_source logs --tail=100 "$NGINX_SERVICE" > "$dir/logs/nginx.log" 2>&1 || true
  compose_source logs --tail=100 "$DB_SERVICE" > "$dir/logs/db.log" 2>&1 || true

  docker images "${WEB_IMAGE}" > "$dir/logs/docker_images_web.txt" 2>&1 || true
}

# ----------------------------
# 3. Kiểm tra môi trường
# ----------------------------

log "Thông tin cấu hình build migration"
echo "PROJECT_DIR=$PROJECT_DIR" >&2
echo "BACKEND_DIR=$BACKEND_DIR" >&2
echo "SOURCE_DOCKER_DIR=$SOURCE_DOCKER_DIR" >&2
echo "RELEASE_DIR=$RELEASE_DIR" >&2
echo "SOURCE_BACKUP_DIR=$SOURCE_BACKUP_DIR" >&2
echo "WEB_IMAGE=$WEB_IMAGE" >&2
echo "DOCKERFILE=$DOCKERFILE" >&2
echo "SOURCE_ENV_FILE=$SOURCE_ENV_FILE" >&2
echo "TAG=$TAG" >&2
echo "RUN_DEV_MAKEMIGRATIONS=$RUN_DEV_MAKEMIGRATIONS" >&2
echo "RUN_DEV_MIGRATE=$RUN_DEV_MIGRATE" >&2
echo "RUN_STAGING_MIGRATE=$RUN_STAGING_MIGRATE" >&2

require_dir "$PROJECT_DIR"
require_dir "$BACKEND_DIR"
require_dir "$SOURCE_DOCKER_DIR"
require_file "$DOCKERFILE"

SOURCE_COMPOSE_FILE_PATH="$(detect_compose_file)"
require_file "$SOURCE_COMPOSE_FILE_PATH"
echo "SOURCE_COMPOSE_FILE_PATH=$SOURCE_COMPOSE_FILE_PATH" >&2

check_write_dir "$RELEASE_DIR"
check_write_dir "$SOURCE_BACKUP_DIR"

command -v docker >/dev/null 2>&1 || die "Không thấy docker trong PATH"
docker compose version >/dev/null 2>&1 || die "docker compose chưa sẵn sàng"

# ----------------------------
# 4. DEV SQLite - migration/check
# ----------------------------

log "DEV SQLite - makemigrations/migrate/check"
cd "$BACKEND_DIR"

if [[ -f "$VENV_PATH" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_PATH"
else
  log "Không thấy venv tại $VENV_PATH, dùng python hiện tại trong PATH"
fi

python --version >&2
python manage.py check

if [[ "$RUN_DEV_MAKEMIGRATIONS" == "1" ]]; then
  python manage.py makemigrations
else
  log "Bỏ qua makemigrations DEV"
fi

if [[ "$RUN_DEV_MIGRATE" == "1" ]]; then
  python manage.py migrate
else
  log "Bỏ qua migrate DEV"
fi

python manage.py check

log "Migration files gần nhất"
find . -path "*/migrations/*.py" -not -name "__init__.py" -printf "%TY-%Tm-%Td %TT %p\n" \
  | sort \
  | tail -50 >&2 || true

# ----------------------------
# 5. Build Docker image
# ----------------------------

docker_build_image

# ----------------------------
# 6. Docker nguồn/staging PostgreSQL
# ----------------------------

if [[ "$RUN_STAGING_DB_UP" == "1" ]]; then
  log "Đảm bảo DB Docker nguồn đang chạy"
  compose_source up -d "$DB_SERVICE"
  wait_for_db
fi

if [[ "$RUN_STAGING_BACKUP" == "1" ]]; then
  STAGING_BACKUP="$SOURCE_BACKUP_DIR/staging_db_before_migration_${TS}.dump"
  backup_staging_db "$STAGING_BACKUP"
else
  log "Bỏ qua backup staging DB"
fi

update_source_tag_reference "$TAG"

if [[ "$RUN_STAGING_WEB_UP" == "1" ]]; then
  log "Chạy web Docker nguồn bằng image mới"
  compose_source up -d --no-deps "$WEB_SERVICE"
fi

if [[ "$RUN_STAGING_MIGRATE" == "1" ]]; then
  log "Migrate thử trên Docker nguồn PostgreSQL"
  compose_source exec "$WEB_SERVICE" python manage.py showmigrations || true
  compose_source exec "$WEB_SERVICE" python manage.py migrate
else
  log "Bỏ qua migrate staging"
fi

if [[ "$RUN_STAGING_CHECK" == "1" ]]; then
  log "Django check trên Docker nguồn"
  compose_source exec "$WEB_SERVICE" python manage.py check
fi

if [[ "$RESTART_SOURCE_NGINX" == "1" ]]; then
  log "Restart nginx Docker nguồn"
  compose_source restart "$NGINX_SERVICE" || true
fi

compose_source ps >&2
command -v curl >/dev/null 2>&1 && curl -I "$SOURCE_HTTP_URL" >&2 || true

# ----------------------------
# 7. Đóng gói release
# ----------------------------

log "Tạo release migration hoàn chỉnh"

rm -rf "$UPDATE_DIR"
mkdir -p "$UPDATE_DIR/images" "$UPDATE_DIR/deploy/docker" "$UPDATE_DIR/logs"

save_image_strict "$TAG" "$UPDATE_DIR/images/${WEB_IMAGE}_${TAG}.tar"
copy_source_configs_to_release "$UPDATE_DIR"
collect_staging_logs "$UPDATE_DIR"
write_release_files "$UPDATE_DIR"
make_checksums "$UPDATE_DIR"
verify_release_dir "$UPDATE_DIR"
create_archive_strict "$UPDATE_NAME" "$ARCHIVE"

# ----------------------------
# 8. Kết quả
# ----------------------------

log "HOÀN TẤT BUILD MIGRATION RELEASE"
echo "TAG=$TAG"
echo "UPDATE_DIR=$UPDATE_DIR"
echo "RELEASE=$ARCHIVE"
echo "STAGING_BACKUP=$STAGING_BACKUP"
echo
echo "Kiểm tra nhanh:"
echo "  ls -lh \"$ARCHIVE\""
echo "  tar -tzf \"$ARCHIVE\" | head -100"
echo
echo "Copy sang máy đích:"
echo "  scp \"$ARCHIVE\" appz115@172.17.17.30:/home/appz115/"
