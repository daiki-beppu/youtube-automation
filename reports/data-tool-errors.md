# Codex tool wrapper・入力検証・編集失敗調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象: issue #1969 / #1976 の Codex `0.144.1` session、TAKT `0.51.0`
- 一次情報: 対象 session JSONL、OpenAI Codex `rust-v0.144.1` source、TAKT `v0.51.0` source

代表抽出コマンド:

```text
$ rg -n -F 'timeout_ms must be at least 10000' <target-session.jsonl>
174: ... "wait_agent","{\"timeout_ms\":1000}"
175: ... "timeout_ms must be at least 10000"
$ rg -n -F 'apply_patch verification failed' <#1969-session.jsonl>
153: ... Failed to find expected lines in .../thumbnail-test/SKILL.md
191: ... Failed to find expected lines in .../analytics-analyze/SKILL.md
```

## 調査項目ごとの結果と詳細

### 1. `timeout_ms must be at least 10000`

対象の生ログは2件である。

```text
#1969
2026-07-14T10:31:07.711Z wait_agent {"timeout_ms":1000}
2026-07-14T10:31:07.731Z timeout_ms must be at least 10000
2026-07-14T10:31:09.788Z wait_agent {"timeout_ms":10000}
2026-07-14T10:31:19.796Z {"message":"Wait timed out.","timed_out":true}

#1976
2026-07-14T10:36:53.703Z wait_agent {"timeout_ms":1000}
2026-07-14T10:36:53.721Z timeout_ms must be at least 10000
```

出典:

- `/Users/mba/.codex/sessions/2026/07/14/rollout-2026-07-14T19-22-54-019f6026-a8d8-7e91-a2ca-bd040b1c1a55.jsonl`
- `/Users/mba/.codex/sessions/2026/07/14/rollout-2026-07-14T19-32-35-019f602f-896b-7563-becf-4a6eaff0da95.jsonl`

Codex v0.144.1 の multi-agent v2 `wait` handler は次の schema / wrapper 契約を持つ。

- `timeout_ms`: 最小 `10,000`、既定 `30,000`、最大 `3,600,000`
- unknown field: `deny_unknown_fields`
- 範囲外: `FunctionCallError::RespondToModel` として当該tool callだけを拒否
- session concurrency既定: 4

固定 source:

- https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs
- https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/core/src/config/mod.rs
- 境界 tests: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/core/src/tools/handlers/multi_agents_tests.rs

判定: **入力schema違反による局所的tool error**。1秒後にSIGTERMを送るtimeoutではない。#1969は正しい10,000msで再試行し、その後も6分以上処理を継続した。#1976も以後stream eventが継続した。

#### wrapper既定値との照合

「短くpollしたい」場合でも caller が `1000` を渡すのは無効である。値を省略すれば wrapper 既定30秒となる。10秒だけ待つなら明示 `10000`。これは TAKT の stream idle timeout 10分や quality gate 300秒とは別の値である。

### 2. `apply_patch verification failed`

#1969 で2件確認した。

```text
2026-07-14T10:30:29.163Z
Failed to find expected lines in .../.claude/skills/thumbnail-test/SKILL.md:
設計モードでは以下を行う。

`/10-assets/` の対象パターンを列挙し...

2026-07-14T10:31:58.933Z
Failed to find expected lines in .../.claude/skills/analytics-analyze/SKILL.md:
description: "Use when 収集済み Analytics データの分析と戦略提案が必要なとき。..."
```

実ファイルの再読込では最初の期待行が `` `10-assets/` `` であり、patchの `` `/10-assets/` `` と一致しなかった。

```text
10:30:28.941 combined patch attempt
10:30:29.163 verification failed
10:30:33.465 rgで対象行を再読込
10:30:46.949 修正したpatch
10:30:47.515 success
10:30:52.460 sedで編集後を再読込
```

この時系列は「失敗後に現在内容を再読込し、contextを作り直す」ことで回復した実例である。

2件目は複数ファイルを含むpatch内で、`analytics-analyze/SKILL.md` のdescriptionが期待値と一致せず全体verifyに失敗した。sessionは並行subagentを使っており、読み取りから適用までに別編集が入る可能性もあった。ただし対象行の変更主体まではsessionだけで確定できない。

Codex sourceの契約:

- tool handlerはparse / filesystem verify失敗を `RespondToModel` で返す。
- update hunkは現在ファイルからold lines / contextを探索し、不一致なら `Failed to find expected lines`。
- verify失敗したpatchは適用しない。

固定 source:

- https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/core/src/tools/handlers/apply_patch.rs
- https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/apply-patch/src/lib.rs
- side-effect / missing-context tests: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/core/tests/suite/apply_patch_cli.rs

判定: **局所的編集エラー**。古い/不正な前提での上書きを防ぐ安全機構であり、workerのfatal errorではない。

### 3. 編集前再読込と古いファイル前提

対象sessionから確認できる規則は次の通り。

1. patch contextは記憶や別agentの要約ではなく、編集直前に対象fileから取る。
2. 並行編集可能なfileは、読み取りとpatchの間を短くする。
3. 1つの巨大multi-file patchは、1 fileのstale contextで全体が失敗する。独立変更はfile単位に分ける。
4. verify失敗後は同一patchを盲目的に再送せず、`rg` / `sed`で該当sectionを再読込する。
5. 成功後は対象sectionと`git diff --check`等で結果を検証する。

これは source の「現在fileにexpected linesが存在すること」という検証機序と、対象sessionの回復手順の両方に整合する。

### 4. TAKT側 timeout と Codex tool wait の分離

