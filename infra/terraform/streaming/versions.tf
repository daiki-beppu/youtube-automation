terraform {
  required_version = ">= 1.5"

  backend "s3" {
    bucket         = "youtube-automation-tfstate"
    key            = "streaming/terraform.tfstate"
    region         = "ap-northeast-1"
    kms_key_id     = "alias/tfstate"
    encrypt        = true
    dynamodb_table = "tfstate-lock"
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
  }
}

provider "vultr" {
  api_key = var.vultr_api_key
}
