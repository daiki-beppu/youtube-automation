---
name: loop-video
description: Use when コレクションのサムネイル画像からループ動画背景を生成したいとき。Veo 3.1 API で main.png/jpg を元に微細アニメーション付きの 8秒シームレスループ動画を生成。ループ動画、背景動画、loop.mp4、アニメーション背景、動画背景など、静止画を動画化する場面で必ず使用すること
---

## Overview

Veo 3.1 API を使い、コレクションの `main.png/jpg` から 8秒のシームレスループ動画を生成します。
生成された `loop.mp4` は `generate_videos.sh` が自動検出し、静止画の代わりに動画背景として使用します。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

**ループ動画化の有効/無効**: skill-config の `enabled`（default `true`）で制御する。`config/skills/loop-video.yaml::enabled: false` のチャンネルでは本スキルは実行不可で、`yt-generate-loop-video` は fail-loud で停止する（Veo 課金を防ぐ）。サムネが完成済みでループ動画のリターンが Veo コストに見合わないチャンネルは `false` にする。

## Script

| スクリプト | 役割 | 場所 |
|-----------|------|------|
| `generate_loop_video.py` | main.png/jpg → 8秒ループ動画 (Veo 3.1) | entry point: `uv run yt-generate-loop-video` |

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `uv run yt-generate-loop-video <collection-path> -y` | 指定コレクションでループ動画生成 |
| `uv run yt-generate-loop-video -y` | CWD のコレクションでループ動画生成 |
| `uv run yt-generate-loop-video <path> --motion-targets "leaves,steam" --static-targets "character,two animals (count remains 2)" -y` | 構造化プロンプトで生成（推奨） |
| `uv run yt-generate-loop-video <path> --prompt "..." -y` | カスタムプロンプトで全文上書き |
| `uv run yt-generate-loop-video <path> --smooth -y` | 生成後に FFmpeg クロスフェード補正 |

## Instructions

### 対象コレクション

```
$ARGUMENTS
```

引数が指定されている場合、そのコレクションを対象とします。
未指定の場合、`collections/planning/` から `thumbnail.approved = true` かつ `loop.mp4` が未生成のコレクションを自動検出します。

### 前提条件

- `10-assets/main.png` または `main.jpg` が存在すること（サムネイル生成済み）
- Vertex AI ADC が初期化されていること (`gcloud auth application-default login` + `set-quota-project`)。project_id は ADC quota project から自動解決される（`GOOGLE_CLOUD_PROJECT` は任意で上書き可）。region は `generate_loop_video.py` 側で `us-central1` を明示固定するため `GOOGLE_CLOUD_LOCATION` は不要
- `gcloud auth application-default login` で ADC が取得済みであること

### ステップ

1. **対象確認**: `10-assets/` に `main.png` or `main.jpg` があることを確認
2. **プロンプト検討**: シーンに応じた自然な動きを指定
   - デフォルトプロンプトは skill-config (`config/skills/loop-video.yaml` または `.claude/skills/loop-video/config.default.yaml`) の `veo.default_prompt` を使用
   - シーンに合わない場合は `--prompt` でカスタマイズ
3. **生成実行**: `uv run yt-generate-loop-video <collection-path> -y`
4. **品質確認**: ユーザーに `loop.mp4` を確認してもらう
5. **ループ確認**: 継ぎ目が気になる場合は `--smooth` で再実行

### 構造化プロンプト（推奨）

「動かす対象」と「固定対象」をリストで明示する方式。Veo 3.1 公式推奨のポジティブ表現テンプレートに展開される。`default_prompt` の単一文字列より事故率が低い（動物の数が変わる / 肩から鳥が湧く等の現象を抑制）。

**プロンプト解決の優先順位**:

| 順位 | 入力 | 用途 |
|---|---|---|
| 1 | `--prompt "..."` | 全文上書き（最強、structured 系は無視される） |
| 2 | `--motion-targets / --static-targets` | コレクション単位の都度上書き |
| 3 | skill-config の `motion_targets` / `static_targets` | チャンネル単位デフォルト |
| 4 | skill-config の `default_prompt` | freeform 上書き（後方互換） |
| 5 | ハードコード `DEFAULT_PROMPT` | 最終フォールバック |

