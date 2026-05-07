# intro skill — references

チャンネル共通の **30 秒 intro 動画** (`branding/intro.mp4`) ビルダー一式。

## 配置

```
.claude/skills/intro/
├── SKILL.md                    # チャンネル開設 / ブランド刷新時の 4-step 手順
├── config.default.yaml         # text / logo / font / color の default
└── references/
    ├── generate_intro.py       # ffmpeg ビルダー (video-only 出力)
    ├── generate_droplet_png.py # 雫 PNG ビルダー
    └── README.md               # このファイル
```

## 設計の経緯（v6 → v7.1）

| 観点 | v6 (2026-05-05 archive) | v7.1 (現行) |
|---|---|---|
| `intro.mp4` 構造 | 環境音 SFX + 楽曲 amix を内蔵 | **video-only**（`-an`、音声なし） |
| 設計 D（10s afade-in 合流）の実行場所 | `generate_videos.sh` で amix 実装 | `/masterup` の `finalize_master.py` で amix 実装 |
| `generate_videos.sh` の役割 | amix 担当 | pure concat + audio map（v13） |
| 雫 PNG overlay | なし（v6 は `05_logo.png` color-key で焼き込み） | あり（`05_droplet.png` overlay + drawtext logo） |

v7.1 採用の根拠:

- intro.mp4 を pure video asset に整理することで、`/videoup` を audio mix から解放（pure concat に集中）
- 音声合流は `/masterup` で実機検証された設計 D（10s 遅延 + 2s afade-in、N-layer rain + 3 SFX + loudnorm two-pass）に集約
- `branding/intro.mp4` がビット単位 reuse 可能 → 既存コレクションへの影響なし

## ビルド手順

詳細は `SKILL.md` を参照。要約:

1. **Gemini で 4 still 生成** → `branding/intro_assets/{01_rain_cu,02_lamp_steam,03_room_ws,04_cinemagraph}.png`
2. **Veo で 4 loop 生成** → 同ディレクトリの `<name>_loop.mp4`
3. **雫 PNG ビルド**: `uv run python .claude/skills/intro/references/generate_droplet_png.py`
4. **intro.mp4 ビルド**: `uv run python .claude/skills/intro/references/generate_intro.py --force`

各 still / loop / 雫 PNG / intro.mp4 はチャンネル開設 / ブランド刷新時に **1 回**だけ生成すれば、以降のコレクション制作で再利用される。

## SFX / rain ambience の配置（`/masterup` 側で読まれる）

intro.mp4 自体には音声を焼き込まないが、設計 D の音声側施策のために以下を別途用意する:

```
branding/intro_sfx/
├── cup_v3.wav      # 6 秒目に -3dB で配置 (ceramic コーヒーカップを置く音)
├── paper.wav       # 18 秒目に -12dB で配置 (柔らかな紙ページめくり)
└── vinyl_v4.wav    # 10 秒目に -6dB で配置 (vinyl 針落ち)

branding/rain_layers/
└── rain_*.wav      # N-layer rain ambience。各 layer -19dB / 0.5s fadein で amix
```

これらは `/masterup` の `finalize_master.py` が自動検出して master.mp3 に統合する。各ファイル名・dB・配置 ms は `.claude/skills/masterup/config.default.yaml` の `intro_audio:` namespace で channel ごとに上書き可能。

## チャンネル上書き

`config/skills/intro.yaml`（channel 側）で以下を上書き:

```yaml
font:
  en: "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
  ja: "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"

color:
  drawtext: "#3A4A55"   # サムネ整合カラー (RJN は dark teal、他チャンネルは要調整)
  droplet: "#3A4A55"

logo:
  heading_left: "Sleep"        # チャンネル名の左半分
  heading_right: "Lullaby"     # チャンネル名の右半分
  tagline: "Drift into deep sleep with gentle melodies"

segments:
  - {name: "01_rain_cu", start: 0, end: 5, text_en: "Drift away.", text_ja: "穏やかな夜へ。"}
  # ... 5 segments すべてを書き直す (deep-merge は dict のみ。list は置換)
```

`segments` はリスト全体が上書き対象。部分更新は不可。

## 関連ドキュメント

- `.claude/skills/intro/SKILL.md` — `/intro` Claude command 起動時のガイド
- `.claude/skills/masterup/SKILL.md` — Step 5.5 で `finalize_master.py` を案内
- `.claude/skills/videoup/SKILL.md` — Intro 統合モード（`branding/intro.mp4` 検出時の concat 経路）
