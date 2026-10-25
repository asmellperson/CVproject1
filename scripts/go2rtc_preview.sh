#!/usr/bin/env bash
# 独立管理预览侧车；不读取 cold_start.env，也不向控制台输出流地址或运行日志。
set -u

GO2RTC_PREVIEW_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
GO2RTC_PREVIEW_ROOT="$(cd "${FUDA_CVP_ROOT:-$GO2RTC_PREVIEW_SCRIPT_DIR/..}" && pwd -P)"
GO2RTC_PREVIEW_RUNTIME="$GO2RTC_PREVIEW_ROOT/runtime/go2rtc"
GO2RTC_PREVIEW_CONFIG="$GO2RTC_PREVIEW_RUNTIME/go2rtc.preview.yaml"
GO2RTC_PREVIEW_LOG="$GO2RTC_PREVIEW_RUNTIME/go2rtc.log"
GO2RTC_PREVIEW_SESSION="fuda_go2rtc_preview"
GO2RTC_PREVIEW_API="http://127.0.0.1:1984"

go2rtc_preview_dependencies() {
  local tool
  for tool in tmux ss curl readlink; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "[FAIL] 缺少 $tool；tmux 管理侧车，ss（iproute2）核对监听归属，curl 检查本机健康，readlink 解析程序路径。" >&2
      return 1
    fi
  done
}

