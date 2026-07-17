# TAKT auto-commit / PR 作成失敗調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象: issue #2009, #2001, #2002, #2003, #2018, #2023, #2037, #2063, #2064, #2019, #1938, #1799
- 対象 TAKT: 0.51.0
- 調査方式: ローカル一次コード、保存済み run、`tasks.yaml`、clone metadata、各 clone の reflog、Git の read-only preflight。対象 worktree に対する `git add` / `git commit` / `git push` は実行していない。
- 主要一次資料:
  - `/Users/mba/02-yt/00-automation/.takt/tasks.yaml`
  - `/Users/mba/.bun/install/global/node_modules/takt/dist/features/tasks/execute/postExecution.js`
  - `/Users/mba/.bun/install/global/node_modules/takt/dist/infra/task/autoCommit.js`
  - `/Users/mba/.bun/install/global/node_modules/takt/dist/infra/task/git.js`
  - `/Users/mba/.bun/install/global/node_modules/takt/dist/core/runtime/runtime-environment.js`
  - `/Users/mba/02-yt/00-automation/.takt/config.yaml`
  - `/Users/mba/02-yt/00-automation/.takt/runtime-prepare.sh`
  - [Git config 2.54.0](https://git-scm.com/docs/git-config/2.54.0.html)
  - [Git commit](https://git-scm.com/docs/git-commit.html)

## 調査項目ごとの結果と詳細

### 1. 12件の failure と直後の Git 状態

`tasks.yaml` では全件が workflow 完了後に同じ post-execution エラーで failed になっている。保存されたエラーは全件とも `Auto-commit failed before PR creation.` だけである。

| Issue | tasks.yaml | failed（JST） | 同一 clone の復旧 commit（JST） | 間隔 | 非空差分の証拠 |
|---|---:|---:|---|---:|---|
| #2009 | 940-958 | 07-14 20:43:28 | `e6016a57` 20:47:31 | 4:03 | 1 file, +11 |
| #2001 | 961-980 | 07-15 03:47:31 | `48827dfa` 03:51:34 | 4:03 | 3 files, +63 |
| #2002 | 983-1001 | 07-15 04:16:32 | `1c236c89` 04:20:31 | 3:59 | 3 files, +66/-16 |
| #2003 | 1004-1022 | 07-15 04:42:31 | `1f57d12e` 04:48:01 | 5:30 | 3 files, +98 |
| #2018 | 1270-1295 | 07-16 22:32:28 | `f9fc6146` 22:34:19 | 1:51 | 最終 main commit は 10 files, +754/-1069 |
| #2023 | 1297-1317 | 07-16 22:57:26 | `c0d69058` 22:58:49 | 1:23 | 最終 main commit は 13 files, +312/-260 |
| #2037 | 1355-1378 | 07-16 22:02:25 | `71fdd1cf` 22:10:38 | 8:13 | 4 files, +67/-5 |
| #2063 | 1405-1422 | 07-17 00:21:35 | `fa0d3562` 00:23:00 | 1:25 | 最終 main commit は 4 files, +42/-13 |
| #2064 | 1425-1442 | 07-17 00:59:50 | `94cb5bf6` 01:08:11 | 8:21 | 最終 main commit は 3 files, +41/-6 |
| #2019 | 1583-1600 | 07-17 02:32:54 | `59dcd817` 02:36:33 | 3:39 | 最終 main commit は 9 files, +123/-1 |
| #1938 | 1659-1677 | 07-17 02:03:14 | `26eae20b` 02:06:49 | 3:35 | 最終 main commit は 9 files, +112/-13 |
| #1799 | 1741-1759 | 07-17 08:18:35 | `8c2151e3` 08:19:40 | 1:05 | 最終 main commit は 14 files, +945/-19 |

各時刻・commit は各 clone の `git reflog --all --date=iso-strict` と `git show --stat` から取得した。復旧 commit の author/committer は `daiki-beppu <beppu.engineer@gmail.com>`、確認できた commit は unsigned である。現在は全 clone が clean だが、これは復旧・push 後の状態であり、失敗時状態の代替証拠にはしていない。

run の一次資料は各 worktree の次のディレクトリにある。

```text
/Users/mba/02-yt/takt-worktrees/20260714T1134-2009-issue-2009-docs-onboarding-ni/.takt/runs/20260714-113420-implement-using-only-the-files-1qt463/
/Users/mba/02-yt/takt-worktrees/20260714T1832-2001-issue-2001-suno-helper-yt-coll/.takt/runs/20260714-183217-implement-using-only-the-files-jxhncl/
/Users/mba/02-yt/takt-worktrees/20260714T1859-2002-issue-2002-suno-helper-server/.takt/runs/20260714-185920-implement-using-only-the-files-ay7lgk/
/Users/mba/02-yt/takt-worktrees/20260714T1929-2003-issue-2003-suno-helper-server/.takt/runs/20260714-192935-implement-using-only-the-files-2nhh0k/
/Users/mba/02-yt/takt-worktrees/20260716T1114-2018-issue-2018-oxlint-1-73-0-no-to/.takt/runs/20260716-132834-implement-using-only-the-files-kjz1qu/
/Users/mba/02-yt/takt-worktrees/20260716T1114-2023-issue-2023-postmortem-skill-wo/.takt/runs/20260716-134041-implement-using-only-the-files-cmf1vd/
/Users/mba/02-yt/takt-worktrees/20260716T1114-2037-issue-2037-upload-preflight-de/.takt/runs/20260716-124625-implement-using-only-the-files-zcoo63/
/Users/mba/02-yt/takt-worktrees/20260716T1445-2063-issue-2063-analytics-wf-new-no/.takt/runs/20260716-144536-implement-using-only-the-files-k2av0d/
/Users/mba/02-yt/takt-worktrees/20260716T1530-2064-issue-2064-analytics-setup-no/.takt/runs/20260716-153039-implement-using-only-the-files-kp4ymg/
/Users/mba/02-yt/takt-worktrees/20260716T1630-2019-issue-2019-oxlint-de-react-hoo/.takt/runs/20260716-163044-implement-using-only-the-files-fzgjpd/
/Users/mba/02-yt/takt-worktrees/20260716T1630-1938-issue-1938-audio-gen-genre-lin/.takt/runs/20260716-163045-implement-using-only-the-files-coqa67/
/Users/mba/02-yt/takt-worktrees/20260716T2002-1799-issue-1799-analytics-yt-analyt/.takt/runs/20260716-200222-implement-using-only-the-files-ra2ipf/
```

### 2. auto-commit / PR 作成の実コマンド経路

`postExecutionFlow()` → `autoCommitAndPush()` → `AutoCommitter.commitAndPush()` → `stageAndCommit()` の順で呼ばれる。TAKT 0.51.0 の実コマンドは次の順序である。

```text
git add -A
git status --porcelain
git commit --no-verify -m "takt: <taskName>"
git rev-parse --short HEAD
git fetch <cloneCwd> HEAD:refs/heads/<branch>   # commit 成功後
git push origin <branch>                         # materialize 成功後
PR 検索・作成                                      # push 成功後
```

根拠:

- `/Users/mba/.bun/install/global/node_modules/takt/dist/infra/task/git.js` の `getSafeGitEnv()` と `stageAndCommit()`
- `/Users/mba/.bun/install/global/node_modules/takt/dist/infra/task/autoCommit.js` の `commitAndPush()`
- `/Users/mba/.bun/install/global/node_modules/takt/dist/features/tasks/execute/postExecution.js` の `postExecutionFlow()`

`allowGitHooks` / `allowGitFilters` は project/global config に未設定なので既定 `false`。この場合 `GIT_CONFIG_*` overlay で `core.hooksPath=/dev/null` を与え、さらに `git commit --no-verify` を使う。[Git 公式文書](https://git-scm.com/docs/git-commit.html)でも `--no-verify` は `pre-commit` と `commit-msg` を bypass するとされる。したがって今回の auto-commit で lefthook の Ruff は起動していない。

空 diff は `stageAndCommit()` が `undefined` を返し、`AutoCommitter` が `success: true, message: "No changes to commit"` を返す。今回の generic failure にはならない。

### 3. Git identity の同条件 read-only preflight

TAKT の `prepareRuntimeEnvironment()` は `XDG_CONFIG_HOME=<clone>/.takt/.runtime/config` を process 環境へ設定する。Git は `$XDG_CONFIG_HOME/git/config` を global config として読むため、通常の `/Users/mba/.config/git/config` にある `user.name` / `user.email` が worker から見えなくなる。Git のファイル探索規則は [Git config FILES](https://git-scm.com/docs/git-config/2.54.0.html) と一致する。

代表 clone の保存済み環境:

```text
$ sed -n '1,80p' /Users/mba/02-yt/takt-worktrees/20260716T1630-1938-issue-1938-audio-gen-genre-lin/.takt/.runtime/env.sh
export XDG_CONFIG_HOME='/Users/mba/02-yt/takt-worktrees/20260716T1630-1938-issue-1938-audio-gen-genre-lin/.takt/.runtime/config'
export XDG_DATA_HOME='/Users/mba/02-yt/takt-worktrees/20260716T1630-1938-issue-1938-audio-gen-genre-lin/.takt/.runtime/data'
export YOUTUBE_AUTOMATION_SKIP_LEFTHOOK='1'
```

対象に書き込まない `git var` の生出力:

```text
$ git var GIT_AUTHOR_IDENT
Author identity unknown

*** Please tell me who you are.

Run

  git config --global user.email "you@example.com"
  git config --global user.name "Your Name"

to set your account's default identity.
Omit --global to set the identity only in this repository.

fatal: unable to auto-detect email address (got 'mba@mba.(none)')
exit=128

$ git var GIT_COMMITTER_IDENT
Committer identity unknown
...
fatal: unable to auto-detect email address (got 'mba@mba.(none)')
exit=128

$ git config --get user.name
exit=1
$ git config --get user.email
exit=1
$ git config --get commit.gpgsign
exit=1
```

runtime XDG を外した対照群では次が見える。

```text
$ env -u XDG_CONFIG_HOME -u XDG_DATA_HOME -u XDG_STATE_HOME -u XDG_CACHE_HOME git config --global --list --show-origin
file:/Users/mba/.config/git/config  gpg.format=openpgp
file:/Users/mba/.config/git/config  gpg.openpgp.program=/nix/store/wid05g78kbzmd74ixjgcky8c1zfxwl0m-gnupg-2.4.9/bin/gpg
file:/Users/mba/.config/git/config  user.email=beppu.engineer@gmail.com
file:/Users/mba/.config/git/config  user.name=daiki-beppu
exit=0
```

12 clone すべてで同じ identity 欠落を再現した。`git commit` 自体はユーザー指示により再実行していない。

### 4. 失敗分類

| 分類 | 判定 | 根拠 |
|---|---|---|
| identity | **最有力・read-only 再現済み** | 12 clone で author/committer ident が exit 128。復旧 commit は identity 付きで直後に成功。 |
| commit command | **失敗点** | `git add -A` 後の `git commit --no-verify` が identity を要求する。実 stderr は未保存。 |
| hook / lefthook | **直接原因から除外** | `core.hooksPath=/dev/null` と `--no-verify`。worker は `YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1`。 |
| lint / test | **直接原因から除外** | run metadata は workflow completed。lint/test の一部環境障害は step 内で分類済みで、postExecution より前。 |
| signing | **直接原因から除外** | runtime 環境で `commit.gpgsign` / signing key は未設定、コマンドに `-S` なし、復旧 commit は unsigned。 |
| empty diff | **除外** | コード上 success 扱い。全12件で直後に非空復旧 commit。 |
| branch | **commit 前には未到達** | branch materialization/push は commit hash 取得後だけ。clone-meta に branch/path は存在。 |
| index lock | **当時は調査不可** | 現在 lock なしだが復旧後状態。失敗時の lock path/process/owner は保存されていない。 |
| 権限 | **当時は調査不可、主因を支持しない** | `git add -A` 後に staged 内容が復旧 commit/stash に残った形跡があるが、当時の syscall/errno は未保存。 |

workflow 内の lint/test と postExecution を混同しないため、各 run の `context/previous_responses/` も照合した。

| Issue | workflow 終了直前の検証証拠 | postExecution との関係 |
|---|---|---|
| #2009 | review approved、`git diff --check` green。対象 pytest は Nix daemon/network によりテスト起動前 exit 2 | 環境制約を review が分類後、postExecution へ進行 |
| #2001 | 187 tests、Ruff green、故障再現 exit 1、supervise approved | workflow completed 後に commit failure |
| #2002 | 1,104 tests、compile/lint green、approved | 同上 |
| #2003 | 1,106 tests、compile/lint green、approved | 同上 |
| #2018 | install/lint/format/contract green。既存 UI build timeout を切分け後 approved | 同上 |
| #2023 | Ruff/format/対象150 tests green。TAKT env 由来 full-suite 22 failures を補正後 approved | 同上 |
| #2037 | Ruff、full pytest 5,244 passed、diff-check green、supervise approved | 同上 |
| #2063 | contract 26 tests green。途中 needs_fix を修正後 final approved | 同上 |
| #2064 | doctor 関連 290 tests、diff-check green、final approved | 同上 |
| #2019 | fixture/共通設定/両 lint/format、Suno 1,155 + DistroKid 258 tests green、approved | 同上 |
| #1938 | 5,347 tests、Ruff/format green、review approved。12 failures は mktemp sandbox 要因を再実行 green | 同上 |
| #1799 | targeted/adjacent 111 tests、Ruff/format/bash/diff green、final approved | 同上 |

したがって一部 run に環境ノイズはあるものの、保存された workflow verdict はいずれも完了/approved 相当で、lint/test の exit が postExecution の `git commit` を落とした証拠はない。

### 5. exit code / stderr の保存状況

`stageAndCommit()` は `execFileSync(..., stdio: 'pipe')` を使うため Node 例外自体には status/stdout/stderr がある。しかし `AutoCommitter` catch は `getErrorMessage(err)` を戻り値の `message` に入れる一方、logger には generic outcome しか保存しない。さらに `postExecutionFlow()` はその `message` を捨てて `Auto-commit failed before PR creation.` だけを task error にする。debug logging も project config で未設定である。

よって保存されているのは次だけで、当時の exact command、exit code、stderr は復元不能である。

```yaml
status: failed
failure:
  error: Auto-commit failed before PR creation.
```

各 `trace.md` / provider JSONL は agent step の終了までで、postExecution は記録範囲外。この欠落のため identity は「再現可能で最有力」だが、historical stderr による断定ではない。

### 6. 対象関数ごとの改善仕様案（実装はしない）

| 対象 | preflight | 構造化エラー | retry | 復旧 | テスト | 受け入れ条件 | rollback |
|---|---|---|---|---|---|---|---|
| `runtime-environment.js::createBaseEnvironment` | XDG 切替後に Git config の探索先を列挙 | `runtime.git_config_isolated` | 設定変更まで不可 | `GIT_CONFIG_GLOBAL` を元の信頼済み global config へ固定、または identity のみ安全に引継ぐ | 元 config が XDG 配下の fixture | worker 内で `git var` が exit 0、秘密設定は複製しない | Git config preservation を無効化する feature flag |
| `clone-exec.js::cloneAndIsolateAbortable` | root repo の effective `user.name/email` と env identity を確認 | `git.identity_missing` | identity 注入後のみ可 | clone-local identity へコピー。値と source scope を記録 | root local/global/env/欠落の4系統 | clone の author/committer ident が一致 | local config entries を除去 |
| `git.js::stageAndCommit` | `rev-parse`, status, author/committer ident, signing config, lock path、hooks/filters effective 値 | `git_stage_failed`, `git_commit_identity`, `git_commit_hook`, `git_commit_signing`, `git_index_lock`, `git_permission` | lock/transient I/O のみ限定。identity/signing/hookは環境修正まで不可 | staging 成功・commit 失敗を明示し index を保持 | fake git で command/status/stdout/stderr 分類 | command/exit/status/sanitized stderr が保存される | 旧 generic result へ戻せる schema version |
| `autoCommit.js::commitAndPush` | `stageAndCommit` preflight result を受領 | `AutoCommitResult.failure` に phase/category/retryable/cause | category policy に従う | commit hash の有無で materialize 可否を決定 | 各 failure category と empty diff | empty diff success、commit failureは詳細保持 | category 利用を止め generic message を表示 |
| `postExecution.js::postExecutionFlow` | commit result の完全性を検証 | task failure に category + detail log path | retryable のみ task retry を提示 | preserved worktree、staged state、復旧コマンドを表示 | message が潰れない契約テスト | tasks.yaml に sanitized cause/exit/log path | UI は generic、内部 schema は保持 |
| `taskExecution.js::executeTaskAndCompleteWithDetails` | postExecution failure を workflow result と分離 | `workflow_status=completed`, `publication_status=failed` | publication のみ再実行可能 | workflow を再走せず commit/push/PR だけ resume | 状態遷移テスト | agent成果と公開失敗を混同しない | 旧 `status: failed` 互換 view |

## 主要な発見のサマリー

1. 12件は別々の lint/test 問題ではなく、同じ TAKT 0.51.0 postExecution 経路で失敗している。
2. 最有力根因は runtime sandbox が `XDG_CONFIG_HOME` を clone-local に変更し、Git identity を隠したこと。12 clone で read-only に exit 128 を再現した。
3. auto-commit は hooks を明示的に無効化するため、lefthook/Ruff は今回の commit failure を起こしていない。
4. 全件で1〜8分後に同じ clone から非空 commit が作られ、empty diff ではない。
5. TAKT は実例外 detail を内部で一度得るが、task error へ渡す前に捨てるため historical exit code/stderr を監査できない。

## 注意点・リスク

- runtime XDG 全体を解除すると、sandbox 隔離・キャッシュ・ツール設定の再現性を壊す。Git identity だけを狭く扱うべき。
- 元 global Git config 全体をコピーすると credential helper、署名鍵、URL rewrite、filter 等を意図せず worker に持ち込む危険がある。
- `git add -A` は preflight より先に実行される現設計なので、commit 失敗後に index が staged のまま残る。復旧説明にはこの状態を含める必要がある。
- identity 欠落を自動 retry しても環境が不変なら同じ失敗を繰り返す。
- task status を generic `failed` にすると workflow 実装失敗と publication failure を区別できない。

## 調査できなかった項目と理由

- 当時の `git commit` の exact exit code / stderr: postExecution が保存していないため。read-only preflight の exit 128 は再現証拠であり historical raw log ではない。
- 当時の index.lock / errno / permission: failure 時点 snapshot がなく、現在は復旧済み。現在状態だけで否定しない。
- 復旧時に identity をどう注入したか: shell history / command transcript が保存されていない。
- destructive な再現: 対象 worktreeで `git add` / `git commit` / `git push` を行うことは禁止されているため未実施。

## 推奨／結論

最優先は TAKT 側で、auto-commit 前に `git var GIT_AUTHOR_IDENT` と `GIT_COMMITTER_IDENT` を実行し、欠落なら staging 前に `git.identity_missing` として fail-fast すること。そのうえで `stageAndCommit()` の command/exit code/sanitized stderr を構造化保存し、`postExecutionFlow()` で generic message に潰さない。identity の供給は XDG 隔離を解除せず、信頼済み root repository の effective identity を clone-local config または限定 env として渡すのが最小リスクである。
