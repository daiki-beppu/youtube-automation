resource "google_project_service" "wif" {
  for_each = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])

  project            = google_project.this.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = google_project.this.project_id
  workload_identity_pool_id = "github-actions-drift"
  display_name              = "GitHub Actions drift"
  depends_on                = [google_project_service.wif]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = google_project.this.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject" = "assertion.sub"
  }
  attribute_condition = "assertion.repository_owner_id == \"${var.github_repository_owner_id}\""
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "drift" {
  project      = google_project.this.project_id
  account_id   = "terraform-drift"
  display_name = "Read-only Terraform drift detection"
  depends_on   = [google_project_service.wif]
}

resource "google_service_account_iam_member" "github_main" {
  service_account_id = google_service_account.drift.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject/repo:daiki-beppu/youtube-automation:ref:refs/heads/main"
}

resource "google_project_iam_member" "drift_read" {
  for_each = toset([
    "roles/browser",
    "roles/serviceusage.serviceUsageViewer",
    "roles/iam.securityReviewer",
    "roles/iam.workloadIdentityPoolViewer",
  ])

  project = google_project.this.project_id
  role    = each.value
  member  = google_service_account.drift.member
}

# get と list を分離し、bucket 単位の list が object 本文へのアクセスを広げないようにする。
resource "google_project_iam_custom_role" "state_get" {
  project     = google_project.this.project_id
  role_id     = "terraformStateGet"
  title       = "Terraform state object read"
  permissions = ["storage.objects.get"]
}

resource "google_project_iam_custom_role" "state_list" {
  project     = google_project.this.project_id
  role_id     = "terraformStateList"
  title       = "Terraform state object listing"
  permissions = ["storage.objects.list"]
}

resource "google_storage_bucket_iam_member" "drift_state_get" {
  bucket = var.tfstate_bucket
  role   = google_project_iam_custom_role.state_get.name
  member = google_service_account.drift.member

  condition {
    title       = "gcp-state-only"
    description = "Other stacks may contain plaintext secrets"
    expression  = "resource.name.startsWith(\"projects/_/buckets/${var.tfstate_bucket}/objects/gcp/\")"
  }
}

resource "google_storage_bucket_iam_member" "drift_state_list" {
  bucket = var.tfstate_bucket
  role   = google_project_iam_custom_role.state_list.name
  member = google_service_account.drift.member
}
