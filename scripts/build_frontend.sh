#!/usr/bin/env bash
# 原子构建 unified_frontend/dist，供生产 Nginx 静态托管。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${FUDA_CVP_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FRONTEND_DIR="${UNIFIED_FRONTEND_DIR:-${PROJECT_ROOT}/unified_frontend}"
DIST_DIR="${FRONTEND_DIR}/dist"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

[[ -f "${FRONTEND_DIR}/package.json" ]] || fail "缺少 ${FRONTEND_DIR}/package.json"
[[ -f "${FRONTEND_DIR}/package-lock.json" ]] || fail "缺少 package-lock.json，无法保证前端依赖可复现"
[[ -d "${FRONTEND_DIR}/node_modules" ]] || fail "缺少 node_modules，请先执行: cd ${FRONTEND_DIR} && npm ci"
command -v npm >/dev/null 2>&1 || fail "未找到 npm"

BUILD_DIR="$(mktemp -d "${FRONTEND_DIR}/.dist-build.XXXXXX")"
BACKUP_DIR="${FRONTEND_DIR}/.dist-backup.$$"

safe_remove_generated_dir() {
  local target="$1"
  case "$target" in
    "${FRONTEND_DIR}"/.dist-build.*|"${FRONTEND_DIR}"/.dist-backup.*)
      rm -rf -- "$target"
      ;;
    *)
      fail "拒绝清理非构建目录: ${target}"
      ;;
  esac
}

cleanup() {
  if [[ -d "$BUILD_DIR" ]]; then
    safe_remove_generated_dir "$BUILD_DIR"
  fi
  if [[ -e "$BACKUP_DIR" || -L "$BACKUP_DIR" ]]; then
    if [[ ! -e "$DIST_DIR" && ! -L "$DIST_DIR" ]]; then
      mv -- "$BACKUP_DIR" "$DIST_DIR"
    else
      safe_remove_generated_dir "$BACKUP_DIR"
    fi
  fi
}
trap cleanup EXIT INT TERM

(
  cd "$FRONTEND_DIR"
  npm run build -- --outDir "$BUILD_DIR" --emptyOutDir
)

[[ -s "${BUILD_DIR}/index.html" ]] || fail "构建结果缺少 index.html，保留现有 dist"

if [[ -e "$DIST_DIR" || -L "$DIST_DIR" ]]; then
  mv -- "$DIST_DIR" "$BACKUP_DIR"
fi

if ! mv -- "$BUILD_DIR" "$DIST_DIR"; then
  if [[ -e "$BACKUP_DIR" || -L "$BACKUP_DIR" ]]; then
    mv -- "$BACKUP_DIR" "$DIST_DIR"
  fi
  fail "切换新 dist 失败，已恢复旧版本"
fi

if [[ -e "$BACKUP_DIR" || -L "$BACKUP_DIR" ]]; then
  safe_remove_generated_dir "$BACKUP_DIR"
fi
trap - EXIT INT TERM

echo "[ OK ] 前端生产构建已原子发布到 ${DIST_DIR}"
