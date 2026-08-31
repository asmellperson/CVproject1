#!/usr/bin/env bash
# 文件说明：提供`build_frontend` 模块的命令行运维或验证流程。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# 可选：原子构建 unified_frontend/dist，用于手动检查生产构建产物。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${FUDA_CVP_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FRONTEND_DIR="${UNIFIED_FRONTEND_DIR:-${PROJECT_ROOT}/unified_frontend}"
DIST_DIR="${FRONTEND_DIR}/dist"

# 功能：实现 `fail` 对应的`build_frontend` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/build_frontend.sh` 的脚本流程调用本函数；`scripts/start.sh` 的脚本流程调用本函数；`scripts/tests/test_frontend_build.sh`
#         的脚本流程调用本函数；`scripts/tests/test_service_topology.sh` 的脚本流程调用本函数；另有 2 处调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
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

# 功能：删除或清理 `safe_remove_generated_dir` 对应的`build_frontend` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$1 / target`（Shell 字符串）：`target` 对应的业务输入值
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/build_frontend.sh` 的脚本流程调用本函数
#   - 内部调用：`fail`。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息。
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

# 功能：删除或清理 `cleanup` 对应的`build_frontend` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/build_frontend.sh` 的脚本流程调用本函数；`scripts/tests/test_frontend_build.sh` 的脚本流程调用本函数
#   - 内部调用：`safe_remove_generated_dir`。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限。
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
