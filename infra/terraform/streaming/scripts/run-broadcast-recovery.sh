#!/usr/bin/env bash
# Run broadcast recovery only while the 24/7 ffmpeg service is active.

set -euo pipefail

readonly RESULT_FILE="${BROADCAST_RECOVERY_RESULT:-/var/lib/youtube-broadcast-recovery/last-result.json}"
readonly RECOVERY_CLI="${BROADCAST_RECOVERY_CLI:-/opt/youtube-stream/broadcast-recovery/venv/bin/yt-stream-broadcast-recover}"
readonly STREAM_ID_B64="${BROADCAST_RECOVERY_STREAM_ID_B64:?BROADCAST_RECOVERY_STREAM_ID_B64 is required}"
readonly TITLE_B64="${BROADCAST_RECOVERY_TITLE_B64:?BROADCAST_RECOVERY_TITLE_B64 is required}"

umask 0077
mkdir -p "$(dirname "$RESULT_FILE")"
tmp_file="$(mktemp "${RESULT_FILE}.tmp.XXXXXX")"
cleanup() { rm -f "$tmp_file"; }
trap cleanup EXIT HUP INT TERM

write_result() {
  printf '%s\n' "$1" >"$tmp_file"
  printf '%s\n' "$1" | systemd-cat --identifier=youtube-broadcast-recovery
  mv -f "$tmp_file" "$RESULT_FILE"
}

BROADCAST_RECOVERY_STREAM_ID="$(printf '%s' "$STREAM_ID_B64" | base64 --decode)"
BROADCAST_RECOVERY_TITLE="$(printf '%s' "$TITLE_B64" | base64 --decode)"
export BROADCAST_RECOVERY_STREAM_ID BROADCAST_RECOVERY_TITLE

if ! systemctl is-active --quiet youtube-stream.service; then
  write_result "{\"status\":\"waiting_ingest\",\"action\":\"none_stream_service_inactive\",\"stream_id\":\"$BROADCAST_RECOVERY_STREAM_ID\",\"broadcast_id\":null,\"dry_run\":false,\"changed\":false}"
  exit 0
fi

if output="$("$RECOVERY_CLI" \
  --stream-id "$BROADCAST_RECOVERY_STREAM_ID" \
  --title "$BROADCAST_RECOVERY_TITLE")"; then
  write_result "$output"
else
  status=$?
  printf 'broadcast recovery command failed (exit=%s)\n' "$status" \
    | systemd-cat --identifier=youtube-broadcast-recovery --priority=err
  exit "$status"
fi
