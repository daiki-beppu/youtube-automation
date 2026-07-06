# Plan 006: comments-reply / pinned-comment の dry-run→apply 間に明示的承認ゲートを追加する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/comments-reply/ .claude/skills/pinned-comment/`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW(ドキュメント変更のみ。ただし対象は実 YouTube への公開操作の防護柵)
- **Depends on**: plans/005-skill-authoring-standard.md(承認ゲート標準型の定義。005 未完了でも本文の指示だけで実行可能)
- **Category**: docs(実質は安全性)
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

`/comments-reply` と `/pinned-comment` は YouTube に**実際にコメントを公開投稿する**スキルで、下流リポジトリで Sonnet 級モデルが実行する。現状の SKILL.md は dry-run(Phase 4 / Phase 1)の「確認ポイント」を列挙した直後に apply コマンドを提示しており、(a) 確認ポイントの PASS/FAIL 判定基準がなく、(b) apply 前のユーザー承認要求がない。弱いモデルは「確認ポイントを眺めた」ことを「確認完了」と解釈し、不適切な返信文のまま実投稿まで直行しうる。投稿されたコメントは公開されるため実害が出てからでは遅い。同リポジトリの `/live-clean` には「AskUserQuestion で確認、承認されるまで絶対に実行しない」という先例があり、それと同じ型に揃える。

## Current state

- `.claude/skills/comments-reply/SKILL.md` — 対象ファイル 1。
  - 71 行目付近: `### Phase 4: dry-run で内容をプレビュー` — `uv run yt-comments-reply --dry-run --agent-replies-file /tmp/comment-replies.json --limit 5` の後に「出力の確認ポイント:」として 4 項目(`返信候補` が期待件数か / `reply` 欄が persona と言語に合うか / `skipped` に `already_replied` / `ng_word` / `reply_contains_ng_word` があるか / `agent_reply_missing` の扱い)を列挙。**PASS/FAIL の判定形式にはなっていない**。
  - その後「## 設定スキーマ」セクションを挟んで 110 行目付近: `### Phase 5: apply で反映` — `uv run yt-comments-reply --apply --agent-replies-file /tmp/comment-replies.json --limit 5`。**Phase 4 と Phase 5 の間に承認ステップがない**。
- `.claude/skills/pinned-comment/SKILL.md` — 対象ファイル 2。
  - 44-60 行: `--dry-run` のコマンド例(collection 指定 / video-id 直接指定の 2 形)と「確認ポイント」3 項目(`planned` 件数 / `scene_phrase` / `scene_emoji` 展開 / `SKIP ... already_posted` 等)。
  - 62 行目付近: `### Phase 2: apply で投稿` — 直後に `--apply` コマンド。**間に承認ステップがない**。
- 型として揃える先例: `.claude/skills/live-clean/SKILL.md:84`「表示後、AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない。」
- frontmatter は両スキルとも `description:` が double-quoted string(この規約を維持すること)。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| ユニットテスト | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |
| frontmatter 検証 | `uv run pytest tests/test_skill_frontmatter_yaml.py -q` | exit 0 |
| スキル docs 整合 | `uv run pytest tests/test_skill_docs_consistency.py -q` | exit 0 |

## Scope

**In scope**(変更してよいファイル):
- `.claude/skills/comments-reply/SKILL.md`
- `.claude/skills/pinned-comment/SKILL.md`
- `CHANGELOG.md`(`[Unreleased]` への追記 — `.claude/skills/` は CHANGELOG ゲート対象)

**Out of scope**(触らない):
- `src/youtube_automation/scripts/` の CLI 実装(`yt-comments-reply` / `yt-pinned-comment`)— CLI の挙動変更はしない。ゲートは SKILL.md の手順としてのみ追加する。
- `.claude/skills/live-clean/SKILL.md` — 承認の選択肢形式の改善は plans/011 の担当。
- 各スキルの `--limit` 値や設定スキーマの記述。

## Git workflow

- worktree 上で作業(`$REPO_ROOT/.worktrees/006-approval-gates/`)。base は main。
- コミット例: `docs(skills): comments-reply / pinned-comment に apply 前の承認ゲートを追加`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: comments-reply の Phase 4 を PASS/FAIL ゲート化する

`.claude/skills/comments-reply/SKILL.md` の Phase 4「出力の確認ポイント:」を以下の構造に書き換える(既存 4 項目の内容は保持し、判定形式に変換する):

