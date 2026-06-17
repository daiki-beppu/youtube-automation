# publish チェックリスト

`/automation-release` の publish フェーズ実行前の前提条件とエッジケース対応。

---

## 実行前の前提（必須）

### 1. リリース PR がマージ済み

```bash
gh pr list --state merged --search "chore(release): v${VER}" --json number,mergedAt,headRefName,mergeCommit
```

該当 PR が無ければ:
- まだマージされていない → 「リリース PR がまだマージされていません。先にレビュー→マージしてください」と案内して abort
- マージ済みなのに検索ヒットしない → タイトル形式が異なる可能性、ユーザーに PR 番号を尋ねる

### 2. main が PR マージコミットに更新済み

```bash
git fetch origin
main_sha=$(git rev-parse origin/main)
release_pr_merge_sha=$(gh pr list --state merged --search "chore(release): v${VER}" --json mergeCommit --jq '.[0].mergeCommit.oid // ""')
git log origin/main -1 --format="%s"
# → "chore(release): vX.Y.Z" を含む、または main_sha と release_pr_merge_sha が一致
```

ローカル main が古い場合は `git pull origin main` してから進める。

### 3. packages/cli/package.json::version と push する tag が一致

VER 抽出ロジックは `SKILL.md` Phase 2-1 と共通。抽出した `v${VER}` をユーザーに表示して `AskUserQuestion` で確認。誤ったタイミング（merge 前）で実行すると古いバージョンで tag が打たれる事故を防ぐ。

### 4. tag が未作成

```bash
git ls-remote --tags origin "v${VER}" | head -1
# → 何も返らないこと、または main HEAD を指すこと
```

既に存在する場合:
- ローカルだけ → `git tag -d v${VER}` してから push しなおし
- リモートにもあり、main HEAD と異なる commit を指す → 「既存 tag v${VER} が origin/main を指していません」と案内して abort
- リモートにもあり、GitHub Release もあり、`tayk@${VER}` が npm alpha として publish 済み → no-op
- リモートにもあるが GitHub Release が無い → GitHub Release 作成を再実行
- リモートにもあり、GitHub Release もあるが `tayk@${VER}` が npm alpha として未 publish → tag/GitHub Release は再作成せず、npm workflow dispatch へ復帰

```bash
main_sha=$(git rev-parse HEAD)
tag_sha=$(git rev-parse "v${VER}^{commit}" 2>/dev/null || echo "")
if [ "${tag_sha}" != "${main_sha}" ]; then
  echo "ERROR: existing tag v${VER} points to ${tag_sha}, not main HEAD ${main_sha}"
  exit 1
fi
npm view "tayk@${VER}" version
npm view tayk dist-tags.alpha
gh release view "v${VER}"
```

### 5. CHANGELOG.md に v<VER> セクションがある

```bash
grep -q "^## \[${VER}\]" CHANGELOG.md
```

無ければ prepare が不完全。ユーザーに通知して abort。

### 6. bun.lock と package metadata が一致

prepare Phase 1-5 で `bun install --lockfile-only` 同期済みのはずだが、念のため main HEAD で乖離が無いことを確認する。

```bash
package_name=$(bun -e 'console.log(JSON.parse(await Bun.file("package.json").text()).name)')
lock_name=$(grep -A2 '^    "": {' bun.lock | grep '"name":' | head -1 | sed -E 's/.*"name": "([^"]+)".*/\1/')
package_ver=$(bun -e 'console.log(JSON.parse(await Bun.file("packages/cli/package.json").text()).version)')
lock_ver=$(grep -A4 '^    "packages/cli": {' bun.lock | grep '"version":' | head -1 | sed -E 's/.*"version": "([^"]+)".*/\1/')
if [ "${package_name}" != "${lock_name}" ] || [ "${package_ver}" != "${lock_ver}" ]; then
  echo "ERROR: package metadata と bun.lock が一致しません。prepare をやり直すか、lock sync hotfix PR を入れてください"
  exit 1
fi
```

不一致だった場合は publish を続行せず、`bun install --lockfile-only` を当てた hotfix PR を先に main にマージしてから再度 publish を走らせる。

### 7. npm publish workflow を dispatch できる

```bash
gh workflow view npm-publish-alpha.yml
gh secret list | grep -q '^NPM_TOKEN'
```

workflow は `workflow_dispatch` の `version` input を要求し、publish job で `npm publish --provenance --tag alpha` を実行する。`NPM_TOKEN` が無ければ publish は失敗するため、dispatch 前に abort してユーザーへ案内する。

---

## エッジケース

### ケース A: tag は打ったが gh release create で失敗

`gh release create` がネットワークエラー等で失敗するケース。

**対応**: tag は既に push 済みなので、`gh release create v${VER} --generate-notes --title "v${VER}"` を再実行する。GitHub Release が存在するまで npm workflow dispatch へ進まない。

### ケース A-2: tag/GitHub Release はあるが npm workflow が失敗

`npm-publish-alpha.yml` が `NPM_TOKEN` 未設定、provenance 権限不足、version mismatch などで失敗したケース。

**対応**: `npm view "tayk@${VER}" version` と `npm view tayk dist-tags.alpha` で `tayk@${VER}` が alpha publish 済みか確認する。未 publish なら tag/GitHub Release を完了扱いにせず、同じ `version` input で `gh workflow run npm-publish-alpha.yml --ref main -f version="${VER}"` を再実行する。

### ケース B: --generate-notes が空になる

前回 tag から PR が一切無い場合（手動で tag だけ動かしたケース等）に発生。

**対応**: 下流の `/automation-update` 側が CHANGELOG.md fallback で抽出するので publish 時点では問題視しない。本文を手で補完したい場合は `gh release edit` で CHANGELOG.md::[VER] セクションを貼り付ける。

### ケース C: リリースブランチが既に削除されている

GitHub の PR 設定で「マージ後に自動削除」が有効だと、リモートブランチは既に消えている。

**対応**: `git push origin --delete "release/v${VER}"` のエラーは無視（`|| true`）。ローカルブランチだけ削除して終了。

---

## チェックリスト（最終確認用）

publish 完了直後にユーザーへ提示するサマリ:

```
✅ v${VER} リリース完了

Tag: v${VER}（push 済み）
GitHub Release: https://github.com/daiki-beppu/youtube-automation/releases/tag/v${VER}
npm: tayk@${VER}（alpha dist-tag / provenance）
リリースブランチ: release/v${VER}（削除済み）

次のステップ:
- clean な下流リポジトリで `bun add -d tayk@${VER}` 後に `bunx tayk --help` を確認
- 各チャンネルリポジトリで `bunx tayk <cmd>` を使って追従
```
