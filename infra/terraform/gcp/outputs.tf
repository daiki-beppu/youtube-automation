output "project_id" {
  description = "確定した GCP project ID"
  value       = local.project_id
}

output "location" {
  description = "Vertex AI リージョン"
  value       = var.location
}

output "env_vars" {
  description = ".env に流し込むキー/値 (ラッパースクリプトが利用)"
  value = {
    GOOGLE_GENAI_USE_VERTEXAI = "true"
    GOOGLE_CLOUD_PROJECT      = local.project_id
    GOOGLE_CLOUD_LOCATION     = var.location
  }
}

output "oauth_console_url" {
  description = "OAuth クライアント ID を作成する Console URL (手動操作が必要な唯一のステップ)"
  value       = "https://console.cloud.google.com/apis/credentials?project=${local.project_id}"
}

output "enabled_apis" {
  description = "有効化した API 一覧"
  value       = [for api in google_project_service.apis : api.service]
}
