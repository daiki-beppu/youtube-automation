#!/usr/bin/env bash
# select_channel.sh — Terraform workspace とチャンネル資格情報を一体で選択する
#
# Usage:
#   select_channel.sh <channel-slug> [plan|apply|destroy|show] [options]
#
# Options:
#   --video PATH       plan / apply で使用する配信動画
#   --tf-dir DIR       Terraform module (既定: infra/terraform/streaming)
#   --auto-approve     apply / destroy に -auto-approve を付ける
#   --dry-run          secret を取得せず、実行予定と 1Password 参照だけを表示する
#   -h, --help         このヘルプ

set -euo pipefail

TF_DIR="infra/terraform/streaming"
ACTION="show"
VIDEO_PATH=""
AUTO_APPROVE=false
DRY_RUN=false

log()   { printf '\033[0;36m[select-channel]\033[0m %s\n' "$*"; }
error() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }

if [[ $# -eq 0 || "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    [[ $# -gt 0 ]] && exit 0 || exit 2
fi

CHANNEL_SLUG="$1"
shift
if [[ $# -gt 0 && "$1" != -* ]]; then
    ACTION="$1"
    shift
fi
case "$ACTION" in plan|apply|destroy|show) ;; *) error "未知の操作: $ACTION"; exit 2 ;; esac

while [[ $# -gt 0 ]]; do
    case "$1" in
        --video) [[ $# -ge 2 ]] || { error "--video に値が必要です"; exit 2; }; VIDEO_PATH="$2"; shift 2 ;;
        --video=*) VIDEO_PATH="${1#*=}"; shift ;;
        --tf-dir) [[ $# -ge 2 ]] || { error "--tf-dir に値が必要です"; exit 2; }; TF_DIR="$2"; shift 2 ;;
        --tf-dir=*) TF_DIR="${1#*=}"; shift ;;
        --auto-approve) AUTO_APPROVE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) error "未知の引数: $1"; usage; exit 2 ;;
    esac
done

[[ -d "$TF_DIR" && -f "$TF_DIR/main.tf" ]] || { error "tf-dir に main.tf がありません: $TF_DIR"; exit 1; }
if [[ "$ACTION" == "plan" || "$ACTION" == "apply" ]]; then
    [[ -n "$VIDEO_PATH" ]] || { error "$ACTION には --video PATH が必要です"; exit 2; }
    [[ -f "$VIDEO_PATH" ]] || { error "動画ファイルが存在しません: $VIDEO_PATH"; exit 1; }
    command -v realpath >/dev/null 2>&1 || { error "realpath が見つかりません"; exit 1; }
    VIDEO_PATH="$(realpath "$VIDEO_PATH")"
elif [[ "$ACTION" == "destroy" ]]; then
    VIDEO_PATH="/dev/null"
fi

resolve_stream_key_ref() {
    case "$1" in
        002ch-deepfocus365) printf '%s\n' 'op://Personal/YouTube_DeepFocus365/stream_key' ;;
        003ch-soulful-grooves) printf '%s\n' 'op://Personal/YouTube_SoulfulGrooves/stream_key' ;;
        *) error "stream_key の 1Password 参照が未登録です: $1"; return 1 ;;
    esac
}

VULTR_API_KEY_REF='op://Personal/Vultr/api_key'
DISCORD_WEBHOOK_REF='op://Personal/YouTube_Stream_Discord_Webhook/url'

log "channel: $CHANNEL_SLUG"
log "tf-dir: $TF_DIR"

if $DRY_RUN; then
    log "dry-run: terraform workspace select $CHANNEL_SLUG"
    if [[ "$ACTION" == "show" ]]; then
        log "dry-run: terraform workspace show && terraform state list"
    else
        STREAM_KEY_REF="$(resolve_stream_key_ref "$CHANNEL_SLUG")"
        log "stream-key-ref: $STREAM_KEY_REF"
        log "dry-run: terraform workspace show && terraform state list && terraform $ACTION"
    fi
    exit 0
fi

command -v terraform >/dev/null 2>&1 || { error "terraform が見つかりません"; exit 1; }
WORKSPACES="$(terraform -chdir="$TF_DIR" workspace list)"
if ! printf '%s\n' "$WORKSPACES" | sed 's/^[*[:space:]]*//' | grep -Fxq "$CHANNEL_SLUG"; then
    error "workspace が存在しません: $CHANNEL_SLUG"
    error "明示的に作成してください: terraform -chdir=$TF_DIR workspace new $CHANNEL_SLUG"
    error "既存 workspace:"
    printf '%s\n' "$WORKSPACES" >&2
    exit 1
fi

terraform -chdir="$TF_DIR" workspace select "$CHANNEL_SLUG" >/dev/null
SELECTED_WORKSPACE="$(terraform -chdir="$TF_DIR" workspace show)"
if [[ "$SELECTED_WORKSPACE" != "$CHANNEL_SLUG" ]]; then
    error "workspace 切替後の値が一致しません (expected: $CHANNEL_SLUG, actual: $SELECTED_WORKSPACE)"
    exit 1
fi
log "workspace: $SELECTED_WORKSPACE"
terraform -chdir="$TF_DIR" state list

[[ "$ACTION" == "show" ]] && exit 0
if [[ "$ACTION" == "apply" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    "$SCRIPT_DIR/verify_ssh_agent_key.sh" "$HOME/.ssh/yt_stream_key"
fi
command -v op >/dev/null 2>&1 || { error "1Password CLI (op) が見つかりません"; exit 1; }
STREAM_KEY_REF="$(resolve_stream_key_ref "$CHANNEL_SLUG")"
log "stream-key-ref: $STREAM_KEY_REF"

# 解決後の値は echo/log せず、この子プロセス環境だけに閉じ込める。
TF_VAR_stream_key="$(op read "$STREAM_KEY_REF")"
TF_VAR_vultr_api_key="$(op read "$VULTR_API_KEY_REF")"
TF_VAR_discord_webhook_url="$(op read "$DISCORD_WEBHOOK_REF")"
export TF_VAR_channel_slug="$CHANNEL_SLUG"
export TF_VAR_stream_key TF_VAR_vultr_api_key TF_VAR_discord_webhook_url
export TF_VAR_video_path="$VIDEO_PATH"

terraform_args=("-chdir=$TF_DIR" "$ACTION")
if $AUTO_APPROVE && [[ "$ACTION" == "apply" || "$ACTION" == "destroy" ]]; then
    terraform_args+=("-auto-approve")
fi
terraform "${terraform_args[@]}"
