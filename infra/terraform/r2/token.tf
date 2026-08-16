resource "cloudflare_account_token" "media_store" {
  account_id = var.cloudflare_account_id
  name       = "${local.resource_name}-media-store"
  status     = "active"

  policies = [{
    effect = "allow"
    permission_groups = [{
      id = var.r2_bucket_item_write_permission_group_id
    }]
    resources = jsonencode({
      (local.bucket_resource) = "*"
    })
  }]
}
