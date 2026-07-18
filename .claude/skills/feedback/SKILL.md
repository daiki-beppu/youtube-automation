---
name: feedback
description: "Use when 下流チャンネルリポジトリでスキル実行中の不具合・摩擦・改善案を構造化記録するとき、または記録済み feedback を上流 issue に還流するとき。「/feedback」「摩擦を記録」「改善案を残す」「feedback を上流に還流して」「今週の feedback 還流して」で発動。分析の学びは /analytics-analyze や /flop-analysis を使う"
---

## Overview

下流チャンネルリポジトリの `data/feedback/feedback-log.jsonl` に、不具合・摩擦・
改善案を記録する。または、記録済み entry をユーザー承認後に上流
`daiki-beppu/youtube-automation` の GitHub issue へ還流する。

## Hard Gates

- 記録モードでは既存行を変更せず、schema 準拠の JSON object を末尾に 1 行だけ追加する
- 還流モードでは `status="recorded"` の行だけを候補にする。`status="filed"` の行は表示も起票もせず、二重起票を防ぐ
- issue 起票前に open issue のタイトルを照合し、類似候補ごとに新規起票かスキップかをユーザーに確認する
- 起票対象、件数、タイトル、チャンネル名の掲載有無を表示し、`AskUserQuestion` で「起票する / 中止」の明示 2 択を提示する。承認されるまで `gh issue create` を絶対に実行しない
- GitHub issue は外部へ反映され、起票後はこのスキルから取り消せないことを承認時に警告する
- entry の `context` と issue のタイトル・本文に、未マスクの機密情報を含めない
- `gh issue create` が成功して issue URL を返した entry だけを `status="filed"` に更新し、同じ URL を `issue_url` に記録する

## 完了条件

### 記録モード

- `feedback-log.jsonl` の末尾に schema 準拠の JSONL が 1 行だけ追加されている
- 新規 entry の `status` は `"recorded"` で、`issue_url` はない
- `context` 内の機密情報は `***REDACTED***` に置換されている

### 還流モード

- ユーザーが承認した entry ごとに、上流へ `feedback` ラベル付き issue が 1 件起票されている
- 起票に成功した行だけが `status="filed"` と `issue_url` を持つ
- 未選択、スキップ、起票失敗の行は変更されていない
- 更新後の全行が entry schema に準拠し、JSONL の行数と順序が更新前と同じである

## References

- Entry schema: `references/feedback-entry.schema.json`
- Upstream issue body: `references/upstream-issue-template.md`

## モード選択

| ユーザーの意図 | モード |
|---|---|
| 「さっきの `/thumbnail` の摩擦を記録して」 | 記録 |
| 「このスキル、ここでエラーになった」 | 記録 |
| 「feedback を上流に還流して」 | 還流 |
| 「今週の feedback 還流して」 | 還流 |
| YouTube Analytics や投稿結果から得た運営上の学びを残す | 対象外。`/analytics-analyze` や `/flop-analysis` を使う |

## Entry Schema

1 entry は JSON object 1 行で、次のフィールドを持つ。

| field | required | value |
|---|---:|---|
| `date` | yes | 記録日時。ISO 8601 の date-time 文字列 |
| `skill` | yes | 対象スキル名。例: `thumbnail` |
| `category` | yes | `bug` / `friction` / `idea` のいずれか |
| `summary` | yes | 1 文の要約 |
| `context` | yes | 再現状況・エラー抜粋・期待と実際の差分 |
| `status` | yes | 未還流は `recorded`、起票済みは `filed` |
| `issue_url` | filed only | `filed` にした GitHub issue の URL |

## 共通: 機密情報のマスク

`context` に次の情報が含まれる場合は、値全体を `***REDACTED***` に置換する。

- OAuth token / refresh token / access token / bearer token
- API key / secret / password / private key
- `.env` 由来の値
- `auth/client_secrets.json` / `auth/token.json` の中身
- `op://` 参照そのものを除く、1Password から取得した secret 値

記録モードではマスク後の `context` だけを保存する。還流モードでも、既存 entry を
信用してそのまま転記せず、タイトルと本文の組み立て前に同じ規則で再確認・再マスクする。
未マスクの値をログ、画面、issue のタイトル・本文へ出してはならない。

## 記録モード

### Step 1: 記録内容を確定

ユーザー発話と直近の作業文脈から、次を確定する。

- `skill`: 対象スキル名。明示されていなければ、直近で実行中だったスキル名を使う。特定できない場合はユーザーに確認して停止する
- `category`: `bug` / `friction` / `idea` から 1 つ選ぶ
- `summary`: 1 文に要約する
- `context`: 再現状況、エラー抜粋、期待した挙動、実際の挙動を含める

### Step 2: 追記先を用意

下流リポジトリのルートを基準に、`data/feedback/` が存在しなければ作成する。
`data/feedback/feedback-log.jsonl` が存在しなければ新規作成する。

### Step 3: append-only で 1 行追記

既存の `feedback-log.jsonl` がある場合は、既存行を変更せず、末尾に 1 行だけ追記する。
pretty print した複数行 JSON は使わない。

記録例:

```json
{"date":"2026-07-11T15:02:24Z","skill":"thumbnail","category":"friction","summary":"生成結果が期待した構図から外れた","context":"ユーザーが夜景寄りのサムネを期待したが、出力は昼の室内風だった。エラーはなし。","status":"recorded"}
```

### Step 4: 追記後チェック

- 追加されたのは末尾 1 行だけである
- 追加行は `references/feedback-entry.schema.json` のフィールド要件に合っている
- `status` は `"recorded"` で、`issue_url` は含まない
- `context` に未マスクの token / secret / password / private key / API key が残っていない

完了報告では、追記したファイルパス、対象スキル、category、summary だけを伝える。
機密値や長い error log は再掲しない。

## 還流モード

### Step 1: 前提確認と未還流 entry の一覧提示

`data/feedback/feedback-log.jsonl` の存在を確認する。存在しない場合は、先に記録モードで
feedback を記録するよう案内して停止する。各行を JSON として読み、schema に準拠しない
行が 1 行でもあれば、行番号だけを示して停止する。壊れた行を飛ばして続行しない。

`status` が `"recorded"` の行だけを、元の行番号、`date`、`skill`、`category`、
`summary` とともに一覧表示する。`context` は一覧に表示しない。候補が 0 件なら
「未還流 feedback は 0 件」と報告して終了する。

ユーザーに起票する行を選んでもらう。選択した各行について、行番号と元の JSON object
全体を保持する。以後の更新対象はこの組で識別し、同内容の entry が複数あっても混同しない。

### Step 2: 本文案とチャンネル名の掲載可否を確認

各選択 entry から、タイトルを `[feedback][<skill>] <summary>` の形で作る。
`references/upstream-issue-template.md` の全セクションを埋める。entry に独立したエラー
抜粋がなければ「なし」と書き、情報を推測で補わない。

発生チャンネル名は entry schema に含まれないため、自動推定・自動掲載しない。
`AskUserQuestion` で「チャンネル名を掲載する / 掲載しない」の明示 2 択を entry ごとに
提示する。掲載する場合はユーザーが明示した名前だけを使い、掲載しない場合は
テンプレートの発生チャンネル欄を「掲載しない（ユーザー確認済み）」とする。

タイトルと本文へ共通のマスク規則を再適用した後、ユーザーへ全文を提示する。

### Step 3: open issue の重複照合

起票前に上流の open issue を全件取得する。

```bash
gh api --paginate --method GET \
  repos/daiki-beppu/youtube-automation/issues \
  -f state=open \
  -f per_page=100 \
  --jq '.[] | select(has("pull_request") | not) | {number, title, url: .html_url}'
```

候補タイトルと open issue タイトルを、前後空白の除去、連続空白の 1 文字化、英字の
小文字化をした文字列で照合する。次のどちらかなら類似候補として警告する。

- 正規化後のタイトルが完全一致する
- 同じ `[feedback][<skill>]` prefix を持ち、一方の prefix 後の全文が他方に含まれる

類似候補の番号、タイトル、URL を表示し、`AskUserQuestion` で「それでも新規起票する /
この entry をスキップ」の明示 2 択を提示する。ユーザーが選ぶまでその entry を起票しない。
スキップした entry はログも変更しない。

### Step 4: 最終承認ゲート

スキップを除いた起票対象について、件数、各タイトル、発生チャンネル欄の内容を表示する。
「GitHub issue として外部へ反映され、このスキルからは取り消せない」と警告し、
`AskUserQuestion` で次の 2 択を提示する。

1. 起票する
2. 中止

「起票する」が明示的に選ばれた場合だけ Step 5 へ進む。「中止」、無回答、曖昧な回答では
`gh issue create` を実行せず、ログも変更しない。

### Step 5: issue 起票と直後のログ更新

承認済み entry を 1 件ずつ処理する。マスク済み本文を一時ファイルへ保存し、次を実行する。

```bash
gh issue create \
  --repo daiki-beppu/youtube-automation \
  --label feedback \
  --title "<承認済みタイトル>" \
  --body-file "<マスク済み本文の一時ファイル>"
```

exit code が 0 で、標準出力から当該 issue URL を取得できた場合だけ、該当する元の行を
`status: "filed"`、`issue_url: "<取得した URL>"` に置換する。更新直前に、保持した行番号の
現在値が保持した元 JSON object と完全一致することを確認する。一致しなければログを
変更せず停止し、起票済み URL と状態更新失敗を報告する。

ログ更新は一時ファイルに全行を JSONL 形式で書き出し、次をすべて確認してから元ファイルへ
置換する。

- 更新対象は保持した行番号の 1 行だけである
- 更新後の対象行は `status="filed"` と取得した `issue_url` を持つ
- 全行が `references/feedback-entry.schema.json` に準拠する
- 行数と行順は更新前と同じである
- 対象以外の行は byte-for-byte で同じである

1 件の起票またはログ更新が失敗したら後続 entry を起票せず停止する。失敗した entry は
`recorded` のままにし、成功済み issue の URL、未処理 entry、失敗箇所を報告する。

### Step 6: 完了報告

起票した issue のタイトルと URL、`filed` に更新した行番号、スキップした entry を報告する。
機密値、本文全文、長い error log は再掲しない。

## Non-goals

- 起票された上流 issue のトリアージ・優先度付け
- Analytics / flop-analysis 由来の運営知見の記録
