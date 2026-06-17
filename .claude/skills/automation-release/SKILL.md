---
name: automation-release
description: "Use when youtube-automation リポジトリ本体の新規リリースを作成したいとき。`/automation-release` 1 コマンドで状態判定し、prepare（リリース PR 作成）または publish（tag + GitHub Release + npm alpha publish）に自動分岐する。「リリースして」「リリース作って」「新しいバージョン作って」「v0.1.0-alpha.1 出して」「/automation-release」で発動。グローバル `/release` は本リポジトリでは使わない。"
---

## Overview

リポジトリ状態を判定して以下の 2 フェーズのいずれかに自動分岐する:

1. **prepare**: `main` の `[Unreleased]` を吸い上げて `release/vX.Y.Z` ブランチを切り、`packages/cli/package.json::version` を bump し、`bun.lock` と `CHANGELOG.md` を同期し、リリース PR を作成する
2. **publish**: マージ済みリリース PR を tag push + GitHub Release 化し、`.github/workflows/npm-publish-alpha.yml` を `workflow_dispatch` で実行して npm `alpha` dist-tag へ publish し、リリースブランチを削除する

**前提**:
- バージョン管理は npm publish 対象の `packages/cli/package.json::version` を **唯一のソース** とする
- 配布は npm package `tayk` の alpha dist-tag（`npm publish --provenance --tag alpha`）で行う
- `[Unreleased]` セクションに各 PR 時点で内容を書き溜めている運用が前提（書かれていない場合は prepare を中止）

**責務分離**:
- 本スキル = リリース実施（prepare + publish）
- 下流追従 = 各チャンネルリポジトリで `/automation-update` スキル（本リポジトリで配布）が CHANGELOG.md / GitHub Release 本文を読み取って実施
- グローバル `/release`（`~/.claude/skills/release/`）= Node.js / npm リポジトリ向けで本リポジトリでは使わない

## Instructions

**実行場所**: youtube-automation リポジトリのルート（`/Users/mba/02-yt/automation`）

### Phase 0: 状態判定

以下のコマンドでリポジトリ状態を取得し、prepare / publish / no-op を判定する:

```bash
git fetch origin --tags --prune
VER=$(git show origin/main:packages/cli/package.json | bun -e 'console.log(JSON.parse(await Bun.stdin.text()).version)')
main_sha=$(git rev-parse origin/main)
any_open_release_branch=$(git ls-remote --heads origin "release/v*" | head -1)
open_release_branch_for_ver=$(git ls-remote --heads origin "release/v${VER}" | head -1)
release_pr_merge_sha=$(gh pr list --state merged --search "chore(release): v${VER}" --json mergeCommit --jq '.[0].mergeCommit.oid // ""')
release_pr_merged=false
if [ -n "${release_pr_merge_sha}" ]; then
  release_pr_merged=true
fi
main_head_is_release_commit=false
if git log origin/main -1 --format=%s | grep -q "chore(release): v${VER}"; then
  main_head_is_release_commit=true
elif [ "${release_pr_merge_sha}" = "${main_sha}" ]; then
  main_head_is_release_commit=true
fi
tag_exists_for_ver=false
tag_points_to_main=false
if git ls-remote --tags origin "v${VER}" | grep -q "refs/tags/v${VER}$"; then
  tag_exists_for_ver=true
  tag_sha_for_ver=$(git rev-parse "v${VER}^{commit}" 2>/dev/null || echo "")
  if [ "${tag_sha_for_ver}" = "${main_sha}" ]; then
    tag_points_to_main=true
  fi
fi
github_release_exists=false
if gh release view "v${VER}" >/dev/null 2>&1; then
  github_release_exists=true
fi
npm_version=$(npm view "tayk@${VER}" version 2>/dev/null || echo "")
npm_alpha_version=$(npm view tayk dist-tags.alpha 2>/dev/null || echo "")
npm_alpha_published=false
if [ "${npm_version}" = "${VER}" ] && [ "${npm_alpha_version}" = "${VER}" ]; then
  npm_alpha_published=true
fi
```

判定ルール:

