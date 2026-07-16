mock_provider "vultr" {
  mock_resource "vultr_instance" {
    defaults = {
      id      = "instance-test"
      main_ip = "127.0.0.1"
    }
  }
}

provider "null" {}

mock_provider "tls" {
  mock_resource "tls_private_key" {
    defaults = {
      private_key_openssh = "test-private-key"
      public_key_openssh  = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestHostKey"
    }
  }
}

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

run "setup_cloud_init_change" {
  command   = apply
  state_key = "cloud-init"

  module {
    source = "./tests/state_setup"
  }

  variables {
    host_algorithm   = "ED25519"
    user_data_suffix = "\n# previous cloud-init revision"
    install_root     = "/opt/youtube-stream"
  }
}

run "plan_cloud_init_change" {
  command   = plan
  state_key = "cloud-init"
}

run "setup_host_key_change" {
  command   = apply
  state_key = "host-key"

  module {
    source = "./tests/state_setup"
  }

  variables {
    host_algorithm   = "RSA"
    user_data_suffix = ""
    install_root     = "/opt/youtube-stream"
  }
}

run "plan_host_key_change" {
  command   = plan
  state_key = "host-key"
}

run "setup_install_root_change" {
  command   = apply
  state_key = "install-root"

  module {
    source = "./tests/state_setup"
  }

  variables {
    host_algorithm   = "ED25519"
    user_data_suffix = ""
    install_root     = "/opt/old-youtube-stream"
  }
}

run "plan_install_root_change" {
  command   = plan
  state_key = "install-root"
}
