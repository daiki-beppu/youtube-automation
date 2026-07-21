terraform {
  required_version = "~> 1.15.0"

  backend "gcs" {
    prefix = "streaming"
  }

  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.32"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.3"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.4"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.3"
    }
  }
}

provider "vultr" {
  api_key = var.vultr_api_key
}
