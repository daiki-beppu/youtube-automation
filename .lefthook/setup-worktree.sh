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

# explicit setup 経路は fail-closed: devShell 入場後にまず依存同期を行い、失敗したら
# 後続コマンドを実行せず exit 非 0 で停止する（issue #2125）。対話 shell（direnv
# .envrc → flake.nix shellHook）の warning 継続方針とは意図的に分離している
command=(bash "$checkout_root/.lefthook/sync-deps.sh" "${command[@]}")

# 並列 worktree 間の Nix キャッシュ競合を避けるため、NIX_CACHE_HOME を worktree 分離
# TMPDIR（issue #2088）配下へ向ける（issue #2089）。direnv 経路は .envrc 側でも同値を
# export するが、nix develop フォールバック経路は .envrc を通らず flake 評価が
# shellHook より先に走るため、ここでの export が唯一の分離点になる。解決に失敗した
# 場合は共有キャッシュのまま続行する（分離は品質ゲートではなく干渉回避のため fail-open）
if worktree_tmpdir="$(bash "$checkout_root/.lefthook/worktree-tmpdir.sh" 2>/dev/null)"; then
  export NIX_CACHE_HOME="$worktree_tmpdir/nix-cache"
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
