# Plan 035: CI autofix の発火しきい値を critical+warning に上げ、info-only レビューでの Opus 起動を止める

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 9996de7b..HEAD -- .github/workflows/ci-autofix.yml tests/repo/test_ci_autofix_workflow.py`
> 変更があれば「Current state」の抜粋と実物を突き合わせ、一致しなければ STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none（034 と独立。同時進行可 — 触るファイルが非重複）
- **Category**: dx
- **Planned at**: commit `9996de7b`, 2026-08-23
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4602

## Why this matters

[ci-autofix.yml](../.github/workflows/ci-autofix.yml) は Code review workflow の完了ごとに gate を
評価し、レビュー指摘が **1 件でもあれば**（`critical + warning + info > 0`）Opus の自動修正
セッションを起動して PR へ commit を push する。レビューはほぼ毎回 info（simplify 系の提案）を
少なくとも 1 件は出すため、実質ほぼ全 PR で「Opus セッション → push → CI + sonnet レビューの
再実行」という 2 周目のパイプラインが走る。1 日 30〜40 PR の運用ではこれが Opus クォータの
主要消費源になっている。severity の定義（code-review.yml のプロンプト）上、critical = Spec 違反・
バグ相当、warning = リポジトリ規約違反、info = simplify 提案なので、**info-only は自動修正の
対象から外し、人間または次の変更に委ねる**のが妥当。critical / warning を含む場合の挙動
（全 severity をまとめて修正する）は変えない。

## Current state

対象ファイルと役割:

- `.github/workflows/ci-autofix.yml` — workflow_run 起点の自動修正。`gate`（修正要否判定）→
  `autofix`（Opus 実行）の 2 job
- `tests/repo/test_ci_autofix_workflow.py` — 上記の contract test（**必ず同時更新**）

現状の判定部（ci-autofix.yml:104-118、gate job の `decide` step 内）:

```bash
            summary="$(awk '/^---[[:space:]]*$/{exit} {print}' <<<"$review_comment")"
            severity_count() {
              # 表・箇条書き・太字・括弧と、3 severity を 1 行に連結する形式を
              # 許容する。severity と件数の間は空白・記号だけに限定する。
              grep -ioE "${1}[[:space:][:punct:]]*[0-9]+" <<<"$summary" \
                | head -n 1 | grep -oE '[0-9]+' | head -n 1
            }
            critical_count="$(severity_count critical)"
            warning_count="$(severity_count warning)"
            info_count="$(severity_count info)"
            [ -n "$critical_count" ] && [ -n "$warning_count" ] && [ -n "$info_count" ] \
              || skip "code review severity summary could not be parsed"
            [ "$((critical_count + warning_count + info_count))" -gt 0 ] \
              || skip "code review reported no findings"
```

contract test 側の関連 assertion（tests/repo/test_ci_autofix_workflow.py::test_review_runs_skip_without_findings_and_supply_the_aggregate_comment、:70-91）:

```python
    assert "critical_count" in decide["run"]
    assert "warning_count" in decide["run"]
    assert "info_count" in decide["run"]
    ...
    assert 'skip "code review reported no findings"' in decide["run"]
