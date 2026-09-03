# publish チェックリスト

`/automation-release` の publish フェーズ実行前の前提条件とエッジケース対応。

---

## 実行前の前提（必須）

### 1. リリース PR がマージ済み

```bash
gh pr list --state merged --search "chore(release): v${VER}" --json number,mergedAt,headRefName
```

該当 PR が無ければ:
- まだマージされていない → 「リリース PR がまだマージされていません。先にレビュー→マージしてください」と案内して abort
- マージ済みなのに検索ヒットしない → タイトル形式が異なる可能性、ユーザーに PR 番号を尋ねる

### 2. main が PR マージコミットに更新済み

```bash
git fetch origin
git log origin/main -1 --format="%s"
# → "Merge pull request ..." または "chore(release): vX.Y.Z" を含む
```

ローカル main が古い場合は `git pull origin main` してから進める。

### 3. pyproject.toml::version と push する tag が一致

VER 抽出ロジックは `SKILL.md` Phase 2-1 と共通。抽出した `v${VER}` をユーザーに表示して `AskUserQuestion` で確認。誤ったタイミング（merge 前）で実行すると古いバージョンで tag が打たれる事故を防ぐ。

### 4. tag が未作成

```bash
git ls-remote --tags origin "v${VER}" | head -1
# → 何も返らないこと
```

既に存在する場合:
- ローカルだけ → `git tag -d v${VER}` してから push しなおし
- リモートにもある → 既にリリース済みなので no-op（GitHub Release 作成だけ再試行する選択肢を提示）

### 5. CHANGELOG.md に v<VER> セクションがある

```bash
grep -q "^## \[${VER}\]" CHANGELOG.md
```

無ければ prepare が不完全。ユーザーに通知して abort。

### 6. uv.lock と pyproject.toml の version が一致

prepare Phase 1-5 で `uv lock` 同期済みのはずだが、念のため main HEAD で乖離が無いことを確認する（#515 再発防止）。

```bash
pyproject_ver=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.+)"/\1/')
lock_ver=$(grep -A1 'name = "youtube-channels-automation"' uv.lock | grep '^version' | head -1 | sed -E 's/version = "(.+)"/\1/')
if [ "${pyproject_ver}" != "${lock_ver}" ]; then
  echo "ERROR: pyproject.toml (${pyproject_ver}) と uv.lock (${lock_ver}) が一致しません。prepare をやり直すか、`uv lock` を手で当てる hotfix PR を入れてください"
  exit 1
fi
```

不一致だった場合は publish を続行せず、`uv lock` を当てた hotfix PR を先に main にマージしてから再度 publish を走らせる。

---

## post-release note の local gates

承認済みの公開ノート案を post-release branch に載せた後、commit / push 前に次を記載順で実行する。

```bash
nix develop .#extensions --command pnpm -C site install --frozen-lockfile
nix develop .#extensions --command pnpm -C site check
nix develop .#extensions --command pnpm -C site build
nix develop .#extensions --command pnpm -C site test
git diff --check
```

すべて exit 0 の場合だけ commit / push / PR 作成へ進む。失敗時の扱いはケース E に従う。

---

## エッジケース

### ケース A: tag は打ったが gh release create で失敗

`gh release create` がネットワークエラー等で失敗するケース。

**対応**: tag は既に push 済みなので、`gh release create v${VER} --generate-notes --title "v${VER}"` を再実行すれば OK（idempotent）。

### ケース B: --generate-notes が空になる

前回 tag から PR が一切無い場合（手動で tag だけ動かしたケース等）に発生。

**対応**: 下流の `/automation --update` 側が CHANGELOG.md fallback で抽出するので publish 時点では問題視しない。本文を手で補完したい場合は `gh release edit` で CHANGELOG.md::[VER] セクションを貼り付ける。

### ケース C: リリースブランチが既に削除されている

GitHub の PR 設定で「マージ後に自動削除」が有効だと、リモートブランチは既に消えている。

**対応**: `git push origin --delete "release/v${VER}"` のエラーは無視（`|| true`）。ローカルブランチだけ削除して終了。

### ケース D: 公開ノート案が非承認または修正依頼

生成内容を修正して再提示し、対象 tag・post-release branch・変更 path とともに再度承認を得る。承認されるまで git 副作用を起こさない。

非承認 / skip の場合はノートを commit / push せず、GitHub Release publish は完了扱いにする。canonical authoring reference、生成 path、手動作成手順を報告して release branch cleanup は必ず続行する。

### ケース E: local gates が失敗

失敗した check / build / test と診断を表示し、push せず retry 手順を報告する。post-release branch を作成済みでも、失敗を隠して commit・push・PR 作成へ進まない。GitHub Release publish と tag は取り消さず、release branch cleanup は必ず続行する。

### ケース F: 既存 post-release branch / PR がある

local または remote に既存 post-release branch がある場合は削除・上書きしない。`gh pr list --state all --head "${POST_RELEASE_BRANCH}"` で既存 pull request を確認し、存在すれば URL と state を報告して重複作成しない。

PR が無ければ branch の対象 tag、生成 path、commit、diff を照合する。一致が確認できた場合だけ local gates から retry し、不一致なら自動処理を停止して手動 reconciliation を依頼する。どちらの場合も release branch cleanup は必ず続行する。

### ケース G: push または PR 作成が失敗

push 済みかを remote branch で、PR 作成済みかを `gh pr list` で再確認する。既存 pull request があればその URL を再利用して重複作成しない。未作成なら同じ branch の local gates と diff を再確認してから失敗した操作だけ retry する。

---

## チェックリスト（最終確認用）

publish 完了直後にユーザーへ提示するサマリ:

```
✅ v${VER} リリース完了

Tag: v${VER}（push 済み）
GitHub Release: https://github.com/daiki-beppu/youtube-automation/releases/tag/v${VER}
リリースブランチ: release/v${VER}（削除済み）
生成 path: docs/release-notes/v${VER}.md
post-release PR: <URL または skip / retry 状態>
site は PR pending: Cloudflare Pages preview と required checks の確認待ち
merge 後の公開 URL: https://youtube-automation-release-notes.pages.dev/releases/v${VER}/

次のステップ:
- 各チャンネルリポジトリで `/automation --update` を実行すれば CHANGELOG.md / Release 本文から累積影響を要約して追従可能
```
