---
name: short
description: Use when リリースの本編動画が完成し、告知用ショート動画の制作・投稿が必要なとき。BGM チャンネル（collection 型）はループ動画テイスター + 多言語ローカライズ、話す系（release 型）は JP+EN クリップに対応
---

## Overview

本編動画の公開後にショート動画を生成し、YouTube に投稿して本編への誘導を行う。
`config/channel/youtube.json` の `content_model.type` に応じて自動的にモードを切り替える。

FFmpeg 一括生成は `scripts/` 配下の bash スクリプトに切り出してあり、本 SKILL は
それらの呼び出し方と前後の判断フローを示す。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- 本編動画のアップロードが完了した後（`/upload` 完了後の翌日以降）
- `/post-upload` ワークフローの T+1 日アクションとして実行
- ショート動画で本編を告知・誘導したいとき

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `/short` | 最新コレクションのショート動画を生成 |
| `/short <path>` | 指定コレクション/リリースのショート動画を生成 |

`$ARGUMENTS` をコレクション/リリースディレクトリパスとして使用。省略時は `collections/live/` の最新を対象。

## Instructions

### 前提条件

- 本編動画がアップロード済み（`upload_tracking.json` に video_id 記録済み）
- `workflow-state.json` に `post_upload` セクションが存在

### モード判定

```python
from youtube_automation.utils.config import load_config
config = load_config()
mode = config.youtube.content_model.type
# "collection" → Mode A: BGM テイスターモード
# "release"    → Mode B: 話す系クリップモード
```

### 多言語ローカライゼーション対象

Mode A では全ての supported language に対してショート用メタデータ（title/description）を生成する。対象言語の出所:

- **Canonical ソース**: `config/localizations.json` の `supported_languages` + `default_language`
- **実装**: `load_config().localizations.supported_languages`
- **テンプレート定義**: `localizations.json.languages.<lang>.short_title_template` / `short_description_template`

### 生成パラメータ

duration / fade / count / font などは skill-config で管理する。
チャンネル側で上書きする場合は `config/skills/short.yaml`。デフォルトは
`.claude/skills/short/config.default.yaml` を参照:

```python
from youtube_automation.utils.skill_config import load_skill_config
short_cfg = load_skill_config("short")
duration = short_cfg.get("duration_sec", 20)
fade_in = short_cfg.get("fade_in_sec", 1.0)
fade_out = short_cfg.get("fade_out_sec", 1.5)
count = short_cfg.get("default_count", 3)
font = short_cfg.get("font_path")
release = short_cfg.get("release", {})
```

`generate-shorts-mode-a.sh` は `SHORT_DURATION` / `SHORT_FADE_IN` / `SHORT_FADE_OUT` / `SHORT_FONT` / `SHORT_CHANNEL_NAME` / `SHORT_COLLECTION_NAME` の env で上書きできる。skill-config の値を読み取って呼び出し側で env に設定する。

### ショート動画仕様（共通）

| 項目 | 値 |
|------|-----|
| アスペクト比 | 9:16（縦型） |
| 最大長 | 60 秒 |
| 推奨長 | 15-25 秒 |
| 解像度 | 1080x1920 |
| フレームレート | 30fps 必須（元動画が低 fps の場合 `fps=30` フィルター追加） |

---

## Mode A: BGM テイスターモード（collection 型）

`content_model.type == "collection"` の場合。
`generate-shorts-mode-a.sh` が素材の優先順位を自動判定して 3 系統のいずれかで並列生成する。

### Step 1: 素材確認

映像ソースの優先順位（スクリプトが自動選択）:

1. **ショート用ループ動画**: `10-assets/short-loop.mp4` — Veo 3.1 で short.png から生成した 9:16 ループ動画（キャラアニメーション + テキスト焼き込み済み）
2. **ショート専用サムネイル + zoompan**: `10-assets/short.png` — 9:16 縦型、Ken Burns 効果
3. **16:9 ループ + drawtext**: `10-assets/loop.mp4` — drawtext でチャンネル名 / コレクション名を重畳

いずれも無い場合はマスター動画フォールバックは**提供しない**。素材を揃えてから再実行すること（ループ動画生成: `uv run yt-generate-short-loop <collection-path> -y`）。

