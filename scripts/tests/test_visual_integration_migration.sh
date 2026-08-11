#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT

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
if VISUAL_INTEGRATION_PROJECT_ROOT="$FIXTURE_ROOT" \
  bash "$PROJECT_ROOT/scripts/migrate_visual_integrations.sh" >/dev/null 2>&1; then
  fail "migration must stop when a destination file already exists"
fi
grep -qx 'target' "$FIXTURE_ROOT/AiVision/integrations/guard_room/config/config.yaml" || \
  fail "migration overwrote an existing destination file"
[[ -f "$FIXTURE_ROOT/guard_room/config/config.yaml" ]] || \
  fail "conflicting legacy file should remain for manual resolution"

echo "PASS: legacy visual integration assets migrate without overwriting tracked files"
