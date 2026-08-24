#!/usr/bin/env bash
# =============================================================================
# 福达视觉平台 - 服务状态查询脚本
# -----------------------------------------------------------------------------
# 作用：查询 2 个后端 tmux 服务，以及 Nginx 静态前端产物和 health 状态。
# 用法：bash scripts/status.sh
# 只读：不修改任何状态。
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${FUDA_CVP_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FRONTEND_DIST="${PROJECT_ROOT}/unified_frontend/dist"
FRONTEND_STATIC_PORT="${FRONTEND_STATIC_PORT:-3000}"
FRONTEND_HEALTH_URL="${FRONTEND_HEALTH_URL:-http://127.0.0.1:3000/}"

# 服务名|端口|health_url|judge_rule
# judge_rule:
#   http2xx         仅看 HTTP 2xx
#   json:KEY=VAL    JSON 响应中 KEY 字段等于 VAL
#   skip            不做 health 探测
SERVICES=(
  "aivision|7862|http://127.0.0.1:7862/api/v2/runtime/health|json:ok=true"
  "unified_backend|5000|http://127.0.0.1:5000/api/health|json:status=ok"
)

HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-3}"

if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_DIM=""; C_RST=""
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "${C_RED}[FAIL]${C_RST} 未安装 tmux"; exit 1
fi
if ! command -v ss >/dev/null 2>&1; then
  echo "${C_RED}[FAIL]${C_RST} 未安装 ss（iproute2）"; exit 1
fi

# 探测工具（status.sh 用 curl 或 python3 兜底）
HEALTH_TOOL="none"
if command -v curl >/dev/null 2>&1; then
  HEALTH_TOOL="curl"
elif command -v python3 >/dev/null 2>&1; then
  HEALTH_TOOL="python3"
fi

# probe URL TIMEOUT  -> 输出 "CODE<TAB>BODY"
probe() {
  local url="$1" timeout="$2"
  case "$HEALTH_TOOL" in
    curl)
      local body
      body="$(curl -sS --max-time "$timeout" -w $'\n__HTTP_CODE__%{http_code}' "$url" 2>/dev/null)" || { printf '000\t'; return; }
      local code="${body##*__HTTP_CODE__}"
      body="${body%__HTTP_CODE__*}"; body="${body%$'\n'}"
      printf '%s\t%s' "$code" "$body"
      ;;
    python3)
      python3 - "$url" "$timeout" <<'PYEOF' 2>/dev/null
import sys, urllib.request, urllib.error
url, timeout = sys.argv[1], float(sys.argv[2])
try:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        print(f"{r.status}\t{r.read().decode('utf-8', errors='replace')}", end='')
except urllib.error.HTTPError as e:
    print(f"{e.code}\t{e.read().decode('utf-8', errors='replace')}", end='')
except Exception:
    print("000\t", end='')
PYEOF
      ;;
    *) printf '000\t' ;;
  esac
}

# eval_rule RULE BODY  -> 0=match
eval_rule() {
  local rule="$1" body="$2"
  case "$rule" in
    http2xx) return 0 ;;
    skip) return 0 ;;
    json:*)
      local kv="${rule#json:}"
      local key="${kv%%=*}"
      local val="${kv#*=}"
      if command -v python3 >/dev/null 2>&1; then
        local tmpf="/tmp/health_eval_$$.json"
        printf '%s' "$body" > "$tmpf"
        python3 - "$key" "$val" "$tmpf" <<'PYEOF'
import sys, json
key, expected, path = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    sys.exit(1)
v = data.get(key)
if isinstance(v, bool):
    v = "true" if v else "false"
elif v is None:
    v = "null"
else:
    v = str(v)
sys.exit(0 if v == expected else 1)
PYEOF
        local rc=$?
        rm -f "$tmpf"
        return $rc
      else
        echo "$body" | grep -qE "\"${key}\"[[:space:]]*:[[:space:]]*${val}"
      fi
      ;;
    *) return 1 ;;
  esac
}

AUTH_SECRET_FILE="$SCRIPT_DIR/auth_secret"

echo "福达视觉平台服务状态 - $(date '+%F %T')"

# AUTH_SECRET 状态（不显示原文）
if [[ -s "$AUTH_SECRET_FILE" ]]; then
  if command -v sha256sum >/dev/null 2>&1; then
    auth_fp=$(tr -d '\n\r' < "$AUTH_SECRET_FILE" | sha256sum | cut -c1-8)
  elif command -v shasum >/dev/null 2>&1; then
    auth_fp=$(tr -d '\n\r' < "$AUTH_SECRET_FILE" | shasum -a 256 | cut -c1-8)
  else
    auth_fp="????????"
  fi
  auth_perm=$(stat -c '%a' "$AUTH_SECRET_FILE" 2>/dev/null || stat -f '%Lp' "$AUTH_SECRET_FILE" 2>/dev/null || echo "?")
  if [[ "$auth_perm" == "600" ]]; then
    echo "${C_GRN}[ OK ]${C_RST} AUTH_SECRET: 已配置 (sha256:${auth_fp}, 权限 ${auth_perm})"
  else
    echo "${C_YLW}[WARN]${C_RST} AUTH_SECRET: 已配置 (sha256:${auth_fp}, 权限 ${auth_perm} 应为 600)"
    echo "        修复: chmod 600 ${AUTH_SECRET_FILE}"
  fi
