---
name: automation-update
description: "Use when 下流チャンネルリポジトリで youtube-channels-automation を upstream 最新リリースに追従させたいとき。「追従」「アップグレード」「最新版に上げて」「v5.x.y に上げて」「automation-update」「automation を更新」「skills sync 含めて更新」など、`pyproject.toml` の pin bump → `uv lock` → `yt-skills sync` → 動作確認 → コミットまでを 1 コマンドで回したい場面で使用する。GitHub Release 本文と `CHANGELOG.md` から累積影響を要約し、local fix 衝突や破壊的操作の前で人間に確認を求める AI 主導 wizard。"
---

## Overview

このスキルは **AI 主導の追従 wizard** である。下流チャンネルリポジトリ（bobble / deepfocus365 / rjn 等）で発動し、自リポの `pyproject.toml` を upstream `daiki-beppu/youtube-automation` の最新 tag まで bump して、`.claude/skills/` の同期、動作確認、コミットまでを 1 コマンドで回す。

機械的に決まる手順（実行場所判定 / pin 形式判定 / 差分判定 / pin 書き換え / `uv lock` / `yt-skills sync` / smoke check）は upstream 同梱の **`yt-automation-update` CLI** に委譲する。本スキル（AI）は判断が必要なポイント — リリース内容の要約、local fix 上書き判断、同意取得、コミット — に専任する。

利用者は upstream のリリース内容を都度追わなくてよい。AI が各リリースの **GitHub Release 本文** と **`CHANGELOG.md` の該当バージョンセクション** から累積影響を要約してから、破壊的操作の前で `[HUMAN STEP]` として人間判断を求める。

Phase 2 の入力源の優先順位:

1. `gh release view v<target> --json body` の本文（`gh` 未インストール時は GitHub REST API を `curl` で取得）
2. 上記が空 / 取得失敗した場合は `gh api .../contents/CHANGELOG.md` または raw `CHANGELOG.md` を `curl` で取得し、`[<target>] - <DATE>` セクションを抽出

Migration セクションの構造契約は `docs/changelog-contract.md` を参照（所要時間の目安 / local fix 衝突注意 が必須要素）。

## 実行場所

下流チャンネルリポジトリ（自リポが `youtube-channels-automation` を依存として `pyproject.toml` で参照している側）でのみ意味を持つ。判定は `yt-automation-update check` が機械的に行う: upstream リポ自身（`[project].name` が `youtube-channels-automation`）や依存参照のないリポで実行すると exit 2 の明示エラーで停止する。

その場合、AI は単に「依存が見つからない」で終わらせず、**移動先候補のチャンネルフォルダ** を探して案内する:

```bash
find "$HOME/02-yt" "$HOME/01-yt" "$HOME" -maxdepth 4 -type f -name pyproject.toml \
  -not -path '*/.venv/*' -not -path '*/.git/*' 2>/dev/null | head -50
```

各 pyproject.toml の `[project].dependencies` に `youtube-channels-automation` を含むものが候補（-, _, . は同一扱い）。`[project].name` が `youtube-channels-automation` の upstream 本体は除外する。候補が見つかったら `cd -- <dir>`（パスは shell escape して提示）してから本スキルを再実行するよう依頼する。

## AI が絶対に勝手にやらないこと

以下は破壊的・対外的な操作のため、必ず `[HUMAN STEP]` で人間判断を取ってから AI が実行する（または人間に手動実行を依頼する）:

- `yt-automation-update apply --force-sync` — local fix を破棄する場合
- `git push` — **AI は commit までで停止**。push は完了メッセージで利用者に依頼するだけ
- 既存の手書き skill（過去に `.claude/skills/community-post/` / `community-draft/` 等を手書きで配置していた場合）の上書き判断
- sha pin の場合の bump 先 sha 確定（`apply --rev <sha>` に渡す sha の決定）
- `--prune` による「target 側にのみ存在する旧 skill ディレクトリ」の削除判断（rename 跡が含まれる可能性。CLI の責務外のまま）

## [HUMAN STEP] の書き方

`/setup` と同じ形式で停止する:

```
> [HUMAN STEP]
> 以下の差分を確認してください:
>   <diff 抜粋 or 内容>
>
> 進めてよければ "yes"、中止なら "no" と返してください。
```

利用者が "yes" を返すまで、AI は次の Bash ツール呼び出しをしない。

