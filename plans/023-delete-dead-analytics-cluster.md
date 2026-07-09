# Plan 023: dead analytics/report クラスタ 3 ファイル（1,016 行）を削除する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 5394c378..HEAD -- src/youtube_automation/utils/report_generator.py src/youtube_automation/utils/report_renderer.py src/youtube_automation/utils/analytics_analyzer.py src/youtube_automation/utils/ctr_analytics.py`
> 差分が出たら Step 1 の到達可能性検査を必ずやり直す。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `5394c378`, 2026-07-09

## Why this matters

`utils/report_generator.py`（426 行）+ `utils/report_renderer.py`（127 行）+ `utils/analytics_analyzer.py`（463 行）は、analytics が現行の mixin 構成（`analytics_base.py` Protocol + `strategic_analytics.py` / `ctr_analytics.py` 等）へ移行する前の旧モノリスの残骸で、**どこからも import されていない**。実装らしい見た目（`AnalyticsAnalyzer` クラス、HTML レポート生成）のせいで「どちらの analytics 経路が正か」を読者に誤認させ、dead 側を拡張してしまう事故の温床になっている。テストもゼロなので削除はランタイムもスイートも壊し得ない。1,016 行のメンテナンス表面積が純減する。

## Current state

到達可能性は監査時に検証済み（executor は Step 1 で再検証すること）:

- `report_generator.py` — importer ゼロ。`:23-24` で `analytics_analyzer` と `report_renderer` を import している（このクラスタ内部の参照のみ）
- `report_renderer.py` — importer は `report_generator.py:24` だけ
- `analytics_analyzer.py` — importer は `report_generator.py:23` だけ。`AnalyticsAnalyzer` はどのテストにも登場しない
- 動的 import の確認済み: `importlib` / `__import__` を使うのは `cli_entrypoints.py`, `cli/skills_sync/__init__.py`, `utils/weekly_vote_log.py`, `utils/skill_config.py`, `utils/schemas/__init__.py`, `__init__.py` のみで、いずれもこの 3 モジュール名を文字列で参照しない
- `pyproject.toml` の `[project.scripts]` にこの 3 モジュールを指す entry point は無い
- 残る参照はコメント 1 行 — `src/youtube_automation/utils/ctr_analytics.py:16`:

  ```
  コレクション別ランキングは `analytics_analyzer._analyze_collection_ctrs` 側で
  ```

  これは stale なドキュメント参照であり、削除と同時に修正する

- `docs/superpowers/specs/2026-04-14-launch-curve-analysis-design.md` と `docs/superpowers/plans/2026-04-14-launch-curve-analysis.md` にも名前が出るが、これらは**過去の設計記録**（歴史文書）なので触らない

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 到達可能性 | `rg -l 'report_generator\|report_renderer\|analytics_analyzer\|AnalyticsAnalyzer' src tests --glob '!__pycache__'` | 3 ファイル自身 + `ctr_analytics.py` のみ |
| 全テスト | `uv run pytest -q` | all pass |
| Lint / Format | `uv run ruff check src tests && uv run ruff format --check src tests` | exit 0 |

## Scope

**In scope**:

- `src/youtube_automation/utils/report_generator.py`（削除）
- `src/youtube_automation/utils/report_renderer.py`（削除）
- `src/youtube_automation/utils/analytics_analyzer.py`（削除）
- `src/youtube_automation/utils/ctr_analytics.py`（`:16` 周辺のコメント 1 箇所の修正のみ）
- `CHANGELOG.md`（`[Unreleased]` 追記 — src/ を触るため必須）

**Out of scope**:

- `docs/superpowers/` 配下 — 歴史文書。参照が残っていても直さない
- CHANGELOG の**過去エントリ** — 履歴の書き換えはしない（追記のみ）
- live な analytics mixin 群（`analytics_base.py`, `strategic_analytics.py`, `ctr_analytics.py` の実コード部分, `traffic_source_analytics.py`, `audience_analytics.py`, `retention_analytics.py`）— 削除対象と名前が似ているが**現役**。1 行も変えない
- `strategic_analytics.py` の未使用 `comprehensive` モード — 監査で latent と判定されたが、削除判断は別（README の残課題参照）

