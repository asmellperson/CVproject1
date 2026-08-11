#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

start_script="$(<"$PROJECT_ROOT/scripts/start.sh")"
status_script="$(<"$PROJECT_ROOT/scripts/status.sh")"
stop_script="$(<"$PROJECT_ROOT/scripts/stop.sh")"
aivision_app="$(<"$PROJECT_ROOT/AiVision/api/app.py")"

[[ "$start_script" == *'conda activate ${AIVISION_ENV} && python main.py'* ]] || \
  fail "AiVision must start from its Conda environment"
[[ "$start_script" != *"uv run"* && "$start_script" != *"UV_BIN"* ]] || \
  fail "startup must not use uv"

for removed_port in 5001 8000; do
  [[ "$start_script" != *"|${removed_port}|"* ]] || \
    fail "start.sh must not launch port ${removed_port}"
  [[ "$status_script" != *"|${removed_port}|"* ]] || \
    fail "status.sh must not monitor port ${removed_port}"
done

[[ "$stop_script" == *"SERVICES=(unified_frontend unified_backend aivision)"* ]] || \
  fail "stop.sh must only stop the three managed services"
[[ "$aivision_app" == *'app.mount('*"/api/v2/integrations/guard-room"* ]] || \
  fail "Guard Room must be mounted in AiVision"
[[ "$aivision_app" == *'app.mount('*"/api/v2/integrations/security-vlm"* ]] || \
  fail "Security VLM must be mounted in AiVision"
[[ "$aivision_app" != *"VisualWorkerClient"* ]] || \
  fail "AiVision must not retain the HTTP worker relay"

echo "PASS: three-service managed visual topology"
