# 🔐 GCP / YouTube API セットアップガイド

新しい YouTube チャンネル用に GCP プロジェクト + API + 認証情報を用意する手順。

**従来は Console クリック中心だったが、本リポジトリはスクリプト / Terraform での半自動化に移行した**。手動クリックが残るのは **OAuth クライアント ID 作成の 1 ステップだけ**。

---

## 📋 前提条件

- Google アカウント（YouTube チャンネル所有者）
- `gcloud` CLI インストール済み（[導入手順](https://cloud.google.com/sdk/docs/install)）
- `gcloud auth login` 済み
- Terraform ルートを使うなら `terraform` >= 1.5 + `jq`

## 💳 課金体系の変更について（2026 年〜）

2026 年以降、Google Cloud の新規アカウントは **前払い（プリペイド）制のみ** に変更され、従来の **$300 無料クレジットは Google AI Studio の API キー経由では利用不可** になった。

本リポジトリは YouTube Data API（無料枠で十分）に加えて Gemini / Veo / Lyria など有料 API を利用する。**新規 GCP アカウントの場合、$300 クレジットは Vertex AI 経由でのみ消費可能** なため:

| パターン | 推奨度 | 方式 |
|---------|-------|------|
| 既存の Google アカウント / GCP プロジェクトを流用 | ⭐⭐⭐ 最簡単 | AI Studio モード（従来通り）|
| 新規 GCP アカウント + $300 クレジット活用 | ⭐⭐ 推奨 | Vertex AI モード |
| 新規アカウントで AI Studio モード | — | 前払いで入金必要 |

YouTube Data API / Analytics API は OAuth 認証で動作し、この変更の影響を受けない。

---

## 🚀 セットアップ: 2 つのルート

### ルート A: `scripts/gcp-bootstrap.sh`（gcloud 半自動化・最速）

チャンネル単位で気軽に立ち上げたいケース。1 コマンドでプロジェクト作成〜API 有効化〜IAM 付与〜`.env` 書き出しまで完結する。冪等なので再実行しても安全。

```bash
# 最小 (既存プロジェクト流用)
automation/scripts/gcp-bootstrap.sh my-existing-project

# 新規プロジェクト作成 + Billing 紐付け
automation/scripts/gcp-bootstrap.sh \
  --create \
  --billing-account 012345-6789AB-CDEF01 \
  my-new-yt-channel
```

主なオプション:

| オプション | 意味 |
|-----------|------|
| `--create` | プロジェクトが存在しなければ作成 |
| `--billing-account ID` | Billing account を紐付け（有料 API に必須） |
| `--adc-email EMAIL` | `aiplatform.user` 付与先アカウント（既定: `gcloud config account`） |
| `--env-file PATH` | 書き出す `.env`（既定: `./.env`） |
| `--location REGION` | Vertex AI リージョン（既定: `us-central1`） |
| `--skip-adc` | `gcloud auth application-default login` を省略 |
| `--dry-run` | 変更せずプレビュー |

完了時に OAuth クライアント ID 作成用の Console URL が表示されるので、そこだけ手動で作成（[Step OAuth](#step-oauth) 参照）。

### ルート B: `infra/terraform/gcp`（宣言的 IaC・本命）

Organization 配下で統制したい、複数プロジェクトを tfstate 管理したい、将来的に変更履歴を残したいケース。

```bash
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# → project_id, adc_email, billing_account を編集

# apply + .env 反映までをラッパーで実行
cd ../../..
automation/scripts/gcp-terraform-apply.sh
```

`terraform.tfvars` の必須キーは `project_id` / `adc_email`。新規作成時は `billing_account` も必要（既存流用なら `create_project = false` にして不要）。

詳細は [`infra/terraform/gcp/README.md`](../infra/terraform/gcp/README.md) を参照。

---

## <a id="step-oauth"></a>🔑 OAuth クライアント ID の作成（手動・1 クリック）

`gcloud` / Terraform いずれも OAuth クライアント ID 作成には対応していないため、ここだけ Console での作業が必要:

1. スクリプト / terraform 出力に表示された URL を開く
   - 形式: `https://console.cloud.google.com/apis/credentials?project=<PROJECT_ID>`
2. 「認証情報を作成」→「OAuth クライアント ID」
3. アプリケーションの種類: **「デスクトップ」**
4. 名前を入力（例: "YouTube Auto Uploader"）→ 作成
5. 右側「ダウンロード」で JSON を取得
6. `client_secrets.json` にリネームし、**チャンネルリポジトリの `auth/` 配下**に配置
   - 推奨パス: `<channel_dir>/auth/client_secrets.json`

検索順:
1. `CLIENT_SECRETS_DIR` 環境変数で指定されたディレクトリ
2. `<channel_dir>/auth/client_secrets.json`（推奨）
3. `<channel_dir>/automation/auth/client_secrets.json`（submodule 互換フォールバック）

---

## ✅ 動作確認

```bash
# YouTube OAuth 初回認証（ブラウザ起動）
yt-channel-status

# Vertex AI での画像生成
uv run yt-generate-image --prompt "a gentle watercolor forest" --output /tmp/test.png -y
```

両方成功すれば完了。

## 📁 ファイル構成

```
<channel_dir>/
├── .env                            # GOOGLE_CLOUD_PROJECT 等 (スクリプトが書き出す)
└── auth/
    ├── client_secrets.json          # OAuth 2.0 認証情報（要作成・gitignore）
    └── token.json                   # 認証トークン（自動生成・gitignore）
```

---

## 🌐 AI Studio モード vs Vertex AI モード

スクリプト / Terraform ルートでセットアップすると `.env` に以下が書き出され、**Vertex AI モードが有効になる**:

```bash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=<your-project-id>
GOOGLE_CLOUD_LOCATION=us-central1
```

既存アカウントで AI Studio モードに留まりたい場合は、`.env` から上 3 行を削除 or コメントアウトし、代わりに `GEMINI_API_KEY` を設定すること。

### 対応状況

| API | AI Studio モード | Vertex AI モード |
|-----|-----------------|------------------|
| Gemini 画像生成（サムネイル等）| ✅ | ✅ |
| Gemini 画像分析（ベンチマーク）| ✅ | ✅ |
| Veo 動画生成（ループ動画/ショート）| ✅ | ✅ |
| Lyria 3 音楽生成（`lyria-3-pro-preview` / `lyria-3-clip-preview`）| ✅ | ✅ Preview 提供中（[公式ドキュメント](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/lyria/lyria-3)） |

`youtube_automation` の `generate_music.py` / `generate_music_dj.py` は `create_genai_client()` 経由で両モードに自動対応。Vertex AI モードの場合は `aiplatform.googleapis.com` が有効化されていれば Lyria 3 も同じクライアントでそのまま呼べる（追加設定不要）。

---

## ⚠️ セキュリティ注意事項

- `auth/client_secrets.json`: **絶対に公開しない**（gitignore 済み）
- `auth/token.json`: **絶対に公開しない**（gitignore 済み）
- `infra/terraform/gcp/terraform.tfvars`: **絶対に公開しない**（gitignore 済み）
- `.env`: **絶対に公開しない**（gitignore 済み）

---

## 🔧 トラブルシューティング

### bootstrap/terraform 共通

#### `Permission denied` / 認証エラー
`gcloud auth application-default login` で ADC を更新。必要なら quota project を固定:
```bash
gcloud auth application-default set-quota-project <project-id>
```

#### `roles/aiplatform.user` 付与でエラー
IAM 付与権限がない。Organization / Project オーナー権限を持つアカウントで実行すること。

#### プロジェクト作成上限に達した
GCP のプロジェクト作成は 1 アカウントあたり上限あり（初期は少ない）。不要プロジェクトを削除するか、上限緩和申請。

#### `billingEnabled` エラー（Vertex AI / aiplatform 有効化時）
Billing account が紐付いていない。`--billing-account` を渡して再実行するか、Console で紐付け。

### bootstrap 固有

#### `project-id が複数指定されました`
位置引数として project-id を渡せるのは 1 つだけ。フラグの前後を確認。

### terraform 固有

#### `already exists but is not managed by this terraform configuration`
プロジェクト ID がグローバルで衝突している。`project_id` を別名に変えるか、`create_project = false` で既存流用。

#### `Error 400: ... not enabled for billing`
`aiplatform.googleapis.com` には Billing が必須。`billing_account` を正しく指定。

### YouTube OAuth 固有

#### `client_secrets.json が見つかりません`
[Step OAuth](#step-oauth) を確認。ファイル配置先を見直し。

#### `Access blocked: This app's request is invalid`
OAuth 同意画面の設定が必要。Console で OAuth 同意画面を設定（テストユーザーに自分を追加）。

#### `The OAuth client was not found`
`client_secrets.json` の内容が壊れている。再ダウンロード。

#### ブラウザが開かない
ファイアウォール設定 / ポート接続を確認。
