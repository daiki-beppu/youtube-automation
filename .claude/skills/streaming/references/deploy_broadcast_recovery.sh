#!/usr/bin/env bash
# deploy_broadcast_recovery.sh — ephemeral OAuth を注入して broadcast recovery timer を配備する
#
# Usage:
#   OP_BROADCAST_RECOVERY_TOKEN_REF='op://<vault>/<item>/<field>' \
#   OP_BROADCAST_RECOVERY_CLIENT_SECRETS_REF='op://<vault>/<item>/<field>' \
#   deploy_broadcast_recovery.sh [--tf-dir DIR] [--auto-approve]

set -euo pipefail

TF_DIR="infra/terraform/streaming"
AUTO_APPROVE=false

log() { printf '\033[0;36m[broadcast-recovery-deploy]\033[0m %s\n' "$*"; }
ok() { printf '\033[0;32m[ok]\033[0m %s\n' "$*"; }
error() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }
usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tf-dir) TF_DIR="$2"; shift 2 ;;
    --tf-dir=*) TF_DIR="${1#*=}"; shift ;;
    --auto-approve) AUTO_APPROVE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) error "未知の引数: $1"; usage; exit 2 ;;
  esac
done

for command_name in terraform op python3; do
  command -v "$command_name" >/dev/null 2>&1 || {
    error "$command_name が見つかりません"
    exit 1
  }
done

for ref_name in OP_BROADCAST_RECOVERY_TOKEN_REF OP_BROADCAST_RECOVERY_CLIENT_SECRETS_REF; do
  [[ -n "${!ref_name:-}" ]] || {
    error "$ref_name に 1Password secret reference を設定してください"
    exit 1
  }
done

[[ -d "$TF_DIR" && -f "$TF_DIR/main.tf" ]] || {
  error "Terraform module が見つかりません: $TF_DIR"
  exit 1
}

TF_VAR_broadcast_recovery_youtube_token_json="$(op read "$OP_BROADCAST_RECOVERY_TOKEN_REF")" || {
  status=$?
  error "1Password token の取得に失敗しました"
  exit "$status"
}
TF_VAR_broadcast_recovery_client_secrets_json="$(op read "$OP_BROADCAST_RECOVERY_CLIENT_SECRETS_REF")" || {
  status=$?
  error "1Password client secrets の取得に失敗しました"
  exit "$status"
}
export TF_VAR_broadcast_recovery_youtube_token_json
export TF_VAR_broadcast_recovery_client_secrets_json

cleanup() {
  unset TF_VAR_broadcast_recovery_youtube_token_json
  unset TF_VAR_broadcast_recovery_client_secrets_json
}
trap cleanup EXIT HUP INT TERM

for json_value in \
  "$TF_VAR_broadcast_recovery_youtube_token_json" \
  "$TF_VAR_broadcast_recovery_client_secrets_json"; do
  printf '%s' "$json_value" | python3 -m json.tool >/dev/null || {
    error "1Password から取得した値が JSON ではありません"
    exit 1
  }
done

if command -v shasum >/dev/null 2>&1; then
  CREDENTIALS_REVISION="$(printf '%s\0%s' \
    "$TF_VAR_broadcast_recovery_youtube_token_json" \
    "$TF_VAR_broadcast_recovery_client_secrets_json" | shasum -a 256 | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  CREDENTIALS_REVISION="$(printf '%s\0%s' \
    "$TF_VAR_broadcast_recovery_youtube_token_json" \
    "$TF_VAR_broadcast_recovery_client_secrets_json" | sha256sum | awk '{print $1}')"
else
  error "shasum または sha256sum が見つかりません"
  exit 1
fi

export TF_VAR_enable_broadcast_recovery=true
export TF_VAR_broadcast_recovery_credentials_revision="$CREDENTIALS_REVISION"

log "terraform plan（OAuth JSON は ephemeral のため plan/state/triggers に保存されません）"
terraform -chdir="$TF_DIR" plan

log "terraform apply"
if $AUTO_APPROVE; then
  terraform -chdir="$TF_DIR" apply -auto-approve
else
  terraform -chdir="$TF_DIR" apply
fi

ok "youtube-broadcast-recovery.timer の配備が完了しました"
