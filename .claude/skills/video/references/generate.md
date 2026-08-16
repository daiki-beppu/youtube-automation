# 動画生成

## 共通Web review lifecycle

動画の手動確認は [マスター動画 review](master-video-review.md) に従い、preview/full専用の `yt-master-video-review` を実行する。
single-use loopback brokerが返すallowlist候補IDとartifact digestを実fileとprobe結果に対して再検証し、fullだけ既存の確定処理を呼ぶ。
HTMLやbrokerから任意path、command、state patchを受け取らない。renderer・browser・timeout失敗はfail-closedで停止する。
Web失敗から会話へ黙って切り替えず、browserのない環境だけ `--transport terminal` を明示する。
preview不要の自動経路はpreview用CLIを呼ばずHTML・待機を作らない。Codex / Claude固有session APIは使用しない。

`.claude/skills/` 配下の共有スクリプト（`yt-skills sync` で配布）を使ってマスター音源と動画を生成します。
スクリプトは毎回生成せず、既存の汎用スクリプトを実行します。

Suno 系チャンネルは `/music --master`、Lyria 系チャンネルは `/music --generate`（`/music --master` 不要）でマスター音源を生成してから実行する。

背景構成は `config/skills/video.yaml::generate.video_type`（`loop` / `static`、既定 `loop`）で明示する。新しいタイプを追加する実装箇所は `references/video-type-extension.md` を参照する。

## 完了条件

`01-master/` にマスター動画（例: `Theme-Name-Master.mp4`）が生成され、`workflow-state.json` の `assets.master_video` に動画ファイル名が記録されたとき完了とする。

## Subagent Contract

- **入力**: 対象コレクション、採用するマスター音源、背景素材
- **成果物**: `01-master/*.mp4`、probe 検証結果
- **例外**: `generate_videos.sh` の実行に必要な範囲で `workflow-state.json` を読み取ってよい（書き込みは不可）

subagent は `workflow-state.json` へ書き込まない。完了報告は `status: success | failure`、成果物の絶対パス一覧、エラー。成果物の存在検証と owner CLI 実行はメインが行う。

## 前提

以下を確認し、満たさなければ前工程を案内して停止する:

- 対象コレクション（`collections/planning/` 配下）に `workflow-state.json` が存在すること。無ければ `/wf-new` を案内して停止する
- マスター音源が存在すること（`workflow-state.json::assets.master_audio` が指すファイル、または `01-master/master-mix.*` / `master.*`）。無ければ `/music --master`（Suno）または `/music --generate`（Lyria）を案内して停止する（DAW バウンス済みなら `master-mix.m4a` の手動配置でも可）
- 動画背景素材が存在すること: `10-assets/main.png` / `main.jpg`（無ければ `/thumbnail` を案内）。`thumbnail::textless.enabled: false` では文字入り `main.jpg` を正規入力として受け入れ、未設定または `true` では textless main を要求する。ループ動画運用チャンネルで `10-assets/loop.mp4` が無ければ `/thumbnail --loop` を案内する
- `ffmpeg` / `ffprobe` が利用可能であること（`generate_videos.sh` が使用）。無ければ `/setup` を案内する

## Scripts

| スクリプト | 役割 | 場所 |
|-----------|------|------|
| `yt-generate-master` | 個別 MP3 → クロスフェード結合 → マスター MP3 | Python CLI（`music.master` 設定参照） |
| `yt-generate-videos-batch` | マスター音源確定済み・未動画化のコレクションを並列動画化 | Python CLI (skill-config `video.generate.batch.max_workers` 参照) |
| `generate_videos.sh` | 音声 + テキストなし動画背景 (`main.png/jpg` or `loop.mp4`) → MP4 動画 | `.claude/skills/video/references/generate_videos.sh` |

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `yt-generate-master` | CWD のコレクションでマスター音源生成 |
| `yt-generate-master <path>` | 指定コレクションでマスター音源生成 |
| `yt-generate-videos-batch` | マスター音源確定済み・未動画化のコレクションを並列動画化 |
| `uv run bash "$(git rev-parse --show-toplevel)/.claude/skills/video/references/generate_videos.sh" <collection-path>` | 1 コレクションの動画を生成 |

対象 stage・並列度・通常 option は `yt-generate-videos-batch --help`、collection path・preview・overlay option は `generate_videos.sh --help` を正とする。

## Instructions

### 対象コレクション

```
$ARGUMENTS
```

引数が指定されている場合、そのコレクションを対象とします。
未指定の場合、`collections/planning/` から `assets.master_audio` が設定済み（`null` 以外）かつ `assets.master_video` が `null` のコレクションを自動検出します。
複数件を一括処理する場合は `yt-generate-videos-batch` を使います。通常 option と解決契約は同 CLI の `--help` に従います。