## Phase 1: 現状把握

### Step 1-1. 差分チェック（CLI）

```bash
uv run yt-automation-update check
```

| exit code | 意味 | 次のアクション |
|---|---|---|
| 0 | 既に最新 | 「✓ 既に最新です」と報告して終了 |
| 1 | 差分あり（要追従） | 出力から pin 形式と pin 種別ごとの target（tag pin は最新 tag、main 追従は upstream HEAD sha、sha pin は `[HUMAN STEP]` で決める bump 先）を控えて Step 1-2 へ |
| 2 | エラー（実行場所不適切 / registry 参照 等） | メッセージに従い対処。実行場所エラーは「実行場所」セクションの候補探索を実施 |

`command not found: yt-automation-update` の場合は、導入済み automation が CLI 追加前の旧版。Gotchas の「CLI 未搭載の旧版からの初回追従」を参照。

pin 形式ごとの check の挙動:

| pin 形式 | check の判定 |
|---|---|
| **tag pin**（inline table `tag = "vX.Y.Z"` / URL 直接参照 `@vX.Y.Z`） | 現在 tag と最新リリース tag を比較 |
| **main 追従**（tag 無し / `branch = "main"` / URL 直接参照 `@main`） | `uv.lock` の解決済み sha と upstream HEAD を比較。Phase 2 は latest release tag ではなく upstream HEAD sha 追従として扱う |
| **sha pin**（`rev = "<40 桁>"`） | 常に exit 1（自動判定対象外）。latest release tag は自動取得せず、`[HUMAN STEP]` で bump 先を確認 |

sha pin の場合の `[HUMAN STEP]`:

```
> [HUMAN STEP]
> sha pin (rev = "<old>") を検出しました。bump 先を決めてください:
>   (a) 最新 release tag の sha に揃える
>   (b) main HEAD の sha を取る
>   (c) 手動で sha を指定する
> a / b / c を返してください。
```

選択に応じて `gh release view --repo daiki-beppu/youtube-automation --json tagName --jq .tagName` → `gh api repos/daiki-beppu/youtube-automation/git/refs/tags/<tag> --jq .object.sha`、または `gh api repos/daiki-beppu/youtube-automation/commits/main --jq .sha` 等で sha を解決し、Phase 3 の `apply --rev <sha>` に使う。

### Step 1-2. 前提確認

```bash
git status --porcelain
command -v gh >/dev/null 2>&1 && gh auth status 2>&1 | head -3
```

`git status --porcelain` が **非空** の場合は、追従コミットに無関係な変更が混入するため停止（`apply` 自身も作業ツリー確認で止まる）:

```
> [HUMAN STEP]
> 作業ツリーに未コミットの変更があります:
>   <git status --porcelain の出力>
>
> /channel-new 直後の初回保存が未完了なら、まず初回 commit を作成してください。
> それ以外の差分は stash / commit / 破棄 のいずれかで clean にしてから "done" と返してください。
```

`gh` があるのに `gh auth status` が green でない場合:

```
> [HUMAN STEP]
> gh CLI が未認証です。以下を実行してください:
>   gh auth login
> 完了したら "done" と返してください。
```

## Phase 2: リリース本文読み込みと要約

入力源は `gh release view --json body`（第 1 経路、`gh` 未インストール時は `curl`）と `CHANGELOG.md` の該当バージョンセクション（第 2 経路 / fallback）。フォーマット契約は upstream の `docs/changelog-contract.md` を参照。

経路の決定:

```bash
if command -v gh >/dev/null 2>&1; then
  export YT_AUTOMATION_GITHUB_MODE=gh
else
  command -v curl >/dev/null || { echo "❌ gh CLI が無い環境では curl が必要"; exit 1; }
  export YT_AUTOMATION_GITHUB_MODE=curl
  echo "ℹ gh CLI が未インストールのため curl で GitHub API を直接呼び出します"
fi
```

### Step 2-1. Release 本文の取得（単一バージョン差分）

**第 1 経路: GitHub Release 本文**

