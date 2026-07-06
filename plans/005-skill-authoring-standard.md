# Plan 005: Sonnet-safe スキル記述規約を docs/skill-design/ に制定する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- docs/skill-design/ CLAUDE.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

このリポジトリの `.claude/skills/` 配下 47 スキル(SKILL.md 合計約 10,300 行)は、下流チャンネルリポジトリで Claude Code / Codex CLI により実行される。実行モデルは Opus 級とは限らず Sonnet 級のことが多い。2026-07-05 の監査で 42 件の findings が出たが、その大半は少数の同型パターンの反復だった: 承認ゲートの型が曖昧、前提ファイルの存在ガードがない、判断基準なしの判断要求、同一ロジックの散文重複、兄弟スキル間の frontmatter 矛盾。個別修正(plans/006〜017)だけでは新規スキル作成時に同じ問題が再生産されるため、記述規約を 1 枚のドキュメントに定めて再発を止める。この規約は plans/006, 008, 009, 011 の修正方針の根拠にもなる。

## Current state

- `docs/skill-design/` — 既存ディレクトリ。`ADR-001-thumbnail-prompt-schema.md` が置かれている(`.claude/skills/thumbnail/SKILL.md:213` から参照されている)。ここに規約ドキュメントを追加する。
- `CLAUDE.md`(リポジトリルート)— 「## 開発規約」セクション配下に「### skill frontmatter」という小節があり、`description:` の double-quote 必須規則が既に書かれている。規約ドキュメントへのポインタをここに 1 行追加する。
- 監査で確認済みの「良い実例」(規約の each ルールの exemplar として引用する):
  - 承認ゲートの良い例: `.claude/skills/live-clean/SKILL.md:84`「表示後、AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない。」
  - 前提の明文化の良い例: `.claude/skills/channel-new/SKILL.md:110-140`(停止すべき 17 チェックと許容する 4 fail を理由文字列付きで分離)
  - 単一ソースの良い例: `.claude/skills/collection-ideate/references/freshness-rules.md`(stale 判定の参照先ドキュメント)
  - 機械検証の良い例: `.claude/skills/suno-lyric/SKILL.md:122`「機械チェックを実行して exit 0 を確認する: `python .claude/skills/suno-lyric/references/check_lyric_duplication.py ...`」
- 悪い実例(規約の反例として引用する。修正自体は plans/006〜017 の担当なので**ここでは直さない**):
  - frontmatter 矛盾: `.claude/skills/viewer-voice/SKILL.md:3`「任意後続スキル」 vs `.claude/skills/audience-persona-design/SKILL.md:3`「/viewer-voice を必須入力に」
  - ゲートなし apply: `.claude/skills/comments-reply/SKILL.md:71-115`(dry-run の確認ポイント列挙の直後に apply コマンド)

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| ユニットテスト | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |
| lint | `uv run ruff check .` | exit 0 |

## Scope

