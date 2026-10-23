#!/usr/bin/env bash
# 文件说明：提供`stop` 模块的命令行运维或验证流程。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# =============================================================================
# 福达视觉平台 - 一键关停脚本
# -----------------------------------------------------------------------------
# 作用：先等待后端已接收请求结束，再关停当前 2 个 tmux 服务。
# 用法：
#   bash scripts/stop.sh            # 关停全部服务
#   bash scripts/stop.sh -y         # 跳过确认，直接关停
# 注意：这是破坏性操作，会让线上服务下线。
#
# 关于 AUTH_SECRET：
#   本脚本只关停 tmux 会话，不会动 scripts/auth_secret 文件。
#   下次 start.sh 会复用同一密钥，用户登录态保持不变。
#   如需强制刷新密钥（会踢所有用户下线）：rm scripts/auth_secret
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$SCRIPT_DIR/cold_start.env" ]] && source "$SCRIPT_DIR/cold_start.env"
source "$SCRIPT_DIR/service_control.sh"

SERVICES=(aivision unified_frontend)

if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_DIM=""; C_RST=""
fi

YES=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) YES=1 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "${C_RED}[FAIL]${C_RST} 未知参数: $arg"; exit 2 ;;
  esac
done

# 列出当前存在的会话
RUNNING=()
for s in "${SERVICES[@]}"; do
  if tmux has-session -t "$s" 2>/dev/null; then
    RUNNING+=("$s")
  fi
done

if [[ ${#RUNNING[@]} -eq 0 ]]; then
  echo "${C_GRN}[ OK ]${C_RST} 没有需要关停的服务"
  exit 0
fi

echo "${C_YLW}[WARN]${C_RST} 即将关停以下 tmux 会话："
for s in "${RUNNING[@]}"; do echo "        - $s"; done
echo "${C_RED}[WARN]${C_RST} 前端、后端 API 和检测服务都将下线"

if [[ $YES -ne 1 ]]; then
  read -r -p "确认继续？输入 yes 继续: " ans
  if [[ "$ans" != "yes" ]]; then
    echo "${C_DIM}[SKIP]${C_RST} 用户取消"
    exit 0
  fi
fi

for s in "${RUNNING[@]}"; do
  if fuda_stop_session "$s"; then
    echo "${C_GRN}[ OK ]${C_RST} 已关停 $s"
  else
    echo "${C_RED}[FAIL]${C_RST} 关停失败 $s"
    exit 1
  fi
done
