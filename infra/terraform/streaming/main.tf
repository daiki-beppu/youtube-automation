locals {
  scripts_dir             = "${path.module}/../../../.claude/skills/streaming/references"
  ssh_host_key_algorithm  = "ED25519"
  ssh_host_public_key     = trimspace(tls_private_key.ssh_host.public_key_openssh)
  ssh_host_public_key_sha = sha256(local.ssh_host_public_key)
  source_video_preflight  = data.external.source_video_preflight.result
  source_video_ok         = local.source_video_preflight.ok == "true"
  source_video_profile_ok = local.source_video_preflight.profile_ok == "true"
  live_chat_config_dir    = "${var.live_chat_channel_dir}/config/channel"
  live_chat_config_files  = var.enable_live_chat_reply ? fileset(local.live_chat_config_dir, "*.json") : toset([])
  live_chat_config_hash = var.enable_live_chat_reply ? sha256(join("", [
    for name in sort(tolist(local.live_chat_config_files)) : filesha256("${local.live_chat_config_dir}/${name}")
  ])) : "disabled"
  live_chat_install_root = "${var.install_root}/live-chat-reply"
  live_chat_state_root   = "/var/lib/live-chat-reply"
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

  provisioner "remote-exec" {
    inline = [
      "install -d -m 0700 -o root -g root /run/youtube-stream-provision",
    ]
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream.env.tftpl", {
      video    = "${var.install_root}/videos/current.mp4"
      rtmp_url = "rtmp://a.rtmp.youtube.com/live2/${var.stream_key}"
    })
    destination = "/run/youtube-stream-provision/youtube-stream.env.tmp"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream-healthcheck.env.tftpl", {
      webhook = var.discord_webhook_url
    })
    destination = "/run/youtube-stream-provision/youtube-stream-healthcheck.env.tmp"
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
      "install -m 0600 -o root -g root /run/youtube-stream-provision/youtube-stream.env.tmp /etc/youtube-stream.env",
      "rm -f /run/youtube-stream-provision/youtube-stream.env.tmp",
      "install -m 0600 -o root -g root /run/youtube-stream-provision/youtube-stream-healthcheck.env.tmp /etc/youtube-stream-healthcheck.env",
      "rm -f /run/youtube-stream-provision/youtube-stream-healthcheck.env.tmp",
      "rm -rf /run/youtube-stream-provision",
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