| timeout | 値 | 対象 | 終了動作 |
|---|---:|---|---|
| Codex `wait_agent.timeout_ms` | min 10秒、default 30秒、max 60分 | agent mailbox wait | invalidなら当該tool call拒否、満了ならtimed_out応答 |
| TAKT Codex stream idle | 10分無event | provider stream | AbortSignal、最大2 timeout retry |
| TAKT command quality gate | default 300秒 | shell quality gate | process group SIGTERM、100ms後SIGKILL |
| team leader part timeout | workflow `team_leader.timeout_ms` | team leader part | part timeout分類 |
| graceful SIGINT | interactive 10秒 / noninteractive 5秒 | active worker群 | shared AbortController、期限/2回目でexit 130 |

TAKT source:

- stream: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/codex/client.ts
- command gate: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/core/workflow/quality-gates/commandGateRunner.ts
- gate defaults: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/core/models/quality-gate-defaults.ts
- shutdown: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/execute/shutdownManager.ts

対象3件は終了の0.5–20.4秒前にeventがあり、10分stream idle条件を満たさない。`wait_agent`の1000ms schema errorとも無関係である。

### 5. schema制約、対象関数、ログlevel

| 対象 | 設定 / 関数 | 制約 | 表面化 |
|---|---|---|---|
| Codex wait | `WaitArgs`, wait handler | 10,000–3,600,000ms、unknown禁止 | tool ERROR / RespondToModel |
| Codex patch | `apply_patch`, `seek_sequence`等 | expected old linesが現在fileに存在 | tool ERROR / RespondToModel |
| TAKT concurrency | project config schema | integer 1–10 | config parse failure |
| TAKT task poll | project config schema | integer 100–5,000ms | config parse failure |
| TAKT team leader | workflow schema | `max_concurrency` 1–3、timeout positive | workflow parse failure |
| command gate | `CommandGateSchema.timeout` | positive、default 300,000ms | gate failure |

TAKT config schema: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/core/models/config-schemas.ts

### 6. fatal / nonfatal 分類

| 事象 | patch/file state | agent/process state | 分類 |
|---|---|---|---|
| wait 1000ms | 変更なし | agent継続 | 非致命、入力エラー |
| patch verify failed | 当該patch非適用 | agent継続 | 非致命、安全な編集拒否 |
| patch success | 対象変更適用 | agent継続 | 正常 |
| SIGTERM | 適用済み部分差分はworktreeに残り得る | Codex worker終了、TAKT task failed | 致命的 |

## 主要な発見のサマリー

1. `timeout_ms must be at least 10000` は `wait_agent(1000)` のschema違反であり、timeout発火やSIGTERMではない。
2. `apply_patch verification failed` は現在fileとexpected linesの不一致を検出した安全な拒否である。
3. #1969 は再読込後のpatch成功までログで追跡でき、局所errorから回復している。
4. 巨大multi-file patchと並行編集はstale contextのblast radiusを広げる。
5. terminal failureはこれらtool errorではなく、後続のSIGTERMである。

## 注意点・リスク

- task ledgerはtool ERRORをterminal SIGTERMのstderrへ連結するため、先行tool errorがtask failure原因に見える。
- `apply_patch`成功は意味的正しさを保証しない。edit後のsection確認とtestが必要。
- multi-agent環境では「直前に読んだ」だけでは不十分で、別agentが同じfileを編集しないownershipも必要。
- waitの最小値をwrapper側で勝手に丸めるとcaller bugを隠す。明示的validation errorを維持すべきである。

## 調査できなかった項目と理由

1. **2件目patchの対象行を変更した主体**: 対象sessionは並行agentを使うが、失敗時点のfile provenanceが保存されていない。
2. **失敗multi-file patchの他hunkが全て未適用かの当時worktree確認**: worktreeは削除済み。source契約上はverify failureで非適用だが、当時snapshotはない。
3. **tool wrapper生成schemaのUI側表示**: sessionにはruntime validation結果はあるが、当時の完全なtool manifest snapshotはない。

## 推奨／結論

### 推奨する変更候補

1. agent prompt / wrapper usage exampleで `wait_agent` の最小10秒、既定30秒を固定する。
2. `apply_patch`前に対象fileのmtime/hashを記録し、read時hashと異なる場合は再読込する。
3. patch failure logへfile、hunk ordinal、read hash、current hashを追加する。file本文やsecretは出さない。
4. 並行agentへfile ownershipを割り当て、同一fileの同時writerを避ける。
5. 独立したmulti-file変更はfile単位のpatchに分割し、各成功後に局所testを行う。

### テスト

- `wait_agent(9999)` はschema error、`10000` はwait開始、省略は30秒既定。
- unknown wait fieldは拒否。
- patch expected line 1文字差で非適用、file hash不変。
- verify失敗後に再読込してcontext更新したpatchは成功。
- 2 writerが同一fileを更新した場合、後続writerはhash差を検出して再読込。
- multi-file patchの1 file不一致で部分適用されないことを固定。

### 受け入れ条件

- invalid waitがprocess/task terminal failureにならない。
- patch verify failureで対象fileが部分変更されない。
- stale readを検出した場合、自動で再読込するか明示的に停止し、古いcontextを再送しない。
- task ledgerで `tool_validation_error`、`edit_conflict`、`signal_termination` を区別できる。

### ロールバック

- hash guardはfeature flagで無効化できるようにし、既存apply_patch検証は常に残す。
- structured fieldsはoptional追加とし、旧`error`文字列を併記する。
- wait validationは安全境界なのでロールバック時も10秒未満を許可せず、usage docsだけを戻す。

結論: 修正対象の中心はtimeout値ではなく、callerのschema遵守、編集直前再読込、file ownership、error分類の永続化である。
