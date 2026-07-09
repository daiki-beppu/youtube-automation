---
name: analytics-analyze
description: "Use when 収集済み Analytics データの分析と戦略提案が必要なとき。「パフォーマンス分析」「戦略検討」「振り返り」で発動。/analytics-collect の後工程"
---

## Overview

収集済みの YouTube Analytics データを詳細分析し、データドリブンな改善提案を行います。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## When to Use

- `/analytics-collect` でデータ収集を完了した後
- `/wf-next` 完了（動画公開）から T+7 日後の初週パフォーマンス確認（推奨タイミング）
- 戦略検討のための詳細分析が必要なとき
- CTR 改善やコンテンツ最適化の根拠データが欲しいとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | 分析対象ファイル指定（省略可） | `/analytics-analyze data/analytics.json` |
| 未指定 | 最新の analytics データファイルを自動検出 | `/analytics-analyze` |

## Instructions

あなたは YouTube Analytics エキスパートです。`config/channel/content.json` の `genre` セクションからチャンネルのジャンル・コンテキストを読み取り、そのチャンネルに最適化された分析を行います。

### 鮮度チェック（並列実行対応）

分析実行前に `reports/` 配下の最新レポートを確認する:
- 30分以内に生成されたレポートがあれば分析をスキップし、その内容を使用
- スキップ時: 「既存レポートが十分新しいため分析をスキップしました（`<filename>`、`<N>`分前に生成）」と表示

### 対象データ

```
$ARGUMENTS
```

引数が指定されている場合はそのファイルを、未指定の場合は `data/` 配下の最新ファイルを自動検出して分析してください。

### 分析項目

以下の4項目をカバーする。各項目は `/collection-ideate` での企画立案と `/thumbnail` でのCTR最適化に直接活用されるため、断片的な分析では後続ステップの品質が下がる:

1. **CTR 改善戦略分析**: 高CTRコンテンツの特徴分析、サムネイル・タイトル最適化提案 — サムネイル制作の方向性決定に直結
2. **チャンネル特化パフォーマンス分析**: コレクション別比較、テーマ別パフォーマンス — 次期テーマ選定の根拠データ
3. **戦略的改善提案**: 上位動画の共通成功要因、直近投稿の動向分析、次期コレクション企画推奨 — `/collection-ideate` の入力データ
4. **具体的アクションプラン**: CTR 達成のための具体的施策 — 即実行可能なアクションに落とし込む

### pandas ベースの詳細分析 CLI (v1.3+)

静的な `analytics_data_*.json` だけでなく、以下の専門 CLI を積極的に活用すること。デフォルト出力は AI 消費向け JSON で、`--text` フラグで人間向けサマリーに切替:

- **`yt-launch-curve --latest`**: 新作動画の投稿後 N 日時点のパフォーマンスを、過去動画の同日齢ベンチマーク (p25/p50/p75) と比較。判定・`trace`・`all_videos` ランキングを返す。新作の初速評価や「過去の成功パターン vs 今の初速」の判断に必須。
- **`yt-channel-trend`**: 日次 views/subs の移動平均、週次集計、前週比、z-score ベースの異常検知 (spike/dip)、up/flat/down トレンド判定。直近の勢い判断・バズ日特定に使う。
- **`yt-theme-compare`**: `config/channel/content.json::tags.themes`（コードからは `load_config().content.tags.themes`）のキーワードでタイトル分類し、各テーマの平均 launch curve・ピーク日齢平均・初速最強/ロングテール最強テーマを返す。テーマ選定の根拠データ。
- **`yt-thumbnail-correlate --metric views`**: サムネ画像の特徴量 (brightness/contrast/saturation/dominant_hue/colorfulness) と CTR/views/engagement の Pearson 相関。CTR データ未提供時は `--metric views` / `engagement` にフォールバック。次回サムネ制作の方向性。

これらの出力 JSON をそのまま分析の根拠として引用し、「数値 (例: 中央値比 6.3倍)」を含む主張を行うこと。

### 分析品質基準

- 相関と因果の区別を明確にする
- 推奨事項に確信度を付記する
- データが不完全な場合は明示する
- 業界標準とチャンネル固有のベースラインを比較する

### 出力スタイル

- 具体的かつ実用的な改善策を含める
- データ可視化の概念を用いてトレンドを説明する

### レポート保存

分析結果は `reports/analysis_YYYYMMDD.md` に保存する（チャンネル横断レポート）。

このファイルは **`/collection-ideate` の前提必須入力**として読まれる。`/collection-ideate` Phase 1-2 で
以下のセクションが重視される（内容で認識、番号は目安）:

- **§ 5 戦略的改善提案** — CTR 改善・コンテンツ最適化の方向性
- **§ 6 推奨される次期コレクション候補** — データから導出されたテーマ候補
- **§ 8 戦略ディスカッション** — 長期視点の示唆

個別コレクションの振り返りメモが必要な場合は、`20-documentation/` に任意で
追記してよい（`/collection-ideate` の入力にはならない）。

## 障害時ガイダンス

分析は `data/` の収集済みスナップショットを読むため通常は外部 API を呼ばない。再収集が必要なときのみ以下が該当する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ不在 | `data/` のベンチマーク/Analytics スナップショットが無い | 先に `/benchmark`・`/analytics-collect` 等を実行して入力を用意 |
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |

## Next Step

分析完了後:
→ `/collection-ideate` でデータに基づくコレクション企画を生成

## 関連ファイル

- `data/video_analysis/<slug>/<video_id>.json` — `/video-analyze` の `scene_timeline` 出力（retention drop と動画展開のクロス参照に使う）
  - 冒頭クリップ窓（既定 900 秒、JSON の `analysis_window_sec`）内の分析結果。retention drop との照合では、窓外の全尺展開を推測しない。
