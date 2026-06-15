---
name: benchmark
description: "Use when 競合チャンネルのベンチマークデータを最新化したいとき。YouTube Data API (OAuth) で競合の最新動画データを取得し docs/benchmarks/*.md を更新する。「競合分析」「ベンチマーク更新」「競合の最新データ」など、競合情報の取得・更新に関わる場面で使用すること"
---

## Overview

`benchmark_collector.py` で競合チャンネルの**直近投稿のうち再生数しきい値（既定 10,000）以上**の動画だけを収集し、`docs/benchmarks/*.md` を自動更新する。
チャンネル単位ではなく**動画単位**でベンチマーク対象を抽出する（伸びていない動画は分析から除外）。
`/collection-ideate` の Phase 1-2 から自動呼び出しされるが、単独実行も可能。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## 取得データ（拡充版）

| 基本データ (YouTube API) | 派生指標 (自動算出) | サムネイル分析 (エージェント) |
|---|---|---|
| 再生数・高評価・コメント数 | 日次再生数 (views/日数) | 構図・配色 |
| タイトル・タグ・説明文 | エンゲージメント率 (ER%) | テキスト配置 |
| 尺・公開日・サムネイルURL | 投稿間隔トレンド | キャラ活動・雰囲気 |

## 実行フロー

### Step 1: データ収集

```bash
# チャンネルディレクトリから実行（鮮度チェック → 古いもののみ更新）
uv run yt-benchmark-collect -y

# オプション
uv run yt-benchmark-collect --force -y       # 全チャンネル強制更新
uv run yt-benchmark-collect --no-thumbnails  # サムネイルDLスキップ（高速）
uv run yt-benchmark-collect --json-only      # JSON のみ（Markdown スキップ）
uv run yt-benchmark-collect --channel <slug> # 単一チャンネル指定
uv run yt-benchmark-collect -v               # 詳細ログ
```

スクリプトが自動で以下を実行:
1. `config/channel/analytics.json` の `benchmark.channels` から対象チャンネルを読み込み
2. `docs/benchmarks/*.md` の更新日時で鮮度チェック（`freshness_days` 日以上前なら更新）
3. YouTube Data API で**直近 `scan_recent` 本（既定 50）** を走査し、**`min_views` 以上（既定 10,000）** の動画だけを抽出
4. 派生指標算出（日次再生数・ER%・投稿間隔トレンド）
5. サムネイル画像を `docs/benchmarks/thumbnails/` にダウンロード
6. `data/benchmark_YYYYMMDD.json` に中間データ保存
7. `docs/benchmarks/*.md`（個別 + common-patterns + README）を自動生成
   - 該当動画が 0 件のチャンネルは「該当動画なし」注記付きの空レポートになる

### Step 2: サムネイル分析（エージェント）

スクリプト完了後、エージェントが以下を実施:

1. 各チャンネルのレポート（`docs/benchmarks/{slug}.md`）を読み、再生数上位 5 本の動画を特定
2. 該当動画のサムネイル画像を `docs/benchmarks/thumbnails/{slug}_{video_id}.jpg` から Read ツールで読み込み
3. 各サムネイルを以下の観点で分析:
   - **構図**: レイアウト・焦点・キャラクター配置
   - **配色**: 支配色・全体のムード/トーン
   - **テキスト配置**: タイトルテキストの位置・スタイル
   - **キャラ活動**: キャラクターの動作（いなければ 'none'）
   - **雰囲気**: 全体のムード・ライティング・環境効果
   - **強み**: 効果的な要素のリスト
4. 分析結果を `docs/benchmarks/{slug}.md` の末尾に `## サムネイル分析` セクションとして追記

### Step 3: 結果確認・戦略的評価

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
| `gemini_thumbnail_analysis` | false | Gemini API によるサムネイル分析（Vertex AI 課金あり、通常は不要） |
| `thumbnail_analysis.model` | gemini-2.5-flash | Gemini 分析モデル（`gemini_thumbnail_analysis: true` 時のみ） |
| `thumbnail_analysis.delay_sec` | 5 | API レート制限対策の待機秒数 |
| `thumbnail_analysis.prompt` | 汎用プロンプト | ジャンル/世界観に合わせて上書き推奨 |

## コストに関する注意

- **YouTube Data API**: 無料枠内（10,000 units/day）。1チャンネルあたり約 4 ユニット
- **サムネイル分析**: デフォルトではエージェントが実行（追加コストなし）
- **Gemini サムネイル分析** (`gemini_thumbnail_analysis: true`): Vertex AI 課金が発生する。10チャンネル × 各 20 本 = 200 回の API 呼び出しで数千円になる可能性があるため、通常は OFF のままにすること

## 注意事項

- OAuth 認証は `auth/token.json` を使用
- `common-patterns.md` の手書きパターン分析は「運用ベンチマーク」セクションより上に維持される

## 関連ファイル

- `data/video_analysis/<slug>/<video_id>.json` — `/video-analyze` の動画本体スコアリング出力（競合スコアリングの追加入力）
