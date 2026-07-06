resource "google_project_service" "apis" {
  for_each = toset(var.apis)

  project = local.project_id
  service = each.key

  # terraform destroy でも API は無効化しない (他の資産が残るケースを考慮)
  disable_on_destroy = false
}
