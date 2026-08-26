#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_ROOT="${TARGET_ROOT:-/opt/z115-backoffice}"
SCRIPTS_DIR="${SCRIPTS_DIR:-$TARGET_ROOT/scripts}"

mkdir -p "$SCRIPTS_DIR"

cp target/*.sh "$SCRIPTS_DIR/"

chmod +x "$SCRIPTS_DIR"/*.sh

echo "Đã copy target scripts vào: $SCRIPTS_DIR"
ls -lh "$SCRIPTS_DIR"/*.sh
