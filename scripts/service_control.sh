#!/usr/bin/env bash
# start.sh 和 stop.sh 共用的停止流程，等待后端退出及前端监听释放。

fuda_wait_port_released() {
  local port="$1" timeout="$2" listeners deadline=$((SECONDS + $2))
  while true; do
    # tmux 会话消失后 Node 仍可能正在退出；不能仅凭会话状态立即启动新实例。
    if ! listeners="$(ss -H -ltn "sport = :${port}" 2>/dev/null)"; then
      echo "[FAIL] 无法检查端口 ${port} 是否释放，请检查 ss（iproute2）"
      return 1
    fi
    [[ -z "$listeners" ]] && return 0
    if (( SECONDS >= deadline )); then
      echo "[FAIL] 等待端口 ${port} 释放超时（${timeout}s），未启动新进程，也未终止其他占用进程"
      return 1
    fi
    sleep 0.1
  done
}

fuda_find_aivision_pids() {
  local session="$1" pane_pids processes
  pane_pids="$(tmux list-panes -s -t "$session" -F '#{pane_pid}')" || return 1
  processes="$(ps -ww -eo pid=,ppid=,comm=,args=)" || return 1
  # 只寻找当前会话的 Python 主入口，不能向模型、采集子进程或其他部署发信号。
  awk -v roots="$pane_pids" '
    BEGIN { split(roots, values, /[[:space:]]+/); for (i in values) root[values[i]] = 1 }
    { parent[$1] = $2 }
    $3 ~ /^python/ {
      for (i = 5; i < NF; i++)
        if ($i == "-m" && $(i + 1) == "AiVision.main") candidate[$1] = 1
    }
    END {
      for (pid in candidate) {
        current = pid
        while (current && current != 1) {
          if (root[current]) { print pid; break }
          current = parent[current]
        }
      }
    }
  ' <<< "$processes"
}

fuda_aivision_pid_running() {
  # 排除已经退出的僵尸进程，也避免 PID 被复用后误等待其他程序。
  ps -ww -p "$1" -o stat=,comm=,args= 2>/dev/null | awk '
    $1 !~ /^Z/ && $2 ~ /^python/ {
      for (i = 4; i < NF; i++)
        if ($i == "-m" && $(i + 1) == "AiVision.main") found = 1
    }
    END { exit !found }
  '
}

fuda_stop_session() {
  local session="$1" port="${2:-3000}" timeout="${FUDA_STOP_TIMEOUT_SECONDS:-180}"
  if [[ ! "$timeout" =~ ^[1-9][0-9]*$ ]]; then
    echo "[FAIL] FUDA_STOP_TIMEOUT_SECONDS 必须为正整数"
    return 1
  fi
  if [[ "$session" == "aivision" ]]; then
    local found pid signalled deadline waiting
    local pids=()
    if ! found="$(fuda_find_aivision_pids "$session")"; then
      echo "[FAIL] 无法识别 aivision 主进程，保留会话"
      return 1
    fi
    while read -r pid; do
      [[ -n "$pid" ]] && pids+=("$pid")
    done <<< "$found"
    signalled="$(tmux show-option -qv -t "$session" @fuda_stopping_pids 2>/dev/null || true)"
    for pid in "${pids[@]}"; do
      if [[ " $signalled " != *" $pid "* ]] && fuda_aivision_pid_running "$pid"; then
        if ! kill -TERM "$pid" 2>/dev/null && fuda_aivision_pid_running "$pid"; then
          echo "[FAIL] 无法通知 aivision 正常退出，保留会话"
          return 1
        fi
        signalled="$signalled $pid"
        tmux set-option -t "$session" @fuda_stopping_pids "$signalled" || return 1
      fi
    done
    if [[ ${#pids[@]} -gt 0 ]]; then
      echo "[INFO] 等待已接收的 AGV 请求完成检测和回传，再关闭算法（进程退出等待上限 ${timeout}s）"
    fi
    deadline=$((SECONDS + timeout))
    while true; do
      waiting=0
      for pid in "${pids[@]}"; do
        fuda_aivision_pid_running "$pid" && waiting=1
      done
      [[ $waiting -eq 0 ]] && break
      if (( SECONDS >= deadline )); then
        echo "[FAIL] aivision 尚未退出，已保留会话；请通过 tmux attach -t aivision 查看日志"
        return 1
      fi
      sleep 1
    done
  fi
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux kill-session -t "$session" || return 1
  fi
  if [[ "$session" == "unified_frontend" ]]; then
    echo "[INFO] 等待前端端口 ${port} 释放（最多 ${timeout}s）"
    fuda_wait_port_released "$port" "$timeout" || return 1
  fi
}
