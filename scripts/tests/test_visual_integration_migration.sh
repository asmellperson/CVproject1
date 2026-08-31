#!/usr/bin/env bash
# 文件说明：包含数据迁移的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT

# 功能：实现 `fail` 对应的数据迁移逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/build_frontend.sh` 的脚本流程调用本函数；`scripts/start.sh` 的脚本流程调用本函数；`scripts/tests/test_frontend_build.sh`
#         的脚本流程调用本函数；`scripts/tests/test_service_topology.sh` 的脚本流程调用本函数；另有 2 处调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mkdir -p \
  "$FIXTURE_ROOT/guard_room/config" \
  "$FIXTURE_ROOT/guard_room/models" \
  "$FIXTURE_ROOT/security_vlm/configs" \
  "$FIXTURE_ROOT/security_vlm/data" \
  "$FIXTURE_ROOT/AiVision/integrations/guard_room/config" \
  "$FIXTURE_ROOT/AiVision/integrations/security_vlm/configs"
printf 'data:\n  staff_identity_dir: /legacy/security_vlm/data/annotations/staff_rois\n' \
  > "$FIXTURE_ROOT/security_vlm/configs/config.yaml"
touch \
  "$FIXTURE_ROOT/guard_room/config/config.yaml" \
  "$FIXTURE_ROOT/guard_room/models/person_phone.pt" \
  "$FIXTURE_ROOT/security_vlm/data/cameras.json" \
  "$FIXTURE_ROOT/AiVision/integrations/guard_room/config/config.example.yaml" \
  "$FIXTURE_ROOT/AiVision/integrations/security_vlm/configs/config.example.yaml"

GUARD_ROOM_SKIP_DATA_MIGRATION=1 \
  VISUAL_INTEGRATION_PROJECT_ROOT="$FIXTURE_ROOT" \
  bash "$PROJECT_ROOT/scripts/migrate_visual_integrations.sh"

[[ ! -e "$FIXTURE_ROOT/guard_room" ]] || fail "legacy guard_room directory remains"
[[ ! -e "$FIXTURE_ROOT/security_vlm" ]] || fail "legacy security_vlm directory remains"
[[ -f "$FIXTURE_ROOT/AiVision/integrations/guard_room/config/config.yaml" ]] || fail "guard config was not moved"
[[ -f "$FIXTURE_ROOT/AiVision/integrations/guard_room/models/person_phone.pt" ]] || fail "guard model was not moved"
[[ -f "$FIXTURE_ROOT/AiVision/integrations/security_vlm/configs/config.yaml" ]] || fail "security config was not moved"
[[ -f "$FIXTURE_ROOT/AiVision/integrations/security_vlm/data/cameras.json" ]] || fail "security data was not moved"
grep -q 'staff_identity_dir: data/annotations/staff_rois' \
  "$FIXTURE_ROOT/AiVision/integrations/security_vlm/configs/config.yaml" || \
  fail "security ROI path was not normalized after moving"

mkdir -p "$FIXTURE_ROOT/guard_room/config"
printf 'legacy\n' > "$FIXTURE_ROOT/guard_room/config/config.yaml"
printf 'target\n' > "$FIXTURE_ROOT/AiVision/integrations/guard_room/config/config.yaml"
if GUARD_ROOM_SKIP_DATA_MIGRATION=1 \
  VISUAL_INTEGRATION_PROJECT_ROOT="$FIXTURE_ROOT" \
  bash "$PROJECT_ROOT/scripts/migrate_visual_integrations.sh" >/dev/null 2>&1; then
  fail "migration must stop when a destination file already exists"
fi
grep -qx 'target' "$FIXTURE_ROOT/AiVision/integrations/guard_room/config/config.yaml" || \
  fail "migration overwrote an existing destination file"
[[ -f "$FIXTURE_ROOT/guard_room/config/config.yaml" ]] || \
  fail "conflicting legacy file should remain for manual resolution"

echo "PASS: legacy visual integration assets migrate without overwriting tracked files"
