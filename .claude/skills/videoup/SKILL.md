---
name: videoup
description: "Use when 音声ファイルが揃い動画生成が必要なとき。「動画変換」「MP3→MP4」「generate_videos」「videoup」で発動。マスター音源・マスター動画生成を案内。YouTube への投稿は /video-upload"
---

## Overview

`.claude/skills/` 配下の共有スクリプト（`yt-skills sync` で配布）を使ってマスター音源と動画を生成します。
スクリプトは毎回生成せず、既存の汎用スクリプトを実行します。

前工程はマスター音源の用意: Suno 系チャンネルは `/masterup`、Lyria 系チャンネルは `/lyria`（`/masterup` 不要）でマスター音源を生成してから本スキルを実行する。

## 完了条件

`01-master/` にマスター動画（例: `Theme-Name-Master.mp4`）が生成され、`workflow-state.json` の `assets.master_video` に動画ファイル名が記録されたとき完了とする（詳細は「ステップ」4-5 が正）。

## Subagent Contract

subagent として呼ぶ場合、メインエージェントは対象コレクション、採用するマスター音源、背景素材をリポジトリルート相対パスで入力に含める。音源や背景の選択が必要なら、メインが選択を確定するまで subagent を起動しない。subagent は入力確認と `generate_videos.sh` の実行に必要な範囲で `workflow-state.json` を読み取ってよいが、書き込まず、`AskUserQuestion` も実行しない。完了報告には `status: success | failure`、生成した `01-master/*.mp4` の絶対パス一覧、probe 検証結果、エラーを含める。メインはファイル存在と指定入力との整合を検証してから state を更新する。直接実行時は既存手順を変更しない。

## 設定読み込みゲート

Quick Reference や対象コレクション確認に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/videoup/config.default.yaml`
2. `config/skills/videoup.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("videoup")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。このスキルが `masterup` や `loop-video` の skill-config を直接参照する段階では、それぞれの `config.default.yaml` と `config/skills/<skill>.yaml` も同じ手順で読む。

## 前提

以下を確認し、満たさなければ前工程を案内して停止する:

- 対象コレクション（`collections/planning/` 配下）に `workflow-state.json` が存在すること。無ければ `/wf-new` を案内して停止する
- マスター音源が存在すること（`workflow-state.json::assets.master_audio` が指すファイル、または `01-master/master-mix.*` / `master.*`）。無ければ `/masterup`（Suno）または `/lyria`（Lyria）を案内して停止する（DAW バウンス済みなら `master-mix.m4a` の手動配置でも可）
- 動画背景素材が存在すること: textless `10-assets/main.png` / `main.jpg`（無ければ `/thumbnail` を案内）。ループ動画運用チャンネル（`loop-video.enabled` が `false` でない）で `10-assets/loop.mp4` が無ければ `/loop-video` を案内する
- `ffmpeg` / `ffprobe` が利用可能であること（`generate_videos.sh` が使用）。無ければ `/setup` を案内する

## Scripts

| スクリプト | 役割 | 場所 |
|-----------|------|------|
| `yt-generate-master` | 個別 MP3 → クロスフェード結合 → マスター MP3 | Python CLI (skill-config `masterup` 参照) |
| `generate_videos.sh` | 音声 + テキストなし動画背景 (`main.png/jpg` or `loop.mp4`) → MP4 動画 | `.claude/skills/videoup/references/generate_videos.sh` |

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
未指定の場合、`collections/planning/` から `assets.master_audio` が設定済み（`null` 以外）かつ `assets.master_video` が `null` のコレクションを自動検出します。

### ステップ

