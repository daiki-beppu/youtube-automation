---
name: thumbnail-compare
description: Use when サムネイルをベンチマーク競合と並べて比較検証したいとき。「サムネ比較」「サムネイル検証」「目立ってるか確認」「サムネ並べて」「モバイル表示テスト」「320px」など。文字サイズ・コントラスト・縮小表示での視認性を検証。方向性見直し時に必ず使用すること
---

## Overview

自チャンネルの全サムネイルとベンチマーク3チャンネルの1万再生以上の動画サムネイルを
ダウンロード・並列比較し、検索結果・おすすめで目立つかを検証する。

## 実行フロー

### Phase 1: サムネイル収集（スクリプト実行）

```bash
uv run yt-thumbnail-compare --no-open
```

スクリプトが自動で以下を実行:
1. ベンチマークデータの鮮度チェック → 古ければ全チャンネル一括更新
2. 1万再生以上の動画サムネイルをダウンロード → `data/thumbnail_compare/benchmark/`
3. 自チャンネルの全サムネイルをコピー → `data/thumbnail_compare/自チャンネルスラッグ/`
4. 全サムネイルを 320x180px に縮小 → `data/thumbnail_compare/small/`

### Phase 2: 比較分析（サブエージェント並列）

**2つのサブエージェントを並列起動**（Agent ツール）:

**Agent 1: ベンチマークサムネイル分析**
- `data/thumbnail_compare/benchmark/` の全画像を Read ツールで確認
- 各サムネイルの以下を評価・記録:
  - アートスタイル（アニメ/フォトリアル/イラスト）
  - キャラサイズ（フレームに対する割合）
  - キャラの顔の見え方（正面/横顔/後姿）
  - 活動の具体性（演奏/読書/ティータイム/立つだけ）
  - 楽器の有無
  - テキスト構成（タイトル/ジャンルラベル/チャンネル名）
  - 明るさ（明るい/中間/暗い）
  - 再生数との相関パターン
- チャンネル別の共通パターンを抽出

**Agent 2: 自チャンネルサムネイル分析**
- `data/thumbnail_compare/自チャンネルスラッグ/` の全画像を Read ツールで確認
- Agent 1 と同じ評価項目で分析
- `data/thumbnail_compare/small/` の自チャンネル縮小版で 320px 視認性をテスト:
  - テキストが読めるか
  - キャラが認識できるか
  - 何のシーンか一目で分かるか

### Phase 3: 比較レポート生成

Agent 1 + Agent 2 の結果を統合し、以下の比較表を作成:

1. **要素別比較表**: 自チャンネル vs ベンチマーク各チャンネル
2. **チャンネルページ「図鑑効果」評価**: 自チャンネルの全サムネを並べたときの統一感
3. **320px 縮小表示テスト結果**: モバイルでの視認性
4. **改善提案**: 優先度付きのアクション項目

### Phase 4: レポート保存 + プレビュー

`docs/plans/thumbnail-comparison.md` を生成。
サムネイル比較ディレクトリを `open` で表示:

```bash
open data/thumbnail_compare/
```

## 関連ファイル

- `yt-thumbnail-compare` (`youtube_automation.scripts.compare_thumbnails`) — サムネイル収集・縮小スクリプト
- `data/thumbnail_compare/` — 出力ディレクトリ
- `data/benchmark_YYYYMMDD.json` — ベンチマーク動画データ（サムネURL）
- `collections/live/*/10-assets/thumbnail.jpg` — 自チャンネルサムネイル
- `docs/benchmarks/common-patterns.md` — サムネイルチェックリスト v4
