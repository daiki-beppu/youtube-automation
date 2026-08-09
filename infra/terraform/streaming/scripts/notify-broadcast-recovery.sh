#!/usr/bin/env bash
# Notify only a successful recovery; always leave the outcome in journald.

set -euo pipefail

readonly RESULT_FILE="${BROADCAST_RECOVERY_RESULT:-/var/lib/youtube-broadcast-recovery/last-result.json}"
readonly NOTIFY_SCRIPT="${YOUTUBE_STREAM_NOTIFY_SCRIPT:-/opt/youtube-stream/bin/notify.sh}"

if [[ ! -r "$RESULT_FILE" ]]; then
  printf 'result file is unavailable; notification skipped\n' \
    | systemd-cat --identifier=youtube-broadcast-recovery --priority=warning
  exit 0
fi

if grep -q '"status"[[:space:]]*:[[:space:]]*"recovered"' "$RESULT_FILE"; then
  printf 'status=recovered; sending operator notification\n' \
    | systemd-cat --identifier=youtube-broadcast-recovery
  if [[ -x "$NOTIFY_SCRIPT" ]]; then
    "$NOTIFY_SCRIPT" "YouTube live broadcast was recovered automatically" || true
  else
    printf 'notify.sh is unavailable; recovery remains recorded in journald\n' \
      | systemd-cat --identifier=youtube-broadcast-recovery --priority=warning
  fi
else
  printf 'broadcast recovery check completed without mutation\n' \
    | systemd-cat --identifier=youtube-broadcast-recovery
fi
