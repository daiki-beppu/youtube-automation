#!/usr/bin/env bash
# 並列 run 間の共有 TMPDIR 競合を避けるため、worktree ごとに分離した一時ディレクトリを
# 決定して stdout へ 1 行出力する（issue #2088）。
#
# macOS の TMPDIR は per-user のグローバル値のため、複数 worktree の並列実行
# （takt concurrency 5 / 手動 worktree の並行 pytest）が同一パスへ書くと、
# tests/conftest.py の stale cleanup（PID 生存確認 → rmtree）や pytest の
# 一時ディレクトリが run 間で干渉しうる。devShell 入場時（flake.nix shellHook）に
# 本スクリプトの出力を TMPDIR へ export することで、各 run の一時ファイルを
# worktree 単位で分離する。
#
# 分離先は checkout 内ではなく「共有 TMPDIR 配下の worktree ごとの決定的な
# サブディレクトリ」にする。checkout 内（<root>/.tmp 等）へ置くと pytest の
# tmp_path が git checkout 内部に着地し、「git checkout の外」を前提とする
# 既存契約テストの git rev-parse 意味論が変わってしまうため。
#
# - TMPDIR が既に checkout 内を指す場合（takt core が注入する
#   <clone>/.takt/.runtime/tmp 等）はその隔離を尊重し、現値をそのまま出力する
# - TMPDIR が既に本スクリプトの出力（再入場）なら現値をそのまま出力する（冪等）
# - それ以外は ${TMPDIR:-/tmp}/yt-automation-tmp-<slug>-<cksum> を作成して出力する
set -euo pipefail

if ! checkout_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "error: run this script from a Git checkout or worktree." >&2
  exit 1
fi

case "${TMPDIR:-}" in
"$checkout_root"/*)
  printf '%s\n' "$TMPDIR"
  exit 0
  ;;
esac

slug="$(basename "$checkout_root" | tr -cd 'A-Za-z0-9._-' | cut -c1-32)"
digest="$(printf '%s' "$checkout_root" | cksum | cut -d' ' -f1)"
isolated_name="yt-automation-tmp-${slug}-${digest}"

case "${TMPDIR:-}" in
*/"$isolated_name" | */"$isolated_name"/)
  printf '%s\n' "$TMPDIR"
  exit 0
  ;;
esac

shared_root="${TMPDIR:-/tmp}"
worktree_tmpdir="${shared_root%/}/$isolated_name"
mkdir -p "$worktree_tmpdir"
chmod 700 "$worktree_tmpdir"
printf '%s\n' "$worktree_tmpdir"