## Git workflow

- worktree 上で作業。base branch は main
- commit 例: `refactor(utils): 旧 analytics モノリス残骸 3 ファイル(1,016行)を削除 (#<issue>)`
- push / PR 化はオペレーター指示時のみ

## Steps

### Step 1: 到達可能性を再検証する

```
rg -l 'report_generator|report_renderer|analytics_analyzer|AnalyticsAnalyzer' src tests --glob '!__pycache__'
```

期待: `src/youtube_automation/utils/report_generator.py`, `src/youtube_automation/utils/analytics_analyzer.py`, `src/youtube_automation/utils/ctr_analytics.py` の 3 件のみ（report_renderer は generator 経由でのみ参照されるため単体では出ないことがある）。**これ以外の src/tests ファイルが出たら STOP**。

**Verify**: 上記コマンド → 期待どおりの 3 件以下

### Step 2: 3 ファイルを削除し、コメントを修正する

`git rm` で 3 ファイルを削除。`ctr_analytics.py:14-17` 付近の docstring/コメントから `analytics_analyzer._analyze_collection_ctrs` への言及を、実際の現行実装位置（そのコメントが説明している対象。前後の文脈から `ctr_analytics.py` 自身のメソッドを指すよう書き直すか、文ごと削除）に改める。コメント以外のコード変更はしない。

**Verify**: `rg -n 'analytics_analyzer' src --glob '!__pycache__'` → 0 件

### Step 3: CHANGELOG 追記 + 全体検証

`CHANGELOG.md` `[Unreleased]` の Removed に「旧 analytics モノリスの unreachable な残骸（report_generator / report_renderer / analytics_analyzer、計 1,016 行）を削除」を追記。

**Verify**: `uv run pytest -q` → all pass / `uv run ruff check src tests && uv run ruff format --check src tests` → exit 0

## Test plan

新規テストなし（削除のみ）。全スイート green が回帰検証そのもの。削除対象にテストが存在しないことは監査で確認済み（Step 1 の rg が tests/ でヒットしないことで再確認される）。

## Done criteria

- [ ] 3 ファイルがリポジトリから消えている（`ls src/youtube_automation/utils/report_generator.py` → No such file）
- [ ] `rg -n 'report_generator|report_renderer|analytics_analyzer|AnalyticsAnalyzer' src tests --glob '!__pycache__'` → 0 件
- [ ] `uv run pytest -q` exit 0
- [ ] ruff check / format --check exit 0
- [ ] `CHANGELOG.md` `[Unreleased]` に追記
- [ ] `git status` で in-scope 外の変更なし
- [ ] `plans/README.md` の 023 行を更新

## STOP conditions

- Step 1 の rg で src/tests 内に第 4 の参照元が出た（プラン作成後に誰かが使い始めた — 削除不可）
- `uv run pytest -q` が削除後に fail し、失敗テストのトレースにこの 3 モジュールが関与している
- wheel build / force-include（`pyproject.toml`）にこれらのファイルへの明示参照が見つかった場合（監査時点では無い）

## Maintenance notes

- レビューで見るべき点: diff が「3 ファイル削除 + コメント 1 箇所 + CHANGELOG」**だけ**であること
- この削除で `utils/` の flat 化解消（監査 finding DEBT-03、未プラン化）の対象母数が 83 → 80 になる。将来 `utils/analytics/` パッケージ化をやる場合、dead code が消えている分だけ移行が単純になる
- `strategic_analytics.py` の `comprehensive` モード（呼び出し元ゼロの N+1 経路、`:208-210` / `:237-261`）は本プランで消していない。次に analytics を触る誰かが「使うか消すか」を判断すること（plans/README の残課題に記録済み）
