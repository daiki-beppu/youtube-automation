# TAKT interrupt / timeout / 実行キュー調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 調査対象: TAKT 0.51.0、automation リポジトリの 2026-07-14 wave 4、issue #1969 / #1801 / #1976
- TAKT 0.51.0 の固定点: tag `v0.51.0` = commit `90ecdfb893909979c92f550f3730393502e6fde8`
- ローカル実体: `/Users/mba/.bun/install/global/node_modules/takt/`（`takt --version` は `0.51.0`）
- 主な一次情報:
  - TAKT source: https://github.com/nrslib/takt/tree/90ecdfb893909979c92f550f3730393502e6fde8
  - OpenAI Codex SDK 0.144.1 `exec.ts`: https://github.com/openai/codex/blob/rust-v0.144.1/sdk/typescript/src/exec.ts
  - Node.js `child_process`: https://nodejs.org/api/child_process.html
  - 親運用セッション生ログ: `/Users/mba/.codex/archived_sessions/rollout-2026-07-14T16-16-11-019f5f7b-b6fe-76a3-90b3-5dcb94b6ce01.jsonl`
  - ローカル task ledger: `/Users/mba/02-yt/00-automation/.takt/tasks.yaml`
  - ローカル運用記録: `/Users/mba/02-yt/00-automation/.codex/takt-open-issues-execution-notes.md`

以下では「事実」と「推測／判断」を分離する。URL は取得日時点で閲覧した一次情報、絶対パスは取得日時点のローカル証跡である。

## 調査項目ごとの結果と詳細

### 1. signal と Codex 子プロセスの SIGTERM 発生経路

#### 事実

TAKT の Codex provider は `CodexClient` に `AbortSignal` を渡す。

- `src/infra/providers/codex.ts::toCodexOptions`: provider の `options.abortSignal` を Codex 呼び出しへ転送する。
  - 固定 URL: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/providers/codex.ts
- `src/infra/codex/client.ts::call`: 外部 signal の abort で `abortCause = 'external'` とし、stream 用 controller を abort する。10 分無通信の場合は `abortCause = 'timeout'` とする。
  - 条件式（抜粋）: `abortCause = 'external'` / `streamAbortController.abort(options.abortSignal?.reason)`
  - timeout 定数: `CODEX_STREAM_IDLE_TIMEOUT_MS = 10 * 60 * 1000`
  - timeout retry 上限: `CODEX_TIMEOUT_MAX_RETRIES = 2`
  - external abort は retry しない。`shouldRetry` が再試行するのは stream idle timeout、または retriable provider error だけである。
  - 固定 URL: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/codex/client.ts
- `@openai/codex-sdk` 0.144.1 は `spawn(..., { signal: args.signal })` で Codex CLI を子プロセス起動し、終了 signal を `Codex Exec exited with signal ...` に整形する。
  - ローカル配布物: `/Users/mba/.bun/install/global/node_modules/@openai/codex-sdk/dist/index.js`
  - 固定 URL: https://github.com/openai/codex/blob/rust-v0.144.1/sdk/typescript/src/exec.ts
- Node.js の公式仕様では `AbortSignal` による child process abort は `.kill()` 相当で、`killSignal` の既定値は `SIGTERM` である。
  - 出典: https://nodejs.org/api/child_process.html#child_processspawncommand-args-options

既存条件への最小再現を実施した。ファイル変更はない。

```text
$ node --input-type=module -e '<AbortSignal を渡して子 Node process を起動し 50ms 後に abort>'
error AbortError ABORT_ERR
exit {"code":null,"signal":"SIGTERM"}
```

したがって、TAKT から Codex SDK へ渡した signal が abort されると、観測された `Codex Exec exited with signal SIGTERM` を再現できる。

一方、TAKT の clone 準備中 git command は別経路である。`src/infra/task/clone-exec.ts::runGitCommandAbortable` は abort 時に process group へまず `SIGINT`、500ms 後も未終了なら `SIGKILL` を送る。対象 3 件の文字列はこの git 経路ではなく Codex Exec 経路である。