```bash
if [ "${YT_AUTOMATION_GITHUB_MODE:-gh}" = "gh" ]; then
  gh release view "v<target>" --repo daiki-beppu/youtube-automation --json body --jq .body > /tmp/release-v<target>.md
else
  curl -fsSL "https://api.github.com/repos/daiki-beppu/youtube-automation/releases/tags/v<target>" \
    > /tmp/release-v<target>.json
  python3 - <<'PY' > /tmp/release-v<target>.md
import json
from pathlib import Path

release = json.loads(Path("/tmp/release-v<target>.json").read_text())
print(release.get("body") or "")
PY
fi
```

`/tmp/release-v<target>.md` が空 / コマンド失敗の場合は第 2 経路に進む。

**第 2 経路: CHANGELOG.md の該当バージョンセクション**

```bash
if [ "${YT_AUTOMATION_GITHUB_MODE:-gh}" = "gh" ]; then
  gh api repos/daiki-beppu/youtube-automation/contents/CHANGELOG.md --jq .content | base64 -d > /tmp/changelog.md
else
  curl -fsSL https://raw.githubusercontent.com/daiki-beppu/youtube-automation/main/CHANGELOG.md \
    > /tmp/changelog.md
fi

ver="<target without v>"   # 例: 5.5.1
awk -v ver="$ver" '
  $0 ~ "^## \\[" ver "\\]" { flag = 1; next }
  /^## \[/                  { flag = 0 }
  flag
' /tmp/changelog.md > /tmp/changelog-section-v<target>.md
```

両経路ともに空になった場合は Phase 2 を `[HUMAN STEP]` に切り替えて利用者に手動確認を依頼する（古いリリースで Release 本文が削除されている等の例外ケース）。

### Step 2-2. 中間バージョン跨ぎ（v5.0.0 → v5.5.1 等）

**方針: 一気に最新へ飛ぶ。中間バージョンは累積要約のみ提示する**（利用者に毎回確認しない）。

```bash
if [ "${YT_AUTOMATION_GITHUB_MODE:-gh}" = "gh" ]; then
  gh release list --repo daiki-beppu/youtube-automation --limit 50 \
    --json tagName,publishedAt,isLatest
else
  curl -fsSL 'https://api.github.com/repos/daiki-beppu/youtube-automation/releases?per_page=50' \
    > /tmp/youtube-automation-releases.json
  python3 - <<'PY'
import json
from pathlib import Path

releases = json.loads(Path("/tmp/youtube-automation-releases.json").read_text())
print(json.dumps([
    {
        "tagName": r["tag_name"],
        "publishedAt": r.get("published_at"),
        "isLatest": i == 0,
    }
    for i, r in enumerate(releases)
], ensure_ascii=False))
PY
fi
```

current 〜 target の間に挟まる全 tag を抽出し、各 tag について Step 2-1 と同じ手順（Release 本文 → CHANGELOG fallback）で本文を取得する。404 / 空はスキップ（警告のみ）。AI が各リリースから「**重大変更 Top 3**」「**Fixed**」「**Migration セクション全文**」を抽出し、**累積版** として 1 つにまとめる。

### Step 2-3. リリース本文から抽出する固定要素

CHANGELOG / Release 本文の各バージョンセクションは以下の構造を持つ（フォーマット契約: `docs/changelog-contract.md`）:

- `### Added` / `### Changed` / `### Fixed` / `### Removed` / `### Migration`（必要なもののみ存在）
- `### Migration` セクションには以下が含まれる:
  - 1 行目: `所要時間の目安: X〜Y 分`
  - `local fix 衝突注意:` 配下に該当 skill 名（または「無し」）
  - サマリ箇条書き

AI は以下を抽出して提示する:

1. **重大変更 Top 3** — `### Added` / `### Changed` から運営者影響の大きい順に 3 件を AI が選別（破壊的変更・新機能・運用挙動の変更）
2. **Fixed 一覧** — `### Fixed` セクションの全行（バグ修正で「これまで失敗していた操作が成功するようになる」内容）
3. **Migration セクション全文** — `### Migration` 配下をそのまま転記
   - 1 行目の `所要時間の目安: X〜Y 分` を `<elapsed>` 変数に保持して Step 2-4 で提示
   - `local fix 衝突注意:` 配下の skill リストを `<conflicts>` 変数に保持して Step 3-1 の検出対象として使う
4. **中間バージョン累積版の場合**: 跨ぐ各バージョンの「重大変更 Top 1〜2」と各 Migration の `所要時間` / `local fix 衝突注意` を箇条書きで併記

