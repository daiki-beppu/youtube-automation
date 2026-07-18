#!/usr/bin/env bash
# 定期実行の前提診断（/automation-schedule Step 0）（#1892）。
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

# --- 実行環境（少なくとも一方が必要） ---
have_runtime=0
if command -v claude >/dev/null 2>&1; then
  report ok runtime-claude "claude CLI あり（非対話実行: claude -p）"
  have_runtime=1
else
  report warn runtime-claude "claude CLI が無い"
fi
if command -v codex >/dev/null 2>&1; then
  report ok runtime-codex "codex CLI あり（非対話実行: codex exec）"
  have_runtime=1
else
  report warn runtime-codex "codex CLI が無い"
fi
if [ "$have_runtime" -eq 0 ]; then
  report fail runtime "claude / codex のどちらの CLI も見つからない（いずれかをインストールする）"
fi

# --- スケジューラー経路 ---
case "$(uname -s)" in
  Darwin)
    if command -v launchctl >/dev/null 2>&1; then
      report ok scheduler "launchd（launchctl）利用可"
    else
      report fail scheduler "launchctl が見つからない"
    fi
    ;;
  *)
    if command -v crontab >/dev/null 2>&1; then
      report ok scheduler "cron（crontab）利用可"
    else
      report fail scheduler "crontab が見つからない"
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
