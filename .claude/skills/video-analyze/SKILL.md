---
name: video-analyze
description: Use when 動画コンテンツ分析・映像解析が必要なとき。Gemini に YouTube URL を直接渡してフック構造・BGM 展開・シーンタイムライン・サムネ整合性・編集指標を抽出する。「signature 要素抽出」「retention drop の構造的原因」「競合動画の冒頭 30 秒解析」「BGM のピーク位置」など、メタデータ・コメント・静止画では届かない動画本体の中身に切り込みたい場面で使用すること
---

## Overview

`yt-video-analyze` で YouTube 動画を Gemini に直接渡し、以下の構造化データを抽出する:

- `hook_structure` — 0-30 秒のカット割り・テキスト出現タイミング・signature 要素
- `bgm_arc` — イントロ尺・ピーク位置・アウトロのタイムスタンプ
- `scene_timeline` — シーン境界 + 一言要約
- `thumbnail_alignment` — サムネで提示した要素が本編に映っているかの整合性
- `editing_metrics` — 平均カット長・テキスト出現頻度

既存スキルが扱えていなかった「動画の中身」というドメインを埋め、`/benchmark`・`/analytics-analyze`・`/alignment-check`・`/thumbnail-compare`・`/viewer-voice` の精度を底上げする。

## 前提

- `config/channel/` がロード可能であること (`load_config()`)
- `GOOGLE_CLOUD_PROJECT` 設定済み + `gcloud auth application-default login` 済み (Vertex AI ADC)
- 解析対象動画が **Public または Unlisted** であること (Gemini API は Private 動画を取得できない)

## 実行フロー

### Step 1: スクリプト実行

```bash
# ベンチマーク競合の上位動画を解析
uv run yt-video-analyze --source benchmark --channel <slug> --top 5

# 自チャンネル live コレクションを解析
uv run yt-video-analyze --source own --collection <name>

# 単発動画 (任意 URL)
uv run yt-video-analyze --url <youtube_url>
```

| オプション | 説明 |
|---|---|
| `--source benchmark` | `data/benchmark_*.json` から `--channel` slug でフィルタし `--top` 件 (default 5) を解析 |
| `--source own` | `collections/live/<name>/20-documentation/upload_tracking.json` の `complete_collection.video_id` (および `videos[]`) を解析 |
| `--url` | 任意 YouTube URL を直接解析 (slug は固定 `url`) |

### Step 2: 出力確認

| 出力先 | 用途 |
|---|---|
| `data/video_analysis/<slug>/<video_id>.json` | 構造化データ (1 動画 1 ファイル) |
| `reports/video_analysis/<slug>.md` | 人間向けサマリー (slug 単位で集約) |

## 設定

skill-config (`.claude/skills/video-analyze/config.default.yaml`):

| 項目 | 既定 | 説明 |
|---|---|---|
| `model` | `gemini-2.5-flash` | 動画入力対応 Gemini モデル |
| `delay_sec` | 10 | 動画間の API レート対策ウェイト (秒) |
| `prompt` | 汎用プロンプト | ジャンル/世界観に合わせて `config/skills/video-analyze.yaml` で上書き推奨 |

## 注意事項

- Gemini API には YouTube URL を直接渡す (動画ダウンロードしない)
- Public/Unlisted のみ対応 (Private 動画は API 側で拒否される)
- Shorts は Gemini の 1fps サンプリング制約により `hook_structure` / `scene_timeline` の細粒度メトリクスは精度が落ちるため参考程度に扱うこと（`bgm_arc` 等の粗いメトリクスは利用可能）
- API レート制限対策で動画間に `delay_sec` 秒スリープ

## 関連ファイル

- `yt-video-analyze` (`youtube_automation.scripts.video_analyze`) — CLI 本体
- `data/video_analysis/<slug>/<video_id>.json` — 動画別構造化データ
- `reports/video_analysis/<slug>.md` — slug 別 Markdown レポート
- `data/benchmark_YYYYMMDD.json` — `--source benchmark` の入力
- `collections/live/<name>/20-documentation/upload_tracking.json` — `--source own` の入力
