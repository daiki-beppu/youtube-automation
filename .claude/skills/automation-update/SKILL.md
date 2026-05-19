---
name: automation-update
description: Use when 下流チャンネルリポジトリで youtube-channels-automation を upstream 最新リリースに追従させたいとき。「追従」「アップグレード」「最新版に上げて」「v5.x.y に上げて」「automation-update」「automation を更新」「skills sync 含めて更新」など、`pyproject.toml` の pin bump → `uv lock` → `yt-skills sync` → 動作確認 → コミットまでを 1 コマンドで回したい場面で使用する。upstream の `docs/upgrades/v<ver>.md` を `gh api` で取得して累積影響を要約し、local fix 衝突や破壊的操作の前で人間に確認を求める AI 主導 wizard。
---

## Overview

このスキルは **AI 主導の追従 wizard** である。下流チャンネルリポジトリ（bobble / deepfocus365 / rjn 等）で発動し、自リポの `pyproject.toml` を upstream `daiki-beppu/youtube-automation` の最新 tag まで bump して、`.claude/skills/` の同期、動作確認、コミットまでを 1 コマンドで回す。

利用者は upstream のリリース内容を都度追わなくてよい。AI が `gh release list` で最新を検出し、`docs/upgrades/v<ver>.md` を取得して累積影響を要約してから、破壊的操作の前で `[HUMAN STEP]` として人間判断を求める。

対になる upstream 側のスキル `/release-notes` が生成する `docs/upgrades/v<ver>.md` の「■ AI にお任せする場合のプロンプト」セクションを本スキルが実体化したものとして位置づける。

## 実行場所

下流チャンネルリポジトリ（自リポが `youtube-channels-automation` を依存として `pyproject.toml` で参照している側）でのみ意味を持つ。upstream リポ（`daiki-beppu/youtube-automation` 本体）は `pyproject.toml` の `name = "youtube-channels-automation"` 自身を持つので、Step 1-1 の判定で `upstream` と分岐して終了する。

## AI が絶対に勝手にやらないこと

以下は破壊的・対外的な操作のため、必ず `[HUMAN STEP]` で人間判断を取ってから AI が実行する（または人間に手動実行を依頼する）:

- `uv run yt-skills sync --force` — local fix を破棄する場合
- `git push` — **AI は commit までで停止**。push は完了メッセージで利用者に依頼するだけ
- 既存の手書き skill（過去に `.claude/skills/community-post/` / `community-draft/` 等を手書きで配置していた場合）の上書き判断
- sha pin の場合の bump 先 sha 確定
- `--prune` による「target 側にのみ存在する旧 skill ディレクトリ」の削除判断（rename 跡が含まれる可能性）

## [HUMAN STEP] の書き方

`/onboard` と同じ形式で停止する:

```
> [HUMAN STEP]
> 以下の差分を確認してください:
>   <diff 抜粋 or 内容>
>
> 進めてよければ "yes"、中止なら "no" と返してください。
```

利用者が "yes" を返すまで、AI は次の Bash ツール呼び出しをしない。

## Phase 1: 現状把握

### Step 1-1. 実行場所と前提コマンドの確認

```bash
# 自リポ name が youtube-channels-automation 自身なら upstream リポ → このスキルは下流リポ専用なので終了
if grep -qE '^\s*name\s*=\s*"youtube-channels-automation"' pyproject.toml 2>/dev/null; then
  echo "このスキルは下流リポ専用です（upstream リポ自身では発動しません）"
  exit 0
fi

# 依存として参照していなければ追従対象なし
grep -q 'youtube-channels-automation' pyproject.toml || { echo "❌ pyproject.toml に youtube-channels-automation の依存参照が見つかりません"; exit 1; }

# 必須コマンドが揃っているか
gh auth status 2>&1 | head -3   # gh 未認証なら [HUMAN STEP] で `gh auth login` を依頼
uv --version                    # uv 未インストールなら /onboard 完了を依頼
command -v git >/dev/null || { echo "❌ git が必要"; exit 1; }

# 作業ツリーが clean か
git status --porcelain
```

