#!/usr/bin/env bash
# 明示選択された OS fallback の作成・更新・確認・停止（#1892, #2369）。
#
# usage: scheduler_job.sh install|status|disable --backend os-fallback [--confirm-os-fallback] [--runtime claude|codex]
#
# - macOS: launchd（~/Library/LaunchAgents/<label>.plist）。同一 label を上書きするため
#   再実行は常に「更新」になり、重複ジョブを作らない。
# - その他: crontab。`# <label>` マーカー行で既存行を置換するため同じく重複しない。
# - label はチャンネルディレクトリ名から決まる: com.youtube-automation.<dir>.schedule
set -eu

COMMAND="${1:-}"
shift || true
RUNTIME="claude"
BACKEND=""
CONFIRM_OS_FALLBACK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --runtime) RUNTIME="$2"; shift 2 ;;
    --backend) BACKEND="$2"; shift 2 ;;
    --confirm-os-fallback) CONFIRM_OS_FALLBACK=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
case "$COMMAND" in install|status|disable) ;; *)
  echo "usage: scheduler_job.sh install|status|disable --backend os-fallback [--confirm-os-fallback] [--runtime claude|codex]" >&2
  exit 2
  ;;
esac
if [ "$BACKEND" != "os-fallback" ]; then
  echo "scheduler_job.sh は明示選択された OS fallback 専用です。--backend os-fallback が必要です" >&2
  exit 2
fi
if [ "$COMMAND" = "install" ] && [ "$CONFIRM_OS_FALLBACK" -ne 1 ]; then
  echo "OS fallback は自動登録しません。制約を提示してユーザー承認後に --confirm-os-fallback を付けてください" >&2
  exit 2
fi
case "$RUNTIME" in claude|codex) ;; *)
  echo "--runtime は claude または codex を指定する（got: $RUNTIME）" >&2
  exit 2
  ;;
esac

CHANNEL_DIR="$(pwd)"
LABEL="com.youtube-automation.$(basename "$CHANNEL_DIR").schedule"
RUN_SCRIPT="$CHANNEL_DIR/.claude/skills/automation-schedule/references/run_scheduled.sh"
BACKEND_SCRIPT="$CHANNEL_DIR/.claude/skills/automation-schedule/references/schedule_backend.py"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
IS_DARWIN=0
[ "$(uname -s)" = "Darwin" ] && IS_DARWIN=1

read_config() { # effective 設定（loader 検証済み）を単一ソースとして読む
  uv run python .claude/skills/automation-schedule/references/schedule_config.py show
}

weekday_num() { # launchd/cron 共通: 0=sun .. 6=sat
  case "$1" in
    sun) echo 0 ;; mon) echo 1 ;; tue) echo 2 ;; wed) echo 3 ;;
    thu) echo 4 ;; fri) echo 5 ;; sat) echo 6 ;;
    *) echo "unknown cadence day: $1" >&2; return 1 ;;
  esac
}

