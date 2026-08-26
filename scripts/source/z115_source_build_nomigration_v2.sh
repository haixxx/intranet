#!/usr/bin/env bash
set -Eeuo pipefail

# ==========================================================
# Z115 Backoffice - SOURCE script
# Chạy trên máy nguồn Oracle Ubuntu có Internet.
# Máy nguồn có source code tại /mnt/code/intranet.
# ==========================================================

PROJECT_DIR="${PROJECT_DIR:-/mnt/code/intranet}"
BACKEND_DIR="${BACKEND_DIR:-$PROJECT_DIR/backend}"
SOURCE_DOCKER_DIR="${SOURCE_DOCKER_DIR:-$PROJECT_DIR/deploy/docker}"
RELEASE_DIR="${RELEASE_DIR:-$PROJECT_DIR/releases}"
SOURCE_BACKUP_DIR="${SOURCE_BACKUP_DIR:-$PROJECT_DIR/backups}"
WEB_IMAGE="${WEB_IMAGE:-z115-backoffice-web}"
DOCKERFILE="${DOCKERFILE:-$PROJECT_DIR/deploy/docker/Dockerfile}"
SOURCE_ENV_FILE="${SOURCE_ENV_FILE:-$SOURCE_DOCKER_DIR/.env.production}"
VENV_PATH="${VENV_PATH:-/home/appz115/.venvs/app/bin/activate}"
SOURCE_HTTP_URL="${SOURCE_HTTP_URL:-http://127.0.0.1}"

log() {
  echo
  echo "[$(date '+%F %T')] $*"
}

die() {
  echo
  echo "ERROR: $*" >&2
  exit 1
}

require_dir() {
  [[ -d "$1" ]] || die "Không thấy thư mục: $1"
}

require_file() {
  [[ -f "$1" ]] || die "Không thấy file: $1"
}

