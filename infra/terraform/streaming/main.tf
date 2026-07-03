locals {
  scripts_dir             = "${path.module}/../../../.claude/skills/streaming/references"
  ssh_host_key_algorithm  = "ED25519"
  ssh_host_public_key     = trimspace(tls_private_key.ssh_host.public_key_openssh)
  ssh_host_public_key_sha = sha256(local.ssh_host_public_key)
  source_video_preflight  = data.external.source_video_preflight.result
  source_video_ok         = local.source_video_preflight.ok == "true"
  source_video_profile_ok = local.source_video_preflight.profile_ok == "true"
}

data "external" "source_video_preflight" {
  program = ["python3", "${path.module}/video_preflight.py"]

  query = {
    video_path = var.video_path
  }
}

check "source_video_h264_profile" {
  assert {
    condition     = local.source_video_profile_ok
    error_message = local.source_video_preflight.profile_message
  }
}

resource "tls_private_key" "ssh_host" {
  algorithm = local.ssh_host_key_algorithm
}

resource "vultr_ssh_key" "this" {
  name    = "youtube-stream"
  ssh_key = file(pathexpand(var.ssh_pub_key_path))
}

resource "vultr_firewall_group" "stream" {
  description = "youtube-stream firewall group"
}

resource "vultr_firewall_rule" "ssh" {
  for_each          = toset(var.allowed_ssh_cidr)
  firewall_group_id = vultr_firewall_group.stream.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = split("/", each.value)[0]
  subnet_size       = tonumber(split("/", each.value)[1])
  port              = "22"
}

resource "vultr_instance" "this" {
  region   = var.region
  plan     = var.plan
  os_id    = var.os_id
  hostname = "youtube-stream"
  label    = "youtube-stream"
  tags     = ["youtube-stream"]

  firewall_group_id = vultr_firewall_group.stream.id

  ssh_key_ids = [vultr_ssh_key.this.id]

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    install_root         = var.install_root
    ssh_host_private_key = tls_private_key.ssh_host.private_key_openssh
    ssh_host_public_key  = local.ssh_host_public_key
  })
}

resource "null_resource" "deploy" {
  triggers = {
    instance_id  = vultr_instance.this.id
    video_hash   = filemd5(var.video_path)
    ssh_host_key = local.ssh_host_public_key_sha
    stream_hours = tostring(var.stream_hours)
    break_hours  = tostring(var.break_hours)
    # SHA256 は不可逆なので nonsensitive() で剥がし triggers map に格納する
    # （terraform 1.5+ は sensitive 値の派生も sensitive 扱いするため必須）
    stream_key      = nonsensitive(sha256(var.stream_key))
    discord_webhook = nonsensitive(sha256(var.discord_webhook_url))
    healthcheck_sh  = filemd5("${local.scripts_dir}/healthcheck.sh")
    notify_sh       = filemd5("${local.scripts_dir}/notify.sh")
    logrotate_conf  = filemd5("${path.module}/templates/logrotate.conf.tftpl")
    cron_d          = filemd5("${path.module}/templates/cron.d.tftpl")
    systemd_unit    = filemd5("${path.module}/templates/youtube-stream.service.tftpl")
    run_ffmpeg_sh   = filemd5("${local.scripts_dir}/run-ffmpeg.sh")
  }

  lifecycle {
    precondition {
      condition     = var.stream_hours > 0 || var.break_hours == 0
      error_message = "break_hours は stream_hours > 0 のときのみ有効です。24/7 モード (stream_hours=0) では break_hours=0 にしてください。"
    }
    precondition {
      condition     = local.source_video_ok
      error_message = local.source_video_preflight.message
    }
  }

  connection {
    type     = "ssh"
    host     = vultr_instance.this.main_ip
    user     = "root"
    agent    = true
    host_key = local.ssh_host_public_key
  }

  provisioner "file" {
    source      = var.video_path
    destination = "${var.install_root}/videos/current.mp4"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream.env.tftpl", {
      video    = "${var.install_root}/videos/current.mp4"
      rtmp_url = "rtmp://a.rtmp.youtube.com/live2/${var.stream_key}"
    })
    destination = "/tmp/youtube-stream.env.tmp"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream-healthcheck.env.tftpl", {
      webhook = var.discord_webhook_url
    })
    destination = "/tmp/youtube-stream-healthcheck.env.tmp"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream.service.tftpl", {
      install_root = var.install_root
      stream_hours = var.stream_hours
      break_hours  = var.break_hours
    })
    destination = "/etc/systemd/system/youtube-stream.service"
  }

  provisioner "file" {
    source      = "${local.scripts_dir}/healthcheck.sh"
    destination = "${var.install_root}/bin/healthcheck.sh"
  }

  provisioner "file" {
    source      = "${local.scripts_dir}/notify.sh"
    destination = "${var.install_root}/bin/notify.sh"
  }

  provisioner "file" {
    source      = "${local.scripts_dir}/run-ffmpeg.sh"
    destination = "${var.install_root}/bin/run-ffmpeg.sh"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/logrotate.conf.tftpl", {
      install_root = var.install_root
    })
    destination = "/etc/logrotate.d/youtube-stream"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/cron.d.tftpl", {
      install_root = var.install_root
    })
    destination = "/etc/cron.d/youtube-stream-healthcheck"
  }

  provisioner "remote-exec" {
    inline = [
      "umask 0077",
      "install -m 0600 -o root -g root /tmp/youtube-stream.env.tmp /etc/youtube-stream.env",
      "rm -f /tmp/youtube-stream.env.tmp",
      "install -m 0600 -o root -g root /tmp/youtube-stream-healthcheck.env.tmp /etc/youtube-stream-healthcheck.env",
      "rm -f /tmp/youtube-stream-healthcheck.env.tmp",
      "mkdir -p ${var.install_root}/bin",
      "chmod 755 ${var.install_root}/bin/healthcheck.sh ${var.install_root}/bin/notify.sh ${var.install_root}/bin/run-ffmpeg.sh",
      "chmod 0600 /etc/youtube-stream-healthcheck.env",
      "chown root:root /etc/youtube-stream-healthcheck.env",
      "chmod 0644 /etc/cron.d/youtube-stream-healthcheck /etc/logrotate.d/youtube-stream",
      # 止血措置として手動 rename された .disabled 残骸を除去（merge 後の cron 自動再開のため）
      "rm -f /etc/cron.d/youtube-stream-healthcheck.disabled",
      "systemctl daemon-reload",
      "systemctl enable --now youtube-stream",
      "systemctl restart youtube-stream",
      "systemctl restart cron",
    ]
  }
}