install_job() {
  uv run python "$BACKEND_SCRIPT" --channel-dir "$CHANNEL_DIR" guard --backend os-fallback >/dev/null
  CONFIG_JSON="$(read_config)"
  py() { printf '%s' "$CONFIG_JSON" | uv run python -c "$1"; }

  ENABLED="$(py 'import json,sys; print(json.load(sys.stdin)["enabled"])')"
  if [ "$ENABLED" != "True" ]; then
    echo "scheduled_automation.enabled が false です。先に schedule_config.py generate --enable で有効化してください" >&2
    exit 1
  fi
  RUN_TIME="$(py 'import json,sys; print(json.load(sys.stdin)["run_time"])')"
  TZ_NAME="$(py 'import json,sys; print(json.load(sys.stdin)["timezone"])')"
  CADENCE="$(py 'import json,sys; print(" ".join(json.load(sys.stdin)["cadence"]))')"
  HOUR="${RUN_TIME%%:*}"
  MINUTE="${RUN_TIME##*:}"

  SYSTEM_TZ="$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || true)"
  if [ -n "$SYSTEM_TZ" ] && [ "$SYSTEM_TZ" != "$TZ_NAME" ]; then
    echo "warn: config の timezone ($TZ_NAME) とシステム TZ ($SYSTEM_TZ) が異なります。スケジュールはシステム TZ の壁時計で解釈されます" >&2
  fi

  if [ "$IS_DARWIN" -eq 1 ]; then
    {
      printf '<?xml version="1.0" encoding="UTF-8"?>\n'
      printf '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
      printf '<plist version="1.0">\n<dict>\n'
      printf '  <key>Label</key><string>%s</string>\n' "$LABEL"
      printf '  <key>WorkingDirectory</key><string>%s</string>\n' "$CHANNEL_DIR"
      printf '  <key>ProgramArguments</key>\n  <array>\n'
      printf '    <string>/bin/bash</string>\n'
      printf '    <string>%s</string>\n' "$RUN_SCRIPT"
      printf '    <string>--channel-dir</string>\n    <string>%s</string>\n' "$CHANNEL_DIR"
      printf '    <string>--runtime</string>\n    <string>%s</string>\n' "$RUNTIME"
      printf '  </array>\n'
      printf '  <key>StartCalendarInterval</key>\n  <array>\n'
      for day in $CADENCE; do
        wd="$(weekday_num "$day")"
        printf '    <dict>\n'
        printf '      <key>Weekday</key><integer>%s</integer>\n' "$wd"
        printf '      <key>Hour</key><integer>%s</integer>\n' "$((10#$HOUR))"
        printf '      <key>Minute</key><integer>%s</integer>\n' "$((10#$MINUTE))"
        printf '    </dict>\n'
      done
      printf '  </array>\n'
      printf '</dict>\n</plist>\n'
    } >"$PLIST"
    # 既存ジョブがあれば一度外してから読み直す（同一 label の更新。重複作成しない）
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    uv run python "$BACKEND_SCRIPT" --channel-dir "$CHANNEL_DIR" record --backend os-fallback --external-id "$LABEL" >/dev/null
    echo "launchd job を作成・更新しました: $LABEL ($RUN_TIME [$CADENCE] runtime=$RUNTIME)"
  else
    CRON_DAYS="$(for day in $CADENCE; do weekday_num "$day"; done | paste -sd, -)"
    CRON_LINE="$((10#$MINUTE)) $((10#$HOUR)) * * $CRON_DAYS /bin/bash $RUN_SCRIPT --channel-dir $CHANNEL_DIR --runtime $RUNTIME # $LABEL"
    (crontab -l 2>/dev/null | grep -vF "# $LABEL"; echo "$CRON_LINE") | crontab -
    uv run python "$BACKEND_SCRIPT" --channel-dir "$CHANNEL_DIR" record --backend os-fallback --external-id "$LABEL" >/dev/null
    echo "crontab entry を作成・更新しました: $LABEL"
  fi
}

status_job() {
  uv run python "$BACKEND_SCRIPT" --channel-dir "$CHANNEL_DIR" guard --backend os-fallback >/dev/null
  echo "--- backend identity ---"
  uv run python "$BACKEND_SCRIPT" --channel-dir "$CHANNEL_DIR" show
  echo "--- config (effective) ---"
  read_config
  echo "--- scheduler ---"
  if [ "$IS_DARWIN" -eq 1 ]; then
    if [ -f "$PLIST" ]; then
      echo "plist: $PLIST"
      launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | head -20 || echo "launchd 未登録（plist はあるがロードされていない）"
    else
      echo "launchd job 未作成（$LABEL）"
    fi
  else
    crontab -l 2>/dev/null | grep -F "# $LABEL" || echo "crontab entry 未作成（$LABEL）"
  fi
  echo "--- 直近ログ ---"
  ls -t .automation-schedule/logs/ 2>/dev/null | head -3 || echo "(実行ログなし)"
}

disable_job() {
  uv run python "$BACKEND_SCRIPT" --channel-dir "$CHANNEL_DIR" guard --backend os-fallback >/dev/null
  if [ "$IS_DARWIN" -eq 1 ]; then
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "launchd job を停止・削除しました: $LABEL"
  else
    (crontab -l 2>/dev/null | grep -vF "# $LABEL") | crontab -
    echo "crontab entry を削除しました: $LABEL"
  fi
  uv run python "$BACKEND_SCRIPT" --channel-dir "$CHANNEL_DIR" disable --backend os-fallback >/dev/null || true
  echo "config 側も無効化する場合: uv run python .claude/skills/automation-schedule/references/schedule_config.py generate --disable"
}

case "$COMMAND" in
  install) install_job ;;
  status) status_job ;;
  disable) disable_job ;;
esac
