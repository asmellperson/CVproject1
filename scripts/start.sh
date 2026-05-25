#!/usr/bin/env bash
# =============================================================================
# 福达视觉平台 - 冷启动脚本
# -----------------------------------------------------------------------------
# 作用：用 tmux 后台启动 4 个子服务：guard_room / aivision / security_vlm /
#       unified_frontend，并做端口健康检查。
#
# 用法：
#   bash scripts/cold_start.sh                  # 安全模式：已存在会话则跳过
#   bash scripts/cold_start.sh --force          # 强制：先 kill 旧会话再启动
#   bash scripts/cold_start.sh --no-check       # 跳过端口健康检查
#   bash scripts/cold_start.sh --skip-precheck  # 跳过启动前配置文件检查
#   bash scripts/cold_start.sh --yes            # 非交互：跳过首次生成 AUTH_SECRET 的确认
#   bash scripts/cold_start.sh -h               # 帮助
#
# 多服务器适配：
#   脚本会自动探测 nvm / 系统 node / conda / uv 的路径。
#   探测不到时，可创建 scripts/cold_start.env 手动指定，示例见
#   scripts/cold_start.env.example。
#
# AUTH_SECRET 管理：
#   首次运行会在 scripts/auth_secret 生成 64 字符 hex 密钥（权限 600）。
#   只注入到 guard_room / aivision 两个服务的 tmux 环境。
#   要刷新密钥：删除 scripts/auth_secret 后重新启动（会踢下线所有用户）。
#   跨服务器迁移：scp scripts/auth_secret 到目标机以保持登录态。
#
# 设计说明：
#   - 默认安全：不会动正在跑的同名 tmux 会话，避免误杀生产；
#   - 按服务粒度跳过：某服务依赖缺失只跳过该服务，不影响其他；
#   - 缺依赖/缺配置时直接在控制台给出可执行的修复命令；
#   - 启动失败自动抓取 tmux 末尾日志并匹配建议；
#   - 不开 set -e：单个服务起失败不影响其他服务继续启动；
#   - 用 set -u 防止未定义变量造成隐式错误。
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${FUDA_CVP_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# ---- 加载可选本地配置（覆盖自动探测结果）------------------------------------
[[ -f "$SCRIPT_DIR/cold_start.env" ]] && source "$SCRIPT_DIR/cold_start.env"

# ---- 颜色 ------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'
  C_BLU=$'\033[34m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_DIM=""; C_RST=""
fi

log()  { echo "${C_BLU}[INFO]${C_RST} $*"; }
ok()   { echo "${C_GRN}[ OK ]${C_RST} $*"; }
warn() { echo "${C_YLW}[WARN]${C_RST} $*"; }
err()  { echo "${C_RED}[FAIL]${C_RST} $*"; }
skip() { echo "${C_DIM}[SKIP]${C_RST} $*"; }
miss() { echo "${C_RED}[MISSING DEPS]${C_RST} $*"; }
cfg()  { echo "${C_YLW}[MISSING CONFIG]${C_RST} $*"; }
hint() { echo "  ${C_DIM}→${C_RST} $*"; }

# ---- 参数解析 --------------------------------------------------------------
FORCE=0
NO_CHECK=0
SKIP_PRECHECK=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --force)         FORCE=1 ;;
    --no-check)      NO_CHECK=1 ;;
    --skip-precheck) SKIP_PRECHECK=1 ;;
    --yes|-y)        ASSUME_YES=1 ;;
    -h|--help)
      sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      err "未知参数: $arg （用 -h 查看帮助）"
      exit 2 ;;
  esac
done

# ---- 动态探测函数 ----------------------------------------------------------

detect_nvm_sh() {
  if [[ -n "${NVM_SH:-}" && -f "$NVM_SH" ]]; then echo "$NVM_SH"; return 0; fi
  for p in "${NVM_DIR:-}/nvm.sh" "$HOME/.nvm/nvm.sh" \
           "/usr/local/nvm/nvm.sh" "/opt/nvm/nvm.sh"; do
    if [[ -n "$p" && -f "$p" ]]; then echo "$p"; return 0; fi
  done
  return 1
}

# 系统 node 探测：版本主号需匹配 NODE_VERSION
detect_system_node() {
  local node_ver="${NODE_VERSION:-20}"
  if command -v node >/dev/null 2>&1; then
    local v major
    v="$(node -v 2>/dev/null)" || return 1
    major="${v#v}"; major="${major%%.*}"
    if [[ "$major" == "$node_ver" ]]; then
      echo "$(command -v node)|$v"
      return 0
    fi
  fi
  return 1
}

detect_conda_sh() {
  if [[ -n "${CONDA_SH:-}" && -f "$CONDA_SH" ]]; then echo "$CONDA_SH"; return 0; fi
  for p in "$HOME/miniconda3/etc/profile.d/conda.sh" \
           "$HOME/anaconda3/etc/profile.d/conda.sh" \
           "/root/miniconda3/etc/profile.d/conda.sh" \
           "/opt/miniconda3/etc/profile.d/conda.sh" \
           "/opt/conda/etc/profile.d/conda.sh"; do
    if [[ -f "$p" ]]; then echo "$p"; return 0; fi
  done
  if command -v conda >/dev/null 2>&1; then
    local base
    base="$(conda info --base 2>/dev/null)" || true
    if [[ -n "$base" && -f "$base/etc/profile.d/conda.sh" ]]; then
      echo "$base/etc/profile.d/conda.sh"; return 0
    fi
  fi
  return 1
}

