---
name: short
description: Use when リリースの本編動画が完成し、告知用ショート動画の制作・投稿が必要なとき。BGM チャンネル（collection 型）はループ動画テイスター + 多言語ローカライズ、話す系（release 型）は JP+EN クリップに対応
---

## Overview

本編動画の公開後にショート動画を生成し、YouTube に投稿して本編への誘導を行う。
`channel_config.json` の `content_model.type` に応じて自動的にモードを切り替える。

## 前提

`config/channel_config.json` が存在すること。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- 本編動画のアップロードが完了した後（`/upload` 完了後の翌日以降）
- `/post-upload` ワークフローの T+1日アクションとして実行
- ショート動画で本編を告知・誘導したいとき

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `/short` | 最新コレクションのショート動画を生成 |
| `/short <path>` | 指定コレクション/リリースのショート動画を生成 |

### 引数の解釈

`$ARGUMENTS` をコレクション/リリースディレクトリパスとして使用。省略時は `collections/live/` の最新を対象。

## Instructions

### 前提条件

- 本編動画がアップロード済み（`upload_tracking.json` に video_id 記録済み）
- `workflow-state.json` に `post_upload` セクションが存在

### モード判定

```python
from utils.channel_config import ChannelConfig
config = ChannelConfig.load()
mode = config.raw.get("content_model", {}).get("type", "release")
# "collection" → Mode A: BGM テイスターモード
# "release"    → Mode B: 話す系クリップモード
```

### 生成パラメータ

各モードの尺・フェード・本数・フォント等は skill-config で管理する。
チャンネル側で上書きする場合は `config/skills/short.yaml`。デフォルトは
`.claude/skills/short/config.default.yaml` を参照:

```python
from youtube_automation.utils.skill_config import load_skill_config
short_cfg = load_skill_config("short")
duration = short_cfg.get("duration_sec", 20)       # Mode A
fade_in = short_cfg.get("fade_in_sec", 1.0)
fade_out = short_cfg.get("fade_out_sec", 1.5)
count = short_cfg.get("default_count", 3)
font = short_cfg.get("font_path")
release = short_cfg.get("release", {})             # Mode B
```

### ショート動画仕様（共通）

| 項目 | 値 |
|------|-----|
| アスペクト比 | 9:16（縦型） |
| 最大長 | 60秒 |
| 推奨長 | 15-25秒 |
| 解像度 | 1080x1920 |
| フレームレート | 30fps 必須（元動画が低fpsの場合 `fps=30` フィルター追加） |

---

## Mode A: BGM テイスターモード（collection 型）

`content_model.type == "collection"` の場合。
マスター動画から各チャプター別にクロップし、複数のショート動画を一括生成する。

### Step 1: 素材確認

映像ソースの優先順位:

1. **ショート用ループ動画**（最優先）: `10-assets/short-loop.mp4` — Veo 3.1 で short.png から生成した 9:16 ループ動画（キャラアニメーション付き）
2. ショート専用サムネイル + zoompan: `10-assets/short.png` — 9:16 縦型、テキスト焼き込み済み。zoompan で Ken Burns 効果
3. サムネイル画像: `10-assets/main.png` or `main.jpg` — zoompan + drawtext
4. マスター動画（フォールバック）: `01-master/*Master*.mp4` — 直接クロップ

**ショート用ループ動画の生成:**
```bash
# short.png が必要（なければ /short-thumbnail で先に生成）
uv run yt-generate-short-loop <collection-path> -y
# カスタムプロンプト指定
uv run yt-generate-short-loop <collection-path> --prompt "gentle character animation..." -y
```

```bash
ls <collection-path>/10-assets/short-loop.mp4  # ショート用ループ動画（最優先）
ls <collection-path>/10-assets/short.png       # ショート専用サムネイル
ls <collection-path>/10-assets/main.*          # 16:9 サムネイル
ls <collection-path>/01-master/*Master*.mp4    # マスター動画（フォールバック）
```

### Step 2: CC video_id の自動検出

`upload_tracking.json` から CC の `video_url` を取得する。

```python
# upload_tracking.json から取得
tracking = json.load(open(collection_path / '20-documentation' / 'upload_tracking.json'))
cc = tracking['complete_collection']
cc_video_url = cc['video_url']
cc_publish_at = cc.get('publish_at')
```

