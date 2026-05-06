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
- `yt-fetch-stream-key --vault=Personal --item=YouTube` でストリームキーを 1Password に保管済み（初回のみ）
- SSH 鍵ペア `~/.ssh/yt_stream_key` / `~/.ssh/yt_stream_key.pub` を生成済み
- 配信対象の MP4 ファイルがローカルにある（絶対パス）

## 使い方

```bash
# 1. tfvars を用意
cd infra/terraform/streaming
cp terraform.tfvars.example terraform.tfvars
# → video_path を実値（絶対パス）に書き換え

# 2. secret を環境変数経由で注入（1Password CLI 推奨）
#    ストリームキーが 1Password に未保管なら事前に `yt-fetch-stream-key --vault=Personal --item=YouTube` を実行
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

## 動画の差し替え手順

`null_resource.deploy` の `triggers.video_hash`（`filemd5(var.video_path)`）が変わると同 resource のみが再実行され、新動画が VPS に転送されて `systemctl restart youtube-stream` まで一気通貫で走る。`vultr_ssh_key` / `vultr_instance` は trigger に含まれないため **VPS は再作成されない**。

```bash
# 1. 新動画の絶対パスを TF_VAR_video_path に export
export TF_VAR_video_path=$(realpath ./new_video.mp4)

# 2. 差分計画を確認（null_resource.deploy のみ replace 予定であること）
terraform -chdir=infra/terraform/streaming plan

# 3. 適用（filemd5 trigger が変わるので null_resource が再実行 → ファイル送信 + systemctl restart）
terraform -chdir=infra/terraform/streaming apply
```

`terraform plan` の出力で `null_resource.deploy` の **replace 1 件のみ** であることを確認してから apply する。`vultr_instance` / `vultr_ssh_key` の change/replace 行が混じる場合は、`terraform.tfvars` の `region` / `plan` / `os_id` を意図せず変更している可能性があるため apply しない。

### 1 コマンドラッパー: `swap_video.sh`

上記 3 ステップを 1 コマンドに畳んだラッパー `scripts/streaming/swap_video.sh` を同梱している。引数の動画パスを `realpath` で絶対化し `TF_VAR_video_path` に export してから `terraform -chdir=infra/terraform/streaming plan` → `apply` を順に実行する。

```bash
# 対話確認あり（既定）
scripts/streaming/swap_video.sh ./new_video.mp4

# 非対話 apply（CI / 確信があるとき）
scripts/streaming/swap_video.sh --auto-approve ./new_video.mp4
```

secret 系（`TF_VAR_stream_key` / `TF_VAR_vultr_api_key`）はラッパーが扱わない方針のため、呼び出し側で事前 export しておくこと（§使い方 の手順 2 と同じ）。`terraform init` も実行しないため、初回のみ手動で `terraform -chdir=infra/terraform/streaming init` を一度走らせる。

### 視聴者ダウンタイムを 0 秒にする運用 tips

§配信サイクル の 11h+1h サイクル中、毎日 11:00–12:00 / 23:00–0:00 の **休止時間** に apply するのが基本。

| 実施タイミング | 視聴者影響 | 反映タイミング |
|---|---|---|
| 休止時間（11:00–12:00 / 23:00–0:00）| 0 秒 | apply 完了直後（休止状態がキャンセルされ即起動。以降のサイクルは apply 時刻基点にシフトする）|
| 配信中 | `systemctl restart` 実行直後の数秒〜数十秒の中断 | apply 完了直後（即時再起動。以降のサイクルは apply 時刻基点にシフトする）|

中断を 0 秒に抑えたければ必ず休止時間まで待ってから apply する。`null_resource.deploy` の最終 provisioner は `systemctl restart youtube-stream` を無条件で実行する（`main.tf` の `provisioner "remote-exec"` 参照）ため、配信中 apply で「次サイクル待ち」を選ぶ手段は提供されていない。

休止時間の正確な開始時刻は VPS 上で以下を確認できる:

```bash
ssh -i ~/.ssh/yt_stream_key root@<instance_ip> systemctl show youtube-stream | grep -E 'ExecMainStartTimestamp|RuntimeMaxUSec'
```

### 同じ動画で再 apply した場合（冪等性）

`filemd5(var.video_path)` が前回と同値なら `triggers` 全体が不変となり、`null_resource.deploy` は no-op。`terraform plan` の差分も 0 件になる（`No changes. Your infrastructure matches the configuration.`）。同じ mp4 で誤って再 apply しても VPS には何も起きないため、運用上は安全に空打ちできる。

### 旧動画の扱い

`provisioner "file"` の `destination` が `/opt/youtube-stream/videos/current.mp4` に固定されており、毎回同一パスへ上書きされる。VPS 上に旧動画は残らないため、明示的な削除手順は不要（単一ファイル方式の自然な振る舞い）。

### トラブルシューティング（差し替え時）

#### `Error: Missing required argument` / `var.video_path is required`
`TF_VAR_video_path` を export せずに `terraform plan` / `apply` を実行している。`export TF_VAR_video_path=$(realpath ./new_video.mp4)` を当該シェルで再実行する。

#### `terraform plan` で `vultr_instance` まで replace される
`terraform.tfvars` の `region` / `plan` / `os_id` を意図せず変更している。差分行の resource 名を確認し、必要なら `terraform.tfvars` を元の値に戻してから再 plan する（差替時はこの 3 値を触らない）。

#### apply 後も旧動画のまま見えている
RTMP セッションの切替遅延（YouTube 側の数秒バッファ）または `ffmpeg` の再起動失敗。`journalctl -u youtube-stream -n 50 -f` で `ffmpeg` 起動時刻と入力ファイルを確認する。新しい時刻で `Stream #0:0` が出ていれば反映済（視聴側のキャッシュ抜けを待つ）。

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
