# Plan 034: Code review を diff 指紋（patch-id）で重複排除し、rebase-only push での sonnet 再レビューを skip する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 9996de7b..HEAD -- .github/workflows/code-review.yml tests/repo/test_code_review_workflow.py .github/workflows/ci-autofix.yml`
> 変更があれば「Current state」の抜粋と実物を突き合わせ、一致しなければ STOP。

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none（035 と同時着手可。ただし 035 が先にマージされた場合、本 plan は
  ci-autofix.yml を変更しないので conflict しない）
- **Category**: dx
- **Planned at**: commit `9996de7b`, 2026-08-23
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4601

## Why this matters

このリポジトリは stacked PR 運用（`gh stack merge --squash`）で 1 日 30〜40 PR をマージする。
下段 PR がマージされるたびに上段 PR 全てが rebase され `synchronize` イベントが発火し、
[code-review.yml](../.github/workflows/code-review.yml) が **diff 内容が 1 バイトも変わっていないのに**
sonnet の全差分レビュー（1 回 3〜6 分）を再実行する。実測（2026-08-23、直近 60 run）では
1 PR あたり 5〜9 回の Code review run・レビュー wall-time 1,300〜1,600 秒/PR に達しており、
Claude クォータ消費の最大要因かつ takt の CI green 待ち時間の主因になっている。
diff の指紋（`git patch-id --stable`）が前回レビュー時と同一なら claude-code-action の起動自体を
skip し、前回の判定（critical 有無）だけを再適用する。

## Current state

対象ファイルと役割:

- `.github/workflows/code-review.yml` — PR ごとの自動レビュー。`auth-check` → `review` の 2 job 構成
- `tests/repo/test_code_review_workflow.py` — 上記 workflow の構造を固定する contract test（**必ず同時更新**）
- `.github/workflows/ci-autofix.yml` — 変更しないが相互作用がある（後述）。gate は
  `<!-- code-review-workflow -->` で **始まる**コメントを `startswith` で探す（ci-autofix.yml:98）ため、
  marker が先頭行であることを壊してはならない

現状の review job の骨格（code-review.yml:43-135）:

```yaml
  review:
    needs: auth-check
    if: needs.auth-check.outputs.available == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
      - name: Run Claude code review
        id: review
        uses: anthropics/claude-code-action@4a3947e8ca609a286ab07d4d048d9ec4016798c1 # v1
        ...
      - name: Post review comment
        if: steps.review.outputs.structured_output != ''
        ...
          marker='<!-- code-review-workflow -->'
          {
            echo "$marker"
            echo
            jq -r '.report_markdown' <<<"$STRUCTURED_OUTPUT"
          } > "$RUNNER_TEMP/review-comment.md"
        ...（既存 marker コメントがあれば PATCH で上書き、なければ新規作成）
      - name: Fail on critical findings
        env:
          STRUCTURED_OUTPUT: ${{ steps.review.outputs.structured_output }}
        run: |
          set -eu
          critical=$(jq -r '.critical_count' <<<"$STRUCTURED_OUTPUT")
          ...
          if [ "$critical" -gt 0 ]; then ... exit 1
```

contract test の中で本 plan の変更に伴い**更新が必要になる assertion**（test_code_review_workflow.py）:

- `test_critical_findings_fail_the_check_via_structured_output`（:80-91）—
  `verdict["env"] == {"STRUCTURED_OUTPUT": ...}` を**完全一致**で assert している。
  skip 経路用の env 追加に合わせて更新する
- `test_review_comment_is_upserted_by_a_workflow_step_not_by_claude`（:99-118）—
  `post["if"] == "steps.review.outputs.structured_output != ''"` を完全一致で assert。
  skip 条件の AND 追加に合わせて更新する

リポジトリ規約:

