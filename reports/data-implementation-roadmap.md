# TAKT 失敗群の実装対応ロードマップ

- 取得日: 2026-07-17（Asia/Tokyo）
- 調査対象: TAKT `0.51.0`、Codex CLI / SDK `0.144.1`、本リポジトリの保存済み task ledger・run report・workflow・環境設定
- 成果物: `/Users/mba/02-yt/00-automation/reports/data-implementation-roadmap.md`
- 調査境界: 読み取りと統合のみ。コード、workflow、設定、commit、push、stagingは変更していない。
- 事実の扱い: 「確認済み」は生ログ、配布済みコード、tag固定source、公式仕様のいずれかで確認したもの。「提案」は未実装の設計。「未確認」は証拠不足を明記した。

## 調査項目ごとの結果と詳細

### 1. 根拠集合と版固定

主要なローカル一次資料・詳細調査は次のとおり。すべて取得日は2026-07-17である。

| 領域 | 絶対パス |
|---|---|
| workflow遷移 | `/Users/mba/02-yt/00-automation/reports/data-workflow-transitions.md` |
| role prompt / template | `/Users/mba/02-yt/00-automation/reports/data-review-prompts.md` |
| #1939 Supervisor反復 | `/Users/mba/02-yt/00-automation/reports/data-supervisor-rejections.md` |
| auto-commit | `/Users/mba/02-yt/00-automation/reports/data-auto-commit.md` |
| preflight | `/Users/mba/02-yt/00-automation/reports/data-preflight.md` |
| interrupt / timeout | `/Users/mba/02-yt/00-automation/reports/data-interrupt-timeout.md` |
| concurrency / resource | `/Users/mba/02-yt/00-automation/reports/data-concurrency-resources.md` |
| worktree / Nix / lefthook | `/Users/mba/02-yt/00-automation/reports/data-git-hooks-worktree.md` |
| environment parity | `/Users/mba/02-yt/00-automation/reports/data-environment-parity.md` |
| Codex tool error | `/Users/mba/02-yt/00-automation/reports/data-tool-errors.md` |
| Codex runtime / telemetry | `/Users/mba/02-yt/00-automation/reports/data-codex-runtime.md` |
| task ledger | `/Users/mba/02-yt/00-automation/.takt/tasks.yaml` |
| project runtime | `/Users/mba/02-yt/00-automation/.takt/config.yaml`, `/Users/mba/02-yt/00-automation/.takt/runtime-prepare.sh` |
| upstream配布コード | `/Users/mba/.bun/install/global/node_modules/takt/dist/` |