1. **対象コレクション確認**: `workflow-state.json` で状態確認
2. **マスター音源**: `workflow-state.json::assets.master_audio` にファイル名が記録されていればそれを最優先で使用し、`01-master/` 内に存在することを確認する。未設定の場合のみ `master-mix.{wav,m4a,aac,mp3,flac}` → `master.{wav,m4a,aac,mp3,flac}` の順で探す。`assets.master_audio` が不正 JSON / 非 string / パス付き / 存在しないファイルを指す場合、`generate_videos.sh` は固定名探索へ fallback せずエラー停止する。なければ `/masterup` または `/lyria` でのマスター音源生成を案内（DAW バウンス済みの場合は `master-mix.m4a` をそのまま配置可、`/lyria` / `/masterup` の自動生成出力は `master.{wav,mp3}` で配置される）
3. **ループ動画背景**: `10-assets/loop.mp4` が既にあればスキップ。
   `config/skills/loop-video.yaml::enabled: false` のチャンネルではループ動画化が無効化されているため、`/loop-video` を案内せず textless `10-assets/main.png` または `main.jpg` を静止背景として使用する。
   この場合、既存の `10-assets/loop.mp4` が残っていても `generate_videos.sh` は無視し、静止背景に切り替える。
   それ以外（`enabled` 未指定 or `true`）で `loop.mp4` が無ければ `/loop-video` でのループ動画生成を案内。
   `loop.mp4` があると `generate_videos.sh` が自動的に動画背景を使用（静止画の代わり）
4. **動画生成**: `generate_videos.sh` を実行する（「長時間処理の取り扱い」に従い background で起動する）
5. **workflow-state.json 更新**: `assets.master_video` に生成された動画ファイル名（例: `01-master/Theme-Name-Master.mp4`）を記録

### 自動検出される要素

スクリプトはコレクションのディレクトリ構造から以下を自動検出します:

- **コレクション名**: ディレクトリ名から（`YYYYMMDD-xxx-theme-collection` → `Theme-Name`）
- **マスター音声**: `workflow-state.json::assets.master_audio` が最優先。未設定の場合のみ `master-mix.{wav,m4a,aac,mp3,flac}` → `master.{wav,m4a,aac,mp3,flac}` の順に検出（m4a/aac は `-c:a copy` で再エンコード回避）。`master-mix.*` は DAW バウンス・手動配置、`master.*` は `/lyria` / `/masterup`（`yt-generate-master`）の自動生成出力（#507）。明示された `assets.master_audio` が壊れている場合は fail-closed し、別音源で動画生成を続行しない
- **動画背景**: `10-assets/main.png` 優先、`main.jpg` フォールバック。`thumbnail.jpg/png` は YouTube アップロード用のテキスト付きサムネイルなので動画背景には使わない
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

## 設定: config/skills/videoup.yaml (v14)

`generate_videos.sh` のチューニング値は **すべて下流チャンネルの `config/skills/videoup.yaml` から取得**する（新規 env override は追加しない config 駆動）。**全キー省略可**で、省略時は現行の固定値にフォールバックする（=無回帰）。

```yaml
audio:
  target_video_duration_min: 120   # 短尺 master を動画尺へ loop 伸長（#545, 既存 env 優先）
video:
  still_fps: 1            # 静止画(effect 無し)の短尺ベイク fps（既定 1）
  still_crf: 28           # 静止画(effect 無し)の短尺ベイク CRF（既定 28、高画質寄りは 26）
  still_gop: 300          # 静止画ベイクの 1 周期（既定 300 frames = 1fps で 5 分）
  loop_maxrate: "6000k"   # loop 正規化 / effect ベイクの maxrate（既定 6000k、容量重視は 4000-4500k）
  loop_bufsize: "12000k"  # 同上 bufsize（既定 12000k）
effect:
  type: none             # none | particles | bokeh | gradient（旧 VIDEOUP_EFFECT の config 版）
  intensity: subtle       # subtle | medium | strong
shrink:
  enabled: false         # 生成後の容量最適化 re-encode（下記）
  maxrate: ""            # 例 "2500k"。enabled かつ maxrate or crf 指定で発火
  crf: ""               # maxrate と排他（どちらか一方）
```

