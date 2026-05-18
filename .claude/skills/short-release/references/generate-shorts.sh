#!/usr/bin/env bash
# Mode B (release 型) — JP + EN クリップショート動画を縦型に変換
#
# 引数:
#   $1 release_path
#   -s <秒>  開始位置（既定 30 秒）
#   -t <秒>  切り出し長さ（既定 40 秒）
#
# 前提:
#   ${release_path}/video/${motif}-{jp,en}.mp4 が存在すること
#   motif は release_path のベース名から先頭の "数字-" を除いたもの
set -euo pipefail

RELEASE_DIR="${1:?usage: $(basename "$0") <release_path> [-s start_sec] [-t duration_sec]}"
shift || true

START="30"
DUR="40"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s) START="$2"; shift 2 ;;
    -t) DUR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

MOTIF="$(basename "$RELEASE_DIR" | sed 's/^[0-9]*-//')"

for LANG in jp en; do
  SRC="${RELEASE_DIR}/video/${MOTIF}-${LANG}.mp4"
  OUT="${RELEASE_DIR}/video/short-${LANG}.mp4"
  if [[ ! -f "$SRC" ]]; then
    echo "skip: ${SRC} not found" >&2
    continue
  fi
  ffmpeg -y -i "$SRC" \
    -ss "$START" -t "$DUR" \
    -vf "crop=ih*9/16:ih,scale=1080:1920,fps=30" \
    -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    "$OUT"
  echo "✓ $OUT"
done