### ステップ

1. **対象コレクション確認**: `workflow-state.json` で状態確認
2. **マスター音源**: `workflow-state.json::assets.master_audio` にファイル名が記録されていればそれを最優先で使用し、`01-master/` 内に存在することを確認する。未設定の場合のみ `master-mix.{wav,m4a,aac,mp3,flac}` → `master.{wav,m4a,aac,mp3,flac}` の順で探す。`assets.master_audio` が不正 JSON / 非 string / パス付き / 存在しないファイルを指す場合、`generate_videos.sh` は固定名探索へ fallback せずエラー停止する。なければ `/music --master` または `/music --generate` でのマスター音源生成を案内する
3. **ループ動画背景**: `10-assets/loop.mp4` が既にあればスキップ。
   loop 無効のチャンネルでは `/thumbnail --loop` を案内せず `10-assets/main.png` または `main.jpg` を静止背景として使用する。`thumbnail::textless.enabled: false` の共有 `main.jpg` は文字入りでも正規入力として扱い、textless 再生成へ戻さない。
   この場合、既存の `10-assets/loop.mp4` が残っていても `generate_videos.sh` は無視し、静止背景に切り替える。
   それ以外で `loop.mp4` が無ければ `/thumbnail --loop` でのループ動画生成を案内。
   `loop.mp4` があると `generate_videos.sh` が自動的に動画背景を使用（静止画の代わり）
4. **プレビュー承認**: `generate.review.preview_required: true` なら `generate_videos.sh --preview 20 <collection-path>` の成功後、`master-video-review.md` のpreview reviewを実行する。承認前・probe失敗・不受理では全尺生成へ進まずstateを変更しない。`false` ならpreview生成・HTML・確認待ちを作らない
5. **動画生成**: `generate_videos.sh` を実行する（所要時間とログの扱いは「所要時間と完了報告」を参照）
6. **完成動画確認とworkflow-state.json更新**: 全尺生成の成功後だけ、`master-video-review.md` のfull reviewを実行する。probeとdigest再検証後だけCLIが `assets.master_video` に動画ファイル名を記録する。別のstate更新を重ねず、プレビューのみでは実行しない

### 自動検出される要素

スクリプトはコレクションのディレクトリ構造から以下を自動検出します:

- **コレクション名**: ディレクトリ名から（`YYYYMMDD-xxx-theme-collection` → `Theme-Name`）
- **マスター音声**: `workflow-state.json::assets.master_audio` が最優先。未設定の場合のみ `master-mix.{wav,m4a,aac,mp3,flac}` → `master.{wav,m4a,aac,mp3,flac}` の順に検出（m4a/aac は `-c:a copy` で再エンコード回避）。`master-mix.*` は DAW バウンス・手動配置、`master.*` は `/music --generate` / `/music --master` の自動生成出力。明示された `assets.master_audio` が壊れている場合は fail-closed し、別音源で動画生成を続行しない
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
| 環境変数 | `VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN=120 uv run bash .../generate_videos.sh ...` | 高 |
| チャンネル override | `config/skills/video.yaml::generate` に `audio: { target_video_duration_min: 120 }` | 中 |
| 未設定 | (既定) | 従来動作 |

- master 尺 ≥ `target_video_duration_min × 60` のときは無視され従来動作になる (master 尺が支配)
- 音声 loop seam の crossfade は本機能のスコープ外 (将来拡張)

## 設定: config/skills/video.yaml::generate (v14)

`generate_videos.sh` のチューニング値は **すべて下流チャンネルの `config/skills/video.yaml::generate` から取得**する（新規 env override は追加しない config 駆動）。**全キー省略可**で、省略時は現行の固定値にフォールバックする（=無回帰）。

```yaml
generate:
  video_type: loop
  audio:
    target_video_duration_min: 120
  video:
    still_fps: 1
    still_crf: 28
    still_gop: 300
    loop_maxrate: "6000k"
    loop_bufsize: "12000k"
  effect:
    type: none
    intensity: subtle
  shrink:
    enabled: false
    maxrate: ""
    crf: ""
```

- **最終ファイルサイズ ≒ ベイク/正規化ビットレート × 尺**。容量を絞りたいときは `loop_maxrate` を下げるのが最も効く（YouTube 側で再トランスコードされるため、source を 4000-4500k へ下げても最終画質はほぼ不変）。
- `effect.type` / `effect.intensity` は config が一次ソース。既存の `VIDEOUP_EFFECT` / `VIDEOUP_EFFECT_INTENSITY` env は #648 互換の legacy fallback としてのみ残る。