- workflow の action は全て `owner/repo@<40 桁 SHA>` 形式でピン留め（`tests/repo/test_github_actions_pinning.py` が機械担保）。新 step で action は追加しないこと（shell のみで実装する）
- `.github/workflows/` の変更は CI の affected-test 選定で `tests/repo/test_actions_parallel_workflows.py` が自動実行される（.github/scripts/select-affected-tests.py:37）

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 依存同期 | `nix develop --command uv sync` | exit 0 |
| 対象 contract test | `nix develop --command uv run pytest tests/repo/test_code_review_workflow.py -q` | all pass |
| workflow 構文全体 | `nix develop --command uv run pytest tests/repo/test_actions_parallel_workflows.py tests/repo/test_github_actions_pinning.py -q` | all pass |
| autofix 相互作用 | `nix develop --command uv run pytest tests/repo/test_ci_autofix_workflow.py -q` | all pass（本 plan では無変更のまま green のはず） |
| Lint | `nix develop --command uv run ruff check . && nix develop --command uv run ruff format --check .` | exit 0 |

## Scope

**In scope**（変更してよいのはこれだけ）:
- `.github/workflows/code-review.yml`
- `tests/repo/test_code_review_workflow.py`

**Out of scope**（触らない）:
- `.github/workflows/ci-autofix.yml` — 発火条件の変更は Plan 035 の責務
- `.github/workflows/ci.yml` ほか他の workflow 全て
- `changelog.d/` — 変更パスが CHANGELOG ゲートの対象 regex（`src/youtube_automation/` /
  `.claude/skills/` / `pyproject.toml` 等）に一致しないため fragment 不要

## Git workflow

- 作業は必ず linked worktree（`$REPO_ROOT/.claude/worktrees/<slug>/`）上で行う。メイン作業ツリーで直接ブランチを切らない
- まず GitHub issue を起票し（1 issue = 1 PR 規約）、ブランチ名は `issue-<N>-code-review-dedup` 形式
- commit は日本語 Conventional Commits + タイトル末尾 `(#<issue 番号>)`、1 branch 1 commit に寄せる
  （例: `feat(ci): Code review を patch-id で重複排除する (#NNNN)`）
- push / PR 化はオペレーターの指示があるときのみ

## Steps

### Step 1: review job に diff 指紋計算と前回メタ取得の step を追加する

`code-review.yml` の review job で、checkout の直後・claude-code-action の**前**に 2 step を挿入する:

```yaml
      - name: Compute diff fingerprint
        id: fingerprint
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          set -eu
          patch_id=$(git diff "${BASE_SHA}...${HEAD_SHA}" | git patch-id --stable | cut -d' ' -f1)
          echo "patch_id=${patch_id}" >> "$GITHUB_OUTPUT"
      - name: Look up previous review
        id: previous
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          REPO: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          PATCH_ID: ${{ steps.fingerprint.outputs.patch_id }}
        run: |
          set -eu
          marker='<!-- code-review-workflow -->'
          body="$(gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" --paginate \
            --jq "[.[] | select(.body | startswith(\"${marker}\"))][0].body // empty")"
          meta="$(grep -m1 -oE '<!-- code-review-meta patch=[0-9a-f]+ crit=[0-9]+ -->' <<<"$body" || true)"
          prev_patch="$(grep -oE 'patch=[0-9a-f]+' <<<"$meta" | cut -d= -f2 || true)"
          prev_crit="$(grep -oE 'crit=[0-9]+' <<<"$meta" | cut -d= -f2 || true)"
          if [ -n "$PATCH_ID" ] && [ -n "$prev_patch" ] && [ "$PATCH_ID" = "$prev_patch" ]; then
            echo "skip=true" >> "$GITHUB_OUTPUT"
            echo "prev_crit=${prev_crit:-0}" >> "$GITHUB_OUTPUT"
            echo "::notice::diff unchanged since last review (patch-id ${PATCH_ID}); skipping paid review"
          else
            echo "skip=false" >> "$GITHUB_OUTPUT"
            echo "prev_crit=" >> "$GITHUB_OUTPUT"
          fi
```

設計上の要点（変えないこと）:

