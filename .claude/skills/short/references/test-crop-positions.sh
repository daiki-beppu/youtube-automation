#!/usr/bin/env bash
# Step 3: 16:9 → 9:16 クロップ位置のテストフレームを生成する。
# center / x=400 / x=350 の 3 パターンを /tmp に書き出し `open` で表示する。
#
# Usage: test-crop-positions.sh <master_video> [timestamp_sec=30]
set -euo pipefail

MASTER="${1:?usage: $(basename "$0") <master_video> [timestamp_sec]}"
TS="${2:-30}"

ffmpeg -y -ss "$TS" -i "$MASTER" -frames:v 1 \
  -vf "crop=ih*9/16:ih,scale=1080:1920" /tmp/short-test-center.jpg
ffmpeg -y -ss "$TS" -i "$MASTER" -frames:v 1 \
  -vf "crop=ih*9/16:ih:400:0,scale=1080:1920" /tmp/short-test-x400.jpg
ffmpeg -y -ss "$TS" -i "$MASTER" -frames:v 1 \
  -vf "crop=ih*9/16:ih:350:0,scale=1080:1920" /tmp/short-test-x350.jpg

open /tmp/short-test-*.jpg
