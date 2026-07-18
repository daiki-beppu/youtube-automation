---
name: analytics-report
description: "Use when 既存の Analytics レポートを表示・比較したいとき。「レポート見せて」「過去データ確認」「前回の分析結果」で発動"
---

## 前後工程

- `前工程`: `/analytics-analyze`
- `後工程`: `なし`

## Overview

`reports/` ディレクトリに保存された Analytics 分析レポートを表示、または HTML ビジュアルレポートを生成します。

## 完了条件

- `latest` / `list` / 引数なし: 該当レポートの内容（または一覧）を表示した時点で完了
- `html`: `reports/{channel_slug}_analytics_YYYYMMDD.html` を生成し、`open` でブラウザ表示した時点で完了

## 設定読み込みゲート

前提確認やレポート生成に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/analytics-report/config.default.yaml`
2. `config/skills/analytics-report.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("analytics-report")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。HTML レポートの KPI カードは `html.kpi_cards`、Shorts 除外キーワードは `html.exclude_title_keywords`、テーマ色は `theme.colors` を参照する。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

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

`reports/` ディレクトリから更新時刻が最新の Markdown 分析レポート（`ls -t reports/analysis_*.md | head -1` で取得できるもの）を検出して内容を表示する。同日付の `analysis_YYYYMMDD.json` は `/analytics-analyze` の数値根拠を保持する構造化成果物であり、`latest` の表示対象にはしない。

### `/analytics-report list`

`reports/` ディレクトリ内の全レポートファイルを一覧表示する。

### `/analytics-report html` — ビジュアルレポート生成

`data/` 配下の **全 analytics スナップショット** と `benchmark` データを集約し、視覚的な HTML レポートを `reports/` に生成する（KPI カード・Shorts 除外・テーマ色は「設定読み込みゲート」で読んだ skill-config を使う）。

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
   - KPI カードは skill-config `html.kpi_cards` の並び順・枚数で描画（既定 4 枚: 総再生数 / 総視聴時間 / 登録者数 / CTR）

2. **日次推移チャート**（Chart.js 折れ線グラフ）
   - Views（青系）と Watch Time（緑系）の dual-axis
   - 全スナップショットの daily_metrics を統合（重複日は最新値）

3. **動画別パフォーマンス表**
   - Views, Watch Time, Avg Duration でソート可能
   - 数値に応じた背景色グラデーション（ヒートマップ風）
   - Complete Collection のみ表示（skill-config `html.exclude_title_keywords` にタイトルが部分一致する動画 = Shorts を除外）

4. **動画別 Views 推移**（Chart.js 折れ線グラフ）
   - 各スナップショット収集日ごとの動画別 views を折れ線で表示
   - 成長率が視覚的にわかるよう色分け

5. **CTR 推移**（Chart.js バーチャート + 折れ線）
   - スナップショットごとの impressions（バー）と CTR%（折れ線）

6. **競合ベンチマーク比較**
   - 自チャンネル vs 競合チャンネルのスケール比較表
   - 競合 Top 動画の views/engagement rate

7. **分析 & 改善提案**
   - データから導出される戦略的インサイト
   - 具体的なアクションプラン

#### デザインテーマ

色は skill-config `theme.colors` を使用する。既定パレットは `.claude/skills/analytics-report/config.default.yaml` に定義し、チャンネルごとの差し替えは `config/skills/analytics-report.yaml` で必要なキーだけ上書きする。

必須キー:
- `background`
- `card_background`
- `accent`
- `text`
- `chart_palette`
- `success`
- `warning`
- `danger`

フォント: system-ui, -apple-system, sans-serif
レスポンシブ: max-width: 1200px, モバイル対応

#### 出力

- **ファイル名**: `reports/{channel_slug}_analytics_YYYYMMDD.html`（`channel_slug` は `config/channel/meta.json` の `channel.short` を小文字化したもの、日付は実行日）
- 生成後に `open reports/{channel_slug}_analytics_YYYYMMDD.html` でブラウザ表示

#### CTR 値の解釈

`aggregated_ctr_percentage`（および `per_video[].ctr_percentage` / `per_day[].ctr_percentage`）は**百分率を表す float**（例: `4.2` = 4.2%）。
- 表示は小数 1〜2 桁 + `%` をそのまま付与する（例: `4.2%`）
- 100 で割る/掛ける、整数として再解釈するなどの変換は禁止（値はすでに百分率）
- `None` は「CTR データなし（Reporting API 未取得）」と表示する

#### 注意事項

- 開設初期（データが少ない場合）でも見栄えが崩れないようにする
- 0 views の動画もテーブルに含める（データの完全性）
- Shorts は動画パフォーマンス表から除外（skill-config `html.exclude_title_keywords`、既定 `#Shorts` にタイトルが部分一致する動画）。Complete Collection と KPI 構造（CTR / Avg Duration / 視聴維持の意味合い）が異なり同じ表で比較できないため。v5.5.1 で `/short` 由来の Shorts が増えても本表の集計対象外
- benchmark データがない場合はセクションをスキップ

## 障害時ガイダンス

分析は `data/` の収集済みスナップショットを読むため通常は外部 API を呼ばない。再収集が必要なときのみ以下が該当する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ不在 | `data/` のベンチマーク/Analytics スナップショットが無い | 先に `/benchmark`・`/analytics-collect` 等を実行して入力を用意 |
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |

## Next Step

レポート生成後:
- `/analytics-analyze` で詳細な戦略分析を実行
- `/collection-ideate` でデータに基づくコレクション企画を生成
