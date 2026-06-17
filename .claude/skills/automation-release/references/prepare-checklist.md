# prepare チェックリスト

`/automation-release` の prepare フェーズ実行前の前提条件とエッジケース対応。

---

## 実行前の前提（必須）

以下を全て満たしていること。1 つでも欠ければ abort してユーザーに案内する。

### 1. working tree がクリーン

```bash
git status --porcelain | wc -l
# → 0 であること
```

dirty な場合は `git stash` または別 PR でコミットしてからやり直し。

### 2. main が最新

```bash
git fetch origin
git rev-list --count HEAD..origin/main
# → 0 であること（origin/main より遅れていない）
```

### 3. CHANGELOG.md::[Unreleased] に内容がある

```bash
# Unreleased セクションの本文（次の ## までを抽出して空白行を除去）
awk '/^## \[Unreleased\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md | grep -v '^$' | head -5
```

何も出力されない（実質空）場合は「リリースする変更がない」ので abort。

### 4. CHANGELOG.md::[Unreleased] に `### Migration` セクションがある（warning レベル）

```bash
awk '/^## \[Unreleased\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md \
  | grep -q '^### Migration' \
  || echo "WARNING: Unreleased に Migration セクションがありません"
```

無くても abort はしない。`AskUserQuestion` で「Migration セクション無しで続行するか」を確認する。Migration セクションは下流の `/automation-update` が `所要時間の目安` / `local fix 衝突注意` を抽出する契約上の入力源（詳細: `docs/changelog-contract.md`）。

### 5. 開いている release/* ブランチが無い

```bash
git ls-remote --heads origin "release/v*"
# → 何も返らないこと
```

既に存在する場合は次のいずれか:
- 前回 prepare がマージされず残っている → 手動で確認 → クローズ or 再利用
- 他者が並行作業中 → 衝突するので abort

### 6. CI が green（推奨、必須ではない）

```bash
main_sha=$(git rev-parse origin/main)
gh run list --branch main --commit "${main_sha}" --limit 5 --json status,conclusion,headSha
# → status=completed, conclusion=success
```

main の最新コミットで CI が落ちている場合は警告し、ユーザーに続行可否を確認。

### 7. bun が利用可能（必須）

`packages/cli/package.json::version` の bump 後に `bun install --lockfile-only` を実行して `bun.lock` を同期するため、`bun` が PATH 上にあることを確認する。

```bash
which bun
# → /etc/profiles/... など何らかの path が返ること
```

入っていない場合は `nix develop`（devShell）または `direnv exec . bun install --lockfile-only` 経由で呼び出すか、`bun` をインストールしてから prepare を実行する。`bun.lock` の同期は SKILL.md Phase 1-5 で必須化されている。

---

## エッジケース

### ケース A: Unreleased が複数バージョン累積している

過去リリース時に昇格を忘れた結果、Unreleased に 2 バージョン分が混在しているケース。

**対応**: `./changelog-promotion.md` の「Unreleased 内容が累積している場合の対応」セクション参照。「v<VER> リリースに累積で含まれる」として全体昇格する。

### ケース B: packages/cli/package.json::version が既に bump 済み

ローカルで手で bump して push し忘れたケース、または前回 prepare が中途半端に終わったケース。

**対応**: 現在の `version` 値とユーザーが希望するバージョンを突き合わせ:
- 一致 → bump 不要、CHANGELOG 昇格と PR 作成のみ実施
- 不一致 → どちらが正しいかユーザーに確認

### ケース C: bun.lock が package metadata と既に乖離している

main 時点で既に `package.json::name` と `bun.lock` root workspace name、または `packages/cli/package.json::version` と `bun.lock` CLI workspace version が食い違っているケース。

```bash
package_name=$(bun -e 'console.log(JSON.parse(await Bun.file("package.json").text()).name)')
lock_name=$(grep -A2 '^    "": {' bun.lock | grep '"name":' | head -1 | sed -E 's/.*"name": "([^"]+)".*/\1/')
package_ver=$(bun -e 'console.log(JSON.parse(await Bun.file("packages/cli/package.json").text()).version)')
lock_ver=$(grep -A4 '^    "packages/cli": {' bun.lock | grep '"version":' | head -1 | sed -E 's/.*"version": "([^"]+)".*/\1/')
echo "root=${package_name}/${lock_name} cli=${package_ver}/${lock_ver}"
```

**対応**: prepare の Phase 1-5 で必ず `bun install --lockfile-only` が走るため、リリース PR の bump 結果として同じ commit に lock 同期差分が乗る。事前に hotfix を入れる必要はないが、CHANGELOG に「`bun.lock` を v<VER> に同期」と明示しておくとレビューしやすい。

### ケース D: rebase が必要

```bash
gh pr view --json mergeable
# → "mergeable": "CONFLICTING"
```

リリース PR push 時に main が進んでいると稀に発生（同じ pyproject.toml を別 PR が触った等）。

**対応**: ユーザーに rebase を促す:
```bash
git fetch origin
git rebase origin/main
git push --force-with-lease
```

---

## チェックリスト（最終確認用）

prepare 完了直前にユーザーへ提示するサマリ:

```
✅ リリース PR 作成完了

バージョン: vX.Y.Z (bump 種別: minor / patch / major)
ブランチ: release/vX.Y.Z
PR: https://github.com/daiki-beppu/youtube-automation/pull/NNN

変更内容:
- packages/cli/package.json::version → X.Y.Z
- bun.lock workspace metadata → X.Y.Z（`bun install --lockfile-only` 実行）
- CHANGELOG.md [Unreleased] → [X.Y.Z] - YYYY-MM-DD 昇格

次のステップ:
1. PR をレビュー → マージ
2. マージ後、`/automation-release` を再実行 → publish フェーズ（tag + GitHub Release + npm alpha publish）
3. 各チャンネルリポジトリで `bunx tayk <cmd>` を使って追従
```