- 固定 URL: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/clone-exec.ts

親運用セッションの archived JSONL に signal sender command が残っていたため、対象 3 件についてはさらに発生元を確定できた。

```text
# archive line 3243
22286 13771 ... codex ... --cd .../20260714T1022-1969-...
51147 13771 ... codex ... --cd .../20260714T1022-1801-...
98783 13771 ... codex ... --cd .../20260714T1022-1939-...

# archive line 3246, 2026-07-14T10:28:12.975Z
kill -TERM 51147

# archive line 3406, 2026-07-14T10:37:57.701Z
pid=$(pgrep -P 13771 -f '1969-issue-1969' || true)
... kill -TERM "$pid"

# archive line 3424, 2026-07-14T10:38:53.291Z
pid=$(pgrep -P 13771 -f '1976-issue-1976' || true)
... kill -TERM "$pid"
```

`takt -q run` の PID は 13771。親運用セッションはその直下の Codex worker を PID、PPID、issue 固有 worktree cwd で識別し、直接 `kill -TERM` を送った。#1801 は PID 51147、#1969 は直前の process 一覧で PID 22286。#1976 の実 PID 値は変数展開後の値を出力していないが、PPID + issue 固有 cwd の選択条件と直後の failed 出力により対象 worker は確定する。

#### 推測／判断

この 3 件に限れば、OS 上の送信主体は外部の親運用セッションによる明示的 `kill -TERM` と確定した。TAKT の AbortSignal / SDK timeout が SIGTERM を送ったのではない。上記 AbortSignal 経路は同じ error 文字列を作れる一般経路の再現であり、今回の直接原因ではない。

### 2. Ctrl+C、graceful shutdown、全体並列実行

#### 事実

`src/features/tasks/execute/parallelExecution.ts::runWithWorkerPool` は全 worker で 1 個の共有 `AbortController` を使う。

- 1 回目の SIGINT: `ShutdownManager.onGraceful` が共有 controller を abort する。
- controller abort 後: 新しい task を slot へ入れず、in-flight promise の settle を待つ。
- 2 回目の SIGINT、または graceful timeout: `process.exit(130)`。
- graceful timeout: TTY は 10,000ms、`TAKT_NO_TTY=1` は 5,000ms。`TAKT_SHUTDOWN_TIMEOUT_MS` で正整数 override 可。
- 固定 URL:
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/execute/parallelExecution.ts
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/execute/shutdownManager.ts

各 task は `executeTaskAndCompleteWithDetails` 内で task-local controller を作るが、その abort source は worker pool の共有 external signal だけである。

```text
externalAbortSignal -> taskAbortController.abort()
                    -> workflow AbortHandler
                    -> CodexClient streamAbortController
                    -> Node child_process SIGTERM
```

TAKT 0.51.0 の CLI task management に、実行中の特定 task だけへ abort signal を送る API はない。`takt list` の `forceFailRunningTask` は ledger を `failed` に書き換えるが、owner process や Codex child を signal しない。

- 固定 URL: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/list/taskForceFailActions.ts

#### 推測／判断

wave 4 は同一 persistent `takt run` / concurrency 3 だった。共有 SIGINT なら #1969 と #1801 の両方が abort され、#1976 を新規開始しない。実際の個別停止が直接 `kill -TERM` だったことは archived session で確定しており、この時系列と完全に一致する。

### 3. 実行キュー、slot 補充、実行前 interrupt の遅延確定

#### 事実

2026-07-14 時点の project config は `concurrency` を override しておらず、`/Users/mba/.takt/config.yaml` の `concurrency: 3` と `task_poll_interval_ms: 500` を継承していた。project で `concurrency: 5` を固定した commit は 2026-07-16 の `e128d2cae9273277dc64bf0ae20d72b4264ca37a` で、対象 wave より後である。

`runAllTasks` は起動時に `claimNextTasks(concurrency)` を呼ぶ。worker pool は、task 完了または poll tick のたびに空き slot 数を計算し、`claimNextTasks(freeSlots)` で `.takt/tasks.yaml` 上の先頭の `pending` を `running` にする。

