# TAKT role prompt / workflow template 調査データ

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象 TAKT: 0.51.0（`/Users/mba/.bun/install/global/node_modules/takt/package.json`）
- upstream: [nrslib/takt](https://github.com/nrslib/takt)
- 中心 run ID: `20260714-102251-implement-using-only-the-files-e8g626`
- 調査範囲: planner / implementer(coder) / reviewer / supervisor の persona・instruction・output contract、custom workflow、合格条件、成果物、REJECT形式、Previous Response 実装
- 信頼性: 実際に解決される installed 0.51.0 assets、dotfiles の user override、project override、保存 run prompt/log を照合。外部実行ファイルは取得していない。

## 調査項目ごとの結果と詳細

### 1. 解決される prompt と template の所在

| 種別 | 実体 / 出典 |
|---|---|
| project planner override | `/Users/mba/02-yt/00-automation/.takt/facets/instructions/plan.md` |
| global custom workflows | `/Users/mba/01-dev/dotfiles/config/.takt/workflows/{fix,lite,solid,feature,improve,docs,diagnose-fix}.yaml` |
| global review schema | `/Users/mba/01-dev/dotfiles/config/.takt/schemas/review-verdict.json` |
| builtin personas | `/Users/mba/.bun/install/global/node_modules/takt/builtins/ja/facets/personas/*.md` |
| builtin instructions | `/Users/mba/.bun/install/global/node_modules/takt/builtins/ja/facets/instructions/*.md` |
| builtin output contracts | `/Users/mba/.bun/install/global/node_modules/takt/builtins/ja/facets/output-contracts/*.md` |
| prompt assembly | `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/instruction/InstructionBuilder.js` |
| Previous Response snapshots | `/Users/mba/.bun/install/global/node_modules/takt/dist/core/workflow/engine/StepExecutor.js` |
| task wrapper | `/Users/mba/.bun/install/global/node_modules/takt/dist/infra/task/instruction.js` |

installed package は npm metadata 上 `takt@0.51.0`、repository は `https://github.com/nrslib/takt.git`。運用変更は installed asset の直接編集ではなく、dotfiles の `config/.takt/` user override または project `.takt/` override で行うべき。

### 2. 工程別の要求証跡と生成可能性

| role / step | 現行の必須証跡 | step 内生成可能性 | 問題 |
|---|---|---:|---|
| planner | 元要求、要件分解、参照資料、スコープ、既存動作、依存/import、実装方針 | 可 | acceptance を「pre-commit」「post-PR」に分類しない |
| implementer | 作業結果、変更、build、test、境界変更、scope/decisions | 可 | 自分が生成不能な external gate を明示的に pending 化する契約がない |
| reviewer | diff、実コード、tests、Policy/Knowledge 全章、finding_id | 可 | `needs_fix` と `blocked` の owner/capability が弱い。workflow により structured/non-structured が混在 |
| supervisor | 要件表、finding 再評価、検証サマリー、未確認範囲、new/persists/resolved、summary | 大半可 | persona は「テストやビルドの再実行をしない」。一方、instruction は read-only 検証を要求。外部 CI 未確認を品質 REJECT にできる |
| postExecutionFlow | commit / push / PR | workflow COMPLETE 後のみ可 | pre-COMPLETE supervisor からは到達不能 |
| post-PR gate | CI結果、review/merge readiness | PR後のみ可 | `fix` workflow に専用 step がない |

### 3. role prompt ごとの変更仕様（編集は未実施）

#### A. Planner

**変更前の問題**

- project `plan.md` instruction は要件・既存動作・依存を丁寧に分解するが、受入条件の実行 phase と capability owner を記録しない。
- builtin planner persona の「常に最適な構造」「既存コードに構造上の問題があれば…リファクタリング」は、同じ persona 内の「明記された作業のみ」「一般論を要件化しない」と緊張関係がある。成功条件に影響しない構造改善を計画へ混入させる余地がある。
- issue #1939 では `GitHub CI green` を pre-commit supervise でも満たす必要があるように受け渡した。

**変更後責務**

- 各 acceptance criterion を `local-edit` / `local-readonly` / `post-commit` / `post-PR` / `human` に分類する。
- `required_capability`、証跡を作る owner、失敗時の遷移先を固定する。
- post-PR 条件を実装完了条件へ混ぜず、最終リリース/merge readiness 条件として保持する。

**必須出力**

```markdown
## 受入条件フェーズ表
| 条件 | phase | owner | required capability | 証跡 | このworkflow内で生成可能か | 未達時の遷移 |
```

**合格条件**

- すべての受入条件に phase / owner / capability がある。
- `生成可能か=不可` の条件は implement/review loop の APPROVE 条件にしない。
- 暗黙要求には元の明示要求への参照がある。

**対象ファイル（提案）**

- project override: `/Users/mba/02-yt/00-automation/.takt/facets/instructions/plan.md`
- general persona: `/Users/mba/.bun/install/global/node_modules/takt/builtins/ja/facets/personas/planner.md` の upstream source
- output: `/Users/mba/.bun/install/global/node_modules/takt/builtins/ja/facets/output-contracts/plan.md` の upstream source

**テスト**

- prompt snapshot: CI green を含む issue から phase 表が生成される。
- workflow lint: implement/review より後の capability を要求する条件を検出する。
- regression fixture: issue #1939 order.md を入力し、CI owner が `post_execution` になる。

**受け入れ条件**

- `takt prompt fix/lite/feature` で phase 表要求が見える。
- issue #1939 fixture で implementer の完了条件に GitHub CI green が含まれない。

**ロールバック**

- project `plan.md` override の変更だけを戻し、旧 output contract へ戻す。schema/workflow変更とは別 commit に分離する。

#### B. Implementer / fix / fix-supervisor

**変更前の問題**

- builtin `fix.md:20-27` は open findings の全処理と build/test 実行を要求するが、現在 step で構造的に解消不能な finding は自由文 blocker にするだけ。
- `fix-supervisor.md:1-15` は report directory を一次情報にするが、指摘の `actionable_in_step` 判定、required capability、owner の必須出力がない。
- custom `fix.yaml:108-114` は `fix_supervisor` が「修正を進行できない」場合も supervise に戻す。この遷移が #1939 の空転を直接許した。
- #1939 の生応答は「commit/push禁止…確認できません」と正しく報告したが、同じ supervisor に再投入された。

**変更後責務**

- finding を修正前に `actionable` / `disputed` / `blocked` / `external_pending` に分類する。
- step 禁止操作や後続 phase を要する finding はコードを触らず structured blocker として返す。
- `修正を進行できない → supervise` を廃止し、orchestrator 判定または ABORT/post-execution へ送る。

**必須出力**

```markdown
## Finding disposition
| finding_id | class | actionable_in_step | required capability | owner | action/evidence | acceptance test |
```

**合格条件**

- quality finding は修正＋適切なテストで green。
- `actionable_in_step=false` を「修正完了」と表現しない。
- external pending だけの場合、ソース差分を追加せず orchestrator へ返す。

**対象ファイル（提案）**

- upstream instructions: `.../builtins/ja/facets/instructions/fix.md`, `fix-supervisor.md`, `implement.md`
- workflow override: `/Users/mba/01-dev/dotfiles/config/.takt/workflows/fix.yaml`
- schema: `/Users/mba/01-dev/dotfiles/config/.takt/schemas/review-verdict.json` または専用 `fix-disposition.json`

**テスト**

- quality defect → fix → supervise。
- permission blocker → orchestrator/ABORT、supervise へ戻らない。
- external CI pending → post-execution。
- 同一 non-actionable finding が2回連続しても implementer を再起動しない。

**受け入れ条件**

- #1939 fixture はコード finding 解消後、`fix_supervisor` を8回起動せず終了する。
- fixer の output に required capability と owner が必ずある。

**ロールバック**

- `fix.yaml` の新分岐を旧3-step遷移へ戻し、専用 schema 参照を外す。instruction本文は互換的な追加なので最後に戻す。

#### C. Reviewer

**変更前の問題**

- coding reviewer は「場所、影響、修正方針」を要求し、architecture output contract は `finding_id` を必須化している点は良い。
- 一方、review policy の「数秒〜数分で修正可能な問題は REJECT」等は時間推定に依存し、具体的な acceptance test より作業量を判定軸にしている。
- custom lite は `approved | needs_fix | blocked` を structured に返すが、custom fix supervisor は自然言語 rule と Markdown report。workflow 間で REJECT形式が揺れる。
- reviewer が生成不能な CI 証跡を `needs_fix` にすると、実装者へ誤配される。

**変更後責務**

- blocking finding ごとに `failure_class` / `actionable_in_step` / `required_capability` / `owner` / `acceptance_test` を出す。
- `needs_fix` はコード/テスト/文書変更で現在 edit step が解消できるものだけ。
- 環境・権限は blocked、PR/CI は external_pending、workflow矛盾は workflow blocked。
- 時間推定ではなく、要件違反・再現可能な影響・明示的な期待結果で blocking を決める。

**必須出力**

- `data-supervisor-rejections.md` の提案 JSON schema。
- Markdown reportを残す場合も同フィールドを表としてミラーする。

**合格条件**

- finding には file:line/URL、期待結果、修正主体がある。
- `needs_fix` の全 finding が `actionable_in_step=true`。
- 外部条件だけでは品質 verdict を downgrade しない。

**対象ファイル（提案）**

- `/Users/mba/01-dev/dotfiles/config/.takt/schemas/review-verdict.json`
- `/Users/mba/01-dev/dotfiles/config/.takt/workflows/{lite,solid,feature,improve,docs,diagnose-fix}.yaml`
- upstream `review-coding.md`, `review-arch.md`, `review.md`,各 review output contract

**テスト**

- JSON schema validation: verdict と failure_class の不正組合せを拒否。
- reviewer prompt snapshot: CI pending を external_pending に分類。
- finding_id 再利用時に class/owner が無断で変われば検出。

**受け入れ条件**

- 全custom workflow が同じ verdict schema を使う。
- `needs_fix + actionable_in_step=false` は doctor/CI で invalid。

**ロールバック**

- schema enum を旧3値へ戻し、workflow の deterministic `when:` を旧条件へ戻す。reportの追加列は残しても後方互換。

#### D. Supervisor

**変更前の問題**

- persona `supervisor.md` は「コード品質レビューをしない」「テストやビルドの再実行をしない」と定義する一方、DoD は build/動作証跡を必須視する。証跡が後続 phase にしかない場合の扱いがない。
- instruction `supervise.md:10-22` は「未充足が1つでもあれば REJECT」。output contract は未確認範囲を `APPROVE可 / REJECT理由` にするが、phase/capability分類がない。
- custom `fix.yaml:68-71` は `すべて問題なし → COMPLETE`、`要求未達成、テスト失敗、ビルドエラー → fix_supervisor` の2分岐だけ。environment / permission / workflow / external pending を quality failure と同じ帰路へ送る。
- #1939 では「コミット・PR 作成後」の行為を fixer に要求し続けた。

**変更後責務**

- validation を品質判定と phase readiness 判定に分ける。
- 要件が未充足でも、当該 step で解消不能なら REJECT/needs_fix ではなく class別に route する。
- external pending の場合、local quality verdict を approved として固定し、必要な後続 gate を列挙する。
- 同じ non-actionable finding の反復を検知し、2回目で workflow defect として停止する。

**必須出力**

```markdown
## Local quality verdict
## Phase readiness verdict
## Blocking findings（class / owner / capability / actionable / acceptance test）
## External gates pending
## Route decision
```

**合格条件**

- quality REJECT は、実装者が現在 step で直せる具体的欠陥がある場合のみ。
- permission/workflow/external は別 verdict と route。
- APPROVE summary に未実行コマンドの成功を捏造しない。

**対象ファイル（提案）**

- upstream `.../personas/supervisor.md`
- upstream `.../instructions/supervise.md`
- upstream `.../output-contracts/supervisor-validation.md`, `summary.md`
- `/Users/mba/01-dev/dotfiles/config/.takt/workflows/fix.yaml`
- `/Users/mba/01-dev/dotfiles/config/.takt/schemas/review-verdict.json`

**テスト**

- local quality green + CI pending → external_pending/post_execution。
- missing focused test caused by code → needs_fix/implementer。
- daemon unavailable → blocked/orchestrator。
- no credential → blocked/human。
- repeated non-actionable finding → loop stop。

**受け入れ条件**

- #1939 fixture が `VAL-NEW-execution-evidence` を quality REJECT にしない。
- supervisor → fixer の遷移は `actionable_in_step=true` の finding がある場合だけ。

**ロールバック**

- supervisor output contract の新sectionを外し、workflow ruleを旧自然言語2分岐へ戻す。保存済みreportはMarkdownなので閲覧互換を維持。

### 4. Previous Response 引継ぎ処理

一次実装:

- `InstructionBuilder.js:17-35`: Previous Response は最大2,000文字へ切り詰め、truncated時は snapshot path を注記。
- `InstructionBuilder.js:91-100`: `passPreviousResponse` が true かつ previous output がある場合だけ prompt へ注入。
- `StepExecutor.js:68-84`: step名・iteration・timestamp付き snapshot と `latest.md` を保存。
- `workflowStepNormalizer.js:202-211`: `pass_previous_response` の既定は true。
- `infra/task/instruction.js:1-7`: task wrapper は「Report Directory を primary history」「previous response / conversation summary に依存するな」と明示。

issue #1939 の `fix.yaml` は supervise と fix_supervisor の双方で `pass_previous_response: false`。それでも情報は Report Directory の `supervisor-validation.md` と `fix-supervisor-verification.md` 経由で継承された。したがって空転の原因は Previous Response の欠落ではない。

問題点:

- 既定 true と task wrapper の「依存するな」は表面的に矛盾する。実際の優先順位は report > file > previous response だが、すべてのroleで同じ強さに明文化されていない。
- 2,000文字切り詰め後も source path は渡るが、agent が全文を読むことを強制しない。
- `latest.md` は最後の応答だけで、分類済み ledger ではない。反復時に failure class/owner が失われる。

推奨変更:

1. Previous Response は「補助・隣接stepの短期文脈」に限定し、blocking finding の正本は structured ledger/report とする。
2. truncation 時は、blocking finding があるなら source snapshot の読み取りを必須化する。
3. `pass_previous_response` の明示を workflow doctor で要求し、暗黙 default true を廃止または警告する。
4. response ではなく `finding_id + class + owner + acceptance_test + disposition` を後続へ渡す。

対象ファイル・テスト・受入・rollback:

- 対象: upstream `InstructionBuilder.js`, `StepExecutor.js`, `workflowStepNormalizer.js`, `infra/task/instruction.js`。
- tests: 2,001文字境界、truncation source、false時非注入、report優先、ledger継承、subworkflow境界。
- 受入: 同じ finding が文言揺れしても ID/class/owner/acceptance が保存される。`pass_previous_response` false でも report ledger で修正可能。
- rollback: normalizer の既定値を true に戻し、doctor warning を無効化。snapshot形式は追加フィールドのみで後方互換にする。

### 5. workflow template の変更仕様

**変更前**: custom `fix.yaml` は `fix → supervise → fix_supervisor → supervise`。supervise に structured output/blocked分岐/loop monitor がなく、`fix_supervisor` の「進行できない」も supervise に戻る。`max_steps: 24` まで空転可能。

**変更後**:

```text
fix
  → supervise
      ├─ approved → COMPLETE → auto commit/push/PR
      ├─ needs_fix(actionable) → fix_supervisor
      ├─ blocked(env/permission/workflow) → ABORT + typed report
      └─ external_pending → COMPLETE_LOCAL → post_pr_verify
post_pr_verify
  ├─ green → COMPLETE
  └─ failed → external gate failure（implement loopへ戻さない）
```

必須変更:

- supervise に `structured_output: review-verdict-v2`。
- deterministic `when:` 分岐。
- `fix_supervisor` の「修正を進行できない → supervise」を削除。
- `supervise ↔ fix_supervisor` loop monitor を追加。non-actionable同一findingは即停止、quality findingの進展だけ継続。
- post-PR verify を TAKT の postExecutionFlow と整合する位置へ追加するか、外部 orchestration の明示契約にする。

対象:

- `/Users/mba/01-dev/dotfiles/config/.takt/workflows/fix.yaml`
- `/Users/mba/01-dev/dotfiles/config/.takt/schemas/review-verdict.json`
- upstream postExecutionFlow / workflow engine（post-PR stepをengine内へ持つ場合）

テスト・受入条件:

- `takt workflow doctor fix` が成功。
- prompt preview で4分類と route が見える。
- mock provider E2Eで quality / env / permission / workflow / external の各分岐を1回ずつ通す。
- #1939 replay が16 iterationへ到達せず、コード品質green後は post-PR gateへ移る。
- PR作成失敗/CI redは typed external failure で終了し、コードを無意味に再編集しない。

ロールバック:

- workflow YAML と schema を同時に旧版へ戻す。post-PR verifierを外部に置いた場合は feature flag で無効化し、従来の auto-PR flowを維持する。

### 6. 成功例・失敗例の曖昧／矛盾／過剰条件

| 種別 | 短い引用 | 評価 |
|---|---|---|
| 成功 | 「場所、影響、修正方針を含める」 (`review-coding.md:18`) | findingが具体化する |
| 成功 | 「daemon…権限…は needs_fix ではなく blocked」 (`lite.yaml:104`) | failure classを遷移に反映 |
| 成功 | 「レポート…と実際のファイル内容を優先」 (`fix-supervisor.md:2`) | 引継ぎ正本が明確 |
| 曖昧 | 「すべて問題なし」 (`fix.yaml:68`) | 証跡不足と品質欠陥の境界がない |
| 矛盾 | 「修正を進行できない → supervise」 (`fix.yaml:113-114`) | 同じ不可能条件を再判定して空転 |
| 過剰 | 「数秒〜数分で修正可能な問題は REJECT」 (`review` policy) | 時間推定を品質gateにしている |
| 到達不能 | 「コミット・PR 作成後に…CI…記録」 (#1939 report) | current stepはcommit/push禁止 |
| 引継ぎ緊張 | default `passPreviousResponse=true` と task wrapper「依存するな」 | 補助情報か正本かをroleごとに明記すべき |

## 主要な発見のサマリー

- prompt単体より、acceptance criterion の phase/owner/capabilityを表せない出力契約と `fix.yaml` の2分岐が主因。
- `lite` 系にはすでに `blocked` と deterministic route があり、改善パターンの成功例として再利用できる。
- #1939 では Previous Response を無効にしても report経由で同じ finding が継承された。欠落ではなく分類不足が問題。
- planner→implementer→reviewer→supervisor の全roleに同じ `failure_class / actionable / owner / acceptance_test` 語彙が必要。

## 注意点・リスク

- installed `node_modules/takt` の直接編集は禁止。upstream変更または dotfiles user overrideで行う。
- schema enum追加は workflowの `when:` と同時更新が必要。片方だけではunknown verdictでABORTする。
- external_pending を安易な成功扱いにするとCI redを見逃す。必ずpost-PR gateと最終task状態を持つ。
- `blocked` を広く使いすぎると実装欠陥が逃げる。`actionable_in_step` と required capability の証拠を必須化する。

## 調査できなかった項目と理由

- upstream nrslib/takt の未公開開発ブランチ・将来設計: installed 0.51.0 と公開metadataのみを対象にした。
- TAKT upstream test suite の正確なテストファイル名: npm配布物にtestsが同梱されていない。上記は必要なテストケース仕様として提示した。
- issue #1939 の非公開FB管理情報: 権限外。

## 推奨／結論

第一優先は `fix.yaml` の structured 4分類と遷移修正、第二優先は review schema v2、第三優先は plannerのphase表と Previous Responseの明示契約である。prompt文言だけを直しても自然言語judgeが同じ帰路を選べるため不十分。#1939 の保存runを replay fixtureとして、コード品質green + external CI pending が implement loopへ戻らないことを受け入れ条件にする。
