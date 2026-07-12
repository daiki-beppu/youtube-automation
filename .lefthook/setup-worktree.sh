#!/usr/bin/env bash
set -euo pipefail

if ! checkout_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "error: run this script from a Git checkout or worktree." >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  command=(bash "$checkout_root/.lefthook/install.sh")
else
  command=("$@")
fi

if command -v direnv >/dev/null 2>&1; then
  direnv allow "$checkout_root"
  exec direnv exec "$checkout_root" "${command[@]}"
fi

if command -v nix >/dev/null 2>&1; then
  exec nix develop "$checkout_root" --command "${command[@]}"
fi

echo "error: neither direnv nor nix is available in PATH." >&2
exit 1
