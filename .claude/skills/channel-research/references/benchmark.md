## Overview

`benchmark_collector.py` で競合チャンネルの**直近投稿のうち再生数しきい値（既定 10,000）以上**の動画だけを収集し、収集 JSON から検証済み benchmark report JSON+HTML を更新する。
チャンネル単位ではなく**動画単位**でベンチマーク対象を抽出する（伸びていない動画は分析から除外）。
`/wf-new` 企画工程の Phase 1-2 から自動呼び出しされるが、単独実行も可能。

## 完了条件

Step 1 のスクリプトが exit 0 で終了して `data/benchmark_YYYYMMDD.json` が更新され、Step 2 の分析を `docs/benchmarks/benchmark-report.json` + `.html` へ共通 workflow で公開し、Step 3 の結果サマリー報告を終えた時点で完了。

## Subagent 委譲ゲート

メインエージェントは設定読み込み、前提確認、必要なユーザー承認、成果物 pair 確認、結果サマリー報告だけを担当する。YouTube Data API 呼び出し、`data/benchmark_YYYYMMDD.json` 生成、サムネイル画像の読み込み、candidate JSON の生成と共通 migration workflow の実行は subagent へ委譲する。

メインエージェントは `data/benchmark_*.json`、検証済み benchmark report JSON、`docs/benchmarks/thumbnails/*` の中身を直接 Read しない。subagent は成果物パス、更新件数、主要パターンの要約だけを返し、生 JSON や画像分析の中間メモをメイン会話へ貼らない。下流入力は `references/structured-report.md` の pair 検証を通した JSON に限る。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/channel-research/config.default.yaml`
2. `config/skills/benchmark.yaml`（存在する場合）

合成規則は `youtube_automation.configuration.skills.load_skill_config("benchmark")` と同じで、チャンネル上書きが優先される。存在しない override は未設定として扱い、勝手に作成しない。

## 前提成果物ガード

後続 Step に入る前に、以下の前提を確認する。**停止する fail** が 1 件でもあれば、記載した前工程スキルを案内して停止し、解消するまで後続 Step に進まない。**許容する fail** は停止条件に含めない。

### 停止する fail

- `config/channel/` が存在しない、または `load_config()` でロードできない → 新規チャンネルは `/setup --channel` Step 4、既存チャンネルは `/setup --import` を案内して停止する
- `config/channel/analytics.json::benchmark.channels` に承認済みベンチマークチャンネルが設定されていない → `/setup --channel` Step 5（`.claude/skills/setup/references/ttp-seed-and-duration.md`）/ `/channel-research --discover` を案内して停止する
- `auth/token.json` が存在しない、または OAuth 認証が無効 → `/setup` を案内して停止する

### 許容する fail

- `config/skills/benchmark.yaml` が無い → `.claude/skills/channel-research/config.default.yaml` を使うため停止しない
- `data/benchmark_*.json` / `docs/benchmarks/benchmark-report.json` が無い → 本スキルで生成するため停止しない

## 取得データ（拡充版）

| 基本データ (YouTube API) | 派生指標 (自動算出) | サムネイル分析 (エージェント) |
|---|---|---|
| 再生数・高評価・コメント数 | 日次再生数 (views/日数) | 構図・配色 |
| タイトル・タグ・説明文 | エンゲージメント率 (ER%) | テキスト配置 |
| 尺・公開日・サムネイルURL | 投稿間隔トレンド | キャラ活動・雰囲気 |

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API v3（channels.list、1 unit/call） | ceil(チャンネル数/50) units | ベンチマークチャンネル数 |
| YouTube Data API v3（playlistItems.list + videos.list、各 1 unit） | 鮮度切れチャンネルごとに `2 × ceil(scan_recent / 50)` units | 鮮度切れチャンネル数、`scan_recent`（既定 150） |
| Vertex AI Gemini（サムネイル分析） | 既定 OFF で 0。有効時はサムネイル枚数分 | `gemini_thumbnail_analysis: true` の場合のみ |

- 上限 / 承認: `freshness_days` 以内のチャンネルは再収集せず、サムネイル DL は CDN 直取得で quota を消費しない。`-y` / `--force` なしの実行では収集前に `[Y/n]` 確認プロンプトで停止する。
- 通常収集の上限式は `ceil(更新チャンネル数 / 50) + 更新チャンネル数 × 2 × ceil(scan_recent / 50)`。先頭項は共有の `channels.list`、後半は各チャンネルの `playlistItems.list` と `videos.list`。1 チャンネルなら `scan_recent: 50` で最大 3 units、既定 150 で最大 7 units（投稿総数が少ない場合は早期終了して減る）。

## 実行フロー

### Step 1: データ収集

以下のコマンド実行は subagent へ委譲する。subagent は CLI の実行結果、更新された `data/benchmark_YYYYMMDD.json`、公開した benchmark report pair のパスを完了報告に含める。

```bash
# チャンネルディレクトリから実行（鮮度チェック → 古いもののみ更新）
uv run yt-benchmark-collect --json-only -y

