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

---

## エッジケース

### ケース A: tag は打ったが gh release create で失敗

`gh release create` がネットワークエラー等で失敗するケース。

**対応**: tag は既に push 済みなので、`gh release create v${VER} --generate-notes --title "v${VER}"` を再実行すれば OK（idempotent）。

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
リリースブランチ: release/v${VER}（削除済み）

次のステップ:
- 各チャンネルリポジトリで `/automation-update` を実行すれば CHANGELOG.md / Release 本文から累積影響を要約して追従可能
```
