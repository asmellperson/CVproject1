#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJECT_ROOT/scripts/lib/unified_backend_runtime.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_equals() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [[ "$actual" != "$expected" ]]; then
    fail "${message}: expected '${expected}', got '${actual}'"
  fi
}

conda_env_exists() {
  local env_name="$1"
  local conda_sh="$2"
  [[ "${FAKE_CONDA_ENV_EXISTS:-0}" == "1" ]] \
    && [[ "$env_name" == "unified_backend" ]] \
    && [[ "$conda_sh" == "/opt/conda/etc/profile.d/conda.sh" ]]
}

runtime="$(resolve_unified_backend_runtime \
  "/custom/python" \
  "/opt/conda/etc/profile.d/conda.sh" \
  "unified_backend" \
  "/usr/bin/python3")"
assert_equals \
  "/custom/python" \
  "$runtime" \
  "explicit Python must have highest priority"

FAKE_CONDA_ENV_EXISTS=1
runtime="$(resolve_unified_backend_runtime \
  "" \
  "/opt/conda/etc/profile.d/conda.sh" \
  "unified_backend" \
  "/usr/bin/python3")"
assert_equals \
  "source /opt/conda/etc/profile.d/conda.sh && conda activate unified_backend && python" \
  "$runtime" \
  "existing unified_backend Conda environment must be selected"

FAKE_CONDA_ENV_EXISTS=0
runtime="$(resolve_unified_backend_runtime \
  "" \
  "/opt/conda/etc/profile.d/conda.sh" \
  "unified_backend" \
  "/usr/bin/python3")"
assert_equals \
  "/usr/bin/python3" \
  "$runtime" \
  "system Python must remain a compatibility fallback"

if runtime="$(resolve_unified_backend_runtime "" "" "unified_backend" "")"; then
  fail "runtime resolution must fail when no Python runtime exists"
fi
assert_equals "" "$runtime" "failed runtime resolution must not emit a command"

help_output="$(bash "$PROJECT_ROOT/scripts/start.sh" --help)"
if [[ "$help_output" != *"bash scripts/start.sh"* ]]; then
  fail "start.sh help must show the actual startup script name"
fi
if [[ "$help_output" != *"scripts/start.env.example"* ]]; then
  fail "start.sh help must show the existing environment example filename"
fi

echo "PASS: unified backend runtime selection"
