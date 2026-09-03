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

「唯一の1件」判定は今回の run が生成した zip だけを対象にする必要があるため、スクリプトは `pnpm zip` の直前に `.output/*.zip` を削除する（`.output/` は gitignore 済みのビルド成果物で `pnpm zip` が再生成する）。過去 run の zip を残したまま判定すると `expected exactly one zip ... found N` で誤 abort する。

なお exit code をパイプ越しに読まないこと。`bash verify-extensions.sh | tail -60` の `$?` は `tail` の値になり、スクリプトの `exit 1` が 0 に見える。

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

**対応**: partial assets の状態では公開ノート生成へ進まない。SKILL.md E2-4の検証を実行し、zip assetが合計3件かつ3拡張が各1件でなければ失敗させる。tagが正しいmerge commitを指すか（`git rev-parse "ext-v${VER}^{commit}"` と `mergeCommit.oid` の一致）を確認し、workflow の修復・再実行後に E2-4 から再実行する。

### ケース F: Release body が空または取得に失敗

3 zip assets が揃っていても Release body が空なら公開ノート生成へ進まない。`gh release view "ext-v${VER}" --json body --jq .body` の tag・認証・応答を確認し、workflow が生成した Release body を復旧してから E2-5 を retry する。Python 本体の CHANGELOG section で代用しない。

### ケース G: 公開ノート案が非承認 / skip

修正依頼では生成内容を修正して再提示し、承認されるまで commit / push / PR 作成を行わない。非承認 / skip では extension publish は完了扱いとし、同一 tag の Release body、canonical authoring reference、生成 pathを使う手動作成手順を報告する。extension release branch cleanup は必ず続行する。

### ケース H: 既存 extension post-release branch / PR がある

local または remote の既存 extension post-release branch は削除・上書きしない。`gh pr list --state all --head "${EXT_POST_RELEASE_BRANCH}"` で既存 pull request を確認し、存在すれば URL と state を報告して重複作成しない。

PR が無ければ branch の tag、生成 path、commit、diff を照合する。一致時だけ local gates から retry し、不一致なら自動処理を停止する。どちらの場合も extension release branch cleanup は必ず続行する。

### ケース I: local gates / push / PR 作成が失敗

local gates が non-zero なら push せず、失敗した gate と retry 手順を報告する。push / PR 作成失敗時は remote branch と既存 pull request を再確認し、作成済みなら URL を再利用して重複作成しない。未作成なら同じ branch の gates と diff を再確認してから失敗した操作だけ retry する。

---

## チェックリスト（最終確認用）

extension publish 完了直後にユーザーへ提示するサマリ:

```
✅ ext-v${VER} リリース完了

Tag: ext-v${VER}（merge commit に push 済み）
GitHub Release: https://github.com/daiki-beppu/youtube-automation/releases/tag/ext-v${VER}
Asset: <name>-<VER>-chrome.zip（+ 他2拡張の現行版数 zip）
リリースブランチ: release/ext-v${VER}（削除済み）
生成 path: docs/release-notes/ext-v${VER}.md
post-release PR: <URL または skip / retry 状態>
site は PR pending: Cloudflare Pages preview と required checks の確認待ち
merge 後の公開 URL: https://youtube-automation-release-notes.pages.dev/releases/ext-v${VER}/

次のステップ:
- 利用者への告知はチャットで Release URL を共有（ADR 0011。自動アップデート通知は無し）
- 手元 Chrome の拡張更新は `/extension --update`
```
