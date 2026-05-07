---
name: intro
description: Use when チャンネル共通 30 秒 intro 動画 (`branding/intro.mp4`) を新規作成 / 刷新するとき。チャンネル開設時 / ブランド刷新時の 1 回限りの作業で、コレクション制作毎には呼ばない。サムネ世界観に整合した photoreal video-only intro (4 Veo ショット + drawtext + 雫 PNG overlay) をビルドする。
---

## Overview

チャンネル共通の **30 秒 intro 動画** (`branding/intro.mp4`) を新規生成 / 刷新する。

- **作成タイミング**: チャンネル開設時 / ブランド刷新時に **1 回だけ**
- **配置**: `branding/intro.mp4`（チャンネルブランディング素材、video-only）
- **連携**: コレクション制作時は `/videoup` が本編に concat する。SFX + rain ambience の合流は `/masterup` の `finalize_master.py` が `branding/intro_sfx/*.wav` + `branding/rain_layers/*.wav` から直接 amix する（intro.mp4 自体は無音）

### 設計の核（v7.1 photoreal video-only / 設計 D）

サムネで集まった視聴者の冒頭離脱を防ぐ動画側施策。サムネ世界観 ⇄ intro 世界観 ⇄ 楽曲世界観の 3 段整合が retention を決める。

- intro.mp4 は **video-only**（`-an`、音声なし、1920×1080、24fps、libx264 high CRF 18、30s 固定）
- drawtext / 雫 PNG overlay / drawbox は `config.default.yaml` で text / logo / font / color を上書き可能
- intro.mp4 タイムラインの 5 segment 構造（0/5/10/15/25/30s 境界）は設計 D の本質定数で `generate_intro.py` の module 定数に固定（config 化しない）
- SFX (cup/vinyl/paper) と rain ambience は `/masterup` の `finalize_master.py` が直接合成。`/videoup` の concat は pure video stream copy 経路で audio mix を持たない

## 設定

動作パラメータは skill-config (`.claude/skills/intro/config.default.yaml`) で管理。
チャンネル側で上書きする場合は `config/skills/intro.yaml`:

| 項目 | 既定 | 説明 |
|---|---|---|
| `segments[*].text_en` / `text_ja` | RJN サンプル文 | 各 segment 上に焼き込む drawtext。空文字列で drawtext 抑止 |
| `text.fontsize_en` / `fontsize_ja` / `fontsize_logo` / `fontsize_tagline` | 84 / 42 / 96 / 32 | drawtext のフォントサイズ (EN 主文 / JA 副文 / logo heading / tagline) |
| `text.fade_seconds` | 0.7 | drawtext 両端 alpha フェード秒（segment 境界で in/out） |
| `text.shadow_color` / `shadow_x` / `shadow_y` | `black@0.35` / 1 / 2 | drawtext 影色 / オフセット |
| `font.en` / `font.ja` | macOS 既定パス | drawtext のフォントパス。Linux / Windows では override 必須 |
| `color.drawtext` | `#3A4A55`（ダークティール） | drawtext / drawbox の塗り色（サムネ整合） |
| `color.droplet` | `#3A4A55` | 雫 PNG (`05_droplet.png`) の塗り色 |
| `logo.heading_left` / `heading_right` / `tagline` | RJN サンプル文 | 15-25s logo segment 用テキスト 3 行（左右 heading + tagline） |
| `droplet.size` / `super_sampling` | 96 / 4 | 雫 PNG の出力サイズとアンチエイリアス倍率 |

## When to Use

- チャンネル開設時にブランド共通 intro.mp4 を作るとき
- 既存 intro の世界観を刷新するとき（サムネ更新と歩調を揃える）

コレクション制作毎の呼び出しは不要。`branding/intro.mp4` が存在すれば `/videoup` が自動検出する。

## 制作手順

### Step 1. Gemini で 4 still を順次生成

サムネ参照画像（`branding/thumbnail-references/*.jpg` 等）と整合する photoreal still を 4 枚生成し、`branding/intro_assets/{01_rain_cu,02_lamp_steam,03_room_ws,04_cinemagraph}.png` に配置する。03_room_ws は **上 2/3 を空けてロゴ drawtext 配置領域を担保**（オブジェクトを下 1/3 に）。

```bash
uv run yt-generate-image -y --aspect-ratio 16:9 --size 2K --no-composition \
  --output branding/intro_assets/01_rain_cu.png --prompt "..."
# 02_lamp_steam, 03_room_ws, 04_cinemagraph を同様に
```

### Step 2. Veo で 4 loop を順次生成

各 still を一時 collection の `main.png` に配置して `yt-generate-loop-video` を実行、出力 `loop.mp4` を `branding/intro_assets/<name>_loop.mp4` にコピー。

### Step 3. 雫 PNG を生成

```bash
uv run python .claude/skills/intro/references/generate_droplet_png.py
```

`branding/intro_assets/05_droplet.png` (96×96 RGBA, 透明背景, color.droplet 塗り) が生成される。

### Step 4. intro.mp4 をビルド

```bash
uv run python .claude/skills/intro/references/generate_intro.py --force
```

出力: `branding/intro.mp4` (30s, 1920x1080, 24fps, libx264 high CRF 18, **音声なし**, `-an`)。

### Step 5. 検証

QuickTime で再生し、サムネとの世界観整合 / drawtext 視認性 / 雫 PNG の中央配置を確認。NG なら Step 1-3 のいずれかに戻る。OK ならコミット。

## アセット配置

```
.claude/skills/intro/
├── SKILL.md                    # このファイル
├── config.default.yaml         # text / logo / font / color の default
└── references/
    ├── generate_intro.py       # ffmpeg ビルダー (video-only 出力)
    ├── generate_droplet_png.py # 雫 PNG ビルダー
    └── README.md               # 詳細仕様 + 過去版経緯

branding/                       # チャンネルブランディング素材
├── intro.mp4                   # 最終生成物 (video-only, 30s)
├── intro_sfx/                  # /masterup が読む SFX 配置先
│   ├── cup_v3.wav
│   ├── paper.wav
│   └── vinyl_v4.wav
├── rain_layers/                # /masterup が読む rain N レイヤー
│   └── rain_*.wav
└── intro_assets/
    ├── 01_rain_cu.png / _loop.mp4
    ├── 02_lamp_steam.png / _loop.mp4
    ├── 03_room_ws.png / _loop.mp4
    ├── 04_cinemagraph.png / _loop.mp4
    └── 05_droplet.png          # 雫マーク (heading overlay 用)
```

## 関連スキル

- `/videoup` — `branding/intro.mp4` 検出時に Intro 統合モード（pure concat、audio mix を持たない）で本編に concat
- `/masterup` — `finalize_master.py` が `branding/intro_sfx/*.wav` + `branding/rain_layers/*.wav` を直接読んで master.mp3 に統合（設計 D の音声側施策）
- `/thumbnail` — サムネ世界観のソース。intro はサムネと整合させること
