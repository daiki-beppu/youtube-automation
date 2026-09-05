#!/usr/bin/env bash
set -euo pipefail

: "${TFSTATE_BUCKET:?}"
: "${GITHUB_EVENT_NAME:?}"
: "${GITHUB_SERVER_URL:?}"
: "${GITHUB_REPOSITORY:?}"
: "${GITHUB_RUN_ID:?}"
: "${DISCORD_WEBHOOK_URL:?}"

plan_exit=0
if terraform init -backend-config="bucket=$TFSTATE_BUCKET" -input=false; then
  terraform plan -detailed-exitcode -lock=false -input=false || plan_exit=$?
else
  plan_exit=1
fi
if [[ "$plan_exit" == 0 ]]; then
  exit 0
fi
job_exit=0
if [[ "$plan_exit" != 2 ]]; then
  kind='job 失敗'
  job_exit=1
elif [[ "$GITHUB_EVENT_NAME" == push ]]; then
  kind='apply 待ち'
else
  kind='drift 検知'
fi
run_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
payload=$(jq -cn --arg content "$kind $run_url" '{content: $content}')
curl --fail --silent --show-error --max-time 30 --output /dev/null \
  --header 'Content-Type: application/json' --data "$payload" "$DISCORD_WEBHOOK_URL"

exit "$job_exit"
