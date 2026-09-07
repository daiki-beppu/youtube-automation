output "project_id" {
  description = "確定した GCP project ID"
  value       = google_project.this.project_id
}

output "oauth_console_url" {
  description = "Google Auth Platform の Branding / Audience / Clients 手動設定用 Console URL"
  value       = "https://console.cloud.google.com/apis/credentials?project=${google_project.this.project_id}"
}

output "enabled_apis" {
  description = "有効化した API 一覧"
  value       = [for api in google_project_service.apis : api.service]
}

output "wif_provider_name" {
  description = "GitHub Actions auth の workload_identity_provider (非 secret)"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "drift_service_account_email" {
  description = "GitHub Actions の読み取り専用 drift SA (非 secret)"
  value       = google_service_account.drift.email
}
