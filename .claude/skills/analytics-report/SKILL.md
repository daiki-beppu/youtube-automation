---
name: analytics-report
description: Use when Analytics分析レポートの表示・閲覧が必要なとき。過去レポートの比較やパフォーマンスレビュー時に使用。「レポート見せて」「過去データ確認」「パフォーマンスレビュー」「前回の分析結果」など、既存レポートの参照・比較が必要な場面で必ず使用すること
---

## Overview

`reports/` ディレクトリに保存された Analytics 分析レポートを表示、または HTML ビジュアルレポートを生成します。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- 定期的なパフォーマンスレビュー時
- 戦略検討の参考データが必要なとき
- 過去のレポートを比較したいとき
- 視覚的なダッシュボードレポートが必要なとき

## Quick Reference

| 引数 | 説明 |
|------|------|
| `/analytics-report latest` | 最新の分析レポートを表示 |
| `/analytics-report html` | HTML ビジュアルレポートを生成（全履歴データ集約） |
| `/analytics-report list` | 全レポートファイル一覧表示 |
| `/analytics-report` | 引数なし = 最新レポート表示 |

## Instructions

### `/analytics-report latest` / `/analytics-report`（デフォルト）

`reports/` ディレクトリから最新のレポートファイルを検出して内容を表示する。

### `/analytics-report list`

`reports/` ディレクトリ内の全レポートファイルを一覧表示する。

### `/analytics-report html` — ビジュアルレポート生成

`data/` 配下の **全 analytics スナップショット** と `benchmark` データを集約し、視覚的な HTML レポートを `reports/` に生成する。

#### データ収集手順

1. `data/analytics_data_*.json` を全件読み込み、時系列順にソート
2. `data/benchmark_*.json` の最新ファイルを読み込み
3. `config/channel/*.json` からチャンネル情報を取得
4. 各スナップショットから以下を抽出:
   - `channel_analytics.daily_metrics` — 日次メトリクス（重複日は最新値優先）
   - `channel_analytics.ctr_data` — CTR スナップショット
   - `video_analytics` — 動画別メトリクスのスナップショット間推移

#### HTML レポート構成

**単一 HTML ファイル**（CSS インライン + Chart.js CDN）で以下のセクションを含める:

1. **ヘッダー & KPI カード**
   - チャンネル名、分析期間
   - 4枚の KPI カード: 総再生数 / 総視聴時間 / 登録者数 / CTR

2. **日次推移チャート**（Chart.js 折れ線グラフ）
   - Views（青系）と Watch Time（緑系）の dual-axis
   - 全スナップショットの daily_metrics を統合（重複日は最新値）

3. **動画別パフォーマンス表（Complete Collection）**
   - Views, Watch Time, Avg Duration でソート可能
   - 数値に応じた背景色グラデーション（ヒートマップ風）
   - Complete Collection（長尺）のみ集計（タイトルに `#Shorts` を含まない動画）

4. **Shorts パフォーマンス表**
   - 公開済み Shorts（タイトルに `#Shorts` を含む動画）を別表で集計
   - Views, Watch Time, Avg Duration を Complete Collection と同じ軸で比較
   - 各 Shorts の親 Complete Collection への流入導線リンクを併記（`upload_tracking.json` 経由）
   - Shorts が 0 件のチャンネルは本セクションをスキップ

6. **動画別 Views 推移**（Chart.js 折れ線グラフ）
   - 各スナップショット収集日ごとの動画別 views を折れ線で表示
   - 成長率が視覚的にわかるよう色分け

7. **CTR 推移**（Chart.js バーチャート + 折れ線）
   - スナップショットごとの impressions（バー）と CTR%（折れ線）

8. **競合ベンチマーク比較**
   - 自チャンネル vs 競合チャンネルのスケール比較表
   - 競合 Top 動画の views/engagement rate

9. **分析 & 改善提案**
   - データから導出される戦略的インサイト
   - 具体的なアクションプラン

#### デザインテーマ

```
カラーパレット:
- 背景: #0f1419 (ダークネイビー)
- カード背景: #1a2332
- アクセント: #c8a96e (ブランドアクセントカラー)
- テキスト: #e8e6e3
- チャート色: #4ecdc4, #45b7d1, #96ceb4, #ffeaa7, #dfe6e9
- 成功: #00b894
- 警告: #fdcb6e
- 危険: #e17055

フォント: system-ui, -apple-system, sans-serif
レスポンシブ: max-width: 1200px, モバイル対応
```

#### 出力

- **ファイル名**: `reports/{channel_slug}_analytics_YYYYMMDD.html`（`channel_slug` は `config/channel/meta.json` の `channel.short` を小文字化したもの、日付は実行日）
- 生成後に `open reports/{channel_slug}_analytics_YYYYMMDD.html` でブラウザ表示

#### CTR 値の解釈

Analytics API の `ctr_percentage` は **整数値**（例: 2606 = 実際のパーセントとして解釈が必要）。
`impressions` と `ctr_percentage` の関係から実際の CTR% を算出:
- `click_count ≈ impressions × (ctr_percentage / impressions)` ではなく
- 実際には API が返す値をそのまま使用し、表示時に適切にフォーマットする

#### 注意事項

- 開設初期（データが少ない場合）でも見栄えが崩れないようにする
- 0 views の動画もテーブルに含める（データの完全性）
- Complete Collection と Shorts は性質（尺・流入導線）が異なるため**別表に分離**して集計する（旧版では Shorts を除外していたが、Shorts スキル復活に伴い別表で可視化する方針に変更）
- 集計上の判定はタイトルに `#Shorts` を含むかどうか
- benchmark データがない場合はセクションをスキップ

## Next Step

レポート生成後:
→ `/analytics-analyze` で詳細な戦略分析を実行
→ `/collection-ideate` でデータに基づくコレクション企画を生成
