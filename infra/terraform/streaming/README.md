# infra/terraform/streaming

Vultr VPS をプロビジョニングし、ローカル MP4 を YouTube Live に常時配信する Terraform モジュール。`terraform apply` 一発で「VPS 作成 → cloud-init で systemd unit 配置 → 動画アップロード → `.env` 配置 → 配信開始」までを完結する。

配信は systemd の `RuntimeMaxSec=11h` + `RestartSec=1h` により **11 時間配信 → 1 時間休止 → 自動再開** のサイクルで自律的に回る（YouTube が 12 時間以上のライブをアーカイブしない仕様への対応）。

## 管理するリソース

- `vultr_ssh_key` × 1（VPS 作成時に登録する SSH 公開鍵）
- `vultr_instance` × 1（Ubuntu 24.04 LTS / vc2-1c-2gb / 東京リージョン）
- `null_resource.deploy` × 1（動画アップロード + `EnvironmentFile` 配置 + systemd 起動）

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

## トラブルシューティング

### `Error: Output refers to sensitive values`
`triggers.stream_key` を `sha256(var.stream_key)` のまま書くとこのエラーが出る。本モジュールでは `nonsensitive(sha256(...))` でラップ済み（SHA256 は不可逆なので脱 sensitive 安全）。

### `Permission denied (publickey)`（provisioner SSH 失敗）
`ssh_priv_key_path`（デフォルト `~/.ssh/yt_stream_key`）が `ssh_pub_key_path`（デフォルト `~/.ssh/yt_stream_key.pub`）と対になっていない。`ssh-keygen -t ed25519 -f ~/.ssh/yt_stream_key` で再生成し、`terraform apply` を再実行する。

### `terraform apply` 後に配信が始まらない
- `journalctl -u youtube-stream -f` で `ffmpeg` のエラーを確認（stream key 不正・動画ファイル破損など）
- `/etc/youtube-stream.env` の権限が `0600` / root 所有になっているか確認（`stat /etc/youtube-stream.env`）
- `systemctl restart youtube-stream` を手動で実行して再起動

## 帯域モニタリング

Vultr `vc2-1c-2gb` プランの月間帯域上限 **2 TB** に対し、11h+1h 断続配信は理論 1.16 TB（58%）。超過防止のため `yt-stream-bandwidth` CLI で月次レポートと 80% 到達アラートを自動化する（Issue #110）。

### 必要なシークレット（1Password CLI 経由）

| 名前 | 1Password 参照 | 用途 |
|------|----------------|------|
| `VULTR_API_KEY` | `op://Personal/Vultr/api_key` | Vultr `/v2/instances/{id}/bandwidth` 認証 |
| `STREAM_WEBHOOK_URL` | `op://Personal/Stream_Notification_Webhook/url` | Discord-compat webhook (`{"content": ...}`) 投稿先。#109 と共有経路 |

`utils/secrets.py` 経由で env → `op read` の順で解決され、いずれの経路でも取得できなければ `ConfigError` で停止する（webhook 投稿モード `--report` / `--check-threshold` は両 secret 必須）。

### CLI モード

```bash
# 現状サマリ (今月の使用量を stdout)
uv run yt-stream-bandwidth --terraform-dir infra/terraform/streaming

# 月次レポート (前月既定 / --month YYYY-MM 指定)
uv run yt-stream-bandwidth --report --terraform-dir infra/terraform/streaming

# 80% 閾値アラート (未超は静黙)
uv run yt-stream-bandwidth --check-threshold --terraform-dir infra/terraform/streaming

# 配信元 MP4 のビットレートを ffprobe で実測 (想定 4 Mbps と比較)
uv run yt-stream-bandwidth --probe-bitrate /path/to/stream.mp4
```

`--instance-id <ID>` を渡せば terraform output を経由せず直接指定できる（CI / ローカル検証用）。

### cron サンプル

```cron
# 月初 0:00 に前月分の月次レポートを Discord に投稿
0 0 1 * * cd /path/to/repo && uv run yt-stream-bandwidth --report --terraform-dir infra/terraform/streaming

# 毎日 6:00 に当月の 80% 閾値超過をチェック
0 6 * * * cd /path/to/repo && uv run yt-stream-bandwidth --check-threshold --terraform-dir infra/terraform/streaming
```

### 超過時の対応方針

- 超過料金: $0.01/GB
- **対策 A**: ビットレートを 4 Mbps → 3 Mbps に下げる（`youtube-stream.service.tftpl` の `ExecStart` を再エンコード化）
- **対策 B**: `vc2-2c-4gb` ($20/月、3 TB) にプラン変更（Terraform `var.plan` 切替で再 `apply`）
