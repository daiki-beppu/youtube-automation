# Plan 012: stale/freshness 判定の記述を freshness-rules.md へ単一ソース化する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/collection-ideate/ .claude/skills/wf-new/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none(plans/005 のルール 5「単一ソース原則」の実装例)
- **Category**: tech-debt(ドキュメント重複)
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

analytics レポートの stale 判定(相対比較 OR 絶対鮮度)が、`/collection-ideate` と `/wf-new` の 2 つの SKILL.md に**別々の散文**で書かれている。参照先として `.claude/skills/collection-ideate/references/freshness-rules.md` が既に存在するのに、両 SKILL.md が判定ロジック本体を本文に重複記述しているため、(a) 片方だけ更新されて食い違う(実際、文言は既に微妙に異なる)、(b) Sonnet 級モデルが 2 つの記述を別ルールと解釈して判定がブレる、というリスクがある。判定ロジックの正本を freshness-rules.md に置き、両 SKILL.md は「要約 1 行 + 参照」に縮約する。

## Current state

- `.claude/skills/collection-ideate/references/freshness-rules.md` — 既存の参照先ファイル(正本にする対象)。現在の内容を実読し、判定ロジックの完全な定義(下記 2 箇所の記述の和集合)を含むか確認すること。
- `.claude/skills/collection-ideate/SKILL.md:58` — 判定ロジックの記述 1:
  「`reports/analysis_*.md` が存在するが stale → fallback せず中断。stale 判定は相対比較（最新 `data/analytics_data_*.json` より古い）と絶対鮮度（収集データ自体が実行日から `freshness_days`（既定 7 日、`config/skills/collection-ideate.yaml` で上書き可）を超えて経過）の OR（#1427）。ユーザーに `/analytics-analyze` 再実行を案内（必要なら `/analytics-collect` 先行。絶対鮮度 stale では収集データ自体が古いため `/analytics-collect` → `/analytics-analyze` の順で必須）。**自動呼び出し不可**（AI 推論コスト発生のため）」
- `.claude/skills/wf-new/SKILL.md:77` — 判定ロジックの記述 2(同ロジックの別文面):
  「stale 判定は相対比較（最新 `data/analytics_data_*.json` より古い）と絶対鮮度（収集データ自体が実行日から `freshness_days` を超えて経過。この場合 `/analytics-collect` を先行案内）の OR。絶対鮮度では `/collection-ideate` と同じく `.claude/skills/collection-ideate/config.default.yaml` + `config/skills/collection-ideate.yaml` を deep-merge した解決済み `freshness_days`（既定 7 日）を使う — 詳細は `/collection-ideate` の `references/freshness-rules.md` を参照。」

差異の例: collection-ideate 側のみ「#1427」「自動呼び出し不可」を持ち、wf-new 側のみ「deep-merge した解決済み freshness_days」の説明を持つ。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |
| wf-new 契約テスト | `uv run pytest tests/test_wf_new_analytics_fallback_skill_contract.py -q` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/collection-ideate/references/freshness-rules.md`(正本化 — 必要な定義を集約)
- `.claude/skills/collection-ideate/SKILL.md`(該当段落の縮約)
- `.claude/skills/wf-new/SKILL.md`(該当段落の縮約)
- `CHANGELOG.md`

**Out of scope**:
- 判定ロジックの**内容変更**(相対 OR 絶対、既定 7 日などの規則自体は一切変えない。記述の置き場所を変えるだけ)。
- `/analytics-analyze` / `/analytics-collect` 側の記述。
- `config.default.yaml` の値。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(skills): stale 判定ロジックを freshness-rules.md へ単一ソース化`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: freshness-rules.md を正本化する

`freshness-rules.md` を実読し、上記 2 箇所の記述の**和集合**(相対比較の定義 / 絶対鮮度の定義と `freshness_days` の解決手順(deep-merge)/ OR 判定 / stale 時の案内順序(`/analytics-collect` → `/analytics-analyze`)/ 自動呼び出し不可の理由 / #1427 参照)がすべて含まれるよう追記する。既に全部あるなら変更不要。

**Verify**: `rg -n 'deep-merge|自動呼び出し不可|相対比較' .claude/skills/collection-ideate/references/freshness-rules.md` → 3 概念すべてヒット。

### Step 2: collection-ideate 側を縮約する

`collection-ideate/SKILL.md:58` の該当箇条書きを以下に置き換える(挙動指示は残し、ロジック定義を参照化):

```markdown
- `reports/analysis_*.md` が存在するが stale → fallback せず中断し、`/analytics-analyze` 再実行を案内（絶対鮮度 stale の場合は `/analytics-collect` → `/analytics-analyze` の順で必須）。**自動呼び出し不可**（AI 推論コスト発生のため）。stale 判定の定義（相対比較 OR 絶対鮮度、`freshness_days` の解決手順）は `references/freshness-rules.md` を正とする
```

**Verify**: `rg -n 'freshness-rules.md を正とする' .claude/skills/collection-ideate/SKILL.md` → 1 件。

### Step 3: wf-new 側を縮約する

`wf-new/SKILL.md:77` の stale 判定説明文を以下に置き換える:

```markdown
`reports/analysis_*.md` が存在するが stale の場合は fallback せず、`/analytics-analyze` 再実行を案内して中断する（古い分析と別入力の混在を避けるため）。stale 判定の定義は `/collection-ideate` の `references/freshness-rules.md` を正とする（相対比較 OR 絶対鮮度、既定 7 日）。
```

**Verify**: `rg -n 'freshness-rules.md を正とする' .claude/skills/wf-new/SKILL.md` → 1 件。かつ `rg -n 'deep-merge した解決済み' .claude/skills/wf-new/SKILL.md` → 0 件(重複記述が消えている)。

### Step 4: CHANGELOG 追記とテスト

```
- collection-ideate / wf-new: stale 判定ロジックの重複記述を references/freshness-rules.md へ単一ソース化（判定規則の変更なし）
```

**Verify**: `rg -n '単一ソース化' CHANGELOG.md` → 1 件。`uv run pytest tests -q --ignore=tests/integration` → exit 0(特に `test_wf_new_analytics_fallback_skill_contract.py`)。

## Test plan

`tests/test_wf_new_analytics_fallback_skill_contract.py` が wf-new の fallback 記述を契約として検証している。縮約後も pass することが必須。fail した場合、**テストが要求する文言を freshness-rules.md ではなく wf-new 本文に残す方向で調整**する(契約テストが正)。

## Done criteria

- [ ] freshness-rules.md に判定ロジックの完全な定義がある
- [ ] 両 SKILL.md の本文からロジック本体の重複記述が消え、「〜を正とする」参照になっている
- [ ] 判定規則の内容(相対 OR 絶対、7 日、案内順序)がどこにも変わっていない
- [ ] `uv run pytest tests -q --ignore=tests/integration` が exit 0
- [ ] `CHANGELOG.md` 追記済み、`plans/README.md` の 012 行を更新済み

## STOP conditions

- freshness-rules.md の既存内容が 2 つの SKILL.md の記述と**矛盾**している(単なる欠落ではなく食い違い)— どれが正か判断できないため STOP して報告。
- `test_wf_new_analytics_fallback_skill_contract.py` が文言調整で解決できない形で fail する。

## Maintenance notes

- 以降、stale 判定の規則変更(日数・順序)は freshness-rules.md の 1 箇所だけを編集すればよい。SKILL.md 側に規則本体を書き戻さないこと(レビュー観点)。
- `/wf-next` にも鮮度関連の記述があれば同様の縮約候補(今回スコープ外、実読で確認した範囲では重複はこの 2 箇所)。
