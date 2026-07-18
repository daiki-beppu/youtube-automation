---
name: thumbnail-compare
description: "Use when 自チャンネルの生成済みサムネイルを競合と並べて 320px 視認性を比較検証するとき。「サムネ比較」「目立ってるか確認」「モバイル表示テスト」「320px」で発動。競合だけの勝ちパターン分析は /thumbnail-research、生成は /thumbnail、Studio の A/B テスト設計・結果記録は /thumbnail-test"
---

## 前後工程

- `前工程`: `/thumbnail`, `/benchmark`
- `後工程`: `なし`

## Overview

自チャンネルの全サムネイルとベンチマーク3チャンネルの1万再生以上の動画サムネイルを
ダウンロード・並列比較し、検索結果・おすすめで目立つかを検証する。

## 完了条件

- Phase 3 の比較結果（要素別比較表 / 図鑑効果評価 / 320px 縮小表示テスト / 優先度付き改善提案）が揃っている
- `docs/plans/thumbnail-comparison.md` にレポートが保存され、`open data/thumbnail_compare/` でプレビューを提示している

## 前提

以下を確認し、満たさなければ前工程を案内して停止する:

- `config/channel/` が存在すること（`load_config()` でロード可能）。存在しない場合は `/channel-new`（既存チャンネルは取り込みモード）を案内して停止する
- `config/channel/analytics.json::benchmark.channels` に承認済みベンチマークチャンネルが設定済みであること。未設定なら `/channel-new` / `/discover-competitors` を案内して停止する
- `data/benchmark_*.json` が存在すること（鮮度が古い場合はスクリプトが自動更新する）。一度も収集していなければ先に `/benchmark` を案内する
- 自チャンネルのサムネイル `collections/live/*/10-assets/thumbnail.jpg` が 1 件以上存在すること。無ければ比較対象なしとして `/thumbnail` → `/video-upload` の前工程を案内する
- ベンチマーク更新は YouTube Data API を使うため `auth/token.json` の OAuth 認証が必要。未認証なら `/setup` を案内する

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API v3（直接呼び出し） | 0（ローカル比較 + CDN 画像 DL のみ） | — |
| YouTube Data API v3（ベンチマーク自動再収集） | ベンチマークが鮮度切れの場合のみ /benchmark 相当（1 チャンネルあたり数 units） | ベンチマークデータの鮮度 |

- 上限 / 承認: 事前に `/benchmark` でデータを最新化しておけば API call 0 で完結する（サムネイル DL は CDN 直取得で quota を消費しない）。

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

**2つのサブエージェントを並列起動**（Agent ツール。サブエージェント機能が無い実行環境（Codex 等）では、同じ 2 つの分析を同一セッションで順次実行する）:

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

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ不在 | `data/` のベンチマーク/Analytics スナップショットが無い | 先に `/benchmark`・`/analytics-collect` 等を実行して入力を用意 |
| サムネ取得失敗 | `yt-thumbnail-compare` の画像 DL が HTTP エラー | YouTube / CDN のステータスを確認し時間を置いて再実行 |

## 関連ファイル

- `yt-thumbnail-compare` (`youtube_automation.scripts.compare_thumbnails`) — サムネイル収集・縮小スクリプト
- `data/thumbnail_compare/` — 出力ディレクトリ
- `data/benchmark_YYYYMMDD.json` — ベンチマーク動画データ（サムネURL）
- `collections/live/*/10-assets/thumbnail.jpg` — 自チャンネルサムネイル
- `docs/benchmarks/common-patterns.md` — サムネイルチェックリスト v4
- `data/video_analysis/<slug>/<video_id>.json` — `/video-analyze` の `signature_elements` / `hook_structure` 出力（競合のサムネ実装パターン抽出を補強）
  - 冒頭クリップ窓（既定 900 秒、JSON の `analysis_window_sec`）内の実装パターン。動画全尺で出る signature 要素を網羅したものとは扱わない。