# オプション
uv run yt-benchmark-collect --json-only --force -y # 全チャンネル強制更新
uv run yt-benchmark-collect --no-thumbnails  # サムネイルDLスキップ（高速）
uv run yt-benchmark-collect --json-only      # JSON のみ（Markdown スキップ）
uv run yt-benchmark-collect --competitor <slug> # 単一競合指定
uv run yt-benchmark-collect -v               # 詳細ログ
```

スクリプトが自動で以下を実行:
1. `config/channel/analytics.json` の `benchmark.channels` から対象チャンネルを読み込み
2. 検証済み `docs/benchmarks/benchmark-report.json` + `.html` の古い方の更新日時で鮮度チェック（`freshness_days` 日以上前なら更新）
3. YouTube Data API で**直近 `scan_recent` 本（既定 150）** を走査し、**`min_views` 以上（既定 10,000）** の動画だけを抽出
4. 派生指標算出（日次再生数・ER%・投稿間隔トレンド）
5. サムネイル画像を `docs/benchmarks/thumbnails/` にダウンロード
6. `data/benchmark_YYYYMMDD.json` に中間データ保存
7. subagent が収集 JSON と画像分析から `channel-research-report.schema.json` 準拠の candidate を作り、`references/structured-report.md` の共通 workflow で `docs/benchmarks/benchmark-report.json` + `.html` を公開する
   - 競合比較、共通パターン、個別根拠を一つの構造化レポートへ統合する
   - 既存 `docs/benchmarks/benchmark-report.md` がある場合は明示 yes/no gate を通し、pair 再読込成功後だけ削除する
   - 該当動画が 0 件のチャンネルも比較行に残し、0 件である根拠を記録する

### Step 2: サムネイル分析（subagent）

スクリプト完了後、subagent が以下を実施:

1. 各チャンネルのレポート（`docs/benchmarks/{slug}.md`）を読み、再生数上位 5 本の動画を特定
2. 該当動画のサムネイル画像を `docs/benchmarks/thumbnails/{slug}_{video_id}.jpg` から Read（Codex では同等の画像閲覧機能）で読み込み
3. 各サムネイルを以下の観点で分析:
   - **構図**: レイアウト・焦点・キャラクター配置
   - **配色**: 支配色・全体のムード/トーン
   - **テキスト配置**: タイトルテキストの位置・スタイル
   - **キャラ活動**: キャラクターの動作（いなければ 'none'）
   - **雰囲気**: 全体のムード・ライティング・環境効果
   - **強み**: 効果的な要素のリスト
4. 分析結果を benchmark report candidate の `evidence`、`winning_patterns`、`application_candidates` へ evidence ID で接続する

### Step 3: 結果確認・戦略的評価

1. メインエージェントは `docs/benchmarks/benchmark-report.json` + `.html` と `data/benchmark_YYYYMMDD.json` の存在を確認
2. subagent から受け取った高パフォーマンス動画パターン、勝ちパターン、自チャンネル向け適用候補の要約を確認
3. 結果サマリーをユーザーに報告

### 委譲プロンプト要件

subagent へは次を具体値で渡す:

- 入力パス: `.claude/skills/channel-research/config.default.yaml`、存在する場合は `config/skills/benchmark.yaml`、`config/channel/analytics.json`
- 実行する作業: `uv run yt-benchmark-collect -y` と、必要なサムネイル分析追記
- 期待成果物: `data/benchmark_YYYYMMDD.json`、`docs/benchmarks/benchmark-report.json` + `.html`、必要に応じて `docs/benchmarks/thumbnails/{slug}_{video_id}.jpg`
- 完了報告: `status: success | failure`、`commands`、`artifacts`、`updated_reports`、`summary`、`errors`

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

走査・分析の動作パラメータは skill-config (`.claude/skills/channel-research/config.default.yaml`) で管理。
チャンネル側で上書きする場合は `config/skills/benchmark.yaml`:

| 項目 | 既定 | 説明 |
|---|---|---|
| `scan_recent` | 150 | チャンネルあたりの走査プール本数（直近 N 投稿、50 本単位で API call が増加） |
| `min_views` | 10000 | ベンチマーク対象の視聴数しきい値 |
| `freshness_days` | 3 | レポート更新間隔（日） |
| `gemini_thumbnail_analysis` | false | Gemini API によるサムネイル分析（Vertex AI 課金あり、通常は不要） |
| `thumbnail_analysis.model` | gemini-2.5-flash | Gemini 分析モデル（`gemini_thumbnail_analysis: true` 時のみ） |
| `thumbnail_analysis.delay_sec` | 5 | API レート制限対策の待機秒数 |
| `thumbnail_analysis.prompt` | 汎用プロンプト | ジャンル/世界観に合わせて上書き推奨 |

## コストに関する注意

- **YouTube Data API**: 無料枠内（10,000 units/day）。通常収集は上記ページング式で、1 チャンネルなら既定 150 本で最大 7 units
- **サムネイル分析**: デフォルトではエージェントが実行（追加コストなし）
- **Gemini サムネイル分析** (`gemini_thumbnail_analysis: true`): Vertex AI 課金が発生する。10チャンネル × 各 20 本 = 200 回の API 呼び出しで数千円になる可能性があるため、通常は OFF のままにすること

## 注意事項

- OAuth 認証は `auth/token.json` を使用
- 旧 `docs/benchmarks/*.md` は直接更新しない。移行対象は同 basename の `benchmark-report.md` に集約したうえで明示承認 gate を通す

## 関連ファイル

- `data/video_analysis/<slug>/<video_id>.json` — `/audit --video` の動画本体スコアリング出力（競合スコアリングの追加入力）
