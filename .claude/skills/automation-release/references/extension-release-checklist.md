# extension release チェックリスト

`/automation-release` の extension prepare / extension publish フェーズ実行前の前提条件とエッジケース対応。手順本体は `SKILL.md` の Phase E0〜E2（本ファイルはロジックを重複させず、前提確認とエッジケースのみ扱う）。

---

## extension prepare 実行前の前提（必須）

### 1. 対象拡張が実在する

```bash
ls extensions/<name>/package.json
# → 存在すること（現行の対象: suno-helper / distrokid-helper / community-helper）
```

依頼された拡張名が `extensions/` 配下に無ければ、拡張名の誤りか未対応拡張。ユーザーに確認して abort。

### 2. working tree がクリーン

```bash
git status --porcelain | wc -l
# → 0 であること
```

### 3. Nix extensions shell が利用可能

release workflow と同じ **Node 24 / pnpm 11.15.1** の Nix extensions shell を使う。ambient `node` / `pnpm` は使わず、`extensions/<name>/pnpm-workspace.yaml::allowBuilds` を有効に保つため `--ignore-workspace` も使わない。

```bash
bash .claude/skills/automation-release/references/verify-extensions.sh <name>
# → exit 0
```

検証ロジックとPASS/FAIL条件は `verify-extensions.sh` が単一ソース。`pnpm install --frozen-lockfile` → `pnpm build` → `pnpm zip`、対象拡張の期待名 zip が唯一の1件であること、対象 lockfile に差分がないことを検証する。non-zeroなら出力された原因を解消するまでabort。

### 4. 開いている release/ext-v* ブランチが無い

```bash
git ls-remote --heads origin "release/ext-v*"
# → 何も返らないこと
```

既に存在する場合は前回 prepare の残骸か並行作業。手動確認を促して abort。

### 5. 要求版数が現行版数より大きい

```bash
grep '"version"' extensions/<name>/package.json
git tag --list 'ext-v*' --sort=-v:refname | head -1
```

- 要求版数 ≤ 現行 package.json 版数 → bump にならないので abort（既にリリース済みの可能性をユーザーに確認）
- 要求版数 ≤ 最新 `ext-v*` tag の版数 → tag は系列の次番号へ進める（SKILL.md Phase E0「tag 版数の決定」）

## extension publish 実行前の前提（必須）

### 6. リリース PR がマージ済み

```bash
gh pr view <N> --json state,mergeCommit,mergedAt
# → state == "MERGED" かつ mergeCommit.oid が取得できること
```

`gh pr merge` の exit code では判定しない（worktree footgun、下記ケース C）。

### 7. ext-v<VER> tag が未作成

```bash
git ls-remote --tags origin "ext-v${VER}" | head -1
# → 何も返らないこと
```

- ローカルだけにある → `git tag -d "ext-v${VER}"` してから打ち直し
- リモートにもある → 既にリリース済み。Release asset の確認（SKILL.md E2-4）だけ再実行する選択肢を提示

---

## エッジケース

### ケース A: pnpm install --frozen-lockfile が失敗する

version bump 自体では `pnpm-lock.yaml` は乖離しない。失敗するのは依存を触った変更が混入している場合。

**対応**: リリースを中断し、lockfile 同期の修正を別 PR で先に main へマージしてから prepare をやり直す。`--no-frozen-lockfile` で握りつぶして続行しない（CI の workflow は `--frozen-lockfile` で走るため、local だけ通っても publish で落ちる）。

### ケース B: verify 後に version 以外の差分が出る

`git status --porcelain` に `extensions/<name>/package.json` 以外の行が出るケース。

**対応**: 停止して原因を特定する。典型は `--frozen-lockfile` を付けない install による `pnpm-lock.yaml` 書き換わり・root への lockfile / workspace 設定の混入、`pnpm add` の誤実行。`--ignore-workspace` は `extensions/<name>/pnpm-workspace.yaml::allowBuilds` を無視して build script を失敗させるため使わない。復旧は `git checkout -- <file>` で差分破棄 → Nix extensions shell で verify 再実行。`.output/` / `.wxt/` / `node_modules/` が `git status` に出る場合は `.gitignore` の破損なので、リリースを中断して先に修正する。

### ケース C: gh pr merge --delete-branch が non-zero を返す（worktree footgun）

worktree 環境では remote merge 成功後の local checkout 後処理（`git checkout main`）が `fatal: 'main' is already used by worktree ...` で失敗し、コマンド全体が non-zero になる。

**対応**: merge を再実行せず `gh pr view <N> --json state,mergeCommit` で remote state を確認する。`MERGED` なら成功しているので `mergeCommit.oid` を使って tag push（SKILL.md E2-2）へ進む。remote branch が残っていれば E2-5 のクリーンアップで削除する。

### ケース D: tag は打ったが workflow が失敗した

**対応**: `gh run view <run_id> --log-failed` で原因を確認。ビルド失敗なら修正 PR を main にマージ後、`git push origin ":refs/tags/ext-v${VER}"` で remote tag を削除 → `git tag -d "ext-v${VER}"` → 新しい merge commit へ再 tag。transient エラー（ネットワーク等）なら `gh run rerun <run_id>` で再実行できる。

### ケース E: Release に一部拡張の zip しか無い / 版数が想定と違う

workflow は tag push 時点の main で **3拡張** を zip して添付する。bump していない拡張はそれぞれの現行版数の zip が付く。

**対応**: SKILL.md E2-4の検証を実行する。zip assetが合計3件かつ3拡張が各1件でなければ失敗。tagが正しいmerge commitを指すか（`git rev-parse "ext-v${VER}^{commit}"` と `mergeCommit.oid` の一致）を確認する。

---

## チェックリスト（最終確認用）

extension publish 完了直後にユーザーへ提示するサマリ:

```
✅ ext-v${VER} リリース完了

Tag: ext-v${VER}（merge commit に push 済み）
GitHub Release: https://github.com/daiki-beppu/youtube-automation/releases/tag/ext-v${VER}
Asset: <name>-<VER>-chrome.zip（+ 他2拡張の現行版数 zip）
リリースブランチ: release/ext-v${VER}（削除済み）

次のステップ:
- 利用者への告知はチャットで Release URL を共有（ADR 0011。自動アップデート通知は無し）
- 手元 Chrome の拡張更新は `/ext-install`
```
