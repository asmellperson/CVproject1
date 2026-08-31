#!/usr/bin/env bash
# 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。


set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJECT_ROOT/scripts/lib/unified_backend_runtime.sh"

# 功能：实现 `fail` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
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

# 功能：实现 `assert_equals` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$1 / expected`（Shell 字符串）：`expected` 对应的业务输入值
#   - `$2 / actual`（Shell 字符串）：`actual` 对应的业务输入值
#   - `$3 / message`（Shell 字符串）：用于展示、记录或发送的文本消息
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/tests/test_unified_backend_runtime.sh` 的脚本流程调用本函数
#   - 内部调用：`fail`。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息。
assert_equals() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [[ "$actual" != "$expected" ]]; then
    fail "${message}: expected '${expected}', got '${actual}'"
  fi
}

# 功能：实现 `conda_env_exists` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$1 / env_name`（Shell 字符串）：`env_name` 对应的业务输入值
#   - `$2 / conda_sh`（Shell 字符串）：`conda_sh` 对应的业务输入值
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/lib/unified_backend_runtime.sh` 的脚本流程调用本函数；`scripts/migrate_visual_integrations.sh` 的脚本流程调用本函数；`scripts/start.sh`
#         的脚本流程调用本函数
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息。
conda_env_exists() {
  local env_name="$1"
  local conda_sh="$2"
  [[ "${FAKE_CONDA_ENV_EXISTS:-0}" == "1" ]] \
    && [[ "$env_name" == "unified_backend" ]] \
    && [[ "$conda_sh" == "/opt/conda/etc/profile.d/conda.sh" ]]
}

runtime="$(resolve_unified_backend_runtime \
  "/custom/python" \
  "/opt/conda/etc/profile.d/conda.sh" \
  "unified_backend" \
  "/usr/bin/python3")"
assert_equals \
  "/custom/python" \
  "$runtime" \
  "explicit Python must have highest priority"

FAKE_CONDA_ENV_EXISTS=1
runtime="$(resolve_unified_backend_runtime \
  "" \
  "/opt/conda/etc/profile.d/conda.sh" \
  "unified_backend" \
  "/usr/bin/python3")"
assert_equals \
  "source /opt/conda/etc/profile.d/conda.sh && conda activate unified_backend && python" \
  "$runtime" \
  "existing unified_backend Conda environment must be selected"

FAKE_CONDA_ENV_EXISTS=0
runtime="$(resolve_unified_backend_runtime \
  "" \
  "/opt/conda/etc/profile.d/conda.sh" \
  "unified_backend" \
  "/usr/bin/python3")"
assert_equals \
  "/usr/bin/python3" \
  "$runtime" \
  "system Python must remain a compatibility fallback"

if runtime="$(resolve_unified_backend_runtime "" "" "unified_backend" "")"; then
  fail "runtime resolution must fail when no Python runtime exists"
fi
assert_equals "" "$runtime" "failed runtime resolution must not emit a command"

help_output="$(bash "$PROJECT_ROOT/scripts/start.sh" --help)"
if [[ "$help_output" != *"bash scripts/start.sh"* ]]; then
  fail "start.sh help must show the actual startup script name"
fi
if [[ "$help_output" != *"scripts/start.env.example"* ]]; then
  fail "start.sh help must show the existing environment example filename"
fi

echo "PASS: unified backend runtime selection"
