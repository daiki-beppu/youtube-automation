---
name: viewing-scene
description: Use when 視聴シーン（いつ・どこで・なぜ聴くか）を検証・定義したいとき。「視聴シーン」「利用シーン」「どんな時に聴かれるか」「シーン分析」「視聴者はいつ聴く」「TTP の用途設計版」など。/audience-persona の結果を踏まえてシーン別パフォーマンスを分析。チャンネル立ち上げ・方向性見直し時に必ず使用すること
---

## Overview

自チャンネル既存データのシーン別パフォーマンス + ベンチマーク競合の活動タグ分析 +
YouTube 検索需要調査で、注力すべきシーンと最適な動画尺を特定する。

## TTP 原則（ベンチマーク参照）

シーン定義は **TTP（徹底的にパクる）の用途設計版**。
ベンチマーク競合のタイトルに現れる活動タグ（for Study / for Focus / for Sleep 等）と
動画尺の **型** を抽出し、自チャンネルのシーン候補に転写する。
独自シーンは、転写した型の空白に対して設計する順序を取る。

## 前提

- `config/channel/` が存在すること（`load_config()` でロード可能）。
  存在しない場合 → 新規チャンネルなら `/channel-new`、既存チャンネルなら `/channel-import` を案内。
- `docs/channel/personas/persona-definition.md` が存在すること（未実施なら `/audience-persona` を案内）
- `reports/` に最新の分析レポートがあること（なければ `/analytics-collect` → `/analytics-analyze` を案内）

## 実行フロー

### Phase 1: データ収集（サブエージェント並列）

**3つのサブエージェントを並列起動**（Agent ツール）:

**Agent 1: 自チャンネルシーン別パフォーマンス**
- `reports/` の最新分析レポートを読み込み
- 各動画の想定シーン（study, sleep, relaxation, dnd 等）を `config/channel/content.json` の `title.theme_activities` から判定
- シーン × 再生数 × 平均視聴時間のマッピング表を作成
- シーン別パフォーマンスランキングを生成
- 動画尺とパフォーマンスの相関分析

**Agent 2: ベンチマーク活動タグ分析**
- `data/benchmark_YYYYMMDD.json`（最新）を読み込み
- 全ベンチマーク動画のタイトルから活動タグ（for Study, for Focus, for Relaxation 等）を抽出
- 活動タグ別の平均再生数を比較
- チャンネルごとの動画尺パターンを比較分析
- TTP 対象として転写する活動タグ・尺パターンの **型** を明示

**Agent 3: 検索需要調査**
- `config/channel/content.json` の `tags.base` と `suno.genre_line`（またはチャンネルのジャンルキーワード）から動的にキーワードを構築して WebSearch で需要を調査する
- `config/channel/content.json` の `tags.base` と `genre.*` からキーワードを構築（例: `{genre.primary} music for study` / `{genre.style} music for work` / `作業用BGM {genre.primary}`）
- YouTube 検索のオートコンプリート傾向を推定

### Phase 2: シーン × ペルソナ クロス分析

Phase 1 の結果 + `persona-definition.md` を統合し:

1. 各シーンと各ペルソナの親和性マトリクスを作成
2. 最も効果的なシーン3つを特定
3. 動画尺の最適解を導出（シーン別 or 統一）
4. 現行設定（`audio.target_duration_min`）の妥当性を検証

### Phase 3: 意思決定 + レポート保存

AskUserQuestion でメインシーンと動画尺の方針を確認。
`docs/plans/viewing-scene-matrix.md` を生成。

## 関連ファイル

- `docs/channel/personas/persona-definition.md` — ペルソナ定義（入力）
- `reports/analysis_*.md` — チャンネルパフォーマンスデータ
- `data/benchmark_YYYYMMDD.json` — ベンチマーク動画データ
- `config/channel/content.json` — `title.theme_activities`
- `config/channel/audio.json` — `audio.target_duration_min`
