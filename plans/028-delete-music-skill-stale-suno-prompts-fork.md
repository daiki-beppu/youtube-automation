# Plan 028: music skill 内の stale fork `generate_suno_prompts.py` を削除する

> **Executor instructions**: この plan を上から順に実行すること。各 step の
> Verify コマンドを実行し、期待結果を確認してから次へ進む。「STOP conditions」
> のいずれかが発生したら改善を試みず停止して報告する。完了したら
> `plans/README.md` の本 plan の Status 行を更新する。
>
> **Drift check (最初に実行)**: `git diff --stat 0030e636..HEAD -- .claude/skills/music/ src/youtube_automation/commands/suno/generate_suno_prompts.py CHANGELOG.md`
> in-scope ファイルに変更があれば「Current state」の excerpt と実物を突き合わせ、
> 不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 033 (soft — CHANGELOG は fragment 方式で書く。033 が未マージの場合のみ CHANGELOG.md 直接編集に fallback)
- **Category**: tech-debt
- **Planned at**: commit `0030e636`, 2026-08-22
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4460

## Why this matters

`.claude/skills/music/references/generate_suno_prompts.py` は、本来 symlink であるべきところが **19KB の通常ファイルとして commit された古い fork** で、`src/youtube_automation/commands/suno/generate_suno_prompts.py` から 95 行分乖離している（`f33df96b` の prompt 解決リファクタが反映されていない）。`.claude/skills/` は wheel に force-include されるため、この stale fork は下流チャンネルリポジトリ全部に配布される。skill 本文はすべて `uv run yt-generate-suno` を呼ぶためこのファイルを参照する経路はゼロだが、`references/` を探索したエージェントが直接実行すると**エラーなしで古い挙動の出力**を返す silent-wrong-output 経路になる。

## Current state

- `.claude/skills/music/references/generate_suno_prompts.py` — 削除対象。`ls -la` で通常ファイル（`-rw-r--r--`、19464 bytes）であることが確認できる。同ディレクトリの `finalize_master.py` は symlink（`lrwxr-xr-x` → `../../../../src/youtube_automation/commands/media/finalize_master.py`）で、これがこのリポジトリの正規パターン。references/ 配下の src 連携スクリプト 15 本はすべて symlink であり、この 1 本だけが実体コピー。
- `src/youtube_automation/commands/suno/generate_suno_prompts.py` — 正規実装。`pyproject.toml` の `yt-generate-suno` entry point から到達し、`tests/commands/suno/test_generate_suno_prompts.py` 等 4 テストファイルが import する。**触らない**。
- skill 側の呼び出しは CLI 経由のみ: `.claude/skills/music/references/prompt.md` に `uv run yt-generate-suno` が 9 箇所（29, 106, 115, 117, 174, 198, 204, 222, 252 行付近）。ファイルパス `references/generate_suno_prompts.py` への言及は skill 内・テスト内ともにゼロ（`git grep -n "references/generate_suno_prompts" -- .claude tests` が空であることを確認済み）。
- リポジトリ規約: `.claude/skills/` を触る変更は `CHANGELOG.md` の `[Unreleased]` 追記が CI ゲートで必須。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| テスト（skill 配布契約） | `nix develop --command uv run pytest tests/repo/test_skills_sync_installed_wheel.py -x -q` | all pass |
| テスト（suno 系） | `nix develop --command uv run pytest tests/commands/suno/ -q` | all pass |
| skill lint | `nix develop --command uv run yt-skills lint` | exit 0 |
| Ruff | `nix develop --command uv run ruff check .` | exit 0 |

## Scope

**In scope**（変更してよいのはこれだけ）:
- `.claude/skills/music/references/generate_suno_prompts.py`（削除）
- `CHANGELOG.md`（`[Unreleased]` 追記）

**Out of scope**（触らない）:
- `src/youtube_automation/commands/suno/generate_suno_prompts.py` — 正規実装。同期・編集不要。
- `.claude/skills/music/` の他ファイル — symlink 化への置き換えも行わない（skill は CLI 経由で呼ぶ設計のため、リンクを増やす必要がない）。
- `.agents/skills` — `.claude/skills` への symlink。個別操作不要。

