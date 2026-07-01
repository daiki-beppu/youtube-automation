---
name: automation-update
description: "Use when 下流チャンネルリポジトリで youtube-channels-automation を upstream 最新リリースに追従させたいとき。「追従」「アップグレード」「最新版に上げて」「v5.x.y に上げて」「automation-update」「automation を更新」「skills sync 含めて更新」など、`pyproject.toml` の pin bump → `uv lock` → `yt-skills sync` → 動作確認 → コミットまでを 1 コマンドで回したい場面で使用する。GitHub Release 本文と `CHANGELOG.md` から累積影響を要約し、local fix 衝突や破壊的操作の前で人間に確認を求める AI 主導 wizard。"
---

## Overview

このスキルは **AI 主導の追従 wizard** である。下流チャンネルリポジトリ（bobble / deepfocus365 / rjn 等）で発動し、自リポの `pyproject.toml` を upstream `daiki-beppu/youtube-automation` の最新 tag まで bump して、`.claude/skills/` の同期、動作確認、コミットまでを 1 コマンドで回す。

利用者は upstream のリリース内容を都度追わなくてよい。AI が `gh release list`（`gh` 未インストール時は `curl`）で最新を検出し、各リリースの **GitHub Release 本文** と **`CHANGELOG.md` の該当バージョンセクション** から累積影響を要約してから、破壊的操作の前で `[HUMAN STEP]` として人間判断を求める。

入力源の優先順位:

1. `gh release view v<target> --json body` の本文（`gh` 未インストール時は GitHub REST API を `curl` で取得）
2. 上記が空 / 取得失敗した場合は `gh api .../contents/CHANGELOG.md` または raw `CHANGELOG.md` を `curl` で取得し、`[<target>] - <DATE>` セクションを抽出

Migration セクションの構造契約は `docs/changelog-contract.md` を参照（所要時間の目安 / local fix 衝突注意 が必須要素）。

## 実行場所

下流チャンネルリポジトリ（自リポが `youtube-channels-automation` を依存として `pyproject.toml` で参照している側）でのみ意味を持つ。upstream リポ（`daiki-beppu/youtube-automation` 本体）は `pyproject.toml` の `name = "youtube-channels-automation"` 自身を持つので、Step 1-1 の判定で `upstream` と分岐して終了する。

対象外フォルダで起動された場合は、単に「依存が見つからない」とだけ言わず、**現在地が不適切な理由** と **移動先候補のチャンネルフォルダ** を必ず表示して終了する。候補を自動検出できない場合も、探し方（`pyproject.toml` 内の `youtube-channels-automation` 参照を探す）を具体的に案内する。

## AI が絶対に勝手にやらないこと

以下は破壊的・対外的な操作のため、必ず `[HUMAN STEP]` で人間判断を取ってから AI が実行する（または人間に手動実行を依頼する）:

- `uv run yt-skills sync --force` — local fix を破棄する場合
- `git push` — **AI は commit までで停止**。push は完了メッセージで利用者に依頼するだけ
- 既存の手書き skill（過去に `.claude/skills/community-post/` / `community-draft/` 等を手書きで配置していた場合）の上書き判断
- sha pin の場合の bump 先 sha 確定
- `--prune` による「target 側にのみ存在する旧 skill ディレクトリ」の削除判断（rename 跡が含まれる可能性）

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

### Step 1-1. 実行場所と前提コマンドの確認

