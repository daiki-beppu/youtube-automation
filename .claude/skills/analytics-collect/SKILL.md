---
name: analytics-collect
description: "Use when YouTube Analytics データの収集・最新化だけが必要なとき。「データ更新」「統計を取得」「分析の準備」で発動。収集済みデータの分析のみは /analytics-analyze、収集→分析→表示の一括実行は /analytics-run を使う"
---

## 前後工程

- `前工程`: `/setup`
- `後工程`: `/analytics-analyze`

## Overview

`analytics_system.py` を実行し、チャンネルの YouTube Analytics データを収集します。

## 完了条件

通常収集（standard / full / include-reporting）は、収集コマンドが exit 0 で終了し、`data/analytics_data_YYYYMMDD_HHMMSS.json` が新規保存された時点で完了。鮮度チェックで収集をスキップした場合は、既存データのファイル名と経過分数の表示で完了。成果物の depth 検証は `references/validate-depth.sh` を単一ソースとし、次が exit 0 になった場合だけ完了とする。

```bash
bash .claude/skills/analytics-collect/references/validate-depth.sh <analytics-json> <standard|full>
```

Reporting 管理サブモード（`--reporting-dry-run` / `--reporting-create-job`）は Analytics JSON を生成しないため depth 検証の対象外。

## Subagent 委譲ゲート

メインエージェントは設定読み込み、前提確認、鮮度チェック、ユーザーへの結果報告だけを担当する。YouTube Analytics API 呼び出し、Reporting API 確認、JSON ファイル生成は subagent へ委譲し、メイン会話には収集ログや `analytics_data_*.json` の中身を貼らない。

subagent へ渡す入力は、解決済みの実行モード、実行コマンド、期待成果物だけにする。subagent は `workflow-state.json` を読み書きせず、完了時に `status`、実行したコマンド、生成または再利用した成果物パス、スキップ理由だけを返す。メインエージェントは完了報告だけで成功扱いにせず、`data/analytics_data_*.json` の存在またはスキップ対象ファイル名を機械的に確認してから完了を報告する。

## 設定読み込みゲート

前提確認や鮮度チェックに入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/analytics-collect/config.default.yaml`
2. `config/skills/analytics-collect.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("analytics-collect")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合はここで停止し、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

`config/channel/` が `load_config()` でロード可能になるまで後続手順へ進まない。

## When to Use

- 分析の前にデータを最新化したいとき
- チャンネル統計・動画別パフォーマンスデータが必要なとき
- `/analytics-analyze` 実行前のデータ収集ステップとして

## Quick Reference

| 引数 | 説明 | 実行コマンド |
|------|------|------|
| `/analytics-collect` | デフォルト: standard（上位50本 + 直近30日投稿、CTR・流入元・デバイス） | `uv run yt-analytics` |
| `/analytics-collect full` | full（standard + retention・`by_country`） | `uv run yt-analytics --depth full` |
| `/analytics-collect reporting` | Reporting API の reportType / job 状態を確認し、必要なら job を作成 | `uv run yt-analytics --reporting-dry-run` → 必要なら `--reporting-create-job` |
| `$ARGUMENTS` | モード指定（省略可） | — |

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API v3（channels.list / videos.list ほか、1 unit/call） | 約 3 + ceil(動画数/50) units | チャンネルの動画数 |
| YouTube Analytics API（reports.query。Data API と別枠 quota） | standard で約 10 + 直近動画数 call | `--days` / `--all-time` の対象期間、動画数 |
| YouTube Analytics API（`--depth full` 追加分） | country / retention で最大 +11 call | full 指定時のみ |
| YouTube Reporting API（jobs 系、無料枠） | `--include-reporting` / `--reporting-*` 時のみ数 call | Reporting サブモードの利用有無 |

- 上限 / 承認: 鮮度チェック（既定 `freshness_minutes` = 30 分）以内の既存データがあれば収集をスキップし、`--depth` で取得深度を調整できる。Reporting job 作成は `--reporting-dry-run` で事前確認してから `--reporting-create-job` を実行する。

`yt-dashboard` の通常起動も registry の各チャンネルへこの standard 収集を 1 回ずつ実行するため、上表の call 数は登録チャンネル数に比例する。さらに公開予約ストック取得の YouTube Data API `videos.list(status)` がチャンネルごとに `ceil(全動画数/50)` call 加わる。OAuth のない E2E / 配布確認で `--skip-refresh` を指定した場合は、この起動時 API call は発生しない。

## 鮮度チェック（並列実行対応）

