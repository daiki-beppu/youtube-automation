# Plan 011: live-clean の削除承認を明示的選択肢 + 取消不可警告の形式に固定する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/live-clean/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW(ドキュメントのみ。対象は不可逆なファイル削除の防護柵)
- **Depends on**: plans/005-skill-authoring-standard.md(ルール 2。005 未完了でも実行可能)
- **Category**: docs(実質は安全性)
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

`/live-clean` は `collections/live/` 配下の大容量メディア(監査時の例では 1 実行あたり数 GB〜15GB)を `rm -f` で削除するスキル。承認ゲート自体は存在する(「AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない」)が、**承認の形式が未指定**のため、Sonnet 級モデルは自由文で確認を出し、ユーザーの曖昧な返答(「OK」「いいよ」が別の質問への返答である場合など)を承認と誤認する余地がある。選択肢の文言・取消不可警告・削除対象サマリーの提示内容を SKILL.md で固定し、解釈の幅を消す。

## Current state

- `.claude/skills/live-clean/SKILL.md`(131 行)— 対象ファイル。
  - 84 行目(Step 3 末尾): 「表示後、AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない。」— ゲートは在るが選択肢・警告の形式指定なし。
  - 86 行目〜: 「### Step 4: 削除実行」「ユーザーが承認した場合のみ、ファイル単位で `rm -f` を実行する。」— `rm -f "collections/live/<dir>/01-master/master.mp3"` 等の具体コマンドが続く。
  - Step 3 では削除対象のドライラン表示(コレクション別のファイル数と GB、「削除対象: N コレクション / M ファイル / X.X GB」のサマリー)が既に定義されている(75-82 行)。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/live-clean/SKILL.md`(Step 3 末尾の承認文 1 段落の置き換えのみ)
- `CHANGELOG.md`(`[Unreleased]` への追記)

**Out of scope**:
- Step 1-2(安全 3 条件・対象検出)と Step 4 の `rm -f` コマンド群 — 変更しない。
- 削除対象の選定ロジック・安全条件そのもの。
- 他スキルへの同型適用(comments-reply / pinned-comment は plans/006)。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(live-clean): 削除承認を明示的選択肢と取消不可警告の形式に固定`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: 承認文を形式指定付きに置き換える

`.claude/skills/live-clean/SKILL.md:84` の「表示後、AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない。」を以下で置き換える:

```markdown
表示後、AskUserQuestion で以下の形式の確認を取る。**承認されるまで絶対に削除を実行しない**:

- 質問文: 「上記 N コレクション / M ファイル / X.X GB を削除しますか？**削除は取り消せません**（`rm -f` による物理削除）」
- 選択肢: 「削除を実行する」/「キャンセル」の 2 択。デフォルトを実行側にしない
- 「削除を実行する」が明示的に選ばれた場合のみ Step 4 へ進む。それ以外の応答（自由文・別話題・無回答）はすべてキャンセルとして扱う
- AskUserQuestion が使えない環境（Codex 等）では同内容をテキスト提示し、ユーザーが「削除を実行する」と明示するまで待つ
```

**Verify**: `rg -n '削除は取り消せません' .claude/skills/live-clean/SKILL.md` → 1 件。`rg -n 'キャンセルとして扱う' .claude/skills/live-clean/SKILL.md` → 1 件。

### Step 2: CHANGELOG 追記とテスト

`CHANGELOG.md` の `[Unreleased]`:

```
- live-clean: 削除承認を明示的 2 択（実行/キャンセル）+ 取消不可警告の形式に固定（曖昧応答の承認誤認を防止）
```

**Verify**: `rg -n 'live-clean: 削除承認' CHANGELOG.md` → 1 件。`uv run pytest tests -q --ignore=tests/integration` → exit 0。

## Test plan

新規テスト不要。既存ユニットスイート green を確認。

## Done criteria

- [ ] 承認の質問文・2 択・取消不可警告・曖昧応答の扱いが SKILL.md に明文化されている
- [ ] Step 4 の実行条件が「『削除を実行する』が明示的に選ばれた場合のみ」と一致している
- [ ] `CHANGELOG.md` 追記済み、ユニットテスト exit 0
- [ ] `plans/README.md` の 011 行を更新済み

## STOP conditions

- 84 行付近の承認文が Current state の引用と一致しない(先行変更)。既に選択肢形式が指定済みなら重複追加せず STOP して報告。

## Maintenance notes

- plans/006 と合わせて「外部反映・破壊的操作の承認ゲート標準型」(規約 005 ルール 2)の実装例が 3 スキル分揃う。以降の新スキルはこの 3 つを exemplar にする。
- レビュー観点: 質問文に実数(N/M/X.X)を埋める指示になっているか — 数字なしの抽象的確認は承認の質を下げる。
