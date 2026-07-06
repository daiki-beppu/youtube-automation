# プロジェクト: create_project=true なら resource で作成、そうでなければ data source で既存参照
resource "google_project" "this" {
  count = var.create_project ? 1 : 0

  project_id      = var.project_id
  name            = coalesce(var.project_name, var.project_id)
  billing_account = var.billing_account
  org_id          = var.org_id
  folder_id       = var.folder_id

  # terraform destroy 時にプロジェクトを本当に削除する
  # (共有プロジェクトを Terraform 管理下に置きたくない場合は create_project=false で)
  deletion_policy = "DELETE"
}

data "google_project" "this" {
  count      = var.create_project ? 0 : 1
  project_id = var.project_id
}

locals {
  project_id = var.create_project ? google_project.this[0].project_id : data.google_project.this[0].project_id
}
