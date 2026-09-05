---
name: streaming
purpose: 進める
description: "Use when ライブ配信用 Vultr VPS・動画配信本体を Terraform で構築・運用・トラブルシュートするとき。「ライブ配信」「24/7 配信」「配信止まった」で発動。ライブチャット自動返信は /reply の live mode を使う"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `infra/terraform/streaming/terraform.tfvars`, `/var/lib/youtube-broadcast-recovery/last-result.json`
- `読み込む`: `infra/terraform/streaming/.terraform/terraform.tfstate`, `infra/terraform/streaming/README.md`

## Overview

`infra/terraform/streaming/` の Terraform モジュールを使った YouTube ライブ配信 VPS の運用ガイド。`terraform apply` 一発で **VPS 作成 → cloud-init → 動画アップロード → 配信開始** が完結する。デフォルトは `stream_hours=0` / `break_hours=0` の **24/7 連続配信**。YouTube アーカイブ生成を優先する場合は `stream_hours=11` / `break_hours=1` で従来の **11h 配信 + 1h 休止** に切り替える。

**詳細仕様の Single Source of Truth は `infra/terraform/streaming/README.md`。** 本スキルはオペレーション索引として機能し、操作の入口を提供する。判断に迷ったら必ず README を参照すること。

## 前提

最初に [Terraform 資産と実行場所の確定](references/upstream-checkout.md) を実行し、上流 `AUTOMATION_ROOT`・対象 `CHANNEL_DIR`・`TF_DIR` を確定する。以下の相対パスとコマンドは上流 root 基準。動画など下流の入力は絶対パスで渡す。

以下を確認し、満たさなければ整備手順（各項目に記載、詳細は README §前提）を案内してから先へ進む:

- `terraform` 1.15.x / `python3` / `uv` / 1Password CLI (`op`)
- SSH 鍵 `~/.ssh/yt_stream_key{,.pub}`（無ければ `ssh-keygen -t ed25519 -f ~/.ssh/yt_stream_key`）
- ssh-agent に秘密鍵を登録済み（`ssh-add ~/.ssh/yt_stream_key`）。`null_resource.deploy.connection` は `agent = true` で ssh-agent 経由に接続するため、未登録だと apply 時に `Permission denied (publickey)` で失敗する。`ssh-add -l` で登録済み鍵を確認できる。**OS 再起動・再ログイン時に agent は空に戻る（毎セッション再登録が必要）**。**`ssh -i ~/.ssh/yt_stream_key` 経由の手動 SSH は agent 状態と独立で検証手段にならない**（詳細は README §前提）
- 1Password に以下が登録済み:
  - `op://Personal/Vultr/api_key`
  - `op://Personal/YouTube/stream_key`（未登録なら `yt-fetch-stream-key --vault=Personal --item=YouTube` で自動取得）
  - `op://Personal/YouTube_Stream_Discord_Webhook/url`（死活監視通知）
- operator のグローバル IP を `/32` CIDR で `allowed_ssh_cidr` に渡せること（Vultr ファイアウォールで SSH 22/tcp を operator IP のみに制限する。`curl -s ifconfig.me` で取得）

## Quick Reference