compose_source() {
  cd "$SOURCE_DOCKER_DIR"

  if [[ -f "$SOURCE_ENV_FILE" ]]; then
    docker compose --env-file "$SOURCE_ENV_FILE" "$@"
  else
    docker compose "$@"
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

update_source_tag_reference() {
  local tag="$1"

  if [[ -f "$SOURCE_ENV_FILE" ]]; then
    cp "$SOURCE_ENV_FILE" "$SOURCE_ENV_FILE.before_${TS}"
    set_env_value "$SOURCE_ENV_FILE" "TAG" "$tag"
    set_env_value "$SOURCE_ENV_FILE" "WEB_IMAGE_TAG" "$tag"
  else
    set_env_value "$SOURCE_ENV_FILE" "TAG" "$tag"
    set_env_value "$SOURCE_ENV_FILE" "WEB_IMAGE_TAG" "$tag"
  fi

  # Nếu compose nguồn đang hard-code image tag thì sửa trực tiếp.
  local compose_file=""
  for f in "$SOURCE_DOCKER_DIR/docker-compose.yml" "$SOURCE_DOCKER_DIR/docker-compose.yaml" "$SOURCE_DOCKER_DIR/compose.yml" "$SOURCE_DOCKER_DIR/compose.yaml"; do
    [[ -f "$f" ]] && compose_file="$f" && break
  done

  if [[ -n "$compose_file" ]]; then
    cp "$compose_file" "$compose_file.before_${TS}"
    sed -i -E "s|(image:[[:space:]]*${WEB_IMAGE}:)[^[:space:]#]+|\1${tag}|g" "$compose_file" || true
  fi
}

load_source_pg_vars() {
  if [[ -f "$SOURCE_ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$SOURCE_ENV_FILE"
    set +a
  fi

  POSTGRES_USER="${POSTGRES_USER:-${DB_USER:-}}"
  POSTGRES_DB="${POSTGRES_DB:-${DB_NAME:-}}"

  [[ -n "${POSTGRES_USER:-}" ]] || die "Không xác định được POSTGRES_USER/DB_USER từ $SOURCE_ENV_FILE"
  [[ -n "${POSTGRES_DB:-}" ]] || die "Không xác định được POSTGRES_DB/DB_NAME từ $SOURCE_ENV_FILE"
}

TAG="${TAG:-$(date +%Y%m%d_%H%M%S)-nomigrate}"
TS="$(date +%Y%m%d_%H%M%S)"
UPDATE_DIR="$RELEASE_DIR/z115_update_${TS}_${TAG}"
ARCHIVE="$RELEASE_DIR/z115_update_${TS}_${TAG}.tar.gz"

log "Thông tin máy nguồn"
echo "PROJECT_DIR=$PROJECT_DIR"
echo "BACKEND_DIR=$BACKEND_DIR"
echo "SOURCE_DOCKER_DIR=$SOURCE_DOCKER_DIR"
echo "RELEASE_DIR=$RELEASE_DIR"
echo "WEB_IMAGE=$WEB_IMAGE"
echo "TAG=$TAG"

require_dir "$PROJECT_DIR"
require_dir "$BACKEND_DIR"
require_dir "$SOURCE_DOCKER_DIR"
require_file "$DOCKERFILE"

mkdir -p "$RELEASE_DIR"

log "Kiểm tra Django DEV và chắc chắn không có migration mới"
cd "$BACKEND_DIR"

if [[ -f "$VENV_PATH" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_PATH"
else
  log "Không thấy venv tại $VENV_PATH, dùng python hiện tại trong PATH"
fi

python manage.py check
python manage.py makemigrations --check --dry-run

log "Build Docker image"
cd "$PROJECT_DIR"

docker build \
  -t "${WEB_IMAGE}:${TAG}" \
  -f "$DOCKERFILE" \
  "$PROJECT_DIR"

log "Cập nhật TAG trên Docker nguồn staging"
update_source_tag_reference "$TAG"

log "Chạy thử Docker nguồn"
compose_source up -d --no-deps web
compose_source restart nginx || true

compose_source ps
compose_source logs --tail=120 web || true
compose_source logs --tail=80 nginx || true

if command -v curl >/dev/null 2>&1; then
  curl -I "$SOURCE_HTTP_URL" || true
fi

log "Đóng gói release code-only"
mkdir -p "$UPDATE_DIR/images" "$UPDATE_DIR/deploy/docker" "$UPDATE_DIR/logs"

docker save \
  "${WEB_IMAGE}:${TAG}" \
  -o "$UPDATE_DIR/images/${WEB_IMAGE}_${TAG}.tar"

# Copy thêm file compose/env nguồn để lưu vết, máy đích không nhất thiết dùng trực tiếp.
cp "$SOURCE_DOCKER_DIR"/*.yml "$UPDATE_DIR/deploy/docker/" 2>/dev/null || true
cp "$SOURCE_DOCKER_DIR"/*.yaml "$UPDATE_DIR/deploy/docker/" 2>/dev/null || true
cp "$SOURCE_ENV_FILE" "$UPDATE_DIR/deploy/docker/.env.production" 2>/dev/null || true

cat > "$UPDATE_DIR/RELEASE_INFO.txt" <<EOF
Z115 Backoffice Update
Type=Code only - No migration
TAG=${TAG}
CreatedAt=${TS}
BuiltOn=$(hostname)

Target default:
- TARGET_ROOT=/opt/z115-backoffice
- COMPOSE=/opt/z115-backoffice/deploy/docker/docker-compose.offline.yml
- ENV=/opt/z115-backoffice/deploy/docker/.env.production

Rules:
- No makemigrations on production
- No migrate on production
- No DB import from source to target
- No PostgreSQL volume reset
EOF

cat > "$UPDATE_DIR/APPLY_ON_TARGET.txt" <<EOF
Trên máy đích chạy:

/opt/z115-backoffice/scripts/z115_target_apply_nomigration_offline_v2.sh \\
  /opt/z115-backoffice/releases/$(basename "$ARCHIVE")
EOF

cd "$RELEASE_DIR"
tar -czf "$ARCHIVE" "z115_update_${TS}_${TAG}"

log "HOÀN TẤT"
echo "TAG=$TAG"
echo "RELEASE=$ARCHIVE"
echo
echo "Copy sang máy đích:"
echo "scp \"$ARCHIVE\" appz115@172.17.17.30:/opt/z115-backoffice/releases/"
