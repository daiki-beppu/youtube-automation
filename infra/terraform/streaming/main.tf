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
    systemd_unit = templatefile("${path.module}/templates/youtube-stream.service.tftpl", {})
  })
}

resource "null_resource" "deploy" {
  triggers = {
    instance_id = vultr_instance.this.id
    video_hash  = filemd5(var.video_path)
    # SHA256 は不可逆なので nonsensitive() で剥がし triggers map に格納する
    # （terraform 1.5+ は sensitive 値の派生も sensitive 扱いするため必須）
    stream_key      = nonsensitive(sha256(var.stream_key))
    discord_webhook = nonsensitive(sha256(var.discord_webhook_url))
    healthcheck_sh  = filemd5("${path.module}/../../../scripts/streaming/healthcheck.sh")
    notify_sh       = filemd5("${path.module}/../../../scripts/streaming/notify.sh")
    logrotate_conf  = filemd5("${path.module}/../../../scripts/streaming/logrotate.conf")
    cron_d          = filemd5("${path.module}/../../../scripts/streaming/cron.d")
  }

  connection {
    type        = "ssh"
    user        = "root"
    host        = vultr_instance.this.main_ip
    private_key = file(pathexpand(var.ssh_priv_key_path))
  }

  provisioner "file" {
    source      = var.video_path
    destination = "/opt/youtube-stream/videos/current.mp4"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream.env.tftpl", {
      video    = "/opt/youtube-stream/videos/current.mp4"
      rtmp_url = "rtmp://a.rtmp.youtube.com/live2/${var.stream_key}"
    })
    destination = "/etc/youtube-stream.env"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream-healthcheck.env.tftpl", {
      webhook = var.discord_webhook_url
    })
    destination = "/etc/youtube-stream-healthcheck.env"
  }

  provisioner "file" {
    source      = "${path.module}/../../../scripts/streaming/healthcheck.sh"
    destination = "/opt/youtube-stream/bin/healthcheck.sh"
  }

  provisioner "file" {
    source      = "${path.module}/../../../scripts/streaming/notify.sh"
    destination = "/opt/youtube-stream/bin/notify.sh"
  }

  provisioner "file" {
    source      = "${path.module}/../../../scripts/streaming/logrotate.conf"
    destination = "/etc/logrotate.d/youtube-stream"
  }

  provisioner "file" {
    source      = "${path.module}/../../../scripts/streaming/cron.d"
    destination = "/etc/cron.d/youtube-stream-healthcheck"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod 600 /etc/youtube-stream.env",
      "chown root:root /etc/youtube-stream.env",
      "mkdir -p /opt/youtube-stream/bin",
      "chmod 755 /opt/youtube-stream/bin/healthcheck.sh /opt/youtube-stream/bin/notify.sh",
      "chmod 0600 /etc/youtube-stream-healthcheck.env",
      "chown root:root /etc/youtube-stream-healthcheck.env",
      "chmod 0644 /etc/cron.d/youtube-stream-healthcheck /etc/logrotate.d/youtube-stream",
      "systemctl daemon-reload",
      "systemctl enable --now youtube-stream",
      "systemctl restart youtube-stream",
      "systemctl restart cron",
    ]
  }
}
