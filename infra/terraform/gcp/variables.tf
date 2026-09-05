variable "project_id" {
  type        = string
  description = "Terraform が管理する既存の共有 GCP project ID"
}

variable "project_name" {
  type        = string
  description = "プロジェクト表示名。未指定なら project_id を流用"
  default     = null
}

variable "billing_account" {
  type        = string
  description = "共有プロジェクトに紐付ける Billing account ID (例: 012345-6789AB-CDEF01)"
  sensitive   = true
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

variable "adc_email" {
  type        = string
  description = "roles/aiplatform.user を付与する Google アカウント (ADC で使うユーザー)"
  sensitive   = true
}

variable "apis" {
  type        = list(string)
  description = "有効化する GCP API 一覧"
  default = [
    "youtube.googleapis.com",
    "youtubeanalytics.googleapis.com",
    "youtubereporting.googleapis.com",
    "aiplatform.googleapis.com",
    "generativelanguage.googleapis.com",
    "storage.googleapis.com",
  ]
}