detect_uv_bin() {
  if [[ -n "${UV_BIN:-}" && -x "$UV_BIN" ]]; then echo "$UV_BIN"; return 0; fi
  if command -v uv >/dev/null 2>&1; then command -v uv; return 0; fi
  if [[ -x "$HOME/.local/bin/uv" ]]; then echo "$HOME/.local/bin/uv"; return 0; fi
  return 1
}

conda_env_exists() {
  local env_name="$1" conda_sh="$2"
  # 用子 shell source conda 后检查，不污染当前 shell
  if ! output="$(bash -c "source '$conda_sh' 2>/dev/null && conda env list 2>/dev/null" 2>/dev/null)"; then
    return 1
  fi
  echo "$output" | awk '{print $1}' | grep -qx "$env_name"
}

# ---- AUTH_SECRET 管理 ------------------------------------------------------
# 读取或首次生成共享 auth 密钥；写入 scripts/auth_secret（权限 600）。
# 首次生成会踢下线所有现有用户，因此默认弹出确认；--yes 跳过。
# 仅注入到 guard_room 与 aivision 的 tmux 环境。
AUTH_SECRET=""
AUTH_SECRET_SOURCE=""    # reuse | new
AUTH_SECRET_FP=""        # sha256 前 8 位
AUTH_SECRET_FILE=""

ensure_auth_secret() {
  AUTH_SECRET_FILE="$SCRIPT_DIR/auth_secret"

  if [[ -s "$AUTH_SECRET_FILE" ]]; then
    AUTH_SECRET="$(tr -d '\n\r' < "$AUTH_SECRET_FILE")"
    AUTH_SECRET_SOURCE="reuse"
  else
    # 首次生成 - 高风险操作，默认要求确认
    if [[ $ASSUME_YES -ne 1 ]]; then
      echo
      warn "首次生成 AUTH_SECRET（${AUTH_SECRET_FILE}）"
      warn "  影响：所有当前在线用户的登录 token 立即失效，需重新登录。"
      warn "  跨服务器迁移：可改为 scp 已有 auth_secret 到本机（取消本次后操作）。"
      read -r -p "  确认生成新密钥？输入 yes 继续，其他任意键取消: " reply
      if [[ "$reply" != "yes" ]]; then
        err "已取消。请 scp 现有 auth_secret 到 ${AUTH_SECRET_FILE} 后重试。"
        exit 3
      fi
    fi

    if command -v openssl >/dev/null 2>&1; then
      AUTH_SECRET="$(openssl rand -hex 32)"
    elif command -v python3 >/dev/null 2>&1; then
      AUTH_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
    elif [[ -r /dev/urandom ]] && command -v xxd >/dev/null 2>&1; then
      AUTH_SECRET="$(head -c 32 /dev/urandom | xxd -p -c 64)"
    elif [[ -r /dev/urandom ]] && command -v od >/dev/null 2>&1; then
      AUTH_SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    else
      err "无法生成 AUTH_SECRET：需要 openssl 或 python3 或 (xxd|od) + /dev/urandom 之一"
      exit 3
    fi

    # 原子写入 + 严格权限
    local tmp="${AUTH_SECRET_FILE}.tmp.$$"
    ( umask 077 && printf '%s\n' "$AUTH_SECRET" > "$tmp" ) || {
      err "写入 ${AUTH_SECRET_FILE} 失败"; exit 3;
    }
    chmod 600 "$tmp"
    mv -f "$tmp" "$AUTH_SECRET_FILE"
    AUTH_SECRET_SOURCE="new"
  fi

  # 校验长度（避免误写空文件或截断）
  if [[ ${#AUTH_SECRET} -lt 32 ]]; then
    err "AUTH_SECRET 长度异常 (${#AUTH_SECRET} 字符)，请删除 ${AUTH_SECRET_FILE} 重新生成"
    exit 3
  fi

  # 指纹（便于多机比对，不泄露原文）
  if command -v sha256sum >/dev/null 2>&1; then
    AUTH_SECRET_FP="$(printf '%s' "$AUTH_SECRET" | sha256sum | cut -c1-8)"
  elif command -v shasum >/dev/null 2>&1; then
    AUTH_SECRET_FP="$(printf '%s' "$AUTH_SECRET" | shasum -a 256 | cut -c1-8)"
  else
    AUTH_SECRET_FP="????????"
  fi
}

# tmux 是否支持 `new -e KEY=VAL`（>= 3.2）
# 0=不支持（用 export prepend 兜底），1=支持
TMUX_SUPPORTS_ENV=0
detect_tmux_env_support() {
  local v major minor
  v="$(tmux -V 2>/dev/null | awk '{print $2}')"
  # tmux -V 形如 "tmux 3.4" / "tmux 3.2a" / "tmux next-3.5"
  v="${v##*-}"           # 去掉 next- 前缀
  major="${v%%.*}"
  minor="${v#*.}"; minor="${minor%%.*}"
  # 去掉 minor 中字母后缀 (如 3.2a -> 2)
  minor="${minor%%[!0-9]*}"
  if [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]]; then
    if (( major > 3 )) || (( major == 3 && minor >= 2 )); then
      TMUX_SUPPORTS_ENV=1
    fi
  fi
}

# 判断某服务是否需要 AUTH_SECRET 注入
needs_auth_secret() {
  case "$1" in
    guard_room|aivision) return 0 ;;
    *) return 1 ;;
  esac
}

