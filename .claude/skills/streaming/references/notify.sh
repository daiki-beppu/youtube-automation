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

# source は使わず限定パーサで読む（env ファイル改ざん時の任意コード実行を防ぐ）。
# 形式: 1 行 1 KEY=VALUE。値が "..." で囲まれていても tr で剥がす（CRLF 混入も同様）。
# grep が一致行を見つけられないケースでも cron を壊さないよう `|| true` で吸収する
# （`set -euo pipefail` 下で grep の exit 1 が pipefail 経由で script 自体を落とすのを防ぐ）。
DISCORD_WEBHOOK_URL=$(grep -E '^DISCORD_WEBHOOK_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '\r"' || true)

if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "notify.sh: DISCORD_WEBHOOK_URL が未設定" >&2
  exit 0
fi

# webhook URL は Discord 公式ホストの HTTPS endpoint のみ許可（SSRF 防御、Issue #166 / #174）。
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

# HTTP エラーは握りつぶす（cron に伝播させない）。
# issue #174: Discord 障害時に curl が無限に待ちつつ cron 5 分間隔で累積し FD/メモリが枯渇するのを防ぐため、
# --connect-timeout / --max-time を必須化する（接続 5 秒・全体 10 秒の硬い天井）。
curl --connect-timeout 5 --max-time 10 -sS -X POST \
  -H "Content-Type: application/json" \
  --data "$payload" \
  "$DISCORD_WEBHOOK_URL" >/dev/null || true

exit 0
