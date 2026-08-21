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
frontend_build_script="$(<"$PROJECT_ROOT/scripts/build_frontend.sh")"
nginx_config="$(<"$PROJECT_ROOT/deploy/nginx/aicv-unified-backend.conf")"
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

[[ "$stop_script" == *"SERVICES=(unified_backend aivision)"* ]] || \
  fail "stop.sh must manage exactly the two backend runtime services"
[[ "$stop_script" == *"LEGACY_SERVICES=(unified_frontend security_vlm guard_room)"* ]] || \
  fail "stop.sh must clean the retired Vite and visual service sessions"
[[ "$start_script" == *"LEGACY_SERVICE_SESSIONS=(guard_room security_vlm unified_frontend)"* ]] || \
  fail "start.sh must detect legacy visual service sessions"
[[ "$start_script" != *"npm run dev"* && "$start_script" != *"|3000|"* ]] || \
  fail "production startup must not launch the Vite development server"
[[ "$start_script" == *"scripts/build_frontend.sh"* ]] || \
  fail "production startup must build the static frontend"
[[ "$status_script" == *'${FRONTEND_DIST}/index.html'* ]] || \
  fail "status.sh must verify the built frontend artifact"
[[ "$frontend_build_script" == *'mktemp -d'* ]] || \
  fail "frontend production build must use an isolated temporary directory"
[[ "$frontend_build_script" == *'mv -- "$BUILD_DIR" "$DIST_DIR"'* ]] || \
  fail "frontend production build must atomically switch the completed dist"
[[ "$nginx_config" == *"unified_frontend/dist"* && "$nginx_config" == *"try_files "*"/index.html"* ]] || \
  fail "Nginx must serve the built SPA from unified_frontend/dist"
[[ "$nginx_config" != *"127.0.0.1:3000"* ]] || \
  fail "production Nginx must not proxy to the Vite development server"
[[ "$start_script" == *"scripts/migrate_visual_integrations.sh"* ]] || \
  fail "start.sh must direct legacy source layouts through the safe migration script"
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

echo "PASS: two runtime services plus static frontend topology"