| 操作 | コマンド |
|------|----------|
| 初回構築 | §1 |
| workspace 一覧 | `terraform -chdir=infra/terraform/streaming workspace list` |
| 現在の workspace | `terraform -chdir=infra/terraform/streaming workspace show` |
| workspace 作成 | `terraform -chdir=infra/terraform/streaming workspace new <workspace>` |
| workspace 切替 | `terraform -chdir=infra/terraform/streaming workspace select <workspace>` |
| チャンネル選択・state 確認 | `$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/select_channel.sh <channel-slug> show` |
| チャンネル別 plan / apply | 同上 + `plan --video ./stream.mp4` / `apply --video ./stream.mp4` |
| 選択 workspace の GCS state | `workspace=$(terraform -chdir=infra/terraform/streaming workspace show); bucket=$(jq -r '.backend.config.bucket' infra/terraform/streaming/.terraform/terraform.tfstate); gcloud storage ls "gs://${bucket}/streaming/${workspace}.tfstate"` |
| VPS / state 突合診断 | `VULTR_API_KEY="$(op read 'op://Personal/Vultr/api_key')" uv run yt-doctor --json` (`streaming_vps_state` を確認) |
| ライブチャット自動返信 | `/reply --live` |
| 動画差し替え | `$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh ./new_video.mp4` |
| 帯域チェック | `uv run yt-stream-bandwidth --check-threshold --terraform-dir infra/terraform/streaming` |
| 月間帯域見積もり用の MP4 実測 | `uv run yt-stream-bandwidth --probe-bitrate ./stream.mp4` |
| アーカイブ件数確認（11h+1h 運用時） | `uv run yt-stream-archive-check --expected 2` |
| ingest 稼働中に消えた配信枠を復旧 | `uv run yt-stream-broadcast-recover --stream-id <stream-id> --title '<stable-title>' --dry-run` で確認後、`--dry-run` を外す |
| 24/7 の配信枠自動復旧を配備 | `OP_BROADCAST_RECOVERY_TOKEN_REF=... OP_BROADCAST_RECOVERY_CLIENT_SECRETS_REF=... .claude/skills/streaming/references/deploy_broadcast_recovery.sh` |
| サービス状態 | `ssh -i ~/.ssh/yt_stream_key root@$(terraform -chdir=infra/terraform/streaming output -raw instance_ip) systemctl status youtube-stream` |
| ログ追跡 | 同上 + `journalctl -u youtube-stream -f` |
| 破棄 | §5 |

workspace は state だけを切り替える。既存 workspace の操作は `select_channel.sh` で切替・一致検証・state 表示と `TF_VAR_video_path` / `TF_VAR_stream_key` / `TF_VAR_discord_webhook_url` / `TF_VAR_channel_slug` の再注入を一体化する。workspace の新規作成だけは明示操作とし、apply 前の照合まで含む詳細手順は `$TF_DIR/README.md` の「チャンネル別 Terraform workspace 運用」 を正本とする。

| CLI / スクリプト | 用途 |
|---|---|
| `yt-fetch-stream-key` | YouTube Data API 経由でストリームキーを取得し 1Password に保存 |
| `yt-stream-bandwidth` | Vultr 帯域 API 月次レポート + 80% 閾値アラート |
| `yt-stream-archive-check --expected 2` | `stream_hours=11` / `break_hours=1` 運用で 1 日 2 本のアーカイブが上がっているか確認 |
| `yt-stream-broadcast-recover` | active 枠があれば no-op。ingest inactive なら systemd 側の復旧を待つ。active ingest かつ active 枠なしの場合だけ upcoming 枠を再利用、または作成して bind → live 遷移 |
| `$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh` | `terraform plan` → `apply` の 1 コマンドラッパー |
| `$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/select_channel.sh` | workspace とチャンネル資格情報を揃えて `show` / `plan` / `apply` / `destroy` |

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| Vultr VPS（terraform apply） | API call 数ではなく VPS 存在中は時間課金が継続 | 稼働時間（terraform destroy まで） |
| liveStreams.list（1 unit、yt-fetch-stream-key） | 1 | — |
| search.list + videos.list（≈ 101 units、yt-stream-archive-check） | 各 1 | — |
| search.list（100 units / ページ、yt-stream-bandwidth --report のみ） | ページ数分 | アーカイブ本数（default 実行は Vultr API / ローカルのみで無料） |
| liveBroadcasts.list + liveStreams.list（yt-stream-broadcast-recover） | 1〜3 | active 枠ありは 1、ingest inactive は 2、復旧判定は 3 |
| liveBroadcasts.insert + bind + transition（yt-stream-broadcast-recover） | 0〜3 | `--dry-run` / no-op は 0、upcoming の再利用状況により 1〜3 |

- 上限 / 承認: `terraform plan` で apply 前に差分確認し、§5 の `terraform destroy` で課金を停止する。yt-stream-archive-check は read のみで書き込みなし。yt-stream-broadcast-recover は必ず最初に `--dry-run` で予定 action を確認し、同じ `--title` を再試行時も使う。