### 生成後の容量最適化（shrink, opt-in）

`shrink.enabled: true` かつ `shrink.maxrate` か `shrink.crf` を指定すると、生成済み出力を 2 パス目で再エンコードして置換する。

- **トレードオフ**: 全尺を再エンコードするため、effect ベイク / stream copy の速度メリットは相殺される（長尺で数分〜十数分）。**容量を最小化したい最終版のみ**に使う。
- 本来は `loop_maxrate` を下げて上流で容量制御するのが推奨。
- アップロード確認後にファイルを消すディスク運用は `/publish --clean` が担当。

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

`config/skills/video.yaml::generate` に書くだけ（env 指定は不要）:

```yaml
# config/skills/video.yaml::generate
effect:
  type: particles      # particles | bokeh | gradient
  intensity: subtle    # subtle | medium | strong
```

あとは通常どおり `generate_videos.sh` を回すと自動でエフェクトが乗る。既存の `VIDEOUP_EFFECT=... uv run bash .../generate_videos.sh` env 指定も legacy fallback として動く。

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

overlay 合成は動画生成工程だけが担当し、音源生成・master 化では適用しない。一回限りの切替入口と config に対する override 契約は `generate_videos.sh --help` を正とし、設定ファイルを一時編集しない。

runtime mask helper は script 内から `uv run python -m youtube_automation.infrastructure.media.audio_visualizer_mask` で起動する。script 自体も `uv run bash` で実行し、system Python に package が無い環境でも venv の依存を使う。

### 設定例（youtube.json）

