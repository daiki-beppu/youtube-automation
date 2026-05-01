resource "vultr_ssh_key" "this" {
  name    = "youtube-stream"
  ssh_key = file(pathexpand(var.ssh_pub_key_path))
}

resource "vultr_instance" "this" {
  region   = var.region
  plan     = var.plan
  os_id    = var.os_id
  hostname = "youtube-stream"
  label    = "youtube-stream"
  tags     = ["youtube-stream"]

  ssh_key_ids = [vultr_ssh_key.this.id]

  user_data = base64encode(templatefile("${path.module}/cloud-init.yaml", {
    systemd_unit = templatefile("${path.module}/templates/youtube-stream.service.tftpl", {})
  }))
}

resource "null_resource" "deploy" {
  triggers = {
    instance_id = vultr_instance.this.id
    video_hash  = filemd5(var.video_path)
    # SHA256 は不可逆なので nonsensitive() で剥がし triggers map に格納する
    # （terraform 1.5+ は sensitive 値の派生も sensitive 扱いするため必須）
    stream_key = nonsensitive(sha256(var.stream_key))
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

  provisioner "remote-exec" {
    inline = [
      "chmod 600 /etc/youtube-stream.env",
      "chown root:root /etc/youtube-stream.env",
      "systemctl daemon-reload",
      "systemctl enable --now youtube-stream",
      "systemctl restart youtube-stream",
    ]
  }
}