**Migration セクションが欠落しているリリース**（古いフォーマット・Release 本文に `--generate-notes` の PR list のみ等）の場合は fallback として CHANGELOG / Release 本文全体を AI に渡して累積要約を生成する。`所要時間` / `local fix 衝突注意` が抽出できなかった旨を明示し、Step 3-1 で `[HUMAN STEP]` で利用者に skill 一覧を確認してもらう。

### Step 2-4. 利用者への同意取得

```
> [HUMAN STEP]
> 以下が v<target> への追従内容です（CHANGELOG.md / GitHub Release 本文より抽出）:
>
>   所要時間: <elapsed>（Migration セクションより）
>   重大変更 Top 3:
>     1. ...
>     2. ...
>     3. ...
>   Fixed:
>     - ...
>   local fix 衝突注意:
>     <conflicts>
>
> このまま Phase 3 (実行) に進んでよければ "yes" と返してください。
> 詳細を確認したければ /tmp/release-v<target>.md または /tmp/changelog-section-v<target>.md を開いてください。
> 中止する場合は "no" と返してください（Phase 3 はスキップして終了）。
```

`no` が返ってきた場合は何も書き換えずに完了メッセージを出して終了する（pyproject.toml も uv.lock も触らない）。

## Phase 3: 追従実行

### Step 3-1. local fix の検出と上書き判断

`apply` は skills sync を含むため、**apply 実行前に** local fix を検出して人間判断を取る:

```bash
uv run yt-skills diff
```

差分なし → そのまま Step 3-2 へ（無印 `apply`）。

**差分あり** → 利用者に提示して判断を取る:

```
> [HUMAN STEP]
> yt-skills diff で以下の差分を検出しました:
>   <diff 抜粋>
>
> 対応を選んでください:
>   (a) upstream 版で上書き (apply / apply --force-sync) — local fix は破棄されます
>   (b) 指定した安全な skill だけ同期 (apply --sync-only で allowlist 指定)
>   (c) 中止して手動でマージ
> a / b / c を返してください。
```

#### 自スキル (automation-update) が差分対象に含まれる特例

`yt-skills diff` の出力に **`automation-update` 自身** が含まれる場合、上記 (a)/(b)/(c) prompt の **前に** 自スキル更新の特例 prompt を出して、変更内容を構造的に提示してから確認を取る:

```bash
# 自スキル分の同梱版を取得し、unified diff として表示
python - <<'PY' > /tmp/automation-update-bundled.SKILL.md
from youtube_automation.cli.skills_sync import _asset_root

print((_asset_root("skills") / "automation-update" / "SKILL.md").read_text(encoding="utf-8"), end="")
PY
diff -u .claude/skills/automation-update/SKILL.md /tmp/automation-update-bundled.SKILL.md || true
```

`yt-skills` には export コマンドは無い。wheel 同梱 asset は `youtube_automation.cli.skills_sync._asset_root("skills")` から取得する。

AI は取得した unified diff を **H2 セクション境界（`## `）で集約** し、「Phase X の手順が変わる」「Gotchas に Y が追加」のようなセクション単位の要約を作って提示する:

```
> [HUMAN STEP]
> ⚠ このスキル自身 (automation-update) が更新対象に含まれています。
>
> 変更内容（セクション単位の要約）:
>   - Phase 3-1: <要約>
>   - Gotchas: <要約>
>
> 仕様:
>   - sync 実行後も、本セッションは旧版 SKILL.md の手順で完走します
>     （Claude Code はセッション開始時に SKILL.md をロードしてメモリ保持するため）
>   - 次回 /automation-update を起動した時点から新版が適用されます
>   - 手書き改造（local fix）がある場合は破棄されます
>
> 続行してよければ "yes"、自スキルだけ手動マージしたければ "manual" と返してください。
```

`"manual"` が返ってきた場合は、自スキルは利用者に手動マージを依頼する。他に上書きしてよい skill が明確な場合だけ、Step 3-2 の (b) `--sync-only <safe-skill...>` でその skill だけ同期する（`--sync-only` は除外指定ではなく allowlist 指定）。

#### `config.default.yaml` の直接編集が検出された場合の特例

`yt-skills diff` の出力に **`.claude/skills/<skill>/config.default.yaml`** が含まれる場合、それは運営者が直接編集してしまっている可能性が高い。`config.default.yaml` は upstream 管理のデフォルト設定で、運営者のカスタム値は **`config/skills/<skill>.yaml`** に置く運用が正しい（deep-merge される）。直接編集を維持して `--force-sync` で上書きすると変更が失われる。

