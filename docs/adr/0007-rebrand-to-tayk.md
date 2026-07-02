# Product rebrand to `tayk` (ADR-0001 の identity 決定を supersede)

## Status

accepted (2026-06-14)。**ADR-0001 §Identity（package 同名維持）を supersede** する。

2026-07-02 監査注記: 起案時前提「下流は全て first-party（第三者 consumer なし）」は ADR-0015 (2026-06-25) で外部ユーザー（数十人規模）の実在に更新された。移行コストは ADR-0015 §移行戦略（告知 + 移行ガイド + skills エントリポイント安定）で吸収するため、rebrand 決定自体は維持する。なお workspace scope 名（`@youtube-automation/*` → `@tayk/*`）の改名は未実施 — lock point は最初の alpha publish 前。

## Context

ADR-0001 は TS 移行にあたり package 名を `youtube-channels-automation` のまま維持し（下流に "同じツールの大幅 update" と見せる）、新名採用を「別ツールへの乗り換え体験 = オーバーキル」として却下していた。PR #791 のグリル (2026-06-14) でこの前提を再評価した:

- 下流 5 リポは **全て first-party**（第三者 consumer なし）。「別ツール乗り換え」コストは自分が負い、`automation-update` skill (#728) が自動化する
- 現 Python 版は **npm 未公開**（git+https / submodule 配布）。TS 版が初 npm publish であり、下流は「Python git-pin → npm devDep」という **配布方式の乗り換え**を必ず通過する。同名は同一性の糸を 1 本残すだけで "単なる bump" にはならない
- `tayk` / `@tayk/core` は npm 未登録（404 確認済み）

## Decision

公開ブランドを **`tayk`** に rebrand する:

1. **公開 npm package 名 = `tayk`**（ADR-0006 の publish 対象 1 package）
2. **bin 名 = `tayk`**（ccusage 流の package==bin）。canonical 起動文字列は **`bunx tayk <cmd>`**
3. **内部 workspace scope = `@tayk/*`**（`@tayk/core` / `@tayk/cli`）。core は bundle され publish しないため cosmetic だが整合のため改名する
4. version reset (`5.5.7 → 0.1.0`) は ADR-0001 のまま不変

## Why

- 配布方式も版数も総入れ替えする以上、AI-first reframe を外見（ブランド）にも出す方が誠実。同名維持の利点（下流の移行摩擦低減）は first-party + #728 自動化でほぼ消える
- `tayk` は短く bin / `bunx` 起動に向き、`youtube-channels-automation` の冗長さを解消する

## Consequences

- **ADR-0001 §Identity を supersede**（同名維持 → rebrand）。ADR-0001 Considered Options の「新 package 名は却下」も本 ADR で反転
- **ADR-0006 更新**: publish 名 `youtube-channels-automation` → `tayk`、bin `yt` → `tayk`、canonical 起動 `bunx yt` → `bunx tayk`
- **ADR-0004 更新**: dispatcher 起動例 `yt skills list` → `tayk skills list`
- **#965 / #966**: skills の `uv run` 置換先を **`bunx tayk <cmd>`** に確定（`bunx yt` ではない）
- **#728 (automation-update)**: scope を「同名 devDep bump」→「`youtube-channels-automation`(git) を外し `tayk`(npm devDep) を載せる package 載せ替え + 5.x→0.x」に再記述
- **#968 (publish 基盤)**: publish 名 = `tayk`、内部 scope `@tayk/*` 改名を含む
- **lock point**: 最初の alpha publish (#968) 前に rebrand を反映する。publish 後の再改名はコスト大
- `tayk` は仮の最終候補。#980 が別案に収束した場合のみ（publish 前まで）本 ADR を改訂する

## Related

- ADR-0001（identity を supersede） / ADR-0006（配布、名前更新） / ADR-0004（bin）
- #980 (naming research) / #968 / #965 / #966 / #728 / Epic #727
