#!/usr/bin/env bash
# takt runtime.prepare スクリプト（issue #1999）。
# sandbox 化された worker はホームディレクトリ配下（~/.local/share 等）へ
# 書込みできず、direnv の allow ストア（$XDG_DATA_HOME/direnv/allow）への
# 書込みと lefthook install が反復失敗して run が停滞する。
# ここで stdout に出力した KEY=VALUE 行は takt が worker 環境へ注入する:
# - XDG_DATA_HOME: worktree ローカルの runtime ディレクトリへ向け、
#   direnv allow の書込み先を sandbox 内で完結させる
# - YOUTUBE_AUTOMATION_SKIP_LEFTHOOK: flake.nix shellHook / .lefthook/install.sh
#   に lefthook install を安全にスキップさせる（ゲートは CI 側で担保）
set -euo pipefail

echo "XDG_DATA_HOME=${TAKT_RUNTIME_ROOT}/data"
echo "YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1"
