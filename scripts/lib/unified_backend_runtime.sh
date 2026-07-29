#!/usr/bin/env bash

resolve_unified_backend_runtime() {
  local explicit_python="$1"
  local conda_sh="$2"
  local conda_env="$3"
  local system_python="$4"

  if [[ -n "$explicit_python" ]]; then
    printf '%s' "$explicit_python"
    return 0
  fi

  if [[ -n "$conda_sh" ]] \
    && [[ -n "$conda_env" ]] \
    && conda_env_exists "$conda_env" "$conda_sh"; then
    printf 'source %q && conda activate %q && python' "$conda_sh" "$conda_env"
    return 0
  fi

  if [[ -n "$system_python" ]]; then
    printf '%s' "$system_python"
    return 0
  fi

  return 1
}
