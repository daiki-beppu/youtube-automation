---
name: live-clean
description: "Use when live コレクションの大容量メディアを削除して容量回復するとき。「容量」「クリーンアップ」「live 整理」「でかいファイル」で発動"
---

## Overview

`collections/live/` 配下の公開済みコレクションから、YouTube にアップロード済み or 再生成可能な大容量メディアファイルを安全に削除し、ディスク容量を回復する。

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| なし | 全 live コレクションをスキャン | `/live-clean` |
| テーマ名 | 部分一致でフィルタ | `/live-clean harbor` |

## Instructions

### Step 1: スキャン & 安全性検証

`collections/live/*/workflow-state.json` を Glob で列挙し、各ファイルを Read で読み込む。

以下の **3条件すべて** を満たすコレクションのみクリーンアップ対象とする:

1. `stage` が `"live"`
2. `phase` が `"complete"`
3. `upload.video_id` が存在し、空文字でない

条件を満たさないコレクションはスキップし、理由を表示する。

`$ARGUMENTS` が指定されている場合は、コレクションのディレクトリ名に対する部分一致でフィルタする。

### Step 2: 削除対象ファイルの特定

安全性検証を通過したコレクションについて、以下のファイルの存在とサイズを確認する。

```bash
# 各コレクションディレクトリで実行
du -sh 01-master/master.mp3 01-master/master-mix.wav 01-master/*-Master.mp4 02-Individual-music/*.mp3 10-assets/loop_normalized.mp4 2>/dev/null
```

**削除対象（YouTube に存在 or 再生成可能）:**

| ファイル | 理由 |
|---------|------|
| `01-master/master.mp3` | raw マスター（個別トラックから再生成可能） |
| `01-master/master-mix.wav` | ミックスダウン済み（DAW で再生成可能） |
| `01-master/*-Master.mp4` | YouTube マスター動画（YouTube に存在） |
| `02-Individual-music/*.mp3` | 個別ソーストラック（Suno から再取得可能） |
| `10-assets/loop_normalized.mp4` | 正規化キャッシュ（loop.mp4 から再生成可能） |

**絶対に削除しないファイル:**
- `workflow-state.json`
- `10-assets/main.png`, `10-assets/main.jpg`
- `10-assets/thumbnail.jpg`, `10-assets/thumbnail.png`
- `10-assets/loop.mp4`（オリジナル、再生成不可）
- `20-documentation/*` 全ファイル

削除対象ファイルが 1 つもないコレクションは「クリーンアップ済み」として表示する。

### Step 3: ドライラン表示

削除実行前に、必ず以下の形式でサマリーを表示する:

```
Live Collection クリーンアップ — ドライラン
============================================

■ Harbor Warehouse (harbor-warehouse)
  YouTube: https://www.youtube.com/watch?v=fbn_dSPzySk
  削除対象:
    01-master/master.mp3                 217 MB
    01-master/master-mix.wav             1.5 GB
    01-master/Harbor-Warehouse-Master.mp4 7.8 GB
    02-Individual-music/ (24 files)      169 MB
  小計: 9.7 GB

============================================
削除対象: N コレクション / M ファイル / X.X GB
クリーンアップ済み: N コレクション
安全条件未達（スキップ）: N コレクション
```

表示後、AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない。

### Step 4: 削除実行

ユーザーが承認した場合のみ、ファイル単位で `rm -f` を実行する。

```bash
# マスターファイル
rm -f "collections/live/<dir>/01-master/master.mp3"
rm -f "collections/live/<dir>/01-master/master-mix.wav"
rm -f collections/live/<dir>/01-master/*-Master.mp4

# 個別トラック
rm -f collections/live/<dir>/02-Individual-music/*.mp3

# キャッシュ
rm -f "collections/live/<dir>/10-assets/loop_normalized.mp4"
```

**禁止事項:**
- `rm -rf` は絶対に使わない
- ディレクトリ自体は削除しない（空のまま保持）

### Step 5: 結果レポート

```
クリーンアップ完了
==================
■ Harbor Warehouse: 9.7 GB 回復
  - 01-master/: 3 files deleted
  - 02-Individual-music/: 24 files deleted

合計回復容量: X.X GB
```

最後に live ディレクトリ全体のディスク使用量を表示:

```bash
du -sh collections/live/
```

## 障害時ガイダンス

ファイル削除はローカル操作で、外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 対象ファイル不在 | 削除対象が見つからない | 対象コレクションのパスを確認（外部サービスに依存しないため API 障害・quota の影響は受けない） |
