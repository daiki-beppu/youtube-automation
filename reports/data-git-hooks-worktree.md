# Git hooks / lefthook / Nix / worktree 調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象 repository: `/Users/mba/02-yt/00-automation`
- 対象 worktree/clone: issue #2009, #2001, #2002, #2003, #2018, #2023, #2037, #2063, #2064, #2019, #1938, #1799 の保存済み TAKT clone
- バージョン: Git 2.54.0 / Nix 2.33.3 / direnv 2.37.1 / lefthook 2.1.1 / TAKT 0.51.0
- 調査方式: 設定・script・tests・wrapper の読み取りと、非破壊の `check-install` / skip branch / Git preflight。hook の再インストールは行っていない。
- 外部一次資料:
  - [Lefthook install](https://lefthook.dev/usage/commands/install/)
  - [Lefthook check-install](https://lefthook.dev/usage/commands/check-install/)
  - [Lefthook usage / `LEFTHOOK=0`](https://lefthook.dev/usage/)
  - [Git hooks](https://git-scm.com/docs/githooks)

## 調査項目ごとの結果と詳細

### 1. 通常 checkout / worktree の導入経路

通常の親 checkout と手動 worktree は次の経路で hooks を導入する。

```text
.envrc: use flake
  または .lefthook/setup-worktree.sh -> direnv allow/exec
                                  -> fallback: nix develop
flake.nix devShell.shellHook
  -> .lefthook/install.sh
  -> lefthook install --force（最大3回、0.2秒間隔）
  -> fail-closed wrapper を Git hooks dir の pre-commit / pre-push に atomic mv
```

一次資料:

- `/Users/mba/02-yt/00-automation/.envrc`
- `/Users/mba/02-yt/00-automation/flake.nix`
- `/Users/mba/02-yt/00-automation/.lefthook/setup-worktree.sh`
- `/Users/mba/02-yt/00-automation/.lefthook/install.sh`
- `/Users/mba/02-yt/00-automation/lefthook.yml`
- `/Users/mba/02-yt/00-automation/docs/development.md:59`
- `/Users/mba/02-yt/00-automation/docs/takt-operations.md:59`
- `/Users/mba/02-yt/00-automation/CLAUDE.md:92`

`flake.nix` は devShell に `lefthook` を含め、Git checkout 内なら `.lefthook/install.sh || exit 1`。`.lefthook/install.sh` は lefthook 不在・install 3回失敗・wrapper 非 executable を exit 1 にする。wrapper は install 時の Nix store binary が消えても PATH の `lefthook` へ fallbackし、それも無ければ exit 1。公式 Lefthook も `lefthook install` が configured hooks を Git hooks directory へ導入すると説明している。

親 checkout の非破壊確認:

```text
$ lefthook check-install
exit=0
```

代表 clone の非破壊確認:

```text
$ lefthook check-install
exit=0
```

これは「現在 wrapper が同期済み」の証拠であり、失敗時に hook が実行された証拠ではない。

### 2. hook の内容

`lefthook.yml` は次を定義する。

- pre-commit: staged Python files へ `uv run ruff check` と `uv run ruff format --check`（parallel）。
- pre-push: `changelog-gate.sh` を唯一の stdin consumer とし、内部から test-diff warning と Any/any gate を連鎖。

Git 公式では `pre-commit` / `commit-msg` は `git commit --no-verify` で bypass できる。TAKT auto-commit はさらに command-scope `core.hooksPath=/dev/null` を設定するため、今回の12件で上記 hook は auto-commit command の failure source ではない。

### 3. sandbox TAKT worker の分岐

project config は全 worker に `.takt/runtime-prepare.sh` を適用する。

```yaml
# /Users/mba/02-yt/00-automation/.takt/config.yaml
runtime:
  prepare:
    - .takt/runtime-prepare.sh
```

TAKT 0.51.0 の `runtime-environment.js::createBaseEnvironment()` は worker ごとに次を設定する。

```text
TMPDIR=<clone>/.takt/.runtime/tmp
XDG_CACHE_HOME=<clone>/.takt/.runtime/cache
XDG_CONFIG_HOME=<clone>/.takt/.runtime/config
XDG_STATE_HOME=<clone>/.takt/.runtime/state
CI=true
```

project の `.takt/runtime-prepare.sh` は追加で次を返す。

```text
$ TAKT_RUNTIME_ROOT=<clone>/.takt/.runtime bash .takt/runtime-prepare.sh
XDG_DATA_HOME=<clone>/.takt/.runtime/data
YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1
exit=0
```

この環境では `flake.nix` shellHook と `.lefthook/install.sh` は明示メッセージ付きで install を skip する。

```text
$ YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1 bash .lefthook/install.sh
info: YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1 のため lefthook install をスキップします。
exit=0
```

したがって「Nix shellHook が各 worktree へ必ず lefthook を導入する」は通常 checkout/worktree では正しいが、sandbox TAKT worker は意図的な例外である。worker 内の CHANGELOG 等は CI に委譲する設計が `docs/development.md:80` に明記される。

### 4. worktree/clone ごとの観測

12件は Git linked worktree ではなく TAKT 管理 clone で、path/branch は `.takt/clone-meta/takt--<issue>--*.json` に保存されている。各 clone の run root は `data-auto-commit.md` に列挙した。

代表 #1938 の保存済み `.takt/.runtime/env.sh` は runtime XDG と skip flag を保持する。clone の `.git/hooks/pre-commit` / `pre-push` は現在 lefthook wrapper だが、現在の復旧作業後状態である。auto-commit の実コードは wrapper の有無と無関係に hooksPath を `/dev/null` へ上書きする。

現在の全12 clone:

- clean (`git status --porcelain=v2 --branch`)
- #2009/#2001/#2002/#2003/#2037/#2064/#2019/#1938/#1799 は task branch と origin が +0/-0
- #2018/#2023/#2063 は main clean、local task branch は削除済み、origin task ref は存在

これらは復旧・push・main追従後の snapshot であり、index の staged/unstaged/untracked だけを成果物欠落や未完了の証拠にはしていない。成果物は後続 commit と main squash commit の参照関係で確認した。`reports/` は root `.gitignore` に該当せず、`.takt/.gitignore` の対象外でもある。

保存先の確認結果:

```text
$ git check-ignore -v reports/data-auto-commit.md reports/data-git-hooks-worktree.md
exit=1  # 該当 ignore rule なし
```

### 5. safe preflight と分類

対象 clone への書込みを行わない preflight 結果:

```text
$ git rev-parse --is-inside-work-tree
true
exit=0

$ git status --porcelain=v2 --branch
# branch.oid <recovered-tip>
# branch.head <task-branch-or-main>
# branch.upstream <origin/...>
# branch.ab +0 -0
exit=0

$ git var GIT_AUTHOR_IDENT
Author identity unknown
...
fatal: unable to auto-detect email address (got 'mba@mba.(none)')
exit=128

$ git config --get commit.gpgsign
exit=1

$ test -e <absolute-git-dir>/index.lock
exit=1  # 現在 lock なし
```

この調査 sandbox から clone 外部の index は read-only なので現在の `-w` 判定は original worker 権限の代替にならない。失敗時の permission は保存されていない。一方、復旧 reflog/stash/commit は auto-commit 後に成果物が残っていたことを示す。

| failure 候補 | 結論 |
|---|---|
| lefthook wrapper 不在/古い PATH | auto-commit は hooks を bypass するため除外 |
| pre-commit Ruff failure | 同上。agent step 内 lint と postExecution は別 |
| pre-push CHANGELOG/Any gate | commit failure より後で未到達 |
| Nix shellHook install failure | worker は skip branch で exit 0。workflow は completed |
| Git identity | runtime XDG により12 cloneで exit 128を再現。最有力 |
| signing/GPG | runtime で gpgsign unset、`-S` なし。除外 |
| index lock/permission | historical evidence 不足。現在状態だけで否定しない |

### 6. 既存テスト契約

`/Users/mba/02-yt/00-automation/tests/test_lefthook_installation_contract.py` は少なくとも次を固定している。

- shellHook が install failure を隠さない。
- skip env がある場合だけ明示的に no-op。
- `runtime-prepare.sh` が XDG_DATA_HOME と skip flag を出す。
- `lefthook install --force` を呼ぶ。
- transient install failure を3回まで retryする。
- linked worktree でも hook path を解決する。
- stale lefthook binary の wrapper は fail-closed。
- `setup-worktree.sh` が direnv failure から Nix へ fallbackする。

不足している契約は、TAKT core が自動設定する `XDG_CONFIG_HOME` と Git identity の相互作用、および auto-commit が hooks を bypassする project policyとの統合である。

### 7. 対象ファイル／関数ごとの改善仕様案（実装はしない）

| 対象 | preflight | 構造化エラー | retry | 復旧 | テスト | 受け入れ条件 | rollback |
|---|---|---|---|---|---|---|---|
| `.takt/runtime-prepare.sh` | `TAKT_RUNTIME_ROOT` と Git identity source を表示（値は必要最小限） | `runtime.git_identity_unavailable` | config変更まで不可 | 信頼済み identity の限定継承を core に要求 | output contract test | XDG isolation維持 + `git var` exit 0 | identity bridge flagをoff |
| `runtime-environment.js::createBaseEnvironment` | XDG切替前後の Git config path | `runtime.xdg_git_config_shadowed` | 不可 | `GIT_CONFIG_GLOBAL` の限定 preservation または explicit identity env | XDG fixture、HOME fallback | gh/glab/cursor同様にGitの必要設定も保存 | preservation対象からGitを外す |
| `.lefthook/setup-worktree.sh` | checkout root、direnv/nix可用性、skip env | `worktree.setup_direnv`, `worktree.setup_nix` | direnv失敗→nixは可 | 診断commandを表示 | fake direnv/nix | 正常worktreeはwrapper同期、sandboxは明示skip | 現fallbackへ戻す |
| `.lefthook/install.sh::run_lefthook_install` | git dir/hooks pathのabsolute pathとtype | `hook.binary_missing`, `hook.install_failed`, `hook.path_invalid` | install transientのみ3回 | atomic wrapper維持 | permission/path/binary fixture | failureはexit nonzero、stderr明示 | 旧wrapperをbackupから復元 |
| `flake.nix::shellHook` | `git rev-parse` と skip reason | `devshell.hook_install_failed` | shell再入場可 | `nix develop --command bash .lefthook/install.sh` | source contract + Nix subprocess | 通常はinstall、skipは明示env時だけ | shellHook変更をrevert |
| `lefthook.yml::pre-commit` | staged Python file list | lefthook native command failure | code修正後 | Ruff commandを個別表示 | staged fixture | Ruff exitをそのままcommitへ返す | hook config revert |
| TAKT `git.js::stageAndCommit` | effective allowGitHooksとhooksPathを記録 | `git.commit_hook` と `git.identity` を分離 | category依存 | hooks disabled時は「not run」と明示 | allow true/false matrix | hookを原因に誤分類しない | generic category互換 |

## 主要な発見のサマリー

1. 通常 checkout/worktree の hook導入は `.envrc` / `setup-worktree.sh` → Nix shellHook → fail-closed install で一貫している。
2. sandbox TAKT worker は共有 hooks dir への書込みを避けるため、意図的に lefthook install を skipする。
3. TAKT auto-commit 自体も `core.hooksPath=/dev/null` + `--no-verify` なので、今回12件の auto-commit failure は hook/lintではない。
4. workerの XDG隔離は Git global identityも隠す。hooks問題を避ける変更が別の commit precondition を壊した形である。
5. 既存テストは lefthook導入/skipを厚く保護するが、Git identity preflightを保護していない。

## 注意点・リスク

- sandbox worker に通常 worktree と同じ hook install を強制すると、共有 hooks dir の権限失敗を再発させる。
- hooks を skipするなら CI gate が必須。auto-commit成功だけを品質合格とみなしてはいけない。
- `LEFTHOOK=0`、`--no-verify`、`core.hooksPath=/dev/null` は別レイヤー。ログではどれが有効だったか明示する必要がある。
- normal worktree と TAKT clone は Git dir構造が異なるため、相対 `.git/hooks` を仮定しない。
- 現在の wrapper同期状態、clean index、lock不在は失敗時の証拠ではない。
- global Git config全体の継承は credential/filter/signing設定の持込みリスクがある。

## 調査できなかった項目と理由

- 失敗時の hook directory mode/owner、index.lock、errno: snapshot/logなし。
- 失敗時に wrapperが存在したか: current wrapperは復旧後に作られた可能性がある。ただし auto-commitはhooksをbypassするため根因判定には影響しない。
- Nix shellHookをskipなしで対象 cloneへ再実行: hook fileを書き換えるため調査方針とユーザー制約により未実施。
- actual commit/push再現: destructive/external state変更を避けるため未実施。

## 推奨／結論

lefthook側を変更して今回の12件を直すべきではない。通常worktreeのfail-closed導入とsandbox workerの明示skipは役割どおり動いている。修正対象はTAKTのruntime/auto-commit境界で、XDG隔離後にGit identityをpreflightし、identityだけを限定的に引継ぎ、hook実行有無を構造化記録すること。受け入れ条件は「通常worktreeでは `lefthook check-install=0`」「sandbox workerでは明示skip」「両方で `git var GIT_AUTHOR_IDENT/GIT_COMMITTER_IDENT=0`」「auto-commit failure時にcommand/exit/sanitized stderrが保存」「CI gate green」の組合せとする。
