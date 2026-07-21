#!/usr/bin/env bash
# deploy_live_chat.sh — 1Password から ephemeral secret を注入して live-chat-reply を配備する
#
# Usage:
#   OP_LIVE_CHAT_TOKEN_REF='op://<vault>/<item>/<field>' \
#   OP_LIVE_CHAT_CLIENT_SECRETS_REF='op://<vault>/<item>/<field>' \
#   OP_CODEX_AUTH_REF='op://<vault>/<item>/<field>' \
#   deploy_live_chat.sh [--tf-dir DIR] [--auto-approve] <channel-dir>

set -euo pipefail

TF_DIR="infra/terraform/streaming"
AUTO_APPROVE=false
CHANNEL_DIR=""

log()   { printf '\033[0;36m[live-chat-deploy]\033[0m %s\n' "$*"; }
ok()    { printf '\033[0;32m[ok]\033[0m %s\n' "$*"; }
error() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tf-dir) TF_DIR="$2"; shift 2 ;;
        --tf-dir=*) TF_DIR="${1#*=}"; shift ;;
        --auto-approve) AUTO_APPROVE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) error "未知のオプション: $1"; usage; exit 2 ;;
        *)
            [[ -z "$CHANNEL_DIR" ]] || { error "channel-dir は 1 つだけ指定してください"; exit 2; }
            CHANNEL_DIR="$1"
            shift
            ;;
    esac
done

[[ -n "$CHANNEL_DIR" ]] || { error "channel-dir が未指定です"; usage; exit 2; }
for command_name in terraform op realpath; do
    command -v "$command_name" >/dev/null 2>&1 || {
        error "$command_name が見つかりません"
        exit 1
    }
done

for ref_name in OP_LIVE_CHAT_TOKEN_REF OP_LIVE_CHAT_CLIENT_SECRETS_REF OP_CODEX_AUTH_REF; do
    [[ -n "${!ref_name:-}" ]] || {
        error "$ref_name に 1Password secret reference を設定してください"
        exit 1
    }
done

[[ -d "$TF_DIR" && -f "$TF_DIR/main.tf" ]] || { error "Terraform module が見つかりません: $TF_DIR"; exit 1; }
[[ -d "$CHANNEL_DIR" ]] || { error "channel directory が見つかりません: $CHANNEL_DIR"; exit 1; }
CHANNEL_DIR_ABS="$(realpath "$CHANNEL_DIR")"
[[ -f "$CHANNEL_DIR_ABS/config/channel/comments.json" ]] || {
    error "comments.json が見つかりません: $CHANNEL_DIR_ABS/config/channel/comments.json"
    exit 1
}

export TF_VAR_live_chat_youtube_token_json="$(op read "$OP_LIVE_CHAT_TOKEN_REF")"
export TF_VAR_live_chat_client_secrets_json="$(op read "$OP_LIVE_CHAT_CLIENT_SECRETS_REF")"
export TF_VAR_live_chat_codex_auth_json="$(op read "$OP_CODEX_AUTH_REF")"
cleanup() {
    unset TF_VAR_live_chat_youtube_token_json
    unset TF_VAR_live_chat_client_secrets_json
    unset TF_VAR_live_chat_codex_auth_json
}
trap cleanup EXIT HUP INT TERM

for json_value in \
    "$TF_VAR_live_chat_youtube_token_json" \
    "$TF_VAR_live_chat_client_secrets_json" \
    "$TF_VAR_live_chat_codex_auth_json"; do
    printf '%s' "$json_value" | python3 -m json.tool >/dev/null || {
        error "1Password から取得した値が JSON ではありません"
        exit 1
    }
done

if command -v shasum >/dev/null 2>&1; then
    CREDENTIALS_REVISION="$(printf '%s\0%s\0%s' \
        "$TF_VAR_live_chat_youtube_token_json" \
        "$TF_VAR_live_chat_client_secrets_json" \
        "$TF_VAR_live_chat_codex_auth_json" | shasum -a 256 | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
    CREDENTIALS_REVISION="$(printf '%s\0%s\0%s' \
        "$TF_VAR_live_chat_youtube_token_json" \
        "$TF_VAR_live_chat_client_secrets_json" \
        "$TF_VAR_live_chat_codex_auth_json" | sha256sum | awk '{print $1}')"
else
    error "shasum または sha256sum が見つかりません"
    exit 1
fi

export TF_VAR_enable_live_chat_reply=true
export TF_VAR_live_chat_channel_dir="$CHANNEL_DIR_ABS"
export TF_VAR_live_chat_credentials_revision="$CREDENTIALS_REVISION"

log "channel: $CHANNEL_DIR_ABS"
log "terraform plan（secret 値は ephemeral のため plan/state に保存されません）"
terraform -chdir="$TF_DIR" plan

log "terraform apply"
if $AUTO_APPROVE; then
    terraform -chdir="$TF_DIR" apply -auto-approve
else
    terraform -chdir="$TF_DIR" apply
fi

ok "live-chat-reply の配備が完了しました"
