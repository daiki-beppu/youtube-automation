# Issue #253: `/release` スキル更新 (sub-PR Closes 集約)

## このドキュメントの位置付け

Issue #253 で要求された `.claude/skills/release/SKILL.md` の更新内容を本リポジトリ（YTCA: youtube-channels-automation）の追跡可能パスに保存する。

- `/release` は **dotfiles 配布の user-level skill**（実体: `~/01-dev/dotfiles/config/.claude/skills/release/SKILL.md`、`~/.claude/skills/release/` は dotfiles へのシンボリックリンク）であり、本 YTCA リポジトリには配布されていない。
- takt のワークフロー（issue #253）は YTCA repo の worktree 上で走るため、dotfiles 側ファイルを編集しても YTCA の PR には差分が出ない。
- 加えて、harness が dotfiles 側 SKILL.md への Edit / Write を "sensitive file" として拒否する。

そのため:

1. 本ドキュメントに **完成版 SKILL.md の全文**を保存し、YTCA の PR でレビュー可能にする。
2. dotfiles への反映は **ユーザーが手動で実施**する（後述「適用手順」参照）。
3. dotfiles 側の反映 PR は本 issue とは別個に作成・マージする。

## 適用手順（ユーザー向け）

YTCA のリリース PR がマージされた後、または並行して、以下を実行して dotfiles に反映する。

```bash
# 1) 本ファイルから「完成版 SKILL.md」の本体（下の `---` 区切りより下）を抽出して dotfiles に上書き
#    （手作業で範囲をコピーする想定。スクリプト化する場合は sed で抽出可能）
$EDITOR ~/01-dev/dotfiles/config/.claude/skills/release/SKILL.md

# 2) dotfiles 側でコミット & PR
cd ~/01-dev/dotfiles
git switch -c feat/release-skill-closes-aggregation-253
git add config/.claude/skills/release/SKILL.md
git commit -m "feat(skill): /release に sub-PR の Closes 集約ステップを追加 (#253)"
gh pr create --base main --title "feat(skill): /release に sub-PR の Closes 集約ステップを追加 (#253)" \
  --body "YTCA #253 で要求された /release skill の更新を dotfiles に反映する。"
```

## 完成版 SKILL.md

以下を `~/01-dev/dotfiles/config/.claude/skills/release/SKILL.md` の全文として置き換える。

---

```markdown
---
name: release
description: |
  Node.js / npm リポジトリ向けに GitHub Release の作成をリリース PR 経由で実行するスキル。
  `/release` 1 コマンドでリポジトリの状態を自動判定し、
  前半（prepare: バージョン判定 → リリースブランチ → PR 作成）または
  後半（publish: GitHub Release 作成 → ブランチ削除）を実行する。
  「リリースして」「リリース作って」「バージョン上げて」「npm に公開して」
  「新しいバージョン出して」「/release」で発動。
  注意: リリースの閲覧・削除は対象外。新規リリース作成のみ。
  注意: `package.json` を持たないリポジトリでは起動しない（Cargo.toml / pyproject.toml / go.mod 等は対象外）。
---

# release — GitHub Release パイプライン

## Overview

`/release` 1 コマンドでリポジトリの状態を自動判定し、適切なフローを実行する。

- **前半（prepare）**: バージョン自動判定 → `release/v<version>` ブランチ作成 → version bump → PR 作成
- **後半（publish）**: マージ済みリリース PR を検知 → `gh release create` → ブランチ削除

## When to Use

- `package.json` を持つ Node.js / npm リポジトリで新しいバージョンをリリースしたいとき
- `/release` コマンドを実行したとき
- 「リリースして」「リリース作って」「npm に公開して」と言われたとき

## Prerequisites

- リポジトリ直下に `package.json` が存在し、`version` フィールドが書かれていること
- `gh` が認証済みであること（`gh auth status` で OK）
- main ブランチに push 権限があること

`package.json` がない場合は Node.js / npm 以外のプロジェクト構成と判断し、起動しない（下記 Step 0 を参照）。

## パイプライン

### Step 0: 状態判定

0. **前提チェック**: リポジトリ直下に `package.json` が存在することを確認する。存在しない場合は次のメッセージを表示して終了：

   > release スキルは Node.js / npm リポジトリ向けです。`package.json` が見つからないため終了します。Cargo / pyproject / go.mod 等の他言語プロジェクトには対応していません。

1. main ブランチ以外にいる場合、`git switch main && git pull origin main` を自動実行する。未コミットの変更がある場合はエラー停止。

2. 最新リリースの公開日時を取得:
   ```bash
   gh release list --limit 1 --json tagName,publishedAt -q '.[0]'
   ```
   リリースが 0 件の場合（初回リリース）は全コミットをリリース対象として **前半フロー（prepare）** に進む。

3. マージ済みリリース PR を検索:
   ```bash
   gh pr list --state merged --head "release/*" --base main --json mergedAt,title,number
   ```
   取得した PR のうち `mergedAt` が最新リリースの `publishedAt` より新しいものがあれば → **後半フロー（publish）**

4. オープンなリリース PR を検索:
   ```bash
   gh pr list --state open --head "release/*" --base main --json url -q '.[0].url'
   ```
   → あれば PR URL を表示し「まだマージされていません」で終了

5. 上記いずれでもない → **前半フロー（prepare）**

### 前半フロー（prepare）

#### Step 1: コンテキスト収集

```bash
gh release list --limit 1                    # 最新リリースタグ取得
git log <last-tag>..HEAD --oneline           # 前回以降のコミット一覧
```

差分がない場合は「リリースする変更がありません」と表示して終了。
初回リリースの場合は `git log --oneline` で全コミットを取得。

#### Step 2: バージョン自動判定

前回リリース以降のコミットメッセージを分析し、セマンティックバージョニングで決定する。

| コミットタイプ | バージョン変更 |
|---------------|--------------|
| `!` 付き（破壊的変更） | **major** バンプ |
| `feat` あり | **minor** バンプ |
| `fix` / `chore` のみ | **patch** バンプ |

判定結果をユーザーに表示する（例: `v0.4.2 → v0.5.0 (minor: feat コミットあり)`）。ユーザーが別のバージョンを指定した場合はそちらを採用する。

#### Step 3: リリースブランチ作成 & version bump

1. `git pull origin main`（ローカル main を最新に同期）
2. `git switch -c release/v<version>`
3. `package.json` の `version` フィールドを更新
4. `/skills commit-convention` に従いコミット（例: `release: v0.5.0`）
5. `git push -u origin release/v<version>`

#### Step 4: sub-PR の Closes 集約と PR 本文生成

リリース PR は `release/v<version>` を経由するため、sub-PR 本文に書かれた `Closes #N` は GitHub の自動クローズ機構では発火しない（base が main ではないため）。
このステップで sub-PR から close keyword を集約し、release PR 本文に `## Closes` セクションを生成して main マージ時に一括クローズさせる。