- 空 diff（`patch_id` が空）は**必ず skip=false** に倒す（レビューを走らせる方が fail-safe）
- メタ行の語彙は `crit=` を使う。`critical` という単語を含めてはならない —
  ci-autofix.yml の severity パーサ（`grep -ioE "critical[[:space:][:punct:]]*[0-9]+"`）が
  summary 先頭行から件数を拾うため、メタ行に `critical:3` のような表記があると誤検出する
  （契約は `tests/repo/test_ci_autofix_workflow.py::test_review_severity_parser_accepts_real_comment_formats_without_matching_prose`）

**Verify**: `nix develop --command uv run pytest tests/repo/test_actions_parallel_workflows.py -q` → pass（YAML として整合）

### Step 2: claude-code-action と Post comment を skip 条件でガードし、メタ行を書き込む

- `Run Claude code review` step（id: review）に条件を追加:
  `if: steps.previous.outputs.skip != 'true'`
- `Post review comment` step の条件を
  `if: steps.previous.outputs.skip != 'true' && steps.review.outputs.structured_output != ''`
  に変更し、comment 生成部を次の形にする（**marker が先頭行のまま**であること）:

```
          {
            echo "$marker"
            echo "<!-- code-review-meta patch=${PATCH_ID} crit=${critical} -->"
            echo
            jq -r '.report_markdown' <<<"$STRUCTURED_OUTPUT"
          } > "$RUNNER_TEMP/review-comment.md"
```

  `PATCH_ID` は env で `${{ steps.fingerprint.outputs.patch_id }}` を渡し、
  `critical` は `jq -r '.critical_count' <<<"$STRUCTURED_OUTPUT"` で取り出す。

**Verify**: `nix develop --command uv run pytest tests/repo/test_actions_parallel_workflows.py -q` → pass

### Step 3: Fail on critical findings を両経路対応にする

最終 step を次の形に変更する（skip 時は前回の critical 判定を再適用し、check の
green/red が rebase の前後で変わらないようにする — ここが本 plan の正しさの核心）:

```yaml
      - name: Fail on critical findings
        env:
          STRUCTURED_OUTPUT: ${{ steps.review.outputs.structured_output }}
          SKIPPED: ${{ steps.previous.outputs.skip }}
          PREV_CRIT: ${{ steps.previous.outputs.prev_crit }}
        run: |
          set -eu
          if [ "$SKIPPED" = "true" ]; then
            critical="${PREV_CRIT:-0}"
            echo "review skipped (unchanged diff); re-applying previous verdict: critical=${critical}"
          else
            critical=$(jq -r '.critical_count' <<<"$STRUCTURED_OUTPUT")
            warning=$(jq -r '.warning_count' <<<"$STRUCTURED_OUTPUT")
            info=$(jq -r '.info_count' <<<"$STRUCTURED_OUTPUT")
            echo "critical=${critical} warning=${warning} info=${info}"
          fi
          if [ "$critical" -gt 0 ]; then
            echo "::error::Code review found ${critical} critical finding(s). See the review comment on the PR."
            exit 1
          fi
```

**Verify**: `nix develop --command uv run pytest tests/repo/test_code_review_workflow.py -q` →
この時点では **fail する**（contract 未更新のため）。fail する test 名が
`test_critical_findings_fail_the_check_via_structured_output` と
`test_review_comment_is_upserted_by_a_workflow_step_not_by_claude` の 2 つ**だけ**であることを確認

### Step 4: contract test を更新し、skip 経路の新契約を追加する

`tests/repo/test_code_review_workflow.py` を更新:

1. `test_critical_findings_fail_the_check_via_structured_output` — `verdict["env"]` の完全一致を
   3 キー（STRUCTURED_OUTPUT / SKIPPED / PREV_CRIT）に更新
2. `test_review_comment_is_upserted_by_a_workflow_step_not_by_claude` — `post["if"]` の期待値を
   新しい AND 条件に更新。marker が comment 先頭であることの assert（`"<!-- code-review-workflow -->" in script`）は維持
