#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

if ! lefthook_bin="$(command -v lefthook 2>/dev/null)"; then
  echo "error: lefthook is not available in PATH; enter via nix develop or direnv." >&2
  exit 1
fi

if ! "$lefthook_bin" install --force; then
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
