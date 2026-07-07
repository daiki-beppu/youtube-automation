terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0, < 7.0"
    }
  }
}

provider "google" {
  # project / region は変数で指定せず、各リソース側で明示する
  # (既存プロジェクトを data source 越しに参照する場面でも動かすため)
}