go2rtc_preview_binary() {
  local candidate="${GO2RTC_BIN:-}" resolved
  if [[ -z "$candidate" ]]; then
    candidate="$GO2RTC_PREVIEW_RUNTIME/go2rtc"
    [[ -x "$candidate" ]] || candidate="$(command -v go2rtc 2>/dev/null || true)"
  elif [[ "$candidate" != */* ]]; then
    candidate="$(command -v "$candidate" 2>/dev/null || true)"
  fi
  if [[ -z "$candidate" || ! -f "$candidate" || ! -x "$candidate" ]]; then
    echo "[FAIL] 未找到可执行的 go2rtc；请从官方 https://github.com/AlexxIT/go2rtc/releases 下载对应 Linux 架构的固定版本并核对官方 SHA256。" >&2
    echo "[INFO] 将程序放到 runtime/go2rtc/go2rtc，或设置 GO2RTC_BIN=/绝对路径/go2rtc；脚本不会自动安装软件。" >&2
    return 1
  fi
  resolved="$(readlink -f -- "$candidate")" || return 1
  printf '%s\n' "$resolved"
}

go2rtc_preview_listeners() {
  local line
  if ! GO2RTC_PREVIEW_LISTENERS="$(ss -H -ltnp 'sport = :1984' 2>&1)"; then
    echo "[FAIL] 无法核对 1984 端口，保留现有进程。" >&2
    return 1
  fi
  # 部分受限环境中 ss 无法访问 netlink 却返回 0，不能把报错当作端口空闲。
  while IFS= read -r line; do
    if [[ -n "$line" && ! "$line" =~ ^LISTEN[[:space:]] ]]; then
      echo "[FAIL] 无法核对 1984 端口，请确认当前环境允许访问网络状态。" >&2
      return 1
    fi
  done <<< "$GO2RTC_PREVIEW_LISTENERS"
}

go2rtc_preview_listener_owned() {
  local pid="$1" state received queued address peer details
  [[ -n "${GO2RTC_PREVIEW_LISTENERS:-}" ]] || return 1
  while read -r state received queued address peer details; do
    [[ "$address" == '127.0.0.1:1984' && "$details" == *"pid=$pid,"* ]] || return 1
  done <<< "$GO2RTC_PREVIEW_LISTENERS"
}

go2rtc_preview_pid_matches() {
  local pid="$1" binary="$2" index
  local arguments=()
  [[ "$pid" =~ ^[1-9][0-9]*$ && -r "/proc/$pid/cmdline" ]] || return 1
  mapfile -d '' -t arguments < "/proc/$pid/cmdline" || return 1
  # 同时核对程序与私有配置，避免向同名服务或复用的 PID 发信号。
  for ((index = 0; index + 2 < ${#arguments[@]}; index++)); do
    if [[ "${arguments[index]}" == "$binary" && "${arguments[index + 1]}" == '-c' \
       && "${arguments[index + 2]}" == "$GO2RTC_PREVIEW_CONFIG" ]]; then
      return 0
    fi
  done
  return 1
}

go2rtc_preview_session_owned() {
  local root binary pid
  root="$(tmux show-option -qv -t "$GO2RTC_PREVIEW_SESSION" @fuda_go2rtc_root 2>/dev/null)" || return 1
  binary="$(tmux show-option -qv -t "$GO2RTC_PREVIEW_SESSION" @fuda_go2rtc_binary 2>/dev/null)" || return 1
  [[ "$root" == "$GO2RTC_PREVIEW_ROOT" && -n "$binary" ]] || return 1
  pid="$(tmux list-panes -s -t "$GO2RTC_PREVIEW_SESSION" -F '#{session_name}:#{pane_pid}' 2>/dev/null)" || return 1
  # set-option 不接受所有 target-session 语法，使用普通名称后显式排除前缀匹配。
  [[ "$pid" == "$GO2RTC_PREVIEW_SESSION:"* ]] || return 1
  pid="${pid#"$GO2RTC_PREVIEW_SESSION:"}"
  go2rtc_preview_pid_matches "$pid" "$binary" || return 1
  GO2RTC_PREVIEW_PID="$pid"
  GO2RTC_PREVIEW_ACTIVE_BINARY="$binary"
}

go2rtc_preview_healthy() {
  go2rtc_preview_listener_owned "$GO2RTC_PREVIEW_PID" && \
    curl --noproxy '*' --fail --silent --max-time 2 "$GO2RTC_PREVIEW_API/api" >/dev/null 2>&1
}

go2rtc_preview_status() {
  go2rtc_preview_listeners || return 1
  if ! tmux has-session -t "$GO2RTC_PREVIEW_SESSION" 2>/dev/null; then
    if [[ -n "$GO2RTC_PREVIEW_LISTENERS" ]]; then
      echo "[FAIL] 1984 被非本脚本管理的进程占用；未修改或停止该进程。" >&2
      return 1
    fi
    echo "[INFO] go2rtc 预览侧车未运行。"
    return 3
  fi
  if ! go2rtc_preview_session_owned; then
    echo "[FAIL] 同名 tmux 会话归属无法确认；未修改或停止该会话。" >&2
    return 1
  fi
  if ! go2rtc_preview_healthy; then
    echo "[FAIL] 本项目 go2rtc 会话存在，但本机 API 未就绪或监听归属不符。" >&2
    return 1
  fi
  echo "[ OK ] go2rtc 预览侧车运行正常（$GO2RTC_PREVIEW_API，仅本机）。"
}

go2rtc_preview_start() {
  local binary command deadline
  if tmux has-session -t "$GO2RTC_PREVIEW_SESSION" 2>/dev/null; then
    go2rtc_preview_status
    return $?
  fi
  go2rtc_preview_listeners || return 1
  if [[ -n "$GO2RTC_PREVIEW_LISTENERS" ]]; then
    echo "[FAIL] 1984 已被占用；拒绝启动，未停止占用进程。" >&2
    return 1
  fi
  binary="$(go2rtc_preview_binary)" || return 1
  if [[ -L "$GO2RTC_PREVIEW_ROOT/runtime" || -L "$GO2RTC_PREVIEW_RUNTIME" \
     || -L "$GO2RTC_PREVIEW_CONFIG" || -L "$GO2RTC_PREVIEW_LOG" ]]; then
    echo "[FAIL] 运行目录、配置或日志是符号链接；拒绝把私有源信息写入其他位置。" >&2
    return 1
  fi
  umask 077
  mkdir -p "$GO2RTC_PREVIEW_RUNTIME" || return 1
  chmod 700 "$GO2RTC_PREVIEW_RUNTIME" || return 1
  # 运行配置与日志保存在私有目录；源地址由后端基于数据库动态注册到内存。
  cp "$GO2RTC_PREVIEW_SCRIPT_DIR/go2rtc.preview.yaml" "$GO2RTC_PREVIEW_CONFIG" || return 1
  : > "$GO2RTC_PREVIEW_LOG" || return 1
  chmod 600 "$GO2RTC_PREVIEW_CONFIG" "$GO2RTC_PREVIEW_LOG" || return 1
  printf -v command 'exec %q -c %q > %q 2>&1' "$binary" "$GO2RTC_PREVIEW_CONFIG" "$GO2RTC_PREVIEW_LOG"
  tmux new-session -d -s "$GO2RTC_PREVIEW_SESSION" -c "$GO2RTC_PREVIEW_ROOT" "$command" || return 1
  tmux set-option -t "$GO2RTC_PREVIEW_SESSION" @fuda_go2rtc_root "$GO2RTC_PREVIEW_ROOT" || return 1
  tmux set-option -t "$GO2RTC_PREVIEW_SESSION" @fuda_go2rtc_binary "$binary" || return 1
  deadline=$((SECONDS + GO2RTC_PREVIEW_WAIT_SECONDS))
  while (( SECONDS < deadline )); do
    if go2rtc_preview_session_owned && go2rtc_preview_listeners && go2rtc_preview_healthy; then
      echo "[ OK ] go2rtc 预览侧车已启动（$GO2RTC_PREVIEW_API，仅本机）。"
      return 0
    fi
    tmux has-session -t "$GO2RTC_PREVIEW_SESSION" 2>/dev/null || break
    sleep 0.1
  done
  echo "[FAIL] go2rtc 未在等待期限内就绪；请本机检查 runtime/go2rtc/go2rtc.log（日志可能包含私有源信息）。" >&2
  return 1
}

go2rtc_preview_stop() {
  local pid binary deadline
  go2rtc_preview_listeners || return 1
  if ! tmux has-session -t "$GO2RTC_PREVIEW_SESSION" 2>/dev/null; then
    if [[ -n "$GO2RTC_PREVIEW_LISTENERS" ]]; then
      echo "[FAIL] 1984 被未知进程占用；未向该进程发信号。" >&2
      return 1
    fi
    echo "[ OK ] go2rtc 预览侧车已停止。"
    return 0
  fi
  if ! go2rtc_preview_session_owned; then
    echo "[FAIL] 无法确认 tmux 会话与程序归属，保留会话。" >&2
    return 1
  fi
  pid="$GO2RTC_PREVIEW_PID"
  binary="$GO2RTC_PREVIEW_ACTIVE_BINARY"
  if [[ -n "$GO2RTC_PREVIEW_LISTENERS" ]] && ! go2rtc_preview_listener_owned "$pid"; then
    echo "[FAIL] 1984 监听归属不符；未向任何进程发信号。" >&2
    return 1
  fi
  if ! kill -TERM "$pid" 2>/dev/null && go2rtc_preview_pid_matches "$pid" "$binary"; then
    echo "[FAIL] 无法通知本项目 go2rtc 正常退出，保留会话。" >&2
    return 1
  fi
  deadline=$((SECONDS + GO2RTC_PREVIEW_WAIT_SECONDS))
  while (( SECONDS < deadline )); do
    go2rtc_preview_listeners || return 1
    if ! go2rtc_preview_pid_matches "$pid" "$binary" && [[ -z "$GO2RTC_PREVIEW_LISTENERS" ]]; then
      if tmux has-session -t "$GO2RTC_PREVIEW_SESSION" 2>/dev/null; then
        [[ "$(tmux show-option -qv -t "$GO2RTC_PREVIEW_SESSION" @fuda_go2rtc_root 2>/dev/null)" == "$GO2RTC_PREVIEW_ROOT" ]] || return 1
        tmux kill-session -t "$GO2RTC_PREVIEW_SESSION" || return 1
      fi
      echo "[ OK ] go2rtc 预览侧车已停止，1984 端口已释放。"
      return 0
    fi
    sleep 0.1
  done
  echo "[FAIL] go2rtc 尚未退出或端口尚未释放；保留会话，不强制结束进程。" >&2
  return 1
}

go2rtc_preview_main() {
  case "${1:-}" in
    -h|--help|help)
      echo "用法：bash scripts/go2rtc_preview.sh start|stop|status"
      echo "可选环境变量：GO2RTC_BIN、GO2RTC_PREVIEW_WAIT_SECONDS（默认 10 秒）。"
      return 0 ;;
    start|stop|status) ;;
    *) echo "用法：bash scripts/go2rtc_preview.sh start|stop|status" >&2; return 2 ;;
  esac
  [[ $# -eq 1 ]] || return 2
  GO2RTC_PREVIEW_WAIT_SECONDS="${GO2RTC_PREVIEW_WAIT_SECONDS:-10}"
  if [[ ! "$GO2RTC_PREVIEW_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "[FAIL] GO2RTC_PREVIEW_WAIT_SECONDS 必须为正整数。" >&2
    return 2
  fi
  go2rtc_preview_dependencies || return 1
  "go2rtc_preview_$1"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  go2rtc_preview_main "$@"
fi
