resource "google_project" "this" {
  project_id      = var.project_id
  name            = coalesce(var.project_name, var.project_id)
  billing_account = var.billing_account
  org_id          = var.org_id
  folder_id       = var.folder_id

  # 全チャンネルで共有するプロジェクトの削除事故を二重に防ぐ。
  deletion_policy = "PREVENT"

  lifecycle {
    prevent_destroy = true
  }
}
