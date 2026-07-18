#!/usr/bin/env bash
# 定期実行の実体ラッパー（scheduler_job.sh が登録するジョブから起動される）（#1892）。
#
# usage: run_scheduled.sh --channel-dir <path> --runtime claude|codex
#
# `workflow.scheduled_automation` を読み、以下を担保する:
# - enabled=false なら何もしない（config を無効化すればジョブ削除前でも安全に停止する）
# - prevent_concurrent_runs=true なら lock で並行起動を抑止する
# - allow_external_publish=false なら実行プロンプトに外部反映禁止の指示を必ず付ける
# - 失敗時は max_retries 回まで retry_delay_seconds を空けて再試行する
set -u

CHANNEL_DIR_ARG=""
RUNTIME=""
while [ $# -gt 0 ]; do
  case "$1" in
    --channel-dir) CHANNEL_DIR_ARG="$2"; shift 2 ;;
    --runtime) RUNTIME="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$CHANNEL_DIR_ARG" ] || [ -z "$RUNTIME" ]; then
  echo "usage: run_scheduled.sh --channel-dir <path> --runtime claude|codex" >&2
  exit 2
fi
cd "$CHANNEL_DIR_ARG" || exit 2

STATE_DIR=".automation-schedule"
LOG_DIR="$STATE_DIR/logs"
LOCK_DIR="$STATE_DIR/lock"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE"; }

# --- config 読み出し（loader 検証済みの effective 設定を単一ソースにする） ---
CONFIG_JSON="$(uv run python .claude/skills/automation-schedule/references/schedule_config.py show 2>>"$LOG_FILE")" || {
  log "config の読み出しに失敗（schedule_config.py show が非 0）"
  exit 1
}
cfg() { printf '%s' "$CONFIG_JSON" | uv run python -c "import json,sys; print(json.load(sys.stdin)[sys.argv[1]])" "$1"; }

ENABLED="$(cfg enabled)"
if [ "$ENABLED" != "True" ]; then
  log "scheduled_automation.enabled=false のためスキップ"
  exit 0
fi

TARGET_WORKFLOW="$(cfg target_workflow)"
MAX_RETRIES="$(cfg max_retries)"
RETRY_DELAY="$(cfg retry_delay_seconds)"
PREVENT_CONCURRENT="$(cfg prevent_concurrent_runs)"
NOTIFICATION="$(cfg notification)"
ALLOW_PUBLISH="$(cfg allow_external_publish)"

# --- 実行排他（並行起動禁止） ---
if [ "$PREVENT_CONCURRENT" = "True" ]; then
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" >"$LOCK_DIR/pid"
  else
    old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      log "前回実行（pid=$old_pid）が生存中のためスキップ（prevent_concurrent_runs）"
      exit 0
    fi
    log "stale lock（pid=${old_pid:-unknown}）を回収して続行"
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" && echo "$$" >"$LOCK_DIR/pid"
  fi
  trap 'rm -rf "$LOCK_DIR"' EXIT
fi

# --- 実行プロンプト（外部公開ゲート） ---
PROMPT="/${TARGET_WORKFLOW}"
if [ "$ALLOW_PUBLISH" != "True" ]; then
  PROMPT="$PROMPT

制約: このセッションでは YouTube への書き込み（アップロード・公開・メタデータ更新・コメント投稿などの外部反映）を一切実行しないこと。外部反映を伴うステップの直前で停止し、そこまでの結果を報告して終了する。"
fi

run_once() {
  case "$RUNTIME" in
    claude) claude -p "$PROMPT" >>"$LOG_FILE" 2>&1 ;;
    codex) codex exec "$PROMPT" >>"$LOG_FILE" 2>&1 ;;
    *) log "unknown runtime: $RUNTIME"; return 2 ;;
  esac
}

notify() { # $1=message
  if [ "$NOTIFICATION" = "terminal" ] && command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$1\" with title \"automation-schedule\"" 2>/dev/null || true
  fi
}

attempt=0
max_attempts=$((MAX_RETRIES + 1))
while [ "$attempt" -lt "$max_attempts" ]; do
  attempt=$((attempt + 1))
  log "実行開始 (attempt ${attempt}/${max_attempts}, runtime=$RUNTIME, prompt=/${TARGET_WORKFLOW}, external_publish=$ALLOW_PUBLISH)"
  if run_once; then
    log "実行成功"
    notify "定期実行が完了しました (/${TARGET_WORKFLOW})"
    exit 0
  fi
  log "実行失敗 (attempt ${attempt}/${max_attempts})"
  if [ "$attempt" -lt "$max_attempts" ]; then
    sleep "$RETRY_DELAY"
  fi
done
notify "定期実行が失敗しました (/${TARGET_WORKFLOW}, ${max_attempts} 回試行)"
exit 1
