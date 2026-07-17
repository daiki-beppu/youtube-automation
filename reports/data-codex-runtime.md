# Codex runtime・loader・telemetry 調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象時点: 2026-07-14 10:22–10:39 UTC
- 対象版: Codex CLI / SDK `0.144.1`、TAKT `0.51.0`
- Codex 固定点: `rust-v0.144.1` = `44918ea10c0f99151c6710411b4322c2f5c96bea`
- TAKT 固定点: `v0.51.0` = `90ecdfb893909979c92f550f3730393502e6fde8`

一次情報だけを採用した。ローカルログは対象実行の session / task ledger、外部情報は OpenAI Codex・TAKT・Node.js の公式 source / docs である。

主な抽出コマンドと代表出力:

```text
$ takt --version
0.51.0
$ node -p "require('/Users/mba/.bun/install/global/node_modules/@openai/codex-sdk/package.json').version"
0.144.1
$ sed -n '435,489p' .takt/tasks.yaml | rg -o '<warning patterns>' | sort | uniq -c
34 Model personality
2 apply_patch verification failed
5 codex_analytics::client
4 interface.icon_
1 slow statement
1 timeout_ms must be at least 10000
```

## 調査項目ごとの結果と詳細

### 1. Codex 起動、モデル、親子 process

TAKT の `CodexProvider.toCodexOptions()` は cwd、model、reasoning effort、sandbox、network、`AbortSignal` 等を `CodexClient` へ渡す。

- ローカル: `/Users/mba/.bun/install/global/node_modules/takt/dist/infra/providers/codex.js`
- 固定 source: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/providers/codex.ts

SDK は `codex exec --experimental-json` を `spawn()` し、stdin へ prompt を書き、`signal: args.signal` を渡す。

- ローカル: `/Users/mba/.bun/install/global/node_modules/@openai/codex-sdk/dist/index.js`
- 固定 source: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/sdk/typescript/src/exec.ts

対象 worker の session meta は次の版と cwd を記録する。

```text
#1969 cli_version=0.144.1 cwd=/Users/mba/02-yt/takt-worktrees/20260714T1022-1969-issue-1969-bita-nosamune-ruupu
#1801 cli_version=0.144.1 cwd=/Users/mba/02-yt/takt-worktrees/20260714T1022-1801-issue-1801-analytics-thumbnail
#1976 cli_version=0.144.1 cwd=/Users/mba/02-yt/takt-worktrees/20260714T1028-1976-issue-1976-stale-repooto-ni-an
```

出典:

- `/Users/mba/.codex/sessions/2026/07/14/rollout-2026-07-14T19-22-54-019f6026-a8d8-7e91-a2ca-bd040b1c1a55.jsonl`
- `/Users/mba/.codex/sessions/2026/07/14/rollout-2026-07-14T19-23-56-019f6027-9de0-7e20-a37d-2236fbb873eb.jsonl`
- `/Users/mba/.codex/sessions/2026/07/14/rollout-2026-07-14T19-32-35-019f602f-896b-7563-becf-4a6eaff0da95.jsonl`

対象時点の process 観測では TAKT PID `13771` の直下に Codex worker が3件あった。

```text
2026-07-14T10:28:06.934Z
22286 13771 05:16 S+ codex exec ... --cd .../1969-issue-1969-...
51147 13771 04:10 S+ codex exec ... --cd .../1801-issue-1801-...
98783 13771 01:46 S+ codex exec ... --model gpt-5.6-terra --cd .../1939-...

2026-07-14T10:32:45.087Z
22286 13771 09:55 S+ codex exec ... --cd .../1969-issue-1969-...
30576 13771 02:28 S+ codex exec ... --model gpt-5.6-luna --cd .../1939-...
62906 13771 00:12 S+ codex exec ... --cd .../1976-issue-1976-...
```

生ログ: `/Users/mba/.codex/archived_sessions/rollout-2026-07-14T16-16-11-019f5f7b-b6fe-76a3-90b3-5dcb94b6ce01.jsonl`

`--model` が process list にない worker も session / warning は `gpt-5.6-sol` を示す。TAKT の persona option、省略時の Codex config / model resolution が関与するため、process argv だけから最終モデルを決めない。

### 2. model personality fallback

対象ログ:

```text
WARN codex_protocol::openai_models: Model personality requested but
model_messages is missing, falling back to base instructions.
model=gpt-5.6-sol personality=pragmatic
```

対象 run の出現数（task ledger の `failure.error` だけを数え、複製された `last_message` は除外）:

| issue | 回数 | 最初 | 最後 |
|---|---:|---|---|
| #1969 | 34 | 10:30:10.623677Z | 10:37:53.354727Z |
| #1801 | 0 | — | — |
| #1976 | 20 | 10:36:14.308915Z | 10:38:53.004506Z |

