output "instance_ip" {
  description = "起動した Vultr VPS のパブリック IPv4 アドレス（ssh 接続先）"
  value       = vultr_instance.this.main_ip
}

output "instance_id" {
  description = "Vultr インスタンス ID（destroy / 個別操作時の識別子）"
  value       = vultr_instance.this.id
}
