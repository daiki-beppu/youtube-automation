# infra/terraform/r2

ハイブリッド制作の境界受け渡し専用 R2 bucket、bucket-scoped runtime token、object / 未完了 multipart upload の lifecycle 削除を管理する Terraform stack。

## 管理するリソース

- `cloudflare_r2_bucket`: `${name_prefix}-${environment}-handoffs`
- `cloudflare_r2_bucket_lifecycle`: `object_prefix` 配下の object と未完了 multipart upload を `retention_days` 後に削除
- `cloudflare_account_token`: 作成した bucket だけに `Workers R2 Storage Bucket Item Write` を許可

`retention_days * expected_monthly_collections <= 30` を変数 validation で強制し、ADR-0024 の R2 無料枠 guardrail を超える plan を拒否する。bucket 自体は `prevent_destroy` で保護する。

## 前提

- Terraform 1.15.x
- `infra/terraform/bootstrap` で作成した GCS tfstate bucket
- Terraform bootstrap token に `Workers R2 Storage Write` と `Account API Tokens Write` があること
- 1Password CLI で bootstrap token を取得できること

## plan / apply

```bash
cd infra/terraform/r2
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars は non-secret 値だけを編集する

export TF_VAR_cloudflare_api_token="$(op read 'op://Personal/Cloudflare Terraform API Token/credential')"
terraform init -backend-config="bucket=<tfstate-bucket-name>"
terraform plan
terraform apply
```

`terraform.tfvars` や保存済み plan file に token を書き出さない。`sensitive = true` は CLI 表示を隠すだけで、token value は tfstate に平文で保持される。state は GCS backend の暗号化・IAM・versioning で保護する。

実行前に plan が R2 stack の bucket / lifecycle / token だけを作成・変更し、別 resource の削除や置換を含まないことを確認する。想定外の差分があれば apply しない。

## MediaStore secret への受け渡し

apply 後、`r2_access_key_id` と `r2_api_token` の sensitive output はファイルや shell 履歴へ保存せず、既存の 1Password item へ直接登録する。

非 secret は次で確認できる。

```bash
terraform output r2_account_id
terraform output r2_bucket
terraform output r2_prefix
```

下流 runtime はそれぞれ `R2_ACCOUNT_ID` / `R2_BUCKET` / `R2_PREFIX` として渡す。1Password の `access_key_id` / `api_token` は `R2_ACCESS_KEY_ID` / `R2_API_TOKEN` の既存 secret owner へ接続する。API token の ID が S3 Access Key ID、token value の SHA-256 が S3 Secret Access Key になる。

## 非破壊検証

Cloudflare account へ接続しない static / mock plan gate:

```bash
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
terraform test
```

`terraform test` は mock provider の plan だけを使い、実 resource は作成しない。
