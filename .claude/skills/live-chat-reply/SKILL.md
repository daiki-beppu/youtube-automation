---
name: live-chat-reply
description: "Use when 配信中の YouTube ライブチャットへ常駐 daemon で自動返信するとき。「ライブチャット返信」「チャット自動返信」「live-chat-reply」で発動。公開済み動画コメントは /comments-reply、VPS・動画配信本体は /streaming を使う"
---

## 前後工程

- `前工程`: `/streaming`
- `後工程`: `なし`

## Hard Gates

以下を上から確認し、1 件でも FAIL なら示した前工程を案内して停止する。後続 Step へ進まない。

- `config/channel/comments.json` が存在し、`comments.live_chat.enabled` が `true`。無ければ `examples/channel_config.example/comments.json` から作成する
- `terraform version` が 1.10 以上で、`infra/terraform/streaming/` と `.claude/skills/streaming/references/deploy_live_chat.sh` が存在する。無ければ automation を更新して `/streaming` を実行する
- `auth/client_secrets.json` と `auth/token.json`、`${CODEX_HOME:-$HOME/.codex}/auth.json` が存在する。認証が必要なら AI が `uv run yt-oauth` / `codex login` を起動して完了まで待ち、人間はブラウザ上のログイン・アカウント選択・同意だけを行う
- 1Password CLI `op` が利用でき、session が有効。未認証なら AI が `op signin` を起動し、人間が 1Password app 上で承認する。JSON 本文をチャット、argv、tfvars、リポジトリへ出さない

## 完了条件

`live-chat-reply.service` と `youtube-stream.service` がともに `active`、VPS 上の認証 3 ファイルが mode `600`、直近ログに `codex_error` / `insert_error` / `forbidden` がない状態で完了。配信が無い場合の「アクティブ配信はありません」は正常とする。

## 外部反映ゲート

配備 script は Terraform の対話 apply 確認で停止させる。AI は plan の add/change/destroy 件数と `null_resource.live_chat_reply` 以外の差分を表示し、「配備する」「キャンセル」の明示 2 択で確認する。配備すると daemon が新着チャットへ外部公開の返信を投稿し、投稿は取り消せない。承認までは `yes` を送らず、`--auto-approve` も付けない。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---:|---|
| `liveBroadcasts.list` | 配信検出時 1。配信なしは `no_broadcast_retry_sec` ごと | 既定 60 秒 |
| `liveChatMessages.list` | YouTube 応答の `pollingIntervalMillis` ごとに 1 | YouTube が返す refresh 間隔 |
| Codex `exec` | 機械フィルタ通過メッセージごとに最大 1 | 新着 text message 数 |
| `liveChatMessages.insert` | Codex が返信対象と判定したとき 1 | 既定 12 回/時、同一 user 連続 2 回、返信 quota 1,000 units/日 |

`daily_quota_budget / reply_quota_cost` は返信 insert だけのローカル上限。list 等を含む Google Cloud project 全体の quota ではない。公式 quota は PT 深夜に reset され、既定設定では 50 units × 最大 20 返信/日で打ち止める。

- 上限 / 承認: `pollingIntervalMillis` を厳守し、外部反映ゲートの明示承認後だけ daemon を起動する。返信は時間・連続 user・PT 日次 quota の 3 上限で停止する。

## Step 1: 設定を確定する

`examples/channel_config.example/comments.json` の `comments.live_chat` を channel へ反映する。初回は次を維持する。

- `process_initial_messages: false`: 起動時 backlog を履歴へ記録するだけで返信しない
- `max_replies_per_hour: 12` / `max_consecutive_per_user: 2`: 過剰返信を抑止
- `daily_quota_budget: 1000` / `reply_quota_cost: 50`: 返信を最大 20 件/日に制限
- `ng_words`, `language`, `channel_persona`: channel に合わせて具体値へ変更
- `model: null`: Codex の既定 model。固定が必要なときだけ model ID を設定

`max_length`、上限、retry 秒、timeout はすべて 0 より大きくする。設定 load が成功すれば Step 1 完了。

## Step 2: 人間の認証を AI が起動する

`auth/token.json` が無い、または `youtube.force-ssl` scope が不足・失効している場合、AI が channel root で `uv run yt-oauth` を継続 session として起動し、stdout の同意 URL を人間へ提示する。同じ process が exit 0 になるまで待つ。

Codex auth が無ければ AI が `codex login` を起動し、表示された認証 URL / code を人間へ提示して同じ process の完了を待つ。人間へ shell command、token、client secret の貼り付けを依頼しない。

