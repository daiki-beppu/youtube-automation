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

variable "install_root" {
  type        = string
  description = "VPS 上で動画・ログ・運用スクリプトを配置する root ディレクトリ"
  default     = "/opt/youtube-stream"
}

variable "stream_hours" {
  type        = number
  description = "1 回の配信継続時間（時間）。0 は無制限を表し、24/7 連続配信として RuntimeMaxSec を省略する"
  default     = 0

  validation {
    condition     = var.stream_hours >= 0
    error_message = "stream_hours は 0 以上を指定してください（0 = 24/7 連続配信、正数 = 配信時間（時間））。"
  }
}

variable "break_hours" {
  type        = number
  description = "配信終了後の休止時間（時間）。0 は休止なしを表し、クラッシュ時の再起動間隔 RestartSec=10s を使用する"
  default     = 0

  validation {
    condition     = var.break_hours >= 0
    error_message = "break_hours は 0 以上を指定してください（0 = 休止なし、正数 = 休止時間（時間））。"
  }
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

variable "enable_live_chat_reply" {
  type        = bool
  description = "Codex によるライブチャット返信 daemon を同居させる opt-in"
  default     = false
}

variable "live_chat_channel_dir" {
  type        = string
  description = "config/channel/comments.json を含むローカル channel root。enable 時のみ必須"
  default     = ""
}

variable "live_chat_automation_git_ref" {
  type        = string
  description = "VPS に install する youtube-automation の Git ref。本番では commit SHA pin を推奨"
  default     = "main"

  validation {
    condition     = can(regex("^[0-9A-Za-z._/-]+$", var.live_chat_automation_git_ref))
    error_message = "live_chat_automation_git_ref は Git ref に使える英数字と ._/- のみ指定できます。"
  }
}

variable "live_chat_codex_version" {
  type        = string
  description = "OpenAI 公式 install.sh で導入する Codex CLI version"
  default     = "0.144.1"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+([-.][0-9A-Za-z.]+)?$", var.live_chat_codex_version))
    error_message = "live_chat_codex_version は x.y.z 形式で指定してください。"
  }
}

variable "live_chat_credentials_revision" {
  type        = string
  description = "ephemeral 認証の差し替えを検知する非秘密 revision（deploy script が SHA-256 を設定）"
  default     = ""
}

variable "live_chat_youtube_token_json" {
  type        = string
  description = "YouTube OAuth token.json の内容。state / plan に保存しない ephemeral secret"
  sensitive   = true
  ephemeral   = true
  default     = ""
}

variable "live_chat_client_secrets_json" {
  type        = string
  description = "YouTube OAuth client_secrets.json の内容。state / plan に保存しない ephemeral secret"
  sensitive   = true
  ephemeral   = true
  default     = ""
}

variable "live_chat_codex_auth_json" {
  type        = string
  description = "Codex auth.json の内容。state / plan に保存しない ephemeral secret"
  sensitive   = true
  ephemeral   = true
  default     = ""
}
