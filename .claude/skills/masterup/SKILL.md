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
| `yt-fix-timestamps --dry-run` | テーマ別タイムスタンプの差分を表示（書き込みなし） | `uv run yt-fix-timestamps --dry-run` |
| `yt-fix-timestamps` | `descriptions.md` の Complete Collection タイムスタンプを実音声構成に合わせて修正 | `uv run yt-fix-timestamps` |
| `yt-fix-timestamps --only <substr>` | 対象コレクションを部分一致で絞り込み | `uv run yt-fix-timestamps --only empty-gallery` |

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

### Step 5.7: テーマ別タイムスタンプ整合性チェック・修正

マスター音源の構成（パターン別 MP3 ファイル順 / クロスフェード長）と `descriptions.md` の Complete Collection タイムスタンプが一致しているかを `yt-fix-timestamps` で検証・修正する。

```bash
uv run yt-fix-timestamps --dry-run             # まず差分を確認
uv run yt-fix-timestamps                        # 修正を適用
uv run yt-fix-timestamps --only <substr>        # 特定コレクションのみ対象（カンマ区切り可）
```

`--dry-run` で出力される新タイムスタンプと既存 `descriptions.md` を見比べ、差分があれば `--dry-run` を外して書き込む。

**no-op の条件**:

- 対象コレクションが CLI 内部の `TARGET_COLLECTIONS` リストに含まれない場合 → 何も処理されず正常終了
- `suno-prompts.md` / `02-Individual-music/` / `descriptions.md` のいずれかが欠けるコレクション → `skip (missing files)` を出して継続
- 既に正しいタイムスタンプが書かれている場合は再書き込みされるが差分は 0（実害なし）

**エラー時の挙動**: `process()` 内の例外（パターン解析失敗・コードフェンス検出失敗など）はコレクション単位で捕捉され `❌ <collection>: <error>` を出力した上で次のコレクションへ進む。**ユーザーへ通知し、原因（pattern letter 不一致 / fence 未検出など）を `20-documentation/` の元データを直して再実行すること**。Step 6 のコピーへ進む前に必ず修正を完了する。

**CLI 単体実行は引き続き残す**: バッチ補修や CI から呼ぶ用途では `/masterup` を経由せず `uv run yt-fix-timestamps` を直接実行できる（`pyproject.toml` の `[project.scripts]` に登録されたまま）。

**この処理は常にマスター生成（および雨音レイヤー）完了後、ワークツリーコピー前に自動実行する。**

### Step 6: ワークツリー実行時のメインへのコピー

git worktree 内で実行している場合、生成したコレクション成果物をメインリポジトリにも同期する。
個別ディレクトリだけコピーする方式は将来ファイル種別が増えるたび漏れが発生するため、**コレクションディレクトリ全体を `rsync -a` で同期**する（`01-master/`・`02-Individual-music/`・`03-Individual-movie/`・`10-assets/`・`20-documentation/`・`workflow-state.json` などすべて含む）。

1. ワークツリー検出: `git rev-parse --git-common-dir` を使う。値が `.git` または `<toplevel>/.git` ならメインリポジトリ実行なのでスキップ。
2. メインリポジトリのルートを算出: `git_common_dir` を起点に `git rev-parse --show-toplevel` を再実行。
3. ワークツリールートからのカレントコレクション相対パスを使ってメイン側の目的地パスを構築。
4. `mkdir -p` で目的地を作成し、`rsync -a` でコレクションディレクトリ全体をコピー。

```bash
WORKTREE_COLLECTION="$(pwd)"   # コレクションディレクトリで実行している前提
GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"

if [[ "$GIT_COMMON_DIR" == ".git" || "$GIT_COMMON_DIR" == "$WORKTREE_ROOT/.git" ]]; then
    echo "メインリポジトリで実行中。コピーは不要です。"
else
    MAIN_REPO="$(cd "$GIT_COMMON_DIR" && git rev-parse --show-toplevel)"
    REL_PATH="${WORKTREE_COLLECTION#"$WORKTREE_ROOT"/}"
    MAIN_COLLECTION="$MAIN_REPO/$REL_PATH"
    mkdir -p "$MAIN_COLLECTION"
    rsync -a "$WORKTREE_COLLECTION/" "$MAIN_COLLECTION/"
fi
```

**`--delete` を付けない理由**: メイン側で `/thumbnail` や `/loop-video` 等によって先行生成された素材（例: `10-assets/main.png`, `10-assets/loop.mp4`）が worktree 側に存在しないことがあり、`--delete` を付けるとそれらが消えてしまう。worktree 側で新規追加されたファイルだけメインに上書き反映する片方向追加同期で十分。

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

## 長時間処理の取り扱い

`yt-generate-master`（ffmpeg クロスフェード結合）は **30 秒〜2 分** 程度かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。

spawn 例:

```bash
yt-generate-master > /tmp/masterup-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ マスター音源生成を background 実行中（推定 1〜2 分）。完了まで他の質問にもお答えできます。
> ログ: /tmp/masterup-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "masterup" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "masterup"` + `cmux notify --title "masterup 完了"` を呼ぶ（非 cmux 環境では skip）。

`curl` での MP3 一括ダウンロード（Step 3）も曲数が多いと数十秒〜分単位かかるため、同じ background パターンで起動してよい。完了通知が届いたらログ末尾から結果サマリー（`master.mp3` のパス、ダウンロード成功曲数）をユーザーへ返す。

## Next Step

→ `/videoup` で動画生成を実行
