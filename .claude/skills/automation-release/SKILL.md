---
name: automation-release
description: "Use when 本リポジトリの新規リリースを作成するとき。「リリースして」「/automation-release」「suno-helper をリリースしたい」「ext-v0.2.2 を出したい」で発動。Python 本体（vX.Y.Z）と Chrome 拡張（ext-vX.Y.Z）を判定し prepare / publish に自動分岐。グローバル /release は使わない。下流追従は /automation-update、拡張のインストールは /ext-install"
---

## Overview

まず依頼内容から **Python 本体 release**（`vX.Y.Z`）と **Chrome 拡張 release**（`ext-vX.Y.Z`）のどちらかを判定し（Phase R）、次にリポジトリ状態で prepare / publish に自動分岐する:

**Python 本体**（`pyproject.toml::version` が対象）:

1. **prepare**: `main` の `[Unreleased]` を吸い上げて `release/vX.Y.Z` ブランチを切り、`pyproject.toml::version` を bump し、`CHANGELOG.md` を昇格し、リリース PR を作成する
2. **publish**: マージ済みリリース PR を tag push + GitHub Release 化し、リリースブランチを削除する

**Chrome 拡張**（`extensions/<name>/package.json::version` が対象。対象拡張: suno-helper / distrokid-helper）:

3. **extension prepare**: `release/ext-v<VER>` ブランチで対象拡張の `package.json::version` のみ bump し、`release-extensions.yml` と同一契約の local verify（install / build / zip）を通してリリース PR を作成する
4. **extension publish**: マージ済み PR の merge commit に `ext-v<VER>` tag を push し、Release Extensions workflow の成功と Release asset（`<name>-<VER>-chrome.zip`）を確認する

**責務分離**:
- 本スキル = リリース実施（prepare + publish、Python 本体 / 拡張の両系列）
- 下流追従 = 各チャンネルリポジトリで `/automation-update` スキル（本リポジトリで配布）が CHANGELOG.md / GitHub Release 本文を読み取って実施
- 拡張の配布・インストール側は `/ext-install`（Release asset を読む消費側。tag `ext-v*` / asset `<name>-<version>-chrome.zip` の命名契約を本スキルから変えない）
- グローバル `/release` スキルは廃止済みで存在しない。本リポジトリのリリースは常に本スキルを使う

## 前提

以下を確認し、満たさなければ案内して停止する:

- 実行場所が youtube-automation リポジトリ本体（`pyproject.toml::[project].name` が `youtube-channels-automation`）であること。下流チャンネルリポジトリでの追従は `/automation-update` を使う
- `gh` CLI がインストール済みで認証済み（`gh auth status` が green）であること。未認証なら `gh auth login` を依頼して停止する
- prepare（Python 本体）の場合、`CHANGELOG.md` の `[Unreleased]` セクションに内容が書き溜められていること。空の場合は prepare を中止する（各 PR 時点で書き溜める運用が前提）
- Python 本体のバージョン管理は `pyproject.toml::version` を **唯一のソース** とする（`src/youtube_automation/__init__.py` は `importlib.metadata` 経由で自動追従）。配布は git+https + tag pin（PyPI 公開しない）
- extension release のバージョン管理は `extensions/<name>/package.json::version` を **唯一のソース** とし、Python 本体とは完全独立（`docs/adr/0011-extension-distribution.md`）。extension release では `pyproject.toml` / `uv.lock` / `CHANGELOG.md` 昇格に一切触らない
- extension release の場合、`pnpm` が利用可能であること（`pnpm -v` が 9 系。各拡張の `package.json::packageManager` の pin に従う）。無ければ導入を案内して停止する

## Instructions

**実行場所**: youtube-automation リポジトリのルート（`/Users/mba/02-yt/00-automation`）

### Phase R: リリース種別判定

依頼文から Python 本体 release か extension release かを最初に判定する。**extension release と判定した場合、Python 本体の `pyproject.toml` bump flow（Phase 0〜2）には進まない。**

| 依頼の形 | 種別 | 進み先 |
|---|---|---|
| 拡張名 + バージョン（`suno-helper をリリースしたい v0.2.2` / `distrokid-helper v0.1.1`） | extension | Phase E0 へ |
| `ext-v` プレフィックス（`ext-v0.2.2 を出したい`） | extension | Phase E0 へ |
| 上記以外（`リリースして` / `v5.6.0 を出して` 等、拡張名も `ext-v` も含まない） | Python 本体 | Phase 0 へ |

