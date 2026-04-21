---
name: benchmark
description: Use when 競合チャンネルのベンチマークデータを最新化したいとき。YouTube Data API (OAuth) で競合の最新動画データを取得し docs/benchmarks/*.md を更新する。「競合分析」「ベンチマーク更新」「競合の最新データ」など、競合情報の取得・更新に関わる場面で使用すること
---

## Overview

`benchmark_collector.py` で競合チャンネルの**直近投稿のうち再生数しきい値（既定 10,000）以上**の動画だけを収集し、`docs/benchmarks/*.md` を自動更新する。
チャンネル単位ではなく**動画単位**でベンチマーク対象を抽出する（伸びていない動画は分析から除外）。
`/ideate` の Phase 1-2 から自動呼び出しされるが、単独実行も可能。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

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
1. `config/channel/analytics.json` の `benchmark.channels` から対象チャンネルを読み込み
2. `docs/benchmarks/*.md` の更新日時で鮮度チェック（`freshness_days` 日以上前なら更新）
3. YouTube Data API で**直近 `scan_recent` 本（既定 50）** を走査し、**`min_views` 以上（既定 10,000）** の動画だけを抽出
4. 派生指標算出（日次再生数・ER%・投稿間隔トレンド）
5. サムネイルDL → Gemini API で構図・配色・テキスト配置を分析
6. `data/benchmark_YYYYMMDD.json` に中間データ保存
7. `docs/benchmarks/*.md`（個別 + common-patterns + README）を自動生成
   - 該当動画が 0 件のチャンネルは「該当動画なし」注記付きの空レポートになる

### Step 2: 結果確認・戦略的評価

スクリプト完了後、Claude が以下を実施:

1. 生成された `docs/benchmarks/*.md` を Read ツールで確認
2. 高パフォーマンス動画のパターンを分析
3. `common-patterns.md` の戦略的示唆を 自チャンネル向けに再評価
4. 結果サマリーをユーザーに報告

## 新規競合チャンネル追加

1. `config/channel/analytics.json` の `benchmark.channels` 配列に追加:
   ```json
   {
     "id": "UC_NEW_CHANNEL_ID",
     "slug": "channel-slug",
     "name": "Channel Name",
     "relationship": "自チャンネルとの関係性"
   }
   ```
2. スクリプトを `--force` で実行 → ファイル自動生成

## 設定

競合チャンネルリストは `config/channel/analytics.json` で管理する:

```json
"benchmark": {
  "channels": [
    {"id": "UC_XXX", "slug": "channel-slug", "name": "Channel Name", "relationship": "..."}
  ]
}
```

走査・分析の動作パラメータは skill-config (`.claude/skills/benchmark/config.default.yaml`) で管理。
チャンネル側で上書きする場合は `config/skills/benchmark.yaml`:

| 項目 | 既定 | 説明 |
|---|---|---|
| `scan_recent` | 50 | チャンネルあたりの走査プール本数（直近 N 投稿） |
| `min_views` | 10000 | ベンチマーク対象の視聴数しきい値 |
| `freshness_days` | 3 | レポート更新間隔（日） |
| `analyze_thumbnails` | true | Gemini によるサムネイル分析を実行するか |
| `thumbnail_analysis.model` | gemini-2.5-flash | サムネイル分析モデル |
| `thumbnail_analysis.delay_sec` | 5 | API レート制限対策の待機秒数 |
| `thumbnail_analysis.prompt` | 汎用プロンプト | ジャンル/世界観に合わせて上書き推奨 |

## 注意事項

- OAuth 認証は `auth/token.json` を使用
- YouTube API: 1チャンネルあたり約 4 ユニット（channels 1 + playlistItems 1 + videos 約 2）
- Gemini サムネイル分析: 5秒間隔でレート制限回避（`--no-thumbnails` でスキップ可）
- `common-patterns.md` の手書きパターン分析は「運用ベンチマーク」セクションより上に維持される