| 状態 | 条件 | フェーズ |
|---|---|---|
| **no-op** | `main_head_is_release_commit == true` かつ `tag_points_to_main == true` かつ `github_release_exists == true` かつ `npm_alpha_published == true`（`tayk@${VER}` が npm alpha として publish 済み） | 終了 |
| **publish resume** | `main_head_is_release_commit == true` かつ `tag_points_to_main == true` かつ `github_release_exists == true` かつ `npm_alpha_published == false` | Phase 2-4 へ（tag/GitHub Release 済み、npm publish 未完了） |
| **publish release resume** | `main_head_is_release_commit == true` かつ `tag_points_to_main == true` かつ `github_release_exists == false` | Phase 2-3 へ（tag 済み、GitHub Release 未作成） |
| **abort** | `main_head_is_release_commit == true` かつ `tag_exists_for_ver == true` かつ `tag_points_to_main == false` | 「既存 tag v${VER} が origin/main を指していません」と案内して終了 |
| **abort** | `release_pr_merged == true` かつ `main_head_is_release_commit == false` かつ `tag_exists_for_ver == false` | 「origin/main が release PR merge commit から進んでいます。publish 対象 commit を確認してください」と案内して終了 |
| **publish** | `main_head_is_release_commit == true` かつ `tag_exists_for_ver == false` かつ `any_open_release_branch` 無し | Phase 2 へ |
| **publish (alt)** | `main_head_is_release_commit == true` かつ `tag_exists_for_ver == false` かつ `open_release_branch_for_ver` 有り かつ `release_pr_merged == true` | Phase 2 へ（マージ済みブランチが削除前のケース） |
| **abort** | `any_open_release_branch` 有り かつ `release_pr_merged == false` | 「リリース PR がまだマージされていません」と案内して終了 |
| **prepare** | `main_head_is_release_commit == false` かつ `any_open_release_branch` 無し | Phase 1 へ |

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

#### 1-3. packages/cli/package.json::version の bump

`Edit` ツールで `packages/cli/package.json` の `"version": "X.Y.Z"` 行のみ差し替える。
同じ release commit に `bun.lock` の workspace metadata も含める。

#### 1-4. CHANGELOG.md の昇格

`references/changelog-promotion.md` の 3 段階手順をそのまま実行する。
日付は `date +%Y-%m-%d` で取得して `[VER] - YYYY-MM-DD` のフォーマットに埋める。

**Migration セクション存在チェック**: `[Unreleased]` 配下に `### Migration` セクションが無い場合は warning を出し、`AskUserQuestion` で「Migration セクション無しで続行するか」を確認する。Migration セクションは下流の `/automation-update` が `所要時間の目安` / `local fix 衝突注意` を抽出する契約上の入力源（詳細: `docs/changelog-contract.md`）。

```bash
# Unreleased セクション配下に "### Migration" があるか
awk '/^## \[Unreleased\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md \
  | grep -q '^### Migration' || echo "WARNING: Unreleased に Migration セクションがありません"
```

#### 1-5. bun.lock の同期

`packages/cli/package.json::version` を bump した後、`bun.lock` の root workspace name と CLI workspace version が古い値のまま残らないよう **必ず** `bun install --lockfile-only` を実行して lock も同 commit に含める。

```bash
bun install --lockfile-only

package_name=$(bun -e 'console.log(JSON.parse(await Bun.file("package.json").text()).name)')
lock_name=$(grep -A2 '^    "": {' bun.lock | grep '"name":' | head -1 | sed -E 's/.*"name": "([^"]+)".*/\1/')
package_ver=$(bun -e 'console.log(JSON.parse(await Bun.file("packages/cli/package.json").text()).version)')
lock_ver=$(grep -A4 '^    "packages/cli": {' bun.lock | grep '"version":' | head -1 | sed -E 's/.*"version": "([^"]+)".*/\1/')
if [ "${package_name}" != "${lock_name}" ] || [ "${package_ver}" != "${lock_ver}" ]; then
  echo "ERROR: package metadata と bun.lock が一致しません"
  exit 1
fi
```

これを省くと、後続の `bun install` を叩いた別 PR で lockfile metadata の機械的差分が無関係な PR に混入する。

#### 1-6. commit

```bash
git add packages/cli/package.json bun.lock CHANGELOG.md
git commit -m "chore(release): v${VER} リリース PR"
```

commit メッセージは `commit-convention` スキルの規約に準拠（`chore(release):` プレフィックス + 日本語）。`bun.lock` を必ず同 commit に含めること（1-5 のドリフト再発防止策）。

#### 1-7. push + PR 作成

```bash
git push -u origin "release/v${VER}"
```

PR 作成は `gh pr create` を直接呼ぶ（`/pr` スキルは self-review を回すため、リリース PR では不要）:

```bash
gh pr create --base main --title "chore(release): v${VER}" --body "$(cat <<'EOF'
## Summary

v${VER} のリリース PR。

- `packages/cli/package.json::version` を v${VER} に bump
- `bun.lock` を npm package metadata と同期
- `CHANGELOG.md` の `[Unreleased]` を `[${VER}] - $(date +%Y-%m-%d)` に昇格

## Release notes preview

（CHANGELOG.md の [${VER}] セクションをここに貼り付け）

## Next steps

1. このリリース PR をレビュー → マージ
2. マージ後、`/automation-release` を再実行して publish フェーズに進む（tag + GitHub Release + npm alpha publish）
3. publish 後、各チャンネルリポジトリで `bunx tayk <cmd>` を使って追従できる
EOF
)"
```

PR 番号を控え、ユーザーに「リリース PR を作成しました。レビュー後にマージ → 再度 `/automation-release` を実行してください」と案内して prepare 終了。

### Phase 2: publish

#### 2-1. 前提検証

```bash
git checkout main
git pull origin main

# packages/cli/package.json::version を取得
VER=$(bun -e 'console.log(JSON.parse(await Bun.file("packages/cli/package.json").text()).version)')
main_sha=$(git rev-parse HEAD)
release_pr_merge_sha=$(gh pr list --state merged --search "chore(release): v${VER}" --json mergeCommit --jq '.[0].mergeCommit.oid // ""')
main_is_release_commit=false
if git log HEAD -1 --format=%s | grep -q "chore(release): v${VER}"; then
  main_is_release_commit=true
elif [ "${release_pr_merge_sha}" = "${main_sha}" ]; then
  main_is_release_commit=true
fi
if [ "${main_is_release_commit}" != "true" ]; then
  echo "ERROR: main HEAD ${main_sha} is not the release commit for v${VER}"
  exit 1
fi

tag_exists=false
if git ls-remote --tags origin "v${VER}" | grep -q "v${VER}"; then
  tag_exists=true
  tag_sha=$(git rev-parse "v${VER}^{commit}" 2>/dev/null || echo "")
  if [ "${tag_sha}" != "${main_sha}" ]; then
    echo "ERROR: existing tag v${VER} points to ${tag_sha}, not main HEAD ${main_sha}"
    exit 1
  fi
fi
github_release_exists=false
if gh release view "v${VER}" >/dev/null 2>&1; then
  github_release_exists=true
fi

npm_version=$(npm view "tayk@${VER}" version 2>/dev/null || echo "")
npm_alpha_version=$(npm view tayk dist-tags.alpha 2>/dev/null || echo "")
if [ "${tag_exists}" = "true" ] && [ "${github_release_exists}" = "true" ] && [ "${npm_version}" = "${VER}" ] && [ "${npm_alpha_version}" = "${VER}" ]; then
  echo "v${VER} and tayk@${VER} alpha are already published. Nothing to do."
  exit 0
fi
```

Phase 0 で `git fetch origin --tags --prune` 済みなので再 fetch は省略（Phase 2 のみで呼ばれた場合は別途 fetch する）。`main` の HEAD commit が `chore(release): v<VER>` または merged release PR の merge commit であることも確認。tag は存在するが GitHub Release 未作成の場合は 2-3 を再実行する。tag と GitHub Release が存在し npm publish のみ未完了の場合だけ、Phase 2-4 の workflow dispatch へ復帰する。

#### 2-2. tag push

```bash
if [ "${tag_exists}" = "true" ]; then
  echo "Tag v${VER} already exists. Skipping tag push."
else
  git tag "v${VER}"
  if ! git push origin "v${VER}"; then
    # 他者が同 tag を先に push した race を救済（fast-fail を抜けた場合）
    echo "Tag push rejected. Likely already exists upstream. Skipping to Release creation."
  fi
fi
```

#### 2-3. GitHub Release 作成

```bash
if gh release view "v${VER}" >/dev/null 2>&1; then
  echo "GitHub Release v${VER} already exists. Skipping release creation."
else
  gh release create "v${VER}" --generate-notes --title "v${VER}"
fi
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

#### 2-4. npm alpha publish workflow dispatch

GitHub Actions の `npm-publish-alpha.yml` を `workflow_dispatch` で起動する。workflow 側で `packages/cli/package.json::version` と input が一致すること、`NPM_TOKEN` が設定されていること、`npm publish --provenance --tag alpha` が通ることを検証する。

```bash
dispatch_start=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
gh workflow run npm-publish-alpha.yml --ref main -f version="${VER}"
run_id=""
for _ in {1..30}; do
  run_id=$(gh run list \
    --workflow npm-publish-alpha.yml \
    --branch main \
    --event workflow_dispatch \
    --limit 20 \
    --json databaseId,createdAt,displayTitle \
    --jq ".[] | select(.createdAt >= \"${dispatch_start}\" and .displayTitle == \"Publish tayk@${VER}\") | .databaseId" \
    | head -1)
  if [ -n "${run_id}" ]; then
    break
  fi
  sleep 5