判定基準: 依頼文に `suno-helper` / `distrokid-helper`（`extensions/` 配下の拡張ディレクトリ名）または `ext-v` が含まれれば extension release。どちらの手掛かりも無ければ Python 本体 release。判定に迷う依頼（拡張名なしで `0.x` 系の版数だけ指定された等）は `AskUserQuestion` で種別を確認してから進む。

### Phase 0: 状態判定（Python 本体）

以下のコマンドでリポジトリ状態を取得し、prepare / publish / no-op を判定する:

```bash
git fetch origin --tags --prune
latest_tag=$(git tag --sort=-v:refname | head -1)
main_sha=$(git rev-parse origin/main)
tag_sha=$(git rev-parse "${latest_tag}^{commit}" 2>/dev/null || echo "")
open_release_branch=$(git ls-remote --heads origin "release/v*" | head -1)
```

判定ルール:

| 状態 | 条件 | フェーズ |
|---|---|---|
| **prepare** | `open_release_branch` 無し かつ `main_sha != tag_sha` かつ publish 条件に該当しない（`main` HEAD が bump コミットでない） | Phase 1 へ |
| **publish** | リモートに `release/v<X.Y.Z>` ブランチ無し かつ `main` に bump コミットが含まれる かつ tag 未作成 | Phase 2 へ |
| **publish (alt)** | リモートに `release/v<X.Y.Z>` ブランチ有り かつ PR が merged 済み | Phase 2 へ（マージ済みブランチが削除前のケース） |
| **no-op** | `main_sha == tag_sha`（既にリリース済み） | 終了 |
| **abort** | open release branch 有りで PR が未マージ | 「リリース PR がまだマージされていません」と案内して終了 |

判定結果をユーザーに伝え、`AskUserQuestion` で進行確認する（誤判定時の脱出口を残す）。

### Phase 1: prepare

#### 1-1. バージョン判定

`CHANGELOG.md::[Unreleased]` の内容を読み、semver bump 種別を提案する:

- `### Removed` 有り、または本文中に `BREAKING` / `破壊的変更` 記述 → **major**
- `### Added` 有り → **minor**
- `### Fixed` のみ（または `### Changed` のみで挙動変更が patch レベル）→ **patch**

参照: `references/version-rules.md`

`AskUserQuestion` で提案版数を表示し、ユーザーが上書き可能にする。

**Unreleased が空の場合は abort**:

```bash
# Unreleased セクション直後から次の ## までを抽出
awk '/^## \[Unreleased\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md
```

出力が実質空（空行のみ）なら「Unreleased に内容がありません。リリースする変更がないようです」と案内して中止。

#### 1-2. release ブランチ作成

```bash
git checkout main
git pull origin main
git checkout -b "release/v${VER}"
```

事前に `git status --porcelain` で working tree がクリーンであることを確認。dirty なら abort。

#### 1-3. pyproject.toml::version の bump

`Edit` ツールで `pyproject.toml` の `version = "X.Y.Z"` 行のみ差し替える。
他のフィールドや CLI 一覧には触らない。

#### 1-4. CHANGELOG.md の昇格

`references/changelog-promotion.md` の 3 段階手順をそのまま実行する。
日付は `date +%Y-%m-%d` で取得して `[VER] - YYYY-MM-DD` のフォーマットに埋める。

**Migration セクション存在チェック**: `[Unreleased]` 配下に `### Migration` セクションが無い場合は warning を出し、`AskUserQuestion` で「Migration セクション無しで続行するか」を確認する。Migration セクションは下流の `/automation-update` が `所要時間の目安` / `local fix 衝突注意` を抽出する契約上の入力源（詳細: `docs/changelog-contract.md`）。

```bash
# Unreleased セクション配下に "### Migration" があるか
awk '/^## \[Unreleased\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md \
  | grep -q '^### Migration' || echo "WARNING: Unreleased に Migration セクションがありません"
```

#### 1-5. uv.lock の同期

`pyproject.toml::version` を bump した後、`uv.lock::youtube-channels-automation.version` が古い値のまま残らないよう **必ず** `uv lock` を実行して lock も同 commit に含める。

