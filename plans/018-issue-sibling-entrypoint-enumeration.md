# Plan 018: issue テンプレの「影響ファイル」に兄弟入口・貫通先の列挙を必須化する

> **Executor instructions**: このプランをステップ順に実行すること。各ステップ末尾の
> 検証コマンドを実行し、期待結果を確認してから次へ進む。「STOP conditions」に該当したら
> 即座に停止して報告する（改変・推測で続行しない）。完了したら
> `<automation-repo>/plans/README.md` の本プランの Status 行を更新する。
>
> **⚠ 作業対象リポジトリは dotfiles**: 編集対象ファイルはすべて
> `~/01-dev/dotfiles/config/.claude/skills/` 配下にある。`~/.claude/skills/` は
> dotfiles への symlink なので、**必ず dotfiles リポジトリ側で編集・コミットする**。
> このプランファイル自体は automation リポジトリ（`~/02-yt/00-automation`）の
> `plans/` にあるが、コード変更は dotfiles のみ。
>
> **Drift check (run first)**:
> `cd ~/01-dev/dotfiles && git diff --stat 9a030ff..HEAD -- config/.claude/skills/issue/SKILL.md config/.claude/skills/to-issues/SKILL.md config/.claude/skills/takt-issue/SKILL.md`
> 差分があれば「Current state」の抜粋と実ファイルを突き合わせ、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: dotfiles `9a030ff` / automation `bf68c73d`, 2026-07-06

## Why this matters

takt の 7 観点レビュー（review-takt-default）の REJECT 指摘 676 件（2026-06-17〜07-06、
review 237 run）を全数分類した結果、最大の欠陥クラスは「契約・配線の貫通漏れ」だった:
config キーを定義したが loader→実行経路→出力まで配線されていない（75 件）、同じ責務を持つ
別入口（別 CLI / server 側 / Chrome extension 側 / Python・TS 二重実装）に契約変更が適用
されていない、など。issue 起票時に「変更が貫通すべき兄弟入口」を列挙しておけば、takt の
plan step（automation リポジトリの `.takt/facets/instructions/plan.md` は「配線が必要な
全箇所を列挙する」ことを Coder ガイドラインに要求している）がそれを読み込み、実装漏れ →
レビュー REJECT のループを上流で削れる。現在の issue / to-issues / takt-issue の 3 テンプレは
いずれも「影響ファイル」に新規/変更/削除の区別しか要求しておらず、兄弟入口の観点がない。

## Current state

対象は dotfiles リポジトリの 3 ファイル（`~/.claude/skills/` は symlink）:

1. `config/.claude/skills/issue/SKILL.md`（272 行）— `/issue` スキル。Task Step 3 の
   コアテンプレ内に以下の「影響ファイル」節がある（L82-86 付近）:

   ```markdown
   ## 影響ファイル
   （スコープ明示。新規 / 変更 / 削除を区別）
   - **新規**: path/to/new.ts
   - **変更**: path/to/existing.ts
   - **削除**: path/to/old.ts
   ```

   また L137-142 付近に「情報不足時の振る舞い」リストがあり、
   `**`## 影響ファイル`` が会話から特定できない**: `(plan step で確定する)` と明記して残す`
   という行がある。

2. `config/.claude/skills/to-issues/SKILL.md`（146 行）— `/to-issues` スキル。
   issue-template 内 L97-103 に同様の「影響ファイル」節:

   ```markdown
   ## 影響ファイル

   （スコープ明示。新規 / 変更 / 削除を区別）
   - **新規**: path/to/new.ts
   - **変更**: path/to/existing.ts

   特定できない場合は `(plan step で確定する)` と明記する。
   ```

3. `config/.claude/skills/takt-issue/SKILL.md`（508 行）— Step 0「issue 本文の正規化
   （preflight）」（L61-133）が既にあり、`## 影響ファイル` を含む 4 必須セクションを検証する。
   L107-115 の「不足セクション補完」に
   `**`## 影響ファイル`**: 同上。`**新規**` / `**変更**` / `**削除**` を文脈から推定。不足なら `(plan step で確定する)``
   という補完ルールがある。

