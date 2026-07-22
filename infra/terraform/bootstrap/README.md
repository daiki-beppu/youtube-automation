# infra/terraform/bootstrap

Terraform state を置く GCS bucket を作成する bootstrap stack。

`infra/terraform/streaming` 自身の state を同じ stack で管理すると初回作成前に backend が存在しないため、この stack だけ local state で管理する。作成後の `streaming` state は GCS backend へ移行する。

## 管理するリソース

- `google_storage_bucket` x 1
  - Google 管理鍵によるデフォルト暗号化
  - versioning 有効
  - uniform bucket-level access 有効
  - public access prevention enforced
  - 30 日を超えた古い object 世代を削除

## 前提

- `terraform` 1.15.x インストール済み
- `gcloud auth application-default login` 実行済み
- `storage.googleapis.com` が対象 project で有効化済み

## 使い方

```bash
cp terraform.tfvars.example terraform.tfvars
# project_id / bucket_name を実値に書き換える

terraform init
terraform plan
terraform apply
```

作成した bucket 名は `terraform output bucket_name` で確認する。

## local state を維持する理由

この stack は remote state bucket そのものを作るため、remote backend へ移すと bucket 削除や再作成時の循環依存が発生する。bootstrap stack の local state は operator の管理下で保管し、`streaming` stack の state だけを GCS backend に置く。
