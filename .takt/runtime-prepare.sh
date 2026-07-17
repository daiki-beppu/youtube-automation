#!/usr/bin/env bash
# takt runtime.prepare スクリプト（issue #1999 / #2163）。
# sandbox 化された worker はホームディレクトリ配下（~/.local/share 等）へ
# 書込みできず、direnv の allow ストア（$XDG_DATA_HOME/direnv/allow）への
# 書込みと lefthook install が反復失敗して run が停滞する。
# さらに、親 process から sibling worktree の TMPDIR / XDG_* / UV_CACHE_DIR を
# 継承すると、別 worktree の cleanup・権限変更に巻き込まれて test collection
# 前に停止する（issue #2163）。current TAKT_RUNTIME_ROOT を唯一の path source
# として effective runtime path 全体をここで再構成する。
# ここで stdout に出力した KEY=VALUE 行は takt が worker 環境へ注入する:
# - TMPDIR / XDG_CACHE_HOME / XDG_CONFIG_HOME / XDG_DATA_HOME / XDG_STATE_HOME /
#   UV_CACHE_DIR: current runtime root 配下へ向け、sibling worktree 由来の
#   継承値を上書きする
# - YOUTUBE_AUTOMATION_SKIP_LEFTHOOK: flake.nix shellHook / .lefthook/install.sh
#   に lefthook install を安全にスキップさせる（ゲートは CI 側で担保）
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

mkdir -p "$tmp_dir" "$cache_dir" "$config_dir" "$data_dir" "$state_dir" "$uv_cache_dir"

echo "TMPDIR=${tmp_dir}"
echo "XDG_CACHE_HOME=${cache_dir}"
echo "XDG_CONFIG_HOME=${config_dir}"
echo "XDG_DATA_HOME=${data_dir}"
echo "XDG_STATE_HOME=${state_dir}"
echo "UV_CACHE_DIR=${uv_cache_dir}"
echo "YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1"
