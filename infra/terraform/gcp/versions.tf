terraform {
  required_version = "~> 1.15.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.40"
    }
  }
}

provider "google" {
  # project / region は変数で指定せず、各リソース側で明示する
  # (既存プロジェクトを data source 越しに参照する場面でも動かすため)
}
