# infra/terraform/gcp

共有 GCP プロジェクト + 必要 API + IAM を Terraform で IaC 管理する上流専属 stack。下流チャンネルリポジトリへは配布しない。

## 運用入口

共有プロジェクトの構成管理とドリフト検出は、このディレクトリで Terraform を直接実行する。[使い方](#使い方) の GCS backend 付き init 手順に従う。

チャンネル環境のセットアップは引き続き `/setup --tool` の doctor wizard を使う。

## 管理するリソース

- `google_project.this`（既存共有プロジェクトと billing 紐付け。`PREVENT` + `prevent_destroy` で削除保護）
- `google_project_service` × 6
  - `youtube.googleapis.com`
  - `youtubeanalytics.googleapis.com`
  - `youtubereporting.googleapis.com`
  - `aiplatform.googleapis.com`
  - `generativelanguage.googleapis.com`
  - `storage.googleapis.com`
- `google_project_iam_member` = `roles/aiplatform.user` → `var.adc_email`

**Google Auth Platform の Branding / Audience / Clients 設定は google provider で未サポート** のため、別途 Console から設定し、`client_secrets.json` を配置する。

Terraform apply 後に表示される Console URL を開き、**Branding** を保存し、**Audience > Test users** に OAuth 認証でログインする Google アカウントを追加してから、**Clients > Create client** で Application type **Desktop app** を作成する。作成した client の **Client secrets > Add secret** で新しい secret を発行し、チャンネル repo の `auth/client_secrets.template.json` をコピーして `client_id` / `project_id` / `client_secret` を転記する。

## 前提

- `terraform` 1.15.x インストール済み
- `gcloud auth application-default login` 実行済み（Terraform は ADC 経由で認証）
- 既存プロジェクト、Billing 紐付け、API、IAM を読み取り・管理する権限保持

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

backend の bucket 名は `terraform -chdir=../bootstrap output -raw bucket_name` で取得するため、先に bootstrap stack の構築を完了しておく。初回取り込みは次節の合格条件を確認してから実施する。

Vertex AI の location はモデル用途別にアプリが決定する。project ID を一時的に上書きする必要がある実行だけ `GOOGLE_CLOUD_PROJECT` process env を使う。

## 既存リソースの import

ADC を保持するこのマシンで人間が実施する。`terraform.tfvars` は gitignore のまま、実在する `project_id` / `billing_account` / `adc_email` をローカルに設定する。`org_id` / `folder_id` は null のままとし、表示名は実在する project ID と同じ値を使用する。

```bash
cd infra/terraform/gcp
terraform init -backend-config="bucket=$(terraform -chdir=../bootstrap output -raw bucket_name)"
terraform plan -out=.terraform/import.tfplan
```

初回 plan の合格条件は **8 to import, 0 to add, 0 to change, 0 to destroy**（project 1 + API 6 + IAM 1）。それ以外の差分が 1 件でも出たら **apply せず停止**し、[#4929](https://github.com/daiki-beppu/youtube-automation/issues/4929) で原因を議論する。合格条件を満たす plan だけを確認して適用する。

```bash
terraform apply .terraform/import.tfplan
terraform plan
```

plan / apply の出力と直後の **No changes** を #4929 のコメントに evidence として残す。`billing_account` / `adc_email` は sensitive として扱うが、provider の import ID や refresh ログにも個人値が現れる可能性があるため、投稿前に出力全体を確認してマスクする。保存した plan と state には sensitive の実値が含まれるため共有しない。

`imports.tf` は apply 後も削除しない。取り込み済みリソースには no-op となり、state 喪失時の復旧でも同じ対象を使える。定義外で有効な 26 API、`roles/owner`、aiplatform サービスエージェントは管理外のままとし、無効化・削除しない。API と IAM は additive に管理し、owner は人間の break-glass として残す。

取り込み後の変更経路と drift 解消原則は [ADR-0030](../../../docs/adr/0030-terraform-sole-change-path-for-gcp.md) に従う。

## WIF と読み取り専用 SA

`wif.tf` は GitHub Actions の drift plan 専用 SA 1 本を管理する。GitHub OIDC issuer の `repository_owner_id` を `var.github_repository_owner_id` に固定し、SA の `roles/iam.workloadIdentityUser` は `repo:daiki-beppu/youtube-automation:ref:refs/heads/main` の subject 完全一致に限定する。feature branch / fork / pull request の subject は SA を impersonate できない。CI から apply は実行しない。

`terraform.tfvars` に `github_repository_owner_id`（`gh api users/daiki-beppu --jq .id`）と `tfstate_bucket`（bootstrap の `bucket_name`）を追加する。WIF 用の IAM / IAM Credentials / STS API は独立した `google_project_service.wif` で管理し、チャンネル運用の `var.apis` 6 件は維持する。

| 付与先 | ロール / permission | 読み取りの目的 |
|------|------|------|
| project | `roles/browser` | project と billing 紐付けの取得 |
| project | `roles/serviceusage.serviceUsageViewer` | 有効 API の取得 |
| project | `roles/iam.securityReviewer` | project / SA / bucket IAM policy と custom role の取得。既定ロールには object list も含むが本文 get は含まない |
| project | `roles/iam.workloadIdentityPoolViewer` | WIF pool / provider の取得 |
| tfstate bucket（条件付き） | custom role `terraformStateGet`: `storage.objects.get` のみ | `resource.name.startsWith("projects/_/buckets/<bucket>/objects/gcp/")` に一致する state の本文取得 |
| tfstate bucket | custom role `terraformStateList`: `storage.objects.list` のみ | backend の workspace 列挙。object の名前・メタデータのみで、他 stack の本文は許可しない |

Billing の `projects.getBillingInfo` は [`resourcemanager.projects.get` で参照できる](https://docs.cloud.google.com/billing/docs/reference/rest/v1/projects/getBillingInfo)。billing account 全体の viewer は付与しない。`roles/viewer` / `roles/editor` / `roles/owner` や objectViewer で読み取り範囲を広げない。list は bucket 単位であり [resource.name では prefix 制限できない](https://docs.cloud.google.com/storage/docs/access-control/iam) ため、本文の get と分離する。

ADC を保持する運用者は次の plan で **import 済み 8 件が no-op、追加が WIF 系のみ、change / destroy が 0** と確認してから適用する。保存 plan は sensitive の実値を含むため共有しない。

```bash
terraform plan -out=.terraform/wif.tfplan
terraform apply .terraform/wif.tfplan
terraform plan
terraform output -raw wif_provider_name
terraform output -raw drift_service_account_email
```

2026-09-05 の実環境では **15 added / 0 changed / 0 destroyed**（WIF API 3、pool / provider / SA / subject binding 4、project read binding 4、custom role 2、bucket binding 2）を適用した。import 済み 8 件は全て no-op。ローカル ADC は通常 SA token 発行を許可されないため、ユーザー承認のもと `iam.serviceAccounts.getAccessToken` 1 件だけの一時 custom role を対象 SA / 現在の ADC に限定付与し、10 分 TTL の token で次を実測した。token と state 本文はログへ出していない。

| 実測 | 結果 |
|------|------|
| `gcp/default.tfstate` 本文 get | HTTP 200 |
| 実在する `streaming/default.tfstate` 本文 get | HTTP 403（他 stack の state を拒否） |
| `r2/default.tfstate` get | HTTP 404。`r2/` の object は存在しないため拒否の実証には使わない |
| gcp object list / GCS backend init | HTTP 200 / exit 0 |
| IAM を変更せず list を禁止した downscoped token | gcp get は HTTP 200、list は HTTP 403、init は `storage.objects.list` 不足で exit 1。init には bucket list が必要 |
| SA の `terraform plan -lock=false` | exit 1。`cloudresourcemanager.googleapis.com` が `SERVICE_DISABLED`。追加 API は未有効化 |

一時 custom role / SA binding は検証後に Terraform で **0 added / 0 changed / 2 destroyed** として除去済み。IAM 伝播後、ADC の新規 token 発行が `IAM_PERMISSION_DENIED`（HTTP 403）に戻り、通常 post-plan が **No changes**（exit 0）であることを確認した。SA plan の完走は要件どおり #4932 で実証し、Cloud Resource Manager API 未有効の前提も解決してから最小権限集合を確定する。API の追加有効化を読み取り検証に混ぜない。plan / apply のマスク済み出力、非 secret の output 2 件、実測および一時権限の除去結果は #4931 の evidence に残す。

## Outputs

| 名前 | 内容 |
|------|------|
| `project_id` | 確定した project ID |
| `oauth_console_url` | Google Auth Platform 手動設定用 Console URL |
| `enabled_apis` | 有効化した API 一覧 |
| `wif_provider_name` | GitHub Actions auth の provider 完全名（非 secret） |
| `drift_service_account_email` | 読み取り専用 drift SA メール（非 secret） |

## トラブルシューティング

### `Error 403: The caller does not have permission`
ADC ユーザーの project / billing / API / IAM に対する権限を確認する。取り込みでは新規プロジェクト作成権限ではなく、既存リソースの読み取り権限が必要。権限エラーを解消して plan を再確認するまで apply しない。

### `Error: googleapi: Error 400: ... billingEnabled`
`aiplatform.googleapis.com` を有効化するには Billing が必要。`billing_account` を正しく指定すること。

### `Error: project ... already exists but is not managed by this terraform configuration`
`project_id` が既存の共有プロジェクトを指し、`imports.tf` が読み込まれていることを確認する。プロジェクトを新規作成して回避せず、上記の import 手順に戻る。

### `Permission denied` (apply 後の実行時)
ADC を更新してから実行: `gcloud auth application-default login && gcloud auth application-default set-quota-project <project-id>`