- `claimNextTasks` の条件: `remaining > 0 && task.status === 'pending'`
- task schema の status: `pending | running | completed | failed | exceeded | pr_failed`
- `cancelling` / `cancel_requested` / `interrupted` status、cancel generation、`interrupt_requested_at` は存在しない。
- 固定 URL:
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/execute/runAllTasks.ts
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/execute/parallelExecution.ts
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/taskLifecycleService.ts
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/taskRecordSchemas.ts

対象 wave の運用記録は、#1969 / #1939 / #1801 が最初の 3 slot、#1976 が pending で「slot が止まると自動開始」と明記する。

- 絶対パス: `/Users/mba/02-yt/00-automation/.codex/takt-open-issues-execution-notes.md:62`

#1801 と #1976 の ledger timestamp は次の通りである。

| event | UTC timestamp |
|---|---:|
| #1801 completed_at | 2026-07-14 10:28:13.045 |
| #1976 started_at | 2026-07-14 10:28:13.069 |
| 差 | 24ms |

500ms poll を待たず 24ms で slot が補充されたのは、worker pool が task completion 後にも即座に空き slot を補充する実装と一致する。

#1976 は 10:28:13.069 に始まり、10:38:53.511 に failed となった（10分40.442秒）。issue の停止記録は 10:39:10Z に投稿された。

- task ledger: `/Users/mba/02-yt/00-automation/.takt/tasks.yaml:642`
- issue comment: https://github.com/daiki-beppu/youtube-automation/issues/1976#issuecomment-4968250622

#### 推測／判断

TAKT ledger に開始前 cancel intent を保存する字段がないため、仮に外部で停止予定にしても slot が空いた瞬間の claim は防げない。ただし今回の一次ログには、#1976 を開始前に interrupt request した事実はない。親運用セッションは #1801 を kill した直後に #1976 が clone 開始したことを line 3247 で観測し、その後 #1976 を監査して 10:38:53.291Z に個別 kill している。

したがって「実行前 interrupt がTAKT内部で遅延伝播した」とは判定しない。確定したのは、(1) #1976 が pending から自動 claim された、(2) #1801 完了から 24ms 後だった、(3) 親セッションが開始を観測した後も監査を続け、10分40秒後に明示的 kill した、の 3 点である。遅延は signal propagation ではなく、空き slot の即時補充と後続の運用判断による。

### 4. 中断後の状態確定と再投入

#### 事実

起動時 recovery は `TaskLifecycleService.failInterruptedRunningTasks()` が行う。

- 対象条件: status が `running`、かつ `owner_pid` がないか `process.kill(ownerPid, 0)` で process 不在。
- 更新先: `failed`
- 固定 error: `Task was interrupted before this TAKT run started. Requeue it explicitly to run again.`
- retry metadata: run の `resume_point` / `startStep` を可能なら保持する。
- `takt run` と `takt watch` の次回起動時に実行される。
- 固定 URL:
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/taskLifecycleService.ts
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/process.ts
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/features/tasks/execute/runAllTasks.ts

再投入は自動ではない。docs と error が明示する通り、利用者が `requeue` する必要がある。requeue は pending に戻し retry note を追記するが、「中断なので自動 retry」の扱いにはしない。

TAKT の task record schema には親 task id / 子 task id がない。system workflow の `enqueue_task` effect は独立 task を作成し、返り値として `taskName` 等を返すが、親子 edge を task record へ保存しない。GitHub sub-issue の親子関係も TAKT task schema とは別管理である。

- 固定 URL:
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/workflow/system/system-enqueue-effect.ts
  - https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/infra/task/taskRecordSchemas.ts

#### 推測／判断

起動時 recovery error の「before this TAKT run started」は「前回 run のどこで中断したか」ではなく、「今回 run 開始時に stale running と判定した」という意味である。これを実行前 interrupt の証拠と読むのは誤りである。

親子 edge がないため、親の abort 時に未開始の子を cancel、または子だけ requeue する整合性ルールは実装できない。現状は task 単位の独立 queue として扱う必要がある。