**upload_tracking.json がない場合の API フォールバック:**

YouTube API でスケジュール済み動画を自動検出できる:

```python
# uploads プレイリストから private 動画を抽出
ch = youtube.channels().list(id=channel_id, part='contentDetails').execute()
uploads_pl = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
items = youtube.playlistItems().list(
    playlistId=uploads_pl, maxResults=50, part='snippet,status'
).execute()
private_ids = [i['snippet']['resourceId']['videoId']
               for i in items['items']
               if i.get('status', {}).get('privacyStatus') == 'private']

# publishAt の有無でスケジュール済みかを判定
details = youtube.videos().list(id=','.join(private_ids), part='snippet,status').execute()
for v in details['items']:
    publish_at = v['status'].get('publishAt')  # あればスケジュール済み
```

**注意:** `search().list()` や `playlistItems().list()` の `maxResults=10` ではスケジュール済み動画が漏れる。`maxResults=50` を使うこと。

### Step 3: クロップ位置の確認

16:9 → 9:16 の中央クロップだとキャラが切れる場合がある。**毎回必ず**テストフレームを生成してユーザーに確認する。

```bash
# デフォルト中央、左寄り2パターンのテストフレームを生成
ffmpeg -y -ss 30 -i "$MASTER_VIDEO" -frames:v 1 \
  -vf "crop=ih*9/16:ih,scale=1080:1920" /tmp/short-test-center.jpg
ffmpeg -y -ss 30 -i "$MASTER_VIDEO" -frames:v 1 \
  -vf "crop=ih*9/16:ih:400:0,scale=1080:1920" /tmp/short-test-x400.jpg
ffmpeg -y -ss 30 -i "$MASTER_VIDEO" -frames:v 1 \
  -vf "crop=ih*9/16:ih:350:0,scale=1080:1920" /tmp/short-test-x350.jpg
open /tmp/short-test-*.jpg
```

AskUserQuestion でクロップ位置を選択してもらう。キャラが画面中央に来る位置を選ぶ。
- `crop=ih*9/16:ih` — デフォルト中央（x = (iw-crop_w)/2）
- `crop=ih*9/16:ih:X:0` — X を指定して左右にずらす

### Step 4: ハイライト区間の選択

`20-documentation/descriptions.md` のチャプター情報を参照し、**全チャプターから均等に** 20秒ずつ抽出する。

**選択基準:**
- 各チャプターの開始付近（数十秒後）を選択 — 自然な導入
- チャプター数に応じて本数を調整（デフォルト 3本）
- ユーザーが本数を指定した場合はそれに従う
- 「いい感じに」等の指示なら自動選択して進める

**出力例（6チャプター → 3本の場合）:**

| # | チャプター | 開始位置（秒） |
|---|-----------|-------------|
| 01 | Chapter 1 | 30 |
| 02 | Chapter 3 | (chapter_start + 30) |
| 03 | Chapter 5 | (chapter_start + 30) |

### Step 5: FFmpeg 一括生成

bash スクリプトで全ショートを **並列生成** する。

#### 5a: short-loop.mp4（最推奨 — Veo ループ動画）

Veo 3.1 で生成した 9:16 ループ動画（キャラアニメーション + テキスト焼き込み済み）を使用。drawtext 不要。

```bash
#!/bin/bash
# generate_shorts.sh — 一括ショート動画生成（Veo ループ動画方式）
COLLECTION_DIR="$1"
SHORT_LOOP="${COLLECTION_DIR}/10-assets/short-loop.mp4"
MASTER_AUDIO=$(ls "${COLLECTION_DIR}"/01-master/*Master*.mp3 2>/dev/null | head -1)
OUTDIR="${COLLECTION_DIR}/01-master/shorts"
mkdir -p "$OUTDIR"

DURATION=20
FADE_IN=1.0
FADE_OUT=1.5
FADE_OUT_START=18.5

# チャプター別の開始位置と名前（descriptions.md から算出）
STARTS=(30 3960 6420)
LABELS=(chapter1 chapter3 chapter5)

for i in "${!STARTS[@]}"; do
  START=${STARTS[$i]}
  LABEL=${LABELS[$i]}
  NUM=$(printf '%02d' $((i+1)))
  OUTPUT="${OUTDIR}/short-${NUM}-${LABEL}.mp4"

  ffmpeg -y \
    -stream_loop -1 -i "$SHORT_LOOP" \
    -ss "$START" -i "$MASTER_AUDIO" \
    -t "$DURATION" \
    -vf "scale=1080:1920,fps=30,fade=t=in:st=0:d=${FADE_IN},fade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
    -af "afade=t=in:d=${FADE_IN},afade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
    -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -ar 48000 \
    -shortest -movflags +faststart \
    "$OUTPUT" 2>/dev/null &

  echo "Started #${NUM}: ${LABEL} (start=${START}s)"
done

echo "Waiting for all jobs..."
wait
echo "Done!"
ls -lh "$OUTDIR"/*.mp4
```

