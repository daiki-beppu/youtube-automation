---
name: short-thumbnail
description: Use when ショート動画用の 9:16 縦型サムネイル画像が必要なとき。コレクションの main.png/jpg を参考に、Gemini で縦型構図のサムネイルを生成する。「ショートサムネ」「縦型サムネイル」「short thumbnail」「9:16 画像」など
---

## Overview

ショート動画用の 9:16 縦型サムネイルを Gemini API で生成する。
通常サムネイル（16:9）のシーンを縦型に再構成し、テキスト（コレクション名・チャンネル名・CTA）を画像に焼き込む。

## When to Use

- `/short` でショート動画を生成する前に、縦型サムネイルが必要なとき
- `10-assets/short.png` が存在しない状態で `/short` を実行しようとしたとき
- 既存のショートサムネイルを改善・再生成したいとき

## Quick Reference

```bash
# チャンネルディレクトリから実行
export $(grep -v '^#' .env | xargs) && \
uv run yt-generate-image \
  --aspect-ratio "9:16" \
  --prompt "<プロンプト>" \
  --output <collection-path>/10-assets/short.png \
  -y
```

## Instructions

### Step 1: 素材確認

```bash
ls <collection-path>/10-assets/main.*        # 既存サムネイル（参考用）
ls <collection-path>/20-documentation/thumbnail-prompts.md  # 既存プロンプト
```

既存の `main.png/jpg`（16:9）を **視覚的に確認** し、シーンの構成要素を把握する。

### Step 2: プロンプト作成

既存サムネイルのシーンを **縦型構図で再描写** する。16:9 のクロップではなく、9:16 に最適化した構図をゼロから記述する。

**プロンプト構造:**

```
[縦型構図の指定] → [シーン・キャラクター描写（既存サムネイルを参考に）] → [テキスト指示] → [スタイル句]
```

**テキスト指示（3層）:**

| 層 | 内容 | 位置 | フォントスタイル |
|---|------|------|----------------|
| タイトル | コレクション名 | 上部エリア | 大きめ、暖色アイボリー中世風 |
| チャンネル名 | channel_config の channel.name | タイトル下 | やや小さめ、同スタイル |
| CTA | `Full 2-hour collection on channel` | 下部エリア | 小さめ、クリーン白 |

**テキスト装飾**: テーマに合わせた控えめな装飾（スパークル、葉、Celtic knot 等）。`/thumbnail` スキルの装飾ルールに準拠。

**スタイル句（末尾に付加）:**

```
Hyper-detailed digital matte painting blending photorealism with subtle painterly
illustration touches, slightly stylized proportions and soft edges that hint at
hand-painted artwork, natural cinematic lighting with warm lens diffusion, rich
saturated colors pushed slightly beyond reality for emotional impact.
```

**構図の注意点:**
- `Tall vertical portrait composition` を冒頭に明記
- 構図ルールは 16:9 と同じ（斜め後ろ・横顔推奨、有名キャラは斜め前可、カメラ目線NG）
- 縦長なので天井・床の描写に余裕がある — 環境ディテールを上下に配置
- キャラクターは画面中央〜やや下に配置（上部にテキスト空間を確保）

**プロンプト例:**

```
Tall vertical portrait composition. Inside a cozy medieval stone tower room,
a young woman with impossibly long golden hair sits on a wide stone windowsill
with her back to the viewer, painting on a canvas propped against the window
frame. She wears a blue peasant dress with paint stains. Her golden hair
cascades down and pools in flowing spirals across the wooden floor. Through
the tall arched window, a breathtaking sunset valley with waterfalls, a winding
river, distant castles and pine forests stretches below. Warm golden light
streams in. The room has stone walls, a wooden ceiling with string lights,
scattered art supplies, and stacked books. In the upper area, elegant white
fantasy text in stacked layout reads "Rapunzels Tower" in warm ivory
medieval-style font with subtle golden sparkle accents. Below that, smaller
text reads "{channel_name}" in matching style. Near the bottom, gentle
text reads "Full {duration}-hour collection on channel" in clean white font.
Hyper-detailed digital matte painting blending photorealism with subtle
painterly illustration touches, natural cinematic lighting with warm lens
diffusion, rich saturated colors.
```