検出時は通常の (a)/(b)/(c) prompt の **前に** 移行案内 prompt を出す:

```
> [HUMAN STEP]
> ⚠ config.default.yaml の直接編集が検出されました:
>   - .claude/skills/<skill1>/config.default.yaml
>   - .claude/skills/<skill2>/config.default.yaml
>
> これらは upstream 管理のデフォルト設定です。直接編集すると yt-skills sync で失われます。
>
> 正しい運用:
>   1. 編集内容を <channel-repo>/config/skills/<skill>.yaml に移す（無ければ新規作成）
>      → config.default.yaml の上に deep-merge される。上書きしたいキーだけ書けば OK
>   2. .claude/skills/<skill>/config.default.yaml は upstream 版で上書き
>
> 対応を選んでください:
>   (a) 移行を手伝う — AI が差分を読み取って config/skills/<skill>.yaml に書き出す
>   (b) 今は対応しない、直接編集を維持（次回 sync で再度警告される）
>   (c) 中止して手動マージ
> a / b / c を返してください。
```

`(a) 移行を手伝う` が選ばれた場合:

1. `yt-skills diff` の出力から該当 `config.default.yaml` の差分を抽出
2. **追加・変更されたキーだけ** を `<channel-repo>/config/skills/<skill>.yaml` に書き出す（既存ファイルがあれば deep-merge、無ければ新規作成）
3. ディレクトリ `config/skills/` が無ければ作成
4. 利用者に書き出した内容を提示して確認
5. その後 Step 3-2 で `--force-sync` を付けて `.claude/skills/<skill>/config.default.yaml` を upstream 版に戻す
6. Step 3-2 へ進む

`(b)` が選ばれた場合は通常の (a)/(b)/(c) 分岐へ進む（今回は直接編集を維持し、Step 3-2 で `--sync-only` allowlist または上書き同期を選ばせる）。

### Step 3-2. 追従の一括実行（CLI）

Step 3-1 の判断結果に応じて 1 コマンドで実行:

```bash
uv run yt-automation-update apply                                    # local fix 差分なし（CLI が yt-skills diff で再確認）
uv run yt-automation-update apply --force-sync                       # (a) 上書き
uv run yt-automation-update apply --sync-only <skill1> <skill2> ...  # (b) 指定した安全な skill だけ同期（引数は空白区切り）
uv run yt-automation-update apply --rev <sha>                        # sha pin（bump 先は Step 1-1 の [HUMAN STEP] で確定）
```

`apply` の内部ステップ（順に実行、失敗時は **失敗ステップ名を明示して非 0 終了**）:

1. git 作業ツリー確認（clean でなければ停止）
2. `pyproject.toml` の pin 書き換え（tag pin は inline table / URL 直接参照の両形式対応。main 追従はスキップ）
3. `uv lock --upgrade-package youtube-channels-automation`
4. `yt-skills sync --force`（デフォルト `--asset all` = skills / claude-md / docs ほか全 asset。`--force-sync` は CLI 内の local fix 差分ガードを承認済み上書きとして通過する。`--sync-only` 時は指定した安全な skill だけを skills `--only` で同期し、claude-md は別途同期される）
5. smoke check: `yt-skills list` / `yt-config-migrate verify`

途中失敗時は表示された失敗ステップの原因を解消し、**同コマンド + `--allow-dirty`** で再実行する（apply 自身の pin 書き換えで作業ツリーが dirty になっているため。ステップは冪等）。`uv lock` 失敗が続く場合は `uv cache clean` してから再実行。pin 記法が想定外で書き換えできない旨のエラーが出た場合は `[HUMAN STEP]` で該当箇所を見せて手動編集を依頼する。

`--prune`（target 側にのみ存在する旧 skill ディレクトリの削除）は CLI の責務外。利用者が明示同意した場合のみ `uv run yt-skills sync --prune --yes` を別途実行する（`--prune` 単独では列挙のみで実削除されない）。

### Step 3-3. 追加の動作確認（判断を伴うもの）

`apply` の smoke check は機械ゲートのみ。以下は AI が結果を読んで判断する:

```bash
uv run yt-doctor
uv run yt-channel-status
```

