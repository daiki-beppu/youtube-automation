---
name: skill-feedback
purpose: 振り返る
description: "Use when 下流チャンネルリポジトリでスキル実行中の不具合・摩擦・改善案を構造化記録するとき、または記録済み feedback を上流 issue に還流するとき。「/skill-feedback」「摩擦を記録」「改善案を残す」「feedback を上流に還流して」「今週の feedback 還流して」で発動。分析の学びは analytics の analyze / flop mode を使う"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `data/feedback/feedback-log.jsonl`
- `読み込む`: `data/feedback/feedback-log.jsonl`

## 修飾フラグ

| modifier | 効果 |
|---|---|
| `--analyze` | 運営上の学びは `/analytics` の分析へ委譲する |

## Overview

下流チャンネルリポジトリの `data/feedback/feedback-log.jsonl` に、不具合・摩擦・
改善案を記録する。または、記録済み entry をユーザー承認後に上流
`daiki-beppu/youtube-automation` の GitHub issue へ還流する。

## Hard Gates

- 記録モードでは既存行を変更せず、schema 準拠の JSON object を末尾に 1 行だけ追加する
- 還流モードでは `status="recorded"` の行だけを候補にする。`filed` / `resolved` / `wontfix` は終端状態として表示・選択・起票・変更の対象にしない
- schema-invalid 行は行番号と schema または JSON parse の失敗理由を警告し、候補から除外する。valid な `recorded` entry の処理は継続する
- `resolved` / `wontfix` への更新は、ユーザーが対象行と disposition を明示的に確認した場合だけ行う。空でない簡潔な `disposition_reason` と更新時刻 `disposition_at` を必須とする
- issue 起票前に open issue のタイトルを照合し、類似候補ごとに新規起票かスキップかをユーザーに確認する
- 起票対象、件数、タイトルを表示し、`AskUserQuestion` で「起票する / 中止」の明示 2 択を提示する。承認されるまで `gh issue create` を絶対に実行しない
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
- ユーザーが確認した解決済みの行だけが `status="resolved"`、意図的に起票しないと確認した行だけが `status="wontfix"` となり、`disposition_reason` と `disposition_at` を持つ
- 未選択、スキップ、起票失敗の行は変更されていない
- 更新した行が entry schema に準拠し、JSONL の行数と順序が更新前と同じである
- invalid 行、terminal entry、未選択、スキップ、起票失敗の行は byte-for-byte で変更されていない

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
| YouTube Analytics や投稿結果から得た運営上の学びを残す | 対象外。`/analytics --analyze` や `/analytics --flop` を使う |

## Entry Schema

1 entry は JSON object 1 行で、次のフィールドを持つ。

| field | required | value |
|---|---:|---|
| `date` | yes | 記録日時。ISO 8601 の date-time 文字列 |
| `skill` | yes | 対象スキル名。例: `thumbnail` |
| `category` | yes | `bug` / `friction` / `idea` のいずれか |
| `summary` | yes | 1 文の要約 |
| `context` | yes | 再現状況・エラー抜粋・期待と実際の差分 |
| `status` | yes | 未還流は `recorded`、起票済みは `filed`、解決確認済みは `resolved`、意図的な見送りは `wontfix` |
| `issue_url` | filed only | `filed` にした GitHub issue の URL |
| `disposition_reason` | resolved / wontfix only | 終端 disposition にした根拠を 1 文で簡潔に記録する |
| `disposition_at` | resolved / wontfix only | disposition 更新日時。ISO 8601 の date-time 文字列 |

## Entry lifecycle contract

| status | filing candidate | terminal | required metadata |
|---|---|---|---|
| recorded | yes | no | none |
| filed | no | yes | issue_url |
| resolved | no | yes | disposition_reason, disposition_at |
| wontfix | no | yes | disposition_reason, disposition_at |

`recorded` だけが還流候補である。`filed` / `resolved` / `wontfix` は終端状態であり、
次回以降の還流モードで一覧表示、選択、起票、変更を行わない。

## Schema-invalid line contract

