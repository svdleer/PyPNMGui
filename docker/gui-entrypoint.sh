#!/usr/bin/env sh
set -eu

APP_UID="10001"
APP_GID="10001"
DATA_DIR="/app/data"
LOG_DIR="/app/logs"

mkdir -p "${DATA_DIR}" "${LOG_DIR}"

# Keep volume-backed directories writable for the runtime user.
chown -R "${APP_UID}:${APP_GID}" "${DATA_DIR}" "${LOG_DIR}" || true
chmod -R u+rwX,g+rX "${DATA_DIR}" "${LOG_DIR}" || true

exec gosu "${APP_UID}:${APP_GID}" "$@"