**ポイント:**
- `short-loop.mp4` は 8秒ループ → `-stream_loop -1` で 20秒分ループ再生
- テキスト（タイトル・チャンネル名・CTA）は画像に焼き込み済み — drawtext 不要
- キャラクターが動く（Veo アニメーション）ので zoompan 不要
- 生成: `uv run yt-generate-short-loop <collection-path> -y`

#### 5a-alt: short.png + zoompan（Veo ループ動画がない場合）

`/short-thumbnail` で生成した静止画を zoompan で Ken Burns アニメーション化。

```bash
ffmpeg -y \
  -i "${COLLECTION_DIR}/10-assets/short.png" \
  -ss "$START" -i "$MASTER_AUDIO" \
  -t "$DURATION" \
  -vf "zoompan=z='min(zoom+0.0008,1.25)':d=600:fps=30:s=1080x1920:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',vignette=PI/4,fade=t=in:st=0:d=${FADE_IN},fade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
  -af "afade=t=in:d=${FADE_IN},afade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 \
  -shortest -movflags +faststart \
  "$OUTPUT"
```

#### 5b: main.png + zoompan + drawtext（short.png がない場合）

16:9 サムネイルを 9:16 にクロップして使用。drawtext でテキストを付加する。
- `fade=t=in/out` + `afade` — 映像・音声のフェードイン/アウト同期
- `2>/dev/null &` — 全ジョブ並列実行、`wait` で完了待ち

#### 5b: ループ動画の場合

```bash
ffmpeg -y \
  -stream_loop -1 -i "${COLLECTION_DIR}/10-assets/loop.mp4" \
  -ss "$START" -i "$MASTER_AUDIO" \
  -t "$DURATION" \
  -vf "crop=ih*9/16:ih,scale=1080:1920,fps=30,fade=t=in:st=0:d=${FADE_IN},fade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT},drawtext=text='${CHANNEL_NAME}':fontfile=${FONT}:fontsize=32:fontcolor=white@0.85:borderw=2:bordercolor=black@0.4:x=(w-text_w)/2:y=h*0.12:enable='between(t,0.5,5)',drawtext=text='${COLLECTION_NAME}':fontfile=${FONT}:fontsize=44:fontcolor=white@0.95:borderw=3:bordercolor=black@0.5:x=(w-text_w)/2:y=h*0.18:enable='between(t,0.8,5)'" \
  -af "afade=t=in:d=${FADE_IN},afade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 \
  -shortest -movflags +faststart \
  "$OUTPUT"
```

#### 5c: マスター動画フォールバック（旧方式）

クロップ位置は Step 3 で確認したものを使用。非推奨 — 5a を優先すること。

```bash
ffmpeg -y \
  -ss "$START" -i "$MASTER_VIDEO" \
  -t "$DURATION" \
  -vf "crop=ih*9/16:ih:${CROP_X}:0,scale=1080:1920,fps=30,fade=t=in:st=0:d=${FADE_IN},fade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
  -af "afade=t=in:d=${FADE_IN},afade=t=out:st=${FADE_OUT_START}:d=${FADE_OUT}" \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 \
  -shortest -movflags +faststart \
  "$OUTPUT"
```

### Step 6: プレビュー確認

生成後、ユーザーに `open` で確認を促す:
```bash
open <collection>/01-master/shorts/short-01-*.mp4
```

### Step 7: 一括アップロード

`ShortUploader` を使って全ショートをアップロードする。`localizations.json` の全言語でタイトル・説明文がローカライズされる。

