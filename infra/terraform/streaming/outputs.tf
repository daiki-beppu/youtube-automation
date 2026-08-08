output "instance_ip" {
  description = "起動した Vultr VPS のパブリック IPv4 アドレス（ssh 接続先）"
  value       = vultr_instance.this.main_ip
}

output "instance_id" {
  description = "Vultr インスタンス ID（destroy / 個別操作時の識別子）"
  value       = vultr_instance.this.id
}

output "discord_webhook_setup_warning" {
  description = "Discord webhook が未設定の場合だけ apply 完了時に表示する復旧案内"
  sensitive   = false
  value = nonsensitive(trimspace(var.discord_webhook_url) == "") ? join("\n", [
    "WARNING: healthcheck の Discord webhook が未設定です。",
    "export TF_VAR_discord_webhook_url=\"$(op read 'op://Personal/YouTube_Stream_Discord_Webhook/url')\"",
    "設定後に terraform apply を再実行してください。",
  ]) : null
}