**In scope**(変更してよいファイル):
- `docs/skill-design/skill-authoring-guidelines.md`(新規作成)
- `CLAUDE.md`(「### skill frontmatter」小節への 1 行追記のみ)

**Out of scope**(触らない):
- `.claude/skills/` 配下すべて — 個別スキルの修正は plans/006〜017 の担当。この plan は規約の制定のみ。
- `CHANGELOG.md` — docs のみの変更は CHANGELOG ゲート対象外(`CLAUDE.md` の「CHANGELOG ゲート」参照)。ただし `CLAUDE.md` 自体はゲート対象パスに含まれないので追記不要。
- `.claude/CLAUDE.template.md` — 下流向けテンプレは対象外(これを触ると CHANGELOG 必須になる)。

## Git workflow

- 作業は worktree 上で行う(`$REPO_ROOT/.worktrees/005-skill-authoring-standard/` に `git worktree add`)。base は main。
- コミットメッセージは日本語 Conventional Commits。例: `docs(skill-design): Sonnet-safe スキル記述規約を制定`
- push / PR 作成はオペレーターの指示があるまで行わない。

## Steps

### Step 1: 規約ドキュメントを作成する

`docs/skill-design/skill-authoring-guidelines.md` を新規作成し、以下の 7 ルールを見出しごとに記述する。各ルールには (a) 規則本文、(b) 上記 Current state の「良い実例」への `file:line` 参照、(c) 反例パターンの説明(実在スキル名を挙げてよいが、修正は各 plan の担当と明記)を含める。

1. **発動条件の相互排他**: 発動キーワードは兄弟スキル間で重複させない。混同しやすいペア(生成/比較、collection 型/release 型など)は双方の description に否定トリガー(「〜は /xxx」)を必ず入れる。あるスキルが別スキルの必須入力を作る場合、両者の description の依存表現(必須/任意)を一致させる。
2. **外部反映・破壊的操作の承認ゲート標準型**: YouTube への投稿・削除・課金 API 呼び出しの前は、(a) dry-run 出力の PASS/FAIL 条件を箇条書きで定義し「全項目 PASS の場合のみ次へ」と書く、(b) AskUserQuestion で明示的選択肢(「実行する」「キャンセル」)を提示する、(c) 取り消し不可の操作はその旨を選択肢の説明に含める、の 3 点を必須とする。
3. **前提ガードの標準型**: 前工程スキルの出力ファイルに依存する Step は、冒頭で存在確認コマンド(`ls <path>` 等)を置き、「存在しなければ /前工程スキル を案内して停止する」と書く。inline コード実行の前に依存する認証ファイル(`auth/token.json` 等)の存在確認を置く。
4. **判断基準なしの判断要求の禁止**: 「適切に」「必要なら」「文脈に応じて」を単独で使わない。使う場合は直後に判断条件の列挙(if-then 形式または表)か、調整ルーブリックを付ける。
5. **単一ソース原則**: 同一の判定ロジック(鮮度判定・閾値など)を複数の SKILL.md に散文で重複記述しない。`references/` 配下の 1 ファイルに定義し、他スキルからは「詳細は X を参照。要約: 〜」の 1 行参照にとどめる。
6. **Hard Gates / 完了条件の配置**: スキルの完了条件・絶対制約は SKILL.md 冒頭 60 行以内(Overview 直後)に置く。300 行を超えるスキルでは、後半の Step から冒頭の完了条件セクションへ明示的に参照を張る。
7. **実行者が解決できない参照の禁止**: 下流リポジトリの実行者がアクセスできない参照(オペレーター個人の別リポジトリ、未接続の試験機能)を手順文中に置かない。置く場合は「実行者向けではない」ことを明示する引用ブロック(`> 参考(オペレーター向け): ...`)に隔離する。

ドキュメント冒頭に「この規約は既存スキルの一括改修を要求しない。新規作成・改訂時に適用し、既存の逸脱は plans/006〜017 で個別に解消する」と適用方針を明記する。

**Verify**: `ls docs/skill-design/skill-authoring-guidelines.md` → ファイルが存在する。7 ルールの見出しがあることを `rg -c '^## ' docs/skill-design/skill-authoring-guidelines.md` で確認 → 7 以上。

### Step 2: CLAUDE.md からポインタを張る

`CLAUDE.md` の「### skill frontmatter」小節の末尾に 1 行追加する:

```
- スキル新規作成・改訂時は `docs/skill-design/skill-authoring-guidelines.md`（Sonnet-safe 記述規約）に従うこと
```

**Verify**: `rg -n 'skill-authoring-guidelines' CLAUDE.md` → 1 件ヒット。

### Step 3: 既存テストが壊れていないことを確認する

**Verify**: `uv run pytest tests -q --ignore=tests/integration` → exit 0(この plan はコードもスキルも触らないため、失敗した場合は元から失敗しているか環境問題 — STOP して報告)。

## Test plan

新規テストは不要(docs のみ)。既存ユニットスイートの green 維持のみ確認する。

## Done criteria

- [ ] `docs/skill-design/skill-authoring-guidelines.md` が存在し、7 ルールすべての見出しを含む
- [ ] 各ルールに実在ファイルへの `file:line` 実例参照が最低 1 つある
- [ ] `rg -n 'skill-authoring-guidelines' CLAUDE.md` が 1 件ヒット
- [ ] `uv run pytest tests -q --ignore=tests/integration` が exit 0
- [ ] `git status` で In scope 外の変更ファイルがない
- [ ] `plans/README.md` の 005 行を更新済み

## STOP conditions

- `docs/skill-design/` が存在しない、または `CLAUDE.md` に「### skill frontmatter」小節が見つからない(構成が drift している)。
- 「良い実例」として引用予定の箇所(live-clean:84, channel-new:110-140, suno-lyric:122)が現物と一致しない — plans/006〜017 が先に実行されて行番号がずれた可能性がある。その場合は現物の該当箇所を確認して行番号を更新してよいが、内容自体が消えていたら STOP。
- ユニットテストが変更前から fail している。

## Maintenance notes

- plans/006(承認ゲート)・008(frontmatter)・009(前提ガード)・011(live-clean)はこの規約のルール 2・1・3・2 をそれぞれ実装する。規約の文言を変える場合はそれらの plan の方針と矛盾しないか確認すること。
- 将来的には `tests/test_skill_docs_consistency.py` の系譜で規約の一部(発動キーワード重複の検出など)を機械化できる。この plan では見送り(規約の合意が先)。
- レビュー観点: 規約が「既存スキルの一括改修を要求しない」ことが明記されているか(さもないと 47 スキル改修という誤った着地になる)。