Codex source は personality 指定時に model message/template がなければ WARN を出し、base instructions の clone を返す。明示的な fallback であり、ここでは worker を終了しない。

- 固定 source: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/protocol/src/openai_models.rs
- 対象時点 config: `/Users/mba/.codex/config.toml` の `personality = "pragmatic"`

取得日時点の `/Users/mba/.codex/models_cache.json` では `gpt-5.6-sol` に `model_messages.instructions_template` がある。これは 2026-07-17 取得の cache であり、2026-07-14 の欠落を反証しない。現在値を過去値として扱わない。

判定: **非致命的 WARN**。ただし base instructions へ落ちるため、期待した personality 固有 instruction が適用されない品質リスクはある。

### 3. plugin / skill loader の icon path 警告

対象ログ:

```text
WARN codex_core_skills::loader: ignoring interface.icon_small:
icon path with '..' must resolve under plugin assets/
WARN codex_core_skills::loader: ignoring interface.icon_large:
icon path with '..' must resolve under plugin assets/
```

各 run で `icon_small` / `icon_large` が2巡し、4件ずつ出た。loader source は絶対 path、assets 外、plugin root を安全に解決できない `..` 等を WARN にし、その icon metadata だけを `None` にする。skill / plugin 本体の load は継続する。

- 固定 source: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/core-skills/src/loader.rs
- 固定 tests: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/core-skills/src/loader_tests.rs

| issue | icon WARN | 直後の継続証拠 |
|---|---:|---|
| #1969 | 4 | 10:23以降も tool call、patch、model event が継続 |
| #1801 | 4 | 10:25:45 / 10:27:52 に analytics event |
| #1976 | 4 | 10:33以降も tool call、model event が継続 |

対象時点の plugin cache は既に更新・整理されており、取得日時点の cache 検索から当時の不正 manifest を一意に復元できなかった。

判定: **非致命的 WARN**。表示 icon が欠落する。path traversal を許可する修正は不可で、plugin assets 配下へ asset を置き manifest を直すべきである。

### 4. Codex analytics / telemetry 送信失敗

対象ログ:

```text
WARN codex_analytics::client: failed to send events request:
error sending request for url
(https://chatgpt.com/backend-api/codex/analytics-events/events)
```

| issue | 回数 | 観測時刻 UTC |
|---|---:|---|
| #1969 | 5 | 10:23:36, 10:23:46, 10:23:56, 10:24:32, 10:31:12 |
| #1801 | 2 | 10:25:45, 10:27:52 |
| #1976 | 4 | 10:33:09, 10:35:51, 10:36:06, 10:36:24 |

Codex analytics client source は HTTP non-2xx と transport failure を WARN して return し、agent turn へ例外を再送出しない。したがって analytics delivery は補助経路である。

- 固定 source: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/analytics/src/client.rs
- 固定 tests: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/analytics/src/client_tests.rs

ログには HTTP status、DNS、connect timeout、retry-after、送信量がない。`429` や API rate limit 文字列も対象3 run の failure blockにはない。ネットワーク競合や rate limit を原因とは判定できない。

判定: **非致命的 WARN**。analytics 欠測は起き得るが、Codex model API 自体の失敗証拠ではない。

### 5. SQLite slow query

#1969 と #1976 の起動直後に各1件ある。

```text
#1969 2026-07-14T10:22:53.860131Z
SELECT MAX(threads.updated_at_ms), MAX(threads.recency_at_ms) FROM threads
rows_returned=1 elapsed=2.734329833s slow_threshold=1s

#1976 2026-07-14T10:32:35.905630Z
SELECT MAX(threads.updated_at_ms), MAX(threads.recency_at_ms) FROM threads
rows_returned=1 elapsed=2.625871s slow_threshold=1s
```

Codex v0.144.1 state runtime は WAL、`synchronous=NORMAL`、busy timeout 5秒を設定する。

- 固定 source: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/codex-rs/state/src/runtime.rs

同 source はstatement loggingを明示的に有効化しておらず、`slow statement`文字列もCodex repository内にない。対象stderrがCodex processから来たことは確かだが、警告を発火したsqlx側の閾値設定箇所までは版固定sourceから特定できなかった。

対象ログに `SQLITE_BUSY`、`database is locked`、pool acquire timeout、write failure はない。2.6–2.7秒の read が1秒閾値を超えた事実だけがある。#1801 には同警告がなく、#1969 / #1976 もその後数分間進行した。

判定: **非致命的 WARN**。DB lock、I/O競合、CPU飽和のいずれかをこのログだけで選べない。

### 6. TAKT telemetry / observability wrapper

