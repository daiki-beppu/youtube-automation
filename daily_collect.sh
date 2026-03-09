#!/bin/bash
# daily_collect.sh — YouTube Analytics データの日次自動収集
# launchd から呼び出される想定
#
# セットアップ:
#   chmod +x automation/daily_collect.sh
#   cp automation/launchd/com.youtube-channels.daily-collect.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.youtube-channels.daily-collect.plist

# launchd は最小 PATH で起動するため Homebrew を明示追加
export PATH="/opt/homebrew/bin:$PATH"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${REPO_ROOT}/automation/logs"
LOG_FILE="${LOG_DIR}/daily_collect_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# 各チャンネルのデータを収集
collect_channel() {
    local channel_dir="$1"
    local channel_name
    channel_name=$(basename "$channel_dir")

    if [[ ! -f "${channel_dir}/config/channel_config.json" ]]; then
        log "SKIP: ${channel_name} (channel_config.json not found)"
        return 0
    fi

    log "START: ${channel_name}"
    if CHANNEL_DIR="$channel_dir" python3 "${REPO_ROOT}/automation/analytics_system.py" >> "$LOG_FILE" 2>&1; then
        log "OK: ${channel_name}"
    else
        log "ERROR: ${channel_name} (exit code: $?)"
    fi
}

log "=== Daily collect started ==="

for channel_dir in "${REPO_ROOT}"/channels/*/; do
    collect_channel "$channel_dir"
done

log "=== Daily collect finished ==="

# ログローテーション: 30日超のログを削除
find "$LOG_DIR" -name "daily_collect_*.log" -mtime +30 -delete 2>/dev/null || true
