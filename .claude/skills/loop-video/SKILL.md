---
name: loop-video
description: Use when コレクションのサムネイル画像からループ動画背景を生成したいとき。Veo 3.1 API で main.png/jpg を元に微細アニメーション付きの 8秒シームレスループ動画を生成。ループ動画、背景動画、loop.mp4、アニメーション背景、動画背景など、静止画を動画化する場面で必ず使用すること
---

## Overview

Veo 3.1 API を使い、コレクションの `main.png/jpg` から 8秒のシームレスループ動画を生成します。
生成された `loop.mp4` は `generate_videos.sh` が自動検出し、静止画の代わりに動画背景として使用します。

## Script

| スクリプト | 役割 | 場所 |
|-----------|------|------|
| `generate_loop_video.py` | main.png/jpg → 8秒ループ動画 (Veo 3.1) | `automation/generate_loop_video.py` |

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `python3 automation/generate_loop_video.py <collection-path> -y` | 指定コレクションでループ動画生成 |
| `python3 automation/generate_loop_video.py -y` | CWD のコレクションでループ動画生成 |
| `python3 automation/generate_loop_video.py <path> --prompt "..." -y` | カスタムプロンプトで生成 |
| `python3 automation/generate_loop_video.py <path> --smooth -y` | 生成後に FFmpeg クロスフェード補正 |

## Instructions

### 対象コレクション

```
$ARGUMENTS
```

引数が指定されている場合、そのコレクションを対象とします。
未指定の場合、`collections/planning/` から `thumbnail.approved = true` かつ `loop.mp4` が未生成のコレクションを自動検出します。

### 前提条件

- `10-assets/main.png` または `main.jpg` が存在すること（サムネイル生成済み）
- `GEMINI_API_KEY` が `.env` に設定されていること

### ステップ

1. **対象確認**: `10-assets/` に `main.png` or `main.jpg` があることを確認
2. **プロンプト検討**: シーンに応じた自然な動きを指定
   - デフォルトプロンプトは `channel_config.json` の `veo.default_prompt` を使用
   - シーンに合わない場合は `--prompt` でカスタマイズ
3. **生成実行**: `python3 automation/generate_loop_video.py <collection-path> -y`
4. **品質確認**: ユーザーに `loop.mp4` を確認してもらう
5. **ループ確認**: 継ぎ目が気になる場合は `--smooth` で再実行

### プロンプトガイドライン

**基本テンプレート**:
```
Static scene with only natural subtle movements: [シーン固有の動き].
No smoke, no magical effects, no particles, no falling objects.
Keep the scene calm and grounded, like a living painting.
```

**効果的な動き（シーンに応じて選択）**:
- 蝋燭・火の揺らぎ（室内シーン）
- キャラクターの呼吸・微細な動き
- 光の移ろい・影の変化
- 花や木が風で揺れる（屋外・庭園シーン）
- 雲がゆっくり流れる（空が見えるシーン）
- 水面の揺らぎ（水辺シーン）

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

`channel_config.json` の `veo` セクション:

```json
{
  "veo": {
    "model": "veo-3.1-lite-generate-preview",
    "default_prompt": "...",
    "duration_seconds": 4,
    "crossfade_sec": 0.5
  }
}
```

## Integration

`loop.mp4` が `10-assets/` に存在すると、`generate_videos.sh` v11.0 が自動検出し、
静止画の代わりにループ動画を背景として使用します（24fps、CRF 20）。

## Next Step

ループ動画生成後:
→ `/videoup <collection-path>` でマスター動画を生成