1. **マージ済み sub-PR を取得**:
   ```bash
   gh pr list --state merged --base "release/v<version>" --json number,title,body,baseRefName --limit 200
   ```
   0 件であれば後続の `## 含まれる変更` / `## Closes` セクションは生成せず、PR 本文は `v<version> リリース` の最小形にフォールバックする。

2. **各 sub-PR 本文から close keyword を抽出**:
   - 対象キーワード: `Closes` / `Fixes` / `Resolves`（**case-insensitive**）
   - 参考正規表現: `(?i)\b(?:Closes|Fixes|Resolves)\s+#(\d+)\b`
   - 抽出した issue 番号は重複排除し、出現順で保持する
   - 1 件も抽出できなかった場合は `## Closes` セクションを省略する

3. **抽出した issue 番号の state を判定**:
   ```bash
   gh issue view <N> --json state -q '.state'
   ```
   - `OPEN` のみを `## Closes` 対象に採用する
   - `CLOSED` だったものはユーザーに「`#N` は既に CLOSED のため除外」とログ表示する
   - `gh issue view` がエラーになるケース（別リポジトリ参照、削除済み等）も同様にログ表示し、対象から除外する（握り潰さない）

4. **`## 含まれる変更` セクションの構築**:
   - sub-PR タイトル先頭の Conventional Commit prefix を抽出する
     - 参考正規表現: `^(?<type>feat|fix|chore|test|docs|refactor|perf|build|ci|style)(?:\([^)]+\))?!?:\s*`
   - 各 sub-PR ごとに prefix 抽出を試行し、抽出できた PR は `### <type>` 小見出しに振り分け、抽出失敗の PR は `### other` 小見出しに集約する（mixed ケースでも `### feat` / `### fix` / `### other` のように共存させる）
   - 全 sub-PR で prefix 抽出に失敗した場合のみ、見出しなしのフラットな箇条書きにフォールバックする
   - 各行のフォーマット:
     ```
     - #<sub-PR 番号> <prefix を除いたタイトル> (対応 issue: #<issue 番号>)
     ```
     対応する issue 番号がない sub-PR は ` (対応 issue: #<...>)` 部分を省略する
   - **重要**: この行で `Closes` / `Fixes` / `Resolves`（case-insensitive）の GitHub auto-close 予約語を絶対に使わない。これらが本文に出現すると `## Closes` 側で除外した CLOSED issue や `gh issue view` エラー issue まで auto-close 対象に拾われ、Step 3 の除外ロジックが構造的にバイパスされる