resource "null_resource" "live_chat_reply" {
  count      = var.enable_live_chat_reply ? 1 : 0
  depends_on = [null_resource.deploy]

  triggers = {
    instance_id         = vultr_instance.this.id
    instance_ip         = vultr_instance.this.main_ip
    ssh_host_key        = local.ssh_host_public_key
    channel_config_hash = local.live_chat_config_hash
    credentials         = var.live_chat_credentials_revision
    automation_git_ref  = var.live_chat_automation_git_ref
    codex_version       = var.live_chat_codex_version
    install_root        = local.live_chat_install_root
    systemd_unit        = filemd5("${path.module}/templates/live-chat-reply.service.tftpl")
  }

  lifecycle {
    precondition {
      condition     = try(fileexists("${local.live_chat_config_dir}/comments.json"), false)
      error_message = "enable_live_chat_reply=true では live_chat_channel_dir/config/channel/comments.json が必要です。"
    }
    precondition {
      condition = try(
        jsondecode(file("${local.live_chat_config_dir}/comments.json")).comments.live_chat.enabled == true,
        false,
      )
      error_message = "comments.json の comments.live_chat.enabled を true にしてください。"
    }
    precondition {
      condition     = length(var.live_chat_credentials_revision) == 64
      error_message = "live_chat_credentials_revision に deploy script が生成する SHA-256 を指定してください。"
    }
  }

  connection {
    type     = "ssh"
    host     = self.triggers.instance_ip
    user     = "root"
    agent    = true
    host_key = self.triggers.ssh_host_key
  }

  provisioner "remote-exec" {
    inline = [
      "install -d -m 0700 -o root -g root /run/live-chat-reply",
    ]
  }

  provisioner "file" {
    source      = local.live_chat_config_dir
    destination = "/run/live-chat-reply/"
  }

  provisioner "file" {
    content     = var.live_chat_youtube_token_json
    destination = "/run/live-chat-reply/token.json"
  }

  provisioner "file" {
    content     = var.live_chat_client_secrets_json
    destination = "/run/live-chat-reply/client_secrets.json"
  }

  provisioner "file" {
    content     = var.live_chat_codex_auth_json
    destination = "/run/live-chat-reply/codex-auth.json"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/live-chat-reply.service.tftpl", {
      install_root = local.live_chat_install_root
      state_root   = local.live_chat_state_root
    })
    destination = "/run/live-chat-reply/live-chat-reply.service"
  }

  provisioner "remote-exec" {
    inline = [
      "set -eu",
      "export DEBIAN_FRONTEND=noninteractive",
      "apt-get update -qq",
      "apt-get install -y -qq ca-certificates curl git python3-venv",
      "python3 -m json.tool /run/live-chat-reply/token.json >/dev/null",
      "python3 -m json.tool /run/live-chat-reply/client_secrets.json >/dev/null",
      "python3 -m json.tool /run/live-chat-reply/codex-auth.json >/dev/null",
      "id -u live-chat-reply >/dev/null 2>&1 || useradd --system --home-dir ${local.live_chat_state_root} --create-home --shell /usr/sbin/nologin live-chat-reply",
      "install -d -m 0755 -o root -g root ${local.live_chat_install_root}",
      "install -d -m 0700 -o live-chat-reply -g live-chat-reply ${local.live_chat_state_root}/channel/auth ${local.live_chat_state_root}/channel/config/channel ${local.live_chat_state_root}/codex",
      "cp -a /run/live-chat-reply/channel/. ${local.live_chat_state_root}/channel/config/channel/",
      "chown -R live-chat-reply:live-chat-reply ${local.live_chat_state_root}/channel/config",
      "find ${local.live_chat_state_root}/channel/config -type f -exec chmod 0600 {} +",
      "install -m 0600 -o live-chat-reply -g live-chat-reply /run/live-chat-reply/token.json ${local.live_chat_state_root}/channel/auth/token.json",
      "install -m 0600 -o live-chat-reply -g live-chat-reply /run/live-chat-reply/client_secrets.json ${local.live_chat_state_root}/channel/auth/client_secrets.json",
      "install -m 0600 -o live-chat-reply -g live-chat-reply /run/live-chat-reply/codex-auth.json ${local.live_chat_state_root}/codex/auth.json",
      "curl -fsSL https://chatgpt.com/codex/install.sh -o /run/live-chat-reply/codex-install.sh",
      "CODEX_RELEASE=${var.live_chat_codex_version} CODEX_NON_INTERACTIVE=1 CODEX_INSTALL_DIR=/usr/local/bin CODEX_HOME=${local.live_chat_state_root}/codex sh /run/live-chat-reply/codex-install.sh",
      "python3 -m venv ${local.live_chat_install_root}/venv",
      "${local.live_chat_install_root}/venv/bin/pip install --quiet --upgrade pip",
      "${local.live_chat_install_root}/venv/bin/pip install --quiet --upgrade git+https://github.com/daiki-beppu/youtube-automation.git@${var.live_chat_automation_git_ref}",
      "install -m 0644 -o root -g root /run/live-chat-reply/live-chat-reply.service /etc/systemd/system/live-chat-reply.service",
      "rm -rf /run/live-chat-reply",
      "systemctl daemon-reload",
      "systemctl enable --now live-chat-reply",
      "systemctl restart live-chat-reply",
      "systemctl is-active --quiet live-chat-reply",
    ]
  }

  provisioner "remote-exec" {
    when       = destroy
    on_failure = continue
    inline = [
      "systemctl disable --now live-chat-reply 2>/dev/null || true",
      "rm -f /etc/systemd/system/live-chat-reply.service",
      "rm -rf /var/lib/live-chat-reply ${self.triggers.install_root}",
      "systemctl daemon-reload",
    ]
  }
}
