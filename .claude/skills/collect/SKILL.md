---
name: collect
description: Use when YouTube Analyticsデータの収集・最新化が必要なとき。/analyze 実行前のデータ準備ステップとして使用。ユーザーが「データ更新」「最新の数字」「統計を取得」「分析の準備」と言及したとき、または analytics_system.py の実行が必要な場面で必ず使用すること
---

## Overview

`analytics_system.py` を実行し、チャンネルの YouTube Analytics データを収集します。

## When to Use

- 分析の前にデータを最新化したいとき
- チャンネル統計・動画別パフォーマンスデータが必要なとき
- `/analyze` 実行前のデータ収集ステップとして

## Quick Reference

| 引数 | 説明 |
|------|------|
| `/collect` | デフォルト: 効率モード（上位50本 + 直近30日投稿） |
| `$ARGUMENTS` | モード指定（省略可） |

## 鮮度チェック（並列実行対応）

実行前に既存データの鮮度を確認する:

1. `ls -t automation/data/analytics_data_*.json 2>/dev/null | head -1` で最新ファイルを取得
2. ファイルの更新時刻が **30分以内** → 収集をスキップし、既存データを使用
3. 30分以上経過 or ファイルなし → 通常どおり下記コマンドを実行

スキップ時: 「既存データが十分新しいため収集をスキップしました（`<filename>`、`<N>`分前に収集）」と表示。

## 実行コマンド

```bash
python3 automation/analytics_system.py
```

## 出力

- チャンネル統計データ
- 動画別パフォーマンス分析
- 戦略的分析結果
- JSON データファイル保存（`data/` ディレクトリ）

### 出力例

```
📊 YouTube Analytics データ収集
チャンネル: <channel_config: channel.name>
期間: YYYY-MM-DD 〜 YYYY-MM-DD

✅ チャンネル統計: 登録者 X / 総再生 Y
✅ 動画パフォーマンス: 上位50本 + 直近30日投稿を収集
✅ データ保存: data/analytics_YYYYMMDD.json
```

データ収集完了後、`/analyze` で詳細分析を実行してください。

## Next Step

データ収集完了後:
→ `/analyze` で収集データの詳細分析を実行