実行前に既存データの鮮度を確認する。しきい値は skill-config の `freshness_minutes`（既定 30 分）を使う:

1. `ls -t data/analytics_data_*.json 2>/dev/null | head -1` で最新ファイルを取得
2. ファイルの更新時刻が **`freshness_minutes` 分以内** → 収集をスキップし、既存データを使用。ただし `full` 指定時は、冒頭の「完了条件」を満たす既存 JSON だけを再利用する
3. `freshness_minutes` 分以上経過 or ファイルなし → 通常どおり下記コマンドを実行

`freshness_minutes` は `/analytics-analyze` の鮮度チェックとも共有される単一ソース（`config/skills/analytics-collect.yaml` の上書きが両スキルに効く）。

スキップ時: 「既存データが十分新しいため収集をスキップしました（`<filename>`、`<N>`分前に収集）」と表示。

## 実行コマンド

鮮度チェックで収集が必要と判断した場合、以下のコマンド実行は subagent へ委譲する。メインエージェントはコマンド出力の全文を会話へ展開せず、subagent の要約と成果物パスだけを受け取る。

```bash
uv run yt-analytics
```

視聴維持率と地域別データが必要な場合:

```bash
uv run yt-analytics --depth full
```

このモードでは保存後に冒頭の「完了条件」を機械的に確認する。

Reporting API の初回前提を確認する場合:

```bash
uv run yt-analytics --reporting-dry-run
uv run yt-analytics --reporting-create-job
```

作成直後は最初のレポート取得可能まで最大 48 時間かかる。既存 job と生成済みレポートがある場合は、必要に応じて次で CTR / impressions も取り込む:

```bash
uv run yt-analytics --include-reporting
```

### 委譲プロンプト要件

subagent へは次を具体値で渡す:

- 入力パス: `.claude/skills/analytics-collect/config.default.yaml`、存在する場合は `config/skills/analytics-collect.yaml`、`config/channel/`
- 実行する作業: standard は `uv run yt-analytics`、full は `uv run yt-analytics --depth full`、または Reporting API 確認用の `uv run yt-analytics --reporting-dry-run` / `uv run yt-analytics --reporting-create-job` / `uv run yt-analytics --include-reporting`
- 期待成果物: `data/analytics_data_YYYYMMDD_HHMMSS.json`（通常収集時）、または鮮度チェックで再利用する既存 `data/analytics_data_*.json`
- 完了報告: `status: success | failure`、`command`、`artifacts`（`path` は絶対パス、`result` は depth validator の結果）、`skipped_reason`、`errors`

## 出力

- チャンネル統計データ
- 動画別パフォーマンス分析
- 視聴数上位 200 件のプレイリスト別 views・平均視聴時間・上位 200 件内の視聴シェア
- 戦略的分析結果
- JSON データファイル保存（`data/` ディレクトリ）

### 出力例

```
📊 YouTube Analytics データ収集
チャンネル: <config/channel/meta.json の channel.name>
期間: YYYY-MM-DD 〜 YYYY-MM-DD

✅ チャンネル統計: 登録者 X / 総再生 Y
✅ 動画パフォーマンス: 上位50本 + 直近30日投稿を収集
✅ データ保存: data/analytics_data_YYYYMMDD_HHMMSS.json
```

データ収集完了後、`/analytics-analyze` で詳細分析を実行してください。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| OAuth 未認証/失効 | `infrastructure.auth.youtube` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |
| Reporting API 未有効 | `--reporting-dry-run` / `--reporting-create-job` で `youtubereporting.googleapis.com` 関連の 403 | `/setup` に戻り、必須 API 有効化と OAuth scope を確認する |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota（既定 10,000 units・太平洋時間 0 時リセット）を待つか呼び出しを抑える |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud / YouTube のステータスを確認し、時間を置いて再実行 |

## Next Step

### 収益メトリクス

`yt-analytics` は基本メトリクスとは別クエリで
`estimatedRevenue` / `monetizedPlaybacks` / `cpm` / `playbackBasedCpm` を収集する。
成果物では `revenue_analytics.daily_metrics` と `revenue_analytics.by_video` に保存し、
各行の `rpm` は `estimated_revenue / views * 1000` で算出する。

収益化未承認または monetary data へのアクセス不可の場合は、警告ログを出して
`revenue_analytics.status: "unavailable"` と空の収益データを保存する。これは許容する fail であり、
views / CTR / retention など既存メトリクスの収集は継続する。

データ収集完了後:
- `/analytics-analyze` で収集データの詳細分析を実行
