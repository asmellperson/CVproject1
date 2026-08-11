#!/usr/bin/env bash
# 将旧版根目录中的 Guard Room / Security VLM 本地资产合并进 AiVision。
# 不覆盖任何同名目标；冲突时在移动前终止，交由管理员确认。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${VISUAL_INTEGRATION_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

if [[ -z "$PROJECT_ROOT" || "$PROJECT_ROOT" == "/" ]]; then
  echo "ERROR: 无效的项目根目录，拒绝迁移" >&2
  exit 2
fi

check_tree_conflicts() {
  local source="$1" destination="$2"
  local source_path name destination_path

  [[ -d "$source" ]] || return 0

  while IFS= read -r -d '' source_path; do
    name="${source_path##*/}"
    destination_path="${destination}/${name}"
    if [[ ! -e "$destination_path" && ! -L "$destination_path" ]]; then
      continue
    fi
    if [[ -d "$source_path" && ! -L "$source_path" && -d "$destination_path" && ! -L "$destination_path" ]]; then
      check_tree_conflicts "$source_path" "$destination_path" || return 1
      continue
    fi
    echo "ERROR: 迁移目标已存在，未移动任何文件: $destination_path" >&2
    return 1
  done < <(find "$source" -mindepth 1 -maxdepth 1 -print0)
}

move_tree() {
  local source="$1" destination="$2"
  local source_path name destination_path

  [[ -d "$source" ]] || return 0
  mkdir -p "$destination" || return 1

  while IFS= read -r -d '' source_path; do
    name="${source_path##*/}"
    destination_path="${destination}/${name}"
    if [[ -d "$source_path" && ! -L "$source_path" && -d "$destination_path" && ! -L "$destination_path" ]]; then
      move_tree "$source_path" "$destination_path" || return 1
    else
      mv -- "$source_path" "$destination_path" || return 1
    fi
  done < <(find "$source" -mindepth 1 -maxdepth 1 -print0)

  rmdir -- "$source"
}

declare -a MODULES=(guard_room security_vlm)

for module in "${MODULES[@]}"; do
  check_tree_conflicts \
    "$PROJECT_ROOT/$module" \
    "$PROJECT_ROOT/AiVision/integrations/$module" || exit 3
done

migrated=0
for module in "${MODULES[@]}"; do
  source_path="$PROJECT_ROOT/$module"
  [[ -d "$source_path" ]] || continue
  echo "迁移旧目录: $source_path -> $PROJECT_ROOT/AiVision/integrations/$module"
  move_tree \
    "$source_path" \
    "$PROJECT_ROOT/AiVision/integrations/$module" || exit 4
  migrated=1
done

if [[ $migrated -eq 0 ]]; then
  echo "无需迁移：根目录没有旧版 guard_room / security_vlm"
else
  security_config="$PROJECT_ROOT/AiVision/integrations/security_vlm/configs/config.yaml"
  if [[ -f "$security_config" ]] && grep -qE '^[[:space:]]*staff_identity_dir:' "$security_config"; then
    if ! sed -i -E \
      's|^([[:space:]]*staff_identity_dir:[[:space:]]*).*$|\1data/annotations/staff_rois|' \
      "$security_config"; then
      echo "ERROR: 无法更新 Security VLM ROI 数据目录: $security_config" >&2
      exit 5
    fi
    echo "已将 Security VLM ROI 数据目录改为模块内相对路径"
  fi
  echo "迁移完成：视觉模块及本地资产均位于 AiVision/integrations"
fi