### 5. timeout の種類と retry 分類

#### 事実

| timeout / signal | 入力 | 現行動作 | retry |
|---|---|---|---|
| Codex stream idle | 10分間 stream event なし | stream signal abort、`stream_idle_timeout` | 最大2回 |
| external abort | 上位 `AbortSignal` | Codex stream abort、`external_abort` | なし |
| team leader part timeout | `team_leader.timeout_ms` 由来の signal reason | `part_timeout` | provider retry なし、leader fallback 側で扱う |
| command quality gate | `timeout_ms`、省略時300,000ms | process groupへ SIGTERM、のち SIGKILL、同 step へ failure | workflow step の差し戻し規則次第 |
| graceful shutdown | SIGINT 1回 | 共有 controller abort、in-flight settle 待ち | なし |
| forced shutdown | SIGINT 2回、または5/10秒経過 | process exit 130 | 次回起動時 stale running を failed 化 |
| clone git abort | task abort signal | group SIGINT、500ms後 SIGKILL | task failure |

command gate の既定値:

- `/private/tmp` に取得した固定 source の `src/core/models/quality-gate-defaults.ts`
- 固定 URL: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/core/models/quality-gate-defaults.ts

Codex external abort / part timeout の分類は既存テストで固定されている。

- `src/__tests__/codex-client-retry.test.ts`: external abort は retry なしで `external_abort`、part timeout は `part_timeout`。
- 固定 URL: https://github.com/nrslib/takt/blob/90ecdfb893909979c92f550f3730393502e6fde8/src/__tests__/codex-client-retry.test.ts

#### 推測／判断

provider 層には分類があるが、対象 task ledger では最上位 error が raw `Codex Exec exited with signal SIGTERM` に戻っており、`external_abort` の構造化 category や signal reason が task failure に保存されていない。分類の生成と永続化の間に observability gap がある。

### 6. issue #1969 / #1801 / #1976 の代表ログから遷移を再構築

#### #1801

一次記録:

- issue: https://github.com/daiki-beppu/youtube-automation/issues/1801
- 停止 comment: https://github.com/daiki-beppu/youtube-automation/issues/1801#issuecomment-4968167170
- ledger: `/Users/mba/02-yt/00-automation/.takt/tasks.yaml:570`

```text
created_at   2026-07-14 10:20:43.563 UTC
started_at   2026-07-14 10:22:46.355 UTC
run_slug     20260714-102250-implement-using-only-the-files-bpshpc
step         implement
last log     2026-07-14T10:27:52.631869Z analytics send warning
completed_at 2026-07-14 10:28:13.045 UTC
failure      Codex Exec exited with signal SIGTERM
comment      2026-07-14T10:28:50Z: implement 2/12 で workflow 不一致のため停止
```

遷移: `pending -> running(implement) -> failed(SIGTERM)`。停止時差分 2 files は不採用、PR なし。

判断: 終了の約20.4秒前に出力があるので 10分 idle timeout ではない。issue comment と整合する意図的停止である。

#### #1969

一次記録:

- issue: https://github.com/daiki-beppu/youtube-automation/issues/1969
- 停止 comment: https://github.com/daiki-beppu/youtube-automation/issues/1969#issuecomment-4968245082
- ledger: `/Users/mba/02-yt/00-automation/.takt/tasks.yaml:420`

```text
created_at   2026-07-14 10:20:09.529 UTC
started_at   2026-07-14 10:22:45.995 UTC
run_slug     20260714-102249-implement-using-only-the-files-39xkid
step         implement
last log     2026-07-14T10:37:53.354727Z model warning
completed_at 2026-07-14 10:37:57.916 UTC
failure      Codex Exec exited with signal SIGTERM
comment      2026-07-14T10:38:26Z: implement 1/9 で workflow 不一致のため停止
```

遷移: `pending -> running(implement) -> failed(SIGTERM)`。8 modified + 新規 skill directory は不採用、PR なし。

判断: 終了の約4.6秒前に出力があるので 10分 idle timeout ではない。