| line classification | filing candidate | mutable | required action |
|---|---|---|---|
| schema-invalid | no | no | warn with line number and reason; continue |
| valid recorded | yes | after approval only | continue filing flow |
| valid terminal | no | no | leave unchanged |

schema-invalid には JSON として parse できない行と、parse できても entry schema に準拠しない行を
含む。invalid 行と terminal entry は変更しない。警告理由は error class、schema keyword、JSON pointer、line、column
のうち該当する safe metadata だけから組み立てる。invalid raw bytes、instance value、validator の raw message
は、未マスクの secret-like value や object 全体を含み得るため表示しない。たとえば `summary` が空の
7 行目は `line 7: schema keyword=minLength pointer=/summary` と表示し、実際の値は付けない。

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
feedback を記録するよう案内して停止する。ファイル全体を bytes の snapshot として読み、
各 physical line の元の bytes と line terminator を行番号に対応づけて保持する。全行を先に走査し、
JSON parse と `references/feedback-entry.schema.json` の検証結果から各行を上の contract に分類する。
schema-invalid 行ごとに `line <行番号>: <簡潔な理由>` を警告し、候補から除外して処理を続ける。

走査後、元 snapshot と同一内容を一時ファイルへ書き、同じディレクトリで atomic replace できる
ことと、置換後に行数、行順、対象外行の byte-for-byte 同一性を検証できることを、外部副作用を
始める前に事前確認する。読取エラーなどで全 physical line を分類できない、元 bytes と line
terminator を保持できない、または atomic rewrite の事前検証を完了できない場合は、
issue 起票や disposition 更新を開始せず fail-closed に停止する。事前確認用の一時ファイルで元ログを置換せず、
確認後に削除する。

保持状態は、最新 snapshot、全行の bytes、各 line terminator、valid entry の行番号と JSON object で
構成する。atomic rewrite が成功するたびに更新するため、置換後のファイルを読み直して全行を再分類し、
期待した対象行だけが変わり、それ以外の bytes が保存されたことを検証してから、保持状態全体を新しい
内容へ置き換える。検証または保持状態の更新に失敗した場合は、次の disposition 更新や issue 起票へ
進まず停止する。

この progression は処理種別をまたいで適用する。disposition rewrite の成功後も filing flow の前に最新状態へ進める。
その際に最新 snapshot、全行の bytes、未処理 entry の保持値を置換後の内容から再構築し、処理済み entry は
候補から除く。各 filing candidate の atomic rewrite 成功後にも同じ更新を行い、次の candidate は更新済みの最新 snapshot を基準に処理する。

`status` が `"recorded"` の行だけを、元の行番号、`date`、`skill`、`category`、
`summary` とともに一覧表示する。`context` は一覧に表示しない。候補が 0 件なら
「未還流 feedback は 0 件」と報告して終了する。

`filed` / `resolved` / `wontfix` の行は終端 entry のため、一覧表示、選択、起票、
状態更新のいずれにも含めない。

ユーザーに各 `recorded` entry の扱いを「起票候補 / 解決済み / 意図的に見送り / 今回は保留」
から選んでもらう。選択した各行について、行番号と元の JSON object 全体を保持する。
以後の更新対象はこの組で識別し、同内容の entry が複数あっても混同しない。

### Step 1a: 非起票の終端 disposition を確定

「解決済み」は現行版で問題が解決していると検証できた entry だけに使い、`resolved` とする。
「意図的に見送り」は問題を確認した上で起票しないと判断した entry だけに使い、`wontfix` とする。
各 entry について、空でない 1 文の簡潔な理由をユーザーに確認する。推測で理由を補わない。

対象行、更新後の status、理由を表示し、`AskUserQuestion` で「disposition を記録する / 中止」の
明示 2 択を提示する。確認された場合だけ、保持した行番号の現在値が元 JSON object と完全一致する
ことを確認し、次のフィールドを 1 回の atomic rewrite で更新する。

- `status`: `resolved` または `wontfix`
- `disposition_reason`: ユーザーが確認した簡潔な理由
- `disposition_at`: 更新時点の UTC を ISO 8601 date-time で記録した値

