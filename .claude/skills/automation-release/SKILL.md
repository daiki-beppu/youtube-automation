---
name: automation-release
description: "Use when 本リポジトリの新規リリースを作成するとき。「リリースして」「/automation-release」で発動。prepare / publish に自動分岐。グローバル /release は使わない"
---

## Overview

リポジトリ状態を判定して以下の 2 フェーズのいずれかに自動分岐する:

1. **prepare**: `main` の `[Unreleased]` を吸い上げて `release/vX.Y.Z` ブランチを切り、`pyproject.toml::version` を bump し、`CHANGELOG.md` を昇格し、リリース PR を作成する
2. **publish**: マージ済みリリース PR を tag push + GitHub Release 化し、リリースブランチを削除する

**責務分離**:
- 本スキル = リリース実施（prepare + publish）
- 下流追従 = 各チャンネルリポジトリで `/automation-update` スキル（本リポジトリで配布）が CHANGELOG.md / GitHub Release 本文を読み取って実施
- グローバル `/release`（`~/.claude/skills/release/`）= Node.js / npm リポジトリ向けで本リポジトリでは使わない

## 前提

以下を確認し、満たさなければ案内して停止する:

- 実行場所が youtube-automation リポジトリ本体（`pyproject.toml::[project].name` が `youtube-channels-automation`）であること。下流チャンネルリポジトリでの追従は `/automation-update` を使う
- `gh` CLI がインストール済みで認証済み（`gh auth status` が green）であること。未認証なら `gh auth login` を依頼して停止する
- prepare の場合、`CHANGELOG.md` の `[Unreleased]` セクションに内容が書き溜められていること。空の場合は prepare を中止する（各 PR 時点で書き溜める運用が前提）
- バージョン管理は `pyproject.toml::version` を **唯一のソース** とする（`src/youtube_automation/__init__.py` は `importlib.metadata` 経由で自動追従）。配布は git+https + tag pin（PyPI 公開しない）

## Instructions

**実行場所**: youtube-automation リポジトリのルート（`/Users/mba/02-yt/automation`）

### Phase 0: 状態判定

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
| **prepare** | `open_release_branch` 無し かつ `main_sha != tag_sha` | Phase 1 へ |
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

#### 1-6. commit

```bash
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore(release): v${VER} リリース PR"
```

commit メッセージは `commit-convention` スキルの規約に準拠（`chore(release):` プレフィックス + 日本語）。`uv.lock` を必ず同 commit に含めること（1-5 のドリフト再発防止策）。

#### 1-7. push + PR 作成

```bash
git push -u origin "release/v${VER}"
```

PR 作成は `gh pr create` を直接呼ぶ（`/pr` スキルは self-review を回すため、リリース PR では不要）:

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

## Gotchas

- **Unreleased 空での実行**: prepare Phase 1-1 で必ず Unreleased の中身を確認。空のままバージョンだけ上がる事故を防ぐ
- **release ブランチが既に存在**: `git ls-remote --heads origin "release/v${VER}"` で衝突確認。あれば「前回 prepare 後にマージされず残っている」「他者が並行作業中」のいずれかなので、手動確認を促して abort
- **`pyproject.toml::version` と tag の不一致**: publish Phase 2-1 で必ず突き合わせ。prepare をスキップして手で bump した場合の事故を防ぐ
- **`__init__.py` の独立 bump**: バージョンは `importlib.metadata` 経由で `pyproject.toml` を読むので `__init__.py` を編集してはいけない。`grep '__version__' src/youtube_automation/__init__.py` で `importlib.metadata` ベースのままであることを確認
- **main が prepare 中に進む**: 他者が並行で main にマージしてもリリース PR は固定 SHA から枝分かれしているので影響なし。後乗せ機能は次回リリースに自動で乗る。ただし PR mergeable conflict が出たら rebase が必要
- **tag だけ先に push してしまった場合**: GitHub Release 作成（2-3）を再実行すれば idempotent（gh release create が既存 tag を拾う）
- **`--generate-notes` が空**: 前回 tag から PR が無い場合、自動生成本文が空になる。下流の `/automation-update` 側が CHANGELOG.md fallback で抽出するため publish 時点では問題視しない
- **`uv.lock` の version 乖離**: `pyproject.toml` だけ bump して `uv.lock` を同期し忘れると、別 PR で `uv sync` を叩いた瞬間に機械的な 1 行差分が無関係な PR に混入する（#515 の既往）。prepare Phase 1-5 で **必ず** `uv lock` を実行し、bump コミットに `uv.lock` も含めること。`uv` が未導入なら `nix develop --command uv lock` で囲む

## Rules

- このスキル自体の編集は **takt 経由 NG**（CLAUDE.md 規約: skill 編集は通常の Claude Code 対話セッションで）
- `src/youtube_automation/__init__.py` は **直接編集禁止**（`importlib.metadata` 経由の動的読み込みのため、版数は `pyproject.toml` を bump するだけで追従する）
- リリース PR の commit メッセージは `chore(release): v<VER> リリース PR` 固定（`commit-convention` 規約準拠 + 検索容易性）
- `release/v<VER>` ブランチ命名は固定（state detection と publish クリーンアップが依存）
- prepare 1-4 で `Migration` セクション欠落を warning する（下流の `/automation-update` が `所要時間` / `local fix 衝突注意` を抽出する契約上の入力源）
- prepare 1-5 で **必ず** `uv lock` を実行し、`uv.lock` の version を `pyproject.toml::version` と同期させる（#515 再発防止）。bump コミットに `uv.lock` を含めず main にマージするのは禁止
- 状態判定の結果は `AskUserQuestion` でユーザー確認してから次に進む（誤判定時の脱出口）

## Cross References

- `references/prepare-checklist.md` — prepare 実行前のチェックリストとエッジケース
- `references/publish-checklist.md` — publish 実行前のチェックリストとエッジケース
- `references/version-rules.md` — semver bump 判定ルール
- `references/changelog-promotion.md` — CHANGELOG.md 昇格手順
- `docs/changelog-contract.md` — CHANGELOG.md / Release 本文の Migration セクションフォーマット契約（下流 `/automation-update` との接合点）
- `/automation-update`（下流チャンネルリポジトリ）— publish 後の追従スキル
- `/release` — グローバル Node.js 向け（本リポジトリでは使わない、参考のみ）
- `commit-convention` — commit メッセージ規約
- `/pr` — 通常 PR 作成（リリース PR では使わず、`gh pr create` 直接呼び）