外部一次情報は、TAKT tag `v0.51.0` commit [`90ecdfb`](https://github.com/nrslib/takt/commit/90ecdfb893909979c92f550f3730393502e6fde8)、[WorkflowRunLoop.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/core/workflow/engine/WorkflowRunLoop.ts)、[workflowExecution.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/features/tasks/execute/workflowExecution.ts)、[taskResultHandler.ts](https://github.com/nrslib/takt/blob/v0.51.0/src/features/tasks/execute/taskResultHandler.ts)、[Git config 2.54](https://git-scm.com/docs/git-config/2.54.0.html)、[Git commit](https://git-scm.com/docs/git-commit.html)、[Node.js child_process](https://nodejs.org/api/child_process.html)、[Lefthook install](https://lefthook.dev/usage/commands/install/)、[Lefthook check-install](https://lefthook.dev/usage/commands/check-install/)に限定した。不審なドメイン、バイナリ、実行可能ファイルは取得していない。

版固定上の注意: `/Users/mba/01-dev/takt` は `0.46.0` なので挙動確定には使用せず、実稼働配布版 `0.51.0` とtag固定sourceを採用した。

代表run・issue・生ログの索引:

| 事象 | 一次証拠 |
|---|---|
| #1939 Supervisor反復 | run slug `20260714-102251-implement-using-only-the-files-e8g626`、当時のrun root `/Users/mba/02-yt/takt-worktrees/20260714T1022-1939-issue-1939-automation-update-p/.takt/runs/20260714-102251-implement-using-only-the-files-e8g626/`、[issue #1939](https://github.com/daiki-beppu/youtube-automation/issues/1939) |
| #1939 外部回復 | commit `62fd5231da2439ccfb37a12648fddc796dceec3e`、[PR #2034](https://github.com/daiki-beppu/youtube-automation/pull/2034)、Actions run `29329862316`（取得時6 job SUCCESS） |
| 12件auto-commit failure | `/Users/mba/02-yt/00-automation/.takt/tasks.yaml` と `/Users/mba/02-yt/00-automation/reports/data-auto-commit.md:20` のissue別task range・run root・reflog表 |
| #1969/#1801/#1976 SIGTERM | `/Users/mba/.codex/archived_sessions/rollout-2026-07-14T16-16-11-019f5f7b-b6fe-76a3-90b3-5dcb94b6ce01.jsonl` のarchive line 3243/3246/3406/3424、および `/Users/mba/02-yt/00-automation/reports/data-interrupt-timeout.md:19` |
| wait/patch tool error | 対象session JSONLから抽出した `/Users/mba/02-yt/00-automation/reports/data-tool-errors.md:20`。元worktree削除済みのため、抽出reportを保持証拠とする |
| 分割後の#1976系完了 | [#2062 / PR #2086](https://github.com/daiki-beppu/youtube-automation/pull/2086)、[#2063 / PR #2107](https://github.com/daiki-beppu/youtube-automation/pull/2107)、[#2064 / PR #2112](https://github.com/daiki-beppu/youtube-automation/pull/2112)。取得時の対応Actions runは `29494197754`, `29511008187`, `29514907029`、各6/6 SUCCESS |

上表の「取得時SUCCESS」は2026-07-17時点の観測であり、停止した元runの成果をそのまま採用した証拠ではない。特に#1976系は分割後の別issue/PRによる再実装・検証である。

### 2. 全体の実装対応表

| ID | 実装単位 | 根本原因 | 責任層 | 優先度 | 工数 | 主な既存失敗への作用 |
|---|---|---|---|---|---|---|
| W1 | workflow遷移とエラー分類 | `next: ABORT` が固定 `step_transition` になり、engineのabort kindもtask永続化で消える | TAKT engine / task persistence / workflow schema | P0 | L（8–15人日） | 再分類＋早期検出。#1939型の誤REJECTとretry不能を止める |
| W2 | Supervisor / reviewer prompt | 品質、環境、権限、外部gateを同じREJECTにし、step内で生成不能なPR/CI証跡を要求 | role prompt / workflow template / report schema | P0 | M（4–7人日） | 防止。無意味なfix loopを止める |
| W3 | auto-commit・PR preflight | runtime XDG隔離でGit identityが隠れ、commit detailはgeneric messageへ破棄 | runtime / Git adapter / postExecution | P0 | M（5–8人日） | 防止＋早期検出。12件のpublication failureを直接対象化 |
| W4 | interrupt・timeout・SIGTERM | 個別cancel API/tombstoneがなく、abort sourceがraw SIGTERMへ潰れる | queue / task lifecycle / provider / process control | P0 | L（8–14人日） | 再分類＋防止。#1969/#1801/#1976型の誤診を止める |
| W5 | worktree・Nix・lefthook | 通常worktreeとsandbox workerの意図的非対称、sync成功とshell入場成功の混同 | repo bootstrap / Nix / project runtime / CI | P1 | M（5–9人日） | 早期検出。環境障害を品質REJECTから分離 |
| W6 | Codexツール入力検証 | callerがtool schemaを知らず、stale readと並行writerでpatch検証が失敗 | Codex prompt/wrapper / edit coordination / task logging | P1 | M（4–7人日） | 防止＋再分類。局所tool errorをterminal causeと誤認しない |
| W7 | 構造化ログとメトリクス | terminal cause、stderr diagnostics、resource時系列、publication phaseが非構造または欠測 | observability / task ledger / exporters | P0基盤 | L（8–15人日） | 全単位の早期検出・原因判定を可能にする |

工数はTAKT upstreamでの実装・unit/integration test・schema互換確認を含む相対見積りであり、実測ではない。W1/W7の共通schemaを別々に作ると二重実装になるため、同一vertical sliceとして開始する。

### 3. W1 — workflow遷移とエラー分類

#### 確認済みの根本原因と根拠

- `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/engine/WorkflowRunLoop.js:374` は `nextStep === ABORT` を次の固定値へ変換する。

```js
abort = abortWorkflow(deps, 'step_transition',
  'Workflow aborted by step transition');
```

- `WorkflowAbortKind` には `interrupt | iteration_limit | ... | step_transition | runtime_error` があるが、`workflowExecution.js` のreturnと `taskResultHandler.js::buildTaskResult()` は `success/reason/lastStep/lastMessage` までしかtaskへ渡さない。
- `fix.yaml` の `supervise → fix_supervisor → supervise` は交互loopであり、連続同一stepだけを見るdefault detectorでは検出できない。
- issue [#1939](https://github.com/daiki-beppu/youtube-automation/issues/1939) はSupervisor reportが7世代すべてREJECT、iteration 16で手動ABORT。コードfinding解消後も、workflow成功後にしか作れないcommit/PR/CI証跡を要求し続けた。事後のPR [#2034](https://github.com/daiki-beppu/youtube-automation/pull/2034) とissue commentは外部回復を示す。

#### 実装仕様

- 責任層: TAKT core workflow engine、workflow schema、task persistence、queue policy。
- 対象:
  - `src/core/workflow/types.ts::{WorkflowAbortResult, WorkflowStepFailureSummary}`
  - `src/core/models/workflow-types.ts` とrule schema
  - `src/core/workflow/engine/{WorkflowRunLoop,WorkflowEngineStepCoordinator,WorkflowCallRunner}.ts`
  - `src/features/tasks/execute/{types,workflowExecution,taskResultHandler,taskExecution}.ts`
  - `src/infra/task/{schema,taskLifecycleService}.ts`
  - `/Users/mba/.takt/workflows/{fix,improve,feature}.yaml`
- 具体的変更:
  1. `next: ABORT` ruleへoptional `terminal: {classification,retryable,reason,owner}` を追加。
  2. `abort.kind`, matched `ruleIndex/condition`, response summaryをengineからtask ledgerまで保持。
  3. `failure: {kind,classification,retryable,user_initiated,step,reason}` をoptional追加し、旧 `failure.error` を併記。
  4. child workflowにもabort metadataを保持。
  5. finding fingerprintを導入し、同一actionable finding 3回で `non_converging_reject`。異なるfindingや減少中は継続。
- 依存: W2のverdict schema、W7の共通failure envelope。W3/W4のclassificationも同じenvelopeへ載せる。
- 期待効果: `environment_blocked`, `intentional_reject`, `workflow_contract_error`, `user_interrupted`, `post_execution_blocked` をqueueが区別できる。
- リスク: status enum追加はCLI/MCP/ACP consumerへ波及する。初期段階はstatusを増やさず `failed + failure.kind` とする。

#### 受け入れ条件・テスト・失敗再現

- task recordだけで `kind/classification/retryable/step/reason` を復元できる。
- legacy workflow/taskを読める。max_stepsの現行 `exceeded` / resume pointを維持する。
- child abort、SIGINT、runtime error、blocked、fallback ABORTが別classificationになる。
- `#1939` fixture replayでコードfinding解消後に16 iterationへ到達しない。
- upstream test command候補: `bun test` またはupstream `package.json` が定めるtest command、続けて `takt workflow doctor fix improve feature`。正確なtest script名は実装checkoutで再確認する。
- 失敗再現テスト: legacy `next: ABORT`、typed blocked、schema fallback、同一fingerprint 3回、child `ABORT`、SIGINTの6fixture。
- rollback: reader-firstでoptional fieldを展開し、classification consumerのみfeature flagで停止。YAMLの`terminal` annotationを戻せばlegacy動作へ戻せる。
- 対応種別: 既存失敗の**再分類**が主、同一loopの**防止**、unexpected fallbackの**早期検出**。

### 4. W2 — Supervisor / reviewer prompt

#### 確認済みの根本原因と根拠

- `/Users/mba/02-yt/00-automation/reports/data-review-prompts.md` の工程別表では、workflow内roleが生成できるのはlocal diff/test/reportであり、PR URL・Actions結果はworkflow success後の`postExecutionFlow`でのみ生成される。
- #1939 current supervisor reportは実装5要件、focused pytest、3件のコードfindingをresolvedとした後も、post-PR証跡だけでREJECTした。
- `pass_previous_response: false` でもreport directory経由でfindingは継承されており、空転原因はprevious response欠落ではない。
- current `fix.yaml` はsuperviseのstructured output、blocked分岐、交互loop monitorが不足する。

#### 実装仕様

- 責任層: role prompt、workflow template、structured review schema。
- 対象:
  - `/Users/mba/01-dev/dotfiles/config/.takt/workflows/fix.yaml`
  - `/Users/mba/01-dev/dotfiles/config/.takt/schemas/review-verdict.json`
  - TAKT role prompt/template resolver（詳細pathは `data-review-prompts.md` のPlanner/Implementer/Reviewer/Supervisor節）
  - `InstructionBuilder`, `StepExecutor`, `workflowStepNormalizer`, `infra/task/instruction`
- 具体的変更:
  1. verdictを `approved | needs_fix | blocked | external_pending` にし、findingへ `id,class,owner,capability,actionable,acceptance_test,disposition` を必須化。
  2. Supervisorはlocal qualityとphase readinessを別見出しで返す。commit/PR/CIは`External gates pending`へ置き、`needs_fix`にしない。
  3. `needs_fix` は当該stepで編集可能なquality defectだけに限定。
  4. `fix_supervisor` の「進行不能でもsuperviseへ戻る」edgeを削除し、typed blockedへ終端。
  5. previous responseは補助とし、finding ledger/reportを正本にする。2,000文字truncation時はsnapshot参照を必須化。
- 依存: W1のtyped transition、W3のpost-execution state。
- 期待効果: 実装loopが到達可能な成果だけを評価し、publication/CI failureでコードを再編集しない。
- 工数: M。promptだけならSだが、schema・doctor・mock provider E2Eを含めM。
- リスク: classificationを過度に細分化するとmodel出力が不安定。deterministic schema validationとfallback `workflow_contract_error` が必要。

#### 受け入れ条件・テスト・失敗再現

- `takt workflow doctor fix` が成功し、prompt previewに4分類とrouteが出る。
- mock provider E2Eでquality/environment/permission/workflow/externalを各1回通す。
- #1939 replayでpost-PR証跡不足は `external_pending` となり、コードfindingがなければlocal completeへ進む。
- 失敗再現: 「CI green必須」orderを入力し、workflow内Supervisorが`needs_fix`にしないこと。
- rollback: workflow YAMLとschemaを同時に旧版へ戻す。新ledger fieldsはoptionalのまま残す。
- 対応種別: 誤REJECTの**防止**、non-actionable findingの**早期検出**、外部gateへの**再分類**。

### 5. W3 — auto-commit・PR preflight

#### 確認済みの根本原因と根拠

- 12件（#2009/#2001/#2002/#2003/#2018/#2023/#2037/#2063/#2064/#2019/#1938/#1799）はworkflow完了後、同じ `Auto-commit failed before PR creation.` でfailedになった。
- `postExecutionFlow → autoCommitAndPush → AutoCommitter.commitAndPush → stageAndCommit` は `git add -A` の後に `git commit --no-verify` を実行する。
- runtimeは `XDG_CONFIG_HOME=<clone>/.takt/.runtime/config` を設定する。Git公式仕様ではglobal config探索に `$XDG_CONFIG_HOME/git/config` が関与する。
- 12 cloneすべてでread-only `git var GIT_AUTHOR_IDENT` / `GIT_COMMITTER_IDENT` がexit 128。1〜8分後にidentity付き非空commitが復旧されている。
- auto-commitは `core.hooksPath=/dev/null` と `--no-verify` を使うため、lefthook/Ruffは直接原因ではない。[Git commit公式](https://git-scm.com/docs/git-commit.html)も`--no-verify`がpre-commit/commit-msgをbypassするとする。
- historical exact stderr/exitは保存されていない。従ってGit identityは**再現済みの最有力根因**であり、historical stderrによる断定ではない。

生の再現要約:

```text
$ git var GIT_AUTHOR_IDENT
Author identity unknown
fatal: unable to auto-detect email address (got 'mba@mba.(none)')
exit=128
```

#### 実装仕様

- 責任層: runtime environment、clone isolation、Git adapter、postExecution、task state。
- 対象:
  - `src/core/runtime/runtime-environment.ts::{createBaseEnvironment,prepareRuntimeEnvironment}`
  - `src/infra/task/clone-exec.ts::cloneAndIsolateAbortable`
  - `src/infra/task/git.ts::stageAndCommit`
  - `src/infra/task/autoCommit.ts::commitAndPush`
  - `src/features/tasks/execute/{postExecution,taskExecution}.ts`
- 具体的変更:
  1. **staging前**にrepo/branch、author/committer identity、signing、index.lock、effective hooks/filtersをread-only検査。
  2. root repoのeffective `user.name/email` だけをclone-local configまたは限定envへbridge。credential helper、signing key、URL rewrite、filterはコピーしない。
  3. `stageAndCommit`のcommand phase、exit status、sanitized stderrを `git_commit_identity | git_index_lock | git_permission | git_commit_hook | git_commit_signing` へ分類。
  4. `workflow_status=completed` と `publication_status=failed` を分離し、commit/push/PRのみresume可能にする。
  5. PR/CI確認はpublication phaseに置き、branch/PR/run URLを保存。
- 依存: W7 failure envelope。W1/W2がpublication failureをimplement loopへ戻さないこと。
- 期待効果: 同じ環境を12回消費せず開始時またはstaging前に停止し、成果差分を保持したままpublicationだけ再実行できる。
- 工数: M。
- リスク: global Git config全体のコピーは秘密・署名・filterの境界を破壊する。identity限定bridge以外は禁止。

#### 受け入れ条件・テスト・失敗再現

- isolated XDGでもauthor/committer identがexit 0。identity値そのものはログへ出さない。
- `git add -A` より前にidentity不足を検出し、indexを変更しない。
- task ledgerにphase/category/retryable/sanitized cause/detail log pathが残る。
- empty diffは引き続きsuccess。commit済みpush failureはcommit hashを保持。
- temp repo integration: root local/global/env/欠落の4系統、hooks無効のdummy commit、push/PR fake。
- 失敗再現: runtime XDGを隔離しidentity無しで `git var` exit 128。実task worktreeではcommitしない。
- rollback: identity bridgeをfeature flagで停止し、preflight blockだけ維持。publication stateは旧`failed`互換viewを提供。
- 対応種別: identity欠落の**防止・早期検出**、generic publication failureの**再分類**。

### 6. W4 — interrupt・timeout・SIGTERM

#### 確認済みの根本原因と根拠

- #1969/#1801/#1976の直接終了原因は、archived sessionに保存された明示的 `kill -TERM`。3件とも終了直前にstream outputがあり、10分idle timeoutではない。
- #1801完了の24ms後、slot補充により#1976が開始した。TAKT worker poolはcompletion時にpendingを即claimする。
- TAKT 0.51.0は共有Ctrl+C用AbortControllerを持つが、pending cancel tombstoneとrunning task個別cancel APIを持たない。
- provider層には `external_abort`, `stream_idle_timeout`, `part_timeout` の区別があるが、task ledgerではraw `Codex Exec exited with signal SIGTERM` に潰れる。
- #1976の「実行前interrupt request」は一次ログになく、遅延interruptとは確認できない。

#### 実装仕様

- 責任層: queue claim、task lifecycle、parallel executor、provider abort、process group termination。
- 対象:
  - `src/infra/task/taskRecordSchemas.ts`
  - `src/infra/task/taskLifecycleService.ts`
  - `src/features/tasks/execute/{parallelExecution,taskExecution,workflowExecutionReporting}.ts`
  - `src/infra/codex/client.ts`
  - `src/features/tasks/list/taskForceFailActions.ts`
  - `src/infra/workflow/system/system-enqueue-effect.ts`
- 具体的変更:
  1. task recordへ `cancel_requested_at,cancel_reason,cancel_source,target_run_slug,effective_at,signal` をoptional追加。
  2. pending cancelはclaim対象外にしてprovider call前にterminal化。
  3. active mapをtask名→`{run_slug,promise,AbortController}`としtask-local abortを実装。
  4. `external/user_interrupt`, `stream_idle_timeout`, `part_timeout`, `signal_termination_unknown`, `orphaned_run` をend-to-end保持。
  5. system enqueueへ `parent_task_name,parent_run_slug,enqueue_effect_id` を付与。
  6. PID signal fallbackを使う場合はPPID/cwd/run_slugの3点一致を必須化。
- 依存: W1/W7のfailure schemaとtimestamps。
- 期待効果: cancel対象以外を止めず、timeout延長のような誤った対策を避け、pendingの不要起動を防ぐ。
- 工数: L。
- リスク: cancel/completion race、status enum波及、process settle前のslot再利用。まず既存`failed + failure.kind=user_interrupt`で互換性を優先する。

#### 受け入れ条件・テスト・失敗再現

- concurrency 3で4番目pendingをcancelし、slot解放後もprovider call数0。
- running 1件だけcancelし、他2件は継続。target run_slug不一致なら拒否。
- SDKがraw SIGTERMをthrowしても外部abort reasonがあればuser interruptを優先。
- 10分無eventだけをidle timeout、終了0.5秒前eventありはidle扱いしない。
- direct SIGTERMでsource不明ならunknownとし、user原因を推測しない。
- test command: upstream task lifecycle / parallel execution / Codex provider test suite。process fixtureはtemp child process groupだけを対象にする。
- rollback: task-local cancelをfeature flagで無効化し共有Ctrl+Cを維持。新fieldsはoptional、旧errorを併記。
- 対応種別: pending起動と誤対象signalの**防止**、abort sourceの**再分類**、race/unknown signalの**早期検出**。

### 7. W5 — worktree・Nix・lefthook

#### 確認済みの根本原因と根拠

- 通常checkout/worktreeは `.envrc` または `.lefthook/setup-worktree.sh` → Nix devShell → `.lefthook/install.sh` → `lefthook install --force`（最大3回）でhookを導入する。
- sandbox TAKT workerは `YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1` により意図的にinstallをskipし、CHANGELOG等をCIへ委譲する。
- `flake.nix` のdependency syncは失敗をwarningにしてshell入場を続け得るため、「devShell入場成功」は「依存同期成功」を意味しない。
- 12 TAKT checkoutはlinked worktreeではなく管理clone。auto-commitはhookをbypassするため、hook欠如はW3の直接原因ではない。
- `/Users/mba/02-yt/00-automation/tests/test_lefthook_installation_contract.py` はinstall retry、linked worktree path、stale wrapper fail-closed、direnv→Nix fallbackを既に固定する。

#### 実装仕様

- 責任層: repository bootstrap、Nix devShell、TAKT runtime prepare、CI。
- 対象:
  - `/Users/mba/02-yt/00-automation/flake.nix`
  - `/Users/mba/02-yt/00-automation/.lefthook/{setup-worktree,install}.sh`
  - `/Users/mba/02-yt/00-automation/.takt/runtime-prepare.sh`
  - `/Users/mba/02-yt/00-automation/.github/workflows/ci.yml`
  - `tests/test_lefthook_installation_contract.py`
- 具体的変更:
  1. read-only/default preflightでcheckout種別、runtime paths、Nix eval、`uv lock --check`、explicit `uv sync --frozen`、Git identity、hook policy（install済みまたはTAKT skip明示）を検査。
  2. explicit setup経路はdependency syncをfail-closedにする。対話shellのwarning方針は別に明示。
  3. Python CIをfrozen sync + wheel/sdist build + installed artifact smokeへ拡張。
  4. 通常worktreeとTAKT cloneの差をrun metadataへsnapshot。
- 依存: W3 identity probe、W7 run metadata。repository preflight CLIを本repoに置く場合は `src/youtube_automation/cli/` とentry pointが必要。
- 期待効果: install/network/lock/tool versionを実装前に分類し、Supervisorへ環境障害を渡さない。
- 工数: M。
- リスク: 常時preflightが重いと開始costが増える。defaultは60秒未満、Playwright/auth/buildはscope別profileへ遅延する。

#### 受け入れ条件・テスト・失敗再現

- normalはhook check-install成功、TAKTはexplicit skipが記録される。曖昧な未導入状態を許可しない。
- explicit setupでfake `uv` exit 1ならnonzero。lock driftとnetwork/cacheを別分類。
- `bash .lefthook/setup-worktree.sh uv run pytest tests/test_lefthook_installation_contract.py`
- preflight候補: `bash .lefthook/setup-worktree.sh uv run pytest tests/test_preflight.py tests/integration/test_preflight.py -n auto`
- build候補: `nix develop --command uv sync --frozen`、`nix develop --command uv build`、temp venvへwheel install後 `yt-skills list`。
- 失敗再現: fake uv exit1、invalid lock、ambient tool version、isolated XDG identity、TAKT skip envなし。
- rollback: shellHookはsoft-warningへ戻せるが、独立preflightのexplicit syncは維持。CI build jobは独立revert可能。
- 対応種別: 環境不備の**早期検出・再分類**。auto-commit hook説の誤診を**防止**。

### 8. W6 — Codexツール入力検証

#### 確認済みの根本原因と根拠

- issue #1969/#1976 sessionでは `wait_agent {"timeout_ms":1000}` が `timeout_ms must be at least 10000` で拒否された後、正しい10,000msで再試行され処理が継続した。
- Codex `wait_agent.timeout_ms` はmin 10秒、default 30秒、max 60分。これはTAKT stream idle 10分やquality gate 300秒とは別。
- `apply_patch verification failed` はexpected old linesとcurrent fileの不一致を検出する安全な非適用であり、SIGTERM原因ではない。
- parallel writerと巨大multi-file patchはstale contextのblast radiusを広げる。当時どのagentが対象行を変えたかは未確認。

生ログ抜粋:

```text
2026-07-14T10:31:07.711Z wait_agent {"timeout_ms":1000}
2026-07-14T10:31:07.731Z timeout_ms must be at least 10000
2026-07-14T10:31:09.788Z wait_agent {"timeout_ms":10000}
```

#### 実装仕様

- 責任層: Codex tool schema/usage prompt、tool wrapper、edit coordinator、task diagnostics。
- 対象: Codex multi-agent `WaitArgs`/handler、apply_patch wrapper、TAKT provider prompt/tool docs、task failure persistence。
- 具体的変更:
  1. generated usageにmin/default/maxを表示し、callerがtool call前に値を検証。
  2. 10秒未満を黙って丸めず明示validation errorを維持。
  3. edit前にread hash/mtimeとcurrent hashを比較し、差があれば再読込。
  4. patch failureへfile、hunk ordinal、read/current hashだけを記録し本文・秘密は保存しない。
  5. parallel agentにfile ownershipを割り当て、multi-file patchをfile単位へ分割。
  6. ledgerで `tool_validation_error`, `edit_conflict`, `signal_termination` を分離。
- 依存: W7 diagnostics envelope。multi-agent file ownershipはorchestrator policyと連携。
- 期待効果: 局所回復可能errorをterminal failure原因に見せず、stale patchを安全に止める。
- 工数: M。
- リスク: hash guardのfalse positive、hash/pathの情報漏洩。content hashは許容するがfile本文を記録しない。

#### 受け入れ条件・テスト・失敗再現

- `wait_agent(9999)` は局所schema error、`10000` は開始、省略は30秒。unknown fieldは拒否。
- invalid waitはtask terminal failureにならない。
- expected line 1文字差でpatch非適用・hash不変、再読込後は成功。
- 2 writer fixtureで後続writerがhash差を検知。multi-file不一致で部分適用しない契約を固定。
- rollback: hash guardはfeature flagで停止可能。ただし既存apply_patch検証とwait最小値は安全境界として残す。
- 対応種別: schema違反・stale editの**防止・早期検出**、terminal signalとの**再分類**。

### 9. W7 — 構造化ログとメトリクス

#### 確認済みの根本原因と根拠

- task ledgerの `failure.error` はterminal SIGTERMと先行WARN/tool errorを1文字列へ連結し、因果を誤認させる。
- Codex analytics failure、plugin icon、personality fallback、SQLite slow queryはすべてWARN後に処理継続。対象3件のfatal causeはSIGTERM。
- TAKT observabilityは有効だったが、worktree/run directory削除後はmonitor/usage event全量を回収できなかった。
- 対象runにはCPU/RSS/DB wait/API status/network latencyの時系列がなく、resource競合、OOM、rate limitを原因認定できない。
- `stageAndCommit` のNode例外はstatus/stdout/stderrを持ち得るが、`postExecutionFlow`がgeneric messageへ潰した。

#### 実装仕様

- 責任層: task ledger schema、workflow spans、provider diagnostics、resource sampler、postExecution logger、retention/export。
- 共通failure envelope案:

```json
{
  "schema_version": 1,
  "phase": "workflow|tool|publication|provider|environment",
  "kind": "signal_termination",
  "classification": "user_interrupt|stream_idle_timeout|git_commit_identity|...",
  "retryable": false,
  "owner": "orchestrator",
  "step": "supervise",
  "command": "<sanitized>",
  "exit_code": 143,
  "signal": "SIGTERM",
  "requested_at": "<UTC>",
  "effective_at": "<UTC>",
  "detail_log_path": "<run-local path>"
}
```

- 具体的変更:
  1. terminal failure、stderr diagnostics、WARN、tool errorsを別配列/fieldで保存。legacy error文字列も併記。
  2. run metaへTAKT/Codex/version、effective concurrencyとprovenance、cwd/run_slug、runtime profile、workflow hashをsnapshot。
  3. 5〜10秒resource sample: PID/CPU%/RSS/load、SQLite busy/pool acquire/query p95、API status class/Retry-After、network elapsed。未計測は0でなく`not_measured`。
  4. Git/analytics/provider logはstatus/error class/attempt/elapsedをsecret-freeで記録。
  5. task終端summaryをworktree外のretained storeへexportし、run削除後もclassificationと参照を残す。
  6. log level: cancel INFO、retry/timeout WARN、unknown terminal signal ERROR、resource sample metric/DEBUG、analytics delivery WARN。
- 依存: 全W1〜W6がproducer/consumer。最初にschemaとredaction contractを確定する。
- 期待効果: 「起きたこと」と「原因」を分け、再現不能でもunknownを正しく残す。MTTR、誤retry、誤REJECTを減らす。
- 工数: L。
- リスク: cardinality、I/O overhead、secret漏洩、retention cost。command/pathはsanitizeし、task executionをexporter成功へ依存させない。

#### 受け入れ条件・テスト・失敗再現

- terminal recordだけでphase/kind/classification/retryable/target run/timeを追跡可能。
- WARN配列にanalytics failureがあってもterminal causeへ昇格しない。
- resource sampler欠測は`not_measured`。CPU/RSS/DB/API/networkを推測しない。
- 429/5xx/transport、SQLite busy 0/非0、Git identity/index lock、SIGTERM source known/unknownをfixtureで区別。
- exporter停止・disk fullでもtask本体は継続し、欠測をWARNで記録。
- rollback: exporter/samplerを独立flagで停止。structured fieldsはoptional、旧error文字列を維持。
- 対応種別: 全失敗の**早期検出・再分類**。直接の防止はW1〜W6へ委ねる。

### 10. 依存関係と短中長期の移行順序

```text
短期: schema/観測（壊さず足す）
  W7 failure envelope + redaction
      ├─ W1 abort metadata伝播
      ├─ W3 Git identity preflight / detail保持
      └─ W4 abort source / cancel audit fields
  W2 promptでlocal qualityとexternal gateを分離
  W5 read-only preflight
  W6 usage validation / edit hash logging

中期: 制御（分類に基づき動かす）
  W1 typed terminal + finding fingerprint loop limit
  W3 publication state/resume + PR/CI post gate
  W4 task-local cancel + pending tombstone + lineage
  W5 frozen sync/build CI

長期: 最適化（計測後に調整）
  W7 resource sampler/retention/dashboard/SLO
  retry/backoff・concurrency・timeoutのデータ駆動調整
```

#### 短期（1〜2 release）

1. optional failure envelopeとlegacy併記、redaction contractを導入。
2. Git identity preflightを`git add`前に配置し、12件の再発を最短で止める。
3. Supervisor promptをlocal readiness限定にし、#1939 fixtureを追加。
4. abort kind、provider abort cause、publication phaseをtask recordまで透過させる。
5. read-only environment preflightとCodex tool usage validationを導入。

#### 中期（2〜4 release）

1. typed ABORT schema、finding fingerprint loop detector、child workflow metadataを有効化。
2. task-local cancel/pending tombstone/lineageを実装。
3. workflow completedとpublication failedを別stateにし、commit/push/PR/CIだけresume。
4. explicit setupのfrozen sync、CI build/artifact smokeを追加。

#### 長期（計測基盤が安定後）

1. resource samplerとretained terminal summaryを展開。
2. 実測p95/p99からtimeout・retry・concurrencyを調整。今回の3件を根拠に先にtimeout延長やconcurrency低下をしない。
3. classification別SLO（non-converging reject、environment blocker、publication failure、unknown signal）を可視化。

### 11. 優先順位付き実装slice

| 順 | slice | 完了定義 | 主依存 |
|---:|---|---|---|
| 1 | Failure Envelope v1 | task recordへoptional structured failure、legacy reader green | なし |
| 2 | Git Publication Guard | identity preflight、sanitized commit detail、publication state | 1 |
| 3 | Review Verdict v2 | local/external分離、#1939 replay green | 1 |
| 4 | Abort Provenance | engine/provider→ledgerでkind/cause保持 | 1 |
| 5 | Task-local Cancel | pending tombstone、targeted AbortController、race test | 4 |
| 6 | Environment Preflight | Nix/lock/sync/hook policy/identity分類 | 1,2 |
| 7 | Tool Safety Contract | wait schema docs、hash guard、edit conflict分類 | 1 |
| 8 | Retained Metrics | resource sampler、summary export、SLO | 1,4 |

## 主要な発見のサマリー

1. 最大の共通欠陥は、上位層に存在する分類情報がtask ledgerとpostExecutionでgeneric文字列へ潰れることである。
2. #1939はコード品質ではなくphase設計の失敗で、workflow内Supervisorにworkflow成功後のPR/CI証跡を要求した循環依存である。
3. auto-commit 12件の最有力根因はXDG隔離で隠れたGit identity。lefthook、Ruff、empty diffは一次コードと復旧証拠から直接原因を除外できる。
4. #1969/#1801/#1976はidle timeoutではなく明示SIGTERM。timeout延長は再発防止にならない。
5. `wait_agent(1000)` とpatch verification failureは局所tool errorでありterminal SIGTERMではない。
6. 通常worktreeとTAKT sandbox cloneのhook差は意図的だが、依存sync、identity、publicationとの統合preflightが不足する。
7. 最短の安全な導入は「optional schema → preflight/detail保持 → prompt/transition/cancel制御 → resource最適化」のreader-first順序である。

## 注意点・リスク

- TAKT upstreamのsource変更は本リポジトリではなく `nrslib/takt` 側の責任。ローカルproject workflow/prompt変更とupstream engine変更を別PRに分ける。
- status enumを先に増やすと既存CLI/MCP/ACP/serializerを壊す。まずoptional `failure.kind` とphaseで表現する。
- XDG隔離全体を解除したりglobal Git configを丸ごとコピーするとcredential、署名、URL rewrite、filterを持ち込む危険がある。
- retryableは「同一入力の再実行で成功可能性がある」場合だけtrueにする。identity/auth/policyを無条件retryしない。
- run pathはworktree清掃で失われる。terminal summaryは外部retained storeへ出すが、秘密値・cookie・token・Git identity値を保存しない。
- resource sampler導入前のCPU/RSS/DB/API/network原因はunknownであり、推測で分類しない。
- 本報告の工数は相対見積りであり、upstream test構成・review SLAを実測していない。

## 調査できなかった項目と理由

1. 12件のhistorical `git commit` exact exit/stderr: postExecutionが保存していない。identity exit 128は同条件再現でありhistorical raw logではない。
2. auto-commit失敗時のindex.lock/errno/permission: failure時snapshotがなく現在は復旧済み。
3. #1969/#1976 signal時の展開後PIDとkernel signal audit: archived commandは送信を示すがPID stdout/syscall auditはない。
4. #1976の実行前cancel request: 一次ログに存在せず、遅延interruptの前提を確認できない。
5. 対象runのCPU/RSS/load/DB wait/API status/network latency: 当時未計測またはrun directory削除済み。
6. patch失敗時に対象行を変更した主体と全hunkの当時snapshot: file provenance/worktreeが残っていない。
7. upstream TAKTの実装時に使う正確なtest script名とCI所要時間: 本調査は配布版とtag sourceの読み取りで、upstream開発checkoutでの実行はしていない。
8. 提案変更の性能改善量、失敗率低下率: 実装前でbaseline metricがないため定量化不能。

## 推奨／結論

最優先は、TAKT upstreamでFailure Envelope v1を導入し、同じvertical sliceでGit identity preflightとabort/publication detailの永続化を行うことである。次にproject workflowのSupervisor/reviewerをReview Verdict v2へ切り替え、#1939を回帰fixtureにする。その後、task-local cancelとpending tombstoneを実装し、#1969/#1801/#1976型のsignal provenanceを保持する。

worktree/Nix/lefthook、Codex tool validation、resource metricsは独立課題ではなく、この共通分類へ入力を供給する層として接続する。timeout延長、concurrency低下、全global config共有、generic retryは、今回確認できた根因に対応せず副作用が大きいため先行しない。
