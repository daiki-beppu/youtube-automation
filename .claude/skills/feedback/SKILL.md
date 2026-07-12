---
name: feedback
description: "Use when 下流チャンネルリポジトリでスキル実行中の不具合・摩擦・改善案を構造化記録するとき。「/feedback」「摩擦を記録」「改善案を残す」で発動。分析の学びは /analytics-analyze や /postmortem を使う"
---

## Overview

スキル実行中に遭遇した不具合・摩擦・改善案を、下流チャンネルリポジトリの
`data/feedback/feedback-log.jsonl` に append-only で 1 行追記する。

このスキルは上流 issue 起票を行わない。記録だけを行い、元の作業は中断しない。

## 完了条件

- `data/feedback/feedback-log.jsonl` の末尾に schema 準拠の JSONL が 1 行だけ追加されている
- 既存行は変更・削除・並べ替えされていない
- 新規 entry の `status` は `"recorded"` である
- `context` 内の機密情報は `***REDACTED***` に置換されている

## References

- Entry schema: `references/feedback-entry.schema.json`

## When to Use

| 状況 | 使う？ |
|---|---|
| 「さっきの `/thumbnail` の摩擦を記録して」 | ✅ 使う |
| 「このスキル、ここでエラーになった」 | ✅ 使う |
| 「この手順は改善できそう」 | ✅ 使う |
| YouTube Analytics や投稿結果から得た運営上の学びを残す | ❌ `/analytics-analyze` や `/postmortem` を使う |
| 記録済み feedback を GitHub issue 化する | ❌ このスキルでは行わない |

## Entry Schema

1 entry は JSON object 1 行で、次のフィールドを持つ。

| field | required | value |
|---|---:|---|
| `date` | yes | 記録日時。ISO 8601 の date-time 文字列 |
| `skill` | yes | 対象スキル名。例: `thumbnail` |
| `category` | yes | `bug` / `friction` / `idea` のいずれか |
| `summary` | yes | 1 文の要約 |
| `context` | yes | 再現状況・エラー抜粋・期待と実際の差分 |
| `status` | yes | 新規記録時は必ず `recorded` |
| `issue_url` | filed only | 後続工程で issue 化済みになった場合のみ URL を持つ |

## Instructions

### Step 1: 記録内容を確定

ユーザー発話と直近の作業文脈から、次を確定する。

- `skill`: 対象スキル名。明示されていなければ、直近で実行中だったスキル名を使う。特定できない場合はユーザーに確認して停止する
- `category`: `bug` / `friction` / `idea` から 1 つ選ぶ
- `summary`: 1 文に要約する
- `context`: 再現状況、エラー抜粋、期待した挙動、実際の挙動を含める

### Step 2: 機密情報をマスク

`context` に次の情報が含まれる場合は、値全体を `***REDACTED***` に置換する。

- OAuth token / refresh token / access token / bearer token
- API key / secret / password / private key
- `.env` 由来の値
- `auth/client_secrets.json` / `auth/token.json` の中身
- `op://` 参照そのものを除く、1Password から取得した secret 値

マスク後の `context` だけを entry に入れる。未マスクの機密情報を
`feedback-log.jsonl` に書き込んではならない。

### Step 3: 追記先を用意

下流リポジトリのルートを基準に、`data/feedback/` が存在しなければ作成する。
`data/feedback/feedback-log.jsonl` が存在しなければ新規作成する。

### Step 4: append-only で 1 行追記

既存の `feedback-log.jsonl` がある場合は、既存行を変更せず、末尾に 1 行だけ追記する。
pretty print した複数行 JSON は使わない。

記録例:

```json
{"date":"2026-07-11T15:02:24Z","skill":"thumbnail","category":"friction","summary":"生成結果が期待した構図から外れた","context":"ユーザーが夜景寄りのサムネを期待したが、出力は昼の室内風だった。エラーはなし。","status":"recorded"}
```

### Step 5: 追記後チェック

追記後に次を確認する。

- 追加されたのは末尾 1 行だけである
- 追加行は `references/feedback-entry.schema.json` のフィールド要件に合っている
- `status` は `"recorded"` である
- `issue_url` は含めない
- `context` に未マスクの token / secret / password / private key / API key が残っていない

完了報告では、追記したファイルパス、対象スキル、category、summary だけを伝える。
機密値や長い error log は再掲しない。

## Non-goals

- 記録済み entry の GitHub issue 化
- `status` を `filed` に変更すること
- Analytics / postmortem 由来の運営知見の記録
