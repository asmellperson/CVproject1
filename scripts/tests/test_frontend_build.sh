#!/usr/bin/env bash
# 文件说明：包含`test_frontend_build` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。


set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
FRONTEND_DIR="${TMP_DIR}/unified_frontend"
FAKE_BIN="${TMP_DIR}/bin"

# 功能：删除或清理 `cleanup` 对应的`test_frontend_build` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/build_frontend.sh` 的脚本流程调用本函数；`scripts/tests/test_frontend_build.sh` 的脚本流程调用本函数
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息。
cleanup() {
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT INT TERM

# 功能：实现 `fail` 对应的`test_frontend_build` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/build_frontend.sh` 的脚本流程调用本函数；`scripts/start.sh` 的脚本流程调用本函数；`scripts/tests/test_frontend_build.sh`
#         的脚本流程调用本函数；`scripts/tests/test_service_topology.sh` 的脚本流程调用本函数；另有 2 处调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mkdir -p "$FRONTEND_DIR/node_modules" "$FRONTEND_DIR/dist" "$FAKE_BIN"
printf '{}\n' > "${FRONTEND_DIR}/package.json"
printf '{}\n' > "${FRONTEND_DIR}/package-lock.json"
printf 'old\n' > "${FRONTEND_DIR}/dist/old.txt"

cat > "${FAKE_BIN}/npm" <<'EOF'
#!/usr/bin/env bash
set -u
if [[ "${FAKE_NPM_FAIL:-0}" == "1" ]]; then
  exit 17
fi
out_dir=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--outDir" ]]; then
    out_dir="$2"
    shift 2
  else
    shift
  fi
done
[[ -n "$out_dir" ]] || exit 18
mkdir -p "$out_dir/assets"
printf 'new\n' > "$out_dir/index.html"
printf 'asset\n' > "$out_dir/assets/app.js"
EOF
chmod +x "${FAKE_BIN}/npm"

PATH="${FAKE_BIN}:$PATH" \
UNIFIED_FRONTEND_DIR="$FRONTEND_DIR" \
bash "${PROJECT_ROOT}/scripts/build_frontend.sh" >/dev/null

[[ -s "${FRONTEND_DIR}/dist/index.html" ]] || fail "new index.html was not published"
[[ -s "${FRONTEND_DIR}/dist/assets/app.js" ]] || fail "new assets were not published"
[[ ! -e "${FRONTEND_DIR}/dist/old.txt" ]] || fail "old dist remained after the atomic switch"
if find "$FRONTEND_DIR" -maxdepth 1 \( -name '.dist-build.*' -o -name '.dist-backup.*' \) | grep -q .; then
  fail "temporary build directories were not cleaned"
fi

printf 'stable\n' > "${FRONTEND_DIR}/dist/stable.txt"
if PATH="${FAKE_BIN}:$PATH" \
  FAKE_NPM_FAIL=1 \
  UNIFIED_FRONTEND_DIR="$FRONTEND_DIR" \
  bash "${PROJECT_ROOT}/scripts/build_frontend.sh" >/dev/null 2>&1; then
  fail "failed npm build must return non-zero"
fi
[[ -s "${FRONTEND_DIR}/dist/stable.txt" ]] || fail "failed build replaced the stable dist"

echo "PASS: atomic production frontend build"
