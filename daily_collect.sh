#!/bin/bash
# daily_collect.sh — YouTube Analytics データの日次自動収集
# launchd から呼び出される想定
#
# 使い方:
#   チャンネルリポのルートから実行:
#     ./automation/daily_collect.sh
#   または CHANNEL_DIR を指定:
#     CHANNEL_DIR=/path/to/channel ./automation/daily_collect.sh

# launchd は最小 PATH で起動するため Homebrew を明示追加
export PATH="/opt/homebrew/bin:$PATH"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# チャンネルディレクトリ: CHANNEL_DIR 環境変数 or スクリプトの親ディレクトリ
CHANNEL_DIR="${CHANNEL_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CHANNEL_NAME="$(basename "$CHANNEL_DIR")"
LOG_DIR="${CHANNEL_DIR}/automation/logs"
LOG_FILE="${LOG_DIR}/daily_collect_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

if [[ ! -f "${CHANNEL_DIR}/config/channel_config.json" ]]; then
    log "ERROR: ${CHANNEL_NAME} — config/channel_config.json not found in ${CHANNEL_DIR}"
    exit 1
fi

log "=== Daily collect started: ${CHANNEL_NAME} ==="

if CHANNEL_DIR="$CHANNEL_DIR" python3 "${SCRIPT_DIR}/analytics_system.py" >> "$LOG_FILE" 2>&1; then
    log "OK: ${CHANNEL_NAME}"
else
    log "ERROR: ${CHANNEL_NAME} (exit code: $?)"
fi

log "=== Daily collect finished: ${CHANNEL_NAME} ==="

# ログローテーション: 30日超のログを削除
find "$LOG_DIR" -name "daily_collect_*.log" -mtime +30 -delete 2>/dev/null || true