# ---- 执行探测 --------------------------------------------------------------
NVM_SH_PATH="$(detect_nvm_sh || true)"
CONDA_SH_PATH="$(detect_conda_sh || true)"
UV_BIN_PATH="$(detect_uv_bin || true)"
NODE_VERSION="${NODE_VERSION:-20}"
GUARD_ROOM_ENV="${GUARD_ROOM_ENV:-guard_room}"
SECURITY_VLM_ENV="${SECURITY_VLM_ENV:-security_vlm}"

# 健康检查上限（秒）- 可在 cold_start.env 中覆盖
WAIT_GUARD_ROOM="${WAIT_GUARD_ROOM:-15}"
WAIT_AIVISION="${WAIT_AIVISION:-30}"
WAIT_SECURITY_VLM="${WAIT_SECURITY_VLM:-60}"
WAIT_UNIFIED_FRONTEND="${WAIT_UNIFIED_FRONTEND:-15}"

# node 运行时探测：先 nvm 后系统 node
NODE_RUNTIME_TYPE=""    # nvm | system | ""
NODE_RUNTIME_PATH=""    # nvm.sh 路径 或 node 可执行路径
NODE_RUNTIME_VERSION=""
if [[ -n "$NVM_SH_PATH" ]]; then
  NODE_RUNTIME_TYPE="nvm"
  NODE_RUNTIME_PATH="$NVM_SH_PATH"
elif sys_node="$(detect_system_node)"; then
  NODE_RUNTIME_TYPE="system"
  NODE_RUNTIME_PATH="${sys_node%%|*}"
  NODE_RUNTIME_VERSION="${sys_node##*|}"
fi

# ---- 构造服务列表（顺序即启动顺序） ----------------------------------------
# 每条: tmux会话名|工作目录|启动命令|端口|健康检查等待秒数
SERVICES=()

if [[ -n "$CONDA_SH_PATH" ]] && conda_env_exists "$GUARD_ROOM_ENV" "$CONDA_SH_PATH"; then
  SERVICES+=("guard_room|${PROJECT_ROOT}/guard_room|source ${CONDA_SH_PATH} && conda activate ${GUARD_ROOM_ENV} && python run_server.py|5000|${WAIT_GUARD_ROOM}")
else
  SERVICES+=("guard_room|${PROJECT_ROOT}/guard_room|__DEP_MISSING__|5000|${WAIT_GUARD_ROOM}")
fi

if [[ -n "$UV_BIN_PATH" ]]; then
  UV_DIR="$(dirname "$UV_BIN_PATH")"
  SERVICES+=("aivision|${PROJECT_ROOT}/AiVision|export PATH=${UV_DIR}:\$PATH && ${UV_BIN_PATH} run main.py|7862|${WAIT_AIVISION}")
else
  SERVICES+=("aivision|${PROJECT_ROOT}/AiVision|__DEP_MISSING__|7862|${WAIT_AIVISION}")
fi

if [[ -n "$CONDA_SH_PATH" ]] && conda_env_exists "$SECURITY_VLM_ENV" "$CONDA_SH_PATH"; then
  SERVICES+=("security_vlm|${PROJECT_ROOT}/security_vlm|source ${CONDA_SH_PATH} && conda activate ${SECURITY_VLM_ENV} && python src/main.py --config configs/config.yaml|8000|${WAIT_SECURITY_VLM}")
else
  SERVICES+=("security_vlm|${PROJECT_ROOT}/security_vlm|__DEP_MISSING__|8000|${WAIT_SECURITY_VLM}")
fi

if [[ "$NODE_RUNTIME_TYPE" == "nvm" ]]; then
  SERVICES+=("unified_frontend|${PROJECT_ROOT}/unified_frontend|source ${NODE_RUNTIME_PATH} && nvm use ${NODE_VERSION} >/dev/null && npm run dev|3000|${WAIT_UNIFIED_FRONTEND}")
elif [[ "$NODE_RUNTIME_TYPE" == "system" ]]; then
  SERVICES+=("unified_frontend|${PROJECT_ROOT}/unified_frontend|npm run dev|3000|${WAIT_UNIFIED_FRONTEND}")
else
  SERVICES+=("unified_frontend|${PROJECT_ROOT}/unified_frontend|__DEP_MISSING__|3000|${WAIT_UNIFIED_FRONTEND}")
fi

# ---- 端口监听检查 ----------------------------------------------------------
port_listening() {
  local port="$1"
  ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$"
}

