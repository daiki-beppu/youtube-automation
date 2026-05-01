# infra/terraform/streaming

Vultr VPS をプロビジョニングし、ローカル MP4 を YouTube Live に常時配信する Terraform モジュール。`terraform apply` 一発で「VPS 作成 → cloud-init で systemd unit 配置 → 動画アップロード → `.env` 配置 → 配信開始」までを完結する。

配信は systemd の `RuntimeMaxSec=11h` + `RestartSec=1h` により **11 時間配信 → 1 時間休止 → 自動再開** のサイクルで自律的に回る（YouTube が 12 時間以上のライブをアーカイブしない仕様への対応）。

## 管理するリソース

- `vultr_ssh_key` × 1（VPS 作成時に登録する SSH 公開鍵）
- `vultr_instance` × 1（Ubuntu 24.04 LTS / vc2-1c-2gb / 東京リージョン）
- `null_resource.deploy` × 1（動画アップロード + `EnvironmentFile` 配置 + systemd 起動 + 死活監視配置）

## 前提

- `terraform` >= 1.5 インストール済み
- Vultr API キーを 1Password に保管済み（または環境変数で渡せる状態）
- YouTube Studio で発行したストリームキーを 1Password に保管済み
- SSH 鍵ペア `~/.ssh/yt_stream_key` / `~/.ssh/yt_stream_key.pub` を生成済み
- 配信対象の MP4 ファイルがローカルにある（絶対パス）

## 使い方

```bash
# 1. tfvars を用意
cd infra/terraform/streaming
cp terraform.tfvars.example terraform.tfvars
# → video_path を実値（絶対パス）に書き換え

# 2. secret を環境変数経由で注入（1Password CLI 推奨）
export TF_VAR_vultr_api_key=$(op read 'op://Personal/Vultr/api_key')
export TF_VAR_stream_key=$(op read 'op://Personal/YouTube/stream_key')
export TF_VAR_discord_webhook_url=$(op read 'op://Personal/YouTube_Stream_Discord_Webhook/url')

# 3. apply
terraform init
terraform plan
terraform apply
```

`terraform.tfvars` および環境変数いずれにも secret 値を書かない（`stream_key` / `vultr_api_key` は `TF_VAR_*` のみ。tfstate には sensitive 扱いで保存される）。

## 配信サイクル（11h + 1h）

systemd unit が以下の挙動を持つ:

- `RuntimeMaxSec=11h`: 配信開始から 11 時間で `ffmpeg` プロセスを強制停止 → YouTube 側でアーカイブ生成
- `Restart=always` + `RestartSec=1h`: 停止から 1 時間後に自動再起動 → 2 本目の配信が始まる
- `EnvironmentFile=/etc/youtube-stream.env` から `VIDEO` / `RTMP_URL` を読み込むため、`ExecStart` に stream key が平文で残らない

`null_resource.deploy` は `terraform apply` のたびに以下のトリガーを比較し、差分があれば再実行する:

| trigger | 反応する変更 |
|---|---|
| `instance_id` | VPS 再作成 |
| `video_hash`（`filemd5(var.video_path)`）| 動画ファイルの差し替え |
| `stream_key`（`nonsensitive(sha256(var.stream_key))`）| ストリームキーの差し替え |

同じ動画 / 同じキーで再 apply すると no-op（冪等）。

## 動作確認

VPS 上で以下を実行する（ホスト名は `terraform output instance_ip` で確認）:

```bash
# サービス状態（active / inactive / failed）
ssh -i ~/.ssh/yt_stream_key root@<instance_ip> systemctl status youtube-stream

# 11h+1h サイクルが効いているか確認
ssh -i ~/.ssh/yt_stream_key root@<instance_ip> systemctl show youtube-stream | grep -E 'RuntimeMaxUSec|RestartUSec'

# リアルタイムログ（ffmpeg の出力）
ssh -i ~/.ssh/yt_stream_key root@<instance_ip> journalctl -u youtube-stream -f
```

## Outputs

