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
