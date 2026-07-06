#!/usr/bin/env bash
# gcp-bootstrap.sh — 新チャンネル用 GCP プロジェクトの半自動セットアップ
#
# 何をするか:
#   1. gcloud / ログイン状態の前提チェック
#   2. プロジェクト作成 (--create) or 既存流用
#   3. Billing account の紐付け (任意)
#   4. 必要 API の有効化 (冪等)
#        - youtube.googleapis.com
#        - youtubeanalytics.googleapis.com
#        - aiplatform.googleapis.com
#        - generativelanguage.googleapis.com
#   5. Application Default Credentials (ADC) ログイン + quota project 設定
#   6. roles/aiplatform.user を ADC ユーザーに付与
#   7. .env に GOOGLE_CLOUD_LOCATION / GOOGLE_GENAI_USE_VERTEXAI を書き出し
#      (project_id は ADC quota project から自動解決されるため .env への書き出し不要)
#   8. Google Auth Platform 手動設定のための Console URL を案内
#
# 注意:
#   Claude Code / CI / パイプ等の非対話セッション (TTY を持たない環境) からは実行しないこと。
#   gcloud の OAuth フロー (PKCE) は code_verifier をプロセス内に秘匿して同一プロセス内で
#   トークン取得まで完結させる設計のため、非対話環境では認証コードを渡しても
#   別プロセスとなり invalid_grant ループに陥ります。
#   必ず TTY を持つ通常ターミナル (cmux pane 外) で直接実行してください。
#
# Usage:
#   .claude/skills/channel-new/references/gcp-bootstrap.sh [OPTIONS] <project-id>
#
# Options:
#   --create                      プロジェクトが存在しなければ作成する
#   --billing-account <ID>        billing account を紐付ける (例: 012345-6789AB-CDEF01)
#   --adc-email <EMAIL>           IAM 付与対象の Google アカウント (未指定なら gcloud config account)
#   --env-file <PATH>             書き込む .env のパス (既定: ./.env)
#   --location <REGION>           Vertex AI リージョン (既定: us-central1)
#   --skip-adc                    `gcloud auth application-default login` を省略
#   --dry-run                     変更せず何をするか表示
#   -h, --help                    このヘルプを表示
#
# Examples:
#   .claude/skills/channel-new/references/gcp-bootstrap.sh my-yt-channel
#   .claude/skills/channel-new/references/gcp-bootstrap.sh --create --billing-account 01ABCD-234567-89EFGH my-new-channel
#   .claude/skills/channel-new/references/gcp-bootstrap.sh --env-file .env.local --location asia-northeast1 my-proj

set -euo pipefail

CREATE_PROJECT=false
BILLING_ACCOUNT=""
ADC_EMAIL=""
ENV_FILE="./.env"
LOCATION="us-central1"
SKIP_ADC=false
DRY_RUN=false
PROJECT_ID=""

REQUIRED_APIS=(
    "youtube.googleapis.com"
    "youtubeanalytics.googleapis.com"
    "aiplatform.googleapis.com"
    "generativelanguage.googleapis.com"
)

log()   { printf '\033[0;36m[bootstrap]\033[0m %s\n' "$*"; }
ok()    { printf '\033[0;32m[ok]\033[0m %s\n' "$*"; }
warn()  { printf '\033[0;33m[warn]\033[0m %s\n' "$*"; }
error() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --create) CREATE_PROJECT=true; shift ;;
        --billing-account) BILLING_ACCOUNT="$2"; shift 2 ;;
        --billing-account=*) BILLING_ACCOUNT="${1#*=}"; shift ;;
        --adc-email) ADC_EMAIL="$2"; shift 2 ;;
        --adc-email=*) ADC_EMAIL="${1#*=}"; shift ;;
        --env-file) ENV_FILE="$2"; shift 2 ;;
        --env-file=*) ENV_FILE="${1#*=}"; shift ;;
        --location) LOCATION="$2"; shift 2 ;;
        --location=*) LOCATION="${1#*=}"; shift ;;
        --skip-adc) SKIP_ADC=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) error "未知のオプション: $1"; usage; exit 2 ;;
        *)
            if [[ -z "$PROJECT_ID" ]]; then
                PROJECT_ID="$1"
            else
                error "project-id が複数指定されました: $PROJECT_ID, $1"
                exit 2
            fi
            shift
            ;;
    esac
done

if [[ -z "$PROJECT_ID" ]]; then
    error "project-id は必須です"
    usage
    exit 2
fi

run() {
    if $DRY_RUN; then
        printf '\033[0;35m[dry-run]\033[0m %s\n' "$*"
    else
        log "$*"
        "$@"
    fi
}

log "Step 1: 前提チェック"

# 非対話セッション (Claude Code / CI / pipe 経由) は gcloud の PKCE フローが
# プロセスを跨げず認証ループに陥るため拒否する
if ! $DRY_RUN && { [[ ! -t 0 ]] || [[ ! -t 1 ]]; }; then
    error "非対話セッション (TTY なし) では実行できません"
    error "Claude Code / CI / パイプ経由から呼ばれた場合、gcloud auth フローが PKCE の制約で同一プロセス内で完結できず、"
    error "認証ループに陥ります。必ずあなた自身のターミナル (cmux pane 外) で直接実行してください。"
    exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
    error "gcloud CLI が見つかりません。https://cloud.google.com/sdk/docs/install を参照してインストールしてください"
    exit 1
fi
ok "gcloud: $(gcloud --version | head -n1)"