```bash
uv lock

# 同期を確認: pyproject.toml と uv.lock の version が一致すること
pyproject_ver=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.+)"/\1/')
lock_ver=$(grep -A1 'name = "youtube-channels-automation"' uv.lock | grep '^version' | head -1 | sed -E 's/version = "(.+)"/\1/')
if [ "${pyproject_ver}" != "${lock_ver}" ]; then
  echo "ERROR: pyproject.toml (${pyproject_ver}) と uv.lock (${lock_ver}) が一致しません"
  exit 1
fi
```

これを省くと、後続の `uv sync` を叩いた別 PR で `uv.lock` の 1 行差分（`version`）が機械的に発生し、無関係な PR に混入する（#515）。`uv` が未導入の環境では `nix develop --command uv lock` または `direnv exec . uv lock` で呼び出す。

#### 1-6. Chrome 拡張の release 前検証

`suno-helper` / `distrokid-helper` は、各 `package.json::packageManager`、コミット済み lockfile、`pnpm-workspace.yaml::allowBuilds` の build-script approval、CI と揃えた **pnpm 11.11.0** で検証する。ambient `pnpm` は使わず、両拡張で frozen install → build → zip を実行する:

```bash
for name in suno-helper distrokid-helper; do
  npx -y pnpm@11.11.0 -C "extensions/${name}" install --frozen-lockfile
  npx -y pnpm@11.11.0 -C "extensions/${name}" build
  npx -y pnpm@11.11.0 -C "extensions/${name}" zip
  version=$(node -p "require('./extensions/${name}/package.json').version")
  test -f "extensions/${name}/.output/${name}-${version}-chrome.zip" || exit 1
done

git diff --exit-code -- extensions/suno-helper/pnpm-lock.yaml extensions/distrokid-helper/pnpm-lock.yaml
```

zip の欠落または lockfile 差分があれば release を中止する。lockfile は検証で更新せず、差分の原因を解消してから pinned コマンドを再実行する。詳細なローカル検証契約は `extensions/README.md::pnpm バージョン契約` を参照する。

#### 1-7. commit

```bash
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore(release): v${VER} リリース PR"
```

commit メッセージは日本語 Conventional Commits 規約（CLAUDE.md「開発ワークフロー」参照）に準拠（`chore(release):` プレフィックス + 日本語）。`uv.lock` を必ず同 commit に含めること（1-5 のドリフト再発防止策）。

#### 1-8. push + PR 作成

```bash
git push -u origin "release/v${VER}"
```

PR 作成は `gh pr create` を直接呼ぶ（リリース PR は機械的な昇格 diff のため self-review 付きの通常 PR フローは不要）。以下は quoted heredoc（`<<'EOF'`）のため本文中の `${VER}` / `$(date +%Y-%m-%d)` はシェル展開されない。実行前に本文のプレースホルダを実値へ置換すること:

```bash
gh pr create --base main --title "chore(release): v${VER}" --body "$(cat <<'EOF'
## Summary

v${VER} のリリース PR。

- `pyproject.toml::version` を v${VER} に bump
- `CHANGELOG.md` の `[Unreleased]` を `[${VER}] - $(date +%Y-%m-%d)` に昇格

## Release notes preview

（CHANGELOG.md の [${VER}] セクションをここに貼り付け）

## Next steps

1. このリリース PR をレビュー → マージ
2. マージ後、`/automation-release` を再実行して publish フェーズに進む（tag + GitHub Release 自動作成）
3. publish 後、各チャンネルリポジトリで `/automation-update` を実行すると CHANGELOG.md / Release 本文を読み取って追従できる
EOF
)"
```

PR 番号を控え、ユーザーに「リリース PR を作成しました。レビュー後にマージ → 再度 `/automation-release` を実行してください」と案内して prepare 終了。

### Phase 2: publish

#### 2-1. 前提検証

```bash
git checkout main
git pull origin main

# pyproject.toml::version を取得
VER=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.+)"/\1/')

# tag が既に存在する場合は fast-fail
if git ls-remote --tags origin "v${VER}" | grep -q "v${VER}"; then
  echo "Tag v${VER} already exists on origin. Aborting."
  exit 1
fi
```

Phase 0 で `git fetch origin --tags --prune` 済みなので再 fetch は省略（Phase 2 のみで呼ばれた場合は別途 fetch する）。`main` の HEAD commit が `chore(release): v<VER>` であることも確認。