## §1 初回構築

```bash
cd infra/terraform/streaming
cp terraform.tfvars.example terraform.tfvars
# → video_path を絶対パスに書き換え
# → allowed_ssh_cidr を operator の IP/32 に書き換え（例: ["203.0.113.5/32"]、`curl -s ifconfig.me` で取得）
# → 複数チャンネル運用では channel_slug を設定（例: `005ch-abyss`）

export TF_VAR_vultr_api_key=$(op read 'op://Personal/Vultr/api_key')
export TF_VAR_stream_key=$(op read 'op://Personal/YouTube/stream_key')
export TF_VAR_discord_webhook_url=$(op read 'op://Personal/YouTube_Stream_Discord_Webhook/url')

terraform init
terraform plan   # tls_private_key + vultr_ssh_key + vultr_firewall_group + vultr_firewall_rule×N + vultr_instance + null_resource.deploy（全リソースは README 参照）
terraform apply
```

apply 完了で 1 本目の配信が即開始。`terraform output -raw instance_ip` で IP を確認。

`channel_slug` を指定すると Vultr の instance `label` / `tags` は `youtube-stream-<channel_slug>` になり、複数チャンネルの VPS を一覧で識別できる。未指定時は従来の `youtube-stream` を維持する。Vultr provider では hostname 変更が instance の replace を誘発するため、`hostname` は `youtube-stream` のまま変更しない。

`terraform plan` / `apply` は、ローカルに `ffprobe` があれば配信元 MP4 をプリフライト検証する。`run-ffmpeg.sh` は `-c:v copy` で映像をストリームコピーするため、ソース動画のキーフレーム間隔・ビットレート・H.264 profile が YouTube Live 品質をそのまま決める。キーフレーム最大間隔 > 4 秒、または 1080p で 4,500 Kbps 未満 / 720p で 2,500 Kbps 未満なら plan 時点で止まる。H.264 High profile 以外は warning。`ffprobe` が無い場合は soft skip される。

1080p30 の推奨再エンコード例:

```bash
ffmpeg -i input.mp4 \
  -c:v libx264 -profile:v high -level:v 4.1 \
  -b:v 4500k -maxrate 4500k -bufsize 9000k \
  -g 60 -keyint_min 60 \
  -preset slow -pix_fmt yuv420p -an \
  output.mp4
```

24/7 配信では 4,500 Kbps + 音声 200 Kbps で月約 1.52 TB。`vc2-1c-2gb` の 2 TB/月に収めるため、6,800 Kbps 級へ上げる場合はプランアップか運用時間短縮を先に検討する。

`yt-stream-bandwidth --probe-bitrate` は container 全体の平均 bitrate を見る月間帯域見積もり用。配信元 MP4 の preflight 合否は `terraform plan` / `apply` の stream-level 検証を正とする。

配信サイクルを変える場合は `terraform.tfvars` で `stream_hours` / `break_hours` を指定する。0 は無制限を意味し、`stream_hours=0` では `RuntimeMaxSec` を出力しない。`break_hours=0` では `RestartSec=2s`（`crash_restart_seconds` で 1〜300 秒に上書き可）を出力する。永続的な起動失敗は 60 秒間に 10 回で停止し、healthcheck の anomaly 通知後に手動で原因を直して再起動する。

## §2 動画差し替え

`null_resource.deploy.triggers.video_hash` (= `filemd5(var.video_path)`) が変わると `null_resource` のみが再実行され、新動画が VPS へ転送 + `systemctl restart` まで一気通貫で走る（VPS は再作成されない、冪等）。

```bash
# secret は §1 と同じく事前 export しておくこと
"$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh" ./new_video.mp4              # 対話確認あり
"$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh" --auto-approve ./new_video.mp4  # 非対話
```

`stream_hours=11` / `break_hours=1` 運用では休止時間に実施すれば視聴者ダウンタイムは 0 秒。24/7 連続配信中の apply は数秒〜数十秒の中断あり。

`terraform plan` で `null_resource.deploy` の **replace 1 件のみ** が出ることを確認してから apply。`vultr_instance` まで replace が混じる場合は `terraform.tfvars` の `region` / `plan` / `os_id` を意図せず変更している。

