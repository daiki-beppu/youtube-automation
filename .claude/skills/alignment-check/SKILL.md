---
name: alignment-check
description: "Use when 音楽ムード × サムネ × タイトルの整合性を監査するとき。「整合性チェック」「タイトル見直し」「CTR改善」で発動。方向性見直し時に必須"
---

## Overview

公開済み全コレクションの音楽プロンプト・サムネイル・タイトルを横断的に監査し、
不一致箇所を特定。タイトルフォーマットの改定案も提示する。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## 実行フロー

### Phase 1: 全コレクション棚卸し（サブエージェント並列）

**2つのサブエージェントを並列起動**（Agent ツール）:

**Agent 1: コレクション × サムネ × 音楽プロンプト収集**
- `collections/live/` の全コレクションを列挙
- 各コレクションから以下を読み込み:
  - `workflow-state.json` — タイトル、テーマ、活動タグ。`planning.music`（mood / atmosphere / tempo / instruments）があれば優先採用
  - `20-documentation/suno-prompts.md` or `lyria-prompt.md` — 音楽ムード・楽器・テンポの補助資料
- コレクションごとの [タイトル / 音楽ムード / テーマ] を一覧表にまとめる

**Agent 2: ベンチマークタイトル構造分析**
- `data/benchmark_YYYYMMDD.json`（最新）を読み込み
- 全ベンチマーク動画のタイトル構造をパターン分類
- 各パターンの平均再生数を算出
- 現行テンプレート（`config/channel/content.json` の `title.template`）との比較

### Phase 2: サムネイル視覚確認

Agent 1 の結果から、全コレクションのサムネイルを Read ツールで順に表示:
- `collections/live/*/10-assets/thumbnail.jpg`
- 各サムネイルについて以下を評価:
  - 明るさ（◎/○/△/✗）
  - キャラサイズ（大/中/小）
  - キャラの活動（具体的か）
  - 楽器の有無
  - 音楽ムードとの整合性

### Phase 3: 整合性マトリクス作成

Phase 1-2 の結果を統合し、各コレクションの整合性を判定:

```
| 動画 | 音楽ムード | サムネ雰囲気 | タイトル訴求 | 整合性 |
```

不一致箇所には ⚠️ を付け、具体的な改善提案を付記。

### Phase 4: タイトルフォーマット改定

現行 vs ベンチマーク比較に基づき、新タイトルフォーマット案を提示。
既存動画のタイトル変更候補も提案（YouTube Studio で手動変更可能）。

タイトルの語彙チェック:
- 一般視聴者に分かる語彙か（Scriptorium, Bower, Vigil 等の難語を検出）
- YouTube 検索バーに打ち込む言葉か

### Phase 5: 意思決定 + レポート保存

AskUserQuestion で新タイトルフォーマットを確認。
`docs/plans/alignment-audit.md` を生成。
必要に応じて `config/channel/content.json` のタイトルテンプレートを更新。

## 障害時ガイダンス

整合性監査はローカルの成果物を読むだけで、外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ/設定の不在 | 参照先のローカルファイルが見つからない | 該当ファイルを用意するか前段スキルを先に実行（外部サービスに依存しないため API 障害・quota の影響は受けない） |

## 関連ファイル

- `config/channel/content.json` — `title.template`, `title.theme_activities`
- `docs/benchmarks/common-patterns.md` — 5つの成功法則
- `collections/live/*/10-assets/thumbnail.jpg` — サムネイル
- `collections/live/*/20-documentation/` — 音楽プロンプト
- `collections/live/*/workflow-state.json` — タイトル・テーマ
- `data/video_analysis/<slug>/<video_id>.json` — `/video-analyze` の `thumbnail_alignment` 出力（サムネ vs 本編の整合性監査の根拠）
  - 冒頭クリップ窓（既定 900 秒、JSON の `analysis_window_sec`）内の整合性データ。窓外で回収される訴求まで確認済みとは扱わない。

## Next Step

`docs/plans/alignment-audit.md` 保存後、不整合カテゴリに応じて以下のスキルを再実行する:

| 不整合カテゴリ | 症状 | 再実行スキル |
|---------------|------|-------------|
| **サムネ不一致** | 音楽ムードとサムネ雰囲気がズレ（例: lofi なのに派手な色調） | `/thumbnail <collection>` — 対象コレクションのサムネイル再生成 |
| **音楽ミスマッチ** | テーマ・タイトルと音楽プロンプトがズレ（例: 「rain」テーマなのに upbeat） | `/collection-ideate` で企画段階から見直し、その後 `/suno` または `/lyria` で再生成 |
| **タイトル改善のみ** | サムネ・音楽は OK だがタイトルの訴求/語彙が弱い | YouTube Studio で手動変更 + `config/channel/content.json` の `title.template` を更新 |
| **横断的な方向性ズレ** | 複数コレクションで同じ不整合パターン | `/channel-new`（方向性検討モード）でチャンネル全体の方向性を再検討 |

再実行後は `/alignment-check` を再度走らせて解消を確認する（フィードバックループ）。