```json
{
  "overlays": {
    "enabled": true,
    "audio_visualizer": {
      "enabled": true,
      "style": "bar",
      "bars": 16,
      "mode": "bar",
      "size": "1280x180",
      "rate": "24",
      "fscale": "log",
      "colors": "white",
      "position": "(W-w)/2:H-h-40",
      "opacity": 0.85,
      "glow_enabled": true,
      "glow_sigma": 12.0,
      "glow_opacity": 0.45,
      "ring": {
        "inner_r": 120,
        "length": 160,
        "arc_deg": [30, 330]
      }
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
      "codec": "libx264",
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
- **popup 画像探索順**: 絶対パス → `10-assets/<image>` → `<collection-dir>/<image>` → `<channel-root>/<image>`。`<channel-root>` は `CHANNEL_DIR` または canonical `config/channel/youtube.json` の配置先から確定するため、マルチチャンネル workspace で `branding/subscribe-popup.png` を指定すると選択チャンネル配下の画像を使う。見つからない場合はエラー終了し、popup を欠いた動画を生成しない。
- **再エンコード固定**: overlays 経路は `-c:v copy` 不可。`encoder.crf` / `maxrate` / `bufsize` で品質とサイズを制御する（DeepFocus365 で 70 分マスター = 約 1.0 GB / 2 Mbps 実績）。
- **hardware encode は明示 opt-in**: `encoder.codec: "hardware"` で macOS は `h264_videotoolbox`、対応 NVIDIA 環境は `h264_nvenc` を選ぶ。特定 codec の明示指定も可能。利用不能または 1-frame 起動 probe 失敗時は `libx264` へ戻り、requested / selected と理由をログへ出す。既定は引き続き `libx264`。
- **codec 固有引数**: `libx264` は preset / CRF、VideoToolbox は bitrate、NVENC は `p5` / CQ を使う。H.264 / yuv420p / profile / maxrate / bufsize / fps の出力契約は共通。
- **性能を実測してから opt-in**: `VIDEOUP_BENCH_DURATION=60 VIDEOUP_BENCH_RUNS=3 bash .claude/skills/video/references/benchmark_overlay_encoders.sh` で同一入力を比較し、H.264 / yuv420p / profile / maxrate / bufsize / fps / AAC / duration の共通出力契約と visualizer の位置・形状・opacity の一致を検証する。median wall-clock が `libx264 medium` baseline より 20% 以上短い候補だけを opt-in の採用候補とし、未達なら既定経路を維持する。

### Audio visualizer style（#1684）

`audio_visualizer.style` は次の 5 preset から選ぶ。未指定時は `bar` になり、従来の `showfreqs=mode=bar` filtergraph をそのまま使う。

| style | 表示 | 主な追加設定 |
|---|---|---|
| `bar` | 従来の横並びバー | `mode` / `size` |
| `mirror-mountain` | 低音を中央に寄せた左右鏡像 + 上下対称バー | `bars` / 偶数の `size` |
| `ring` | 円弧上の角丸カプセル | `bars` / `ring.inner_r` / `ring.length` / `ring.arc_deg` |
| `ring-line` | 細線のギザギザリング | `bars` / `ring.*` |
| `heart` | ハート曲線上で内外へ波打つスペクトラムバー | `bars` / `size` |

例: `"style": "mirror-mountain", "bars": 16, "size": "300x110"`。ring 系は `"style": "ring", "bars": 24, "ring": {"inner_r": 120, "length": 160, "arc_deg": [30, 330]}, "fill": {"type": "conical"}` のように指定すると、角度を色相へ対応させたフルスペクトルで描画できる。旧 channel-local ring パッチからの移行は `references/ring-migration.md` を参照する。heart は `"style": "heart"` の 1 行で `size: "600x480"` / `colors: "0xff69b4"`（ピンク）が既定になり、必要なら `bars` / `size` / `colors` を明示して上書きできる。`position` は全 style 共通で最終レイヤーの配置に適用される。heart は `fill`（solid / gradient / rainbow / conical）、`rounding`、`glow` を利用でき、形状自体が左右対称のため `mirror_center` / `symmetric_vertical` は適用しない。

`mirror-mountain` / ring / heart で使うバー間隔・形状マスク PNG は、`generate_videos.sh` が同梱 Python helper で一時領域へ実行時生成する。外部の `make_bars_mask.py`、`build_spectrum_video.sh`、事前生成 PNG は不要。

### 動作実証メモ

- DeepFocus365 で実装済み: 70 分マスター動画を約 2 分弱で生成、visualizer + popup ともに正常合成（#511 背景）。
- visualizer は style ごとの `showfreqs` filtergraph + `gblur` の 2 パス glow で淡い発光を演出。`glow_enabled: false` で 1 パスに減らせる。
- popup は `fade=in` / `enable='between(t,start,end)'` / `fade=out` を組み合わせて時間窓制御している。

## 所要時間と完了報告

`generate_videos.sh` の目安（2 時間尺）: **エフェクト無し（ループ / 静止画短尺ベイクの stream copy）= 約 1〜2 分** / **エフェクト有り（v14 ループ・ベイク）= 約 1〜2 分**（初回はベイク 10〜40 秒 + 連結 約 1 分、2 回目以降はベイク cache hit）。`shrink.enabled` の容量最適化や短尺フォールバックの全尺再エンコードを使うときは尺なりに数分〜十数分かかる。

ログを `/tmp/video-generate-$(date +%s).log` へ redirect し、完了後は末尾から生成された `.mp4` のパスを報告する。失敗時は ffmpeg のエラー行を抜き出す。background 実行フラグを持たない環境（Codex 等）では `nohup ... > <log> 2>&1 &` を使い、完了はログ末尾で確認する。

## オーディオビジュアライザー / オーバーレイについて

`generate_videos.sh` は `config/channel/youtube.json::overlays.enabled: true` のときだけ、audio visualizer や subscribe popup を `filter_complex` で合成する。無効時または `jq` 不在時は textless `main.png/jpg` を短尺ベイクして stream copy するか、`loop.mp4` を stream copy して音声を重ねる。

### よくある誤解 (#646 feedback)

「音源生成時にビジュアライザーを付けて」と指示しても、音源生成・master 化ではビジュアライザーは付かない。理由:

- `/music --prompt` / `/music --generate` / `/music --master` は**音源（mp3 / wav / m4a）を作る工程**であり、映像オーバーレイは扱わない
- ビジュアライザーは本質的に**動画生成（`generate_videos.sh`）側の合成処理**で、`ffmpeg` の `filter_complex` に `showfreqs` 等を組む
- 反映したい場合は `config/channel/youtube.json::overlays.enabled: true` と必要な overlay 設定を用意してから `/video --generate` を実行する

### 正しい運用

- ビジュアライザーが必要な動画は、`config/channel/youtube.json::overlays.enabled: true` にしたうえで `overlays.audio_visualizer.enabled: true` を設定して `/video --generate` を実行する
- popup も必要なら `overlays.subscribe_popup.enabled: true` と画像パスを設定する。画像が見つからない場合は popup だけスキップし、visualizer は継続する
- overlays 無効チャンネルでは従来どおり textless `main.png/jpg` または `loop.mp4` のみで生成する

### Claude への指示時の注意

オペレーターから「ビジュアライザー付きで」「波形表示で」等の指示があった場合は、**Suno 側ではなく `/video --generate` の overlays 設定で反映する**ことを明示してから作業を進めること。その上で、

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
- `/video --describe <collection-path>` で YouTube 概要欄を生成