if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q '@'; then
    error "gcloud にログインしていません"
    error "あなた自身のターミナルで \`gcloud auth login\` を実行してから再度このスクリプトを実行してください"
    error "(Claude Code 等の AI セッション内で gcloud auth login を呼ぶと PKCE の code_verifier がプロセスを跨げず認証ループになります)"
    exit 1
fi
CURRENT_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1)
ok "gcloud active account: ${CURRENT_ACCOUNT}"

if [[ -z "$ADC_EMAIL" ]]; then
    ADC_EMAIL="$CURRENT_ACCOUNT"
fi
log "ADC email (IAM 付与対象): ${ADC_EMAIL}"

log "Step 2: プロジェクト確認"

project_exists() {
    gcloud projects describe "$PROJECT_ID" --format="value(projectId)" >/dev/null 2>&1
}

if project_exists; then
    ok "プロジェクト ${PROJECT_ID} は既に存在します (流用)"
else
    if $CREATE_PROJECT; then
        run gcloud projects create "$PROJECT_ID" --name="$PROJECT_ID"
        ok "プロジェクト ${PROJECT_ID} を作成しました"
    else
        error "プロジェクト ${PROJECT_ID} が存在しません。--create を付けて作成するか、既存の project-id を指定してください"
        exit 1
    fi
fi

# 以降の gcloud コマンドで project を固定
run gcloud config set project "$PROJECT_ID"

if [[ -n "$BILLING_ACCOUNT" ]]; then
    log "Step 3: Billing account 紐付け"
    CURRENT_BILLING=$(gcloud beta billing projects describe "$PROJECT_ID" \
        --format="value(billingAccountName)" 2>/dev/null || echo "")
    if [[ "$CURRENT_BILLING" == *"$BILLING_ACCOUNT"* ]]; then
        ok "Billing account ${BILLING_ACCOUNT} は既に紐付け済み"
    else
        run gcloud beta billing projects link "$PROJECT_ID" \
            --billing-account="$BILLING_ACCOUNT"
        ok "Billing account ${BILLING_ACCOUNT} を紐付けました"
    fi
else
    warn "Step 3: --billing-account 未指定のため billing 紐付けはスキップ (aiplatform 等の有料 API は billing 未紐付けだと利用できません)"
fi

log "Step 4: 必要 API の有効化"

ENABLED_APIS=$(gcloud services list --enabled --project="$PROJECT_ID" \
    --format="value(config.name)" 2>/dev/null || echo "")

for api in "${REQUIRED_APIS[@]}"; do
    if echo "$ENABLED_APIS" | grep -qx "$api"; then
        ok "${api}: 既に有効"
    else
        run gcloud services enable "$api" --project="$PROJECT_ID"
        ok "${api}: 有効化しました"
    fi
done

if $SKIP_ADC; then
    warn "Step 5: --skip-adc のため ADC ログインをスキップ"
else
    log "Step 5: ADC ログイン (ブラウザが開きます)"
    run gcloud auth application-default login
    run gcloud auth application-default set-quota-project "$PROJECT_ID"
    ok "ADC ログイン完了 & quota project を ${PROJECT_ID} に設定"
fi

log "Step 6: IAM 付与 (roles/aiplatform.user → ${ADC_EMAIL})"

HAS_ROLE=$(gcloud projects get-iam-policy "$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.role:roles/aiplatform.user AND bindings.members:user:${ADC_EMAIL}" \
    --format="value(bindings.role)" 2>/dev/null || echo "")

if [[ -n "$HAS_ROLE" ]]; then
    ok "user:${ADC_EMAIL} は既に roles/aiplatform.user を保持"
else
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="user:${ADC_EMAIL}" \
        --role="roles/aiplatform.user" \
        --condition=None \
        --quiet
    ok "roles/aiplatform.user を付与しました"
fi

log "Step 7: ${ENV_FILE} へ書き出し"

# gcp-terraform-apply.sh の write_env_var と awk コア部分は同一 (ドリフト時は両方揃えること)
write_env_var() {
    local key="$1"
    local value="$2"
    local file="$3"

    if $DRY_RUN; then
        printf '\033[0;35m[dry-run]\033[0m %s=%s → %s\n' "$key" "$value" "$file"
        return
    fi

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

write_env_var "GOOGLE_GENAI_USE_VERTEXAI" "true" "$ENV_FILE"
write_env_var "GOOGLE_CLOUD_LOCATION" "$LOCATION" "$ENV_FILE"
ok "${ENV_FILE} に Vertex AI 用環境変数を書き出しました (project_id は ADC quota project から自動解決)"

cat <<EOF

---- 最後に Google Auth Platform の手動設定が必要 ----
gcloud からは Google Auth Platform の Branding / Audience / Clients 設定を作成できないため、Console で設定してください:

  https://console.cloud.google.com/apis/credentials?project=${PROJECT_ID}

手順:
  1. 左メニューで「Google Auth Platform」を開く
  2. 「Branding」でアプリ名・サポートメール・デベロッパー連絡先を保存
  3. 「Audience」で User type は External、Publishing status は Testing のまま、
     「Test users」に OAuth 認証でログインする Google アカウントを追加
     (未追加だと初回認証が 403 access_denied で止まります)
  4. 「Clients」→「Create client」で Application type「Desktop app」を選び、
     名前を <channel-name> Desktop Client にする
  5. 作成した client を開き、「Client secrets」→「Add secret」で新しい secret を発行
  6. auth/client_secrets.template.json をコピーし、client_id / project_id / client_secret を転記して、
     チャンネルリポジトリの auth/client_secrets.json として配置

詳細は auth/SETUP.md を参照。
-----------------------------------

EOF

ok "GCP ブートストラップ完了: project=${PROJECT_ID}, location=${LOCATION}"
