#!/usr/bin/env bash
set -u

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

if ! lefthook_bin="$(command -v lefthook 2>/dev/null)"; then
  echo "error: lefthook is not available in PATH; enter via nix develop or direnv." >&2
  exit 1
fi

if ! "$lefthook_bin" install --force; then
  echo "error: lefthook install failed; run 'nix develop --command lefthook install --force' after fixing the error." >&2
  exit 1
fi

hooks_dir="$(dirname "$(git rev-parse --git-path hooks/pre-commit)")"
mkdir -p "$hooks_dir"

install_hook_wrapper() {
  local hook_name="$1"
  local hook_path="$hooks_dir/$hook_name"

  cat >"$hook_path" <<EOF
#!/usr/bin/env bash
set -u

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
  chmod +x "$hook_path"
}

install_hook_wrapper pre-commit
install_hook_wrapper pre-push
