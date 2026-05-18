#!/usr/bin/env bash
# gcp-terraform-apply.sh — Terraform apply → .env 書き出しまでを 1 コマンドで
#
# Usage:
#   scripts/gcp-terraform-apply.sh [--tf-dir DIR] [--env-file PATH] [--auto-approve]
#
# Options:
#   --tf-dir DIR       Terraform モジュールパス (既定: infra/terraform/gcp)
#   --env-file PATH    書き出す .env (既定: ./.env)
#   --auto-approve     terraform apply に -auto-approve を付ける
#   -h, --help         このヘルプ

set -euo pipefail

TF_DIR="infra/terraform/gcp"
ENV_FILE="./.env"
AUTO_APPROVE=false

log()   { printf '\033[0;36m[tf-apply]\033[0m %s\n' "$*"; }
ok()    { printf '\033[0;32m[ok]\033[0m %s\n' "$*"; }
error() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tf-dir) TF_DIR="$2"; shift 2 ;;
        --tf-dir=*) TF_DIR="${1#*=}"; shift ;;
        --env-file) ENV_FILE="$2"; shift 2 ;;
        --env-file=*) ENV_FILE="${1#*=}"; shift ;;
        --auto-approve) AUTO_APPROVE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) error "未知のオプション: $1"; usage; exit 2 ;;
    esac
done

command -v terraform >/dev/null 2>&1 || {
    error "terraform が見つかりません: https://developer.hashicorp.com/terraform/install"
    exit 1
}
command -v jq >/dev/null 2>&1 || {
    error "jq が見つかりません (brew install jq)"
    exit 1
}

[[ -d "$TF_DIR" ]] || { error "tf-dir が存在しません: $TF_DIR"; exit 1; }

if [[ "$ENV_FILE" = /* ]]; then
    ENV_FILE_ABS="$ENV_FILE"
else
    ENV_FILE_ABS="$(pwd)/$ENV_FILE"
fi

# gcp-bootstrap.sh の write_env_var と同一実装 (ドリフト時は両方揃えること)
write_env_var() {
    local key="$1"
    local value="$2"
    local file="$3"

    mkdir -p "$(dirname "$file")"
    touch "$file"

    local tmp
    tmp=$(mktemp)
    awk -v k="$key" -v v="$value" '
        BEGIN { done = 0 }
        $0 ~ "^" k "=" { print k "=" v; done = 1; next }
        { print }
        END { if (!done) print k "=" v }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

log "Terraform apply: $TF_DIR"
pushd "$TF_DIR" >/dev/null
terraform init -upgrade
if $AUTO_APPROVE; then
    terraform apply -auto-approve
else
    terraform apply
fi

ENV_JSON=$(terraform output -json env_vars)
OAUTH_URL=$(terraform output -raw oauth_console_url)
PROJECT_ID=$(terraform output -raw project_id)
popd >/dev/null

while IFS=$'\t' read -r key value; do
    write_env_var "$key" "$value" "$ENV_FILE_ABS"
done < <(echo "$ENV_JSON" | jq -r 'to_entries[] | "\(.key)\t\(.value)"')

ok ".env updated: $ENV_FILE_ABS (project=$PROJECT_ID)"

# ADC quota project を確定プロジェクトに揃える (gcp-bootstrap.sh と機能等価にするため)
if command -v gcloud >/dev/null 2>&1; then
    log "ADC quota project を $PROJECT_ID に設定"
    gcloud auth application-default set-quota-project "$PROJECT_ID"
    ok "ADC quota project: $PROJECT_ID"
fi

cat <<EOF

---- 最後に手動で 1 ステップ必要 ----
OAuth 2.0 クライアント ID を Console で作成:

  $OAUTH_URL

手順:
  1. 「認証情報を作成」→「OAuth クライアント ID」
  2. アプリケーションの種類: 「デスクトップ」
  3. ダウンロード JSON を auth/client_secrets.json に配置

詳細は auth/SETUP.md を参照。
-----------------------------------

EOF
