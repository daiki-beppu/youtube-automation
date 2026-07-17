# TAKT 同時実行・SIGTERM・resource時系列調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象 wave: 2026-07-14 wave 4
- 対象 issue: #1969 / #1801 / #1976
- TAKT: `0.51.0` (`90ecdfb893909979c92f550f3730393502e6fde8`)
- Codex SDK: `0.144.1` (`44918ea10c0f99151c6710411b4322c2f5c96bea`)

代表抽出コマンドと出力:

```text
$ takt --version
0.51.0
$ git log --format='%H %ad %s' --date=iso -- .takt/config.yaml | head -1
e128d2cae9273277dc64bf0ae20d72b4264ca37a 2026-07-16 17:03:03 +0900 chore(takt): concurrency 5 を恒久設定化
$ git show e128d2ca^:.takt/config.yaml | rg 'concurrency|task_poll'
(出力なし: 対象時点のproject overrideなし)
```

## 調査項目ごとの結果と詳細

### 1. 3件の時系列比較

`.takt/tasks.yaml` の実 timestamp から算出した。GitHub comment時刻は運用説明の投稿時刻で、elapsed計算には使っていない。

| issue | created UTC | started UTC | completed UTC | 実elapsed | 最終event→終了 | step | terminal |
|---|---|---|---|---:|---:|---|---|
| #1801 | 10:20:43.563 | 10:22:46.355 | 10:28:13.045 | 5m26.690s | 20.413s | implement 2/12 | SIGTERM |
| #1969 | 10:20:09.529 | 10:22:45.995 | 10:37:57.916 | 15m11.921s | 4.561s | implement 1/9 | SIGTERM |
| #1976 | 10:20:52.317 | 10:28:13.069 | 10:38:53.511 | 10m40.442s | 0.506s | implement 3/9 | SIGTERM |

#1801 完了から #1976 開始までは `24ms`。TAKT worker poolが空いたslotを即補充した時系列と一致する。

一次情報:

- ledger: `/Users/mba/02-yt/00-automation/.takt/tasks.yaml`
- #1801: https://github.com/daiki-beppu/youtube-automation/issues/1801#issuecomment-4968167170
- #1969: https://github.com/daiki-beppu/youtube-automation/issues/1969#issuecomment-4968245082
- #1976: https://github.com/daiki-beppu/youtube-automation/issues/1976#issuecomment-4968250622

issue commentは全件、workflow再監査による意図的停止、部分差分不採用、PR化なしを記録する。ただしGitHubだけにはPID、signal sender、timeout値はない。signal senderの確定には次のローカル一次ログを使う。

### 2. 同時実行数とslot補充

対象時点のproject `.takt/config.yaml` は `concurrency` をoverrideしておらず、global `/Users/mba/.takt/config.yaml` の `concurrency: 3`、`task_poll_interval_ms: 500` を継承していた。

現在のproject `concurrency: 5` は対象後のcommitである。

```text
e128d2cae9273277dc64bf0ae20d72b4264ca37a
2026-07-16 17:03:03 +0900
chore(takt): concurrency 5 を恒久設定化
```

`git show e128d2ca^:.takt/config.yaml` にconcurrencyはない。現在値5を2026-07-14へ遡及適用してはならない。

TAKT `runWithWorkerPool()` はactive数がconcurrency未満ならqueueからfillし、task完了またはpoll tick後に `freeSlots = concurrency - active.size` を計算し `claimNextTasks(freeSlots)` する。claimはtasks.yamlの先頭pendingをrunningへ変える。

- worker pool: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/execute/parallelExecution.ts
- lifecycle: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/taskLifecycleService.ts
- config schema `concurrency=1..10`: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/core/models/config-schemas.ts

実process snapshot:

```text
10:28:06.934Z active=3
22286 -> #1969
51147 -> #1801
98783 -> #1939

10:28:12.975Z parent operation: kill -TERM 51147
10:28:13.045Z #1801 completed failed
10:28:13.069Z #1976 started

10:32:45.087Z active=3
22286 -> #1969
30576 -> #1939 (次persona/stepのworker)
62906 -> #1976
```

生ログ: `/Users/mba/.codex/archived_sessions/rollout-2026-07-14T16-16-11-019f5f7b-b6fe-76a3-90b3-5dcb94b6ce01.jsonl`

### 3. 親processとSIGTERM送信元

TAKT親process:

```text
2026-07-14T10:23:10.665Z
PID 13771 ELAPSED 00:26 STAT Ss+ node /Users/mba/.bun/bin/takt -q run
```

親運用sessionは次を実行した。

```text
2026-07-14T10:28:12.975Z kill -TERM 51147                       #1801
2026-07-14T10:37:57.701Z pgrep -P 13771 -f '1969-issue-1969'; kill -TERM "$pid"
2026-07-14T10:38:53.291Z pgrep -P 13771 -f '1976-issue-1976'; kill -TERM "$pid"
```

