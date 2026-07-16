mock_provider "vultr" {}
mock_provider "null" {}
mock_provider "tls" {}

mock_provider "external" {
  mock_data "external" {
    defaults = {
      result = {
        ok              = "true"
        profile_ok      = "true"
        message         = "ok"
        profile_message = "ok"
      }
    }
  }
}

variables {
  vultr_api_key       = "test-api-key"
  ssh_pub_key_path    = "tests/fixtures/operator.pub"
  video_path          = "tests/fixtures/video.bin"
  stream_key          = "test-stream-key"
  discord_webhook_url = "https://example.invalid/webhook"
  allowed_ssh_cidr    = ["203.0.113.5/32"]
}

run "accepts_default" {
  command = plan
}

run "accepts_safe_override" {
  command = plan
  variables {
    install_root = "/srv/youtube_stream-2.0"
  }
}

run "rejects_dot_segment" {
  command = plan
  variables { install_root = "/opt/./stream" }
  expect_failures = [var.install_root]
}

run "rejects_parent_segment" {
  command = plan
  variables { install_root = "/opt/../stream" }
  expect_failures = [var.install_root]
}

run "rejects_root" {
  command = plan
  variables { install_root = "/" }
  expect_failures = [var.install_root]
}

run "rejects_double_slash" {
  command = plan
  variables { install_root = "/opt//stream" }
  expect_failures = [var.install_root]
}

run "rejects_trailing_slash" {
  command = plan
  variables { install_root = "/opt/stream/" }
  expect_failures = [var.install_root]
}

run "rejects_relative_path" {
  command = plan
  variables { install_root = "opt/stream" }
  expect_failures = [var.install_root]
}

run "rejects_empty_string" {
  command = plan
  variables { install_root = "" }
  expect_failures = [var.install_root]
}

run "rejects_whitespace_only" {
  command = plan
  variables { install_root = "   " }
  expect_failures = [var.install_root]
}

run "rejects_semicolon" {
  command = plan
  variables { install_root = "/opt/stream;id" }
  expect_failures = [var.install_root]
}

run "rejects_command_substitution" {
  command = plan
  variables { install_root = "/opt/$(id)" }
  expect_failures = [var.install_root]
}

run "rejects_pipe" {
  command = plan
  variables { install_root = "/opt/stream|id" }
  expect_failures = [var.install_root]
}

run "rejects_ampersand" {
  command = plan
  variables { install_root = "/opt/stream&id" }
  expect_failures = [var.install_root]
}
