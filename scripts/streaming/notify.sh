#!/usr/bin/env bash
# Discord Webhook に通知を送る薄いラッパー。
#
# 使い方:
#   notify.sh "<message>"
#
# secret 経路:
#   /etc/youtube-stream-healthcheck.env (mode 0600 root:root) に
#   DISCORD_WEBHOOK_URL=<url> が書かれている前提。terraform 側で配置する。
#
# cron を壊さないため curl 失敗は exit 0 で吸収する（HTTP エラーで healthcheck が
# 失敗したことになると 5 分後に再走して結局同じ症状になる）。

set -euo pipefail

readonly ENV_FILE="/etc/youtube-stream-healthcheck.env"

if [[ ! -r "$ENV_FILE" ]]; then
  echo "notify.sh: $ENV_FILE が読めない（webhook 未設定）" >&2
  exit 0
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "notify.sh: DISCORD_WEBHOOK_URL が未設定" >&2
  exit 0
fi

# webhook URL は Discord 公式ホストの HTTPS endpoint のみ許可（SSRF 防御、Issue #166）。
# secret store 侵害時に file:// / http://169.254.169.254/... 等にすり替えられること
# を防ぐ。不正値は cron を壊さないよう exit 0 で吸収する。
if [[ ! "$DISCORD_WEBHOOK_URL" =~ ^https://(discord\.com|discordapp\.com)/api/webhooks/ ]]; then
  echo "notify.sh: DISCORD_WEBHOOK_URL が不正なホスト/スキーム" >&2
  exit 0
fi

# 引数なしで呼ばれるのは healthcheck.sh 側のバグ。Fail Fast で原因特定可能にする
# （Discord に "(empty)" が流れて原因不明アラートになるのを避ける）。
if [[ $# -lt 1 ]]; then
  echo "notify.sh: message argument required" >&2
  exit 1
fi

readonly MESSAGE="$1"

# Discord Webhook の最低限ペイロード: {"content": "..."}
# JSON エスケープは jq が無い環境でも動くよう自前で最小限のエスケープを行う
escape_json() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

payload="{\"content\":\"$(escape_json "$MESSAGE")\"}"

# HTTP エラーは握りつぶす（cron に伝播させない）
curl -sS -X POST \
  -H "Content-Type: application/json" \
  --data "$payload" \
  "$DISCORD_WEBHOOK_URL" >/dev/null || true

exit 0
