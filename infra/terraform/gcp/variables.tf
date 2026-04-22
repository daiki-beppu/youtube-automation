variable "project_id" {
  type        = string
  description = "GCP project ID (作成する or 既存流用する)"
}

variable "project_name" {
  type        = string
  description = "プロジェクト表示名。未指定なら project_id を流用"
  default     = null
}

variable "create_project" {
  type        = bool
  description = "true の場合 google_project で新規作成。false なら data source で既存を参照"
  default     = false
}

variable "billing_account" {
  type        = string
  description = "Billing account ID (例: 012345-6789AB-CDEF01)。create_project=true なら必須、aiplatform を使うなら実質必須"
  default     = null
}

variable "org_id" {
  type        = string
  description = "Organization ID (任意)。folder_id と同時指定不可"
  default     = null
}

variable "folder_id" {
  type        = string
  description = "Folder ID (任意)"
  default     = null
}

variable "location" {
  type        = string
  description = "Vertex AI リージョン。.env の GOOGLE_CLOUD_LOCATION へ反映"
  default     = "us-central1"
}

variable "adc_email" {
  type        = string
  description = "roles/aiplatform.user を付与する Google アカウント (ADC で使うユーザー)"
}

variable "apis" {
  type        = list(string)
  description = "有効化する GCP API 一覧"
  default = [
    "youtube.googleapis.com",
    "youtubeanalytics.googleapis.com",
    "aiplatform.googleapis.com",
    "generativelanguage.googleapis.com",
  ]
}