対象時点の global config `/Users/mba/.takt/config.yaml` は次を有効化していた。

```yaml
observability:
  enabled: true
  monitor: true
  session_log_exporter: true
  usage_events_phase: true
logging:
  usage_events: true
```

TAKT は Codex 子 process へ nested observability 用 env snapshot を渡す。

- `/Users/mba/.bun/install/global/node_modules/takt/dist/shared/telemetry/childProcessEnv.js`
- `/Users/mba/.bun/install/global/node_modules/takt/dist/infra/codex/client.js`

ただし対象 worktree / `.takt/runs/<run_slug>` は取得日時点で削除済みで、対象 run の monitor / usage event 全量は回収不能。task ledger に stderr の代表 warning は残ったが、CPU / RSS / DB wait / network latency の時系列は残っていない。

### 7. ログレベルと致命性の分離

| 事象 | 実ログ level | runtime 動作 | 判定 |
|---|---|---|---|
| plugin icon path | WARN | icon metadataを無視、load継続 | 非致命 |
| analytics send failure | WARN | warn後return | 非致命、telemetry欠測 |
| personality missing | WARN | base instructionsへfallback | 非致命、instruction品質リスク |
| SQLite slow query | WARN | queryは結果1行を返して継続 | 非致命、性能兆候 |
| `timeout_ms < 10000` | ERROR/tool response | 当該waitだけ拒否 | 局所的入力エラー |
| `apply_patch` verify | ERROR/tool response | 当該patch非適用 | 局所的編集エラー |
| `Codex Exec exited with signal SIGTERM` | task failure | worker終了、task failed | **致命的 terminal cause** |

## 主要な発見のサマリー

1. Codex worker は TAKT PID 13771 の子 process として起動し、SDKの `AbortSignal` 経路を持つ。
2. personality、icon、analytics、SQLite はすべて WARN で、各警告後も tool / stream event が続いた。
3. analytics failure は model API failure ではなく、analytics-events endpoint への補助送信失敗である。
4. SQLite は2件の遅い read を観測したが、lock error は0件である。
5. runtime warning 群をSIGTERMの直接原因にする証拠はない。

## 注意点・リスク

- task ledger の `failure.error` は terminal SIGTERM と、それ以前の stderr warning を1文字列へ連結する。末尾に併記された WARN を原因と誤認しやすい。
- 2026-07-17 の model cache / plugin cache は、2026-07-14 の状態を上書きしている可能性がある。
- analytics の status code がないため、ネットワーク断、DNS、server error、rate limit を分類できない。
- SQLite slow query は性能兆候だが、CPU / I/O / lock waitの内訳がない。

## 調査できなかった項目と理由

1. **当時の不正 icon manifest の一意な plugin名**: cacheが更新済みで、警告にplugin id/pathがない。
2. **analytics送信失敗のHTTP status / retry回数**: stderrに記録なし。
3. **personality用model message欠落の配信payload**: 当時のmodel cache snapshotがない。
4. **SQLiteのlock wait / I/O wait**: query elapsedだけで、wait breakdownや`SQLITE_BUSY`がない。
5. **対象 run の monitor / usage-event全量**: worktreeとrun directoryが削除済み。

## 推奨／結論

変更候補と検証契約は次の通り。これは調査結果であり、実装は行っていない。

| 対象 | 推奨 | テスト / 受け入れ条件 | ロールバック |
|---|---|---|---|
| Codex plugin manifest / loader | warningへplugin id・manifest pathを付与。iconはplugin assets内の相対pathだけ許可 | 不正`../`でplugin本体はload、iconだけNone、警告にsource idが出る | logging field追加を戻す。path安全性は緩和しない |
| analytics client | status / error class / attempt / elapsedをsecret-free fieldでWARN記録 | delivery失敗でもturn成功。429/5xx/transportを区別 | 詳細fieldだけ無効化、fail-soft契約維持 |
| model resolution | model slug、cache generation、fallback reasonを1回に集約 | template欠落でbase instruction採用、turn継続、同一turnの重複WARN抑制 | dedupeを戻し従来WARNへ |
| state DB | query名、elapsed、busy count、pool acquire timeをmetric化 | `SQLITE_BUSY=0` とquery p95を判別可能。agent turnを阻害しない | exporter無効化で従来logのみへ |
| TAKT task failure persistence | terminal failureとstderr diagnosticsを別fieldで保存 | `failure.kind=signal_termination` とWARN配列を別々に照会できる | new fields optional、旧`error`併記 |

結論: 対象3件の fatal cause は SIGTERM であり、runtimeのWARN群ではない。優先すべきは警告抑止より、signal reasonとresource telemetryをterminal recordへ構造化保存することである。
