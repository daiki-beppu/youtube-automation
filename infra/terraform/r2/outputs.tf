output "r2_account_id" {
  description = "R2_ACCOUNT_ID for MediaStore configuration."
  value       = var.cloudflare_account_id
}

output "r2_bucket" {
  description = "R2_BUCKET for MediaStore configuration."
  value       = cloudflare_r2_bucket.handoffs.name
}

output "r2_prefix" {
  description = "R2_PREFIX for MediaStore configuration."
  value       = var.object_prefix
}

output "r2_access_key_id" {
  description = "R2_ACCESS_KEY_ID generated for the bucket-scoped MediaStore token."
  value       = cloudflare_account_token.media_store.id
  sensitive   = true
}

output "r2_api_token" {
  description = "R2_API_TOKEN whose SHA-256 digest is the S3 Secret Access Key."
  value       = cloudflare_account_token.media_store.value
  sensitive   = true
}
