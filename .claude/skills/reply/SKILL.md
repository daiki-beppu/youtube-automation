---
name: reply
purpose: 公開する
description: "Use when 公開済み YouTube 動画のコメントへ返信するとき、または --live で配信中のライブチャットへ常駐 daemon で自動返信するとき。「動画コメント返信」「コメント返信」「リプライ」「ライブチャット返信」「チャット自動返信」で発動。VPS・動画配信本体は /streaming を使う"
---

## 前後工程

- `前工程`: `/streaming`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `comment_reply_history.json`, `/var/lib/live-chat-reply/<channel>/live_chat_reply_history.json`
- `読み込む`: `config/channel/comments.json`, `auth/token.json`, `<CODEX_HOME>/auth.json`

## Overview

YouTube 上の返信操作をまとめるエントリポイント。フラグなしでは公開済み動画のコメント返信を一度実行して終了し、`--live` では配信中ライブチャットへの常駐 daemon を運用する。mode 専用フラグと CLI に渡す引数を混同しない。

## モード判定

`$ARGUMENTS` に含まれる mode フラグ `--live` の個数を最初に数える。

- 0 個なら `references/comments.md` を読み、残りの引数をその手順の CLI 引数として扱う
- 1 個なら `references/live.md` を読み、その手順だけを実行する
- 同じ mode フラグの重複を含め 2 個以上なら排他違反として停止する
- 未知の mode フラグは利用可能な入口を表示して停止し、フラグなし mode へ fallback しない

`--dry-run`、`--apply`、`--video-id`、`--limit`、`--per-video-limit`、`--since`、`--json`、`--export-candidates`、`--agent-replies-file` は comments mode の CLI 引数であり、mode フラグとして数えない。

| mode | 読む reference |
|---|---|
| `--live` | `references/live.md` |

## Instructions

フラグなしでは `references/comments.md` の Phase 1〜6 をそのまま実行する。特に Reviewer rubric と apply 直前の明示承認ゲートを維持し、dry-run が全項目 PASS になる前やユーザーが明示承認する前に投稿しない。`--live` では `references/live.md` の Hard Gates から開始し、`youtube-stream.service` が active でなければ `/streaming` を案内して停止する。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---:|---|
| channels.list（1 unit） | 1 | — |
| playlistItems.list / videos.list（各 1 unit） | 各 ceil(全動画数 / 50) | チャンネルの動画数 |
| commentThreads.list（1 unit） | 対象動画ごとに ceil(per-video limit / 100) | 対象動画数・取得上限 |
| comments.insert（50 units / 返信、`--apply` のみ） | 返信件数 | フィルタ通過コメント数 |
| liveBroadcasts.list（`--live`） | 配信検出時 1。配信なしは `no_broadcast_retry_sec` ごと | 既定 60 秒 |
| liveChatMessages.list（`--live`） | YouTube 応答の `pollingIntervalMillis` ごとに 1 | YouTube が返す refresh 間隔 |
| liveChatMessages.insert（`--live`） | Codex が返信対象と判定したとき 1 | 時間・連続 user・PT 日次 quota 上限 |

- 上限 / 承認: comments の dry-run は書き込み API を呼ばず、`--limit` と `max_replies_per_run` で上限を制御して apply 前の明示承認を省略しない。live は YouTube の polling interval と時間・連続 user・PT 日次 quota 上限を守り、Terraform apply の明示承認後だけ daemon を起動する。

## 完了条件

- dry-run のみなら `references/comments.md` の Phase 5 まで完了している
- apply する場合は Reviewer を通過し、明示承認後の Phase 6 が完了して `errors = 0` である
- `--live` は `references/live.md` の完了条件を全件満たしている
- キャンセル時は apply と履歴更新を行っていない

## References

- `references/comments.md`: 公開済み動画コメントの候補抽出、生成、review、dry-run、承認、apply
- `references/review-rubric.md`: Reviewer の入力境界と4基準
- `references/live.md`: 配信前提ガード、認証、daemon 配備、起動・停止・障害復旧