### Step 3: 生成

```bash
# リポジトリルートから実行
export $(grep -v '^#' .env | xargs) && \
uv run yt-generate-image \
  --aspect-ratio "9:16" \
  --prompt "<Step 2 のプロンプト>" \
  --output <collection-path>/10-assets/short.png \
  -y
```

**出力**: `10-assets/short.png`（1536x2752、9:16）+ 自動生成 `short.jpg`

### Step 4: 確認・承認

```bash
open <collection-path>/10-assets/short.png
```

**チェック項目:**
- [ ] 9:16 縦型（1536x2752）
- [ ] テキスト 3 層が全て読める（タイトル・チャンネル名・CTA）
- [ ] 斜め後ろ/横顔構図（有名キャラは斜め前可、カメラ目線NG）
- [ ] 既存サムネイルとの世界観の一貫性
- [ ] 明るく鮮やかなカラー（暗すぎない）

不満なら `--output` を変えて再生成（自動バージョニング: `short-v2.png` 等）。

### Step 5: ループ動画化（推奨）

承認された `short.png` を Veo 3.1 で 9:16 ループ動画に変換する。キャラクターアニメーション付きで、ショート動画の映像品質が大幅に向上する。

```bash
# リポジトリルートから実行
export $(grep -v '^#' .env | xargs) && \
uv run yt-generate-short-loop <collection-path> -y
```

**カスタムプロンプト** でキャラクターの動きを指定できる:
```bash
uv run yt-generate-short-loop <collection-path> \
  --prompt "Gentle character animation: the woman slowly turns her head, hair sways in the breeze, flowers sway gently. Keep all text static and unchanged." \
  -y
```

**出力**: `10-assets/short-loop.mp4`（9:16、~7秒ループ、末尾1秒自動トリム）

```bash
open <collection-path>/10-assets/short-loop.mp4
```

**チェック項目:**
- [ ] テキストが崩れていないか（3層すべて読める）
- [ ] キャラクターが自然に動いているか
- [ ] ループの継ぎ目が自然か

## Gotchas

- **アスペクト比は `--aspect-ratio "9:16"` で指定**: `image_generator.py` の `aspect_ratio` パラメータが Gemini API に渡される
- **参照画像を渡すと 16:9 に引っ張られる**: `--reference` は使わず、シーンを言葉で再描写すること
- **テキストのアポストロフィ**: Gemini はアポストロフィ付きテキストも正しく描画できる（drawtext と異なりエスケープ不要）
- **CTA の尺**: `channel_config.json` の `audio.target_duration_min` を参照して正確な時間を入れる（例: 120分 → `Full 2-hour collection`）
- **コスト**: サムネイル $0.04（Gemini Flash）、ループ動画は Veo 3.1（別途）
- **Veo テキスト安定性**: `last_frame=image` でテキスト部分は開始・終了フレームで固定されるため崩れにくい。プロンプトに `Keep all text completely static and unchanged` を含めること
- **Veo 末尾ノイズ**: 末尾 ~1秒にノイズが入ることがある。`generate_short_loop.py` がデフォルトで末尾1秒をトリムする

## ファイル構造

```
10-assets/
├── main.png          # 16:9 サムネイル（動画背景用）
├── main.jpg          # 16:9 サムネイル（一部コレクション）
├── thumbnail.jpg     # 16:9 テキスト付きサムネイル（YouTube 用）
├── short.png         # 9:16 ショート用サムネイル（本スキルで生成）
├── short.jpg         # 9:16 JPEG 版（自動生成）
├── short-loop.mp4    # 9:16 ショート用ループ動画（Step 5 で生成）
└── loop.mp4          # 16:9 ループ動画背景
```
