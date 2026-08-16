mock_provider "cloudflare" {}

variables {
  cloudflare_api_token         = "fixture-admin-token"
  cloudflare_account_id        = "0123456789abcdef0123456789abcdef"
  name_prefix                  = "youtube-automation"
  environment                  = "production"
  location                     = "apac"
  object_prefix                = "automation/v1"
  retention_days               = 7
  expected_monthly_collections = 4
}

run "plans_bucket_scoped_credentials_and_expiration" {
  command = plan

  assert {
    condition     = cloudflare_r2_bucket.handoffs.name == "youtube-automation-production-handoffs"
    error_message = "R2 bucket name must follow the shared environment naming contract."
  }

  assert {
    condition     = cloudflare_r2_bucket_lifecycle.handoffs.rules[0].conditions.prefix == "automation/v1/"
    error_message = "Lifecycle must be scoped to the MediaStore object prefix."
  }

  assert {
    condition     = cloudflare_r2_bucket_lifecycle.handoffs.rules[0].delete_objects_transition.condition.max_age == 604800
    error_message = "Completed handoffs must expire after retention_days."
  }

  assert {
    condition     = cloudflare_r2_bucket_lifecycle.handoffs.rules[0].abort_multipart_uploads_transition.condition.max_age == 604800
    error_message = "Incomplete multipart uploads must not outlive completed handoffs."
  }

  assert {
    condition     = cloudflare_account_token.media_store.policies[0].permission_groups[0].id == "2efd5506f9c8494dacb1fa10a3e7d5b6"
    error_message = "Runtime credentials must use the R2 bucket item write permission only."
  }

  assert {
    condition = jsondecode(cloudflare_account_token.media_store.policies[0].resources)[
      "com.cloudflare.edge.r2.bucket.0123456789abcdef0123456789abcdef_default_youtube-automation-production-handoffs"
    ] == "*"
    error_message = "Runtime credentials must be scoped to the provisioned bucket only."
  }
}

run "rejects_a_retention_budget_above_the_free_tier_guardrail" {
  command = plan

  variables {
    retention_days               = 8
    expected_monthly_collections = 4
  }

  expect_failures = [var.retention_days]
}