- `yt-doctor` で WARNING / FAILED が出た場合は `/setup` を起動して再診断するよう案内
- `command not found` / `No module named` が出た場合は **追従内容が原因と判断せず**、env 側の問題として `uv sync` → それでもダメなら `uv cache clean && uv lock --upgrade-package youtube-channels-automation && uv sync` を案内

#### 番号付き重複ファイルの検知と再発防止

`yt-doctor` の `numbered_duplicates` チェック（または `yt-skills sync` の warning）が `.venv/bin/` / `.claude/skills/` への `yt-analytics 2` のような「スペース + 連番」重複を報告した場合、iCloud Drive 等のクラウド同期コンフリクトによる汚染（生成メカニズムは upstream #1409）。放置すると Phase 4 の `git add .claude/skills/` で重複が commit に紛れ込むため、**Phase 4 に進む前に必ず対処する**:

1. `find .claude/skills .venv/bin -name '* [0-9]*'` で分布を確認
2. upstream の [番号付き重複ファイル cleanup guide](https://github.com/daiki-beppu/youtube-automation/blob/main/docs/migration/numbered-duplicate-files-cleanup.md) の手順でクリーンアップ
   （`.venv` は `rm -rf .venv && uv sync` で再作成、`.claude/skills/` は重複削除 →
   `uv run yt-skills sync --asset skills --force`）
3. 再発防止を `[HUMAN STEP]` で案内: リポジトリが iCloud Drive 同期対象
   （`~/Desktop` / `~/Documents` / iCloud Drive フォルダ）にある場合は同期対象外への
   移設が唯一の根本対策。`uv run --frozen` は再発防止にならない（lockfile 再解決を
   止めるだけで venv への sync は走る）。つなぎの対症療法は `uv run --no-sync` または
   `UV_NO_INSTALLER_METADATA=1`

#### 自スキルの frontmatter 健全性チェック

`yt-skills sync` で `.claude/skills/automation-update/SKILL.md` 自身が上書きされた場合、新版の frontmatter が壊れていると **次回起動でスキル発動できなくなる**（YAML パース失敗）。sync 直後に必ず確認:

```bash
head -5 .claude/skills/automation-update/SKILL.md
```

`---` で囲まれた YAML が `name:` と `description:` を含み、2 つ目の `---` で閉じていれば OK。

壊れていた場合（YAML パース不能 / frontmatter 不完全）は git でロールバック:

```bash
git checkout .claude/skills/automation-update/SKILL.md
```

その後、本スキルを利用者の手元で再走するのではなく、上流の issue として報告するよう案内する（automation-update 自身に問題があるため再帰的に追従できない状況）。

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

  動作確認で気になる点があれば /setup で再診断してください。
```

## Gotchas

- **CLI 未搭載の旧版からの初回追従**: `yt-automation-update` CLI 追加前の版が入っている下流リポでは `uv run yt-automation-update` が command not found になる。tag pin の場合は pin の tag を手で `v<target>` へ書き換えたうえで `uv lock --upgrade-package youtube-channels-automation && uv sync` を実行して新版を先に取り込む（main 追従なら書き換え不要で lock/sync のみ）。以降は本スキルの手順どおり `check` から再実行できる
- **Release 本文 / CHANGELOG セクションが空**: 古いリリースで `--generate-notes` の PR list のみが残っているケースや、CHANGELOG への昇格が漏れているケース。Step 2-1 で両経路ともに空になった場合は `[HUMAN STEP]` で利用者に手動確認を依頼
- **`### Migration` セクション欠落**: フォーマット契約は v5.6.0 以降で強制されるため、それ以前のリリース本文には Migration セクションが無いケースがある。Step 2-3 の fallback で CHANGELOG / Release 本文全体を AI 累積要約する。`所要時間` / `local fix 衝突注意` が抽出できないため Step 3-1 で必ず `[HUMAN STEP]` で確認
- **`uv.lock` 添付忘れ**: `git add` で uv.lock を含めないと追従が永続化されない。Phase 4-1 で `git status` を必ず確認
- **同一 tag の再発行**: 稀に upstream が同 tag を force push し直す。`publishedAt` の差分や `gh release view v<target>` で差分有無を確認して人間に判断を仰ぐ
- **自スキルの self-overwrite**: 本スキル自身が `yt-skills diff` の差分対象に含まれる場合がある（v5.5.x → v5.5.y で本スキルが更新された等）。`yt-skills sync` は file 単位の順次上書き（atomicity なし、`--force` で削除→再作成）だが、Claude Code は SKILL.md をセッション開始時にメモリへロードするため、**同セッションでは旧版の手順で完走**し、**次回 /automation-update 起動以降で新版が適用**される。Step 3-1 の特例 prompt で利用者に明示すること。手書き改造（local fix）を残したい場合は `"manual"` 応答で自スキルは手動マージへ回し、他に安全に上書きできる skill がある場合だけ `--sync-only <safe-skill...>` で allowlist 同期する
- **sync 中の部分破損**: `yt-skills sync` のループに atomicity はない。途中失敗すると部分的に壊れた `.claude/skills/` が残る。Step 3-3 で自スキル frontmatter 健全性チェックを必ず実行し、壊れていれば `git checkout` でロールバック
- **番号付き重複ファイルの commit 混入**: sync 先に `<名前> <数字>` 形式の重複（iCloud bounce）があると Step 4-1 の `git add .claude/skills/` で commit に紛れ込む。Step 3-3 の検知（`yt-doctor` の `numbered_duplicates` / `yt-skills sync` の warning）で見つけたら、Phase 4 前に upstream の [番号付き重複ファイル cleanup guide](https://github.com/daiki-beppu/youtube-automation/blob/main/docs/migration/numbered-duplicate-files-cleanup.md) の手順で除去する
- **sync が触る範囲**: `yt-skills sync` の default (`--asset all`) は `.claude/skills/`、`.claude/CLAUDE.md`、`docs/{workflow-cheatsheet,features}.md`、`auth/client_secrets.template.json` を同期する。`auth/client_secrets.template.json` はテンプレートだけで、実 secret の `auth/client_secrets.json` / `auth/token*.json`、`config/channel/*.json`、`.env`、`collections/` は **絶対に上書きされない**。`pyproject.toml` と `uv.lock` は `apply` が明示的に書き換える
- **skill 配下の `config.default.yaml` は上書き対象**: 各スキル (`lyria` / `suno` / `masterup` 等) の `.claude/skills/<skill>/config.default.yaml` は upstream 管理のデフォルト設定なので `yt-skills sync` で確実に上書きされる。運営者のカスタム値は別ファイル `config/skills/<skill>.yaml`（チャンネルリポジトリ直下）に置く運用で、こちらは sync 対象外。`config.default.yaml` を直接編集している場合は `yt-skills diff` に local fix として現れるので Step 3-1 で検出される

## Rules

- 機械的手順（実行場所判定 / pin 形式判定 / 差分判定 / pin 書き換え / `uv lock` / `yt-skills sync` / smoke check）は `yt-automation-update` CLI に委譲し、AI が sed / uv lock 等を手で再実装しない
- 人間が答えるべきステップ（上書き判断 / push 判断 / sha pin の bump 先 / `--prune` 付与）を AI が勝手に決めない
- `--force-sync` / `--prune` 系の破壊的操作は必ず `[HUMAN STEP]` の同意を経る
- commit / push は CLI の責務外。Phase 4 で AI が commit まで行い、push は人間に依頼する
- Step 2-3 の抽出セクション境界（`### Added` / `### Changed` / `### Fixed` / `### Migration`）と Migration セクション必須要素（`所要時間の目安` / `local fix 衝突注意`）は upstream の `docs/changelog-contract.md` との **インターフェース契約**。upstream 側の契約が変わったら Phase 2-3 も同期更新する

## Cross References

- `src/youtube_automation/cli/automation_update.py`（upstream リポ）— 本スキルが委譲する機械的手順の実体（`yt-automation-update check` / `apply`）
- `docs/changelog-contract.md`（upstream リポ）— CHANGELOG.md / Release 本文の Migration セクションフォーマット契約（本スキルの入力構造定義）
- `/automation-release`（upstream リポ）— リリース PR を作成し CHANGELOG.md を昇格させる upstream 側スキル（本スキルが読み取るリリース本文を生成する）
- `/setup` — 追従後に `yt-doctor` で WARNING / FAILED が出た場合の再診断入口、および `[HUMAN STEP]` の書き方の参考実装
- `commit-convention` — Phase 4 のコミットメッセージ規約
