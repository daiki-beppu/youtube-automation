---
name: masterup
description: Use when /suno で生成したプロンプトを Suno UI で曲にしたあと、そのプレイリストを DL + クロスフェードマスター化したいとき。前工程: /suno（プロンプト生成 → Suno UI で人手楽曲生成）。プレイリスト URL を指定して MP3 一括 DL + マスター音源を自動生成（次工程: /videoup）。Lyria チャンネルでは /lyria が自動で音源を出力するため本スキルは不要
---

## Overview

SunoAI プレイリストURLから楽曲を一括ダウンロードし、クロスフェード結合でマスター音源を自動生成するまでの一連フローを実行します。

## 設定

動作パラメータは skill-config (`.claude/skills/masterup/config.default.yaml`) で管理。
チャンネル側で上書きする場合は `config/skills/masterup.yaml`:

| 項目 | 既定 | 説明 |
|---|---|---|
| `audio.crossfade_duration` | 1.0 | トラック間クロスフェード秒数（metadata_generator のタイムスタンプ計算で参照） |
| `audio.bitrate` | "192k" | マスター音源のビットレート |
| `suno_download.cdn_url_template` | `https://cdn1.suno.ai/{song_id}.mp3` | Suno CDN URL テンプレート |

マスター音源生成は `yt-generate-master` CLI が同じ skill-config を読み込むため、`audio.crossfade_duration` は実音声のクロスフェードと metadata_generator のタイムスタンプ計算で常に一致する。

## When to Use

**前工程:** `/suno`（プロンプト生成 → Suno UI で人手楽曲生成）

- `/suno` のプロンプトで生成した楽曲のプレイリストを作成したとき
- SunoAI の楽曲を MP3 でダウンロードしたいとき
- マスター音源（Complete Collection 用）を生成したいとき

Lyria で音源を生成するチャンネルでは `/lyria` が master.wav を直接出力するため本スキルは不要。

## Quick Reference

| コマンド | 説明 | 例 |
|---------|------|-----|
| `/masterup <playlist-url>` | プレイリスト内の全曲をDL + マスター生成 | `/masterup https://suno.com/playlist/xxx` |

## Instructions

あなたは SunoAI 楽曲ダウンロード & マスターアップマネージャーです。

### 引数の解釈

```
$ARGUMENTS
```

- 第1引数: SunoAI プレイリストURL（必須）

### 前提条件

- WebFetch ツールが利用可能であること
- アクティブなコレクションの `02-Individual-music/` ディレクトリが存在

### Step 1: コレクションの特定

1. `collections/planning/` の `workflow-state.json` を検索
2. `music.generated = true` かつ `music.approved = false` のコレクションを対象
3. 複数ある場合はユーザーに選択を促す

### Step 2: WebFetch でプレイリスト情報を取得

1. 引数のプレイリストURLを WebFetch で取得
2. prompt で全曲の情報を抽出するよう指示:
   - タイトル
   - Song ID（UUID）
   - 再生時間
3. WebFetch の結果から曲リストをパースして Step 3 に渡す

### Step 3: MP3 ダウンロード（CDN curl）

各曲について:
1. Song ID から CDN URL を生成: `https://cdn1.suno.ai/{song_id}.mp3`
2. `curl` でダウンロードし `02-Individual-music/` に保存
3. ファイル名: 連番 + タイトルから生成（例: `01-pattern-a-arrival.mp3`）

```bash
curl -L -o "02-Individual-music/{filename}.mp3" "https://cdn1.suno.ai/{song_id}.mp3"
```

**注意**: CDN URL は public だが永続性は不明。生成後なるべく早めにダウンロードすること。1ファイル約2-3MB。

### Step 4: 結果レポート

- ダウンロード成功した曲リスト（タイトル・Song ID・再生時間）
- 合計ファイル数とサイズ
- `02-Individual-music/` のファイル一覧

### Step 5: マスター音源生成（CLI）

ダウンロード完了後、`yt-generate-master` CLI でマスター音源を自動生成:

```bash
yt-generate-master                          # CWD がコレクションディレクトリのとき
yt-generate-master <collection-path>        # 明示指定
```

`02-Individual-music/` の MP3 を自動検出し、skill-config の `audio.crossfade_duration` / `audio.bitrate` でクロスフェード結合します。metadata_generator のタイムスタンプ計算と同じ設定値を参照するため、実音声と description のタイムスタンプが常に一致します。
**この処理は常にダウンロード後に自動実行する。**

### Step 6: ワークツリー実行時のメインへのコピー

git worktree 内で実行している場合（パスに `.claude/worktrees/` を含む場合）、生成した音源ファイルをメインワークツリーにもコピーする。

1. ワークツリーのコレクションパスからメインのコレクションパスを算出:
   - ワークツリー: `.../.claude/worktrees/<name>/collections/...`
   - メイン: `.../collections/...`（`.claude/worktrees/<name>/` 部分を除去）
2. メイン側に `01-master/` と `02-Individual-music/` ディレクトリを作成
3. `01-master/` と `02-Individual-music/` の全ファイルをコピー

```bash
# パス算出例
WORKTREE_PATH="/path/.claude/worktrees/branch-name/collections/..."
MAIN_PATH="${WORKTREE_PATH/.claude\/worktrees\/*/collections/...}"
```

**この処理は常にマスター生成後に自動実行する（ワークツリー実行時のみ）。**

### 完了時の更新

- `workflow-state.json` の `music.approved = true` に更新
- `mp3_count` にダウンロード曲数を記録
- `master_audio` に `"master.mp3"` を記録
- `updated_at` を現在時刻に更新
- `phase` を `"music-approved"` に更新

## CDN URL パターン

| 形式 | URL | 認証 |
|------|-----|------|
| MP3 | `https://cdn1.suno.ai/{song_id}.mp3` | 不要 |

## Next Step

→ `/videoup` で動画生成を実行
