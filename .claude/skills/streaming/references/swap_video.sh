#!/usr/bin/env bash
# swap_video.sh — 配信中動画を 1 コマンドで差し替えるラッパー
#
# Usage:
#   .claude/skills/streaming/references/swap_video.sh [--tf-dir DIR] [--auto-approve] <video-path>
#
# Options:
#   --tf-dir DIR       Terraform モジュールパス (既定: infra/terraform/streaming)
#   --auto-approve     terraform apply に -auto-approve を付ける (既定: 対話確認)
#   -h, --help         このヘルプ
#
# Notes:
#   - secret 系 (TF_VAR_stream_key / TF_VAR_vultr_api_key) は呼び出し側で事前 export すること。
#     本ラッパーは video_path のみ扱う。
#   - terraform init は実行しない (provider バージョンの意図せぬ更新を避けるため)。
#   - cwd 依存を避けるため pushd ではなく terraform -chdir= を使う。

set -euo pipefail

TF_DIR="infra/terraform/streaming"
AUTO_APPROVE=false
VIDEO_PATH=""

log()   { printf '\033[0;36m[swap-video]\033[0m %s\n' "$*"; }
ok()    { printf '\033[0;32m[ok]\033[0m %s\n' "$*"; }
error() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tf-dir) TF_DIR="$2"; shift 2 ;;
        --tf-dir=*) TF_DIR="${1#*=}"; shift ;;
        --auto-approve) AUTO_APPROVE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) error "未知のオプション: $1"; usage; exit 2 ;;
        *)
            if [[ -n "$VIDEO_PATH" ]]; then
                error "動画パスは 1 つだけ指定してください (既: $VIDEO_PATH / 追加: $1)"
                exit 2
            fi
            VIDEO_PATH="$1"
            shift
            ;;
    esac
done

# `--` 以降の残余引数を動画パスとして拾う (まだ未設定なら)
if [[ -z "$VIDEO_PATH" && $# -gt 0 ]]; then
    VIDEO_PATH="$1"
    shift
fi

if [[ -z "$VIDEO_PATH" ]]; then
    error "動画パスが未指定です"
    usage
    exit 2
fi

command -v terraform >/dev/null 2>&1 || {
    error "terraform が見つかりません: https://developer.hashicorp.com/terraform/install"
    exit 1
}
command -v realpath >/dev/null 2>&1 || {
    error "realpath が見つかりません (macOS なら brew install coreutils)"
    exit 1
}

[[ -d "$TF_DIR" ]] || { error "tf-dir が存在しません: $TF_DIR"; exit 1; }
[[ -f "$TF_DIR/main.tf" ]] || { error "tf-dir に main.tf が見当たりません: $TF_DIR"; exit 1; }
[[ -f "$VIDEO_PATH" ]] || { error "動画ファイルが存在しません: $VIDEO_PATH"; exit 1; }

VIDEO_PATH_ABS="$(realpath "$VIDEO_PATH")"
export TF_VAR_video_path="$VIDEO_PATH_ABS"

log "video:  $TF_VAR_video_path"
log "tf-dir: $TF_DIR"

log "terraform plan (差分確認: null_resource.deploy のみ replace 予定)"
terraform -chdir="$TF_DIR" plan

log "terraform apply"
if $AUTO_APPROVE; then
    terraform -chdir="$TF_DIR" apply -auto-approve
else
    terraform -chdir="$TF_DIR" apply
fi

ok "動画差し替え完了: $TF_VAR_video_path"