#### 2-2. tag push

```bash
git tag "v${VER}"
if ! git push origin "v${VER}"; then
  # 他者が同 tag を先に push した race を救済（fast-fail を抜けた場合）
  echo "Tag push rejected. Likely already exists upstream. Skipping to Release creation."
fi
```

#### 2-3. GitHub Release 作成

```bash
gh release create "v${VER}" --generate-notes --title "v${VER}"
```

`--generate-notes` で PR 一覧が自動生成される。これだけで運用上は問題ない（下流の `/automation-update` 側が CHANGELOG.md fallback で `### Migration` を抽出するため）。

リリース本文の先頭に CHANGELOG.md::[VER] セクションも含めたい場合は publish 後に `gh release edit` で追記する:

```bash
section=$(awk -v ver="${VER}" '
  $0 ~ "^## \\[" ver "\\]" { flag = 1; next }
  /^## \[/                  { flag = 0 }
  flag
' CHANGELOG.md)
auto=$(gh release view "v${VER}" --json body --jq .body)
gh release edit "v${VER}" --notes "${section}

---

${auto}"
```

#### 2-4. リリースブランチのクリーンアップ

```bash
# リモート
git push origin --delete "release/v${VER}" 2>/dev/null || true

# ローカル
git branch -D "release/v${VER}" 2>/dev/null || true
```

PR マージ時に GitHub 側で自動削除されているケースもあるため、エラーは無視。

#### 2-5. 次工程の案内

```
✅ v${VER} のリリースが完了しました。

次の選択肢:
- 各チャンネルリポジトリで `/automation-update` を実行すれば CHANGELOG.md / Release 本文から累積影響を要約して追従可能
```

### Phase E0: 状態判定（extension）

```bash
git fetch origin --tags --prune
latest_ext_tag=$(git tag --list 'ext-v*' --sort=-v:refname | head -1)
open_ext_branch=$(git ls-remote --heads origin "release/ext-v*" | head -1)
```

判定ルール:

| 状態 | 条件 | フェーズ |
|---|---|---|
| **extension prepare** | `open_ext_branch` 無し かつ `ext-v<VER>` tag 未作成 | Phase E1 へ |
| **extension publish** | `release/ext-v<VER>` の PR が merged 済み かつ `ext-v<VER>` tag 未作成 | Phase E2 へ |
| **no-op** | `ext-v<VER>` tag が origin に既に存在 | 終了（Release asset の確認だけなら E2-4 を単独再実行してよい） |
| **abort** | open な `release/ext-v*` ブランチ有りで PR が未マージ | 「拡張リリース PR がまだマージされていません」と案内して終了 |

判定結果をユーザーに伝え、`AskUserQuestion` で進行確認する（誤判定時の脱出口を残す）。

**tag 版数の決定**: `ext-v*` は両拡張共通の単一系列（`docs/adr/0011-extension-distribution.md`）。原則、bump する拡張の新バージョンをそのまま tag 版数に使う。ただし要求版数が `latest_ext_tag` の版数以下になる場合は tag だけ系列の次番号へ進め、`AskUserQuestion` で tag 版数を確認する（前例: `ext-v0.2.3` で distrokid-helper を 0.2.1 に bump）。この場合 Release asset 名は tag 版数ではなく package.json 版数（例: `distrokid-helper-0.2.1-chrome.zip`）になる。

### Phase E1: extension prepare

#### E1-1. release ブランチ作成

```bash
git checkout main
git pull origin main
git status --porcelain   # → 空であること。dirty なら abort
git checkout -b "release/ext-v${VER}"
```

#### E1-2. package.json::version の bump

`Edit` ツールで `extensions/<name>/package.json` の `"version": "X.Y.Z"` 行のみ差し替える。他のフィールド（`packageManager` / dependencies / scripts）、もう一方の拡張、`pyproject.toml` / `uv.lock` / `CHANGELOG.md` には触らない。

#### E1-3. local verify（release-extensions.yml と同一契約）

`.github/workflows/release-extensions.yml` が tag push 時に実行するのと同じコマンド列（pnpm 9 / Node 22 / `--frozen-lockfile --ignore-workspace`）で install / build / zip を通す。拡張は `ni`/`nr` ではなく直接 `pnpm` を使う（`docs/development.md` の extensions 節）:

```bash
cd extensions/<name>
pnpm install --frozen-lockfile --ignore-workspace
pnpm zip    # wxt zip（内部で production build も実行される）
ls .output/<name>-${VER}-chrome.zip   # → 存在すること（無ければ FAIL）
```

`pnpm install --frozen-lockfile` が失敗する場合は `package.json` と `pnpm-lock.yaml` が乖離している（version bump 自体では乖離しない — 依存を触った別変更の混入が原因）。リリースを中断し、lockfile 同期の修正を別 PR で先に main へ入れてから prepare をやり直す。

**差分ガード（PASS/FAIL）**: verify 完了後、version 以外の意図しない差分が無いことを確認する:

```bash
git status --porcelain
# PASS: " M extensions/<name>/package.json" の 1 行のみ
git diff -- "extensions/<name>/package.json"
# PASS: "version" の 1 行差分のみ
```

FAIL（それ以外の差分が出た）場合は **停止**し、原因と復旧手順をユーザーに表示する:

- 典型原因: `--frozen-lockfile` / `--ignore-workspace` を付けずに install した（`pnpm-lock.yaml` の書き換わり・root への lockfile / workspace 設定の混入）、`pnpm add` の誤実行、もう一方の拡張のファイルを誤編集
- 復旧: `git checkout -- <file>` で意図しない差分を破棄 → E1-3 を正しいフラグで再実行。ビルド成果物（`.output/` / `.wxt/` / `node_modules/`）は `.gitignore` 済みのため `git status` に出ない（出た場合は `.gitignore` の破損を疑い停止する）

#### E1-4. commit + push + PR 作成

```bash
git add "extensions/<name>/package.json"
git commit -m "chore(<name>): ext-v${VER}"
git push -u origin "release/ext-v${VER}"
gh pr create --base main --title "chore(<name>): ext-v${VER}" --body "（bump 内容 X.Y.Z → ${VER} と local verify 結果を記載）"
```

PR 本文には bump 内容（旧版数 → `${VER}`）と local verify 結果（zip 生成確認・差分ガード PASS）を記載する。`CHANGELOG.md` の昇格は行わない（`extensions/` は CHANGELOG ゲート対象外。拡張の変更履歴は Release notes が担う）。

「拡張リリース PR を作成しました。CI green を確認してマージ → 再度 `/automation-release` を実行してください」と案内して extension prepare 終了。

### Phase E2: extension publish

#### E2-1. merge 状態の確認（worktree footgun 対応）

リリース PR のマージに `gh pr merge <N> --merge --delete-branch` を使った場合、**worktree 環境では remote merge 成功後の local checkout 後処理（`git checkout main`）が `fatal: 'main' is already used by worktree ...` で失敗し、コマンド全体が non-zero を返す**。これは remote merge の失敗ではない。exit code で成否を判断せず、必ず remote の PR state を確認する:

```bash
gh pr view <N> --json state,mergeCommit,mergedAt
```

- `state == "MERGED"` → remote merge は成功している。`mergeCommit.oid` を控えて E2-2 へ進む（`gh pr merge` を再実行しない）
- `state == "OPEN"` → 本当にマージされていない。失敗理由（CI 未 pass / conflict / レビュー未承認）を確認・解消してから再実行
- local 側の checkout 後処理の失敗は無視してよい（worktree では main を checkout できないのが正常。remote branch 削除だけ E2-5 で補完する）

#### E2-2. merge commit へ tag push

tag は `origin/main` の HEAD ではなく **PR の merge commit** に打つ（マージ後に main が進んでいても正しい commit を指すため）:

```bash
merge_sha=$(gh pr view <N> --json mergeCommit -q .mergeCommit.oid)
git fetch origin --tags

# fast-fail: tag 既存
if git ls-remote --tags origin "ext-v${VER}" | grep -q "ext-v${VER}"; then
  echo "Tag ext-v${VER} already exists on origin. Skipping to E2-3."
else
  git tag "ext-v${VER}" "${merge_sha}"
  git push origin "ext-v${VER}"
fi
```

tag push の実行前に、tag 名・対象 commit SHA・対象拡張と版数を表示し、`AskUserQuestion` で実行 / 中止の 2 択確認を取る（tag push は Release Extensions workflow を起動する外部反映操作。承認されるまで push しない）。

#### E2-3. Release Extensions workflow の成功確認