- **最終ファイルサイズ ≒ ベイク/正規化ビットレート × 尺**。容量を絞りたいときは `loop_maxrate` を下げるのが最も効く（YouTube 側で再トランスコードされるため、source を 4000-4500k へ下げても最終画質はほぼ不変）。
- `effect.type` / `effect.intensity` は config が一次ソース。既存の `VIDEOUP_EFFECT` / `VIDEOUP_EFFECT_INTENSITY` env は #648 互換の legacy fallback としてのみ残る。

### 生成後の容量最適化（shrink, opt-in）

`shrink.enabled: true` かつ `shrink.maxrate` か `shrink.crf` を指定すると、生成済み出力を 2 パス目で再エンコードして置換する。

- **トレードオフ**: 全尺を再エンコードするため、effect ベイク / stream copy の速度メリットは相殺される（長尺で数分〜十数分）。**容量を最小化したい最終版のみ**に使う。
- 本来は `loop_maxrate` を下げて上流で容量制御するのが推奨。
- アップロード確認後にファイルを消すディスク運用は `/live-clean` が担当。

## 映像エフェクト (#648 / v14 でループ・ベイク化)

ループ動画背景・静止画背景のどちらでも、画面に **光の粒子**・**ボケ**・**グラデーション流れ** などのエフェクトを重ねられる。動画編集ソフトの「画面を彩るレイヤー効果」を ffmpeg filtergraph だけで再現する機構。**v14 でエフェクト込み 1 周期だけを焼いて stream copy する「ループ・ベイク」方式に刷新し、エフェクト有効時も高速になった**。

### エフェクト一覧

| `VIDEOUP_EFFECT` | 効果 | 想定用途 |
|---|---|---|
| `none` (デフォルト) | エフェクトなし。ループは stream copy、静止画は 1 GOP だけベイク後に stream copy | コスト・容量を最小化したいとき |
| `particles` | 光の粒子（淡い白点が画面をゆっくり流れる） | 落ち着いた BGM・夜景・キラキラ系のサムネ |
| `bokeh` | ボケ（柔らかな円形グラデーションがゆらぐ） | カフェ系・暖色系ジャズ・ロウソク系のサムネ |
| `gradient` | グラデーション流れ（半透明のカラーグラデーションが上下にうごく） | ローファイヒップホップ・シティポップ・夜の街並み |

強度は `effect.intensity` で `subtle` / `medium` / `strong` から選ぶ（デフォルト `subtle`）。BGM 視聴の邪魔をしないよう **subtle 推奨**。`strong` は短時間のテイスター動画やショート向け。

### 使い方

`config/skills/videoup.yaml` に書くだけ（env 指定は不要）:

```yaml
# config/skills/videoup.yaml
effect:
  type: particles      # particles | bokeh | gradient
  intensity: subtle    # subtle | medium | strong
```

あとは通常どおり `generate_videos.sh` を回すと自動でエフェクトが乗る。既存の `VIDEOUP_EFFECT=... bash .../generate_videos.sh` env 指定も legacy fallback として動く。

### 挙動と注意点

- **v14: エフェクト有効時も高速**。エフェクト込みで 1 周期分だけ `fx_baked.mp4` に焼き、あとは `-stream_loop -1 -c:v copy` で連結する。従来の全尺再エンコード（loop/静止画ともに 8〜15 分）が **約 1〜2 分**になり、継ぎ目は closed GOP の stream copy で原理的に無損失
- エフェクト周期は整数固定: **particles=36s / bokeh=60s / gradient=72s**。背景が `loop.mp4` のときは `lcm(loop 尺, 周期)` の長さを焼いて背景・エフェクト双方の継ぎ目を揃える
- ベイク尺が動画尺以上、または上限（`BAKE_MAX_LEN=900s`）超のときは従来の全尺再エンコードへ **自動フォールバック**する（短尺動画など）
- `fx_baked.mp4` は `fx_baked.params`（effect / intensity / 周期 / 元画像 mtime / maxrate）でキャッシュ。サムネ差し替え時のみ再ベイク（10〜40 秒）するので「画像差し替え→再生成」が軽い
- ファイルサイズは `loop_maxrate`（既定 6000k）で制御。stream copy 出力のサイズはベイクのビットレート × 尺で決まる。容量を絞るなら `loop_maxrate` を 4000-4500k へ
- 不正な値（例: `effect.type: sparkle`）は **fail-loud で停止**。ffmpeg が走り始める前にエラーとなる
- 値検証は bash で完結しているため、`set -e` を使わずとも安全

