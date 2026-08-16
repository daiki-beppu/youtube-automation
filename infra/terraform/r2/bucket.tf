locals {
  resource_name     = "${var.name_prefix}-${var.environment}"
  bucket_name       = "${local.resource_name}-handoffs"
  lifecycle_prefix  = "${var.object_prefix}/"
  retention_seconds = var.retention_days * 24 * 60 * 60
  bucket_resource   = "com.cloudflare.edge.r2.bucket.${var.cloudflare_account_id}_default_${local.bucket_name}"
}

resource "cloudflare_r2_bucket" "handoffs" {
  account_id    = var.cloudflare_account_id
  name          = local.bucket_name
  jurisdiction  = "default"
  location      = var.location
  storage_class = "Standard"

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_r2_bucket_lifecycle" "handoffs" {
  account_id   = var.cloudflare_account_id
  bucket_name  = cloudflare_r2_bucket.handoffs.name
  jurisdiction = "default"

  rules = [{
    id      = "expire-media-handoffs"
    enabled = true
    conditions = {
      prefix = local.lifecycle_prefix
    }
    delete_objects_transition = {
      condition = {
        type    = "Age"
        max_age = local.retention_seconds
      }
    }
    abort_multipart_uploads_transition = {
      condition = {
        type    = "Age"
        max_age = local.retention_seconds
      }
    }
  }]
}