`gh auth status` が green でない場合:

```
> [HUMAN STEP]
> gh CLI が未認証です。以下を実行してください:
>   gh auth login
> 完了したら "done" と返してください。
```

`git status --porcelain` が **非空** の場合は、追従コミットに無関係な変更が混入するため停止:

```
> [HUMAN STEP]
> 作業ツリーに未コミットの変更があります:
>   <git status --porcelain の出力>
>
> stash / commit / 破棄 のいずれかで clean にしてから "done" と返してください。
```

### Step 1-2. 自リポの pin 形式を判定

```bash
# 複数行 inline table 形式 (= { git = "...", tag = "..." }) も拾うため文脈付きで grep
grep -nA 3 'youtube-channels-automation' pyproject.toml
```

該当行を読んで pin 形式を分類:

| パターン | マッチ例 | 後続処理 |
|---|---|---|
| **tag pin** | `tag = "v5.5.1"` | Phase 3 で tag 文字列を sed で書き換え |
| **main 追従** | 無印 / `branch = "main"` | Phase 3 で `uv lock` のみ |
| **sha pin** | `rev = "<40 桁>"` | Phase 3 で `[HUMAN STEP]` で bump 先 sha 確認 |

判定結果から **`<old>` 変数** を抽出して以降の Phase で使い回す（tag pin なら `v5.5.0` 等、sha pin なら 40 桁 sha、main 追従なら `main`）。

### Step 1-3. upstream 最新リリースを取得

```bash
# 飛び級ケース (v5.0.0 → v5.5.x 等) を取りこぼさないため limit を大きめに
gh release list --repo daiki-beppu/youtube-automation --limit 50 --json tagName,publishedAt,isLatest
```

`isLatest=true` の `tagName` を **`<target>` 変数** とする。current が結果に含まれないほど離れている場合は `gh api repos/daiki-beppu/youtube-automation/releases --paginate` でフル取得する。

### Step 1-4. 差分判定と利用者への提示

- tag pin で現在の tag と target version が一致 → 「✓ 既に最新です（`v<X.Y.Z>`）」で終了
- main 追従の場合は uv.lock の `youtube-channels-automation` 行から現在解決 sha を取得し、upstream の `main` HEAD と比較（`gh api repos/daiki-beppu/youtube-automation/commits/main --jq .sha`）。一致なら「✓ 既に最新です」で終了
- sha pin の場合は常に `[HUMAN STEP]` で「target sha を `v<X.Y.Z>` に揃えるか、HEAD を取るか」を確認

利用者に提示する情報（例: tag pin で v5.5.0 → v5.5.1）:

```
現状: tag pin (v5.5.0)
更新先: v5.5.1 (publishedAt: 2026-05-12)

Phase 2 に進んで upgrade guide を取得し、変更内容を要約します。
```

## Phase 2: ガイド読み込みと要約

### Step 2-1. upgrade guide の取得

**単一バージョン差分の場合**（例: v5.5.0 → v5.5.1）:

```bash
gh api repos/daiki-beppu/youtube-automation/contents/docs/upgrades/v<target>.md --jq .content | base64 -d > /tmp/upgrade-v<target>.md
```

`gh api` が失敗した場合のフォールバック:

```bash
curl -sL https://raw.githubusercontent.com/daiki-beppu/youtube-automation/main/docs/upgrades/v<target>.md > /tmp/upgrade-v<target>.md
```

または Claude Code の WebFetch tool で同 URL を取得。

### Step 2-2. 中間バージョン跨ぎ（v5.0.0 → v5.5.1 等）

**方針: 一気に最新へ飛ぶ。中間ガイドは累積要約のみ提示する**（利用者に毎回確認しない）。

- Phase 1 で取得した `gh release list` 結果から、current 〜 target の間に挟まる全 tag を抽出
- 各 `v*.md` を順に取得（404 のものは警告だけ出してスキップ）
- AI が各ファイルから「**重大変更 Top 3**」「**local fix 衝突注意**」を抽出し、**累積版** として 1 つにまとめる