else
  echo "${C_YLW}[WARN]${C_RST} AUTH_SECRET: 未配置 (首次 start.sh 会自动生成)"
fi

if [[ "$HEALTH_TOOL" == "none" ]]; then
  echo "${C_YLW}[WARN]${C_RST} HEALTH 工具: 未找到 curl/python3，跳过 health 探测"
fi

echo "============================================================================"
printf " %-18s %-6s %-10s %-10s %-10s %s\n" "服务" "端口" "tmux" "监听" "健康" "PID"
printf " %-18s %-6s %-10s %-10s %-10s %s\n" "----" "----" "----" "----" "----" "----"

ALL_OK=1
DEGRADED=0
for entry in "${SERVICES[@]}"; do
  IFS='|' read -r name port hurl hrule <<< "$entry"

  # tmux 状态
  if tmux has-session -t "$name" 2>/dev/null; then
    tmux_st="${C_GRN}运行中${C_RST}"
  else
    tmux_st="${C_RED}未运行${C_RST}"
    ALL_OK=0
  fi

  # 端口监听状态 + PID
  listen_line=$(ss -tlnp 2>/dev/null | awk -v p=":${port}\$" '$4 ~ p {print; exit}')
  if [[ -n "$listen_line" ]]; then
    port_st="${C_GRN}监听中${C_RST}"
    port_alive=1
    pid=$(echo "$listen_line" | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
    pid=${pid:-"-"}
  else
    port_st="${C_RED}未监听${C_RST}"
    port_alive=0
    pid="-"
    ALL_OK=0
  fi

  # health 探测（仅在端口监听时做）
  if [[ $port_alive -eq 1 && "$HEALTH_TOOL" != "none" && "$hrule" != "skip" ]]; then
    result="$(probe "$hurl" "$HEALTH_TIMEOUT")"
    code="${result%%$'\t'*}"
    body="${result#*$'\t'}"
    if [[ "$code" =~ ^2 ]] && eval_rule "$hrule" "$body"; then
      health_st="${C_GRN}就绪${C_RST}"
    elif [[ "$code" =~ ^2 ]]; then
      health_st="${C_YLW}降级${C_RST}"
      DEGRADED=1
    else
      health_st="${C_RED}HTTP${code}${C_RST}"
      DEGRADED=1
    fi
  elif [[ $port_alive -eq 0 ]]; then
    health_st="-"
  else
    health_st="${C_DIM}跳过${C_RST}"
  fi

  printf " %-18s %-6s %-19s %-19s %-19s %s\n" "$name" "$port" "$tmux_st" "$port_st" "$health_st" "$pid"
done

# 前端是 Nginx 托管的静态产物，不再要求 tmux/Vite 开发服务。
frontend_artifact_st="${C_RED}缺失${C_RST}"
frontend_port_st="${C_RED}未监听${C_RST}"
frontend_health_st="-"
frontend_pid="-"
frontend_ready=1

if [[ -s "${FRONTEND_DIST}/index.html" ]]; then
  frontend_artifact_st="${C_GRN}静态文件${C_RST}"
else
  frontend_ready=0
fi

frontend_listen_line=$(ss -tlnp 2>/dev/null | awk -v p=":${FRONTEND_STATIC_PORT}\$" '$4 ~ p {print; exit}')
if [[ -n "$frontend_listen_line" ]]; then
  frontend_port_st="${C_GRN}监听中${C_RST}"
  frontend_pid=$(echo "$frontend_listen_line" | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
  frontend_pid=${frontend_pid:-"-"}
  if [[ "$HEALTH_TOOL" != "none" ]]; then
    frontend_result="$(probe "$FRONTEND_HEALTH_URL" "$HEALTH_TIMEOUT")"
    frontend_code="${frontend_result%%$'\t'*}"
    if [[ "$frontend_code" =~ ^2 ]]; then
      frontend_health_st="${C_GRN}就绪${C_RST}"
    else
      frontend_health_st="${C_RED}HTTP${frontend_code}${C_RST}"
      frontend_ready=0
    fi
  else
    frontend_health_st="${C_DIM}跳过${C_RST}"
  fi
else
  frontend_ready=0
fi

if [[ $frontend_ready -ne 1 ]]; then
  ALL_OK=0
fi
printf " %-18s %-6s %-19b %-19b %-19b %s\n" \
  "unified_frontend" "$FRONTEND_STATIC_PORT" "$frontend_artifact_st" \
  "$frontend_port_st" "$frontend_health_st" "$frontend_pid"

echo "============================================================================"
if [[ $ALL_OK -eq 1 && $DEGRADED -eq 0 ]]; then
  echo "${C_GRN}[ OK ]${C_RST} 后端服务与 Nginx 静态前端全部正常"
  exit 0
elif [[ $ALL_OK -eq 1 ]]; then
  echo "${C_YLW}[WARN]${C_RST} 端口正常但有服务 health 降级（可能模型未就绪）。建议: tmux attach -t <服务名>"
  exit 0
else
  echo "${C_YLW}[WARN]${C_RST} 有服务或静态前端异常。可执行: bash scripts/start.sh，并检查 Nginx 配置"
  exit 1
fi
