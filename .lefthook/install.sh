#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

# sandbox 化された takt worker 等、hooks を書き込めない環境向けの安全なスキップ
# （ゲートは CI 側で担保される。issue #1999）
if [ "${YOUTUBE_AUTOMATION_SKIP_LEFTHOOK:-0}" = "1" ]; then
  echo "info: YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1 のため lefthook install をスキップします。" >&2
  exit 0
fi

if ! lefthook_bin="$(command -v lefthook 2>/dev/null)"; then
  echo "error: lefthook is not available in PATH; enter via nix develop or direnv." >&2
  exit 1
fi

run_lefthook_install() {
  local attempt

  for attempt in 1 2 3; do
    if "$lefthook_bin" install --force; then
      return 0
    fi

    if [ "$attempt" -lt 3 ]; then
      sleep 0.2
    fi
  done

  return 1
}

if ! run_lefthook_install; then
  echo "error: lefthook install failed; run 'nix develop --command bash .lefthook/install.sh' after fixing the error." >&2
  exit 1
fi

hooks_dir="$(dirname "$(git rev-parse --git-path hooks/pre-commit)")"
mkdir -p "$hooks_dir"

install_hook_wrapper() {
  local hook_name="$1"
  local hook_path="$hooks_dir/$hook_name"
  local tmp_hook="$hooks_dir/.$hook_name.tmp.$$"

  if [ -e "$hook_path" ] && [ ! -f "$hook_path" ]; then
    echo "error: cannot install $hook_name hook because $hook_path is not a file." >&2
    return 1
  fi

  cat >"$tmp_hook" <<EOF
#!/usr/bin/env bash
set -u

if [ "\${LEFTHOOK:-}" = "0" ]; then
  exit 0
fi

installed_lefthook='$lefthook_bin'

if [ -x "\$installed_lefthook" ]; then
  exec "\$installed_lefthook" run "$hook_name" "\$@"
fi

if command -v lefthook >/dev/null 2>&1; then
  exec lefthook run "$hook_name" "\$@"
fi

echo "error: lefthook is not available in PATH; enter via nix develop or direnv." >&2
exit 1
EOF
  chmod +x "$tmp_hook"
  mv -f "$tmp_hook" "$hook_path"

  if [ ! -f "$hook_path" ] || [ ! -x "$hook_path" ]; then
    echo "error: failed to install executable $hook_name hook at $hook_path." >&2
    return 1
  fi
}

install_hook_wrapper pre-commit
install_hook_wrapper pre-push