3. 新規 test を追加（既存の関数スタイル・`_workflow()` ヘルパー流用）:

```python
def test_unchanged_diff_skips_the_paid_review_but_reapplies_the_verdict() -> None:
    review = _workflow()["jobs"]["review"]
    steps = review["steps"]

    fingerprint = next(step for step in steps if step.get("id") == "fingerprint")
    assert "git patch-id --stable" in fingerprint["run"]

    previous = next(step for step in steps if step.get("id") == "previous")
    # メタ行の語彙は crit= 固定(ci-autofix の severity パーサに "critical" を誤検出させない)
    assert "code-review-meta patch=" in previous["run"]
    assert "crit=" in previous["run"]
    assert "critical" not in previous["run"].split("code-review-meta")[1].splitlines()[0]

    assert _review_step(review)["if"] == "steps.previous.outputs.skip != 'true'"

    verdict = steps[-1]
    assert verdict["env"]["SKIPPED"] == "${{ steps.previous.outputs.skip }}"
    assert verdict["env"]["PREV_CRIT"] == "${{ steps.previous.outputs.prev_crit }}"
    assert "exit 1" in verdict["run"]


def test_review_meta_line_never_matches_the_autofix_severity_parser() -> None:
    """メタ行が ci-autofix の severity_count に数値として拾われないことの回帰ガード。"""
    import subprocess

    meta_line = "<!-- code-review-meta patch=0123abcd crit=3 -->"
    result = subprocess.run(
        ["bash", "-c", "grep -ioE 'critical[[:space:][:punct:]]*[0-9]+' || true"],
        input=meta_line,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""
```

**Verify**: `nix develop --command uv run pytest tests/repo/test_code_review_workflow.py tests/repo/test_ci_autofix_workflow.py -q` → all pass

## Test plan

- 新規 test は Step 4 の 2 本（skip 経路の構造契約 + メタ行とパーサの非干渉）。
  既存の `test_review_severity_parser_*`（tests/repo/test_ci_autofix_workflow.py:94-）を構造の手本にする
- 実行: `nix develop --command uv run pytest tests/repo/test_code_review_workflow.py -q` → 全 pass（新規 2 本含む）

## Done criteria

- [ ] `nix develop --command uv run pytest tests/repo/test_code_review_workflow.py tests/repo/test_ci_autofix_workflow.py tests/repo/test_actions_parallel_workflows.py tests/repo/test_github_actions_pinning.py -q` が exit 0
- [ ] `nix develop --command uv run ruff check .` と `ruff format --check .` が exit 0
- [ ] `grep -c "code-review-meta" .github/workflows/code-review.yml` が 2 以上（書き込みと読み出しの両方に存在）
- [ ] `git status` で In scope の 2 ファイル以外に変更がない

## STOP conditions

- code-review.yml の「Current state」抜粋が実物と一致しない（特に step 構成や marker の扱いが変わっている）
- `test_ci_autofix_workflow.py` が本 plan の変更で fail した（ci-autofix との契約を壊している。
  メタ行の語彙を見直しても解消しない場合は設計相談に戻す）
- claude-code-action の outputs 仕様（`structured_output`）が抜粋と異なることを発見した

## Maintenance notes

- **rebase 後の autofix 再発火**: レビューを skip しても workflow_run は完了するため、
  ci-autofix の gate は従来どおり動く。skip 時に comment は更新されないので、autofix が読む
  severity は前回値のまま — これは意図どおり（diff が同じなら指摘も同じ）
- **レビュアーが見るべき点**: skip 判定が「厳密一致」であること。patch-id は diff の内容だけの
  関数なので、base の進行で**コンテキスト行**が変わると別指紋になり再レビューされる（安全側）
- 見送った拡張: skip 時に comment へ「rebase 再検証済み」の追記をする案は、autofix の
  `--edit-last` 系との干渉リスクに対し益が薄いため不採用