### 動作確認

実コレクションで生成した動画は YouTube Studio のプレビュー（モバイル・PC）と実機 YouTube 視聴で粒子・ボケ・グラデーションが**音楽の邪魔にならない強度で乗っているか**を必ず確認すること。BGM チャンネルのコア視聴体験を壊さないことが優先事項。

## Overlays（#511, v13）

`config/channel/youtube.json::overlays` で audio visualizer + subscribe popup の合成を有効化できる。`overlays.enabled: true` のときだけ `generate_videos.sh` は **x264 再エンコード経路** に分岐し、`filter_complex` で背景の上に visualizer / popup を重ねる。`overlays.enabled: false`（既定）または `overlays` キー欠落時は、ループ動画または静止画の短尺ベイクを使う **stream copy 経路**を維持する。

### 設定例（youtube.json）

```json
{
  "overlays": {
    "enabled": true,
    "audio_visualizer": {
      "enabled": true,
      "mode": "bar",
      "size": "1280x180",
      "rate": "24",
      "fscale": "log",
      "colors": "white",
      "position": "(W-w)/2:H-h-40",
      "opacity": 0.85,
      "glow_enabled": true,
      "glow_sigma": 12.0,
      "glow_opacity": 0.45
    },
    "subscribe_popup": {
      "enabled": true,
      "image": "subscribe-popup.png",
      "start_sec": 5.0,
      "duration_sec": 8.0,
      "fade_sec": 0.6,
      "position": "W-w-40:40"
    },
    "encoder": {
      "preset": "medium",
      "crf": 20,
      "maxrate": "4M",
      "bufsize": "8M",
      "framerate": 24
    }
  }
}
```

### 自動検出と前提

- **jq 必須**: `jq` が PATH に無いときは overlays は自動 disable され既存経路で動く。
- **設定ファイル探索順**: `OVERLAYS_CONFIG` 環境変数 → `CHANNEL_DIR/config/channel/youtube.json` → コレクションディレクトリの祖先探索。
- **popup 画像探索順**: 絶対パス → `10-assets/<image>` → `<collection-dir>/<image>`。見つからない場合は popup のみスキップして visualizer は実行する。
- **再エンコード固定**: overlays 経路は `-c:v copy` 不可。`encoder.crf` / `maxrate` / `bufsize` で品質とサイズを制御する（DeepFocus365 で 70 分マスター = 約 1.0 GB / 2 Mbps 実績）。

### 動作実証メモ

- DeepFocus365 で実装済み: 70 分マスター動画を約 2 分弱で生成、visualizer + popup ともに正常合成（#511 背景）。
- visualizer は `showfreqs=mode=bar` + `gblur` の 2 パス glow で淡い発光を演出。`glow_enabled: false` で 1 パスに減らせる。
- popup は `fade=in` / `enable='between(t,start,end)'` / `fade=out` を組み合わせて時間窓制御している。

## 長時間処理の取り扱い

