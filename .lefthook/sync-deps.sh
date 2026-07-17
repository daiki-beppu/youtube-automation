#!/usr/bin/env bash
# explicit setup 経路（.lefthook/setup-worktree.sh）専用の依存同期ラッパー。
# 対話 shell（direnv .envrc → flake.nix shellHook）は uv sync 失敗を warning に
# 留めて入場を継続するが、この経路は fail-closed: 同期に失敗したら後続コマンドを
# 実行せず exit 非 0 で停止する（issue #2125）。nix-direnv のキャッシュ命中時は
# shellHook 自体が再実行されないため、同期はここで明示的に行う。
set -euo pipefail

if ! checkout_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "error: run this script from a Git checkout or worktree." >&2
  exit 1
fi

# pyproject.toml の無い checkout（fixture 等）では同期対象が無いためスキップする
if [ -f "$checkout_root/pyproject.toml" ]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is not available in PATH; enter via nix develop or direnv." >&2
    exit 1
  fi
  if ! (cd "$checkout_root" && uv sync --quiet); then
    echo "error: uv sync failed; dependencies were not synchronized. Fix the sync error before rerunning (see docs/development.md)." >&2
    exit 1
  fi
fi

exec "$@"
