# 🔐 GCP / YouTube API セットアップガイド

新しい YouTube チャンネル用に GCP プロジェクト + API + 認証情報を用意する手順。

本リポジトリは Gemini / Veo / Lyria を **Vertex AI 経由で 1 本化** している（AI Studio モードは廃止）。スクリプト / Terraform で半自動化しているため、手動クリックが残るのは **OAuth クライアント ID 作成の 1 ステップだけ**。

---

## 📋 前提条件

- Google アカウント（YouTube チャンネル所有者）
- `gcloud` CLI インストール済み（[導入手順](https://cloud.google.com/sdk/docs/install)）
- `gcloud auth login` 済み
- Vertex AI API を呼ぶため **Billing account の紐付けが必須**
- Terraform ルートを使うなら `terraform` >= 1.5 + `jq`

2026 年以降、Google Cloud の新規アカウントは前払い（プリペイド）制に変更されたが、**$300 無料クレジットは Vertex AI 経由で消費可能**。本リポジトリを Vertex AI 1 本に揃えた理由もこのクレジットを活かすため。

---

## 🚀 セットアップ: 3 つのルート

| ルート | 推奨対象 | 手数 |
| --- | --- | --- |
| **ルート 0**: `/onboard` skill (Claude Code) | GCP / OAuth に不慣れな利用者、初心者 | 1 発話 + 手動 3 ステップ |
| **ルート A**: `scripts/gcp-bootstrap.sh` | シェルから直接叩きたい、手動派 | 1 コマンド + 手動 1 クリック |
| **ルート B**: `infra/terraform/gcp/` | 複数プロジェクト管理 / 別 PC 引っ越し / drift 検出が欲しい上級者 | tfvars 編集 + apply + 手動 1 クリック |

「初回 1 チャンネルだけ立ち上げ」ならルート 0 or A、「2 つ目以降」「IaC 管理したい」ならルート B が向く。詳細な選択基準は [`infra/terraform/gcp/README.md`](../infra/terraform/gcp/README.md) の「いつ terraform を選ぶか」を参照。

### ルート 0: `/onboard` skill (AI 主導 wizard、推奨)

Claude Code 上で `/onboard` を実行する。AI が `yt-doctor` で API 設定の状態を診断し、GCP プロジェクト作成・billing 紐付け・API 有効化・IAM 付与・`.env` 書き出し・OAuth クライアント ID 配置まで wizard で誘導する。

```
/onboard
```

`gcloud auth login` / `gcloud auth application-default login` / Console での OAuth クライアント ID 作成の 3 ステップだけ PKCE / GUI 制約で AI 実行不可なため利用者が手動で行うが、それ以外は AI が gcloud を直接 Bash で実行する。内部では本書のルート A (bootstrap.sh) を呼ぶ。

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
| `--billing-account ID` | Billing account を紐付け（Vertex AI に必須） |
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
├── .env                            # GOOGLE_CLOUD_LOCATION / GOOGLE_GENAI_USE_VERTEXAI (スクリプトが書き出す)
└── auth/
    ├── client_secrets.json          # OAuth 2.0 認証情報（要作成・gitignore）
    └── token.json                   # 認証トークン（自動生成・gitignore）
```

---

## 🌐 Vertex AI 前提の環境変数

スクリプト / Terraform ルートでセットアップすると `.env` に以下が書き出される:

```bash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_LOCATION=us-central1
```

project_id は ADC quota project (`gcloud auth application-default set-quota-project <PROJECT_ID>`) から自動解決されるため `.env` への書き出しは不要。明示したい場合は `GOOGLE_CLOUD_PROJECT=<id>` を追記すれば従来通り優先される。

アプリ側 (`create_genai_client()`) は `utils/google_cloud_project.resolve_project_id()` を介して env var → ADC の順で project_id を解決し、常に `vertexai=True` で Client を初期化する。`GOOGLE_GENAI_USE_VERTEXAI` は google-genai SDK の自動検出用に置いておく任意フラグ。

### 対応 API

Vertex AI で以下を利用する。`aiplatform.googleapis.com` が有効化されていれば追加設定不要。

| API | 用途 |
|-----|------|
| Gemini 画像生成 | サムネイル等 |
| Gemini 画像分析 | ベンチマーク / 競合調査 |
| Veo 動画生成 | ループ動画 / ショート |
| Lyria 3 音楽生成（`lyria-3-pro-preview` / `lyria-3-clip-preview`）| 楽曲生成（[公式ドキュメント](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/lyria/lyria-3)） |

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