#### #1976

一次記録:

- issue: https://github.com/daiki-beppu/youtube-automation/issues/1976
- 停止 comment: https://github.com/daiki-beppu/youtube-automation/issues/1976#issuecomment-4968250622
- ledger: `/Users/mba/02-yt/00-automation/.takt/tasks.yaml:642`

```text
created_at   2026-07-14 10:20:52.317 UTC
started_at   2026-07-14 10:28:13.069 UTC (#1801 完了の24ms後)
run_slug     20260714-102816-implement-using-only-the-files-ounsvj
step         implement
last log     2026-07-14T10:38:53.004506Z model warning
completed_at 2026-07-14 10:38:53.511 UTC
failure      Codex Exec exited with signal SIGTERM
comment      2026-07-14T10:39:10Z: implement 3/9 で workflow 不一致のため停止
```

遷移: `pending(waiting for slot) -> running(implement) -> failed(SIGTERM)`。5 files の差分は不採用、PR なし。

判断: 終了の約0.5秒前に出力があるので 10分 idle timeout ではない。開始前 cancel tombstone がないため、空き slot への自動投入を防げなかったケースとして説明できる。

#### 停止 run の PR / CI と #1976 の後続親子関係

停止した #1969 / #1801 / #1976 run 自体に対応する commit、PR、CI は 0 件である。各 owner comment が部分差分を不採用・PR化なしと明記し、GitHub の closing PR も存在しない。

#1976 は 2026-07-15 に tracking parent (`takt:manual`) へ変更され、実装を次の sub-issue へ分割した。これは GitHub issue の親子関係であり、TAKT task record の lineage ではない。