#1969は事前snapshotでPID22286、#1976は10:32:45 snapshotでPID62906。ただし後2件のkill commandは展開後PIDをstdoutへ出していない。PPID + issue固有cwdの選択条件、直後の当該task failureでtarget identityは確定できるが、signal瞬間の数値PIDはログ出力されていない。

判定: 対象3件の直接停止入力は親運用sessionの明示的な個別`kill -TERM`。TAKT shared SIGINTやidle timeoutが送信したSIGTERMではない。

### 4. SDK / AbortSignal の一般経路

一般にはTAKTのexternal abortでも同じ文字列を作れる。

1. TAKT providerが`AbortSignal`をCodex SDKへ渡す。
2. SDKが`spawn(..., {signal})`する。
3. Node child processのAbortSignalは`.kill()`相当で、`killSignal`既定はSIGTERM。
4. SDKがexit signalを`Codex Exec exited with signal SIGTERM`へ整形する。

出典:

- TAKT provider: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/providers/codex.ts
- TAKT client: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/codex/client.ts
- Codex SDK: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/sdk/typescript/src/exec.ts
- Codex SDK abort tests: https://github.com/openai/codex/blob/44918ea10c0f99151c6710411b4322c2f5c96bea/sdk/typescript/tests/abort.test.ts
- Node.js: https://nodejs.org/api/child_process.html#child_processspawncommand-args-options

これは「同じerror文字列を作る一般経路」であり、今回の直接原因ではない。raw SIGTERM文字列だけでは外部kill、AbortSignal、timeout、OOM等を区別できない。

### 5. timeoutと終了条件の比較

| 終了条件 | 値 | signal / terminal | 対象3件との整合 |
|---|---:|---|---|
| Codex stream idle | eventなし10分、最大2 retry | stream AbortSignal | 不整合。全件終了0.5–20.4秒前にevent |
| command quality gate | 既定300秒 | process group SIGTERM→100ms後SIGKILL | 対象はquality gate commandでなくCodex workerへの直接kill |
| team leader part timeout | workflow設定値 | part timeout分類 | 証拠なし |
| graceful SIGINT | interactive 10秒 / noninteractive 5秒 | shared abort、全active settle | 個別停止と後続slot補充に不整合 |
| forced SIGINT | 2回目または期限 | process exit 130 | 観測なし |
| 親運用個別kill | 明示操作時刻 | 対象worker SIGTERM | **時系列・targetとも一致** |

### 6. CPU、memory、DB lock、API rate limit、network競合

要求された資源について、取得可能な時系列値だけを示す。

| 資源 | 取得できた値 | 判定 |
|---|---|---|
| process concurrency | 10:28:06と10:32:45にCodex child 3件 | 当時設定3と一致 |
| process state | 対象workerは`S+`、elapsedあり | sleeping stateのみ。CPU飽和を示さない |
| CPU % / load average | **値なし** | 計測不足。原因推測不可 |
| RSS / memory pressure / swap | **値なし** | 計測不足。OOM推測不可 |
| DB query elapsed | #1969 2.734329833s、#1976 2.625871s、閾値1s | slow readは事実 |
| DB lock / busy count | `SQLITE_BUSY` / `database is locked` 0件、wait値なし | lock原因とは判定不可 |
| API 429 / Retry-After | 0件、status値なし | rate limit原因とは判定不可 |
| analytics network | send WARN: #1969=5、#1801=2、#1976=4 | telemetry endpoint失敗。model API競合の証拠ではない |
| network latency / packet loss / DNS | **値なし** | 計測不足 |
| worktree disk usage | 10:25 #1801=25M / #1969=22M、10:32 #1969=659M / #1976=25M | disk使用量のみ。CPU/memory原因には使わない |

資源値がない箇所は推測しない。特に「concurrency 3だからCPU不足」「slow queryだからDB lock」「analytics failureだからnetworkがSIGTERMを誘発」は、いずれも証拠不足である。

### 7. 状態遷移と終了後

3件とも:

```text
pending -> running(implement) -> failed(SIGTERM)
```

#1976だけは`pending(waiting for slot)`から#1801終了24ms後に自動claimされた。TAKT task recordにはpending cancel tombstoneやtask-local cancel APIがなく、shared abortは全active向けである。

stale `running` taskは次回起動時、owner PID不在なら`failed`へ倒し、明示requeueを要求する。

- source: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/taskLifecycleService.ts

## 主要な発見のサマリー

