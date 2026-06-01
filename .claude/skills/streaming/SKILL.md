---
name: streaming
description: "Use when YouTube ライブ配信用の Vultr VPS を Terraform で操作したいとき。「ライブ配信」「24/7 配信」「streaming」「YouTube ライブ」「VPS 配信」「動画差し替え」「terraform streaming」「配信止まった」「死活監視」「帯域チェック」「アーカイブ確認」「terraform destroy」など、`infra/terraform/streaming/` モジュールに関わる初回構築・運用・トラブルシュート全般で使用すること"
---

## Overview

`infra/terraform/streaming/` の Terraform モジュールを使った YouTube ライブ配信 VPS の運用ガイド。`terraform apply` 一発で **VPS 作成 → cloud-init → 動画アップロード → 配信開始** が完結する。systemd の `RuntimeMaxSec=11h` + `RestartSec=1h` で **11h 配信 + 1h 休止** のサイクルが自律的に回り、毎日 2 本のアーカイブが残る（YouTube の 12 時間制限回避）。

**詳細仕様の Single Source of Truth は `infra/terraform/streaming/README.md`。** 本スキルはオペレーション索引として機能し、操作の入口を提供する。判断に迷ったら必ず README を参照すること。

## 前提

- `terraform` >= 1.5 / `uv` / 1Password CLI (`op`)
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
| 動画差し替え | `$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh ./new_video.mp4` |
| 帯域チェック | `uv run yt-stream-bandwidth --check-threshold --terraform-dir infra/terraform/streaming` |
| アーカイブ件数確認 | `uv run yt-stream-archive-check` |
| サービス状態 | `ssh -i ~/.ssh/yt_stream_key root@$(terraform -chdir=infra/terraform/streaming output -raw instance_ip) systemctl status youtube-stream` |
| ログ追跡 | 同上 + `journalctl -u youtube-stream -f` |
| 破棄 | §5 |

| CLI / スクリプト | 用途 |
|---|---|
| `yt-fetch-stream-key` | YouTube Data API 経由でストリームキーを取得し 1Password に保存 |
| `yt-stream-bandwidth` | Vultr 帯域 API 月次レポート + 80% 閾値アラート |
| `yt-stream-archive-check` | 1 日 2 本のアーカイブが上がっているか確認 |
| `$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh` | `terraform plan` → `apply` の 1 コマンドラッパー |

## §1 初回構築

```bash
cd infra/terraform/streaming
cp terraform.tfvars.example terraform.tfvars
# → video_path を絶対パスに書き換え
# → allowed_ssh_cidr を operator の IP/32 に書き換え（例: ["203.0.113.5/32"]、`curl -s ifconfig.me` で取得）

export TF_VAR_vultr_api_key=$(op read 'op://Personal/Vultr/api_key')
export TF_VAR_stream_key=$(op read 'op://Personal/YouTube/stream_key')
export TF_VAR_discord_webhook_url=$(op read 'op://Personal/YouTube_Stream_Discord_Webhook/url')

terraform init
terraform plan   # vultr_ssh_key + vultr_instance + null_resource.deploy = 3 add
terraform apply
```

apply 完了で 1 本目の配信が即開始。`terraform output -raw instance_ip` で IP を確認。

## §2 動画差し替え

`null_resource.deploy.triggers.video_hash` (= `filemd5(var.video_path)`) が変わると `null_resource` のみが再実行され、新動画が VPS へ転送 + `systemctl restart` まで一気通貫で走る（VPS は再作成されない、冪等）。

```bash
# secret は §1 と同じく事前 export しておくこと
"$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh" ./new_video.mp4              # 対話確認あり
"$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/swap_video.sh" --auto-approve ./new_video.mp4  # 非対話
```

**休止時間（毎日 11:00–12:00 / 23:00–0:00）に実施すれば視聴者ダウンタイムは 0 秒。** 配信中の apply は数秒〜数十秒の中断あり。

`terraform plan` で `null_resource.deploy` の **replace 1 件のみ** が出ることを確認してから apply。`vultr_instance` まで replace が混じる場合は `terraform.tfvars` の `region` / `plan` / `os_id` を意図せず変更している。

## §3 監視運用

`terraform apply` 時点で以下が VPS に自動配置される（手動操作不要）:

- `/opt/youtube-stream/bin/healthcheck.sh` + `/etc/cron.d/youtube-stream-healthcheck`（5 分間隔）
- `/etc/logrotate.d/youtube-stream`（daily / rotate 7 / copytruncate）
- `/etc/youtube-stream-healthcheck.env`（mode 0600、Discord webhook URL）

healthcheck は systemd 状態を 4 通りに分類し、**真の異常のみ通知**:

| 状態 | 分類 | 通知 |
|---|---|---|
| `active+running` | ok | しない |
| `activating+auto-restart+success` | idle（11h 完走後の 1h 休止） | しない |
| `inactive+dead+success` | manual（運用者の `systemctl stop`）| しない |
| `failed` / `Result≠success` | anomaly | **送る** |

帯域モニタリング cron 例（ローカル or CI）:

```cron
0 0 1 * * cd <repo> && uv run yt-stream-bandwidth --report --terraform-dir infra/terraform/streaming
0 6 * * * cd <repo> && uv run yt-stream-bandwidth --check-threshold --terraform-dir infra/terraform/streaming
```

11h+1h 断続で月間 1.16 TB（2 TB プランの 58%）。超過時の対策は README §帯域モニタリング 参照。

## §4 トラブルシュート

| 症状 | 一次調査 |
|------|----------|
| 配信が始まらない | `journalctl -u youtube-stream -f`（ffmpeg のエラー / stream key 不正 / 動画破損）|
| `Permission denied (publickey)` | ssh-agent に鍵が登録されていない or 鍵ペアが食い違っている。`ssh-add -l` で確認し、未登録なら `ssh-add ~/.ssh/yt_stream_key`。鍵ペアが対になっていなければ `ssh-keygen -t ed25519 -f ~/.ssh/yt_stream_key` で再生成して `ssh-add` し直す。**`ssh -i` 経由の手動 SSH が通っても判定材料にならない（provisioner は agent 経由）** |
| `Error: Output refers to sensitive values` | `triggers` を `nonsensitive(sha256(...))` でラップ済みのはず。`main.tf` を確認 |
| Discord 通知が来ない | `/etc/youtube-stream-healthcheck.env` の `DISCORD_WEBHOOK_URL` を確認 / 実行ログは `journalctl -t youtube-stream-healthcheck --since '15 min ago'` で参照 / 構文だけ確かめたい場合は `bash -n /opt/youtube-stream/bin/healthcheck.sh`（実行されない）。**`bash -x` は trace 出力に `DISCORD_WEBHOOK_URL` が展開されるため使わない。誤って実行した場合も出力をどこにも貼り付けない**（`notify.sh` が `/etc/youtube-stream-healthcheck.env` を `source` してそのまま `curl` するため） |
| 帯域 80% 超アラート | README §超過時の対応方針（4 Mbps → 3 Mbps 化 / プランアップ）|
| 1 日のアーカイブが 2 本未満 | `RuntimeMaxSec` 到達前に `failed` した可能性。`journalctl -u youtube-stream --since today` |
| `Invalid value for variable` (`allowed_ssh_cidr`) で plan が落ちる | `terraform.tfvars` の `allowed_ssh_cidr` が空 `[]`。`curl -s ifconfig.me` で取得した IP を `/32` 付きで 1 件以上記入 |

切り分けの基本動作:

```bash
INSTANCE_IP=$(terraform -chdir=infra/terraform/streaming output -raw instance_ip)
ssh -i ~/.ssh/yt_stream_key root@$INSTANCE_IP "systemctl show youtube-stream | grep -E 'ActiveState|SubState|Result|RuntimeMaxUSec|RestartUSec'"
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
- **配信中に動画差し替え** → 数秒の中断あり。視聴者ダウンタイム 0 を狙うなら休止時間まで待つ
- **`activating (auto-restart)` を異常と誤認** → これは 11h+1h サイクルの正常な休止状態。healthcheck は idle 分類で通知しない
- **同じ動画で再 apply して心配する** → `filemd5` 不変なら no-op で安全。空打ち可能
- **`yt-stream-archive-check` で 0 件** → YouTube Data API のキャッシュ遅延。`publishedAt` が UTC 基準であることに注意
