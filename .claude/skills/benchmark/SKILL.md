---
name: benchmark
description: Use when 競合チャンネルのベンチマークデータを最新化したいとき。YouTube Data API (OAuth) で競合の最新動画データを取得し docs/benchmarks/*.md を更新する。「競合分析」「ベンチマーク更新」「競合の最新データ」など、競合情報の取得・更新に関わる場面で使用すること
---

## Overview

`benchmark_collector.py` で競合チャンネルの最新データを収集し、`docs/benchmarks/*.md` を自動更新する。
`/ideate` の Phase 1-2 から自動呼び出しされるが、単独実行も可能。

## 取得データ（拡充版）

| 基本データ (YouTube API) | 派生指標 (自動算出) | サムネイル分析 (Gemini) |
|---|---|---|
| 再生数・高評価・コメント数 | 日次再生数 (views/日数) | 構図・配色 |
| タイトル・タグ・説明文 | エンゲージメント率 (ER%) | テキスト配置 |
| 尺・公開日・サムネイルURL | 投稿間隔トレンド | キャラ活動・雰囲気 |

## 実行フロー

### Step 1: スクリプト実行

```bash
# チャンネルディレクトリから実行（鮮度チェック → 古いもののみ更新）
uv run yt-benchmark-collect

# オプション
uv run yt-benchmark-collect --force            # 全チャンネル強制更新
uv run yt-benchmark-collect --no-thumbnails    # サムネイル分析スキップ（高速）
uv run yt-benchmark-collect --keep-thumbnails  # サムネイル画像を保持
uv run yt-benchmark-collect --json-only        # JSON のみ（Markdown スキップ）
uv run yt-benchmark-collect --channel <slug>   # 単一チャンネル指定
uv run yt-benchmark-collect -v                 # 詳細ログ
```

スクリプトが自動で以下を実行:
1. `channel_config.json` の `benchmark.channels` から対象チャンネルを読み込み
2. `docs/benchmarks/*.md` の更新日時で鮮度チェック（`freshness_days` 日以上前なら更新）
3. YouTube Data API で最新動画データ取得（再生数・高評価・コメント・タグ・説明文等）
4. 派生指標算出（日次再生数・ER%・投稿間隔トレンド）
5. サムネイルDL → Gemini API で構図・配色・テキスト配置を分析
6. `data/benchmark_YYYYMMDD.json` に中間データ保存
7. `docs/benchmarks/*.md`（個別 + common-patterns + README）を自動生成

### Step 2: 結果確認・戦略的評価

スクリプト完了後、Claude が以下を実施:

1. 生成された `docs/benchmarks/*.md` を Read ツールで確認
2. 高パフォーマンス動画のパターンを分析
3. `common-patterns.md` の戦略的示唆を 自チャンネル向けに再評価
4. 結果サマリーをユーザーに報告

## 新規競合チャンネル追加

1. `config/channel_config.json` の `benchmark.channels` 配列に追加:
   ```json
   {
     "id": "UC_NEW_CHANNEL_ID",
     "slug": "channel-slug",
     "name": "Channel Name",
     "relationship": "自チャンネルとの関係性"
   }
   ```
2. スクリプトを `--force` で実行 → ファイル自動生成

## 設定（channel_config.json）

```json
"benchmark": {
  "channels": [...],
  "max_videos": 10,
  "freshness_days": 3,
  "analyze_thumbnails": true
}
```

## 注意事項

- OAuth 認証は `auth/token.json` を使用
- YouTube API: 1チャンネルあたり約 30 ユニット（10,000/日の上限に余裕）
- Gemini サムネイル分析: 5秒間隔でレート制限回避（`--no-thumbnails` でスキップ可）
- `common-patterns.md` の手書きパターン分析は「運用ベンチマーク」セクションより上に維持される
