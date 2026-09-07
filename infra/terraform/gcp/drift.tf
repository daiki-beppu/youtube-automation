# drift SA が project を読むために必要な CI 前提 API (#4932)。
# 取り込み済み 6 API を並べた apis.tf の var.apis へは足さず、別 resource で管理する
# (ADR-0030 の import 対象と drift 検知の前提を resource 単位で区別するため)。
resource "google_project_service" "drift_resource_manager" {
  project            = google_project.this.project_id
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}
