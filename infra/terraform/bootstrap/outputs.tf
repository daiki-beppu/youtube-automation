output "bucket_name" {
  description = "GCS bucket name for Terraform remote state."
  value       = google_storage_bucket.tfstate.name
}
