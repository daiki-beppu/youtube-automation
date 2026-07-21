#!/usr/bin/env bash
# ネイティブ定期実行の前提診断（/automation-schedule Step 0）（#1892, #2369）。
# チャンネルリポジトリ直下で実行し、`ok|fail|warn <check> <detail>` を 1 行ずつ出力する。
# fail が 1 件でもあれば exit 1（SKILL.md 側はこれを hard gate に使う）。
set -u

status=0

report() { # $1=level $2=name $3=detail
  printf '%s\t%s\t%s\n' "$1" "$2" "$3"
  if [ "$1" = "fail" ]; then status=1; fi
}

# --- config ---
if [ -f config/channel/workflow.json ]; then
  report ok config-workflow "config/channel/workflow.json あり"
else
  report fail config-workflow "config/channel/workflow.json が無い（チャンネルリポジトリ直下で実行し、/channel-new で config を生成する）"
fi

if command -v uv >/dev/null 2>&1; then
  report ok uv "$(uv --version 2>/dev/null | head -1)"
else
  report fail uv "uv が無い（/setup を実行する）"
fi

# --- 実行中製品とネイティブ経路 ---
if [ -n "${CODEX_THREAD_ID:-}" ]; then
  report ok product-codex "Codex task を検出。既定 backend: Codex Automation"
elif [ -n "${CLAUDECODE:-}" ]; then
  report ok product-claude "Claude Code を検出。依存性に応じて /schedule Cloud Job または Cowork local を選ぶ"
else
  report warn product "実行中製品を自動判定できないため、Codex / Claude をユーザーに確認する"
fi
report warn native-management "ネイティブ scheduler の作成・status・disable は製品の Scheduled 管理機能で行う（CLI で代替しない）"

# --- OS fallback（利用可能性のみ。自動選択しない） ---
case "$(uname -s)" in
  Darwin)
    if command -v launchctl >/dev/null 2>&1; then
      report warn os-fallback "launchd 利用可。明示選択 + --confirm-os-fallback の場合だけ使用"
    else
      report warn os-fallback "launchctl が見つからない（ネイティブ backend には影響なし）"
    fi
    ;;
  *)
    if command -v crontab >/dev/null 2>&1; then
      report warn os-fallback "cron 利用可。明示選択 + --confirm-os-fallback の場合だけ使用"
    else
      report warn os-fallback "crontab が見つからない（ネイティブ backend には影響なし）"
    fi
    ;;
esac

# --- 認証・通知 ---
if [ -f auth/token.json ]; then
  report ok auth "auth/token.json あり"
else
  report warn auth "auth/token.json が無い（外部公開を有効化する場合は /setup で OAuth を先に通す）"
fi
if [ "$(uname -s)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
  report ok notification "osascript（terminal 通知）利用可"
else
  report warn notification "terminal 通知経路なし（notification: none を推奨）"
fi

exit "$status"
