---
name: channel-direction
description: Use when /channel-research の分析結果をもとに新チャンネルの方向性を決定したいとき。「方向性決めたい」「チャンネルの方針」「ポジショニング」「差別化」「ブレスト」など、新チャンネルの戦略的方向性を対話で決定する場面で使用すること。/channel-research の後、/channel-setup の前に実行する
---

## Overview

`/channel-research` の分析レポートをもとに、ユーザーと対話で新チャンネルの方向性を決定する。
データに基づいた議論を行い、決定事項をドキュメントに保存する。

**前提**: `/channel-research` が完了し、`docs/channel-research.md` が存在すること。

## Instructions

**実行場所**: リポジトリルート（チャンネルの独立リポジトリ）

### Step 1: 分析レポートの読み込みとサマリー

`docs/channel-research.md` を読み込み、ユーザーに要点をサマリーで提示:

- 競合の全体像（登録者レンジ、投稿頻度、平均再生数）
- 最も参考になるチャンネル（ロールモデル候補）
- 機会領域（ブルーオーシャン）
- 視聴者が求めているもの

#### ベンチマーク BGM 構造（video-analyze 平均）

`config/channel/analytics.json` の `benchmark.channels[].slug` を列挙し、各 slug について
`data/video_analysis/<slug>/*.json`（`/video-analyze` の出力）が存在するか確認する。

- **存在する場合**: `bgm_arc.intro` / `bgm_arc.peak` / `bgm_arc.outro` / `bgm_arc.energy_curve`
  と `scene_timeline[].start` / `scene_timeline[].summary` を読み込み、slug ごとに intro 秒・peak 秒・
  outro 開始秒の平均と代表的な `energy_curve` パターンをまとめる。`scene_timeline` からは
  「視覚的に強い瞬間」の傾向（出現タイミング・密度）を抽出する。
- **`data/video_analysis/<slug>/*.json` 不在 + `data/benchmark_*.json` も不在**: ユーザーに
  「`/benchmark` を先行実行してください」と案内し、本サブセクションはスキップして警告のみで続行。
- **`data/benchmark_*.json` は存在するが分析未実行**: `AskUserQuestion` で
  `uv run yt-video-analyze --source benchmark --channel <slug> --top 5` の自動実行を提案。承認時のみ
  実行、拒否時は警告のみで続行。
- **鮮度警告**: 各 `.json` の `analyzed_at` が最新 `data/benchmark_*.json` のファイル名日付より古い場合は
  警告のみ（中断しない）。

サマリー出力フォーマット:

```
**ベンチマーク BGM 構造（video-analyze 平均）**

| slug | intro (avg) | peak (avg) | outro 開始 (avg) | energy 代表 |
|---|---|---|---|---|
| <slug> | 12s | 1:45 | 8:20 | 「徐々に上昇 → 中盤ピーク → ゆるやかなフェード」 |
```

このサマリーは Step 2 の「6. 競合の BGM 構造」議論で根拠データとして再利用する。

### Step 2: ポジショニング議論

分析レポートの「推奨事項」をベースに、ユーザーと以下を議論する。
**常にデータ根拠を示しながら**議論を進めること。

#### 議論ポイント

1. **ジャンル & スタイルの確定**
   - 競合の空白ポジションはどこか
   - ユーザーの好み・得意分野とのマッチング
   - 「{genre.primary}」「{genre.style}」「{genre.context}」を確定

2. **差別化ポイント**
   - 競合にない要素は何か（テーマ、スタイル、世界観、品質）
   - 持続可能な差別化か（一時的なトレンドではないか）

3. **ターゲット視聴者**
   - コメント分析から見える主要な視聴者像
   - 狙うべきセグメント
   - 利用シーン（勉強、睡眠、作業、ゲーム等）

4. **コンテンツ戦略**
   - 動画の長さ（競合のデータを参考に `audio.target_duration_min` を決定）
   - 投稿頻度（競合の投稿間隔データを参考に）
   - テーマの幅（専門特化 vs 多様性）

5. **ビジュアルアイデンティティ**
   - サムネイルの方向性（競合分析のサムネイルパターンを参考に）
   - チャンネル全体のトーン＆マナー

6. **競合の BGM 構造**
   - Step 1 のベンチマーク BGM 構造サマリー（`bgm_arc` 平均・`scene_timeline` 傾向）を根拠に、
     楽曲展開（intro / peak / outro の尺配分、エネルギー曲線）の方針を議論
   - 競合の構造を踏襲するか、意図的に外して差別化するかを明示
   - データが不足している場合は本ポイントは省略（無理に推測しない）

7. **チャンネル名の確定**
   - 仮名の見直し
   - SEO 観点（検索されやすさ）
   - ブランド観点（覚えやすさ、独自性）

### Step 3: 決定事項の整理

議論の結果を整理し、ユーザーに最終確認:

| 項目 | 決定内容 | データ根拠 |
|------|---------|-----------|
| チャンネル名（確定） | | |
| 短縮名（3-5文字） | | |
| リポジトリ名 | | |
| genre.primary | | 競合の空白ポジション |
| genre.style | | |
| genre.context | | |
| コアメッセージ | | 視聴者インサイト |
| 差別化ポイント | | 競合にない要素 |
| ターゲット視聴者 | | コメント分析 |
| 動画の長さ（分） | | 競合の傾向 |
| 投稿頻度 | | 競合の投稿間隔 |
| 音楽エンジン（デフォルト） | suno / lyria のどちらか | ジャンル適性・API 可用性 |
| BGM 構造方針 | intro / peak / outro 配分・エネルギー曲線 | 競合 BGM 平均構造（video-analyze） |
| サムネイル方針 | | 競合サムネイル分析 |

### Step 4: 方向性ドキュメント保存

決定事項を `docs/channel-direction.md` に保存:

```markdown
# チャンネル方向性

## 基本情報
- チャンネル名: {name}
- 短縮名: {short}
- ジャンル: {primary} / {style} / {context}
- コアメッセージ: {core_message}

## ポジショニング
- 差別化ポイント: ...
- ターゲット視聴者: ...
- 主な利用シーン: ...

## コンテンツ戦略
- 動画の長さ: {target_duration_min}分
- 投稿頻度: ...
- テーマの幅: ...

## ビジュアルアイデンティティ
- サムネイル方針: ...
- トーン＆マナー: ...

## 決定の根拠
[各決定のデータ根拠をまとめる]
```

### Step 5: 次フェーズへの案内

「方向性が確定しました。次は `/channel-setup` でテクニカルセットアップを行います。」

リポジトリ名が変更された場合、ユーザーにリポジトリのリネームを案内する。

## Cross References

- `/channel-research` → 前フェーズ: ベンチマーク分析
- `/channel-setup` → 次フェーズ: テクニカルセットアップ
- `/video-analyze` → Step 1 のベンチマーク BGM 構造サマリーで `data/video_analysis/<slug>/*.json` を参照