```bash
ls <collection-path>/10-assets/short-loop.mp4  # 最優先
ls <collection-path>/10-assets/short.png       # 次点
ls <collection-path>/10-assets/loop.mp4        # フォールバック
ls <collection-path>/10-assets/main.*          # 参考（drawtext 時の参照用）
```

### Step 2: CC video_id の自動検出

`upload_tracking.json` から CC の `video_url` を取得する。

```python
tracking = json.load(open(collection_path / '20-documentation' / 'upload_tracking.json'))
cc = tracking['complete_collection']
cc_video_url = cc['video_url']
cc_publish_at = cc.get('publish_at')
```

`upload_tracking.json` が無い場合は YouTube API の uploads プレイリストから `privacyStatus == 'private'` な動画を抽出し、`status.publishAt` が付いているものをスケジュール済みとして検出する。`playlistItems().list()` は `maxResults=50` 必須（10 件だとスケジュール済みが漏れる）。

### Step 3: クロップ位置の確認（loop-mp4 モードのみ）

16:9 → 9:16 の中央クロップだとキャラが切れる場合がある。`loop.mp4` ベースのときは**毎回必ず**テストフレームを生成してユーザーに確認する。

```bash
bash .claude/skills/short/scripts/test-crop-positions.sh "$MASTER_VIDEO" 30
```

center / x=400 / x=350 の 3 パターンが `/tmp/short-test-*.jpg` に書き出され `open` で表示される。AskUserQuestion でクロップ位置を選択してもらい、必要に応じてスクリプトに `crop=ih*9/16:ih:<X>:0` を差し替える。

### Step 4: ハイライト区間の選択

`20-documentation/descriptions.md` のチャプター情報を参照し、**全チャプターから均等に** 20 秒ずつ抽出する。

**選択基準:**
- 各チャプターの開始付近（数十秒後）を選択 — 自然な導入
- チャプター数に応じて本数を調整（デフォルト 3 本）
- ユーザーが本数を指定した場合はそれに従う
- 「いい感じに」等の指示なら自動選択して進める

**出力例（6 チャプター → 3 本の場合）:**

| # | チャプター | 開始位置（秒） |
|---|-----------|-------------|
| 01 | Chapter 1 | 30 |
| 02 | Chapter 3 | (chapter_start + 30) |
| 03 | Chapter 5 | (chapter_start + 30) |

### Step 5: 一括生成

`generate-shorts-mode-a.sh` に `SHORT_STARTS` / `SHORT_LABELS` を env で渡して並列実行する:

```bash
export SHORT_STARTS="30 3960 6420"
export SHORT_LABELS="chapter1 chapter3 chapter5"
# loop-mp4 モード時のみ必要
export SHORT_CHANNEL_NAME="Your Channel"
export SHORT_COLLECTION_NAME="Collection Title"

bash .claude/skills/short/scripts/generate-shorts-mode-a.sh <collection-path>
```

素材自動判定で以下のいずれかに分岐する:

| 判定 | 処理 |
|---|---|
| `short-loop.mp4` あり | `-stream_loop -1` + scale (drawtext / zoompan なし) |
| `short.png` あり | zoompan + Ken Burns + vignette |
| `loop.mp4` あり | crop + drawtext でチャンネル名 / コレクション名重畳 |

skill-config の値は `load_skill_config("short")` で読み取り、呼び出し前に `SHORT_DURATION` / `SHORT_FADE_IN` / `SHORT_FADE_OUT` / `SHORT_FONT` に反映する。

### Step 6: プレビュー確認

生成後、ユーザーに `open` で確認を促す:

```bash
open <collection>/01-master/shorts/short-01-*.mp4
```

### Step 7: 一括アップロード

`ShortUploader` を使って全ショートをアップロードする。`localizations.json` の全言語でタイトル・説明文がローカライズされる。

```bash
uv run yt-upload-short <collection-path>
# ドライラン（メタデータ確認のみ）
uv run yt-upload-short <collection-path> --dry-run
```

複数ショートを順番にアップロード:

```bash
for i in 1 2 3; do
  uv run yt-upload-short <collection-path> --short-num $i
done
```

**ShortUploader が自動で行うこと:**

- CC publish_at 基準の公開日計算（翌日 `short_publish_time`）
- EN デフォルトメタデータ生成
- `localizations.json` の全言語でタイトル・説明文ローカライズ
- `workflow-state.json` 更新

#### メタデータ（共通概要欄）