- 見出しを「出力の確認ポイント(**全項目 PASS の場合のみ Phase 5 へ進む**):」に変更。
- 各項目を PASS 条件として書く(例: 「`skipped` の各行の理由が意図どおりである(`reply_contains_ng_word` が 1 件でもあれば該当返信文を修正して dry-run からやり直す)」)。
- 末尾に以下を追加:

```markdown
1 項目でも FAIL の場合は `/tmp/comment-replies.json` の該当返信文を修正し、Phase 4 の dry-run を再実行する。**FAIL のまま Phase 5 に進んではならない。**

全項目 PASS を確認したら、AskUserQuestion で dry-run 結果の要約(返信件数・対象コメントの抜粋)を提示し、「投稿する」「キャンセル」の明示的選択肢でユーザー承認を取る。投稿されたコメントは YouTube 上に公開される。**承認されるまで Phase 5 の apply を実行しない**(Codex など AskUserQuestion が使えない環境では、同内容をテキストで提示しユーザーの明示的な承認応答を待つ)。
```

**Verify**: `rg -n '承認されるまで Phase 5' .claude/skills/comments-reply/SKILL.md` → 1 件ヒット。`rg -n '全項目 PASS' .claude/skills/comments-reply/SKILL.md` → 1 件以上ヒット。

### Step 2: pinned-comment の Phase 1→2 間に同型のゲートを追加する

`.claude/skills/pinned-comment/SKILL.md` の「確認ポイント」(44-60 行付近)にも Step 1 と同じ型を適用する:

- 「確認ポイント(**全項目 PASS の場合のみ Phase 2 へ進む**):」へ変更。
- `### Phase 2: apply で投稿` の直前に、AskUserQuestion による「投稿する」「キャンセル」承認ステップ(Step 1 と同文型、対象は planned 件数と生成テキストの要約)を追加。

**Verify**: `rg -n '承認されるまで' .claude/skills/pinned-comment/SKILL.md` → 1 件以上ヒット。

### Step 3: CHANGELOG に追記する

`CHANGELOG.md` の `[Unreleased]` に追記(セクションは既存の書式に合わせる。無ければ `### Changed`):

```
- comments-reply / pinned-comment: dry-run → apply の間に PASS/FAIL 判定と AskUserQuestion 承認ゲートを追加（Sonnet 級実行時の誤投稿防止）
```

**Verify**: `rg -n 'comments-reply / pinned-comment' CHANGELOG.md` → 1 件ヒット。

### Step 4: テストで回帰がないことを確認する

**Verify**: `uv run pytest tests -q --ignore=tests/integration` → exit 0。

## Test plan

新規テストは不要(SKILL.md の手順文変更)。`tests/test_skill_frontmatter_yaml.py` と `tests/test_skill_docs_consistency.py` を含むユニットスイートが green のままであることを確認する。もし `test_skill_docs_consistency.py` が変更箇所の文言を assert していて fail した場合、テストの期待値を新しい文言に更新してよい(その場合はコミットメッセージに明記)。

## Done criteria

- [ ] comments-reply: Phase 4 に「全項目 PASS の場合のみ」の判定形式と AskUserQuestion 承認ステップがあり、Phase 5 の前に位置する
- [ ] pinned-comment: Phase 2(apply)の直前に同型の承認ステップがある
- [ ] 両ファイルの frontmatter `description:` が double-quoted のまま
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記済み
- [ ] `uv run pytest tests -q --ignore=tests/integration` が exit 0
- [ ] `git status` で In scope 外の変更がない
- [ ] `plans/README.md` の 006 行を更新済み

## STOP conditions

- Phase 4 / Phase 5(comments-reply)または dry-run / Phase 2(pinned-comment)の構造が Current state の記述と一致しない(先行変更で drift)。
- `--apply` の前に既に AskUserQuestion 承認が存在する(誰かが先に直した)— 重複追加せず STOP して報告。
- テスト fail の原因が本変更以外にある。

## Maintenance notes

- `yt-comments-reply` / `yt-pinned-comment` の CLI 側に将来 `--yes` / 確認プロンプトが実装されたら、SKILL.md 側のゲートと二重にならないよう一方に寄せる。
- レビュー観点: ゲート文言が「承認を推奨」ではなく「承認されるまで実行しない」という禁止形になっているか(Sonnet は推奨形を任意と解釈しうる)。
- `/community-post` は Studio 手動投稿のためゲート不要(投稿自体を自動化していない)。対象を広げない。