```bash
is_channel_automation_dependency_pyproject() {
  local pyproject="$1"
  [ -f "$pyproject" ] || return 1
  python3 - "$pyproject" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

try:
    data = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

project = data.get("project")
if not isinstance(project, dict) or project.get("name") == "youtube-channels-automation":
    raise SystemExit(1)

dependency_name = re.compile(r"^\s*youtube-channels-automation(?=\s*(?:$|[\[<>=~!@;,]))")
for dependency in project.get("dependencies") or []:
    if isinstance(dependency, str) and dependency_name.match(dependency):
        raise SystemExit(0)

raise SystemExit(1)
PY
}

print_channel_repo_guidance() {
  echo "❌ /automation-update は下流チャンネルリポジトリで実行してください"
  echo "現在地: $(pwd)"
  echo "理由: このフォルダは youtube-channels-automation を依存として参照するチャンネルリポジトリではありません"
  echo
  echo "移動先候補:"

  found=0
  seen_repo_dirs="
"
  for root in "$HOME/02-yt" "$HOME/01-yt" "$HOME"; do
    [ -d "$root" ] || continue
    while IFS= read -r pyproject; do
      [ -f "$pyproject" ] || continue
      repo_dir=$(dirname "$pyproject")
      if is_channel_automation_dependency_pyproject "$pyproject"; then
        case "$seen_repo_dirs" in
          *"
$repo_dir
"*) continue ;;
        esac
        seen_repo_dirs="${seen_repo_dirs}${repo_dir}
"
        printf '  cd -- %q\n' "$repo_dir"
        found=1
      fi
    done < <(find "$root" -maxdepth 4 -type f -name pyproject.toml -not -path '*/.venv/*' -not -path '*/.git/*' 2>/dev/null | head -50)
  done

  if [ "$found" -eq 0 ]; then
    echo "  自動検出できませんでした。以下でチャンネルリポジトリを探してください:"
    echo "  find \"$HOME\" -maxdepth 4 -type f -name pyproject.toml -not -path '*/.venv/*' -not -path '*/.git/*' -print"
    echo "  各 pyproject.toml の [project].dependencies に package name が youtube-channels-automation の依存があるものを選んでください。"
    echo "  [project].name が youtube-channels-automation の upstream 本体は除外してください。"
    echo "  見つかった pyproject.toml のあるフォルダへ cd してから /automation-update を再実行してください。"
  fi
  echo "チャンネルリポジトリ側へ cd してから /automation-update を再実行してください。"
}

# 自リポ name が youtube-channels-automation 自身なら upstream リポ → このスキルは下流リポ専用なので終了
if grep -qE '^\s*name\s*=\s*"youtube-channels-automation"' pyproject.toml 2>/dev/null; then
  echo "このスキルは下流リポ専用です（upstream リポ自身では発動しません）"
  print_channel_repo_guidance
  exit 0
fi

# 依存として参照していなければチャンネルリポジトリ外とみなし、正しい実行場所を案内して終了
if [ ! -f pyproject.toml ] || ! is_channel_automation_dependency_pyproject pyproject.toml; then
  print_channel_repo_guidance
  exit 1
fi

# 必須コマンドが揃っているか
uv --version                    # uv 未インストールなら /setup 完了を依頼
command -v git >/dev/null || { echo "❌ git が必要"; exit 1; }

if command -v gh >/dev/null 2>&1; then
  export YT_AUTOMATION_GITHUB_MODE=gh
  gh auth status 2>&1 | head -3  # gh 未認証なら [HUMAN STEP] で `gh auth login` を依頼
else
  command -v curl >/dev/null || { echo "❌ gh CLI が無い環境では curl が必要"; exit 1; }
  export YT_AUTOMATION_GITHUB_MODE=curl
  echo "ℹ gh CLI が未インストールのため curl で GitHub API を直接呼び出します"
fi

# 作業ツリーが clean か
git status --porcelain
```

`YT_AUTOMATION_GITHUB_MODE=gh` かつ `gh auth status` が green でない場合:

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
> /channel-new 直後の初回保存が未完了なら、まず初回 commit を作成してください。
> それ以外の差分は stash / commit / 破棄 のいずれかで clean にしてから "done" と返してください。
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
if [ "${YT_AUTOMATION_GITHUB_MODE:-gh}" = "gh" ]; then
  gh release list --repo daiki-beppu/youtube-automation --limit 50 --json tagName,publishedAt,isLatest
else
  curl -fsSL https://api.github.com/repos/daiki-beppu/youtube-automation/releases/latest \
    > /tmp/youtube-automation-latest-release.json
  python3 - <<'PY'
import json
from pathlib import Path

release = json.loads(Path("/tmp/youtube-automation-latest-release.json").read_text())
print(json.dumps([{
    "tagName": release["tag_name"],
    "publishedAt": release.get("published_at"),
    "isLatest": True,
}], ensure_ascii=False))
PY
fi
```

`isLatest=true` の `tagName` を **`<target>` 変数** とする。current が結果に含まれないほど離れている場合は `gh` ルートでは `gh api repos/daiki-beppu/youtube-automation/releases --paginate`、curl ルートでは `curl -fsSL 'https://api.github.com/repos/daiki-beppu/youtube-automation/releases?per_page=100'` でフル取得する。

### Step 1-4. 差分判定と利用者への提示

- tag pin で現在の tag と target version が一致 → 「✓ 既に最新です（`v<X.Y.Z>`）」で終了
- main 追従の場合は uv.lock の `youtube-channels-automation` 行から現在解決 sha を取得し、upstream の `main` HEAD と比較（`gh` ルートは `gh api repos/daiki-beppu/youtube-automation/commits/main --jq .sha`、curl ルートは `curl -fsSL https://api.github.com/repos/daiki-beppu/youtube-automation/commits/main` を Python で読んで `.sha` を抽出）。一致なら「✓ 既に最新です」で終了
- sha pin の場合は常に `[HUMAN STEP]` で「target sha を `v<X.Y.Z>` に揃えるか、HEAD を取るか」を確認

利用者に提示する情報（例: tag pin で v5.5.0 → v5.5.1）:

```
現状: tag pin (v5.5.0)
更新先: v5.5.1 (publishedAt: 2026-05-12)

Phase 2 に進んで Release 本文と CHANGELOG を取得し、変更内容を要約します。
```

## Phase 2: リリース本文読み込みと要約

入力源は `gh release view --json body`（第 1 経路、`gh` 未インストール時は `curl`）と `CHANGELOG.md` の該当バージョンセクション（第 2 経路 / fallback）。フォーマット契約は upstream の `docs/changelog-contract.md` を参照。

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
   - `local fix 衝突注意:` 配下の skill リストを `<conflicts>` 変数に保持して Phase 3-3 の検出対象として使う
4. **中間バージョン累積版の場合**: 跨ぐ各バージョンの「重大変更 Top 1〜2」と各 Migration の `所要時間` / `local fix 衝突注意` を箇条書きで併記

**Migration セクションが欠落しているリリース**（古いフォーマット・Release 本文に `--generate-notes` の PR list のみ等）の場合は fallback として CHANGELOG / Release 本文全体を AI に渡して累積要約を生成する。`所要時間` / `local fix 衝突注意` が抽出できなかった旨を明示し、Phase 3-3 で `[HUMAN STEP]` で利用者に skill 一覧を確認してもらう。

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

失敗時は cache を破棄してリトライ:

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

#### 自スキル (automation-update) が差分対象に含まれる特例

`yt-skills diff` の出力に **`automation-update` 自身** が含まれる場合、上記 (a)/(b)/(c) prompt の **前に** 自スキル更新の特例 prompt を出して、変更内容を構造的に提示してから確認を取る:

```bash
# 自スキル分の差分だけを取り出して unified diff として表示
diff -u .claude/skills/automation-update/SKILL.md <(uv run yt-skills export automation-update 2>/dev/null) \
  || true   # yt-skills に export がなければ次の手で
```

`yt-skills` に直接 export コマンドが無い場合は、wheel 内の `_skills/automation-update/SKILL.md` を `python -c "from importlib.resources import files; print(files('youtube_automation._skills.automation-update').joinpath('SKILL.md').read_text())"` で取得して `diff -u` する。

AI は取得した unified diff を **H2 セクション境界（`## `）で集約** し、「Phase X の手順が変わる」「Gotchas に Y が追加」のようなセクション単位の要約を作って提示する:

```
> [HUMAN STEP]
> ⚠ このスキル自身 (automation-update) が更新対象に含まれています。
>
> 変更内容（セクション単位の要約）:
>   - Phase 3-3: <要約>
>   - Step 3-5: <要約>
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

`"manual"` が返ってきた場合は、Step 3-4 の (b) `--only` で `automation-update` を除外して他スキルだけ sync し、自スキルは利用者に手動マージを依頼する。

#### `config.default.yaml` の直接編集が検出された場合の特例

`yt-skills diff` の出力に **`.claude/skills/<skill>/config.default.yaml`** が含まれる場合、それは運営者が直接編集してしまっている可能性が高い。`config.default.yaml` は upstream 管理のデフォルト設定で、運営者のカスタム値は **`config/skills/<skill>.yaml`** に置く運用が正しい（deep-merge される）。直接編集を維持して `--force` で上書きすると変更が失われる。

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
5. その後 `--force` で `.claude/skills/<skill>/config.default.yaml` を upstream 版に戻す
6. Step 3-4 へ進む

`(b)` が選ばれた場合は通常の (a)/(b)/(c) 分岐へ進む（今回は直接編集を維持し、Step 3-4 で `--only` 除外または `--force` 維持を選ばせる）。

### Step 3-4. skills を同期

選択に応じて以下を実行:

- (a) 上書き: `uv run yt-skills sync --force`
- (b) 個別同期: `uv run yt-skills sync --only <skill1> <skill2> ...`（衝突 skill を除いたリストを利用者と確認、引数は **空白区切り**）
- 差分なし: `uv run yt-skills sync`

`--prune`（target 側にのみ存在する旧 skill ディレクトリの削除）は **利用者が明示同意した場合のみ** 付ける。`--prune` 単独では列挙のみで実削除されないため、削除する場合は `--prune --yes` を併用する必要がある（例: `uv run yt-skills sync --prune --yes`）。デフォルトでは付けない。

### Step 3-5. 動作確認

最低限の health check を順に実行:

```bash
uv run yt-config-migrate verify
uv run yt-channel-status
uv run yt-doctor
uv run yt-skills list
```

`command not found` / `No module named` が出た場合は **追従内容が原因と判断せず**、env 側の問題として以下を案内:

```bash
uv sync
uv pip list | grep youtube-channels-automation
# それでもダメなら
uv cache clean
uv lock --upgrade-package youtube-channels-automation
uv sync
```

`yt-doctor` で WARNING / FAILED が出た場合は `/setup` を起動して再診断するよう案内。

#### 自スキルの frontmatter 健全性チェック

`yt-skills sync` で `.claude/skills/automation-update/SKILL.md` 自身が上書きされた場合、新版の frontmatter が壊れていると **次回起動でスキル発動できなくなる**（YAML パース失敗）。sync 直後に必ず確認:

```bash
head -5 .claude/skills/automation-update/SKILL.md
```

期待形式:

```
---
name: automation-update
description: Use when ...
---
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