| sub-issue | PR | merge commit | Actions run | 取得日時点の checks |
|---|---|---|---|---|
| [#2062](https://github.com/daiki-beppu/youtube-automation/issues/2062) | [#2086](https://github.com/daiki-beppu/youtube-automation/pull/2086) | `de51f73cd64edcc581e63ae55cb4cd951bdeb55b` | [29494197754](https://github.com/daiki-beppu/youtube-automation/actions/runs/29494197754) | 6/6 SUCCESS |
| [#2063](https://github.com/daiki-beppu/youtube-automation/issues/2063) | [#2107](https://github.com/daiki-beppu/youtube-automation/pull/2107) | `179620011106c8405311232e9e1931f4ea4f595a` | [29511008187](https://github.com/daiki-beppu/youtube-automation/actions/runs/29511008187) | 6/6 SUCCESS |
| [#2064](https://github.com/daiki-beppu/youtube-automation/issues/2064) | [#2112](https://github.com/daiki-beppu/youtube-automation/pull/2112) | `63f633a2bf7aa208e7f70a66cf641a6404188b61` | [29514907029](https://github.com/daiki-beppu/youtube-automation/actions/runs/29514907029) | 6/6 SUCCESS |

各 6 check は `lint`, `test`, `windows-cost-tracker`, `changelog`, `adr-numbering`, `any-gate` で、すべて `SUCCESS`。これは停止した 2026-07-14 run の成果を採用した証拠ではなく、分割後の別 issue / PR で再実装し検証した証拠である。

### 7. 変更候補、変更後の遷移、テスト、受け入れ条件、ロールバック

コードは変更していない。以下は候補である。

#### 候補 A: task 個別 cancel を第一級状態にする

変更候補:

- `src/infra/task/taskRecordSchemas.ts`: `cancel_requested_at`, `cancel_reason`, `failure.kind` を追加。status に `cancelled` を追加するか、互換性優先なら `failed` + `failure.kind: user_interrupt` とする。
- `src/infra/task/taskLifecycleService.ts`: `requestTaskCancellation(name, reason)`。pending は claim 対象から除外して即 terminal、running は cancel request を保持。
- `src/features/tasks/execute/parallelExecution.ts`: active map を task name -> `{promise, AbortController}` にし、task 個別 abort を可能にする。
- `src/features/tasks/execute/taskExecution.ts`: task-local controller に cancel reason と requested timestamp を伝播。
- `src/features/tasks/list/taskForceFailActions.ts`: 「ledger だけ force-fail」と「実 process cancel」を別 action にする。

変更後遷移案:

| 現在 | 入力 | 次状態 | 実行 |
|---|---|---|---|
| pending | cancel request | cancelled | provider を起動しない |
| running | cancel request | cancelling | task-local signal abort、slot は provider settle まで占有 |
| cancelling | provider exit | cancelled | reason / requested_at / effective_at / signal を保持 |
| running | stream idle timeout after retry exhaustion | failed | `failure.kind=environment_timeout` |
| running | permanent provider error | failed | `failure.kind=provider_error` |
| running | process crash、次回起動 | failed | `failure.kind=orphaned_run` |

テスト候補:

1. concurrency 3、4番目 pending を cancel 後に 1 slot 解放しても provider が呼ばれない。
2. running 1件だけ cancel し、他2件は継続し、pending 4番目が cancel 済み task の代わりに開始する。
3. cancel request と task completion が同時でも terminal update が一度だけ成功する。
4. cancel reason が Codex `external_abort` と task ledger の `failure.kind` に残る。
5. 古い tasks.yaml（新字段なし）を 0.51 互換で読み込める。

受け入れ条件:

- cancel された pending task の provider call 数が 0。
- 個別 cancel が他の active task の signal を abort しない。
- task ledger だけで、誰のどの入力がいつ request/effective になったか追跡可能。
- Ctrl+C の全体 graceful shutdown は既存互換。

ロールバック:

- writer feature flag で新字段出力を停止し、reader は新字段を optional のまま残す。
- `cancelled` status を導入する場合は、ロールバック前に `cancelled -> failed` の一方向 migration を用意する。互換性リスクを下げるなら status は増やさず `failure.kind` のみ追加する。

#### 候補 B: abort source を end-to-end で永続化する

変更候補:

- `src/infra/codex/client.ts`: raw SDK error より先に `abortCause` と classified failure を返す既存経路を全 exit path で保証。
- `src/features/tasks/execute/taskResultHandler.ts` / `taskExecution.ts`: `AgentFailureDetail.category/reason` を task failure に保存。
- `src/features/tasks/execute/workflowExecutionReporting.ts`: user interrupt、idle timeout、part timeout、forced process signal を別表示。

テスト候補:

- SDK が `Codex Exec exited with signal SIGTERM` を throw しても external signal が aborted なら `user_interrupt` を優先。
- event が10分ない場合のみ `stream_idle_timeout`、終了直前 event があれば timeout 扱いしない。
- direct SIGTERM で reason 不明なら `signal_termination_unknown` とし、user interrupt と推測しない。

受け入れ条件:

- task ledger の terminal record が raw stderr だけに依存せず structured `kind`, `signal`, `reason`, `requested_at`, `effective_at` を持つ。
- external abort は retry 0、idle timeout は最大2 retryという既存契約を維持。

ロールバック:

- structured fields を optional にして raw `error` を併記する。consumer は新字段がない場合に旧 `error` へ fallback する。

#### 候補 C: enqueue の lineage を保存する

変更候補:

- `src/infra/workflow/system/system-enqueue-effect.ts`: `parent_task_name`, `parent_run_slug`, `enqueue_effect_id` を `saveEnqueuedTaskFile` へ渡す。
- `src/infra/task/taskRecordSchemas.ts`: lineage fields を optional 追加。

受け入れ条件:

- system effect で作られた task が親 run へ逆引き可能。
- 親 abort 時の既定は子を自動 cancel せず、明示 policy (`detach` / `cancel_pending_children`) で決める。

ロールバック:

- lineage fields は optional metadata なので writer 停止だけで旧動作へ戻せる。自動 cascade は feature flag で独立に無効化する。

## 主要な発見のサマリー

1. 対象 3 件の直接原因は、親運用セッションによる対象 Codex worker への明示的 `kill -TERM` と archived JSONL で確定した。TAKT timeout / CI / 自然な step 遷移ではない。
2. 3 件はいずれも終了直前に stream 出力があり、10分 idle timeout ではない。GitHub issue の owner comment も workflow 再監査による意図的停止を記録している。
3. wave 4 の #1976 は #1801 完了の 24ms 後に slot 補充で自動開始した。worker pool は completion 時に即補充する。
4. TAKT 0.51.0 には pending task の cancel tombstone も、実行中 task の個別 cancel API もない。共有 Ctrl+C は全 task 向けであり、対象時系列を単独では説明できない。
5. provider 層には `external_abort` / `stream_idle_timeout` / `part_timeout` の分類があるが、task ledger は raw SIGTERM error に潰れている。
6. stale `running` は次回起動時に `failed` へ倒されるが、その固定文言は「前回 run 開始前に interrupt された」という意味ではない。
7. task record に親子 lineage がなく、system enqueue された task は独立 queue item である。#1976 の後続 #2062/#2063/#2064 は GitHub sub-issue であり、別 PR / CI で全件完了した。

## 注意点・リスク

- issue comments 単独では signal sender を証明しないが、今回は archived session の tool call が実 command と対象 process 一覧を保存しているため sender を確定できる。
- `.takt/tasks.yaml` は terminal summary であり、対象 worktree / run report は既に破棄されている。stderr の全量、process tree、AbortSignal.reason は復元できない。
- 現在の project `concurrency: 5` は対象時点の値ではない。対象時点は global `concurrency: 3` を継承していた。
- #1801 の現在の label は取得日時点で `takt:improve` だが、2026-07-14 comment は当該 run を feature 必須として停止したと記録する。label の後続変更と当時の停止判断を混同しない。
- #1976 の現在の label は取得日時点で `takt:manual`。当時の docs run と現在の分類は異なる。
- `SIGTERM` だけで user interrupt / timeout / OOM / external kill を分類してはならない。source reason がない場合は unknown とする必要がある。
- status enum の追加は CLI、serializer、MCP/ACP consumer へ波及する。`failure.kind` の optional 追加の方が後方互換リスクは小さい。

## 調査できなかった項目と理由

1. **#1969 / #1976 の signal 時の数値 PID**: command は `pgrep -P 13771 -f '<issue cwd>'` の結果を shell 変数へ入れたが、展開後 PID を出力していない。対象 worker 自体は PPID + issue 固有 cwd と直後の failed で確定できる。
2. **#1976 の「実行前 interrupt request」**: 一次ログにその request はなく、開始後の監査と kill だけがある。したがって「開始前 request が遅延した」という前提自体を確認できなかった。
3. **対象 run の `meta.json`, trace, session log 全量**: 記録済み worktree `/Users/mba/02-yt/takt-worktrees/20260714T...` は取得日時点で存在せず、root `.takt/runs` にも対象 run_slug の複製がない。
4. **kernel-level signal audit**: archived command で送信操作は確定したが、OS audit subsystem による syscall / sender PID 記録は取得していない。
5. **TAKT task の親子 edge**: schema に edge がないため、GitHub sub-issue 関係以外は復元不能。対象 3 件自体は同一 queue の兄弟 task としてのみ確認できた。

## 推奨／結論

最優先は、timeout 値の変更ではなく「個別 cancel の永続化」と「abort source の end-to-end 保持」である。対象 3 件は idle timeout ではないため、timeout を延長しても再発防止にならない。

推奨順:

1. pending/running task に個別 cancel request を保存し、claim と signal を同じ task identity で制御する。
2. `failure.kind`、signal、reason、requested/effective timestamp を task ledger に保存する。
3. system enqueue に parent task/run lineage を付ける。
4. その後にのみ、必要なら graceful timeout や provider idle timeout を設定化する。

運用上の暫定策は、誤 workflow と判明した pending task を `.takt/tasks.yaml` 上で明示的に terminal/requeue 管理してから slot を解放すること、実行中 task を個別停止した場合は issue comment に UTC 時刻・対象 task/run_slug・送信方法・期待分類を残すことである。共有 Ctrl+C は全 active task を対象にするため、個別停止には使わない。
