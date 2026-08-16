variable "cloudflare_api_token" {
  type        = string
  description = "Terraform bootstrap token. Inject through TF_VAR_cloudflare_api_token from 1Password."
  sensitive   = true
}

variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare account ID that owns the R2 bucket."

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.cloudflare_account_id))
    error_message = "cloudflare_account_id must be a 32-character lowercase hexadecimal account ID."
  }
}

variable "r2_bucket_item_write_permission_group_id" {
  type        = string
  description = "Public Cloudflare permission group ID for Workers R2 Storage Bucket Item Write."
  default     = "2efd5506f9c8494dacb1fa10a3e7d5b6"

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.r2_bucket_item_write_permission_group_id))
    error_message = "r2_bucket_item_write_permission_group_id must be a 32-character lowercase hexadecimal permission group ID."
  }
}

variable "name_prefix" {
  type        = string
  description = "Shared lowercase prefix used for every R2 resource name."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]*[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must contain lowercase letters, digits, and internal hyphens only."
  }
}

variable "environment" {
  type        = string
  description = "Deployment environment included in every R2 resource name."

  validation {
    condition = (
      can(regex("^[a-z0-9][a-z0-9-]*[a-z0-9]$", var.environment))
      && length("${var.name_prefix}-${var.environment}-handoffs") <= 63
    )
    error_message = "environment must be lowercase kebab-case and keep the generated bucket name within 63 characters."
  }
}

variable "location" {
  type        = string
  description = "R2 location hint used only when the bucket is first created."

  validation {
    condition     = contains(["apac", "eeur", "enam", "weur", "wnam", "oc"], var.location)
    error_message = "location must be one of apac, eeur, enam, weur, wnam, or oc."
  }
}

variable "object_prefix" {
  type        = string
  description = "R2 key prefix shared by MediaStore and the lifecycle rule, without leading or trailing slash."

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$", var.object_prefix)) && !strcontains(var.object_prefix, "//") && !strcontains(var.object_prefix, "..")
    error_message = "object_prefix must be a relative key prefix without empty or parent segments."
  }
}

variable "retention_days" {
  type        = number
  description = "Whole days before handoff objects and incomplete multipart uploads are deleted."

  validation {
    condition = (
      var.retention_days >= 1
      && floor(var.retention_days) == var.retention_days
      && var.retention_days * var.expected_monthly_collections <= 30
    )
    error_message = "retention_days must be a positive integer and retention_days * expected_monthly_collections must not exceed 30."
  }
}

variable "expected_monthly_collections" {
  type        = number
  description = "Upper bound of monthly collections used to enforce the R2 free-tier retention guardrail."

  validation {
    condition     = var.expected_monthly_collections >= 1 && floor(var.expected_monthly_collections) == var.expected_monthly_collections
    error_message = "expected_monthly_collections must be a positive integer."
  }
}