```

autofix job のプロンプト（ci-autofix.yml:170-172）には「レビュー起点では全 severity の指摘を
修正し、一部だけ直した commit を push しない」とあり、**これは変更しない**（発火した以上は
info も含めて一括修正するのが正しい — 変えるのは発火条件だけ）。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 依存同期 | `nix develop --command uv sync` | exit 0 |
| 対象 contract test | `nix develop --command uv run pytest tests/repo/test_ci_autofix_workflow.py -q` | all pass |
| workflow 構文全体 | `nix develop --command uv run pytest tests/repo/test_actions_parallel_workflows.py -q` | all pass |
| Lint | `nix develop --command uv run ruff check . && nix develop --command uv run ruff format --check .` | exit 0 |

## Scope

**In scope**:
- `.github/workflows/ci-autofix.yml`（decide step の判定 2 行と skip メッセージのみ）
- `tests/repo/test_ci_autofix_workflow.py`

**Out of scope**:
- `.github/workflows/code-review.yml` — severity の定義・レビュー本体は変更しない（Plan 034 の領分）
- autofix プロンプト本文・モデル指定（opus）・1 PR 1 回制限（`[ci-autofix]` マーカー）— 全て現状維持
- `changelog.d/` — 変更パスが CHANGELOG ゲート対象外のため fragment 不要

## Git workflow

- 作業は必ず linked worktree（`$REPO_ROOT/.claude/worktrees/<slug>/`）上で行う
- GitHub issue を起票し、ブランチ名は `issue-<N>-autofix-severity-threshold` 形式
- commit は日本語 Conventional Commits + タイトル末尾 `(#<issue 番号>)`、1 branch 1 commit
  （例: `fix(ci): autofix の発火を critical+warning に限定する (#NNNN)`）
- push / PR 化はオペレーターの指示があるときのみ

## Steps

### Step 1: gate の発火条件を critical+warning に変更する

ci-autofix.yml の decide step で、次の 2 行:

```bash
            [ "$((critical_count + warning_count + info_count))" -gt 0 ] \
              || skip "code review reported no findings"
```

を次に置き換える（info_count の**取得と検証は残す** — summary が parse 可能であることの
ガードとして機能しているため）:

```bash
            [ "$((critical_count + warning_count))" -gt 0 ] \
              || skip "code review reported no critical or warning findings (info-only is not auto-fixed)"
```

**Verify**: `nix develop --command uv run pytest tests/repo/test_ci_autofix_workflow.py -q` →
`test_review_runs_skip_without_findings_and_supply_the_aggregate_comment` **だけ**が fail する
（`'skip "code review reported no findings"'` の文字列 assert）

### Step 2: contract test を新しい契約に更新する

`tests/repo/test_ci_autofix_workflow.py` の
`test_review_runs_skip_without_findings_and_supply_the_aggregate_comment` を更新:

- `assert 'skip "code review reported no findings"' in decide["run"]` を
  `assert 'skip "code review reported no critical or warning findings' in decide["run"]` に変更
- 新しい発火条件そのものを固定する assert を追加:

```python
    # info-only のレビューでは Opus を起動しない(発火は critical+warning のみ)
    assert '[ "$((critical_count + warning_count))" -gt 0 ]' in decide["run"]
    assert "critical_count + warning_count + info_count" not in decide["run"]
    # summary の parse 可能性ガードとして info_count の取得・検証は残す
    assert "info_count" in decide["run"]
```

docstring やコメントで意図（info = simplify 提案は自動修正しない）を 1 行残すこと。

**Verify**: `nix develop --command uv run pytest tests/repo/test_ci_autofix_workflow.py -q` → all pass

## Test plan

- 既存 test の更新 + 発火条件を固定する assert 追加（Step 2）。severity パーサ自体の挙動 test
  （`test_review_severity_parser_*`）は無変更で green のまま
- 実行: `nix develop --command uv run pytest tests/repo/test_ci_autofix_workflow.py -q` → all pass

## Done criteria

- [ ] `nix develop --command uv run pytest tests/repo/test_ci_autofix_workflow.py tests/repo/test_actions_parallel_workflows.py -q` が exit 0
- [ ] `grep -c "critical_count + warning_count + info_count" .github/workflows/ci-autofix.yml` が 0
- [ ] `grep -c 'severity_count info' .github/workflows/ci-autofix.yml` が 1（info の取得は残存）
- [ ] `git status` で In scope の 2 ファイル以外に変更がない

## STOP conditions

- decide step の判定部が「Current state」の抜粋と一致しない（すでに誰かが条件を変えている）
- Step 1 の Verify で想定外の test も fail した（契約の理解がずれている — 修正せず報告する）

## Maintenance notes

- **観測ポイント**: 適用後 1〜2 週間で autofix の実行回数（`gh run list --workflow "CI autofix"` の
  70 秒超 run 数）が体感で半減するはず。warning の頻度が高すぎて効果が薄い場合、次の一手は
  「critical のみで発火」（同じ 2 行の再変更）
- **レビュアーが見るべき点**: info_count の取得が残っていること（parse 失敗の skip ガードを
  外してしまうと、summary が壊れたコメントで発火判定が誤る）
- info-only の指摘は PR コメントには引き続き表示される。放置され続ける傾向が出たら、
  週次でまとめて拾う運用（/improve の次回監査項目）を検討
