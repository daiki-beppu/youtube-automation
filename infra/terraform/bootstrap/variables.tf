variable "project_id" {
  type        = string
  description = "GCP project ID that owns the Terraform state bucket."
}

variable "bucket_name" {
  type        = string
  description = "Globally unique GCS bucket name for Terraform remote state."
}

variable "location" {
  type        = string
  description = "GCS bucket location for Terraform remote state."
  default     = "asia-northeast1"
}
