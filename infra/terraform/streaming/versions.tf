terraform {
  required_version = ">= 1.5"

  backend "gcs" {
    prefix = "streaming"
  }

  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = ">= 2.0"
    }
    null = {
      source  = "hashicorp/null"
      version = ">= 3.2"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0"
    }
  }
}

provider "vultr" {
  api_key = var.vultr_api_key
}
