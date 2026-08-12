output "project_id" {
  description = "確定した GCP project ID"
  value       = local.project_id
}

output "oauth_console_url" {
  description = "Google Auth Platform の Branding / Audience / Clients 手動設定用 Console URL"
  value       = "https://console.cloud.google.com/apis/credentials?project=${local.project_id}"
}

output "enabled_apis" {
  description = "有効化した API 一覧"
  value       = [for api in google_project_service.apis : api.service]
}