done
if [ -z "${run_id}" ]; then
  echo "ERROR: Publish tayk@${VER} workflow run was not found after dispatch"
  exit 1
fi
gh run watch "${run_id}" --exit-status
```

失敗した場合は npm publish が完了していないため、workflow log を確認し、同じ `version` input で再実行する。`NPM_TOKEN` 未設定、npm 2FA 設定、version mismatch、provenance 権限不足は publish を続行できない blocking issue として扱う。

#### 2-5. リリースブランチのクリーンアップ

```bash
# リモート
git push origin --delete "release/v${VER}" 2>/dev/null || true

# ローカル
git branch -D "release/v${VER}" 2>/dev/null || true
```

PR マージ時に GitHub 側で自動削除されているケースもあるため、エラーは無視。

#### 2-6. 次工程の案内

```
✅ v${VER} のリリースが完了しました。

次の選択肢:
- clean な下流リポジトリで `bun add -d tayk@${VER}` 後に `bunx tayk --help` が動くことを確認
- 各チャンネルリポジトリで `bunx tayk <cmd>` を使って追従
```

## Gotchas

- **Unreleased 空での実行**: prepare Phase 1-1 で必ず Unreleased の中身を確認。空のままバージョンだけ上がる事故を防ぐ
- **release ブランチが既に存在**: `git ls-remote --heads origin "release/v${VER}"` で衝突確認。あれば「前回 prepare 後にマージされず残っている」「他者が並行作業中」のいずれかなので、手動確認を促して abort
- **`packages/cli/package.json::version` と tag の不一致**: publish Phase 2-1 で必ず突き合わせ。prepare をスキップして手で bump した場合の事故を防ぐ
- **npm workflow の version mismatch**: workflow input と `packages/cli/package.json::version` が一致しない場合は workflow が publish 前に失敗する。input を直して再実行する
- **main が prepare 中に進む**: 他者が並行で main にマージしてもリリース PR は固定 SHA から枝分かれしているので影響なし。後乗せ機能は次回リリースに自動で乗る。ただし PR mergeable conflict が出たら rebase が必要
- **tag だけ先に push してしまった場合**: GitHub Release 作成（2-3）を再実行すれば idempotent（gh release create が既存 tag を拾う）
- **tag だけ先に push して GitHub Release が未作成の場合**: Phase 0 は `github_release_exists` を見て Phase 2-3 から再開する。tag 到達だけで npm workflow dispatch に進まない
- **tag/GitHub Release 後に npm workflow が失敗した場合**: Phase 0 は `tayk@${VER}` の npm alpha publish 状態を見て publish resume と判定する。tag 到達だけで no-op にしない
- **`--generate-notes` が空**: 前回 tag から PR が無い場合、自動生成本文が空になる。下流の `/automation-update` 側が CHANGELOG.md fallback で抽出するため publish 時点では問題視しない
- **`bun.lock` の metadata 乖離**: `packages/cli/package.json` だけ bump して `bun.lock` を同期し忘れると、別 PR で `bun install` を叩いた瞬間に機械的な差分が無関係な PR に混入する。prepare Phase 1-5 で **必ず** `bun install --lockfile-only` を実行し、bump commit に `bun.lock` も含めること

## Rules

- このスキル自体の編集は **takt 経由でも Codex provider が coder の場合は可**（AGENTS.md の skill 編集と takt の関係を参照）
- release version は **`packages/cli/package.json::version` のみ** を publish source とする
- リリース PR の commit メッセージは `chore(release): v<VER> リリース PR` 固定（`commit-convention` 規約準拠 + 検索容易性）
- `release/v<VER>` ブランチ命名は固定（state detection と publish クリーンアップが依存）
- prepare 1-4 で `Migration` セクション欠落を warning する（下流の `/automation-update` が `所要時間` / `local fix 衝突注意` を抽出する契約上の入力源）
- prepare 1-5 で **必ず** `bun install --lockfile-only` を実行し、`bun.lock` を package metadata と同期させる。bump commit に `bun.lock` を含めず main にマージするのは禁止
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
