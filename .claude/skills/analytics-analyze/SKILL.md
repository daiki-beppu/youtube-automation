---
name: analytics-analyze
description: "Use when 収集済み Analytics データの分析と戦略提案が必要なとき。「パフォーマンス分析」「戦略検討」「振り返り」で発動。/analytics-collect の後工程"
---

## Overview

収集済みの YouTube Analytics データを詳細分析し、データドリブンな改善提案を行います。

## 完了条件

「分析項目」の 4 項目をカバーした分析結果を `reports/analysis_YYYYMMDD.md` に保存し、ユーザーに要約提示した時点で完了。鮮度チェックで分析をスキップした場合は、既存レポートの成果物パスと要約提示で完了。

## Subagent 委譲ゲート

メインエージェントは前提確認、鮮度チェック、対象ファイルの選定、成果物存在確認、ユーザーへの短い報告だけを担当する。`data/analytics_data_*.json`、専門 CLI の JSON 出力、`data/video_analysis/` の詳細 JSON はメイン会話で直接 Read せず、分析 subagent へ入力パスとして渡す。

分析 subagent は指定された入力パスを読み、必要な専門 CLI を実行し、分析結果を `reports/analysis_YYYYMMDD.md` に保存する。完了報告では `status`、読んだ入力パス、実行した CLI、生成または再利用したレポートパス、主要発見の要約だけを返し、生データ本文や CLI JSON 全文を返さない。メインエージェントは `reports/analysis_*.md` の存在と更新対象を機械的に確認してから完了を報告する。

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

しきい値は `/analytics-collect` の skill-config が単一ソース。まず以下を Read（Codex では同等のファイル閲覧）で開き、`freshness_minutes`（既定 30 分）を確定する:

1. `.claude/skills/analytics-collect/config.default.yaml`
2. `config/skills/analytics-collect.yaml`（存在する場合。deep-merge でチャンネル上書きを優先）

分析実行前に `reports/` 配下の最新レポートを確認する:
- `freshness_minutes` 分以内に生成されたレポートがあれば分析をスキップし、その内容を使用
- スキップ時: 「既存レポートが十分新しいため分析をスキップしました（`<filename>`、`<N>`分前に生成）」と表示

### 対象データ

```
$ARGUMENTS
```

引数が指定されている場合はそのファイルを、未指定の場合は `data/analytics_data_*.json` のうち更新時刻が最新のファイル（`ls -t data/analytics_data_*.json | head -1` で取得できるもの）を対象データとして subagent に渡す。メインエージェントは対象ファイルの中身を直接 Read しない。

### 分析委譲プロンプト要件

subagent へは次を具体値で渡す:

- 入力パス: 対象の `data/analytics_data_*.json`、`config/channel/content.json`、存在する場合は `data/video_analysis/<slug>/<video_id>.json`
- 実行する作業: 「分析項目」の 4 項目をカバーする分析、必要に応じた `yt-launch-curve --latest` / `yt-channel-trend` / `yt-theme-compare` / `yt-thumbnail-correlate --metric views`
- 期待成果物: `reports/analysis_YYYYMMDD.md`
- 完了報告: `status: success | failure`、`inputs`、`commands`、`artifacts`、`summary`、`errors`

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

subagent はこれらの出力 JSON を分析の根拠として使い、「数値 (例: 中央値比 6.3倍)」を含む主張を行うこと。ただしメインエージェントへ返す完了報告には JSON 全文を含めず、レポートパスと主要数値の要約に絞る。

### 分析品質基準

- 相関と因果の区別を明確にする
- 推奨事項に確信度を付記する
- データが不完全な場合は明示する
- 業界標準とチャンネル固有のベースラインを比較する

### 出力スタイル

- 具体的かつ実用的な改善策を含める
- データ可視化の概念を用いてトレンドを説明する

### レポート保存

subagent は分析結果を `reports/analysis_YYYYMMDD.md` に保存する（チャンネル横断レポート）。メインエージェントは保存後にファイル存在だけを確認し、レポート本文の全文を会話へ展開しない。

このファイルは **`/collection-ideate` の前提必須入力**として読まれる。`/collection-ideate` Phase 1-2 で
以下のセクションが重視される（内容で認識、番号は目安）:

- **§ 5 戦略的改善提案** — CTR 改善・コンテンツ最適化の方向性
- **§ 6 推奨される次期コレクション候補** — データから導出されたテーマ候補
- **§ 8 戦略ディスカッション** — 長期視点の示唆

個別コレクションの振り返りメモが必要な場合は、`20-documentation/` に任意で
追記してよい（`/collection-ideate` の入力にはならない）。

## 障害時ガイダンス

分析 subagent は `data/` の収集済みスナップショットを読むため通常は外部 API を呼ばない。再収集が必要なときのみ以下が該当する。

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