1. 対象時点の同時実行数は3。現在のproject値5は2日後の変更である。
2. #1801終了から24ms後に#1976がslot補充で起動した。
3. 対象3件の直接原因は親運用sessionから対象workerへの個別`kill -TERM`。
4. 全件終了直前にeventがあり、10分idle timeoutではない。
5. CPU、memory、DB lock、API rate、network latencyの時系列値はなく、原因推測はできない。
6. SQLite slow readとanalytics送信WARNは観測したが、terminal causeではない。

## 注意点・リスク

- GitHub issue/commentだけではsignal senderや実elapsedは証明できない。ローカルarchived sessionとledgerが必要。
- `failure.error`はSIGTERMとstderr warningを連結し、causal orderingを表現しない。
- #1976の開始前cancel requestは一次ログにない。「遅延interrupt」とは判定しない。
- process snapshotの`S+`はCPU使用率0を意味しない。snapshotに`%CPU/%MEM`列がない。
- OOMなら通常SIGKILL等もあり得るが、対象ログにkernel/OOM eventはない。OOMを除外確定も原因認定もできない。

## 調査できなかった項目と理由

1. **CPU / load / RSS / memory pressureの時系列**: 当時の`ps`に該当列がなく、`vm_stat`等も未実行。
2. **DB lock wait breakdown**: slow query elapsedのみ。lock/busy metricなし。
3. **API rate limit status**: HTTP status / Retry-After未記録。
4. **network latency / packet loss**: telemetryなし。
5. **#1969 / #1976 signal瞬間の展開後PID**: shell変数値をstdoutへ出していない。
6. **対象runのmonitor / trace全量**: worktree / run directory削除済み。
7. **kernel signal audit**: sender syscall auditを取得していない。ただし送信command自体はarchived sessionで確認済み。

## 推奨／結論

### 対象ファイル・設定・関数の変更候補

| 対象 | 変更候補 |
|---|---|
| `src/infra/task/taskRecordSchemas.ts` | `cancel_requested_at`, `cancel_reason`, `failure.kind`, signal、requested/effective timestampをoptional追加 |
| `src/infra/task/taskLifecycleService.ts` | pending cancel tombstone、running task-local cancel request、claim除外 |
| `src/features/tasks/execute/parallelExecution.ts` | active mapへtaskごとのAbortControllerを保持 |
| `src/features/tasks/execute/taskExecution.ts` | task-local reasonをproviderとledgerへend-to-end伝播 |
| `src/infra/codex/client.ts` | raw SDK errorよりstructured abort causeを優先保存 |
| observability exporter | 5–10秒間隔でPID、CPU%、RSS、load、DB busy/p95、API status class、network elapsedを記録 |
| project config | concurrency値と取得元(global/project/env)をrun metaへsnapshot |

### 入力検証

- `concurrency`は既存どおりinteger 1–10。
- cancel targetはtask name + current run_slug一致を必須にし、別runのPIDを止めない。
- pending cancelはprovider call前にterminal化。
- running cancelはtask-local controllerだけをabortし、他active taskへ伝播させない。
- PIDを使う場合はPPID、cwd、run_slugの3点照合後にsignal送信。

### ログlevel

- user/task cancel request: INFO + structured audit。
- idle timeout / provider retry: WARN。
- terminal signal reason不明: ERROR `signal_termination_unknown`。
- CPU/RSS sample: metric/DEBUG。閾値超過だけWARN。
- analytics delivery failure: WARNのままterminal failureへ混ぜない。

### テスト

1. concurrency 3、4番目pendingをcancel後、slotが空いてもprovider call数0。
2. running 1件だけcancelし、他2件は継続。
3. #1801型のslot補充で、cancel tombstone済み#1976をclaimしない。
4. external abort、stream idle、part timeout、direct SIGTERMを別`failure.kind`で保存。
5. eventが終了0.5秒前にあればidle timeout分類しない。
6. resource sampler欠測時は`unknown`で、0として扱わない。
7. old tasks.yamlを新readerが読める。

### 受け入れ条件

- terminal recordだけでsignal source category、request/effective時刻、signal、target runを追跡できる。
- pending cancelされたtaskのprovider callが0。
- task-local cancelが他workerを停止しない。
- run metaに実効concurrencyと設定provenanceが保存される。
- CPU/RSS/DB/API/networkが未計測なら明示`not_measured`、推測値を生成しない。

### ロールバック

- structured fieldはoptional、旧`error`を併記してreader互換を維持。
- task-local cancelはfeature flagで無効化し、shared Ctrl+C経路を維持。
- `cancelled` status追加より、まず既存`failed` + `failure.kind=user_interrupt`で互換性を優先。
- resource samplerは独立flagで停止可能にし、task executionを依存させない。

結論: timeout延長やconcurrency低下を先に行う根拠はない。最優先は個別cancelの永続化、abort sourceの構造化、resource時系列の計測である。
