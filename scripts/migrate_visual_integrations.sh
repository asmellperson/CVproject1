#!/usr/bin/env bash
# 文件说明：提供`migrate_visual_integrations` 模块的命令行运维或验证流程。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# 将旧版根目录中的 Guard Room / Security VLM 本地资产合并进 AiVision。
# 不覆盖任何同名目标；冲突时在移动前终止，交由管理员确认。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${VISUAL_INTEGRATION_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
AIVISION_ENV="${AIVISION_ENV:-aivision}"

if [[ -z "$PROJECT_ROOT" || "$PROJECT_ROOT" == "/" ]]; then
  echo "ERROR: 无效的项目根目录，拒绝迁移" >&2
  exit 2
fi

# 功能：检查或判断 `check_tree_conflicts` 对应的`migrate_visual_integrations` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$1 / source`（Shell 字符串）：`source` 对应的业务输入值
#   - `$2`（Shell 字符串）：第 2 个位置参数
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/migrate_visual_integrations.sh` 的脚本流程调用本函数
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
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

# 功能：实现 `move_tree` 对应的`migrate_visual_integrations` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$1 / source`（Shell 字符串）：`source` 对应的业务输入值
#   - `$2`（Shell 字符串）：第 2 个位置参数
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/migrate_visual_integrations.sh` 的脚本流程调用本函数
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
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

# 功能：实现 `detect_conda_sh` 对应的`migrate_visual_integrations` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/start.sh` 的脚本流程调用本函数
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
detect_conda_sh() {
  local candidate base
  if [[ -n "${CONDA_SH:-}" && -f "$CONDA_SH" ]]; then
    echo "$CONDA_SH"
    return 0
  fi
  for candidate in \
    "$HOME/miniconda3/etc/profile.d/conda.sh" \
    "$HOME/anaconda3/etc/profile.d/conda.sh" \
    "/root/miniconda3/etc/profile.d/conda.sh" \
    "/opt/miniconda3/etc/profile.d/conda.sh" \
    "/opt/conda/etc/profile.d/conda.sh"; do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  if command -v conda >/dev/null 2>&1; then
    base="$(conda info --base 2>/dev/null)" || true
    if [[ -n "$base" && -f "$base/etc/profile.d/conda.sh" ]]; then
      echo "$base/etc/profile.d/conda.sh"
      return 0
    fi
  fi
  return 1
}

# 功能：实现 `conda_env_exists` 对应的`migrate_visual_integrations` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$1 / env_name`（Shell 字符串）：`env_name` 对应的业务输入值
#   - `$2`（Shell 字符串）：第 2 个位置参数
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：`scripts/lib/unified_backend_runtime.sh` 的脚本流程调用本函数；`scripts/migrate_visual_integrations.sh` 的脚本流程调用本函数；`scripts/start.sh`
#         的脚本流程调用本函数
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
conda_env_exists() {
  local env_name="$1" conda_sh="$2" output
  output="$(bash -c "source '$conda_sh' 2>/dev/null && conda env list 2>/dev/null")" || return 1
  echo "$output" | awk '{print $1}' | grep -qx "$env_name"
}

# 功能：实现 `migrate_guard_room_data` 对应的`migrate_visual_integrations` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `$@`（Shell 参数列表）：调用方传入的全部位置参数；具体位置含义由函数内解析
# 返回：Shell 状态码；0 表示成功，非 0 表示失败。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；通过变量间接调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：会读取或修改 Shell 变量并输出运行信息；可能创建、覆盖、移动文件或修改文件权限；失败时通过 Shell 返回码影响上层流程。
migrate_guard_room_data() {
  local target_env="$PROJECT_ROOT/AiVision/.env"
  local conda_sh

  if [[ "${GUARD_ROOM_SKIP_DATA_MIGRATION:-0}" == "1" ]]; then
    echo "跳过 Guard Room 数据库迁移（GUARD_ROOM_SKIP_DATA_MIGRATION=1）"
    return 0
  fi
  if [[ ! -f "$target_env" ]]; then
    echo "ERROR: 缺少 $target_env，无法确定 Guard Room 的目标数据库" >&2
    echo "请先准备 AiVision/.env，再重新执行本迁移脚本；不要手工重配摄像头。" >&2
    return 1
  fi
  conda_sh="$(detect_conda_sh)" || {
    echo "ERROR: 未找到 Conda，无法执行 Guard Room 历史数据迁移" >&2
    return 1
  }
  if ! conda_env_exists "$AIVISION_ENV" "$conda_sh"; then
    echo "ERROR: Conda 环境 '$AIVISION_ENV' 不存在，无法执行 Guard Room 历史数据迁移" >&2
    echo "请先安装 AiVision/requirements.txt，并使用根目录 requirements-python311.lock 约束，然后重新执行本脚本。" >&2
    return 1
  fi

  echo "迁移 Guard Room 保安室、摄像头及参数数据到 AiVision 数据库"
  (
    cd "$PROJECT_ROOT/AiVision" || exit 1
    # shellcheck disable=SC1090
    source "$conda_sh"
    conda run -n "$AIVISION_ENV" \
      python -m integrations.guard_room.src.legacy_data_migration \
      --project-root "$PROJECT_ROOT"
  )
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
  echo "视觉模块及本地资产迁移完成，均位于 AiVision/integrations"
fi

if ! migrate_guard_room_data; then
  echo "ERROR: 文件已安全保留，但 Guard Room 数据尚未迁入目标数据库" >&2
  exit 6
fi

echo "迁移完成：视觉模块、摄像头与配置数据均已处理"
