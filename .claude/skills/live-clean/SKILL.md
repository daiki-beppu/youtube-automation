---
name: live-clean
description: "Use when live コレクションの大容量メディアを削除して容量回復するとき、または collections 配下の tmp/ 残骸を掃除するとき。「容量」「クリーンアップ」「live 整理」「でかいファイル」「tmp 掃除」「残骸」で発動"
---

## Overview

`collections/live/` 配下の公開済みコレクションから、YouTube にアップロード済み or 再生成可能な大容量メディアファイルを安全に削除し、ディスク容量を回復する。あわせて、`collections/` 配下（live に限らず planning 等も含む）に残った `tmp/` ディレクトリ残骸の掃除モードを持つ。

いずれのモードも「スキャン → ドライラン表示 → 明示承認 → 削除 → 結果レポート」の同一安全フローに従い、承認なしの削除は絶対に行わない。

## 設定読み込みゲート

Quick Reference や Step 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない（削除対象 / 保護パターンは特に）。

1. `.claude/skills/live-clean/config.default.yaml`
2. `config/skills/live-clean.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("live-clean")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う（リストは丸ごと置換）。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

以下を確認し、満たさなければ案内して終了する（外部 API・認証には依存しないローカル操作）:

- 実行場所がチャンネルリポジトリ（`CHANNEL_DIR`）配下で、`collections/` ディレクトリが存在すること。無ければ対象なしとして終了する
- 通常モードでは `collections/live/*/workflow-state.json` を持つ公開済みコレクションが 1 件以上存在すること。無ければ削除対象なしとして終了し、公開前なら `/video-upload` が前工程であることを案内する（削除可否は Step 1 の 3 条件 — `stage: "live"` / `phase: "complete"` / `upload.video_id` 非空 — で機械判定する）
- `workflow-state.json` が読めない / JSON 破損のコレクションは安全条件未達としてスキップし、削除しない

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| なし | 全 live コレクションをスキャン | `/live-clean` |
| テーマ名 | 部分一致でフィルタ | `/live-clean harbor` |
| `tmp` | collections 配下の tmp/ 残骸を掃除（後述の tmp/ 残骸クリーンアップモード） | `/live-clean tmp` |

`$ARGUMENTS` が `tmp` の場合は Step 1〜5 を実行せず、「tmp/ 残骸クリーンアップモード」セクションへ分岐する。

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

安全性検証を通過したコレクションについて、skill-config `delete_patterns`（既定値と各パターンの理由コメントは `config.default.yaml` 参照）に一致するファイルの存在とサイズを確認する。

```bash
# 各コレクションディレクトリで実行（delete_patterns の内容に合わせて展開する。以下は既定値の例）
du -sh 01-master/master.mp3 01-master/master-mix.wav 01-master/*-Master.mp4 02-Individual-music/*.mp3 10-assets/loop_normalized.mp4 2>/dev/null
```

**削除対象**: skill-config `delete_patterns`（YouTube に存在 or 再生成可能なもののみ。既定: raw マスター / ミックスダウン wav / YouTube マスター動画 / 個別ソーストラック / 正規化キャッシュ）

**絶対に削除しないファイル**: skill-config `protect_patterns`（既定: `workflow-state.json` / `10-assets/main.png|jpg` / `10-assets/thumbnail.jpg|png` / 再生成不可のオリジナル `10-assets/loop.mp4` / `20-documentation/*`）。`delete_patterns` と重なった場合は `protect_patterns` が優先。

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

表示後、AskUserQuestion で確認を取る。質問文には削除対象の実数(「削除対象: N コレクション / M ファイル / X.X GB」)と「削除は取り消せません（rm -f による物理削除）」を含め、選択肢は「削除を実行する」「キャンセル」の明示 2 択とする(デフォルトを実行側にしない)。「削除を実行する」が明示的に選ばれた場合のみ Step 4 へ進む。それ以外の応答（自由文・別話題・無回答）はすべてキャンセル扱いとし、絶対に削除を実行しない。AskUserQuestion 非対応環境(Codex 等)では同内容をテキストで提示し、ユーザーからの明示的な承認発言を待つ。無応答・曖昧な返答のまま Step 4 に進んではならない。

### Step 4: 削除実行

「削除を実行する」が明示的に選ばれた場合のみ、skill-config `delete_patterns` に一致するファイルをファイル単位で `rm -f` する（以下は既定値の例）。

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

## tmp/ 残骸クリーンアップモード（`/live-clean tmp`）

`collections/` 配下の各コレクションディレクトリに残った `tmp/` ディレクトリ（中間生成物・作業ファイルの残骸）を、一覧提示 → 明示承認のうえで除去する。live に限らず `collections/planning/` 等の全ステージが対象。

### 対象と判定基準

**削除対象:**
- `collections/` 配下でディレクトリ名が **正確に `tmp`** のディレクトリとその中身（下記コマンドで検出されたもの）

**削除対象外（検出されても必ずスキップ）:**
- `<CHANNEL_DIR>/tmp/`（channel ルート直下）。`tmp/veo-operations/`（Veo 中断 resume 用 state）と `tmp/lyria-recovered/`（Lyria 退避音源）は各 skill が管理する復旧用データであり、本モードのスコープ外
- symlink（`find -type d` は symlink を辿らないため通常は検出されないが、万一 symlink が対象に含まれた場合は削除せず報告のみ）

### 手順

**T1: スキャン**

```bash
find collections -type d -name tmp
```

検出 0 件なら「tmp/ 残骸なし」と報告して終了する。検出があれば各 tmp/ について中身とサイズを確認する:

```bash
du -sh <検出パス>
find <検出パス> -type f | head -20
```

**T2: ドライラン表示**

```
tmp/ 残骸クリーンアップ — ドライラン
====================================
■ collections/planning/harbor-warehouse/tmp/   12 MB (8 files)
■ collections/live/rainy-cafe/tmp/             3.2 MB (2 files)
====================================
削除対象: N ディレクトリ / M ファイル / X.X MB
```

表示後、AskUserQuestion で確認を取る。質問文には削除対象の実数と「削除は取り消せません（物理削除）」を含め、選択肢は「削除を実行する」「キャンセル」の明示 2 択とする（デフォルトを実行側にしない）。「削除を実行する」が明示的に選ばれた場合のみ T3 へ進む。それ以外の応答（自由文・別話題・無回答）はすべてキャンセル扱いとし、絶対に削除を実行しない。AskUserQuestion 非対応環境（Codex 等）では同内容をテキストで提示し、ユーザーからの明示的な承認発言を待つ。

**T3: 削除実行**

`rm -rf` 禁止の方針は tmp/ 掃除でも維持する。tmp/ はディレクトリごと除去したいが、`rm -rf` の代わりに「ファイル単位 `rm -f` → 空になったディレクトリを `rmdir`」で行う。`rmdir` は空でないディレクトリに対して失敗するため、想定外のファイルを巻き込んで消すことがない:

```bash
# 承認された各 tmp/ ディレクトリに対して実行
find "<tmp-path>" -type f -exec rm -f {} +
find "<tmp-path>" -depth -type d -exec rmdir {} \;
```

`rmdir` が失敗した場合（隠しファイル等が残存）は、残存ファイルを提示して個別に判断を仰ぐ。無断で削除方法をエスカレートしない。

**T4: 結果レポート**

```
tmp/ 残骸クリーンアップ完了
==========================
■ collections/planning/harbor-warehouse/tmp/ 除去（12 MB 回復）
■ collections/live/rainy-cafe/tmp/ 除去（3.2 MB 回復）

合計回復容量: X.X MB
```

## 棲み分け

| 責務 | 担当 |
|------|------|
| live コレクションの大容量メディア削除（容量回復の本丸） | 本 skill の Step 1〜5 |
| collections 配下の tmp/ 残骸掃除（衛生維持） | 本 skill の tmp/ モード（`/live-clean tmp`） |
| `<CHANNEL_DIR>/tmp/veo-operations/` の resume state | /loop-video（不要時の手動削除手順は同 skill 参照） |
| `<CHANNEL_DIR>/tmp/lyria-recovered/` の退避音源 | /lyria |

tmp/ 掃除は「スキャン → ドライラン → 明示承認 → 削除 → レポート」という本 skill の既存安全フローと完全に同型であり、専用 CLI（yt-clean 等）を新設すると承認ゲートを CLI 側に再実装する重複が生じるため、本 skill への統合とした（#1671）。

## 障害時ガイダンス

ファイル削除はローカル操作で、外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 対象ファイル不在 | 削除対象が見つからない | 対象コレクションのパスを確認（外部サービスに依存しないため API 障害・quota の影響は受けない） |