5. **`## Closes` セクションの構築**:
   ```
   ## Closes

   これらの issue は release ブランチへの sub-PR マージ時には closing keyword が発火しなかったため、本 PR (main マージ) で同時にクローズする。

   Closes #A
   Closes #B
   ...
   ```
   採用された OPEN issue 番号を 1 行ずつ `Closes #N` で並べる。

6. **最終的な PR 本文の組み立て**:
   ```
   v<version> リリース

   ## 含まれる変更

   ### feat
   - #123 新機能 X を追加 (対応 issue: #100)
   ### fix
   - #124 Y のバグ修正 (対応 issue: #110)

   ## Closes

   これらの issue は release ブランチへの sub-PR マージ時には closing keyword が発火しなかったため、本 PR (main マージ) で同時にクローズする。

   Closes #100
   Closes #110
   ```
   - sub-PR が 0 件 → 本文は `v<version> リリース` の 1 行のみ（最小形）
   - sub-PR は存在するが close keyword 抽出 0 件 → `## 含まれる変更` のみ生成、`## Closes` は省略
   - 採用済み OPEN issue が 0 件 → `## Closes` を省略（`## 含まれる変更` は引き続き生成）

#### Step 5: PR 作成

Step 4 で組み立てた本文を heredoc で渡して PR を作成する（他スキル `takt-issue` と同じパターン）。

```bash
gh pr create --base main --head release/v<version> --title "release: v<version>" --body "$(cat <<'EOF'
<Step 4 で組み立てた本文>
EOF
)"
```

- 品質チェック（self-review スキル）は呼ばない（変更が version bump のみのため）
- PR URL を保持して次の Step 6 に進む

#### Step 6: PR 作成後の検証

```bash
gh pr view <PR#> --json closingIssuesReferences
```

- 取得した `closingIssuesReferences` の件数と issue 番号一覧をユーザーに表示する
- Step 4 で採用した OPEN issue 集合と比較し、件数や番号に乖離があれば **WARNING を表示**する（PR 本文の生成漏れや、本文反映後の race を検知する）
- 最後に PR URL を表示して終了

### 後半フロー（publish）

#### Step 1: マージ済みリリース PR から情報取得

- PR タイトルからバージョン番号を抽出（`"release: v0.5.0"` → `v0.5.0`）
- 同じタグが既に存在しないか確認:
  ```bash
  gh release view v<version> 2>/dev/null
  ```
  存在する場合はエラー表示して終了。

#### Step 2: GitHub Release 作成

```bash
gh release create v<version> --target main --generate-notes
```

- リリース URL を表示
- 「Publish ワークフローが自動で npm publish を実行します」と案内

#### Step 3: リリースブランチの削除

```bash
git branch -d release/v<version> 2>/dev/null      # ローカル（存在しなくても OK）
git push origin --delete release/v<version> 2>/dev/null  # リモート（自動削除済みでも OK）
```

## エラーハンドリング

| 状況 | 対応 |
|------|------|
| main 以外のブランチ | `git switch main && git pull` を自動実行（未コミット変更があればエラー停止） |
| 前回リリースからの差分なし | 「リリースする変更がありません」で終了 |
| オープンなリリース PR あり | PR URL を表示し「まだマージされていません」で終了 |
| 同じタグが既に存在 | エラー表示し、バージョンの再指定を促す |
| リリースブランチが存在しない（削除時） | エラーを無視して続行 |
| `gh` 認証エラー | `gh auth login` を案内 |
| sub-PR が 0 件 | `## 含まれる変更` / `## Closes` を省略し、PR 本文を `v<version> リリース` の最小形にする |
| sub-PR は存在するが close keyword 抽出 0 件 | `## 含まれる変更` のみ生成、`## Closes` は省略 |
| 採用済み OPEN issue が 0 件 | `## Closes` のみ省略（`## 含まれる変更` は sub-PR 一覧から引き続き生成） |
| `gh issue view` がエラー（別リポジトリ参照・削除済み等） | 該当 issue を `## Closes` 対象から除外し、ログ表示する |
| Step 6 の `closingIssuesReferences` と採用集合に乖離 | WARNING を表示（PR 本文の生成漏れを検知） |

## Rules

- `/release` 1 コマンドで状態に応じたフローを自動実行
- リリースノートは `--generate-notes` で GitHub に任せる
- 対応リポジトリは Node.js / npm（`package.json`）に限定。Cargo.toml / pyproject.toml / go.mod 等は対象外
- バージョン更新は `package.json` の `version` フィールドのみ
- コミットメッセージは commit-convention に従う（タイプ: `release`）
- バージョン判定はユーザーが上書き可能
- リリースブランチの命名: `release/v<version>`
- リリース PR 本文は sub-PR から `Closes #N` を集約し、main マージ時の自動クローズ発火を保証する（対象キーワード: `Closes` / `Fixes` / `Resolves`、case-insensitive）
```
