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
| `audio.target_duration_min` | (未設定) | `yt-generate-master` で `--loop` / `--target-duration` 両方未指定時に `--target-duration MIN` 相当のデフォルトとして採用される目標尺（分）。チャンネル単位で「最低尺」を宣言したいときに設定する |
| `audio.shuffle` | `false` | `yt-generate-master` で CLI `--shuffle` / `--shuffle-seed` 未指定時に `--shuffle` 相当のデフォルトとして採用される。Suno で同一プロンプトから生成した類似イントロ群がマスター後半で連続するのを避けたいときに `true` にする |
| `audio.shuffle_seed` | (未設定) | シャッフルの再現性 seed（整数）。`audio.shuffle: true` のときに CLI `--shuffle-seed` 未指定なら採用される。seed 単独設定では shuffle を有効化しない（skill-config は永続設定のため誤動作防止に明示要求とする / CLI の暗黙有効化とは挙動が異なる） |
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
| `yt-generate-master --loop N` | マスター生成時に全トラックを N 回繰り返して結合 | `yt-generate-master --loop 3` |
| `yt-generate-master --target-duration MIN` | 目標尺 (分) 以上になる最小ループ回数を自動算出 | `yt-generate-master --target-duration 150` |
| `yt-generate-master --shuffle` | 連結前に MP3 リストをシャッフル（OS entropy で seed 自動生成、stdout に `[Shuffle] seed=<N>` を出力） | `yt-generate-master --shuffle` |
| `yt-generate-master --shuffle-seed N` | シャッフル順を固定（`--shuffle` を暗黙有効化、再現性検証用） | `yt-generate-master --shuffle-seed 42` |
| (skill-config) `audio.target_duration_min` | CLI フラグ未指定時のデフォルト目標尺（分）。`config/skills/masterup.yaml` で設定 | `target_duration_min: 120` |
| (skill-config) `audio.shuffle` | CLI フラグ未指定時のデフォルトシャッフル設定 | `shuffle: true` |
| (skill-config) `audio.shuffle_seed` | `audio.shuffle: true` 時のデフォルト seed（整数） | `shuffle_seed: 42` |

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
yt-generate-master --loop 3                 # 全トラックを 3 回繰り返して結合
yt-generate-master --target-duration 150    # 150 分以上になる最小ループ回数を自動算出
yt-generate-master --shuffle                # ループ展開前にトラック順をランダム化
yt-generate-master --shuffle-seed 42        # 再現性 seed 指定（--shuffle を暗黙有効化）
```

`02-Individual-music/` の MP3 を自動検出し、skill-config の `audio.crossfade_duration` / `audio.bitrate` でクロスフェード結合します。metadata_generator のタイムスタンプ計算と同じ設定値を参照するため、実音声と description のタイムスタンプが常に一致します。
**この処理は常にダウンロード後に自動実行する。**

**ループ時の注意**: `--loop` / `--target-duration` は Suno/Lyria のトラック数が少ないコレクションで raw master の尺を target に届かせるためのオプション。`--loop` と `--target-duration` は同時指定不可。`metadata_generator` が生成する YouTube タイムスタンプは現状 **1 ループ分のみ** なので、動画尺が timestamp 末尾より長くなる（DJ セット動画では許容範囲。複数ループを timestamp に反映したい場合は別途 issue 化）。

**シャッフル時の注意**: `--shuffle` はループ展開の**前**に 1 回だけ実行され、シャッフルされた順序がループごとに同じ並びで N 回繰り返される（ループごとに独立してシャッフルし直すわけではない）。再現性が必要な場合は `--shuffle-seed N` を指定するか、`--shuffle` 単独実行時に stdout に出る `[Shuffle] seed=<N>` の値を控えておけば後で同じ並びを再現できる。再現性ログは `--quiet` 指定時も常に出力される。

### Step 5.5: 雨音レイヤー（オプション）

`branding/rain_layers/rain_*.wav` を持つチャンネルでは、マスター生成後に雨音をレイヤーする:

```bash
yt-finalize-master                       # CWD がコレクションディレクトリ
yt-finalize-master <collection-path>     # 明示指定
```

`branding/rain_layers/` ディレクトリが無い／`rain_*.wav` が 0 件のチャンネルでは何もせず exit 0（pass-through）。
レイヤー音量・フェードイン・loudnorm target は skill-config の `rain_layer:` namespace で制御する。`master.mp3` は `master.tmp.mp3` 経由 atomic rename で in-place 上書きされる（pass2 失敗時は元 master が保護される）。

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