リポジトリ規約（dotfiles）: コミットは日本語 Conventional Commits
（例: `fix(skills): CI 監視でコンフリクト未検知のまま待ち続ける問題を修正`）。
dotfiles にはテストスイート・CHANGELOG ゲートはない。検証は `rg` による構造チェックのみ。

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Drift check | `cd ~/01-dev/dotfiles && git diff --stat 9a030ff..HEAD -- config/.claude/skills/{issue,to-issues,takt-issue}/SKILL.md` | （差分なし、または抜粋と一致） |
| 構造検証 | `rg -c '兄弟入口' config/.claude/skills/issue/SKILL.md` | 1 以上 |
| symlink 確認 | `ls -la ~/.claude/skills/issue` | dotfiles 配下を指す symlink |

## Scope

**In scope**（変更してよいファイル — すべて `~/01-dev/dotfiles/` 配下）:
- `config/.claude/skills/issue/SKILL.md`
- `config/.claude/skills/to-issues/SKILL.md`
- `config/.claude/skills/takt-issue/SKILL.md`

**Out of scope**（触らない）:
- automation リポジトリ側の一切のファイル（`.takt/` の workflow / policy / instruction を含む。
  兄弟入口の実装時チェックは既に `.takt/facets/policies/pre-review-checklist.md` 項目 4 が
  担っており、本プランは issue 起票側だけを扱う）
- `config/.claude/skills/issue-direct/SKILL.md`・`issue-organize` — issue 本文テンプレを
  持たないため対象外
- 各テンプレの「影響ファイル」以外のセクション（要件・スコープ外・参照資料の書式）

## Git workflow

- リポジトリ: `~/01-dev/dotfiles`（main ブランチ運用。ブランチを切る場合は `feat/issue-sibling-entrypoints`）
- コミット例: `feat(skills): issue テンプレの影響ファイルに兄弟入口・貫通先の列挙を追加`
- push / PR はオペレーターの指示がない限り行わない

## Steps

### Step 1: `/issue` のテンプレに「兄弟入口・貫通先」小節を追加

`config/.claude/skills/issue/SKILL.md` のコアテンプレ内「影響ファイル」節を次の形に拡張する
（既存 3 行の直後に追記。セクション名 `## 影響ファイル` 自体は変更しない — takt の plan.md
instruction と takt-issue preflight が見出し名でパースするため）:

```markdown
## 影響ファイル
（スコープ明示。新規 / 変更 / 削除を区別）
- **新規**: path/to/new.ts
- **変更**: path/to/existing.ts
- **削除**: path/to/old.ts

**兄弟入口・貫通先**（契約・データ形式・config キーを変更する issue では省略不可。
同じデータ・同じ責務を扱う別入口を列挙し、「変更する / 変更不要（理由）」を明記する）:
- 同責務の別入口: 別 CLI サブコマンド / server 側 / extension 側 / Python・TS の対になる実装
- config キーの変更なら定義 → loader → 実行経路 → 出力の貫通チェーン
- 該当なしの場合は「なし（単一入口のみ）」と明記。特定できない場合は `(plan step で確定する)`
```

あわせて「情報不足時の振る舞い」リストの `## 影響ファイル` の行の直後に 1 項目追加:

```markdown
- **「兄弟入口・貫通先」が判断できない**: `(plan step で確定する)` と明記して残す（空欄・省略にしない）
```

**Verify**: `rg -n '兄弟入口' ~/01-dev/dotfiles/config/.claude/skills/issue/SKILL.md` → 2 箇所以上ヒット

### Step 2: `/to-issues` のテンプレにも同じ小節を追加

`config/.claude/skills/to-issues/SKILL.md` の issue-template 内「影響ファイル」節
（L97-103 付近）に、Step 1 と同一文面の「兄弟入口・貫通先」ブロックを追記する
（文面を 2 スキル間で一字一句揃えること — 将来の同期修正を単純化するため）。

