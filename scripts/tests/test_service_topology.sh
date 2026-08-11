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
managed_visual_services="$(<"$PROJECT_ROOT/AiVision/platform/visual_services/managed.py")"
security_vlm_main="$(<"$PROJECT_ROOT/AiVision/integrations/security_vlm/src/main.py")"
security_vlm_config="$(<"$PROJECT_ROOT/AiVision/integrations/security_vlm/configs/config.example.yaml")"

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
  fail "stop.sh managed service list must contain exactly three services"
[[ "$start_script" == *"LEGACY_SERVICE_SESSIONS=(guard_room security_vlm)"* ]] || \
  fail "start.sh must detect legacy visual service sessions"
[[ "$start_script" == *"scripts/migrate_visual_integrations.sh"* ]] || \
  fail "start.sh must direct legacy source layouts through the safe migration script"
[[ "$stop_script" == *"LEGACY_SERVICES=(security_vlm guard_room)"* ]] || \
  fail "stop.sh must clean legacy visual service sessions during migration"
[[ "$aivision_app" == *'app.mount('*"/api/v2/integrations/guard-room"* ]] || \
  fail "Guard Room must be mounted in AiVision"
[[ "$aivision_app" == *'app.mount('*"/api/v2/integrations/security-vlm"* ]] || \
  fail "Security VLM must be mounted in AiVision"
[[ "$aivision_app" != *"VisualWorkerClient"* ]] || \
  fail "AiVision must not retain the HTTP worker relay"
[[ "$managed_visual_services" == *"from integrations.guard_room.src.server import create_app"* ]] || \
  fail "Guard Room must be imported from inside AiVision"
[[ "$managed_visual_services" == *"from integrations.security_vlm.src.main import create_app"* ]] || \
  fail "Security VLM must be imported from inside AiVision"
[[ -d "$PROJECT_ROOT/AiVision/integrations/guard_room" ]] || \
  fail "Guard Room source tree must live under AiVision/integrations"
[[ -d "$PROJECT_ROOT/AiVision/integrations/security_vlm" ]] || \
  fail "Security VLM source tree must live under AiVision/integrations"
[[ ! -e "$PROJECT_ROOT/guard_room" && ! -e "$PROJECT_ROOT/security_vlm" ]] || \
  fail "legacy root-level visual service directories must not remain"
[[ ! -e "$PROJECT_ROOT/AiVision/integrations/guard_room/run_server.py" ]] || \
  fail "Guard Room must not retain an independent Web launcher"
[[ "$security_vlm_main" != *"uvicorn.run("* ]] || \
  fail "Security VLM must not retain an independent Web launcher"
[[ "$security_vlm_config" != *"port: 8000"* ]] || \
  fail "Security VLM config must not advertise the removed Web port"

echo "PASS: three-service managed visual topology"
