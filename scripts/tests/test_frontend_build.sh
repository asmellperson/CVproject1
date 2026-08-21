#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
FRONTEND_DIR="${TMP_DIR}/unified_frontend"
FAKE_BIN="${TMP_DIR}/bin"

cleanup() {
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT INT TERM

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mkdir -p "$FRONTEND_DIR/node_modules" "$FRONTEND_DIR/dist" "$FAKE_BIN"
printf '{}\n' > "${FRONTEND_DIR}/package.json"
printf '{}\n' > "${FRONTEND_DIR}/package-lock.json"
printf 'old\n' > "${FRONTEND_DIR}/dist/old.txt"

cat > "${FAKE_BIN}/npm" <<'EOF'
#!/usr/bin/env bash
set -u
if [[ "${FAKE_NPM_FAIL:-0}" == "1" ]]; then
  exit 17
fi
out_dir=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--outDir" ]]; then
    out_dir="$2"
    shift 2
  else
    shift
  fi
done
[[ -n "$out_dir" ]] || exit 18
mkdir -p "$out_dir/assets"
printf 'new\n' > "$out_dir/index.html"
printf 'asset\n' > "$out_dir/assets/app.js"
EOF
chmod +x "${FAKE_BIN}/npm"

PATH="${FAKE_BIN}:$PATH" \
UNIFIED_FRONTEND_DIR="$FRONTEND_DIR" \
bash "${PROJECT_ROOT}/scripts/build_frontend.sh" >/dev/null

[[ -s "${FRONTEND_DIR}/dist/index.html" ]] || fail "new index.html was not published"
[[ -s "${FRONTEND_DIR}/dist/assets/app.js" ]] || fail "new assets were not published"
[[ ! -e "${FRONTEND_DIR}/dist/old.txt" ]] || fail "old dist remained after the atomic switch"
if find "$FRONTEND_DIR" -maxdepth 1 \( -name '.dist-build.*' -o -name '.dist-backup.*' \) | grep -q .; then
  fail "temporary build directories were not cleaned"
fi

printf 'stable\n' > "${FRONTEND_DIR}/dist/stable.txt"
if PATH="${FAKE_BIN}:$PATH" \
  FAKE_NPM_FAIL=1 \
  UNIFIED_FRONTEND_DIR="$FRONTEND_DIR" \
  bash "${PROJECT_ROOT}/scripts/build_frontend.sh" >/dev/null 2>&1; then
  fail "failed npm build must return non-zero"
fi
[[ -s "${FRONTEND_DIR}/dist/stable.txt" ]] || fail "failed build replaced the stable dist"

echo "PASS: atomic production frontend build"
