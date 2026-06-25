# 開発ロードマップ: cutover 中心の 4 フェーズ計画

## Context

Python v5.5.11 が main で運用中、`feat/ts-rewrite` で MCP tool 中心の 0 ベース TS 再設計が並走している (ADR-0001, 0002, 0007)。外部ユーザー（数十人規模のコミュニティ）が `uv add git+https://` で Python 版を導入し、Claude Code の skills 経由で運用している。cutover のタイミング、移行戦略、並走レーンの優先順位を決める必要がある。

## Decision

### タイムライン

| 月 | フェーズ | 内容 |
|---|---|---|
| **2026-07** | 告知 + 開発加速 | 移行告知を公開。TS リライト追い込み / Python fix 17件消化 / Chrome 拡張 fix |
| **2026-08** | dogfood + cutover | dogfood（first-party 2 リポで実走検証）→ `tayk@0.1.0` publish |
| **2026-09** | 新機能 | Community-helper 拡張 + Dashboard MVP 並走。外部ユーザー移行サポート |
| **2026-10〜** | 運用改善 | 安定化 + フィードバック反映 + 次の方向性検討 |

### cutover スコープ（`tayk@0.1.0` に含むもの）

- `packages/core` — service 層 + zod schema
- `packages/cli` — `tayk <cmd>` CLI adapter
- `packages/mcp` — MCP server（agent が直接呼べる typed tool）
- Knowledge codec 5 本 — 60+ skill を集約済み (`collection-lifecycle` / `channel-management` / `analytics` / `content-quality` / `distribution`)
- Remotion renderer — ffmpeg 直叩きからの切替
- libSQL local store — `<CHANNEL>/data/local.db`
- 移行ガイド

### 移行戦略

1. **告知期間 2 ヶ月**: 2026-07 頭に移行ガイド公開。「8 月中に Python 版は消えます、`tayk` に移行してください」
2. **legacy ブランチなし**: cutover 当日に main が TS に切り替わり、Python コードは即座に削除。`uv add git+https://` は即座に取得不可
3. **エントリポイント安定**: 外部ユーザーは skills 中心の利用。`/wf-new` → `/wf-next` のワークフローエントリポイントを維持し、裏の実装が Python → TS に変わっても体感の破壊を最小化
4. **周知徹底**: 内部構造の変更点（knowledge codec 集約、MCP tool 化）は移行ガイドで説明

### 並走レーン

cutover まで 3 レーンを並走:

- **A. TS リライト**（主軸）: MCP server + knowledge codec + Remotion 含む。dogfood → cutover
- **B. Python 品質**: #1225 の 17 件 fix-in-python。legacy ブランチなしのため cutover 時点が Python 最終版
- **C. Chrome 拡張**: suno-helper grid view fix (#1237) + 安定化

cutover 後:
- **C'. Community-helper**: Chrome 拡張新規 (#1192)
- **D. Dashboard**: マルチチャンネル analytics viewer (#1191)
- C' と D は 9 月に並走

### 実装体制

- コード実装は AI agent（takt + Claude/Codex）が行う
- 人間の役割はレビュー + GO/NO-GO 判断 + 外部ユーザーへの周知

## Considered Options

### legacy ブランチの維持

- **3 ヶ月維持（却下）**: `legacy` ブランチで Python 版を維持し critical bug のみ対応。安全だが AI agent でも Python の issue 対応が TS ロードマップを圧迫する
- **1 ヶ月維持（却下）**: 短い猶予で移行を促す。中途半端な並行メンテが二重管理コストを生む
- **維持なし（採用）**: 告知期間を設けた上で即切替。外部ユーザーは skills 中心利用のため、`/wf-new` エントリポイントさえ安定すれば移行は実行可能

### Knowledge codec 集約のタイミング

- **cutover と同時（採用）**: MCP server と codec を同時にリリースすることで、cutover 後すぐに新アーキテクチャの恩恵を受けられる
- **cutover 後に段階的（却下）**: 二度手間になる。skill 名の互換レイヤーを用意するコストが追加で発生する

### cutover 時期

- **2026-09（却下）**: 告知期間 3 ヶ月を確保できるが、集中力が続かない
- **2026-08（採用）**: 告知 2 ヶ月は短いが、外部ユーザーが skills 中心利用のため移行負荷が低い。AI agent 実装なら開発速度は十分
- **2026-12（却下）**: 余裕がありすぎてダレる

## Consequences

- 2026-07 頭に移行告知ドキュメントを公開する義務が発生
- feat/ts-rewrite の scope が拡大（MCP server + knowledge codec + Remotion を cutover に含む）
- Python 版 fix-in-python 17 件を 7-8 月で消化する必要がある（cutover 後は修正不可）
- 外部ユーザーで移行が間に合わない人のリスクを受容する（legacy ブランチなし）
- 10 月以降のロードマップは cutover 後のフィードバックで再検討
