#!/usr/bin/env bash
# 在临时目录和模拟 tmux 中执行真实启动函数，不启动或停止现场服务。
set -u

TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/scripts/lib" "$fixture/project/AiVision"
cp "$TEST_ROOT/scripts/start.sh" "$fixture/scripts/start.sh"
cp "$TEST_ROOT/scripts/lib/unified_backend_runtime.sh" "$fixture/scripts/lib/"
printf 'conda() { printf "aivision\\nunified_backend\\n"; }\n' > "$fixture/conda.sh"
: > "$fixture/nvm.sh"
printf 'MYSQL_DB_URL=127.0.0.1\n' > "$fixture/project/AiVision/.env"
FUDA_CVP_ROOT="$fixture/project"
CONDA_SH="$fixture/conda.sh"
NVM_SH="$fixture/nvm.sh"
unset MYSQL_DB_URL
source "$fixture/scripts/start.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
MOCK_SESSION=1
MOCK_READY=0
MOCK_READY_AFTER=0
MOCK_SEND_FAIL=0
MOCK_SLEEPS=0
MOCK_PORT_CHECKS=0
AUTH_SECRET="test-only-startup-secret"
TMUX_SUPPORTS_ENV=1
exit_file="$fixture/exit-code"
sleep_file="$fixture/sleeps"
: > "$exit_file"
: > "$sleep_file"

tmux() {
  case "$1" in
    has-session) [[ $MOCK_SESSION -eq 1 ]] ;;
    new) MOCK_SESSION=1 ;;
    kill-session) MOCK_SESSION=0 ;;
    set-option) printf '%s' "$5" > "$exit_file" ;;
    show-option) cat "$exit_file" ;;
    send-keys)
      [[ $MOCK_SEND_FAIL -eq 1 ]] && return 1
      eval "$4"
      ;;
    capture-pane) echo "test startup failure" ;;
    *) fail "unexpected tmux command: $1" ;;
  esac
}

port_listening() {
  MOCK_PORT_CHECKS=$((MOCK_PORT_CHECKS + 1))
  [[ $MOCK_READY -eq 1 ]]
}

sleep() {
  MOCK_SLEEPS=$((MOCK_SLEEPS + 1))
  printf '.\n' >> "$sleep_file"
  if [[ $MOCK_READY_AFTER -gt 0 && $MOCK_SLEEPS -ge $MOCK_READY_AFTER ]]; then
    MOCK_READY=1
  fi
  return 0
}

# AiVision/.env 存在时不应误报项目根目录缺少 .env。
output="$(precheck_one aivision "$PROJECT_ROOT" command)"
[[ $? -eq 0 && "$output" != *"MISSING CONFIG"* ]] || fail "AiVision/.env precheck: $output"

mkdir -p "$fixture/legacy/AiVision" "$fixture/missing/AiVision"
printf 'MYSQL_DB_URL=127.0.0.1\n' > "$fixture/legacy/.env"
[[ "$(aivision_env_path "$fixture/legacy")" == "$fixture/legacy/.env" ]] || fail "legacy root .env fallback"
printf '# MYSQL_DB_URL is not a configured value\n' > "$fixture/legacy/AiVision/.env"
[[ "$(aivision_env_path "$fixture/legacy")" == "$fixture/legacy/AiVision/.env" ]] || fail "AiVision .env priority"
precheck_one aivision "$fixture/legacy" command >/dev/null || fail "root settings fallback with partial AiVision env"

output="$(precheck_one aivision "$fixture/missing" command)"
[[ $? -ne 0 && "$output" == *"$fixture/missing/AiVision/.env"* ]] || fail "missing config path"
(
  MYSQL_DB_URL=127.0.0.1
  precheck_one aivision "$fixture/missing" command >/dev/null || fail "environment-based configuration"
) || exit 1

# 已就绪、慢启动和超时三条正常等待路径。
(
  MOCK_READY=1
  wait_port 7862 90 aivision || fail "ready service"
  [[ $MOCK_SLEEPS -eq 0 ]] || fail "ready service should not sleep"
) || exit 1
(
  MOCK_READY_AFTER=2
  wait_port 7862 90 aivision || fail "service becoming ready"
  [[ $MOCK_SLEEPS -eq 2 ]] || fail "stop waiting as soon as ready"
) || exit 1
(
  wait_port 7862 3 aivision
  [[ $? -eq 1 && $MOCK_SLEEPS -eq 3 ]] || fail "genuinely slow service retains timeout"
) || exit 1

# 启动命令退出码为 0 也不能当作持续运行的服务；会话消失同样立即结束等待。
for code in 0 23; do
  printf '%s' "$code" > "$exit_file"
  (
    wait_port 7862 90 aivision
    [[ $? -eq 2 && "$WAIT_PORT_EXIT_CODE" == "$code" && $MOCK_SLEEPS -eq 0 ]] || fail "exit $code fast failure"
  ) || exit 1
done
(
  MOCK_SESSION=0
  wait_port 7862 90 aivision
  [[ $? -eq 2 && $MOCK_SLEEPS -eq 0 ]] || fail "disappeared session fast failure"
) || exit 1

# 执行 start_one 生成的命令，验证 && 激活失败和应用异常退出都记录真实退出码。
MOCK_SESSION=0
for command in 'false && echo SHOULD_NOT_RUN' 'exit 23' ':'; do
  : > "$sleep_file"
  output="$(start_one aivision "$PROJECT_ROOT" "$command" 7862 90)"
  [[ $? -eq 4 && "$output" == *"启动命令已退出"* ]] || fail "start_one early exit: $output"
  [[ "$output" != *"SHOULD_NOT_RUN"* && ! -s "$sleep_file" ]] || fail "failed command must not continue or wait 90 seconds"
  case "$command" in
    false*) expected=1 ;;
    exit*) expected=23 ;;
    *) expected=0 ;;
  esac
  [[ "$(cat "$exit_file")" == "$expected" ]] || fail "recorded exit status"
done

MOCK_SEND_FAIL=1
output="$(start_one aivision "$PROJECT_ROOT" : 7862 90)"
[[ $? -eq 4 && "$output" == *"启动命令发送失败"* && "$output" != *"轮询等待"* ]] || fail "send failure"

echo "PASS: AiVision config paths and startup exit detection"
