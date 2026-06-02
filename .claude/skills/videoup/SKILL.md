---
name: videoup
description: "Use when コレクションの音声ファイルが揃い、動画生成が必要なとき。マスター音源生成（yt-generate-master）とマスター動画生成（generate_videos.sh）の実行案内。動画変換、音声から動画への変換、generate_videos、MP3→MP4、videoup など、動画ファイル生成に関わる場面で必ず使用すること"
---

## Overview

`.claude/skills/` 配下の共有スクリプト（`yt-skills sync` で配布）を使ってマスター音源と動画を生成します。
スクリプトは毎回生成せず、既存の汎用スクリプトを実行します。

## Scripts

| スクリプト | 役割 | 場所 |
|-----------|------|------|
| `yt-generate-master` | 個別 MP3 → クロスフェード結合 → マスター MP3 | Python CLI (skill-config `masterup` 参照) |
| `generate_videos.sh` | 音声 + サムネイル → MP4 動画 | `.claude/skills/videoup/references/generate_videos.sh` |

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `yt-generate-master` | CWD のコレクションでマスター音源生成 |
| `yt-generate-master <path>` | 指定コレクションでマスター音源生成 |
| `bash "$(git rev-parse --show-toplevel)/.claude/skills/videoup/references/generate_videos.sh"` | CWD のコレクションで全動画生成（コレクションディレクトリ内で実行） |
| `bash "$(git rev-parse --show-toplevel)/.claude/skills/videoup/references/generate_videos.sh" <path>` | 指定コレクションで全動画生成 |

## Instructions

### 対象コレクション

```
$ARGUMENTS
```

引数が指定されている場合、そのコレクションを対象とします。
未指定の場合、`collections/planning/` から `music.approved = true` かつ `production.generated = false` のコレクションを自動検出します。

### ステップ

1. **対象コレクション確認**: `workflow-state.json` で状態確認
2. **マスター音源**: `master-mix.{wav,m4a,aac,mp3,flac}` が既にあればスキップ。なければ `/masterup` でのマスター音源生成を案内（DAW バウンス済みの場合は `master-mix.m4a` をそのまま配置可）
3. **ループ動画背景**: `10-assets/loop.mp4` が既にあればスキップ。
   `config/skills/loop-video.yaml::enabled: false` のチャンネルではループ動画化が無効化されているため、`/loop-video` を案内せず `10-assets/main.png` を静止背景として使用する。
   それ以外（`enabled` 未指定 or `true`）で `loop.mp4` が無ければ `/loop-video` でのループ動画生成を案内。
   `loop.mp4` があると `generate_videos.sh` が自動的に動画背景を使用（静止画の代わり）
4. **動画生成**: `generate_videos.sh` の実行コマンドを案内
5. **workflow-state.json 更新**: `production.generated = true` に更新

### 自動検出される要素

スクリプトはコレクションのディレクトリ構造から以下を自動検出します:

- **コレクション名**: ディレクトリ名から（`YYYYMMDD-xxx-theme-collection` → `Theme-Name`）
- **マスター音声**: `master-mix.{wav,m4a,aac,mp3,flac}` を優先順に検出（m4a/aac は `-c:a copy` で再エンコード回避）、`*-Master.mp3` フォールバック
- **サムネイル**: `10-assets/main.png` 優先、`thumbnail.jpg` フォールバック
- **個別音楽**: `02-Individual-music/*.mp3`（アルファベット順）

### 重要

- **スクリプトを毎回生成しない** — `.claude/skills/` 配下の共有スクリプトを使用
- ユーザーが DAW でミックスした `master-mix.{wav,m4a}` がある場合、`yt-generate-master` は不要
- `set -e` は使用しない（明示的エラーハンドリング）

### opt-in: 短尺 master の動画長指定再生 (#545)

`audio.target_duration_min` を小さく (例: 30 分) 保ちつつ動画は長尺で出したい場合、`config.default.yaml::audio.target_video_duration_min` (分) を設定すると `generate_videos.sh` が音声入力にも `-stream_loop -1` を適用し `-t <target>` で動画長を強制する。下流チャンネルの finalize encode 時間 (loudnorm + 雨音重ね 等) を短縮できる。

| 設定方法 | 例 | 優先 |
|---|---|---|
| 環境変数 | `VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN=120 bash .../generate_videos.sh ...` | 高 |
| チャンネル override | `config/skills/videoup.yaml` に `audio: { target_video_duration_min: 120 }` | 中 |
| 未設定 | (既定) | 従来動作 |

- master 尺 ≥ `target_video_duration_min × 60` のときは無視され従来動作になる (master 尺が支配)
- 音声 loop seam の crossfade は本機能のスコープ外 (将来拡張)

## 長時間処理の取り扱い

`generate_videos.sh` は ffmpeg を走らせるため **1〜10 分程度**（コレクション尺次第）かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。

spawn 例:

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/videoup/references/generate_videos.sh" \
  > /tmp/videoup-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ マスター動画生成を background 実行中（推定 N 分）。完了まで他の質問にもお答えできます。
> ログ: /tmp/videoup-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "videoup" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "videoup"` + `cmux notify --title "videoup 完了"` を呼ぶ（非 cmux 環境では skip）。

完了通知が届いたらログ末尾から結果サマリー（生成された `.mp4` のパス）をユーザーへ返す。失敗時は ffmpeg のエラー行を抜き出して報告する。

## オーディオビジュアライザー / オーバーレイについて

**現状: 未実装（feature 化を #511 で追跡中）**

`generate_videos.sh` は現時点で**オーディオビジュアライザー（波形・スペクトラム表示）や購読ボタンポップアップ等のオーバーレイ合成をサポートしていない**。出力は `THUMBNAIL`（静止画）または `loop.mp4`（ループ動画背景）に音声を重ねただけの動画になる。

### よくある誤解 (#646 feedback)

「Suno のデータ取り込み時にビジュアライザーを付けて」とユーザーが指示しても、ビジュアライザーは付かない。理由:

- `/suno` / `/lyria` / `/masterup` は**音源（mp3 / wav / m4a）を作る工程**であり、映像オーバーレイは扱わない
- ビジュアライザーは本質的に**動画生成（`generate_videos.sh`）側の合成処理**で、`ffmpeg` の `filter_complex` に `showfreqs` 等を組む必要がある
- 現状の `generate_videos.sh` v12.x にはこの filter 経路が無いため、どの工程でどう指示しても最終 MP4 にビジュアライザーは反映されない

### 正しい運用（実装されるまでの暫定）

- ビジュアライザーが必要な動画は、現状では `master-mix.{wav,m4a}` と `main.png` で `generate_videos.sh` を回した後、**外部ツール（DaVinci Resolve / After Effects / ffmpeg 手書きスクリプト）で別途オーバーレイ合成する**
- 自動化フローに取り込みたい場合は #511（`overlays.enabled` config-driven 合成）の進捗を待つ。マージされ次第、`config/channel/youtube.json::overlays.audio_visualizer.enabled: true` でチャンネル単位で有効化できるようになる予定

### Claude への指示時の注意

オペレーターから「ビジュアライザー付きで」「波形表示で」等の指示があった場合は、**この制約を即座に明示してから作業を進めること**。「Suno に指示しても載らない」「現状の videoup では合成できない」「#511 が必要」を伝えた上で、

- 静止画 / ループ動画のみで進めるか
- #511 の実装を待つか
- 外部ツールで後付けするか

をユーザーに選んでもらう。黙って静止画で生成すると今回のような FB（期待と実装の乖離）が再発する。

## Next Step

動画生成後:
→ `/video-description <collection-path>` でYouTube概要欄を生成
