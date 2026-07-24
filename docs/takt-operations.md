# Issue / worktree 運用（takt 廃止後）

> 2026-07-23 以降、このリポジトリでは takt を実装経路に使わない。このファイル名は既存リンクとの互換性のため維持する。

## 正規ルート

1. `gh issue create` または `/issue` で issue を起票する。
2. `/issue-direct <issue番号>`、または同等の手動手順で `main` から issue 専用 linked worktree を作る。
3. worktree 内で実装・検証・commit・push を行い、通常 PR を作成する。
4. required CI が成功し、review 指摘と競合がないことを確認して merge する。

`takt add`、`takt run`、workflow 名による routing は実行しない。`takt:*` ラベルが既存 issue に残っていても履歴メタデータとしてのみ扱い、workflow の選択や実装方式へ使わない。新規 issue へ `takt:*` ラベルを付けない。

## linked worktree

親 checkout は main の同期と worktree 管理に使い、実装は行わない。作業開始時は main を fast-forward してから、issue ごとの branch と worktree を作る。

```bash
git switch main
git pull --ff-only
git worktree add .worktrees/issue-<N>-<slug> -b issue-<N>-<slug> main
cd .worktrees/issue-<N>-<slug>
nix develop
```

base branch は `main` 固定とする。別 issue の未マージ branch を base にしない。依存 issue がある場合は依存 PR の merge 後に main を更新し、rebase してから検証する。

## commit / push / PR

- commit: 日本語 Conventional Commits を使い、タイトル末尾に `(#<N>)` を付ける
- push: issue branch だけを push する
- PR: `Closes #<N>`、変更概要、検証コマンド、参照した公式資料を本文へ記載する
- merge: required CI 成功後に行う。チェックの削除・弱体化で green にしない

## 環境

親 checkout と新規 worktree の両方で devShell に入る。direnv があれば `direnv allow` で `.envrc` を allow し、なければ `nix develop` を使う。どちらも shellHook が `uv sync` を自動実行する。非対話 shell は `nix develop --command <command>` を使う。

ローカル git hook は存在しない。品質ゲート（ruff / CHANGELOG / any 型）は CI が担保する（`docs/development.md` の「品質ゲート（CI）」）。

## 旧 takt 状態

`.takt/` 配下の runtime 補助、過去 run、task 履歴は過去実績の参照用であり、現在の正規入口ではない。古い failed / pending task や `takt-worktrees/` の残骸を新しい作業へ再利用しない。不要な runtime 状態を掃除する場合は対象を明示して確認し、通常の issue worktree や未マージ変更を巻き込まない。
