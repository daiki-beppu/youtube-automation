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

# direnv allow は allow ストア（$XDG_DATA_HOME/direnv/allow、既定 ~/.local/share）への
# 書込みを要する。sandbox 化された環境ではホーム配下へ書込みできず失敗するため、
# 失敗時は hard fail せず nix develop 経路へフォールバックする（issue #1999）
if command -v direnv >/dev/null 2>&1; then
  if direnv allow "$checkout_root" 2>/dev/null; then
    exec direnv exec "$checkout_root" "${command[@]}"
  fi
  echo "warning: direnv allow に失敗しました（allow ストアが書込み不可の可能性）。nix develop にフォールバックします。" >&2
fi

if command -v nix >/dev/null 2>&1; then
  exec nix develop "$checkout_root" --command "${command[@]}"
fi

echo "error: neither direnv nor nix is available in PATH." >&2
exit 1