tag push で `.github/workflows/release-extensions.yml` が起動する。成功するまで監視する:

```bash
run_id=$(gh run list --workflow release-extensions.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "${run_id}" --exit-status
```

失敗した場合は `gh run view "${run_id}" --log-failed` でログを確認する。ビルド失敗なら修正 PR を main にマージ後、tag を打ち直す（`git push origin :refs/tags/ext-v${VER}` で remote tag 削除 → `git tag -d ext-v${VER}` → 新しい merge commit へ再 tag）。

#### E2-4. Release asset の確認

```bash
gh release view "ext-v${VER}" --json assets -q '.assets[].name'
```

`<name>-<VER>-chrome.zip`（bump した拡張の zip）が含まれることを確認する。workflow は両拡張を zip するため、もう一方の拡張の zip も現行版数で添付される（正常。例: `ext-v0.2.4` には `suno-helper-0.2.4-chrome.zip` と `distrokid-helper-0.2.1-chrome.zip` が両方付く）。

#### E2-5. クリーンアップと案内

```bash
git push origin --delete "release/ext-v${VER}" 2>/dev/null || true
git branch -D "release/ext-v${VER}" 2>/dev/null || true
```

```
✅ ext-v${VER} のリリースが完了しました。

Tag: ext-v${VER}（merge commit に push 済み）
GitHub Release: https://github.com/daiki-beppu/youtube-automation/releases/tag/ext-v${VER}
Asset: <name>-<VER>-chrome.zip

次のステップ:
- 利用者への告知はチャットで Release URL を共有（ADR 0011。自動アップデート通知は無し）
- 手元 Chrome の拡張更新は `/ext-install`
```

## Gotchas

- **Unreleased 空での実行**: prepare Phase 1-1 で必ず Unreleased の中身を確認。空のままバージョンだけ上がる事故を防ぐ
- **release ブランチが既に存在**: `git ls-remote --heads origin "release/v${VER}"` で衝突確認。あれば「前回 prepare 後にマージされず残っている」「他者が並行作業中」のいずれかなので、手動確認を促して abort
- **`pyproject.toml::version` と tag の不一致**: publish Phase 2-1 で必ず突き合わせ。prepare をスキップして手で bump した場合の事故を防ぐ
- **`__init__.py` の独立 bump**: バージョンは `importlib.metadata` 経由で `pyproject.toml` を読むので `__init__.py` を編集してはいけない。`grep '__version__' src/youtube_automation/__init__.py` で `importlib.metadata` ベースのままであることを確認
- **main が prepare 中に進む**: 他者が並行で main にマージしてもリリース PR は固定 SHA から枝分かれしているので影響なし。後乗せ機能は次回リリースに自動で乗る。ただし PR mergeable conflict が出たら rebase が必要
- **tag だけ先に push してしまった場合**: GitHub Release 作成（2-3）を再実行すれば idempotent（gh release create が既存 tag を拾う）
- **`--generate-notes` が空**: 前回 tag から PR が無い場合、自動生成本文が空になる。下流の `/automation-update` 側が CHANGELOG.md fallback で抽出するため publish 時点では問題視しない
- **`uv.lock` の version 乖離**: `pyproject.toml` だけ bump して `uv.lock` を同期し忘れると、別 PR で `uv sync` を叩いた瞬間に機械的な 1 行差分が無関係な PR に混入する（#515 の既往）。prepare Phase 1-5 で **必ず** `uv lock` を実行し、bump コミットに `uv.lock` も含めること。`uv` が未導入なら `nix develop --command uv lock` で囲む
- **extension 依頼を Python 本体と誤判定**: 依頼に `suno-helper` / `distrokid-helper` / `ext-v` が含まれるのに Phase 0 に進むと `pyproject.toml` が誤 bump される。Phase R の判定表に従い、迷ったら `AskUserQuestion`
- **`gh pr merge --delete-branch` の non-zero（worktree footgun）**: worktree 環境では remote merge 成功後の local checkout 後処理が `fatal: 'main' is already used by worktree ...` で失敗し non-zero になる。remote merge 失敗と誤認して merge を再実行しない。E2-1 の通り `gh pr view <N> --json state,mergeCommit` で remote state を確認し、`MERGED` なら tag push へ進む
- **`pnpm install --frozen-lockfile` の失敗**: version bump 自体では lockfile は乖離しない。失敗＝依存差分の混入なので、リリースとは切り離して lockfile 同期の修正 PR を先に main へ入れる
- **ext-v tag 系列と package.json 版数の乖離**: `ext-v*` は両拡張共通の単一系列のため、bump 対象の拡張によっては tag 版数と package.json 版数がずれる（前例: `ext-v0.2.3` で distrokid-helper 0.2.1）。Release asset 名は package.json 版数に従う（E0 の「tag 版数の決定」参照）
- **Chrome 拡張の pnpm 版数乖離**: ambient pnpm の版は各環境で異なり得る。prepare Phase 1-6 の pnpm 11.11.0 固定コマンドで両拡張を検証し、期待 zip と lockfile 無差分を確認する