terminal entry に `issue_url` を追加しない。更新対象行が schema に準拠し、行数と行順が同じで、
対象外の行が byte-for-byte で同一であることを確認してから元ファイルを置換する。具体的には、
更新対象だけを schema-valid な JSON 1 行へ serialize し、invalid 行、terminal entry、未選択行を元の bytes のまま複写する。
更新直前にファイル全体が保持した bytes snapshot と同一であることも確認する。確認失敗、元 snapshot
の不一致、更新対象の schema 検証失敗ではログを変更せず停止する。既存の schema-invalid 行は
検証対象から除外して元 bytes のまま保持する。更新済みの terminal entry は Step 2
以降へ渡さず、起票も行わない。「今回は保留」の entry は `recorded` のまま変更しない。

### Step 2: 本文案を確認

各選択 entry から、タイトルを `[feedback][<skill>] <summary>` の形で作る。
`references/upstream-issue-template.md` の全セクションを埋める。entry に独立したエラー
抜粋がなければ「なし」と書き、情報を推測で補わない。

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

同じ entry の前回処理で issue 作成だけが成功した可能性があり、open issue のタイトルとマスク済み本文が
今回の生成物に完全一致する場合は `created-unrecorded` の recovery 候補として扱う。この場合は
「それでも新規起票する」を提示せず、既存 issue URL を使う recovery rewrite を Step 5 の更新契約で
行うか、中止するかを確認する。完全一致を証明できなければ新規起票せず fail-closed に停止する。

### Step 4: 最終承認ゲート

スキップを除いた起票対象について、件数と各タイトルを表示する。
「GitHub issue として外部へ反映され、このスキルからは取り消せない」と警告し、
`AskUserQuestion` で次の 2 択を提示する。

1. 起票する
2. 中止

「起票する」が明示的に選ばれた場合だけ Step 5 へ進む。「中止」、無回答、曖昧な回答では
`gh issue create` を実行せず、ログも変更しない。

### Step 5: issue 起票と直後のログ更新

承認済み entry を 1 件ずつ処理する。各 `gh issue create` の直前にファイル全体を再読し、current bytes が最新 snapshot と完全一致
することを検証する。不一致ならコマンドを実行せず fail-closed に停止する。一致した場合だけ、マスク済み本文を
一時ファイルへ保存し、次を実行する。

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
- 更新対象行が `references/feedback-entry.schema.json` に準拠する
- 行数と行順は更新前と同じである
- invalid 行、terminal entry、未選択行を含む対象以外の行は byte-for-byte で同じである

一時ファイルは、更新対象行だけを JSON 1 行へ serialize し、ほかの行は保持した元 bytes と line
terminator を連結して構成する。置換直前に現在のファイル全体が保持した snapshot と同一であることを
再確認し、不一致なら置換せず停止する。

1 件の起票またはログ更新が失敗したら後続 entry を起票せず停止する。`gh issue create` が成功した後に
ログ更新だけが失敗した場合は、その entry を `created-unrecorded` として行番号、作成済み issue URL、
失敗箇所とともに報告する。同じ entry で `gh issue create` を再実行してはならない。再開時は Step 3 で
作成済み issue のタイトルとマスク済み本文の完全一致を確認し、既存 issue URL を使う recovery rewrite
だけを行う。recovery rewrite も current bytes と新しく取得した snapshot の一致、対象 entry の元 JSON
object 一致、schema、行数、行順、対象外 bytes を通常更新と同じ条件で検証し、成功後は保持状態を進める。
対応する issue を一意に証明できなければ新規起票もログ更新も行わず停止する。

issue が作成されていない失敗では entry は `recorded` のままとし、未処理 entry と失敗箇所を報告する。

### Step 6: 完了報告

起票した issue のタイトルと URL、`filed` に更新した行番号、`resolved` / `wontfix` に更新した
行番号と理由、スキップした entry を報告する。
機密値、本文全文、長い error log は再掲しない。

## Non-goals

- 起票された上流 issue のトリアージ・優先度付け
- Analytics の analyze / flop mode 由来の運営知見の記録
- status enum と disposition metadata の追加・変更
- feedback JSONL を処理する runtime Python 実装の追加
