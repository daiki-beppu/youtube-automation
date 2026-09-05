# infra/terraform/gcp

共有 GCP プロジェクト + 必要 API + IAM を Terraform で IaC 管理する上流専属 stack。下流チャンネルリポジトリへは配布しない。

## 運用入口

共有プロジェクトの構成管理とドリフト検出は、このディレクトリで Terraform を直接実行する。[使い方](#使い方) の GCS backend 付き init 手順に従う。

チャンネル環境のセットアップは引き続き `/setup --tool` の doctor wizard を使う。

## 管理するリソース

- `google_project`（`create_project=true` 時のみ）
- `google_project_service` × 5
  - `youtube.googleapis.com`
  - `youtubeanalytics.googleapis.com`
  - `aiplatform.googleapis.com`
  - `generativelanguage.googleapis.com`
  - `storage.googleapis.com`
- `google_project_iam_member` = `roles/aiplatform.user` → `var.adc_email`

**Google Auth Platform の Branding / Audience / Clients 設定は google provider で未サポート** のため、別途 Console から設定し、`client_secrets.json` を配置する。

Terraform apply 後に表示される Console URL を開き、**Branding** を保存し、**Audience > Test users** に OAuth 認証でログインする Google アカウントを追加してから、**Clients > Create client** で Application type **Desktop app** を作成する。作成した client の **Client secrets > Add secret** で新しい secret を発行し、チャンネル repo の `auth/client_secrets.template.json` をコピーして `client_id` / `project_id` / `client_secret` を転記する。

## 前提

- `terraform` 1.15.x インストール済み
- `gcloud auth application-default login` 実行済み（Terraform は ADC 経由で認証）
- Project を新規作成する場合: Organization / Billing Account に対する権限保持

## 使い方

```bash
# 1. tfvars を用意
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# → project_id, adc_email, billing_account を実値に書き換え

# 2. bootstrap stack の output bucket_name を使って初回 backend 設定
terraform init -backend-config="bucket=$(terraform -chdir=../bootstrap output -raw bucket_name)"
terraform plan
```

backend の bucket 名は `terraform -chdir=../bootstrap output -raw bucket_name` で取得するため、先に bootstrap stack の構築を完了しておく。GCP stack は未 apply で state が無いため初回設定となり、init 後も state は空のまま。既存リソースの import を行う #4929 まで apply は実行しない。

Vertex AI の location はモデル用途別にアプリが決定する。project ID を一時的に上書きする必要がある実行だけ `GOOGLE_CLOUD_PROJECT` process env を使う。

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
| `oauth_console_url` | Google Auth Platform 手動設定用 Console URL |
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