## Rules

- このスキル自体の編集は **takt 経由 NG**（CLAUDE.md 規約: skill 編集は通常の Claude Code 対話セッションで）
- `src/youtube_automation/__init__.py` は **直接編集禁止**（`importlib.metadata` 経由の動的読み込みのため、版数は `pyproject.toml` を bump するだけで追従する）
- リリース PR の commit メッセージは `chore(release): v<VER> リリース PR` 固定（日本語 Conventional Commits 準拠 + 検索容易性）
- `release/v<VER>` ブランチ命名は固定（state detection と publish クリーンアップが依存）
- prepare 1-4 で `Migration` セクション欠落を warning する（下流の `/automation-update` が `所要時間` / `local fix 衝突注意` を抽出する契約上の入力源）
- prepare 1-5 で **必ず** `uv lock` を実行し、`uv.lock` の version を `pyproject.toml::version` と同期させる（#515 再発防止）。bump コミットに `uv.lock` を含めず main にマージするのは禁止
- 状態判定（Phase R / Phase 0 / Phase E0）の結果は `AskUserQuestion` でユーザー確認してから次に進む（誤判定時の脱出口）
- extension release は `extensions/<name>/package.json::version` のみを変更する。`pyproject.toml` / `uv.lock` / `CHANGELOG.md` 昇格には触らない（バージョン系列は完全独立、ADR 0011）
- `release/ext-v<VER>` ブランチ命名は固定（Phase E0 の状態判定と E2-5 のクリーンアップが依存）
- extension の commit / PR タイトルは `chore(<name>): ext-v<VER>` 固定（日本語 Conventional Commits 準拠 + 検索容易性）
- extension の local verify は `.github/workflows/release-extensions.yml` と同じコマンド列（`pnpm install --frozen-lockfile --ignore-workspace` → `pnpm zip`）で行う。契約を変える場合は workflow 側と同時に更新する
- `ext-v<VER>` tag は PR の merge commit（`gh pr view <N> --json mergeCommit`）に打つ。tag `ext-v*` / asset `<name>-<version>-chrome.zip` の命名契約は `/ext-install` が読む側で依存しているため変えない
- prepare 1-6 で **必ず** pnpm 11.11.0 を使って両 Chrome 拡張の frozen install / build / zip を実行し、期待 zip の存在と両 `pnpm-lock.yaml` の無差分を確認する

## Cross References

- `references/prepare-checklist.md` — prepare 実行前のチェックリストとエッジケース
- `references/publish-checklist.md` — publish 実行前のチェックリストとエッジケース
- `references/extension-release-checklist.md` — extension prepare / publish 実行前のチェックリストとエッジケース
- `references/version-rules.md` — semver bump 判定ルール
- `references/changelog-promotion.md` — CHANGELOG.md 昇格手順
- `.github/workflows/release-extensions.yml` — extension の install / build / zip 契約（local verify はこれと同一コマンド列で実行する）
- `docs/adr/0011-extension-distribution.md` — 拡張の配布形態 / 統一 tag `ext-v*` / バージョン独立の決定
- `extensions/README.md` — 拡張の開発フローと release 添付方針
- `docs/changelog-contract.md` — CHANGELOG.md / Release 本文の Migration セクションフォーマット契約（下流 `/automation-update` との接合点）
- `/automation-update`（下流チャンネルリポジトリ）— publish 後の追従スキル
- `/ext-install` — Release asset を読む消費側スキル（tag / asset 命名契約の依存先）
- CLAUDE.md「開発ワークフロー」— commit メッセージ規約（日本語 Conventional Commits）