`generate_videos.sh` は ffmpeg を走らせるため数分かかる。目安（2 時間尺）: **エフェクト無し（ループ / 静止画短尺ベイクの stream copy）= 約 1〜2 分** / **エフェクト有り（v14 ループ・ベイク）= 約 1〜2 分**（初回はベイク 10〜40 秒 + 連結 約 1 分、2 回目以降はベイク cache hit）。`shrink.enabled` の容量最適化や短尺フォールバックの全尺再エンコードを使うときは尺なりに数分〜十数分かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。Codex など `run_in_background` 非対応の実行環境では、同コマンドを `nohup ... > <log> 2>&1 &` で background 起動し、完了はログ末尾で確認する読み替えとする。

spawn 例:

```bash
# エフェクト無しの基本パターン
bash "$(git rev-parse --show-toplevel)/.claude/skills/videoup/references/generate_videos.sh" \
  > /tmp/videoup-$(date +%s).log 2>&1

# エフェクト付き（#648）
VIDEOUP_EFFECT=particles VIDEOUP_EFFECT_INTENSITY=subtle \
  bash "$(git rev-parse --show-toplevel)/.claude/skills/videoup/references/generate_videos.sh" \
  > /tmp/videoup-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ マスター動画生成を background 実行中（推定 N 分）。完了まで他の質問にもお答えできます。
> ログ: /tmp/videoup-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "videoup" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "videoup"` + `cmux notify --title "videoup 完了"` を呼ぶ（非 cmux 環境では skip）。

完了通知が届いたらログ末尾から結果サマリー（生成された `.mp4` のパス）をユーザーへ返す。失敗時は ffmpeg のエラー行を抜き出して報告する。

## オーディオビジュアライザー / オーバーレイについて

`generate_videos.sh` は `config/channel/youtube.json::overlays.enabled: true` のときだけ、audio visualizer や subscribe popup を `filter_complex` で合成する。無効時または `jq` 不在時は textless `main.png/jpg` を短尺ベイクして stream copy するか、`loop.mp4` を stream copy して音声を重ねる。

### よくある誤解 (#646 feedback)

「Suno のデータ取り込み時にビジュアライザーを付けて」とユーザーが指示しても、Suno / Lyria / masterup の工程ではビジュアライザーは付かない。理由:

- `/suno` / `/lyria` / `/masterup` は**音源（mp3 / wav / m4a）を作る工程**であり、映像オーバーレイは扱わない
- ビジュアライザーは本質的に**動画生成（`generate_videos.sh`）側の合成処理**で、`ffmpeg` の `filter_complex` に `showfreqs` 等を組む
- 反映したい場合は `config/channel/youtube.json::overlays.enabled: true` と必要な overlay 設定を用意してから `/videoup` を実行する

### 正しい運用

- ビジュアライザーが必要な動画は、`config/channel/youtube.json::overlays.enabled: true` にしたうえで `overlays.audio_visualizer.enabled: true` を設定して `/videoup` を実行する
- popup も必要なら `overlays.subscribe_popup.enabled: true` と画像パスを設定する。画像が見つからない場合は popup だけスキップし、visualizer は継続する
- overlays 無効チャンネルでは従来どおり textless `main.png/jpg` または `loop.mp4` のみで生成する

### Claude への指示時の注意

オペレーターから「ビジュアライザー付きで」「波形表示で」等の指示があった場合は、**Suno 側ではなく `/videoup` の overlays 設定で反映する**ことを明示してから作業を進めること。その上で、

- overlays を有効にして生成するか
- 静止画 / ループ動画のみで進めるか
- 外部ツールで後付けするか

をユーザーに選んでもらう。黙って静止画で生成すると今回のような FB（期待と実装の乖離）が再発する。

## 障害時ガイダンス

動画生成は `generate_videos.sh`（ffmpeg）でローカル実行され、外部サービスには依存しない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| ffmpeg 不在 | `command not found: ffmpeg`（`generate_videos.sh` の `command -v` チェックで停止） | `brew install ffmpeg` 等で install してから再実行 |

## Next Step

動画生成後:
→ `/video-description <collection-path>` でYouTube概要欄を生成