**Verify**: `diff <(rg -A7 '兄弟入口・貫通先' ~/01-dev/dotfiles/config/.claude/skills/issue/SKILL.md | head -8) <(rg -A7 '兄弟入口・貫通先' ~/01-dev/dotfiles/config/.claude/skills/to-issues/SKILL.md | head -8)` → 差分なし（exit 0）

### Step 3: takt-issue preflight の補完ルールに兄弟入口を追加

`config/.claude/skills/takt-issue/SKILL.md` Step 0 の「不足セクション補完」内、
`## 影響ファイル` の補完ルール行を次のように拡張する:

```markdown
- **`## 影響ファイル`**: 同上。`**新規**` / `**変更**` / `**削除**` を文脈から推定。不足なら `(plan step で確定する)`。
  契約・データ形式・config キーの変更を含む issue では「兄弟入口・貫通先」
  （同責務の別 CLI / server / extension / Python・TS 対実装、config の定義→loader→実行→出力チェーン）を
  本文から推定して小節として補完する。推定できなければ `(plan step で確定する)` と明記
```

**Verify**: `rg -n '兄弟入口' ~/01-dev/dotfiles/config/.claude/skills/takt-issue/SKILL.md` → 1 箇所以上ヒット

### Step 4: symlink 経由の反映確認とコミット

```bash
rg -l '兄弟入口' ~/.claude/skills/issue/SKILL.md ~/.claude/skills/to-issues/SKILL.md ~/.claude/skills/takt-issue/SKILL.md
```
3 ファイルすべてヒットすること（symlink なので dotfiles 編集が即反映される）。
その後 dotfiles でコミットする。

**Verify**: `cd ~/01-dev/dotfiles && git status --short` → 上記 3 ファイルのみが変更されている

## Test plan

スキル（プロンプト資産）のためテストスイートはない。構造検証は各 Step の rg チェックが担う。
動作確認（任意・推奨）: 適当な会話文脈で `/issue` を起動し、生成プレビューの「影響ファイル」に
「兄弟入口・貫通先」小節が含まれることを目視確認する（issue は実際には作成せずプレビューで中断してよい）。

## Done criteria

- [ ] `rg -c '兄弟入口' config/.claude/skills/issue/SKILL.md` ≥ 2
- [ ] `rg -c '兄弟入口' config/.claude/skills/to-issues/SKILL.md` ≥ 1
- [ ] `rg -c '兄弟入口' config/.claude/skills/takt-issue/SKILL.md` ≥ 1
- [ ] issue / to-issues の「兄弟入口・貫通先」ブロック文面が一致（Step 2 の diff が exit 0）
- [ ] `git status --short` で in-scope 3 ファイル以外に変更がない
- [ ] automation リポジトリの `plans/README.md` の 018 行を DONE に更新

## STOP conditions

以下の場合は停止して報告する:

- Drift check で「影響ファイル」節の現行文面が Current state の抜粋と一致しない
  （テンプレが既に改訂されている — 上書きすると他の変更を壊す）
- `~/.claude/skills/issue` が symlink ではなく実体ディレクトリになっている
  （dotfiles 管理から外れている — 編集先の前提が崩れている）
- `## 影響ファイル` という見出し名自体を変更したくなった場合（takt の plan.md と
  takt-issue preflight のパースを壊すため、見出し名の変更は本プランの範囲外）

## Maintenance notes

- 将来 `.takt/facets/instructions/plan.md`（automation リポジトリ）の参照資料抽出書式が
  変わる場合、この「兄弟入口・貫通先」小節のパース互換に注意（現状は自由記述小節なので影響なし）
- レビュー時の注視点: 2 スキル間の文面が完全一致していること（片方だけ直す将来変更が起きやすい）
- 見送った案: `## 兄弟入口` を独立必須セクションにする案は、takt-issue preflight の
  必須 4 セクション検証・plan.md の見出しパースへの波及が大きいため不採用（小節方式なら非破壊）