## Git workflow

- 作業は issue 専用 linked worktree 上で行う（`$REPO_ROOT/.claude/worktrees/<slug>/`。メイン作業ツリーで直接ブランチを切らない）
- Branch: `advisor/028-delete-music-suno-prompts-fork`
- Commit: 日本語 Conventional Commits、1 branch 1 commit。例: `chore(skills): music references の stale な generate_suno_prompts fork を削除 (#<issue番号>)`（issue 未起票なら番号は省略可）
- push / PR 作成はオペレーターの指示があるまで行わない

## Steps

### Step 1: fork ファイルを削除する

```bash
git rm .claude/skills/music/references/generate_suno_prompts.py
```

**Verify**: `git status --short` → `D  .claude/skills/music/references/generate_suno_prompts.py` のみ（＋後続の CHANGELOG）

### Step 2: 参照が残っていないことを確認する

**Verify**: `git grep -n "references/generate_suno_prompts" -- .claude tests docs src` → ヒット 0 件

### Step 3: CHANGELOG に追記する

エントリ文面:

```
- music skill の references から stale な generate_suno_prompts.py の実体コピーを削除（正規経路は yt-generate-suno CLI）
```

**Plan 033（issue #4483、changelog fragment 基盤）が main にマージ済みの場合**（`test -d changelog.d` で判定）: `CHANGELOG.md` は編集せず、`changelog.d/4460-delete-suno-prompts-fork.removed.md` を新規作成して上の bullet を書く。未マージの場合のみ、従来どおり `CHANGELOG.md` の `## [Unreleased]` に追記する。

**Verify**: fragment 方式なら `test -f changelog.d/4460-delete-suno-prompts-fork.removed.md` → exit 0（`git diff CHANGELOG.md` は空）。直接編集なら `git diff CHANGELOG.md` → 上記 1 行の追加のみ

### Step 4: テストと lint を通す

**Verify**:
- `nix develop --command uv run pytest tests/repo/test_skills_sync_installed_wheel.py tests/commands/suno/ -q` → all pass
- `nix develop --command uv run yt-skills lint` → exit 0

## Test plan

新規テストは不要（削除のみ）。既存の skill 配布契約テスト `tests/repo/test_skills_sync_installed_wheel.py` と suno 系テスト全部がグリーンであることが回帰確認になる。

## Done criteria

- [ ] `.claude/skills/music/references/generate_suno_prompts.py` が存在しない（`test ! -e` で確認）
- [ ] `git grep -n "references/generate_suno_prompts"` が 0 件
- [ ] `nix develop --command uv run pytest tests/repo/test_skills_sync_installed_wheel.py tests/commands/suno/ -q` が exit 0
- [ ] `nix develop --command uv run yt-skills lint` が exit 0
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記がある
- [ ] In scope 外のファイルに変更がない（`git status`）
- [ ] `plans/README.md` の Status 行を更新した

## STOP conditions

- `.claude/skills/music/references/generate_suno_prompts.py` が symlink になっている（既に誰かが修正済み — この plan は不要）。
- `git grep` で skill 本文・テストのどこかがこのファイルパスを参照している（前提が崩れている）。
- `test_skills_sync_installed_wheel.py` が「ファイル数」や「manifest 一致」で fail し、その fixture / 期待値の更新が必要になった場合 — 期待値をどう更新すべきか判断がいるので報告する。

## Maintenance notes

- 今後 `references/` に src 連携スクリプトを置くときは**必ず symlink** にする（実体コピーはこの障害の再発）。レビュー時は `git diff --stat` でファイルモード `120000`（symlink）を確認するとよい。
- `uv run yt-skills lint` には「未参照 references ファイル検知」が無いため、この類の残骸は機械検出されない（第 6 回監査の残課題として plans/README.md に記載）。
