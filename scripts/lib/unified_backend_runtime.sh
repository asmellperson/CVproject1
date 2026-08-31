#!/usr/bin/env bash
# 文件说明：提供运行时的命令行运维或验证流程。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。


# 功能：计算或解析 `resolve_unified_backend_runtime` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$1 / explicit_python`（Shell 字符串）：`explicit_python` 对应的业务输入值
#   - `$2 / conda_sh`（Shell 字符串）：`conda_sh` 对应的业务输入值
#   - `$3 / conda_env`（Shell 字符串）：`conda_env` 对应的业务输入值
#   - `$4 / system_python`（Shell 字符串）：`system_python` 对应的业务输入值
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/start.sh` 的脚本流程调用本函数；`scripts/tests/test_unified_backend_runtime.sh` 的脚本流程调用本函数
#   - 内部调用：`conda_env_exists`。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；失败时通过 Shell 返回码影响上层流程。
resolve_unified_backend_runtime() {
  local explicit_python="$1"
  local conda_sh="$2"
  local conda_env="$3"
  local system_python="$4"

  if [[ -n "$explicit_python" ]]; then
    printf '%s' "$explicit_python"
    return 0
  fi

  if [[ -n "$conda_sh" ]] \
    && [[ -n "$conda_env" ]] \
    && conda_env_exists "$conda_env" "$conda_sh"; then
    printf 'source %q && conda activate %q && python' "$conda_sh" "$conda_env"
    return 0
  fi

  if [[ -n "$system_python" ]]; then
    printf '%s' "$system_python"
    return 0
  fi

  return 1
}