**Veo 3.1 公式推奨**:
- **ポジティブ表現**で書く（"do not animate X" より "only Y moves, the rest remains exactly as in the source image"）
- **count / shape を肯定文で固定**: `"two animals (count remains 2)"`, `"the character (same posture)"` のように数や形を明示
- **微動語彙**: `subtle`, `gentle`, `slight`, `barely perceptible`, `slow sway`, `living painting`
- I2V は 50〜100 words が目安（テンプレが既に圧縮されている）

**動かす対象（motion_targets）の例**:
- `slow leaves swaying`, `gentle leaves fluttering`（屋外）
- `subtle steam rising from coffee`, `steam from mug`（カフェ/書斎）
- `gentle candle flame flicker`, `slow candle flicker`（室内）
- `slight character breathing`（人物のみ動かしたいとき）
- `soft light shifts on surfaces`（光のみ）
- `rain streaks on window`（雨シーン）
- `slow subtle ripples on water surface`（水辺）
- `subtle monitor glow shifts`（書斎・モニター）

**固定対象（static_targets）の例**:
- `the character (same posture, same expression)` — 人物の姿勢/表情固定
- `two animals (count remains 2)` — 動物の数固定
- `keyboard`, `monitor frame`, `books`, `desk objects` — オブジェクト固定
- `interior structure`, `background elements` — 背景固定
- `dessert plates`, `cups and saucers` — 小物固定

### チャンネル別 structured 設定例

`config/skills/loop-video.yaml` の上書き例:

**rjn（lo-fi jazz × rainy night）**:
```yaml
veo:
  motion_targets:
    - "rain streaks on window"
    - "subtle steam rising from coffee"
    - "soft light shifts on surfaces"
  static_targets:
    - "the character (same posture, same expression)"
    - "dessert plates and cups"
    - "interior structure"
```

**deepfocus365（deep focus × deep house）**:
```yaml
veo:
  motion_targets:
    - "subtle monitor screen glow shifts"
    - "slow steam from coffee mug"
    - "slight character breathing"
  static_targets:
    - "the character (same posture)"
    - "keyboard and monitor frame"
    - "books and desk objects"
```

**bobble（cafe ambience）**:
```yaml
veo:
  motion_targets:
    - "subtle steam from coffee"
    - "soft light shifts"
  static_targets:
    - "the character"
    - "cups, plates, and counter items"
```

### freeform プロンプトガイドライン（後方互換）

`default_prompt` を直接書く旧方式。structured が使えない場合のみ。

**基本テンプレート**:
```
Static scene with only natural subtle movements: [シーン固有の動き].
No smoke, no magical effects, no particles, no falling objects.
Keep the scene calm and grounded, like a living painting.
```

**避けるべき表現**:
- smoke, particles, falling leaves（不自然な追加要素が生成される）
- magical effects（原画にない要素が追加される）
- butterflies, insects（描画品質が低く不自然になる）
- dramatic movement（BGM チャンネルには過度な動き）

### サードパーティ IP ガードレール

Veo 3.1 は画像内容からディズニー等の IP を認識すると **生成をブロック** する。
PD（パブリックドメイン）の童話キャラでも、ディズニー版に似た見た目だと弾かれる。

| 画像タイプ | 結果 |
|-----------|------|
| オリジナルファンタジーキャラ | OK |
| PD 騎士・魔法使い（ジャンヌ・ダルク等） | OK |
| ラプンツェル（金髪ロングヘア+塔） | NG（Tangled 誤認） |
| 白雪姫風・人魚姫風 | 要テスト（NG の可能性あり） |

**ブロックされた場合の対策**:
- プロンプト変更では回避不可（画像自体が判定される）
- 背景のみの画像を別途生成して Veo に渡す
- または静止画背景のまま運用

### 設定

skill-config (`.claude/skills/loop-video/config.default.yaml`) で管理。チャンネル側上書きは `config/skills/loop-video.yaml`:

ループ動画化を停止したいチャンネルは 1 行で無効化できる:

```yaml
# config/skills/loop-video.yaml
enabled: false  # default: true。/loop-video は fail-loud 停止、/videoup は静止背景を使用
```

```yaml
veo:
  model: "veo-3.1-fast-generate-001"

  # structured prompt（推奨）
  motion_targets:
    - "slow leaves swaying"
    - "subtle steam rising from coffee"
  static_targets:
    - "the character"
    - "two animals (count remains 2)"

  # freeform プロンプト（後方互換、structured 未指定時のみ使用）
  default_prompt: |
    Static scene with only natural subtle movements...

  duration_seconds: 8
  crossfade_sec: 0.5
```

| 項目 | 既定 | 説明 |
|---|---|---|
| `enabled` | `true` | このチャンネルでループ動画化を行うか。`false` で CLI は fail-loud 停止（Veo 課金防止）、`/videoup` は静止画背景にフォールバック |
| `veo.model` | veo-3.1-fast-generate-001 | Veo API モデル（選択肢: veo-3.1-fast-generate-001 / veo-3.1-generate-001 / veo-3.1-lite-generate-preview） |
| `veo.motion_targets` | `[]` | 動かす対象のリスト。structured prompt に展開される |
| `veo.static_targets` | `[]` | 固定対象のリスト。count や shape を肯定文で書く |
| `veo.prompt_template` | 公式 5 要素テンプレ | `{motion_clause}` / `{static_clause}` / `{base_rules}` をプレースホルダに持つ |
| `veo.base_rules` | アンビエンス固定文 | `{base_rules}` に差し込まれる共通追加ルール |
| `veo.default_prompt` | 汎用微動プロンプト | structured 未使用時の freeform プロンプト |
| `veo.duration_seconds` | 8 | 生成尺（Veo API 制約で 8 秒固定） |
| `veo.crossfade_sec` | 0.5 | FFmpeg ループ補正のクロスフェード秒数 |
| `compression.enabled` | `true` | Veo 出力直後に libx264 で再エンコードして容量削減（Issue #175）。`false` で完全 skip |
| `compression.crf` | 22 | H.264 CRF。22 で約 40% 削減、24 なら約 55% 削減（攻める設定） |
| `compression.preset` | slow | libx264 preset |

## Integration

`loop.mp4` が `10-assets/` に存在すると、`generate_videos.sh` v11.0 が自動検出し、
静止画の代わりにループ動画を背景として使用します（24fps、CRF 20）。

パイプラインは **Veo 生成 → strip_audio → CRF 圧縮**（`compression.enabled=true` のとき）。
`--smooth` 経路でも同じ crf/preset が適用されるため、`/loop-video` → `--smooth` のいずれの順でも
最終的な `loop.mp4` ビットレートは設定値（既定 CRF 22 ≒ 3〜4 Mbps）に揃う。

## 長時間処理の取り扱い

`yt-generate-loop-video` は Veo 3.1 API を同期ポーリングするため **30〜90 秒** 程度（モデルとリージョン次第）かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。

spawn 例:

```bash
uv run yt-generate-loop-video <collection-path> -y > /tmp/loop-video-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ Veo 3.1 でループ動画を生成中（推定 30〜90 秒）。完了まで他の質問にもお答えできます。
> ログ: /tmp/loop-video-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "loop-video" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "loop-video"` + `cmux notify --title "loop-video 完了"` を呼ぶ（非 cmux 環境では skip）。

完了通知が届いたらログ末尾から結果サマリー（`10-assets/loop.mp4` のパス）をユーザーへ返す。`--smooth` 再実行時も同じパターンで起動する。IP ガードレールでブロックされた場合のエラーメッセージはログから抜き出して報告する。

## Next Step

ループ動画生成後:
→ `/videoup <collection-path>` でマスター動画を生成

## 参考リンク

- [Ultimate prompting guide for Veo 3.1 (Google Cloud Blog)](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1)
- [Veo prompt guide (Google DeepMind)](https://deepmind.google/models/veo/prompt-guide/)