# ---- 轮询等待端口（每 1s 检测，最多 max 秒） -------------------------------
wait_port() {
  local port="$1" max="$2" elapsed=0
  while [[ $elapsed -lt $max ]]; do
    port_listening "$port" && return 0
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

# ---- 健康检查配置 ----------------------------------------------------------
# 每个服务一条: name|health_url|judge_rule
#   judge_rule 语法:
#     http2xx              仅看 HTTP 2xx 返回码
#     json:KEY=VAL         JSON 响应中 KEY 字段等于 VAL（字符串或 true/false）
#     skip                 不做 health 探测（端口监听即视为 READY）
# 注意: health_url 用 127.0.0.1，避免走外部 DNS / 防火墙
SERVICES_HEALTH=(
  "guard_room|http://127.0.0.1:5000/api/health|json:ready=true"
  "aivision|http://127.0.0.1:7862/api/v2/runtime/health|json:ok=true"
  "security_vlm|http://127.0.0.1:8000/health|json:running=true"
  "unified_frontend|http://127.0.0.1:3000/|http2xx"
)

# health 探测参数
HEALTH_PROBE_MAX="${HEALTH_PROBE_MAX:-10}"        # 最多轮询多少次
HEALTH_PROBE_INTERVAL="${HEALTH_PROBE_INTERVAL:-2}"  # 每次间隔秒
HEALTH_PROBE_TIMEOUT="${HEALTH_PROBE_TIMEOUT:-3}"    # 单次 HTTP 超时秒

# 探测工具链（首次调用时确定）
HEALTH_TOOL=""

detect_health_tool() {
  if command -v curl >/dev/null 2>&1; then
    HEALTH_TOOL="curl"
  elif command -v wget >/dev/null 2>&1; then
    HEALTH_TOOL="wget"
  elif command -v python3 >/dev/null 2>&1; then
    HEALTH_TOOL="python3"
  else
    HEALTH_TOOL="none"
  fi
}

# http_fetch_simple URL TIMEOUT  -> 输出 "CODE\tBODY" (失败时 CODE=000)
http_fetch_simple() {
  local url="$1" timeout="$2"
  case "$HEALTH_TOOL" in
    curl)
      local body
      body="$(curl -sS --max-time "$timeout" -w $'\n__HTTP_CODE__%{http_code}' "$url" 2>/dev/null)" || return 1
      local code="${body##*__HTTP_CODE__}"
      body="${body%__HTTP_CODE__*}"
      body="${body%$'\n'}"
      printf '%s\t%s' "$code" "$body"
      ;;
    wget)
      local tmp="/tmp/health.$$.body"
      local code
      # wget 不直接给 HTTP code，靠 -S 解析 server header
      code="$(wget -q -S -O "$tmp" --timeout="$timeout" --tries=1 "$url" 2>&1 \
              | awk '/HTTP\// {code=$2} END{print (code?code:"000")}')"
      local body=""
      [[ -f "$tmp" ]] && body="$(cat "$tmp")" && rm -f "$tmp"
      printf '%s\t%s' "$code" "$body"
      ;;
    python3)
      python3 - "$url" "$timeout" <<'PYEOF' 2>/dev/null
import sys, urllib.request, urllib.error
url, timeout = sys.argv[1], float(sys.argv[2])
try:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = r.read().decode('utf-8', errors='replace')
        print(f"{r.status}\t{body}", end='')
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='replace')
    print(f"{e.code}\t{body}", end='')
except Exception:
    print("000\t", end='')
PYEOF
      ;;
    *)
      printf '000\t'
      ;;
  esac
}

# eval_rule RULE BODY  -> 0=match, 1=no match
eval_rule() {
  local rule="$1" body="$2"
  case "$rule" in
    http2xx) return 0 ;;
    json:*)
      local kv="${rule#json:}"
      local key="${kv%%=*}"
      local val="${kv#*=}"
      if command -v python3 >/dev/null 2>&1; then
        # body 通过临时文件传入（here-doc 会覆盖 stdin，无法用 pipe）
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
    skip) return 0 ;;
    *) return 1 ;;
  esac
}

# get_health_rule NAME  -> 输出 "url|rule"，找不到返回非零
get_health_rule() {
  local name="$1" entry
  for entry in "${SERVICES_HEALTH[@]}"; do
    IFS='|' read -r n u r <<< "$entry"
    if [[ "$n" == "$name" ]]; then
      printf '%s|%s' "$u" "$r"
      return 0
    fi
  done
  return 1
}

