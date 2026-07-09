---
name: analytics-collect
description: "Use when YouTube Analytics データの収集・最新化が必要なとき。「データ更新」「統計を取得」「分析の準備」で発動。/analytics-analyze の前段"
---

## Overview

`analytics_system.py` を実行し、チャンネルの YouTube Analytics データを収集します。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## When to Use

- 分析の前にデータを最新化したいとき
- チャンネル統計・動画別パフォーマンスデータが必要なとき
- `/analytics-analyze` 実行前のデータ収集ステップとして

## Quick Reference

| 引数 | 説明 |
|------|------|
| `/analytics-collect` | デフォルト: 効率モード（上位50本 + 直近30日投稿） |
| `/analytics-collect reporting` | Reporting API の reportType / job 状態を確認し、必要なら job を作成 |
| `$ARGUMENTS` | モード指定（省略可） |

## 鮮度チェック（並列実行対応）

実行前に既存データの鮮度を確認する:

1. `ls -t data/analytics_data_*.json 2>/dev/null | head -1` で最新ファイルを取得
2. ファイルの更新時刻が **30分以内** → 収集をスキップし、既存データを使用
3. 30分以上経過 or ファイルなし → 通常どおり下記コマンドを実行

スキップ時: 「既存データが十分新しいため収集をスキップしました（`<filename>`、`<N>`分前に収集）」と表示。

## 実行コマンド

```bash
uv run yt-analytics
```

Reporting API の初回前提を確認する場合:

```bash
uv run yt-analytics --reporting-dry-run
uv run yt-analytics --reporting-create-job
```

作成直後は最初のレポート取得可能まで最大 48 時間かかる。既存 job と生成済みレポートがある場合は、必要に応じて次で CTR / impressions も取り込む:

```bash
uv run yt-analytics --include-reporting
```

## 出力

- チャンネル統計データ
- 動画別パフォーマンス分析
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
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |
| Reporting API 未有効 | `--reporting-dry-run` / `--reporting-create-job` で `youtubereporting.googleapis.com` 関連の 403 | `/setup` に戻り、必須 API 有効化と OAuth scope を確認する |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota（既定 10,000 units・太平洋時間 0 時リセット）を待つか呼び出しを抑える |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud / YouTube のステータスを確認し、時間を置いて再実行 |

## Next Step

データ収集完了後:
→ `/analytics-analyze` で収集データの詳細分析を実行