## §3 監視運用

`terraform apply` 時点で以下が VPS に自動配置される（手動操作不要）:

- `/opt/youtube-stream/bin/healthcheck.sh` + `/etc/cron.d/youtube-stream-healthcheck`（5 分間隔）
- `/etc/logrotate.d/youtube-stream`（daily / rotate 7 / copytruncate）
- `/etc/youtube-stream-healthcheck.env`（mode 0600、Discord webhook URL）

`enable_broadcast_recovery=true` かつ `stream_hours=0` では、専用 user と 0600 OAuth files、`youtube-broadcast-recovery.service/.timer` も配備される。既定 120 秒ごとに ffmpeg service と ingest を確認し、active broadcast が消えたときだけ upcoming 再利用または create → bind → live を行う。`recovered` は既存 notify 経路へ送り、結果は常に `journalctl -t youtube-broadcast-recovery` に残る。導入、disable cleanup、資格情報更新、明示承認が必要な手動終了テストは `$TF_DIR/README.md` の「24/7 broadcast 自動復旧 timer」 を正本とする。

healthcheck は systemd 状態を 4 通りに分類し、**真の異常のみ通知**:

| 状態 | 分類 | 通知 |
|---|---|---|
| `active+running` | ok | しない |
| `activating+auto-restart+success` + 有限 `RuntimeMaxUSec` | idle（11h+1h の計画休止） | しない |
| `activating+auto-restart+success` + `RuntimeMaxUSec=infinity` / `0` | anomaly（24/7 に計画休止はない） | **送る** |
| `inactive+dead+success` | manual（運用者の `systemctl stop`）| しない |
| `failed` / `Result≠success` | anomaly | **送る** |

さらに `NRestarts` を `/var/lib/youtube-stream/last_n_restarts` と比較する。増加を観測した cron では restart 通知を 1 通だけ送り、同じ観測の状態遷移通知とは重複させない。baseline 不在・非数値への破損・counter 減少（service 再作成など）は異常扱いせず、現在値へ無音で再基準化する。

24/7 の実機 SIGKILL 確認は配信を切断する破壊的操作であり、VPS への接続と実行には利用者の明示的承認が必要。本 issue の文書更新では実行していない。承認後は healthcheck を一度実行して `NRestarts` baseline を作り、対象を限定した SIGKILL 後の次回 cron で `restart detected` が 1 通だけ届くことを確認する。11h+1h は有限 `RuntimeMaxUSec` の計画休止をまたいで通知が 0 通であることを確認する。

帯域モニタリング cron 例（ローカル or CI）:

```cron
0 0 1 * * cd <repo> && uv run yt-stream-bandwidth --report --terraform-dir infra/terraform/streaming
0 6 * * * cd <repo> && uv run yt-stream-bandwidth --check-threshold --terraform-dir infra/terraform/streaming
```

24/7 連続配信は 11h+1h のアーカイブ生成モードより帯域使用量が増える。超過時の対策は README §帯域モニタリング 参照。月次レポートのアーカイブ件数・稼働率は 11h+1h 運用時だけ判定材料にする。

## §4 トラブルシュート