# probe_health NAME  -> 0=READY, 1=DEGRADED, 2=配置缺失/跳过
# 轮询 HEALTH_PROBE_MAX 次，每次间隔 HEALTH_PROBE_INTERVAL 秒
probe_health() {
  local name="$1"
  local conf url rule
  conf="$(get_health_rule "$name")" || return 2
  url="${conf%%|*}"
  rule="${conf#*|}"
  [[ "$rule" == "skip" ]] && return 2

  [[ -z "$HEALTH_TOOL" ]] && detect_health_tool
  if [[ "$HEALTH_TOOL" == "none" ]]; then
    return 2
  fi

  local i=0 code body result
  while (( i < HEALTH_PROBE_MAX )); do
    result="$(http_fetch_simple "$url" "$HEALTH_PROBE_TIMEOUT")"
    code="${result%%$'\t'*}"
    body="${result#*$'\t'}"

    if [[ "$code" =~ ^2 ]]; then
      if [[ "$rule" == "http2xx" ]]; then
        return 0
      fi
      if eval_rule "$rule" "$body"; then
        return 0
      fi
    fi

    i=$((i + 1))
    (( i < HEALTH_PROBE_MAX )) && sleep "$HEALTH_PROBE_INTERVAL"
  done

  # 最后一次失败，把响应留到 caller 通过全局变量看到（用于排错）
  HEALTH_LAST_CODE="$code"
  HEALTH_LAST_BODY="$body"
  return 1
}

# ---- 从 tmux 日志推断修复建议 ----------------------------------------------
suggest_fix_from_log() {
  local name="$1" workdir="$2"
  local log
  log="$(tmux capture-pane -t "$name" -p -S -200 2>/dev/null || true)"

  if echo "$log" | grep -qE 'ModuleNotFoundError.*No module named'; then
    local pkg
    pkg="$(echo "$log" | grep -oE "No module named '[^']+'" | head -1 | sed "s/No module named '//;s/'//")"
    local env_name=""
    case "$name" in
      guard_room)   env_name="$GUARD_ROOM_ENV" ;;
      security_vlm) env_name="$SECURITY_VLM_ENV" ;;
    esac
    if [[ -n "$env_name" && -n "$CONDA_SH_PATH" ]]; then
      hint "缺少 Python 包 '${pkg:-?}'。执行："
      hint "  source ${CONDA_SH_PATH} && conda activate ${env_name} && pip install -r ${workdir}/requirements.txt"
    else
      hint "缺少 Python 包 '${pkg:-?}'，请在对应环境中安装"
    fi
  elif echo "$log" | grep -qE 'Field required.*MYSQL_DB'; then
    hint "AiVision 缺少业务配置 .env（含 MySQL 连接信息）。执行："
    hint "  从老机器拷贝: scp <老机器>:${workdir}/.env ${workdir}/.env"
    hint "  拷贝后务必编辑 MySQL 连接信息: vi ${workdir}/.env"
  elif echo "$log" | grep -qE 'pydantic.*ValidationError'; then
    hint "配置校验失败，请检查 .env 文件中必填字段是否完整"
    hint "  参考示例: ls ${workdir}/.env.*"
  elif echo "$log" | grep -qE 'Address already in use|port .* already'; then
    hint "端口被占用，查看占用进程: ss -tlnp | grep ':<端口>'"
  elif echo "$log" | grep -qE 'CUDA.*error|no CUDA-capable device'; then
    hint "GPU 不可用（可能不致命）。如需 GPU 请检查: nvidia-smi"
  elif echo "$log" | grep -qE 'ImportError.*cannot import name'; then
    hint "依赖版本不匹配，建议重装: pip install -r ${workdir}/requirements.txt --upgrade"
  elif echo "$log" | grep -qE 'No such file or directory.*\.env'; then
    hint "缺少配置文件 .env，请从老机器拷贝或从示例创建"
  elif echo "$log" | grep -qE 'No such file or directory.*config'; then
    hint "缺少配置文件，请从老机器拷贝或从示例创建: ls ${workdir}/config*/"
  else
    hint "未识别错误，请查看完整日志: tmux attach -t ${name}"
  fi
}

# ---- 依赖缺失时的具体修复提示 ----------------------------------------------
suggest_dep_fix() {
  local name="$1" workdir="$2"
  case "$name" in
    guard_room)
      if [[ -z "$CONDA_SH_PATH" ]]; then
        hint "conda 未安装。安装 Miniconda:"
        hint "  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh"
        hint "  bash /tmp/miniconda.sh -b -p \$HOME/miniconda3"
      else
        hint "conda 环境 '${GUARD_ROOM_ENV}' 不存在。执行："
        hint "  source ${CONDA_SH_PATH}"
        hint "  conda create -n ${GUARD_ROOM_ENV} python=3.10 -y"
        hint "  conda activate ${GUARD_ROOM_ENV}"
        hint "  pip install -r ${workdir}/requirements.txt"
      fi
      ;;
    aivision)
      hint "uv 未安装。执行："
      hint "  curl -LsSf https://astral.sh/uv/install.sh | sh"
      hint "  source \$HOME/.local/bin/env 2>/dev/null || export PATH=\$HOME/.local/bin:\$PATH"
      hint "  cd ${workdir} && uv sync"
      ;;
    security_vlm)
      if [[ -z "$CONDA_SH_PATH" ]]; then
        hint "conda 未安装。安装 Miniconda:"
        hint "  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh"
        hint "  bash /tmp/miniconda.sh -b -p \$HOME/miniconda3"
      else
        hint "conda 环境 '${SECURITY_VLM_ENV}' 不存在。执行："
        hint "  source ${CONDA_SH_PATH}"
        hint "  conda create -n ${SECURITY_VLM_ENV} python=3.10 -y"
        hint "  conda activate ${SECURITY_VLM_ENV}"
        hint "  pip install -r ${workdir}/requirements.txt"
      fi
      ;;
    unified_frontend)
      hint "既无 nvm，系统 node 版本也不匹配（需要 v${NODE_VERSION}）。任选其一："
      hint "  A) 装 nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash"
      hint "     source ~/.nvm/nvm.sh && nvm install ${NODE_VERSION}"
      hint "  B) 用 NodeSource 装系统 node ${NODE_VERSION}:"
      hint "     curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash -"
      hint "     apt install -y nodejs"
      if [[ ! -d "${workdir}/node_modules" ]]; then
        hint "node_modules 不存在，安装依赖: cd ${workdir} && npm ci"
      fi
      ;;
  esac
}