### Step 2-3. ガイドから抽出する固定要素

`/release-notes` が生成する `docs/upgrades/v<ver>.md` は以下の構造を持つ（**契約として扱う**。`/release-notes` の `references/release-notes-template.md` と同期する前提）:

- 「**所要時間の目安: X〜Y 分**」 — 冒頭行
- 「**■ TL;DR（30 秒サマリー）**」 — 4 項目（新機能 / 既存機能改善 / バグ修正 / やること）
- 「**■ あなたのチャンネルへの影響**」 — `── パターン A: tag pin ──` / `── パターン B: main 追従 ──` / `── local fix がある場合の追加対応 ──`
- 「**■ トラブルシューティング**」 — Q&A

AI は最低でも以下を要約として提示:

1. **重大変更 Top 3** — TL;DR の「新しくできるようになったこと」「直った不具合」「やること」から運営者影響の大きい順
2. **local fix 衝突注意** — 「── local fix がある場合の追加対応 ──」セクション全文
3. **所要時間の目安**
4. **中間バージョン累積版の場合**: 跨ぐ各バージョンの「重大変更 Top 1〜2」を箇条書きで併記

### Step 2-4. 利用者への同意取得

```
> [HUMAN STEP]
> 以下が v<target> への追従内容です:
>
>   所要時間: X〜Y 分
>   重大変更 Top 3:
>     1. ...
>     2. ...
>     3. ...
>   local fix 衝突注意:
>     ...
>
> このまま Phase 3 (実行) に進んでよければ "yes" と返してください。
> 内容を確認してから判断したければ /tmp/upgrade-v<target>.md を開いてください。
> 中止する場合は "no" と返してください（Phase 3 はスキップして終了）。
```

`no` が返ってきた場合は何も書き換えずに完了メッセージを出して終了する（pyproject.toml も uv.lock も触らない）。

## Phase 3: 追従実行

### Step 3-1. pyproject.toml の pin 書き換え

**tag pin**:

`<old>` (Step 1-2) と `<target>` (Step 1-3) を実値に展開し、GNU/BSD sed どちらでも動く `-i.bak` 形式で書き換える:

```bash
# 例: v5.5.0 → v5.5.1
sed -i.bak 's/tag = "v<old>"/tag = "v<target>"/' pyproject.toml && rm pyproject.toml.bak
git diff pyproject.toml   # 利用者に差分を見せる
```

`git diff` の結果が空 = sed が何もマッチしなかった場合は、pyproject.toml の記法が想定と違う可能性があるので `[HUMAN STEP]` で当該箇所を見せて手動編集を依頼する。

**main 追従**: 書き換え不要（次の `uv lock` で取り込み）。

**sha pin**:

```
> [HUMAN STEP]
> sha pin (rev = "<old>") を検出しました。bump 先を決めてください:
>   (a) v<target> tag の sha に揃える
>   (b) main HEAD の sha を取る
>   (c) 手動で sha を指定する
> a / b / c を返してください。
```

選択に応じて `gh api repos/daiki-beppu/youtube-automation/git/refs/tags/v<target> --jq .object.sha` 等で sha を解決し、`pyproject.toml` の `rev = "..."` を `sed -i.bak '...' pyproject.toml && rm pyproject.toml.bak` で書き換え。

### Step 3-2. uv lock を更新

```bash
uv lock --upgrade-package youtube-channels-automation
```

失敗時はガイドの **Q3（依存解決失敗）** を引用してリトライ手順を案内:

```bash
uv cache clean
uv lock --upgrade-package youtube-channels-automation
```

### Step 3-3. local fix の検出と上書き判断

```bash
uv run yt-skills diff
```

差分なし → そのまま Step 3-4 へ。

**差分あり** → 利用者に提示して判断を取る:

```
> [HUMAN STEP]
> yt-skills diff で以下の差分を検出しました:
>   <diff 抜粋>
>
> 対応を選んでください:
>   (a) upstream 版で上書き (yt-skills sync --force) — local fix は破棄されます
>   (b) 該当 skill だけスキップして他を同期 (--only で個別指定)
>   (c) 中止して手動でマージ
> a / b / c を返してください。
```

### Step 3-4. skills を同期

選択に応じて以下を実行:

- (a) 上書き: `uv run yt-skills sync --force`
- (b) 個別同期: `uv run yt-skills sync --only <skill1> <skill2> ...`（衝突 skill を除いたリストを利用者と確認、引数は **空白区切り**）
- 差分なし: `uv run yt-skills sync`

`--prune`（target 側にのみ存在する旧 skill ディレクトリの削除）は **利用者が明示同意した場合のみ** 付ける。`--prune` 単独では列挙のみで実削除されないため、削除する場合は `--prune --yes` を併用する必要がある（例: `uv run yt-skills sync --prune --yes`）。デフォルトでは付けない。

### Step 3-5. 動作確認

ガイドの「■ 追従後に確認すべきこと」に従って順に実行:

```bash
uv run yt-config-migrate verify
uv run yt-channel-status
uv run yt-doctor
uv run yt-skills list
```

`command not found` / `No module named` が出た場合は **ガイドが古いと判断せず**、env 側の問題として以下を案内（ガイドの **Q4** より）:

```bash
uv sync
uv pip list | grep youtube-channels-automation
# それでもダメなら
uv cache clean
uv lock --upgrade-package youtube-channels-automation
uv sync
```

`yt-doctor` で WARNING / FAILED が出た場合は `/onboard` を起動して再診断するよう案内。

## Phase 4: コミット（push は人間）

### Step 4-1. ステージング

```bash
git status
git add pyproject.toml uv.lock .claude/skills/
```

`git add -A` や `.` は **使わない**（無関係なファイルの巻き込みを避ける）。

### Step 4-2. コミット

`commit-convention` スキル準拠で日本語 Conventional Commits:

```bash
git commit -m "chore: youtube-automation v<target> への追従"
```

下流側に追従 issue 番号が確定している場合（例: bobble#41 のような）は、利用者に確認して末尾に `(#N)` を付ける:

```bash
git commit -m "chore: youtube-automation v<target> への追従 (#N)"
```

### Step 4-3. push は AI が実行しない

完了メッセージで以下を案内するだけで終了:

```
✓ v<target> へのローカル追従が完了しました。
  以下を実行してリモートへ反映してください:
    git push

  動作確認で気になる点があれば /onboard で再診断してください。
```

## Gotchas

- **`v*.md` の 404**: 古いバージョンのガイドが retroactively 削除されている可能性がある。警告だけ出してスキップ
- **`uv.lock` 添付忘れ**: `git add` で uv.lock を含めないと追従が永続化されない。Phase 4-1 で `git status` を必ず確認
- **同一 tag の再発行**: 稀に upstream が同 tag を force push し直す。`publishedAt` の差分や `gh release view v<target>` で差分有無を確認して人間に判断を仰ぐ

## Rules

- 人間が答えるべきステップ（上書き判断 / push 判断 / sha pin の bump 先 / `--prune` 付与）を AI が勝手に決めない
- `--force` / `--prune` 系の破壊的操作は必ず `[HUMAN STEP]` の同意を経る
- ガイドの抽出セクション境界（`■ TL;DR`, `── local fix がある場合の追加対応 ──`）は upstream の `/release-notes` テンプレとの **インターフェース契約**。`/release-notes` 側のテンプレが変わったら Phase 2-3 も同期更新する

## Cross References

- `/release-notes` — upstream 側のガイド生成スキル（本スキルの入力源 `docs/upgrades/v<ver>.md` を作る）
- `/onboard` — 追従後に `yt-doctor` で WARNING / FAILED が出た場合の再診断入口、および `[HUMAN STEP]` の書き方の参考実装
- `commit-convention` — Phase 4 のコミットメッセージ規約
