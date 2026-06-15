# 配布形態: npm 公開 + 単一 bundle CLI (ccusage 型)

## Context

ADR 0001 は TS 再実装の戦略を決めたが、**下流チャンネルリポが TS 版をどう消費するか** (配布形態) は未決だった。PR #791 のグリルセッション (2026-06-12) で以下の制約が確定した:

- 現行 Python 版は uv + git+https / submodule で消費されているが、TS 版で同じ「git 直接参照」は成立しない。`@youtube-automation/cli` は `"@youtube-automation/core": "workspace:*"` に依存しており、**bun の git dependency は monorepo の workspace プロトコルを解決できない**
- 下流チャンネルリポは 5 リポ前後 (rain-jazz-night / fantasy-celtic-music / 8bah / soulful-grooves / deepfocus365 / template) あり、`automation-update` skill の「リリースを見て pin bump」フローと version pin の再現性を維持したい
- dogfood (epic #727 M2) は正式リリース前の pre-release を下流 2 リポへ配る手段を必要とする
- 親 issue #700 (MCP / サブスク化ロードマップ) の長期方向として、html2pptx.app のような hosted API / MCP 提供をベンチマークしているが、これは cutover (#790) とは別の山であり、migration のクリティカルパスに含めない
- ベンチマーク実例として ccusage (npm) を確認: 公開 npm package・`dependencies: {}` (全依存を単一 `dist/cli.js` に bundle 済み)・bin 1 個・`bunx ccusage` で zero-install 実行、という形態で同種の AI 周辺 CLI を配布している

検討時点で npm の `youtube-channels-automation` / `yt-automation` / `tayk` はいずれも未登録 (404 確認済み)。リポは PUBLIC のため npm 公開に障害はない。（package 名は ADR-0007 で `tayk` に確定）

## Decision

**ccusage 型の npm 公開 publish を採用する。**

1. **publish 対象は 1 package**: **`tayk`**（ADR-0007 の rebrand。旧 `youtube-channels-automation` から変更）。内部 scope `@tayk/core` は bundle に取り込まれるため publish しない。root / cli package の `"private": true` は publish 整備 (#968) で外す
2. **`bun build` で JS 依存を単一 `dist/cli.js` に bundle**: `workspace:*` 問題は publish 時に消滅し、下流 install は瞬時になる。ただし **`sharp` は native binary のため bundle 不可** — `dependencies` に sharp のみ残置する (ccusage と違い dependencies 完全空にはならない)。ffmpeg は従来どおり外部バイナリ前提で変化なし
3. **bin は単一 `tayk`** (ADR-0007 rebrand、ADR 0004 の citty dispatcher)。下流からの canonical 起動文字列は **devDependency install + `bunx tayk <cmd>`** に統一する。`.claude/skills/**` の置換 (#965 / #966) はこの文字列を正とする
4. **dogfood は npm dist-tag で実現**: `feat/ts-rewrite` から `0.1.0-alpha.N` を `alpha` dist-tag で publish し、下流 dogfood リポは devDependency で pin。cutover (#790) で `0.1.0` を `latest` へ publish する
5. **publish は GitHub Actions + npm provenance** で自動化し、`/automation-release` skill (#729) に publish ステップを接続する
6. `automation-update` skill (#728) は「下流 `package.json` の devDependency bump」対応へスコープ変更する。5.x へのロールバックは skill に実装せず、旧 `pyproject.toml` 行を復元する手作業 runbook を #790 に記載する

## Considered Options

- **GitHub Release に tarball / 単一バイナリ添付** (extensions の `release-extensions.yml` と同型): version pin は可能だが、bun/npm の標準依存解決に乗らないため下流の install 体験と `automation-update` の実装が独自実装になる。npm publish が workspace 問題・pre-release 配布 (dist-tag)・provenance まで標準機構で解決するため不採用
- **submodule + `bun --cwd`**: 下流 5 リポへの checkout / `bun install` 管理が分散する。1 リポ運用なら最安だが現状に合わず不採用
- **git+https 直接参照**: `workspace:*` が解決できず成立しない
- **hosted API / MCP (SaaS) を最初から配布形態にする**: #700 の長期方向だが、cutover の受入基準に混ぜると migration が「サービス基盤構築」に膨らむ。ADR 0004 が registry/adapter 分離を確保済みのため、cutover 後に `yt mcp` subcommand (ccusage の `ccusage mcp` と同型) を足す後続 epic として分離

## Consequences

- #968 (npm publish 基盤) が Tier 1 (dogfood ブロッカー) として epic #727 に追加された
- #728 / #729 のスコープが本 ADR 前提に変更された
- `.claude/skills/**` の呼び出し置換 (#965 / #966) は canonical 起動文字列 `bunx tayk <cmd>` を正として実施する
- package 名は `tayk`（ADR-0007）。publish 前 (#968 完了前) であれば再改名コストはゼロ。#980 が別案に収束した場合は ADR-0007 を改訂する
- npm 公開によりコードの可視性は変わらない (リポは元々 PUBLIC)。シークレットは従来どおり `os.environ` → `op read` 解決であり、package に同梱される情報はない
