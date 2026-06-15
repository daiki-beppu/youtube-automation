# Cutover の merge 戦略: merge-commit + roll-forward 一本 (main revert 禁止)

## Status

accepted (2026-06-14)

## Context

epic #727 の cutover (#790) は umbrella PR #791 (`feat/ts-rewrite`) を main へ統合する一発の big-bang。統合方式 (merge-commit / squash / rebase) と、統合後に TS 側 critical bug が出たときの復旧方式 (revert / roll-forward) を固定しておく必要がある。これまで PR #791 / epic #727 の本文にのみ書かれていた運用ルールを decision record に固定する。

## Decision

1. **cutover は merge-commit で統合する** (`gh pr merge --merge`、squash / rebase しない)。全子 issue の commit 履歴を main に残し、後日 "あの判断はどこで入ったか" を grep 可能にする
2. **Python 一掃は merge 前に branch 上で commit** し CI green を確認してから merge する (merge 後の main でのぶっつけ削除はしない)
3. **main の git revert は禁止**。TS 側 critical bug は **roll-forward 一本** (修正を前に積む)
4. **下流の復旧は per-repo**: `v5.5.7` tag へ pin を戻すだけ (旧 pyproject 行の復元 runbook を #790 に記載)

## Why

- **merge-commit**: squash は 60+ 子 issue の履歴を 1 commit に潰し、決定の出所が追えなくなる。merge は履歴 grep 性を保つ
- **revert 禁止**: merge commit の revert は、後で再 merge する際に revert-of-revert が必要になる罠がある。big-bang を一度 revert すると再 cutover が著しく面倒になる。roll-forward なら常に前進のみで罠を踏まない
- **per-repo rollback**: 下流は first-party のみ。各リポが Python pin に戻せる以上、main を巻き戻す必要がない

## Considered Options

- **squash merge**: 履歴が 1 commit になり grep 性を失う。不採用
- **main で git revert して復旧**: revert-of-revert の罠。big-bang では特に痛い。不採用
- **merge 後の main で Python 削除**: 削除途中で CI が割れた状態が main に乗るリスク。merge 前 branch 削除の方が安全。不採用

## Related

- ADR-0001 (big-bang big picture) / Epic #727 / 統合 PR #791 / cutover #790
