---
name: videoup
description: Use when コレクションの音声ファイルが揃い、動画生成が必要なとき。マスター音源生成（generate_master.sh）とマスター動画生成（generate_videos.sh）の実行案内。動画変換、音声から動画への変換、generate_videos、MP3→MP4、videoup など、動画ファイル生成に関わる場面で必ず使用すること
---

## Overview

`automation/` の共有スクリプトを使ってマスター音源と動画を生成します。
スクリプトは毎回生成せず、既存の汎用スクリプトを実行します。

## Scripts

| スクリプト | 役割 | 場所 |
|-----------|------|------|
| `generate_master.sh` | 個別 MP3 → クロスフェード結合 → マスター MP3 | `.claude/skills/masterup/references/generate_master.sh` |
| `generate_videos.sh` | 音声 + サムネイル → MP4 動画 | `.claude/skills/videoup/references/generate_videos.sh` |

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `bash "$(git rev-parse --show-toplevel)/.claude/skills/masterup/references/generate_master.sh"` | CWD のコレクションでマスター音源生成 |
| `bash "$(git rev-parse --show-toplevel)/.claude/skills/masterup/references/generate_master.sh" <path>` | 指定コレクションでマスター音源生成 |
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
2. **マスター音源**: `master-mix.wav` が既にあればスキップ。なければ `/masterup` でのマスター音源生成を案内（DAW ミックス済みの場合は `generate_master.sh` を直接実行も可）
3. **ループ動画背景**: `10-assets/loop.mp4` が既にあればスキップ。なければ `/loop-video` でのループ動画生成を案内。`loop.mp4` があると `generate_videos.sh` が自動的に動画背景を使用（静止画の代わり）
4. **動画生成**: `generate_videos.sh` の実行コマンドを案内
5. **workflow-state.json 更新**: `production.generated = true` に更新

### 自動検出される要素

スクリプトはコレクションのディレクトリ構造から以下を自動検出します:

- **コレクション名**: ディレクトリ名から（`YYYYMMDD-xxx-theme-collection` → `Theme-Name`）
- **マスター音声**: `master-mix.wav` 優先、`*-Master.mp3` フォールバック
- **サムネイル**: `10-assets/main.png` 優先、`thumbnail.jpg` フォールバック
- **個別音楽**: `02-Individual-music/*.mp3`（アルファベット順）

### 重要

- **スクリプトを毎回生成しない** — `automation/` の共有スクリプトを使用
- ユーザーが DAW でミックスした `master-mix.wav` がある場合、`generate_master.sh` は不要
- `set -e` は使用しない（明示的エラーハンドリング）

## Next Step

動画生成後:
→ `/description <collection-path>` でYouTube概要欄を生成