# ---- 启动前配置文件检查 ----------------------------------------------------
# 返回 0 表示检查通过；非 0 表示有缺失（仍允许继续尝试启动）
precheck_one() {
  local name="$1" workdir="$2" cmd="$3"
  local issues=0
  [[ "$cmd" == "__DEP_MISSING__" ]] && return 0
  [[ $SKIP_PRECHECK -eq 1 ]] && return 0

  case "$name" in
    aivision)
      if [[ ! -f "${workdir}/.env" ]]; then
        cfg "${name} 缺少配置文件 ${workdir}/.env（含 MySQL 连接信息）"
        hint "从老机器拷贝: scp <老机器>:${workdir}/.env ${workdir}/.env"
        hint "拷贝后务必编辑 MySQL 连接信息: vi ${workdir}/.env"
        issues=$((issues + 1))
      elif ! grep -qE 'MYSQL_DB_URL' "${workdir}/.env" 2>/dev/null; then
        cfg "${name} .env 中缺少 MYSQL_DB_URL"
        hint "请编辑: vi ${workdir}/.env"
        issues=$((issues + 1))
      fi
      ;;
    security_vlm)
      if [[ ! -f "${workdir}/configs/config.yaml" ]]; then
        cfg "${name} 缺少配置文件 ${workdir}/configs/config.yaml"
        hint "从老机器拷贝: scp <老机器>:${workdir}/configs/config.yaml ${workdir}/configs/config.yaml"
        issues=$((issues + 1))
      fi
      ;;
    unified_frontend)
      if [[ ! -d "${workdir}/node_modules" ]]; then
        cfg "${name} 缺少 node_modules"
        hint "安装依赖: cd ${workdir} && npm ci"
        issues=$((issues + 1))
      fi
      ;;
  esac
  return $issues
}

# ---- 启动单个服务 ----------------------------------------------------------
# 返回码:
#   0 = READY (端口监听+health 探测通过) 或 NOT_STARTED(SKIP 已有会话) 或 --no-check 已发出命令
#   2 = DEP_MISSING（依赖缺失，未启动）
#   3 = WORKDIR_MISSING（工作目录不存在）
#   4 = CRASHED（tmux 起了但端口未监听）
#   5 = DEGRADED（端口监听但 health 探测失败，模型/runtime 未就绪）
start_one() {
  local name="$1" workdir="$2" cmd="$3" port="$4" wait_s="$5"

  echo
  log "─── ${name} (端口 ${port}) ───"

  if [[ "$cmd" == "__DEP_MISSING__" ]]; then
    miss "${name} 依赖缺失，跳过启动"
    suggest_dep_fix "$name" "$workdir"
    return 2
  fi

  if [[ ! -d "$workdir" ]]; then
    err "工作目录不存在: $workdir"
    hint "确认项目已拷贝到 ${PROJECT_ROOT}，或在 cold_start.env 中设置 FUDA_CVP_ROOT"
    return 3
  fi

  # 启动前配置文件检查（不阻断，只提示）
  precheck_one "$name" "$workdir" "$cmd" || true

  if tmux has-session -t "$name" 2>/dev/null; then
    if [[ $FORCE -eq 1 ]]; then
      warn "--force 模式：先杀掉已存在的会话 ${name}"
      tmux kill-session -t "$name"
      sleep 1
    else
      skip "tmux 会话 ${name} 已存在，跳过启动（如需重启请用 --force）"
      return 0
    fi
  fi

  log "创建 tmux 会话: $name (cwd=$workdir)"
  local tmux_new_args=(-d -s "$name" -c "$workdir")
  local cmd_to_send="$cmd"

  # 仅对 guard_room / aivision 注入 AUTH_SECRET
  if needs_auth_secret "$name"; then
    if [[ -z "$AUTH_SECRET" ]]; then
      err "${name} 需要 AUTH_SECRET 但未初始化（内部错误）"
      return 4
    fi
    if [[ $TMUX_SUPPORTS_ENV -eq 1 ]]; then
      # 推荐路径：tmux >= 3.2，环境变量不进进程参数表
      tmux_new_args+=(-e "AUTH_SECRET=${AUTH_SECRET}")
    else
      # 兜底：prepend export，单引号包裹避免 hex 中无特殊字符问题
      cmd_to_send="export AUTH_SECRET='${AUTH_SECRET}' && ${cmd}"
    fi
  fi

  if ! tmux new "${tmux_new_args[@]}"; then
    err "tmux 会话创建失败: $name"
    return 4
  fi

  log "注入启动命令"
  tmux send-keys -t "$name" "$cmd_to_send" C-m

  if [[ $NO_CHECK -eq 1 ]]; then
    ok "已发出启动命令（--no-check，未做端口检查）"
    return 0
  fi

  log "轮询等待端口 ${port}（最多 ${wait_s}s）..."
  if ! wait_port "$port" "$wait_s"; then
    # 启动失败：抓取 tmux 末 20 行 + 给出建议
    warn "${name} 端口 ${port} 在 ${wait_s}s 内未监听，下面是 tmux 末 20 行输出："
    tmux capture-pane -t "$name" -p -S -200 2>/dev/null | tail -20 | sed 's/^/  | /'
    echo
    suggest_fix_from_log "$name" "$workdir"
    hint "tmux 会话已保留，可继续排错: tmux attach -t ${name}"
    return 4
  fi
  ok "${name} 端口 ${port} 已监听"

  # 端口在 - 接着做 health 探测（看模型/runtime 是否真就绪）
  log "健康探测（最多 ${HEALTH_PROBE_MAX} 次 × ${HEALTH_PROBE_INTERVAL}s）..."
  HEALTH_LAST_CODE=""; HEALTH_LAST_BODY=""
  probe_health "$name"
  local hrc=$?
  case $hrc in
    0)
      ok "${name} health 探测通过（就绪）"
      return 0
      ;;
    2)
      warn "${name} 未配置 health 探测或工具缺失，跳过（按端口判定为 READY）"
      return 0
      ;;
    1)
      warn "${name} 端口在但 health 未就绪（DEGRADED）"
      hint "最后一次响应: HTTP ${HEALTH_LAST_CODE:-?}  body=${HEALTH_LAST_BODY:0:200}"
      hint "可能原因：模型仍在后台加载 / runtime 未启动 / 依赖外部服务（MySQL/摄像头）不可达"
      hint "继续等待或排查: tmux attach -t ${name}"
      return 5
      ;;
  esac
  return 0
}