| 名前 | 内容 |
|------|------|
| `instance_ip` | プロビジョニングされた VPS の IPv4 アドレス |
| `instance_id` | Vultr インスタンス ID |

## 死活監視（issue #109）

`youtube-stream.service` は **11 時間配信 → 1 時間休止 → 自動再開** のサイクルで自律的に回るため、素朴な「サービス active か」チェックでは 1 時間休止中（`activating (auto-restart)`）に毎回誤検知が出る（5 分間隔 × 1h = 12 回/サイクル）。本モジュールは以下の 4-way 分類で計画停止と本物の異常を切り分ける:

| systemd 状態 | 分類 | 通知 | 想定シナリオ |
|---|---|---|---|
| `active+running` | `ok` | しない | 配信中 |
| `activating+auto-restart+success` | `idle` | しない | `RuntimeMaxSec=11h` 到達による正常停止後の `RestartSec=1h` 休止（自動再開待ち） |
| `inactive+dead+success` | `manual` | しない | 運用者の `systemctl stop` |
| その他（`failed` / `Result≠success` 等） | `anomaly` | **送る** | `kill -9` / `core-dump` / 設定不備 |

### 通知手段

Discord Webhook URL を `/etc/youtube-stream-healthcheck.env` から読み、`curl -X POST` で送信する。secret は他の secret と同様 `TF_VAR_discord_webhook_url` 環境変数経由で 1Password から注入し、`terraform.tfvars` には書かない。

### 配置されるアセット

| パス | 役割 |
|---|---|
| `/opt/youtube-stream/bin/healthcheck.sh` | systemd 状態を 4 通り分類し、anomaly のみ `notify.sh` を呼ぶ |
| `/opt/youtube-stream/bin/notify.sh` | Discord Webhook へ POST。HTTP 失敗は cron に伝播させない |
| `/etc/cron.d/youtube-stream-healthcheck` | `*/5 * * * * root /opt/youtube-stream/bin/healthcheck.sh` |
| `/etc/logrotate.d/youtube-stream` | `/opt/youtube-stream/logs/*.log` を `daily / rotate 7 / copytruncate` でローテート（ffmpeg を再起動しない） |
| `/etc/youtube-stream-healthcheck.env` | mode 0600 root:root、`DISCORD_WEBHOOK_URL=...` |

### テストシナリオ（VPS 上で確認）

| 操作 | 期待結果 |
|---|---|
| `kill -9 $(pgrep ffmpeg)` | 5 分以内に Discord に anomaly 通知が届く |
| `systemctl stop youtube-stream` | 通知は飛ばない（`manual` 分類） |
| 11h `RuntimeMaxSec` 到達による正常停止 | 通知は飛ばない（`activating+auto-restart+success` = `idle`） |
| 1 時間後の自動再開（`RestartSec=1h` / `auto-restart`） | 通知は飛ばない（休止中は `idle`、再開後は `ok`） |

## トラブルシューティング

### `Error: Output refers to sensitive values`
`triggers.stream_key` を `sha256(var.stream_key)` のまま書くとこのエラーが出る。本モジュールでは `nonsensitive(sha256(...))` でラップ済み（SHA256 は不可逆なので脱 sensitive 安全）。

### `Permission denied (publickey)`（provisioner SSH 失敗）
`ssh_priv_key_path`（デフォルト `~/.ssh/yt_stream_key`）が `ssh_pub_key_path`（デフォルト `~/.ssh/yt_stream_key.pub`）と対になっていない。`ssh-keygen -t ed25519 -f ~/.ssh/yt_stream_key` で再生成し、`terraform apply` を再実行する。

### `terraform apply` 後に配信が始まらない
- `journalctl -u youtube-stream -f` で `ffmpeg` のエラーを確認（stream key 不正・動画ファイル破損など）
- `/etc/youtube-stream.env` の権限が `0600` / root 所有になっているか確認（`stat /etc/youtube-stream.env`）
- `systemctl restart youtube-stream` を手動で実行して再起動
