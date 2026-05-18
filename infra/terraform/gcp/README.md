# infra/terraform/gcp

新チャンネル用の GCP プロジェクト + 必要 API + IAM を Terraform で IaC 管理するモジュール。

## いつ terraform を選ぶか

`scripts/gcp-bootstrap.sh` と機能ほぼ同等だが、tfstate を持つ分以下のシナリオで強い:

| シナリオ | 推奨 |
| --- | --- |
| **初回 1 チャンネルだけ立ち上げ** | bootstrap.sh (or `/onboard` skill) — 手数最少 |
| **2 つ目以降のチャンネル開設** | **terraform** — workspace で並列管理可能 |
| **別 PC への引っ越し / 再構築** | **terraform** — tfstate + tfvars を持ち運べば replay 可能 |
| **GCP 側のドリフト検出** | **terraform** — `terraform plan` で差分が出る |
| **CI / IaC パイプライン統合** | **terraform** — Terraform Cloud / GCS backend が使える |

初回 1 チャンネル限定なら bootstrap.sh の方が tfvars 編集の手間が無い分シンプル。複数管理・継続運用を見据えるなら terraform に切り替える価値がある。

`/onboard` skill (AI 主導の wizard) は内部で bootstrap.sh を呼ぶ前提だが、AI に tfvars 編集 + `gcp-terraform-apply.sh` を Bash で叩かせれば terraform ルートも自動化可能。

## 管理するリソース

- `google_project`（`create_project=true` 時のみ）
- `google_project_service` × 4
  - `youtube.googleapis.com`
  - `youtubeanalytics.googleapis.com`
  - `aiplatform.googleapis.com`
  - `generativelanguage.googleapis.com`
- `google_project_iam_member` = `roles/aiplatform.user` → `var.adc_email`

**OAuth 2.0 クライアント ID は google provider で未サポート** のため、別途 Console から作成する（この 1 ステップだけ手動）。

## 前提

- `terraform` >= 1.5 インストール済み
- `gcloud auth application-default login` 実行済み（Terraform は ADC 経由で認証）
- Project を新規作成する場合: Organization / Billing Account に対する権限保持

## 使い方

```bash
# 1. tfvars を用意
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# → project_id, adc_email, billing_account を実値に書き換え

# 2. apply
terraform init
terraform plan
terraform apply

# 3. outputs から .env を更新 (ラッパー推奨)
bash ../../../scripts/gcp-terraform-apply.sh --tf-dir . --env-file ../../../.env
```

`scripts/gcp-terraform-apply.sh` は `terraform apply` → `terraform output -json env_vars` → `.env` へマージまで一気通貫で実行する。

## 既存プロジェクトを流用する場合

`terraform.tfvars`:

```hcl
project_id     = "existing-project-id"
create_project = false
adc_email      = "you@example.com"
# billing_account は不要 (既存で設定済み前提)
```

`data.google_project` で既存を参照するため、API 有効化と IAM 付与のみ反映される。

## Outputs

| 名前 | 内容 |
|------|------|
| `project_id` | 確定した project ID |
| `location` | Vertex AI リージョン |
| `env_vars` | `.env` 用 key/value map (`GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`)。`GOOGLE_CLOUD_PROJECT` は任意の override で、未設定なら ADC quota project から自動解決される |
| `oauth_console_url` | OAuth クライアント ID 作成用 Console URL |
| `enabled_apis` | 有効化した API 一覧 |

## トラブルシューティング

### `Error 403: The caller does not have permission`
ADC ユーザーが Organization / Billing Account に対する必要な権限を持っていない。`roles/resourcemanager.projectCreator` と `roles/billing.user` が最低必要。

### `Error: googleapi: Error 400: ... billingEnabled`
`aiplatform.googleapis.com` を有効化するには Billing が必要。`billing_account` を正しく指定すること。

### `Error: project ... already exists but is not managed by this terraform configuration`
プロジェクト ID がグローバルで衝突している。`project_id` を別名に変えるか、既存流用なら `create_project = false` に。

### `Permission denied` (apply 後の実行時)
ADC を更新してから実行: `gcloud auth application-default login && gcloud auth application-default set-quota-project <project-id>`
