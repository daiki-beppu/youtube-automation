# TAKT workflow transition / reject / retry / abort 調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 調査対象: 実稼働 TAKT 0.51.0、`nrslib/takt` tag `v0.51.0`、本リポジトリの project/global workflow、issue #1939 と対応 run
- 調査方法: 配布済み JavaScript、tag 固定の TypeScript、workflow YAML、NDJSON/run report、GitHub issue/PR/Actions を照合
- 版の注意: `/Users/mba/01-dev/takt` は 0.46.0 (`f268025b...`) のため、0.51.0 の挙動確定には使用していない。実稼働版は `/Users/mba/.bun/install/global/node_modules/takt/package.json` の 0.51.0、tag commit は [`90ecdfb`](https://github.com/nrslib/takt/commit/90ecdfb893909979c92f550f3730393502e6fde8)。

## 調査項目ごとの結果と詳細

### 1. workflow 定義と step 遷移

#### 1.1 確認した一次情報

- 実稼働エンジン: `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/engine/WorkflowRunLoop.js`
- rule → transition: `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/engine/transitions.js`
- rule 評価: `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/evaluation/RuleEvaluator.js`
- 終端定数: `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/constants.js`
- tag 固定ソース: [WorkflowRunLoop.ts (v0.51.0)](https://github.com/nrslib/takt/blob/v0.51.0/src/core/workflow/engine/WorkflowRunLoop.ts)、[WorkflowCallRunner.ts (v0.51.0)](https://github.com/nrslib/takt/blob/v0.51.0/src/core/workflow/engine/WorkflowCallRunner.ts)
- project/global workflow: `/Users/mba/.takt/workflows/fix.yaml`、`/Users/mba/.takt/workflows/improve.yaml`、`/Users/mba/.takt/workflows/feature.yaml`
- builtin deep-research: `/Users/mba/.bun/install/global/node_modules/takt/builtins/ja/workflows/deep-research.yaml`

#### 1.2 事実: 遷移決定

`determineRuleTransition(step, ruleIndex)` は、マッチした rule の `next`、`returnValue`、`requiresUserInput` だけを返す。`REJECT` という語自体に失敗分類の意味はなく、rule 配列の該当 index と `next` が意味を決める（配布版 `transitions.js:6-15`）。

`RuleEvaluator` は aggregate、決定的 `when(...)`、Phase 3 tag、Phase 1 tag、`ai(...)`、AI fallback、deferred `when(true)` の順に評価し、rules があるのに一致しなければ throw する（配布版 `RuleEvaluator.js:39-105`）。したがって rule 不一致は `ABORT` rule ではなく、catch で `runtime_error` になる。

`COMPLETE` と `ABORT` は文字列定数である（配布版 `constants.js:8-9`）。`nextStep === COMPLETE` は completed、`nextStep === ABORT` は後述の固定 `step_transition` abort になる（配布版 `WorkflowRunLoop.js:368-375`、tag ソースでは `WorkflowRunLoop.ts:608`）。

#### 1.3 実コード条件への入力再現

実稼働 0.51.0 の配布モジュールへ直接入力した。実装・ファイル変更はしていない。

```console
$ node --input-type=module -e '<determineRuleTransition に supervise rule index=1 を入力>'
{
  "input": { "matchedRuleIndex": 1, "condition": "REJECT" },
  "transition": { "nextStep": "ABORT" },
  "abortComparison": true,
  "engineAbortKind": "step_transition",
  "engineReason": "Workflow aborted by step transition"
}

$ node --input-type=module -e '<approved/needs_fix/blocked を順に入力>'
{"condition":"approved","transition":{"nextStep":"COMPLETE"}}
{"condition":"needs_fix","transition":{"nextStep":"implement"}}
{"condition":"blocked","transition":{"nextStep":"ABORT"}}
```

これは rule の condition 文言が分類を作らず、`next` だけが現行エンジンの終端を決めることの最小再現である。

### 2. `Workflow aborted by step transition` の入力と条件

#### 2.1 事実: 唯一の直接条件

`runWorkflowToCompletion` では次の順である。

1. step 実行結果を得る。
2. `blocked` / `error` / quality gate failure を先に処理する。
3. `resolveDoneTransition(step, response)` を呼ぶ。
4. `nextStep` が `ABORT` と等しい場合、`abortWorkflow(deps, 'step_transition', 'Workflow aborted by step transition')` を呼ぶ。

根拠: 配布版 `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/engine/WorkflowRunLoop.js:300-375`、tag 固定 [WorkflowRunLoop.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/core/workflow/engine/WorkflowRunLoop.ts#L608)。single-iteration 経路も同じ固定 kind/reason（配布版 `:540-550`、tag ソース `:824`）。

よって、この文言の入力は「マッチした rule（または loop monitor judge）が返した next step が文字列 `ABORT`」である。入力された condition、structured verdict、report の finding、environment error、scope review appendix は abort reason に含まれない。

#### 2.2 事実: abort kind はエンジン内には存在する

`WorkflowAbortKind` は次の union を持つ。

```text
interrupt | iteration_limit | loop_detected | blocked | step_error |
rate_limited | user_input_required | user_input_cancelled |
step_transition | runtime_error
```

根拠: `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/types.d.ts:90-100`。`abortWorkflow` は kind/reason/step を `failure` に保持する（`WorkflowRunLoop.js:122-139`）。

ただし `step_transition` の内部では reject/block/permanent failure の下位分類がない。

### 3. 正常 REJECT、環境障害、永久失敗、ユーザー中断の現行分類

#### 3.1 現行遷移表（事実）

| 入力・条件 | engine 処理 | engine kind/reason | task 側の見え方 | 自動 retry 情報 |
|---|---|---|---|---|
| review/supervise の REJECT が `next: fix` | 次 step へ通常遷移 | abort なし | running 継続 | workflow が再実行 |
| REJECT/blocked/scope review が `next: ABORT` | workflow abort | `step_transition` / 固定文言 | `failed` + 固定文言 | なし |
| `response.status === blocked`、入力 handler なし | workflow abort | `blocked` / `Workflow blocked and no user input provided` | `failed` | なし |
| `response.status === error` | workflow abort | `step_error` / response error | `failed` | なし |
| provider rate limit、fallback なし | workflow abort | `rate_limited` | `failed` | provider switch chain 内だけ retry |
| throw、abort 未要求 | catch → abort | `runtime_error` | `failed` | なし |
| SIGINT/external abort が engine に到達 | loop 冒頭または catch | `interrupt` / `Workflow interrupted by user (SIGINT)` | `failed` | なし |
| max_steps 到達 | iteration handler 後 abort | `iteration_limit`、task は別途 `exceeded` | `exceeded` | 明示 requeue 可 |
| workflow_call child が rule `ABORT` | child abort を親の status `done` response へ変換 | content は child `lastOutput` 優先 | 親 rule が `ABORT` condition を再評価 | child の kind は親 response から消える |

根拠: `WorkflowRunLoop.js:203-380`、`taskExceedService.js:7-50`、[WorkflowCallRunner.ts v0.51.0](https://github.com/nrslib/takt/blob/v0.51.0/src/core/workflow/engine/WorkflowCallRunner.ts#L159-L171)。

#### 3.2 task 永続化で分類が失われる（事実）

`executeWorkflow` は `success`, `reason`, `lastStep`, `lastMessage`, `exceeded` だけを返し、engine の `abort.kind` を返さない（配布版 `workflowExecution.js:215-227`、[workflowExecution.ts v0.51.0](https://github.com/nrslib/takt/blob/v0.51.0/src/features/tasks/execute/workflowExecution.ts#L289-L290)）。

`buildTaskResult` は失敗時 `response = runResult.reason` とし、`failureStep`/`failureLastMessage` は残すが kind/retryable を持たない（配布版 `taskResultHandler.js:3-21`、[taskResultHandler.ts v0.51.0](https://github.com/nrslib/takt/blob/v0.51.0/src/features/tasks/execute/taskResultHandler.ts#L47-L49)）。`TaskLifecycleService.failTask` はこれを status `failed` の `failure.error` に保存する（配布版 `taskLifecycleService.js:123-148`）。

結論（事実）: エンジンで区別される `interrupt` / `runtime_error` / `blocked` すら task record では原則同じ `failed` になり、`step_transition` の内側はエンジン段階から区別不能である。

### 4. 同一 REJECT 反復、最大試行回数、終了理由保持

#### 4.1 同一 REJECT 反復（事実）

`fix.yaml` は `supervise` の「要求未達成、テスト失敗、ビルドエラー」を `fix_supervisor` へ、`fix_supervisor` の両 rule を `supervise` へ戻す（`/Users/mba/.takt/workflows/fix.yaml:48-114`）。この workflow には `loop_monitors` がない。

汎用 `LoopDetector` は同じ step の**連続**実行のみ数え、default は 10 回超で warn、action も `warn` である（配布版 `loop-detector.js:8-45`）。`supervise → fix_supervisor → supervise` の交互反復では連続カウントが毎回 1 に戻るため検出しない。

`feature.yaml` だけは `implement ↔ review` cycle threshold 3 の loop monitor を持つ（`/Users/mba/.takt/workflows/feature.yaml:31-48`）。`fix` / `improve` には同等の「同一 finding fingerprint」判定がない。

#### 4.2 最大試行回数（事実）

- `fix`: `max_steps: 24`（`/Users/mba/.takt/workflows/fix.yaml:9`）
- `improve`: `max_steps: 12`（`/Users/mba/.takt/workflows/improve.yaml:23`）
- `feature`: `max_steps: 30`（`/Users/mba/.takt/workflows/feature.yaml:29`）
- `deep-research`: `max_steps: 15`（builtin `deep-research.yaml:9`）

max 到達時、run context が iteration limit を無視しない限り `exceededInfo` に current step、次回上限、iteration、resume point を保存し、task status は `exceeded` になる（配布版 `workflowExecution.js:100-114`、`taskExecution.js:93-103`、`taskExceedService.js:14-23`）。これは現行で唯一、明示的再投入情報が比較的よく保たれる終端である。

#### 4.3 終了理由保持（事実）

- engine span: abort kind/reason/failure を保持。
- workflow event bridge: `abortReason` だけを保持。
- task result: reason/lastStep/lastMessage を保持、kind は破棄。
- task record: `failure.step/error/last_message` を保持、kind/retryable/userInitiated はなし。
- child workflow: `step_transition` だけ child `lastOutput.content` を親へ優先して渡すが、abort kind は親 response の型に残さない。

### 5. issue #1939: 到達不能な commit / PR / CI 証跡要求

#### 5.1 事実: 循環依存

Issue [#1939](https://github.com/daiki-beppu/youtube-automation/issues/1939) の order は受入基準に「CHANGELOG gate と GitHub CI が green」を置いた（`/Users/mba/02-yt/00-automation/.takt/tasks/20260714-102033-issue-1939-automation-update-p/order.md:52-53` 相当）。一方、TAKT step prompt は git add/commit/push を禁止し、`executeAndCompleteTask` は **workflow success 後にのみ** `postExecutionFlow`（commit/push/PR）へ進む（配布版 `taskExecution.js:21-29,105-137`）。

したがって workflow 内 supervisor が PR/CI green を APPROVE 条件にすると、次の循環になる。

```text
supervisor APPROVE
  └─ 必要: PR/CI green
       └─ 必要: postExecutionFlow
            └─ 必要: workflow success
                 └─ 必要: supervisor APPROVE
```

#### 5.2 代表 run の再構築（生ログ）

run root:

`/Users/mba/02-yt/takt-worktrees/20260714T1022-1939-issue-1939-automation-update-p/.takt/runs/20260714-102251-implement-using-only-the-files-e8g626`

NDJSON:

`.../logs/20260714-192252-vwsqat.jsonl`

meta は `status: running`, `currentStep: supervise`, `currentIteration: 16`、resume point も supervise/16 のまま（`meta.json`）。ログから次の 16 step を復元した。

```text
1 fix
2 supervise
3 fix_supervisor
4 supervise
5 fix_supervisor
6 supervise
7 fix_supervisor
8 supervise
9 fix_supervisor
10 supervise
11 fix_supervisor
12 supervise
13 fix_supervisor
14 supervise
15 fix_supervisor
16 supervise (phase 1 start 後に外部停止)
```

監督 report 履歴は 7 回以上 REJECT。最終 report の生条件は以下。

```text
## 結果: REJECT
CHANGELOG gate の公式実判定: ❌（origin/main 不在でスキップ）
GitHub CI: ❌（PR 不在で未実行）
VAL-NEW-execution-evidence: persists
```

絶対パス: `.../reports/supervisor-validation.md:3,15-16,25,69,88-89`。`fix-supervisor-verification.md` は対象 pytest `78 passed`、Ruff、format、diff check、ローカル changelog 相当条件を成功とし、残件が step 権限では生成不能な PR/CI 証跡だけだと記録する。

Issue コメントも同一理由の supervise/fix 3 回以上反復を明記する: [#1939 owner comment](https://github.com/daiki-beppu/youtube-automation/issues/1939#issuecomment-4968654236)。

#### 5.3 事後証跡（事実）

専用 supervisor が workflow 外で commit/PR を作ると、[PR #2034](https://github.com/daiki-beppu/youtube-automation/pull/2034) と [Actions run 29329862316](https://github.com/daiki-beppu/youtube-automation/actions/runs/29329862316) は成功し、lint/test/windows/changelog/ADR/any-gate の 6 jobs が全成功、その後 merge された。つまり実装の永久失敗ではなく、証跡生成順序の設計不整合だった。

### 6. Supervisor 判定の解釈

#### 6.1 事実

- `fix` の supervise は自然言語 rule で、APPROVE は `COMPLETE`、REJECT は `fix_supervisor`。REJECT 自体は正常なフィードバック遷移である。
- `improve` の review は structured verdict: `approved → COMPLETE`, `needs_fix → implement`, `blocked → ABORT`, fallback → `ABORT`（`improve.yaml:116-126`）。
- `feature` も `approved → COMPLETE`, `needs_fix → implement`, `blocked → ABORT`, fallback → `ABORT`（`feature.yaml:273-283`）。

現行では `blocked → ABORT` と schema fallback → `ABORT` が同じ `step_transition` になる。`blocked` が daemon/network/permission 等の再試行可能障害であっても、永久的な verdict/schema 異常と区別されない。

### 7. 変更候補のファイル・関数

以下は**推奨案（未実装）**。

#### 7.1 最小互換案

task status enum は直ちに増やさず、既存 `failed` に structured failure を追加する。

| ファイル（TAKT source） | 関数/型 | 推奨変更 |
|---|---|---|
| `src/core/workflow/types.ts` | `WorkflowAbortResult`, `WorkflowStepFailureSummary` | `classification`, `retryable`, `userInitiated`, `ruleIndex`, `ruleCondition`, `transitionAppendix` を追加 |
| `src/core/models/workflow-types.ts` / schema | rule schema | `terminal: { classification, retryable, reason }` を `next: ABORT` rule に任意追加。未指定は legacy `step_transition` |
| `src/core/workflow/engine/WorkflowRunLoop.ts` | `abortWorkflow`, ABORT branch | マッチした rule/loop-monitor の terminal metadata と response summary を abort result に保持。固定 reason だけに潰さない |
| `src/core/workflow/engine/WorkflowEngineStepCoordinator.ts` | transition resolution | `nextStep` だけでなく matched rule metadata を返す |
| `src/core/workflow/engine/WorkflowCallRunner.ts` | `buildWorkflowCallResponse` | child `abortKind/classification/retryable` を structured response に保持し、親 rule が利用可能にする |
| `src/features/tasks/execute/types.ts` | workflow run result | `abortKind`, `failure` を追加 |
| `src/features/tasks/execute/workflowExecution.ts` | return object | engine resultの abort metadata を event bridge 経由で破棄しない |
| `src/features/tasks/execute/taskResultHandler.ts` | `buildTaskResult` | structured failure を task result へ転送 |
| `src/infra/task/schema.ts`, `taskLifecycleService.ts` | task failure schema / `failTask` | `kind`, `classification`, `retryable`, `user_initiated` を永続化 |
| `src/features/tasks/execute/taskExecution.ts` | `executeTaskAndCompleteWithDetails` | retryable block/interrupt/permanent failure を queue policy へ渡す |
| workflow YAML (`fix/improve/feature/...`) | `next: ABORT` rules | blocked、intentional reject、permanent invalid を terminal metadata で明示 |

tag 固定参照 URL: [WorkflowRunLoop.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/core/workflow/engine/WorkflowRunLoop.ts)、[taskResultHandler.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/features/tasks/execute/taskResultHandler.ts)、[workflowExecution.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/features/tasks/execute/workflowExecution.ts)、[taskLifecycleService.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/infra/task/taskLifecycleService.ts)。

#### 7.2 #1939 型の外部証跡ゲート

推奨（未実装）:

1. workflow 内 supervise の受入条件を「commit 前に到達可能な local readiness」に限定する。
2. success 後の `postExecutionFlow` で commit/push/PR を作る。
3. `postExecutionFlow` の後段に CI wait/check を置き、CI failure は `post_execution` / retryable として branch/PR/run URL を保持する。
4. issue 文面の「GitHub CI green」は workflow supervisor 条件ではなく task 全体の post-execution acceptance として解釈する。

### 8. 変更後遷移表（推奨、未実装）

| 判定入力 | workflow 遷移 | terminal classification | retryable | task 処理 |
|---|---|---|---|---|
| APPROVE | `COMPLETE` | success | false | post-executionへ |
| REJECT + actionable finding | fix step | なし | n/a | 同一 run 継続 |
| 同一 finding fingerprint が上限未満 | fix step | なし | n/a | promotionし再試行 |
| 同一 finding fingerprint が3回継続 | `ABORT` | `non_converging_reject` | false（要人手） | failed、finding履歴保持 |
| daemon/network/permission block | `ABORT` | `environment_blocked` | true | failed保持または明示 requeue、backoff |
| requirement/scope が実行不能 | `ABORT` | `intentional_reject` | false | failed、再投入しない |
| provider/engine例外（transient判定可） | abort | `runtime_failure` | 判定結果 | retryableのみ再投入 |
| user SIGINT/明示 interrupt | abort | `user_interrupted` | false（自動再投入しない） | resume point保持 |
| max_steps | abort | `iteration_exceeded` | manual | 現行 exceeded維持 |
| local readiness success、PR/CI失敗 | workflowはcompleted、post gate失敗 | `post_execution_blocked` | true | branch/PR/run URLを保持して再確認 |

### 9. テストケース

以下は追加すべきテスト案（未実行）。

1. `next: ABORT` + `terminal.classification=intentional_reject` が fixed generic reason ではなく metadata と rule condition を返す。
2. `blocked → ABORT` が `environment_blocked`, `retryable=true` で task record まで保存される。
3. fallback `when(true) → ABORT` が `workflow_contract_error`（permanent）になる。
4. SIGINT が `user_interrupted`, `userInitiated=true` のまま task record へ到達する。
5. `runtime_error`, `step_error`, `rate_limited` の既存 kind が task 永続化で失われない。
6. child workflow の intentional reject と runtime error が親 workflow で区別できる。
7. `supervise ↔ fix_supervisor` で同一 finding fingerprint 3 回なら明示終端し、異なる finding が減少中なら継続する。
8. `max_steps` は現行 `exceeded` / resume point を維持する。
9. post-execution CI failure が workflow 実装 REJECT に戻らず、PR/run URL を持つ retryable post failure になる。
10. legacy YAML（terminal metadata なし）は従来どおり load できる。
11. JSON/task schema migrationで既存 `failure.error` のみの record を読める。
12. CLI/list/retry UI が retryable block、permanent reject、user interrupt を別表示する。

### 10. 受け入れ条件

推奨変更の acceptance（未実装）:

- `Workflow aborted by step transition` 単独では、ユーザー操作が必要な主要終端を表さない。
- task record から `kind/classification/retryable/step/reason` を復元できる。
- environment block は永久 failure と区別され、無制限自動 retry されない。
- user interrupt は自動 retry されず、resume point と最終確定 step を保持する。
- 同一 REJECT は finding fingerprint と反復回数を保持し、設定上限で明示停止する。
- max_steps/exceeded の現行 resume/requeue 契約を壊さない。
- child workflow でも abort classification を保持する。
- commit/PR/CI の後置条件は post-execution で判定され、workflow 内に到達不能な証跡要求を置かない。
- v0.51.0 以前の workflow/task data を読み込める。

### 11. ロールバック方法

推奨変更を実装した場合の rollback（未実施）:

1. rule の `terminal` metadata は任意フィールドにし、まず reader-first で展開する。
2. task failure の新フィールドも optional にし、旧 reader が無視できる形にする。
3. 問題時は queue の新分類利用だけ feature flag/config で無効化し、`failed` + legacy reason へ戻す。
4. DBではなく YAML/JSON task record のため、新フィールド削除を強制せず旧コードで読み飛ばす。履歴情報を破壊する migration は行わない。
5. post-execution CI gate を無効化しても、作成済み branch/PR URL は保持し、手動照合へ戻す。
6. workflow YAML の terminal annotation を戻すだけで legacy `step_transition` へ戻せる。

## 主要な発見のサマリー

1. **`Workflow aborted by step transition` は原因ではなく、`nextStep === ABORT` の固定ラベルである。** condition、verdict、environment block、scope abort を表さない。
2. **abort kind は engine 内にあるが task 永続化まで伝播しない。** retry policy を正しく実装できる情報が途中で落ちる。
3. **正常な REJECT は fix へ戻る限り正常遷移。** terminal `ABORT` にした瞬間、意図的 reject と再試行可能 block が同じ `step_transition` になる。
4. **fix workflow は交互ループを検出しない。** default detector は連続同一 step だけで、#1939 の `supervise ↔ fix_supervisor` は max_steps まで空転可能。
5. **#1939 は実装失敗ではなく phase-order failure。** workflow success 後にしか作れない PR/CI を workflow 内 APPROVE 条件にしたため循環した。外部 supervisor で PR 化すると CI は全成功した。

## 注意点・リスク

- **事実:** project/global workflow は npm builtin と独立に更新される。TAKT本体だけ修正しても、各 YAML の `next: ABORT` 分類を明示しなければ legacy fallback のままになる。
- **事実:** `WorkflowCallRunner` は child `step_transition` 時に `lastOutput` を優先する特殊処理がある。単純に reason 文言だけ変えると親 rule の `ABORT` condition マッチを壊す可能性がある。
- **事実:** task status enum を増やすと list/watch/retry/ACP/MCP/serializer/UI へ影響が広い。最小案は status を維持して structured failure を追加する方が後方互換リスクが低い。
- **推測:** finding fingerprint は report自由文の完全一致では不安定。ledger finding ID/family tag、structured verdict feedback の正規化など、engine所有の安定キーが必要。
- **推測:** environment block の自動 requeue は無制限だと障害中に資源を浪費する。回数上限、backoff、同一原因 fingerprint が必要。

## 調査できなかった項目と理由

- #1939 の当時のプロセスへ signal を送った主体は、この遷移レポートでは特定していない。SIGTERM/SIGINT・interrupt/timeout は `data-interrupt-timeout.md` で別調査する。
- v0.51.0 の挙動を変更した実装は作成していないため、推奨後の統合/e2e テストは未実行。
- private な provider backend の内部再試行は一次情報へアクセスできず対象外。TAKTが観測する response/status 以降だけを扱った。

## 推奨／結論

最優先は、`ABORT` を別の文字列へ変えることではなく、**rule transition → engine abort → workflow execution result → task result → task record** の全経路で structured terminal classification を保持すること。その上で、workflow YAML に intentional reject / environment blocked / permanent contract failure を明示し、同一 finding 反復を fingerprint で検出する。

#1939 型の条件は workflow supervisor から外し、local readiness → commit/PR → CI の順に post-execution gate で判定する。これにより正常 REJECT、環境障害、永久失敗、ユーザー中断の意味を壊さず、到達不能な証跡要求による空転も防げる。