| 症状 | 一次調査 |
|------|----------|
| 配信が始まらない | `journalctl -u youtube-stream -f`（ffmpeg のエラー / stream key 不正 / 動画破損）|
| `Permission denied (publickey)` | ssh-agent に鍵が登録されていない or 鍵ペアが食い違っている。`ssh-add -l` で確認し、未登録なら `ssh-add ~/.ssh/yt_stream_key`。鍵ペアが対になっていなければ `ssh-keygen -t ed25519 -f ~/.ssh/yt_stream_key` で再生成して `ssh-add` し直す。**`ssh -i` 経由の手動 SSH が通っても判定材料にならない（provisioner は agent 経由）** |
| `Error: Output refers to sensitive values` | `triggers` を `nonsensitive(sha256(...))` でラップ済みのはず。`main.tf` を確認 |
| Discord 通知が来ない | `/etc/youtube-stream-healthcheck.env` の `DISCORD_WEBHOOK_URL` を確認 / 実行ログは `journalctl -t youtube-stream-healthcheck --since '15 min ago'` で参照 / 構文だけ確かめたい場合は `bash -n /opt/youtube-stream/bin/healthcheck.sh`（実行されない）。**`bash -x` は trace 出力に `DISCORD_WEBHOOK_URL` が展開されるため使わない。誤って実行した場合も出力をどこにも貼り付けない**（`notify.sh` が `/etc/youtube-stream-healthcheck.env` を `source` してそのまま `curl` するため） |
| broadcast 復旧 timer が動かない | `systemctl status youtube-broadcast-recovery.timer`、`journalctl -t youtube-broadcast-recovery --since '15 min ago'`、`/var/lib/youtube-broadcast-recovery/last-result.json` を確認。`stream_hours>0` と `youtube-stream.service` inactive は安全な disable/no-op |
| 帯域 80% 超アラート | README §超過時の対応方針（4 Mbps → 3 Mbps 化 / プランアップ）|
| 11h+1h 運用で 1 日のアーカイブが 2 本未満 | `RuntimeMaxSec` 到達前に `failed` した可能性。`journalctl -u youtube-stream --since today` |
| `Invalid value for variable` (`allowed_ssh_cidr`) で plan が落ちる | `terraform.tfvars` の `allowed_ssh_cidr` が空 `[]`。`curl -s ifconfig.me` で取得した IP を `/32` 付きで 1 件以上記入 |

切り分けの基本動作:

```bash
INSTANCE_IP=$(terraform -chdir=infra/terraform/streaming output -raw instance_ip)
ssh -i ~/.ssh/yt_stream_key root@$INSTANCE_IP "systemctl show youtube-stream | grep -E 'ActiveState|SubState|Result|RuntimeMaxUSec|RestartUSec|NRestarts'"
```

## 障害時ガイダンス

外部サービス起因の障害は本表で扱う。配信プロセス・SSH・通知の切り分けは §4 トラブルシュートを参照する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 1Password CLI 未認証 | `op read` が認証エラー / `TF_VAR_vultr_api_key` が空 | `op signin` でセッションを再確立してから再実行 |
| Vultr API 障害 / rate | `terraform apply` が Vultr API エラー / HTTP 429・503 | [Vultr ステータス](https://status.vultr.com) を確認し、時間を置いて再 apply（`terraform plan` で差分のみ適用） |
| terraform apply 失敗 | provider エラーで apply 中断 | エラー行を確認。state は保持されるため原因解消後に再 apply。配信プロセス・SSH・通知の切り分けは §4 トラブルシュートを参照 |

## §5 片付け（破棄）

```bash
export TF_VAR_vultr_api_key=$(op read 'op://Personal/Vultr/api_key')
terraform -chdir=infra/terraform/streaming destroy
```

VPS が消えるまで課金が続くため、**長期休止する場合は必ず destroy する**。再構築は §1 と同じ手順で 5〜10 分で完了する（state ファイルが残っていれば差分のみ）。

## Common Mistakes

- **`terraform.tfvars` に secret を書く** → 必ず `TF_VAR_*` 環境変数経由。`*.tfvars` / `*.tfstate*` は gitignore 済みだが、コミット時に二重チェック
- **配信中に動画差し替え** → 数秒の中断あり。`stream_hours > 0` の計画休止がある運用で視聴者ダウンタイム 0 を狙うなら休止時間まで待つ
- **`activating (auto-restart)` を常に計画休止とみなす** → 有限 `RuntimeMaxUSec` の 11h+1h 運用だけが idle。`infinity` / `0` の 24/7 運用では anomaly
- **同じ動画で再 apply して心配する** → `filemd5` 不変なら no-op で安全。空打ち可能
- **24/7 運用で `yt-stream-archive-check` を使う** → 日次アーカイブ不足判定の対象外。`stream_hours=11` / `break_hours=1` 運用で `--expected 2` を付けて使う
- **`yt-stream-archive-check --expected 2` で 0 件** → YouTube Data API のキャッシュ遅延。`publishedAt` が UTC 基準であることに注意
