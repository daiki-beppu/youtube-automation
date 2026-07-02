# Python → TypeScript(bun) 全面移行 (AI-first standardization, big-bang branch)

## Status

accepted (2026-06-02)。§Identity（package 同名維持）は ADR-0007 (2026-06-14) が supersede — 本文冒頭の注記参照。その他の決定（big-bang branch / v0.1.0 reset）は有効。実装は `feat/ts-rewrite` 上で進行中（cutover #790 で main へ反映予定）。

## Context

`src/youtube_automation/` (Python 28K 行) は歴史的経緯で Python だが、周辺環境 (Chrome 拡張 / Claude Code skills / MCP SDK / 自動化 tooling) は TS/bun スタックに収斂しており、Python は lone island になっている。コードを書くのも消費するのも LLM agent が主体になりつつあり、TS の方が LLM コード生成精度・MCP tool exposing の両面で適合する。現バージョン `5.5.7` は AI 駆動 release skill が積み重ねた人工的な数字で、実際の API 安定性を反映していない。

## Decision

`feat/ts-rewrite` branch で 0 ベース TS 再実装し、ある日 main に big-bang merge して Python を一掃する。~~package 名は `youtube-channels-automation` のまま維持し~~、version を `0.1.0` にリセットする。

> **⚠️ 2026-06-14 supersede (ADR-0007)**: 本 ADR の「同名維持」identity 決定は **ADR-0007 で `tayk` への rebrand に反転**した。下記 Why の「同名 + v0.x reset」と Considered Options の「新 package 名は却下」は ADR-0007 が上書きする。version reset (`0.1.0`) のみ本 ADR のまま不変。

## Why

- **AI-first reframe**: コード生産も消費も LLM agent が主体。TS は型情報が LLM context に乗りやすく、MCP server 実装も npm エコシステム (`@modelcontextprotocol/sdk`) が成熟している
- **big-bang choice**: motivation が "island elimination" なので、Strangler の長期間並走は反 motivation。AI 並列 agent 前提なら 28K 行 big-bang も人間スケールではない (想定 1-2 ヶ月)
- **同名 + v0.x reset**: 下流チャンネルリポにとっては "同じツールの大幅 update"。version `5.x` は AI 駆動 release skill の人工値であり、TS 版で API が stabilize するまで `0.x` が誠実

## Considered Options

- **Strangler パターン (旧 epic #701 当初案)**: 同リポで Python + TS 共存。両言語同居が "island elimination" 動機と矛盾し、AI agent (takt persona 等) の "どちらで書くか" 判断混乱を生むため不採用
- **Scope 縮小 → big-bang**: 46 CLI のうち頻度の高い 15-20 個に絞ってから書き直し。skill 整理は独立プロジェクトとして切り出し、scope 絞りは migration とは別動線で実施するため本 ADR の対象外
- **新 package 名で `v0.1.0`** (例: `@daiki-beppu/yt-automation`): ~~下流の "別ツールへの乗り換え" 体験になりオーバーキル。AI-first reframe は内部哲学であって外見契約ではないため、同名維持で十分~~ → **ADR-0007 で反転**: 下流が全 first-party + 配布方式も乗り換える以上、新名 `tayk` を採用
- **ccusage 流の bit-equal parity-check を全 CLI に適用**: AI-first reframe + `v0.x` なら API 不安定期間を許容するため、parity 厳密化は過剰。end-to-end smoke test に格下げ

## Consequences

- 旧 [epic #701](https://github.com/daiki-beppu/youtube-automation/issues/701) の 24 子 issue (#702-#725) は本 ADR を出典として再設計（約 10 issue + branch 内 commit に集約）。旧 epic は close
- `automation-update` skill の version 比較ロジックを `5.x → 0.x` の downgrade 許容に拡張
- `/automation-release` skill の version bump 判断を保守的に refactor（semver 厳密化、`[Unreleased]` の中身から major/minor を判定）— AI 肥大化の再発防止
- step 0 (#703 / #704 parity 基盤) は撤廃 (`v0.x` で bit-equal parity の必要性が低下、smoke test に格下げ)