## Step 3: 1Password へ安全に保存する

AI が次を実行する。`write_op_secret` は JSON template を stdin で `op` へ渡すため、secret は argv に載らない。

```bash
CHANNEL_DIR=/absolute/path/to/channel uv run python - <<'PY'
import os
from pathlib import Path
from youtube_automation.infrastructure.secrets import write_op_secret

channel = Path(os.environ["CHANNEL_DIR"])
codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
for field, path in {
    "token_json": channel / "auth/token.json",
    "client_secrets_json": channel / "auth/client_secrets.json",
    "codex_auth_json": codex_home / "auth.json",
}.items():
    write_op_secret("Personal", "YouTube_Live_Chat", field, path.read_text())
PY
```

3 field を `op read` し、値を表示せず JSON parse が成功すれば Step 3 完了。参照は次で固定する。

```bash
export OP_LIVE_CHAT_TOKEN_REF='op://Personal/YouTube_Live_Chat/token_json'
export OP_LIVE_CHAT_CLIENT_SECRETS_REF='op://Personal/YouTube_Live_Chat/client_secrets_json'
export OP_CODEX_AUTH_REF='op://Personal/YouTube_Live_Chat/codex_auth_json'
```

## Step 4: VPS へ配備する

`/streaming` の通常 secret と 3 参照を環境へ設定後、AI が PTY / background session で次を起動する。

```bash
"$(git rev-parse --show-toplevel)/.claude/skills/streaming/references/deploy_live_chat.sh" /absolute/path/to/channel
```

Terraform の apply 確認 prompt で外部反映ゲートを実施する。承認後だけ `yes`、キャンセルなら `no` を送る。

## Step 5: 完了を検証する

```bash
INSTANCE_IP=$(terraform -chdir=infra/terraform/streaming output -raw instance_ip)
ssh root@$INSTANCE_IP 'systemctl is-active youtube-stream live-chat-reply'
ssh root@$INSTANCE_IP 'stat -c "%a %U %n" /var/lib/live-chat-reply/channel/auth/{token.json,client_secrets.json} /var/lib/live-chat-reply/codex/auth.json'
ssh root@$INSTANCE_IP 'journalctl -u live-chat-reply -n 100 --no-pager'
```

完了条件を全件確認する。返信履歴は VPS の `/var/lib/live-chat-reply/channel/live_chat_reply_history.json` に残り、同じ message ID を再処理しない。

## 設定リファレンス

| key | 意味 |
|---|---|
| `enabled` | daemon opt-in。Terraform の `enable_live_chat_reply` と両方 true が必要 |
| `language` / `ng_words` / `max_length` | 入出力の言語・禁止語・返信文字数フィルタ |
| `max_replies_per_hour` / `max_consecutive_per_user` | 時間・連続 user 上限 |
| `daily_quota_budget` / `reply_quota_cost` | PT 日次の返信 quota 上限と 1 投稿の見積 cost |
| `no_broadcast_retry_sec` | active broadcast が無いときの再検出間隔 |
| `history_file` | channel root 相対の重複防止履歴 |
| `channel_persona` / `model` / `codex_timeout_sec` | Codex 判定・生成設定 |
| `process_initial_messages` | `false` なら起動時 backlog を返信せず処理済みにする |

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `op read` / signin 失敗 | AI が `op signin` を起動し、人間が 1Password app 上で承認後に Step 3〜4 を再実行 |
| `forbidden` / token refresh 失敗 | AI が `uv run yt-oauth` を起動し、人間のブラウザ同意後に Step 3〜4 を再実行 |
| `codex_error` | `codex login` を AI が起動して認証を更新し、Step 3〜4 を再実行。該当 message は skip され配信は継続 |
| `liveChatDisabled` / `liveChatEnded` | YouTube Studio の配信設定を確認。終了済みなら次の active broadcast を自動待機 |
| `rateLimitExceeded` | `pollingIntervalMillis` より早い独自 poll を追加していないか確認。投稿側は時間上限を下げる |
| service が restart loop | `journalctl -u live-chat-reply -n 100` を確認。`youtube-stream` は独立して継続する |

公式仕様: [liveChatMessages.list](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list)、[liveChatMessages.insert](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/insert)、[quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost)、[1Password JSON template](https://developer.1password.com/docs/cli/create-item/)。VPS 配備詳細の Single Source of Truth は `infra/terraform/streaming/README.md`。
