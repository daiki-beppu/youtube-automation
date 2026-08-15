---
name: reply
purpose: 公開する
description: "Use when 公開済み YouTube 動画のコメントへ自動返信するとき。「動画コメント返信」「コメント返信」「リプライ」で発動。配信中のライブチャット返信は現時点では /live-chat-reply を使う"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `comment_reply_history.json`
- `読み込む`: `config/channel/comments.json`, `auth/token.json`

## Overview

YouTube 上の返信操作をまとめるエントリポイント。現時点ではフラグなしで公開済み動画のコメント返信を実行する。mode 専用フラグと CLI に渡す引数を混同しない。

## モード判定

`$ARGUMENTS` に含まれる mode フラグ `--live` の個数を最初に数える。

- 0 個なら `references/comments.md` を読み、残りの引数をその手順の CLI 引数として扱う
- 1 個の `--live` は未実装として停止し、現時点では `/live-chat-reply` を使うよう案内する
- 同じ mode フラグの重複を含め 2 個以上なら排他違反として停止する
- 未知の mode フラグは利用可能な入口を表示して停止し、フラグなし mode へ fallback しない

`--dry-run`、`--apply`、`--video-id`、`--limit`、`--per-video-limit`、`--since`、`--json`、`--export-candidates`、`--agent-replies-file` は comments mode の CLI 引数であり、mode フラグとして数えない。

## Instructions

フラグなしでは `references/comments.md` の Phase 1〜6 をそのまま実行する。特に Reviewer rubric と apply 直前の明示承認ゲートを維持し、dry-run が全項目 PASS になる前やユーザーが明示承認する前に投稿しない。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---:|---|
| channels.list（1 unit） | 1 | — |
| playlistItems.list / videos.list（各 1 unit） | 各 ceil(全動画数 / 50) | チャンネルの動画数 |
| commentThreads.list（1 unit） | 対象動画ごとに ceil(per-video limit / 100) | 対象動画数・取得上限 |
| comments.insert（50 units / 返信、`--apply` のみ） | 返信件数 | フィルタ通過コメント数 |

- 上限 / 承認: dry-run は書き込み API を呼ばない。`--limit` と `max_replies_per_run` で上限を制御し、apply 前の明示承認を省略しない。

## 完了条件

- dry-run のみなら `references/comments.md` の Phase 5 まで完了している
- apply する場合は Reviewer を通過し、明示承認後の Phase 6 が完了して `errors = 0` である
- キャンセル時は apply と履歴更新を行っていない

## References

- `references/comments.md`: 公開済み動画コメントの候補抽出、生成、review、dry-run、承認、apply
- `references/review-rubric.md`: Reviewer の入力境界と4基準
- `/live-chat-reply`: `--live` 実装前の配信中ライブチャット返信