#### 単体ショートの場合

```bash
uv run yt-upload-short <collection-path>
# ドライラン（メタデータ確認のみ）
uv run yt-upload-short <collection-path> --dry-run
```

#### 複数ショートの場合

```bash
# shorts/ ディレクトリ内の全ショートを順番にアップロード
for i in 1 2 3; do
  uv run yt-upload-short <collection-path> --short-num $i
done
```

または Python スクリプトで一括実行:

```python
from agents.short_uploader import ShortUploader

uploader = ShortUploader()
SHORTS_DIR = collection_path / '01-master' / 'shorts'
shorts = sorted(SHORTS_DIR.glob('short-*.mp4'))

for i, video_path in enumerate(shorts, 1):
    result = uploader.upload_short(collection_path, short_num=i)
    print(f"  #{i}: {result['action']} — {result.get('details', {}).get('video_url', '')}")
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
（{duration} は `channel_config.json` の `audio.target_duration_min` を60で割った値）

{tagline}

{hashtag_line} #Shorts
```

**タイトル（EN デフォルト）:**
```
{collection_name} ✦ {channel_name} #Shorts
```

**ローカライズタイトル（localizations.json の short_title_template）:**
```
ja: 【{theme}】{channel_name} #Shorts
ko: 【{theme}】{channel_name} #Shorts
es/fr/de 等: {theme} ✦ {channel_name} #Shorts
...（全 supported_languages — localizations.json の short_title_template を参照）
```

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

`content_model.type == "release"` の場合（JP+EN 2本対応）。

### Step 1: 素材確認

```bash
ls <release-path>/video/    # 本編動画確認
ls <release-path>/assets/   # サムネイル素材確認
```

### Step 2: FFmpeg ショート動画生成

本編動画のサビ部分（最も盛り上がる 30-45秒）を抽出し、縦型に変換:

```bash
RELEASE_DIR="$1"
MOTIF=$(basename "$RELEASE_DIR" | sed 's/^[0-9]*-//')

# JP ショート
ffmpeg -i "${RELEASE_DIR}/video/${MOTIF}-jp.mp4" \
  -ss 30 -t 40 \
  -vf "crop=ih*9/16:ih,scale=1080:1920,fps=30" \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  "${RELEASE_DIR}/video/short-jp.mp4"

# EN ショート
ffmpeg -i "${RELEASE_DIR}/video/${MOTIF}-en.mp4" \
  -ss 30 -t 40 \
  -vf "crop=ih*9/16:ih,scale=1080:1920,fps=30" \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  "${RELEASE_DIR}/video/short-en.mp4"
```

**注意**: `-ss`（開始位置）は楽曲のサビ部分に合わせて調整。ユーザーに確認を取ること。

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

### Step 4: アップロード＆記録

`video_uploader.py` でアップロード:
- プライバシー: `public`
- カテゴリ: `channel_config.json` の `category_id`
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
- [ ] 60秒以内
- [ ] 本編動画への URL リンクあり（概要欄）
- [ ] `#Shorts` タグ含む（タイトル + タグ欄）
- [ ] 音量が適切（本編と同等、クリッピングなし）
- [ ] フェードイン/アウトが自然
- [ ] 誇張表現なし（Epic/Ultimate 等の禁止語）

## Gotchas

- **drawtext 利用可能**: Nix FFmpeg は libfreetype 付き。`fontfile=/System/Library/Fonts/Palatino.ttc` を必ず指定すること
- **fps=30 必須**: マスター動画が静止画ベース（1fps）の場合、`fps=30` フィルターを追加しないと YouTube がショートとして認識しない
- **zsh 配列**: zsh で `${!array[@]}` は使えない。一括生成スクリプトは `#!/bin/bash` で実行すること
- **スケジュール済み動画の API 検出**: `playlistItems().list()` は `maxResults=50` 必須。10件だとスケジュール済みが漏れる
- **drawtext のアポストロフィ**: コレクション名に `'` が含まれる場合、シェルのクォートと衝突する。変数展開前にアポストロフィを除去するか `'\''` でエスケープすること

## Next Step

ショート動画投稿後:
→ `/post-upload` の残りアクションを確認
→ 全アクション完了なら `/status` で Analytics 監視を開始
