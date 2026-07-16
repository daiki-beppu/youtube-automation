terraform {
  required_providers {
    vultr = { source = "vultr/vultr" }
    null  = { source = "hashicorp/null" }
    tls   = { source = "hashicorp/tls" }
  }
}

variable "host_algorithm" {
  type = string
}

variable "user_data_suffix" {
  type = string
}

variable "install_root" {
  type = string
}

resource "tls_private_key" "ssh_host" {
  algorithm = var.host_algorithm
}

locals {
  ssh_host_public_key     = trimspace(tls_private_key.ssh_host.public_key_openssh)
  ssh_host_public_key_sha = sha256(local.ssh_host_public_key)
  scripts_dir             = "${path.module}/../../../../../.claude/skills/streaming/references"
}

resource "vultr_ssh_key" "this" {
  name    = "youtube-stream"
  ssh_key = file("${path.module}/../fixtures/operator.pub")
}

resource "vultr_firewall_group" "stream" {
  description = "youtube-stream firewall group"
}

resource "vultr_firewall_rule" "ssh" {
  for_each          = toset(["203.0.113.5/32"])
  firewall_group_id = vultr_firewall_group.stream.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = split("/", each.value)[0]
  subnet_size       = tonumber(split("/", each.value)[1])
  port              = "22"
}

resource "vultr_instance" "this" {
  region   = "nrt"
  plan     = "vc2-1c-2gb"
  os_id    = 2284
  hostname = "youtube-stream"
  label    = "youtube-stream"
  tags     = ["youtube-stream"]

  firewall_group_id = vultr_firewall_group.stream.id
  ssh_key_ids       = [vultr_ssh_key.this.id]
  user_data = "${templatefile("${path.module}/../../cloud-init.yaml", {
    ssh_host_private_key = tls_private_key.ssh_host.private_key_openssh
    ssh_host_public_key  = local.ssh_host_public_key
  })}${var.user_data_suffix}"
}

resource "null_resource" "deploy" {
  triggers = {
    instance_id     = vultr_instance.this.id
    video_hash      = filemd5("${path.module}/../fixtures/video.bin")
    ssh_host_key    = local.ssh_host_public_key_sha
    install_root    = var.install_root
    stream_hours    = "0"
    break_hours     = "0"
    stream_key      = sha256("test-stream-key")
    discord_webhook = sha256("https://example.invalid/webhook")
    healthcheck_sh  = filemd5("${local.scripts_dir}/healthcheck.sh")
    notify_sh       = filemd5("${local.scripts_dir}/notify.sh")
    logrotate_conf  = filemd5("${path.module}/../../templates/logrotate.conf.tftpl")
    cron_d          = filemd5("${path.module}/../../templates/cron.d.tftpl")
    systemd_unit    = filemd5("${path.module}/../../templates/youtube-stream.service.tftpl")
    run_ffmpeg_sh   = filemd5("${local.scripts_dir}/run-ffmpeg.sh")
  }
}
