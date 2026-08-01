#!/usr/bin/env bash
# takt runtime.prepare スクリプト（issue #1999 / #2163）。
# sandbox 化された worker はホームディレクトリ配下（~/.local/share 等）へ
# 書込みできず、direnv の allow ストア（$XDG_DATA_HOME/direnv/allow）への
# 書込みが反復失敗して run が停滞する。
# さらに、親 process から sibling worktree の TMPDIR / XDG_* / UV_CACHE_DIR を
# 継承すると、別 worktree の cleanup・権限変更に巻き込まれて test collection
# 前に停止する（issue #2163）。current TAKT_RUNTIME_ROOT を唯一の path source
# として effective runtime path 全体をここで再構成する。
# ここで stdout に出力した KEY=VALUE 行は takt が worker 環境へ注入する:
# - TMPDIR / XDG_CACHE_HOME / XDG_CONFIG_HOME / XDG_DATA_HOME / XDG_STATE_HOME /
#   UV_CACHE_DIR: current runtime root 配下へ向け、sibling worktree 由来の
#   継承値を上書きする
# - NIX_CACHE_HOME: Nix は XDG_CACHE_HOME より NIX_CACHE_HOME を優先するため、
#   XDG_CACHE_HOME だけを差し替えても sibling worktree 由来の継承値が残る。
#   .envrc / flake.nix shellHook は devShell 入場時に `$TMPDIR/nix-cache` を
#   export するが（issue #2089）、worker には direnv が無く、shellHook は
#   `nix develop` の flake 評価が終わってから走るため入場そのものを守れない。
#   継承値を持ち込んだまま評価すると別 worktree の fetcher-cache SQLite を
#   readonly で開き `attempt to write a readonly database` で停止する
#   （issue #3040）。ここで shellHook と同じ値を先に注入して評価前から分離し、
#   入場前後で cache path が動かないようにする
set -euo pipefail

if [ -z "${TAKT_RUNTIME_ROOT:-}" ]; then
  echo "error: TAKT_RUNTIME_ROOT is not set." >&2
  exit 1
fi

tmp_dir="${TAKT_RUNTIME_ROOT}/tmp"
cache_dir="${TAKT_RUNTIME_ROOT}/cache"
config_dir="${TAKT_RUNTIME_ROOT}/config"
data_dir="${TAKT_RUNTIME_ROOT}/data"
state_dir="${TAKT_RUNTIME_ROOT}/state"
uv_cache_dir="${cache_dir}/uv"
# flake.nix shellHook / .envrc が devShell 入場時に導出する値と一致させる。
# worktree-tmpdir.sh は TMPDIR が checkout 内を指すとき現値をそのまま返すため、
# worker では worktree_tmpdir == $tmp_dir になる（.nix/worktree-tmpdir.sh:28-33）
nix_cache_dir="${tmp_dir}/nix-cache"

mkdir -p "$tmp_dir" "$cache_dir" "$config_dir" "$data_dir" "$state_dir" "$uv_cache_dir" "$nix_cache_dir"

# worker sandbox は既定の ~/.cache/uv を開けず、隔離 UV_CACHE_DIR も run ごとに
# 空で始まるため、worker 側の初回 uv sync が全依存を再取得していた（issue #2539）。
# 本スクリプトは takt 本体が sandbox 外で実行するため、ここで共有キャッシュ
# （プロセス既定の UV_CACHE_DIR）を使って .venv を事前同期する。worker の
# uv run は同期済み .venv の検証だけになる。stdout は KEY=VALUE 契約のため
# uv の出力は stderr へ流し、失敗しても run は止めない（worker 側の同期に
# フォールバックする fail-open）
if [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then
  if ! uv sync --quiet 1>&2; then
    echo "warning: runtime-prepare の uv sync に失敗しました。worker 側の同期にフォールバックします。" >&2
  fi
fi

echo "TMPDIR=${tmp_dir}"
echo "XDG_CACHE_HOME=${cache_dir}"
echo "XDG_CONFIG_HOME=${config_dir}"
echo "XDG_DATA_HOME=${data_dir}"
echo "XDG_STATE_HOME=${state_dir}"
echo "UV_CACHE_DIR=${uv_cache_dir}"
echo "NIX_CACHE_HOME=${nix_cache_dir}"
