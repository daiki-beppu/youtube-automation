variable "vultr_api_key" {
  type        = string
  description = "Vultr API key. TF_VAR_vultr_api_key 経由で 1Password から注入する想定（sensitive=true は CLI 出力マスク）"
  sensitive   = true
}

variable "ssh_pub_key_path" {
  type        = string
  description = "Vultr に登録する SSH 公開鍵ファイルのパス（~ は pathexpand で展開される）"
  default     = "~/.ssh/yt_stream_key.pub"
}

variable "region" {
  type        = string
  description = "Vultr リージョンコード（例: nrt = 東京）"
  default     = "nrt"
}

variable "plan" {
  type        = string
  description = "Vultr プランコード（vc2-1c-2gb = $10/月, 1 vCPU, 2GB RAM, 55GB SSD, 2TB 帯域）"
  default     = "vc2-1c-2gb"
}

variable "os_id" {
  type        = number
  description = "Ubuntu 24.04 LTS x64 の Vultr OS ID。Vultr API は integer を要求するため number 型で扱う"
  default     = 2284
}

variable "video_path" {
  type        = string
  description = "VPS にアップロードするローカル動画ファイルの絶対パス（環境依存のため必須項目）"
}

variable "stream_key" {
  type        = string
  description = "YouTube Live のストリームキー。TF_VAR_stream_key 経由で 1Password から注入する想定（sensitive=true は CLI 出力マスク）"
  sensitive   = true
}

variable "discord_webhook_url" {
  type        = string
  description = "死活監視通知の送信先 Discord Webhook URL。TF_VAR_discord_webhook_url 経由で 1Password から注入する想定（sensitive=true は CLI 出力マスク）"
  sensitive   = true
}

variable "allowed_ssh_cidr" {
  type        = list(string)
  default     = []
  description = "SSH (22/tcp) 接続を許可する CIDR のリスト（例: [\"203.0.113.5/32\"]）。デフォルト [] のまま apply すると validation で fail する必須入力"

  validation {
    condition     = length(var.allowed_ssh_cidr) > 0
    error_message = "allowed_ssh_cidr を 1 件以上指定してください（例: 自分の IP を `curl -s ifconfig.me` で取得し \"203.0.113.5/32\" 形式で渡す）。"
  }
}
