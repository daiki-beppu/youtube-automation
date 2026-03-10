#!/bin/bash
# auto_post_comment.sh — 動画公開検知 + コメント自動投稿
# launchd から 30分間隔で呼び出される想定
#
# セットアップ:
#   chmod +x automation/auto_post_comment.sh
#   cp automation/launchd/com.youtube-channels.auto-post-comment.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.youtube-channels.auto-post-comment.plist
#
# 停止:
#   launchctl unload ~/Library/LaunchAgents/com.youtube-channels.auto-post-comment.plist

# launchd は最小 PATH で起動するため Homebrew を明示追加
export PATH="/opt/homebrew/bin:$PATH"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 各チャンネルで実行
for channel_dir in "${REPO_ROOT}"/channels/*/; do
    channel_name=$(basename "$channel_dir")

    if [[ ! -f "${channel_dir}/config/channel_config.json" ]]; then
        continue
    fi

    CHANNEL_DIR="$channel_dir" python3 "${REPO_ROOT}/automation/auto_post_comment.py" 2>&1 || \
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: ${channel_name} (exit code: $?)"
done
