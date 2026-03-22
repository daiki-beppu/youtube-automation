#!/bin/bash
# daily_collect_all.sh — 全チャンネルの Analytics データを順次収集
# launchd から呼び出される想定

set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"

PROJECTS_DIR="$HOME/01-dev/projects"

# 全チャンネルリポを順次処理
for channel_dir in \
  "$PROJECTS_DIR/youtube-8bah" \
  "$PROJECTS_DIR/youtube-fantasy-celtic-music" \
  "$PROJECTS_DIR/youtube-rain-jazz-night"; do

  if [[ -f "$channel_dir/automation/daily_collect.sh" ]]; then
    CHANNEL_DIR="$channel_dir" bash "$channel_dir/automation/daily_collect.sh"
  fi
done
