terraform {
  required_version = "~> 1.15.0"

  backend "gcs" {
    prefix = "r2"
  }

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.22.0"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
