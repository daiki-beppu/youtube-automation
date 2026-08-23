# Plan 036: Skill E2E eval の pnpm devShell 不整合を修理し、日次 → 週次 cadence に変更する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 9996de7b..HEAD -- .github/workflows/evals.yml tests/repo/test_evals_workflow.py flake.nix`
> 変更があれば「Current state」の抜粋と実物を突き合わせ、一致しなければ STOP。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none（034 / 035 と独立・並列可）
- **Category**: bug + dx
- **Planned at**: commit `9996de7b`, 2026-08-23
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4603

## Why this matters

日次 cron（18:17 UTC）の [evals.yml](../.github/workflows/evals.yml) は現在**一度も成功していない**。
2026-08-21 以前は Claude 認証 secret が未設定で eval job が毎日 skip（run 全体は 6〜13 秒で
success 表示）、secret 設定後の初実走（2026-08-22、run 32591953739）は
`/home/runner/work/_temp/nix-shell.FgYK3o: line 2212: exec: pnpm: not found`（exit 127）で失敗した。
原因は既定 devShell（python / uv / ffmpeg のみ）で `pnpm dlx promptfoo` を呼んでいること —
pnpm は `.#extensions` shell にしかない（flake.nix:39-50 vs 52-58）。他の workflow は全て
`nix develop .#extensions --command pnpm ...` を使っており、evals.yml だけが逸脱している。

あわせて cadence を見直す。この eval は wf-status skill の read-only 契約 1 テストのみ
（promptfooconfig.yaml、claude-code 1 セッション・maxTurns 8）で、対象 skill の変更頻度に対して
毎日の Claude Code 実走は過剰。週次 + 手動 dispatch に落とし、クォータ消費を 1/7 にする。

## Current state

対象ファイルと役割:

- `.github/workflows/evals.yml` — 日次 cron + workflow_dispatch の promptfoo eval
- `tests/repo/test_evals_workflow.py` — 上記の contract test（cron 式・pin・step 構造を固定。**必ず同時更新**）
- `flake.nix` — 参照のみ（変更しない）。devShells.default = python314/uv/ffmpeg/time、
  devShells.extensions = nodejs_24/pnpmLatest

現状の該当箇所（evals.yml）:

```yaml
on:
  workflow_dispatch:
  schedule:
    - cron: "17 18 * * *"          # ← 5-6 行目。日次
...
      - name: Install Claude Code   # ← 50-53 行目
        run: |
          nix develop --command npm install --global --prefix "$RUNNER_TEMP/claude-code" @anthropic-ai/claude-code@2.1.226
          echo "$RUNNER_TEMP/claude-code/bin" >> "$GITHUB_PATH"
      - name: Run skill E2E eval    # ← 54-61 行目
        id: promptfoo
        continue-on-error: true
        run: |
          mkdir -p evals/results
          nix develop --command pnpm dlx promptfoo@0.122.0 eval \
            -c evals/promptfooconfig.yaml \
            --output evals/results/ci.json
```

補足: 「Install Claude Code」の `nix develop --command npm` は既定 shell に nodejs が無いのに
動いている — runner のシステム npm に fallback しているだけで、再現性のない偶然。今回まとめて
`.#extensions` に揃える。

contract test 側で**更新が必要になる assertion**（tests/repo/test_evals_workflow.py）:

- `test_evals_workflow_is_manual_and_nightly_but_not_a_pr_gate`（:24-29）—
  `triggers["schedule"] == [{"cron": "17 18 * * *"}]` を完全一致で assert
- `test_authenticated_eval_uses_pinned_tools_and_reports_assertion_failures`（:53-65）—
  `"pnpm dlx promptfoo@0.122.0 eval" in promptfoo["run"]` は shell 変更後も部分一致で
  pass するが、shell 指定を固定する assert を新たに追加する

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 依存同期 | `nix develop --command uv sync` | exit 0 |
| 対象 contract test | `nix develop --command uv run pytest tests/repo/test_evals_workflow.py -q` | all pass |
| workflow 構文全体 | `nix develop --command uv run pytest tests/repo/test_actions_parallel_workflows.py -q` | all pass |
| pnpm 実在のローカル確認 | `nix develop .#extensions --command pnpm --version` | バージョン文字列が出る |
| Lint | `nix develop --command uv run ruff check . && nix develop --command uv run ruff format --check .` | exit 0 |

## Scope

**In scope**:
- `.github/workflows/evals.yml`
- `tests/repo/test_evals_workflow.py`

**Out of scope**:
- `flake.nix` — 既定 shell に pnpm を足す解法は取らない（shell の責務分離を崩す。
  workflow 側を `.#extensions` に揃えるのが既存慣行）