```
{collection_name} | {channel_name}

♫ Full {duration}-hour collection → {cc_video_url}

{tagline}

{hashtag_line} #Shorts
```

`{duration}` は `config/channel/audio.json` の `audio.target_duration_min` を 60 で割った値。

**タイトル（EN デフォルト）:**

```
{collection_name} ✦ {channel_name} #Shorts
```

**ローカライズタイトル** は `localizations.json.languages.<lang>.short_title_template` を参照。

### Step 8: workflow-state.json 更新

```json
"post_upload": {
  "short": {
    "generated": true,
    "uploaded": true,
    "count": 3,
    "publish_at": "2026-03-12T08:00:00+09:00",
    "videos": [
      {"video_id": "xxx", "title": "Morning Light — ..."},
      {"video_id": "yyy", "title": "Mixing Colors — ..."}
    ]
  }
}
```

### ファイル構造

```
01-master/
├── *Master*.mp4          # マスター動画（ソース）
├── short.mp4             # 単体ショート（旧方式、互換用）
└── shorts/               # 一括ショート
    ├── short-01-morning-light-1.mp4
    ├── short-02-morning-light-2.mp4
    └── ...
```

---

## Mode B: 話す系クリップモード（release 型）

`content_model.type == "release"` の場合（JP + EN 2 本対応）。

### Step 1: 素材確認

```bash
ls <release-path>/video/    # 本編動画確認
ls <release-path>/assets/   # サムネイル素材確認
```

### Step 2: ショート動画生成

`generate-shorts-mode-b.sh` が `${motif}-jp.mp4` / `${motif}-en.mp4` を 9:16 に変換する:

```bash
bash .claude/skills/short/scripts/generate-shorts-mode-b.sh <release-path>
# 開始位置・長さを指定する場合
bash .claude/skills/short/scripts/generate-shorts-mode-b.sh <release-path> -s 30 -t 40
```

`-s`（開始秒）は楽曲のサビ部分に合わせて調整。ユーザーに確認を取ること。

### Step 3: メタデータ生成

**JP ショート:**

```
🎵 {motif_ja} | {channel_name}

✨ フル動画はこちら → {jp_video_url}

{tagline}

{hashtag_line} #Shorts
```

**EN ショート:**

```
🎵 {motif_en} | {channel_name}

✨ Full version → {en_video_url}

{tagline_en}

{hashtag_line} #Shorts
```

### Step 4: アップロード & 記録

`video_uploader.py` でアップロード:

- プライバシー: `public`
- カテゴリ: `config/channel/youtube.json` の `youtube.category_id`
- `#Shorts` を必ず含める

`workflow-state.json` 更新:

```json
"post_upload": {
  "short": {
    "jp": { "generated": true, "uploaded": true, "video_id": "xxx" },
    "en": { "generated": true, "uploaded": true, "video_id": "xxx" }
  }
}
```

---

## 品質チェック（共通）

- [ ] 9:16 縦型（1080x1920）
- [ ] 30fps 以上
- [ ] 60 秒以内
- [ ] 本編動画への URL リンクあり（概要欄）
- [ ] `#Shorts` タグ含む（タイトル + タグ欄）
- [ ] 音量が適切（本編と同等、クリッピングなし）
- [ ] フェードイン/アウトが自然
- [ ] 誇張表現なし（Epic/Ultimate 等の禁止語）

## Gotchas

- **drawtext フォント**: Nix FFmpeg は libfreetype 付き。macOS では `/System/Library/Fonts/Palatino.ttc` を指定すること
- **fps=30 必須**: マスター動画が静止画ベース（1fps）の場合、`fps=30` フィルターを追加しないと YouTube がショートとして認識しない
- **zsh 配列**: zsh で `${!array[@]}` は使えない。スクリプトは全て `#!/usr/bin/env bash` で実行される
- **スケジュール済み動画の API 検出**: `playlistItems().list()` は `maxResults=50` 必須。10 件だとスケジュール済みが漏れる
- **drawtext のアポストロフィ**: コレクション名に `'` が含まれる場合、シェルのクォートと衝突する。`SHORT_COLLECTION_NAME` にセットする前にアポストロフィを除去するか `'\''` でエスケープすること

## Next Step

ショート動画投稿後:

→ `/post-upload` の残りアクションを確認
→ 全アクション完了なら `/status` で Analytics 監視を開始
