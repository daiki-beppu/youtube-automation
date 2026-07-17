# Supervisor REJECT 調査データ — issue #1939

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象 TAKT: 0.51.0
- 中心 run ID: `20260714-102251-implement-using-only-the-files-e8g626`
- 公開一次資料: [issue #1939](https://github.com/daiki-beppu/youtube-automation/issues/1939) / [PR #2034](https://github.com/daiki-beppu/youtube-automation/pull/2034) / [CI run 29329862316](https://github.com/daiki-beppu/youtube-automation/actions/runs/29329862316)
- ローカル一次資料: `/Users/mba/02-yt/takt-worktrees/20260714T1022-1939-issue-1939-automation-update-p/.takt/runs/20260714-102251-implement-using-only-the-files-e8g626/`
- 信頼性: issue / PR / Actions は GitHub の first-party API (`gh`) で再取得し、run 本文は保存済み JSONL・report・meta を相互照合した。外部実行ファイルは取得していない。

## 調査項目ごとの結果と詳細

### 1. issue の合格条件と step 内生成可能性

一次資料: `context/task/order.md:19-23,39-53`、公開 issue #1939（取得日 2026-07-17）。

| 工程 | 要求証跡 | step 内で生成可能か | 判定根拠 |
|---|---|---:|---|
| fix / implement | ローカル自作 skill を無確認で削除しない実装 | 可 | edit step。差分・focused test を生成可能 |
| fix / implement | 既知 orphan は承認後に prune | 可 | 実装と dry-run/apply test を生成可能 |
| fix / implement | `--prune` / `--prune --yes` 境界テスト | 可 | `tests/test_skills_sync.py` を編集・実行可能 |
| fix / implement | 指定 pytest 成功 | 可 | 検証記録は `78 passed in 0.42s` |
| supervise | 実装行・テストログ・Ruff・diff の独立照合 | 可 | read-only で既存証跡を検証可能 |
| supervise | official CHANGELOG gate の非スキップ green | **不可** | gate は `origin/main` と committed `HEAD` 前提。run は remote なし・未コミット |
| supervise | GitHub CI green | **不可** | PR がなく、step 中は add / commit / push 禁止。CI を起動できない |
| workflow 完了後 | commit / push / PR 作成 | 可 | task は `auto_pr: true`。ただし COMPLETE 後の post-execution 責務 |
| post-PR | GitHub CI green | 可 | PR 作成後の外部状態。後続回復では全6 job SUCCESS |

issue の生抜粋:

> 「CHANGELOG ゲートと GitHub CI が green になる。」

`context/task/order.md:53`。この条件自体はリポジトリの最終受入条件として妥当だが、workflow 内 supervisor の APPROVE 条件として置くと到達不能になる。

### 2. run の状態と反復回数

一次資料:

- `/Users/mba/02-yt/00-automation/.takt/tasks.yaml:546-565`
- `meta.json:14-25,34-48`
- `monitor.json` の `takt.workflow.step.runs`
- `logs/20260714-192252-vwsqat.jsonl`

確認結果:

- task は `status: failed`、停止 step は `supervise`。
- 停止時は `currentIteration: 16`。
- `supervise` 完了は7回、`fix_supervisor` 完了は7回。iteration 16 の supervise は開始後に手動 ABORT され、固有の完了応答はない。
- tasks.yaml の保存理由は「step 内で生成不能な commit/PR/GitHub CI 証跡だけを理由に同一 REJECT が3回以上反復」。

### 3. supervisor REJECT の同一指摘・文言揺れ

保存された supervisor report 7世代はすべて `## 結果: REJECT`。同じ `VAL-NEW-execution-evidence` が表現だけを変えて継続した。

| report | 短い生抜粋 | 状態 |
|---|---|---|
| `supervisor-validation.md.20260714T103739Z:57-60` | 「成功を示す一次証跡が存在しない」 | new |
| `.20260714T104254Z:62-64` | 「GitHub CI は未実行」 | 未解消 |
| `.20260714T105338Z:67-69` | 「GitHub CI の成功証跡がない」 | persists |
| `.20260714T110020Z:68-70` | 「実判定をスキップ」 | persists |
| `.20260714T111336Z:67-69` | 「green の証跡がない」 | persists |
| `.20260714T112535Z:67-69` | 「一次証跡がない」 | persists |
| current `supervisor-validation.md:67-69` | 「コミット・PR 作成後に…記録する」 | persists |

指摘の意味は一定だが、ラベルが「実行証跡不足」「CI 未実行」「gate スキップ」「green 証跡なし」と揺れる。`finding_id` は維持されたため追跡可能だった一方、`failure_class` と `actionable_in_step` がないため、品質欠陥と workflow 前提不足を区別できなかった。

### 4. コード品質 finding と外部証跡 finding の推移

supervisor は反復中に実在するコード不備も検出した。これは成功例である。

| finding | 内容 | 結果 |
|---|---|---|
| `VAL-NEW-known-removed-skills` | 既知削除 skill の allowlist 漏れ | 修正済み |
| `VAL-NEW-legacy-prune-coverage` | doctor の legacy 3件との不一致 | 修正済み |
| `VAL-NEW-prune-cli-help` | CLI help が旧契約 | 修正済み |
| `VAL-NEW-prune-unknown-entry-contract` | unknown symlink/file を保護しない | 修正済み |
| `VAL-NEW-execution-evidence` | commit/PR/CI 後にしか得られない証跡 | step 内解消不能のまま反復 |

current supervisor report `:9-14,22-24,61-77` は、実装5要件と focused pytest をすべて ✅、コード finding 3件を resolved、new finding を「なし」とした。それでも `:15-16,58-59,69,88-89` の post-PR 証跡だけで REJECT した。

成功例の短い抜粋:

> 「unknown な directory / file / symlink / broken symlink は prune から保護される。」

`reports/fix-supervisor-verification.md:44`。具体的な対象と期待動作があり、その step でテスト可能。

失敗例の短い抜粋:

> 「コミット・PR 作成後に公式 CHANGELOG gate と GitHub CI の green 証跡を記録する」

`reports/supervisor-validation.md:69`。必要アクション自体が現在 step の禁止操作と後続 phase に依存する。

### 5. 環境／権限／workflow failure の分離

一次資料: `reports/fix-supervisor-verification.md:5-40`。

| 分類 | 生の観測 | 品質判定への扱い |
|---|---|---|
| quality | focused pytest `78 passed`、Ruff check / format、`git diff --check` 成功 | 品質 gate は合格 |
| environment | full pytest `5202 passed, 18 failed, 2 errors`。worker の `YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1` と runtime の broken symlink | 今回差分と無関係。current supervisor も「非finding分類済み / 対象外」 |
| permission/capability | add / commit / push 禁止、remote/PR 不在 | fixer へ戻しても解消不能 |
| workflow/phase-order | CI を要求する supervise が postExecutionFlow より前 | workflow 定義の不整合 |
| external pending | PR 作成後の GitHub CI | post-PR gate へ移送すべき |

### 6. workflow 外での回復による反証

GitHub first-party API で 2026-07-17 に再確認した。

- [停止コメント](https://github.com/daiki-beppu/youtube-automation/issues/1939#issuecomment-4968654236): owner が、実装 finding 解消、78 tests/Ruff成功、残件が step 内生成不能な gate/CI 証跡のみと記録。
- [回復コメント](https://github.com/daiki-beppu/youtube-automation/issues/1939#issuecomment-4968808782): 外部 supervisor が commit `62fd5231da2439ccfb37a12648fddc796dceec3e`、PR #2034、full pytest `5227 passed` を記録。
- [PR #2034](https://github.com/daiki-beppu/youtube-automation/pull/2034): 2026-07-14 20:48 JST に MERGED。意図した6ファイルの変更。
- [CI run 29329862316](https://github.com/daiki-beppu/youtube-automation/actions/runs/29329862316): lint / test / windows-cost-tracker / changelog / adr-numbering / any-gate の全6 job SUCCESS。

同一差分が post-PR phase へ移った直後に外部条件を満たしたため、元 run の最終失敗は実装品質 failure ではなく phase-order / capability mismatch だったという因果推論を強く支持する。

### 7. REJECT／BLOCKED 出力スキーマ案

現行 `/Users/mba/01-dev/dotfiles/config/.takt/schemas/review-verdict.json` は `approved | needs_fix | blocked` と自由文 feedback のみで、blocked の内訳・所有者・同一 step で解消可能かを表せない。以下へ拡張する。

```json
{
  "verdict": "approved | needs_fix | blocked | external_pending",
  "failure_class": "none | quality | environment | permission | workflow | external",
  "retry_target": "none | implementer | same_step | orchestrator | post_execution | human",
  "feedback": "string",
  "blocking_findings": [
    {
      "finding_id": "string",
      "summary": "string",
      "evidence": ["file:line or URL"],
      "acceptance_test": "具体的な期待結果と検証方法",
      "actionable_in_step": true,
      "required_capability": "edit | network | commit | push | pr | ci | credential | none",
      "owner": "implementer | reviewer | orchestrator | post_execution | human"
    }
  ],
  "verified": [{"item": "string", "evidence": ["string"]}],
  "unverified": [{"item": "string", "reason": "string", "impact": "string"}],
  "followups": []
}
```

判定不変条件:

1. `needs_fix` は blocking finding が1件以上あり、すべて `actionable_in_step=true` かつ owner が implementer の場合だけ。
2. daemon／network／credential／sandbox は `blocked`。同じ fixer へ戻さず ABORT または orchestrator へ。
3. commit／push／PR／CI が workflow 完了後の責務なら `external_pending`。品質 APPROVE を保持して post-execution gate へ送る。
4. `acceptance_test` に「何を直すか」「期待結果」「その step で実行可能な検証」を必須化する。
5. 同一 `finding_id` が `actionable_in_step=false` のまま再来したら、2回目で deterministic に loop を停止し、workflow defect として分類する。

## 主要な発見のサマリー

- issue #1939 の最終 REJECT は品質 REJECT ではない。実装 finding は解消し、focused tests と静的 gate は成功していた。
- supervisor は post-PR の CHANGELOG/CI を pre-commit step の APPROVE 条件にし、fixer は禁止された commit/push/PR を要求された。
- `VAL-NEW-execution-evidence` は7世代で反復した。文言は揺れたが、解消主体・必要 capability・phase が構造化されなかった点が本質。
- workflow 外で PR/CI を作ると全6 checks が成功しマージされた。最終失敗の分類は `workflow/phase-order` が妥当。

## 注意点・リスク

- CI green を最終受入条件から削除してはいけない。移動先は post-execution / post-PR gate である。
- 環境 failure を安易に APPROVE へ変換してはいけない。差分との因果、代替証跡、未確認範囲を残す。
- current `fix` workflow は structured output を使わず自然言語 judge に依存するため、スキーマ追加だけでは効かない。workflow の分岐も同時に変更する必要がある。
- run 保存先は worktree 内。worktree 清掃で消えるため、重要な failure summary は issue コメントや repo 内 report に残す必要がある。

## 調査できなかった項目と理由

- 非公開 libecity の元FB・投稿者情報: 権限外。公開 issue に引用された原文のみ確認。
- supervise iteration 16 の完了応答: agent 完了前に ABORT されており、raw log に開始イベントしかない。
- 当時の remote 状態の再現: 後続 recovery で状態が変化し得るため再現していない。同時刻の保存レポートを一次証跡とした。

## 推奨／結論

`fix` workflow の supervisor 判定を「品質」「環境」「権限」「workflow」「外部待ち」に分け、`needs_fix` は当該 edit step で修正可能な品質欠陥に限定する。commit／PR／CI は COMPLETE 後の post-execution gate に移し、そこが失敗した場合は実装ループへ戻さず、外部 gate failure として task を停止・報告する。issue #1939 は、この変更の回帰 fixture として保存 run ID をテスト仕様に固定できる。