- `evals/` 配下（promptfooconfig.yaml / providers / assertions）— eval の中身は変更しない
- promptfoo / claude-code のバージョン pin — 更新しない（pin 値は contract test が固定している）
- `changelog.d/` — 変更パスが CHANGELOG ゲート対象外のため fragment 不要

## Git workflow

- 作業は必ず linked worktree（`$REPO_ROOT/.claude/worktrees/<slug>/`）上で行う
- GitHub issue を起票し、ブランチ名は `issue-<N>-evals-pnpm-weekly` 形式
- commit は日本語 Conventional Commits + タイトル末尾 `(#<issue 番号>)`、1 branch 1 commit
  （例: `fix(ci): evals の pnpm を extensions shell に修正し週次化する (#NNNN)`）
- push / PR 化はオペレーターの指示があるときのみ

## Steps

### Step 1: 2 つの step を `.#extensions` shell に切り替える

evals.yml で:

- `Install Claude Code` step: `nix develop --command npm install ...` →
  `nix develop .#extensions --command npm install ...`
- `Run skill E2E eval` step: `nix develop --command pnpm dlx ...` →
  `nix develop .#extensions --command pnpm dlx ...`

`Summarize assertions` step の `nix develop --command jq` は**変更しない**
（jq は runner のシステムに常備されており現に動作している。`.#extensions` にも jq は無いので
切り替えても意味がない）。

**Verify**: `grep -n "nix develop --command pnpm\|nix develop --command npm" .github/workflows/evals.yml` → ヒット 0 件

### Step 2: cron を週次（月曜 18:17 UTC）に変更する

```yaml
  schedule:
    - cron: "17 18 * * 1"
```

**Verify**: `nix develop --command uv run pytest tests/repo/test_evals_workflow.py -q` →
`test_evals_workflow_is_manual_and_nightly_but_not_a_pr_gate` **だけ**が fail する（cron の完全一致）

### Step 3: contract test を更新する

`tests/repo/test_evals_workflow.py`:

1. `test_evals_workflow_is_manual_and_nightly_but_not_a_pr_gate` を
   `test_evals_workflow_is_manual_and_weekly_but_not_a_pr_gate` にリネームし、
   期待値を `[{"cron": "17 18 * * 1"}]` に更新。docstring かコメントで
   「日次は対象 skill の変更頻度に対して過剰（2026-08 監査）」と理由を 1 行残す
2. `test_authenticated_eval_uses_pinned_tools_and_reports_assertion_failures` に、
   shell 不整合の回帰ガードを追加:

```python
    # pnpm / npm は .#extensions shell にしか無い(既定 shell だと exec: pnpm: not found で
    # 即死する — 2026-08-22 run 32591953739 の実障害)
    assert "nix develop .#extensions --command pnpm dlx promptfoo@0.122.0 eval" in promptfoo["run"]
    assert "nix develop .#extensions --command npm install" in steps[2]["run"]
```

**Verify**: `nix develop --command uv run pytest tests/repo/test_evals_workflow.py -q` → all pass

## Test plan

- 既存 2 test の更新 + shell 回帰ガード assert の追加（Step 3）。新規 test ファイルは不要
- 実行: `nix develop --command uv run pytest tests/repo/test_evals_workflow.py tests/repo/test_actions_parallel_workflows.py -q` → all pass

## Done criteria

- [ ] `nix develop --command uv run pytest tests/repo/test_evals_workflow.py tests/repo/test_actions_parallel_workflows.py -q` が exit 0
- [ ] `grep -c 'cron: "17 18 \* \* 1"' .github/workflows/evals.yml` が 1
- [ ] `grep -cE 'nix develop --command (pnpm|npm)' .github/workflows/evals.yml` が 0
- [ ] `git status` で In scope の 2 ファイル以外に変更がない

## STOP conditions

- evals.yml の該当 step が「Current state」の抜粋と一致しない
- `nix develop .#extensions --command pnpm --version` がローカルで失敗する
  （extensions shell の構成が変わっている — flake を触らず報告する）

## Maintenance notes

- **マージ後のオペレーター作業（executor はやらない）**: main マージ後に
  `gh workflow run "Skill E2E eval"` で手動 dispatch し、eval が最後まで走って
  Summary に assertion 結果が出ることを確認する。ここで別の失敗（promptfoo provider や
  claude-code 実行時の問題）が出たら、それは本 plan とは別の issue として起票する —
  本 plan が保証するのは「pnpm not found で即死しない」ことまで
- eval の対象を増やす（wf-status 以外の skill 契約を足す）場合、週次のままセッション数が
  増えていくので、その時点で「skill 変更があった週だけ走る」ゲートの追加を検討
- claude-code / promptfoo のバージョン pin 更新時は contract test の文字列も同時更新が必要
  （test_evals_workflow.py:59-63 が固定している）