- **Release 本文 / CHANGELOG セクションが空**: 古いリリースで `--generate-notes` の PR list のみが残っているケースや、CHANGELOG への昇格が漏れているケース。Step 2-1 で両経路ともに空になった場合は `[HUMAN STEP]` で利用者に手動確認を依頼
- **`### Migration` セクション欠落**: フォーマット契約は v5.6.0 以降で強制されるため、それ以前のリリース本文には Migration セクションが無いケースがある。Step 2-3 の fallback で CHANGELOG / Release 本文全体を AI 累積要約する。`所要時間` / `local fix 衝突注意` が抽出できないため Phase 3-3 で必ず `[HUMAN STEP]` で確認
- **`uv.lock` 添付忘れ**: `git add` で uv.lock を含めないと追従が永続化されない。Phase 4-1 で `git status` を必ず確認
- **同一 tag の再発行**: 稀に upstream が同 tag を force push し直す。`publishedAt` の差分や `gh release view v<target>` で差分有無を確認して人間に判断を仰ぐ
- **自スキルの self-overwrite**: 本スキル自身が `yt-skills diff` の差分対象に含まれる場合がある（v5.5.x → v5.5.y で本スキルが更新された等）。`yt-skills sync` は file 単位の順次上書き（atomicity なし、`--force` で削除→再作成）だが、Claude Code は SKILL.md をセッション開始時にメモリへロードするため、**同セッションでは旧版の手順で完走**し、**次回 /automation-update 起動以降で新版が適用**される。Step 3-3 の特例 prompt で利用者に明示すること。手書き改造（local fix）を残したい場合は `"manual"` 応答で自スキルだけ sync から除外し手動マージへ
- **sync 中の部分破損**: `yt-skills sync` のループに atomicity はない。途中失敗すると部分的に壊れた `.claude/skills/` が残る。Step 3-5 で自スキル frontmatter 健全性チェックを必ず実行し、壊れていれば `git checkout` でロールバック
- **sync が触る範囲**: `yt-skills sync` の default (`--asset all`) は `.claude/skills/`、`.claude/CLAUDE.md`、`docs/{workflow-cheatsheet,features}.md`、`auth/client_secrets.template.json` を同期する。`auth/client_secrets.template.json` はテンプレートだけで、実 secret の `auth/client_secrets.json` / `auth/token*.json`、`config/channel/*.json`、`.env`、`collections/` は **絶対に上書きされない**。`pyproject.toml` と `uv.lock` は Phase 3-1 / 3-2 で本スキルが明示的に書き換える
- **skill 配下の `config.default.yaml` は上書き対象**: 各スキル (`lyria` / `suno` / `masterup` 等) の `.claude/skills/<skill>/config.default.yaml` は upstream 管理のデフォルト設定なので `yt-skills sync` で確実に上書きされる。運営者のカスタム値は別ファイル `config/skills/<skill>.yaml`（チャンネルリポジトリ直下）に置く運用で、こちらは sync 対象外。`config.default.yaml` を直接編集している場合は `yt-skills diff` に local fix として現れるので Step 3-3 で検出される

## Rules

- 人間が答えるべきステップ（上書き判断 / push 判断 / sha pin の bump 先 / `--prune` 付与）を AI が勝手に決めない
- `--force` / `--prune` 系の破壊的操作は必ず `[HUMAN STEP]` の同意を経る
- Step 2-3 の抽出セクション境界（`### Added` / `### Changed` / `### Fixed` / `### Migration`）と Migration セクション必須要素（`所要時間の目安` / `local fix 衝突注意`）は upstream の `docs/changelog-contract.md` との **インターフェース契約**。upstream 側の契約が変わったら Phase 2-3 も同期更新する

## Cross References

- `docs/changelog-contract.md`（upstream リポ）— CHANGELOG.md / Release 本文の Migration セクションフォーマット契約（本スキルの入力構造定義）
- `/automation-release`（upstream リポ）— リリース PR を作成し CHANGELOG.md を昇格させる upstream 側スキル（本スキルが読み取るリリース本文を生成する）
- `/setup` — 追従後に `yt-doctor` で WARNING / FAILED が出た場合の再診断入口、および `[HUMAN STEP]` の書き方の参考実装
- `commit-convention` — Phase 4 のコミットメッセージ規約
