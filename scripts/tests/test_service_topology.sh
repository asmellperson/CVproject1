#!/usr/bin/env bash
# 文件说明：包含业务服务的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 功能：实现 `fail` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：本测试脚本的断言失败路径
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
fail() {
  echo "FAIL: $*" >&2
  exit 1
}

start_script="$(<"$PROJECT_ROOT/scripts/start.sh")"
status_script="$(<"$PROJECT_ROOT/scripts/status.sh")"
stop_script="$(<"$PROJECT_ROOT/scripts/stop.sh")"
vite_config="$(<"$PROJECT_ROOT/unified_frontend/vite.config.ts")"
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

[[ "$stop_script" == *"SERVICES=(unified_backend aivision unified_frontend)"* ]] || \
  fail "stop.sh must manage the frontend and two backend runtime services"
[[ "$stop_script" != *"guard_room"* && "$stop_script" != *"security_vlm"* ]] || \
  fail "stop.sh must not retain retired independent visual service sessions"
[[ "$start_script" != *"LEGACY_SERVICE_SESSIONS"* ]] || \
  fail "start.sh must not retain retired independent visual service sessions"
[[ "$start_script" == *"npm run dev -- --host 0.0.0.0 --port 3000"* && "$start_script" == *"|3000|"* ]] || \
  fail "start.sh must launch unified_frontend through Vite on port 3000"
[[ "$start_script" == *'端口 ${port} 已被非 ${name} tmux 进程占用'* ]] || \
  fail "start.sh must reject a foreign process occupying a managed service port"
[[ "$start_script" != *"build_frontend_static"* && "$start_script" != *"scripts/build_frontend.sh"* ]] || \
  fail "start.sh must not build an Nginx static frontend"
[[ ! -e "$PROJECT_ROOT/scripts/build_frontend.sh" ]] || \
  fail "obsolete dist deployment helper must be removed"
[[ "$status_script" == *"unified_frontend|3000|http://127.0.0.1:3000/|http2xx"* ]] || \
  fail "status.sh must monitor the Vite frontend tmux service on port 3000"
[[ "$status_script" != *"FRONTEND_DIST"* && "$status_script" != *"Nginx"* ]] || \
  fail "status.sh must not retain Nginx static frontend checks"
[[ "$vite_config" == *"host: '0.0.0.0'"* && "$vite_config" == *"strictPort: true"* ]] || \
  fail "Vite must accept remote clients and fail clearly when port 3000 is occupied"
[[ ! -e "$PROJECT_ROOT/deploy/nginx/aicv-unified-backend.conf" ]] || \
  fail "the project-specific Nginx frontend config must be removed"
[[ "$start_script" != *"scripts/migrate_visual_integrations.sh"* ]] || \
  fail "start.sh must not retain the completed five-service migration path"
[[ ! -e "$PROJECT_ROOT/scripts/migrate_visual_integrations.sh" ]] || \
  fail "completed five-service migration helper must be removed"
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

echo "PASS: three tmux services with Vite frontend topology"