# ---- 主流程 ----------------------------------------------------------------
main() {
  log "福达视觉平台冷启动脚本 - $(date '+%F %T')"
  log "模式: $([[ $FORCE -eq 1 ]] && echo '强制重启 (--force)' || echo '安全跳过 (默认)')${NO_CHECK:+, 跳过健康检查}"

  # 全局依赖：tmux 是硬性要求
  if ! command -v tmux >/dev/null 2>&1; then
    err "缺少全局依赖: tmux"
    exit 1
  fi

  # AUTH_SECRET 与 tmux 注入能力探测（必须在创建任何 tmux 会话之前）
  detect_tmux_env_support
  ensure_auth_secret
  detect_health_tool

  # ---- 环境探测报告 -------------------------------------------------------
  echo
  log "环境探测结果："
  log "  PROJECT_ROOT = ${PROJECT_ROOT}"

  # Node 运行时
  if [[ "$NODE_RUNTIME_TYPE" == "nvm" ]]; then
    ok "  NODE         = nvm (${NODE_RUNTIME_PATH})"
  elif [[ "$NODE_RUNTIME_TYPE" == "system" ]]; then
    ok "  NODE         = system ${NODE_RUNTIME_VERSION} (${NODE_RUNTIME_PATH})"
  else
    miss "  NODE         = 未找到 nvm 也无 v${NODE_VERSION} 系统 node（unified_frontend 将跳过）"
  fi

  if [[ -n "$CONDA_SH_PATH" ]]; then
    ok "  CONDA_SH     = ${CONDA_SH_PATH}"
  else
    miss "  CONDA_SH     = 未找到（guard_room / security_vlm 将跳过）"
  fi
  if [[ -n "$UV_BIN_PATH" ]]; then
    ok "  UV_BIN       = ${UV_BIN_PATH}"
  else
    miss "  UV_BIN       = 未找到（aivision 将跳过）"
  fi
  log "  NODE_VERSION = ${NODE_VERSION}"
  log "  GUARD_ROOM_ENV   = ${GUARD_ROOM_ENV}"
  log "  SECURITY_VLM_ENV = ${SECURITY_VLM_ENV}"
  log "  健康检查上限(秒) guard=${WAIT_GUARD_ROOM} ai=${WAIT_AIVISION} vlm=${WAIT_SECURITY_VLM} fe=${WAIT_UNIFIED_FRONTEND}"

  # AUTH_SECRET 状态
  if [[ "$AUTH_SECRET_SOURCE" == "reuse" ]]; then
    ok "  AUTH_SECRET  = 复用 (sha256:${AUTH_SECRET_FP})  ${AUTH_SECRET_FILE}"
  else
    ok "  AUTH_SECRET  = 首次生成 (sha256:${AUTH_SECRET_FP})  ${AUTH_SECRET_FILE}"
  fi
  if [[ $TMUX_SUPPORTS_ENV -eq 1 ]]; then
    log "  tmux 注入   = -e 模式 (tmux $(tmux -V 2>/dev/null | awk '{print $2}'))"
  else
    warn "  tmux 注入   = export prepend 模式 (tmux < 3.2，已自动降级)"
  fi

  # health 探测工具
  if [[ "$HEALTH_TOOL" == "none" ]]; then
    warn "  HEALTH 工具 = 未找到 curl/wget/python3（跳过 health 探测，仅做端口检查）"
  else
    log "  HEALTH 工具 = ${HEALTH_TOOL}  (轮询 ${HEALTH_PROBE_MAX}×${HEALTH_PROBE_INTERVAL}s, 单次超时 ${HEALTH_PROBE_TIMEOUT}s)"
  fi

  # 提示如何覆盖
  if [[ -z "$NODE_RUNTIME_TYPE" || -z "$CONDA_SH_PATH" || -z "$UV_BIN_PATH" ]]; then
    echo
    warn "部分依赖未探测到，对应服务将跳过。"
    warn "如需手动指定路径，请创建 scripts/cold_start.env，参考 scripts/cold_start.env.example"
  fi

  local total=0 ready_cnt=0 fail_cnt=0 dep_cnt=0 skip_cnt=0 degraded_cnt=0
  declare -A RESULT

  for entry in "${SERVICES[@]}"; do
    IFS='|' read -r name workdir cmd port wait_s <<< "$entry"
    total=$((total + 1))
    start_one "$name" "$workdir" "$cmd" "$port" "$wait_s"
    local rc=$?
    case $rc in
      0)
        # 0 既可能是 READY 也可能是 NOT_STARTED(SKIP)
        if tmux has-session -t "$name" 2>/dev/null && port_listening "$port"; then
          RESULT[$name]="READY"; ready_cnt=$((ready_cnt + 1))
        elif [[ $NO_CHECK -eq 1 ]] && tmux has-session -t "$name" 2>/dev/null; then
          RESULT[$name]="STARTED"; ready_cnt=$((ready_cnt + 1))
        else
          RESULT[$name]="NOT_STARTED"; skip_cnt=$((skip_cnt + 1))
        fi
        ;;
      2) RESULT[$name]="DEP_MISSING"; dep_cnt=$((dep_cnt + 1)); fail_cnt=$((fail_cnt + 1)) ;;
      3) RESULT[$name]="WORKDIR_MISSING"; fail_cnt=$((fail_cnt + 1)) ;;
      4) RESULT[$name]="CRASHED"; fail_cnt=$((fail_cnt + 1)) ;;
      5) RESULT[$name]="DEGRADED"; degraded_cnt=$((degraded_cnt + 1)) ;;  # 不计入 fail
      *) RESULT[$name]="FAIL"; fail_cnt=$((fail_cnt + 1)) ;;
    esac
  done

  # ---- 汇总 ---------------------------------------------------------------
  echo
  echo "============================================================"
  echo " 启动汇总  共 ${total}  就绪 ${ready_cnt}  跳过 ${skip_cnt}  降级 ${degraded_cnt}  失败 ${fail_cnt} (含依赖缺失 ${dep_cnt})"
  echo "============================================================"
  printf " %-18s %-6s %-10s %-10s %s\n" "服务" "端口" "tmux" "端口监听" "状态"
  printf " %-18s %-6s %-10s %-10s %s\n" "----" "----" "----" "--------" "----"
  for entry in "${SERVICES[@]}"; do
    IFS='|' read -r name workdir cmd port wait_s <<< "$entry"
    local tmux_st="无"
    tmux has-session -t "$name" 2>/dev/null && tmux_st="运行中"
    local port_st="未监听"
    port_listening "$port" && port_st="监听中"
    local svc_st="${RESULT[$name]:-?}"
    # DEGRADED 加黄色标记
    case "$svc_st" in
      DEGRADED) svc_st="${C_YLW}${svc_st}${C_RST}" ;;
      READY|STARTED) svc_st="${C_GRN}${svc_st}${C_RST}" ;;
      DEP_MISSING|WORKDIR_MISSING|CRASHED|FAIL) svc_st="${C_RED}${svc_st}${C_RST}" ;;
    esac
    printf " %-18s %-6s %-10s %-10s %b\n" "$name" "$port" "$tmux_st" "$port_st" "$svc_st"
  done
  echo "============================================================"
  if [[ $degraded_cnt -gt 0 ]]; then
    warn "有 ${degraded_cnt} 个服务处于 DEGRADED（端口在但 health 未就绪）。"
    warn "  通常为模型仍在加载，可稍后再跑 cold_status.sh 复查。"
    warn "  持续 DEGRADED 请 tmux attach 排查。"
  fi
  echo "查看日志: tmux attach -t <服务名>  （Ctrl+B 然后 D 退出窗口）"
  echo "停止全部: bash ${PROJECT_ROOT}/scripts/cold_stop.sh"
  echo "查询状态: bash ${PROJECT_ROOT}/scripts/cold_status.sh"
  echo "部署清单: cat ${PROJECT_ROOT}/scripts/DEPLOY.md"

  [[ $fail_cnt -eq 0 ]] && exit 0 || exit 1
}

main
