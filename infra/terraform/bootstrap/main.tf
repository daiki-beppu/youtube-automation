resource "google_storage_bucket" "tfstate" {
  name                        = var.bucket_name
  project                     = var.project_id
  location                    = var.location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age        = 30
      with_state = "ARCHIVED"
    }

    action {
      type = "Delete"
    }
  }
}
