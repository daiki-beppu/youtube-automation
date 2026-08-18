# Music master mode

## エンジン判定

対象 collection を確定したら `config/channel/youtube.json::music_engine` を一度だけ解決する。`lyria` / `minimax` は `--generate` が `01-master/master.mp3` を直接生成するため、この mode は完了済みとして skip する。`suno` の場合だけ以下の手順を実行する。未設定または `suno` / `lyria` / `minimax` 以外なら設定不整合として停止する。

## 前後工程

- `前工程`: `/wf-new`, `/music --prompt`, `/music --generate`
- `後工程`: `/video --generate`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `collections/<id>/01-master/master.mp3`, `collections/<id>/01-master/.selection.log`, `collections/<id>/01-master/.loudness-receipt.json`, `collections/<id>/workflow-state.json`
- `読み込む`: `collections/<id>/02-Individual-music/*.mp3`, `collections/<id>/20-documentation/suno-prompts.json`, `config/channel/audio.json`, `config/skills/masterup.yaml`

## Overview

SunoAI 楽曲のクロスフェード結合でマスター音源を自動生成するまでの一連フローを実行します。

**ダウンロードの責務分離**: 楽曲のダウンロードは `/music --generate` が一括ダウンロード機能で自動実行するのが primary path。本スキルの Step 2-3（WebFetch + CDN curl）は `/music --generate` でダウンロード済みの場合はスキップされる。本スキルの主責務は **マスター音源生成 + workflow-state 更新** である。

## 完了条件

以下がすべて満たされたとき本スキルは完了とする（各項目の詳細は該当 Step が正）:

1. Step 1.5 / 1.6 / 3〜4.5 / 5.1 の検証ゲートがすべて通過し、現在の入力と閾値に一致する PASS receipt を検証済みである（FAIL / MISSING / 混入 / 生成漏れ / 曲間音量差が残る間は Step 5 本体または state 更新に進まない）
2. `01-master/` にマスター音源（既定 `master.mp3`）が生成されている
3. `workflow-state.json` の `assets.raw_master` と `updated_at` が更新されている（`phase` は `"prepared"` のまま。`"mastered"` への遷移は `/wf-next` の責務）

## Subagent Contract

- **入力**: 対象コレクション、fallback path を使う場合は確定済み playlist URL または title list、実行する処理
- **成果物**: `01-master/master.*`、`01-master/.selection.log`、`01-master/.loudness-receipt.json`
- **委譲しない処理**: 選曲・混入許容・over-max 例外採用の承認。Step 5.6 の雨レイヤー後処理は成果物生成時に `workflow-state.json` を更新するためメインが実行する

subagent は `workflow-state.json` へ書き込まず `AskUserQuestion` を実行しない。承認が要る処理は、メインが承認を得るまで委譲しない。Step 5.1 の全曲走査は subagent が1回だけ実行して receipt を返し、メインは FFmpeg を再実行せず receipt を検証する。完了報告は `status: success | failure`、成果物の絶対パス一覧、エラー。成果物の存在検証、receipt 検証、owner CLI 実行はメインが行う。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/music/config.default.yaml::master`
2. `config/skills/masterup.json`（存在する場合）
3. `config/skills/masterup.yaml`（JSON が存在しない場合の fallback）

合成規則は `youtube_automation.configuration.skills.load_skill_config("masterup")` と同じで、チャンネル上書きが優先される。TS CLI `uv run yt-generate-master` は `config/skills/masterup.json` を優先し、存在しない場合のみ `config/skills/masterup.yaml` を fallback として読む。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

以下を確認し、満たさなければ前工程を案内して停止する:

- チャンネルの音楽エンジンが Suno であること。Lyria チャンネルでは `/music --generate` が `01-master/master.mp3` を直接出力するため本スキルは不要
- 対象コレクションが `/music --prompt` 完了済みであること（`collections/planning/` 配下に `workflow-state.json` があり `assets.music_prompts = true`、かつ `20-documentation/suno-prompts.json` が存在）。無ければ `/wf-new` → `/music --prompt` を案内して停止する
- `02-Individual-music/` にダウンロード済み音源が揃っていること（primary path は `/music --generate` の一括ダウンロード）。未ダウンロードの場合は `/music --generate` を案内するか、fallback としてプレイリスト URL を引数に受け取り Step 2-3 で DL する。**音源が揃っていれば playlist URL は不要**（URL 未指定を理由に停止しない。突合は Step 1.6 のローカルファイル名を第一手段にする）
- `ffmpeg` / `ffprobe` が利用可能であること（`uv run yt-generate-master` が使用）。無ければ `/setup` を案内する

## 設定

Python の `/music --master` 経路は skill-config (`.claude/skills/music/config.default.yaml::master`) とチャンネル上書きを deep-merge して読む。
TS CLI `uv run yt-generate-master` は `audio` の実行時既定値を組み込み default として持ち、同梱 `config.default.yaml` の `audio.bitrate` / `audio.crossfade_duration` と同期テストで固定する。チャンネル側で上書きする場合は `config/skills/masterup.json` を優先する。既存チャンネル互換として `config/skills/masterup.yaml` もサポートするが、両方ある場合は JSON が優先される。TS CLI が読む `audio` section は optional で、`post_processing` / `pair_selection` だけの override は有効。`audio` が存在する場合は object でなければならず、未対応 YAML 行や空 scalar は config error として停止する。

| 項目 | 既定 | 説明 |
|---|---|---|
| `audio.crossfade_duration` | 1.0 | トラック間クロスフェード秒数（`domains.metadata.service.BAHMetadataGenerator` のタイムスタンプ計算で参照） |
| `audio.bitrate` | "192k" | マスター音源のビットレート |
| `audio.target_duration_min` | (未設定) | 旧 channel override。目標尺の SSOT は `config/channel/audio.json`。channel 側未設定時のみ互換 fallback として使う |
| `audio.shuffle` | `false` | `uv run yt-generate-master` で CLI `--shuffle` / `--shuffle-seed` 未指定時に `--shuffle` 相当のデフォルトとして採用される。Suno で同一プロンプトから生成した類似イントロ群がマスター後半で連続するのを避けたいときに `true` にする |
| `audio.shuffle_seed` | (未設定) | シャッフルの再現性 seed（整数）。`audio.shuffle: true` のときに CLI `--shuffle-seed` 未指定なら採用される。seed 単独設定では shuffle を有効化しない（skill-config は永続設定のため誤動作防止に明示要求とする / CLI の暗黙有効化とは挙動が異なる） |
| `audio.pin_first_count` | `0` | `uv run yt-generate-master` で CLI `--pin-first` / `--pin-first-count` 未指定時に `--pin-first-count N` 相当のデフォルトとして採用される。ソート済み先頭 N 件を順序固定する（`audio.shuffle: true` と併用時は残りだけシャッフル）。`0` = 固定なし。retention に強い 1 曲を冒頭に置きたいときに `1` 以上を設定する |
| `suno_download.cdn_url_template` | `https://cdn1.suno.ai/{song_id}.mp3` | Suno CDN URL テンプレート |
| `suno_download.retry_count` | 3 | curl `--retry` に渡すリトライ回数 |
| `suno_download.retry_delay_seconds` | 2 | curl `--retry-delay` に渡すリトライ間隔（秒） |
| `post_processing.rain_layers.enabled` | `false` | `uv run yt-apply-rain-layers` の opt-in スイッチ。`true` で `branding/rain_layers/*.wav` を raw master に amix する後処理を有効化する |
| `post_processing.rain_layers.volume_db` | `-19` | 各レイヤーに当てる減衰 dB（10^(-19/20) ≈ 0.112）。`uv run yt-apply-rain-layers` が ffmpeg `volume={dB}` でレイヤー毎に適用 |
| `post_processing.rain_layers.output_name` | `master-rain.wav` | 後処理出力ファイル名（`01-master/` 配下）。成功時に `workflow-state.json::assets.raw_master` がこの名前へ書き換わる |
| `post_processing.rain_layers.output_codec` / `.output_sample_rate` | `pcm_s16le` / `44100` | 出力 WAV の ffmpeg コーデックとサンプリングレート（ステレオ固定）。後段の外部 DAW でミキシング+マスタリングする運用想定 |
| `post_processing.suno_audio_cleanup.enabled` | `true` | Suno ダウンロード直後の個別音源に、無音カット / EQ / dynaudnorm / limiter / LUFS 正規化 / 末尾 fade guard を適用する。従来挙動へ戻す場合はチャンネル側で `false` にする |
| `post_processing.suno_audio_cleanup.max_workers` | `2` | `apply` の曲単位最大並列数（1〜8）。CLI `--jobs` が優先し、`--jobs 1` で従来どおり main thread の直列実行を選ぶ。範囲外は処理開始前に失敗する |
| `post_processing.suno_audio_cleanup.loudnorm.I` | `-14` | YouTube 向け LUFS 正規化の目標値。チャンネル側 `config/skills/masterup.json` 優先、既存 `masterup.yaml` fallback で調整可能 |
| `validation.loudness_deviation.max_lu` | `2.0` | マスター結合前に許容するコレクション内 integrated LUFS の最大差（LU）。0 より大きい数値のみ |
| `pair_selection.mode` | `auto` | `suno-prompts.json` の `lyrics` から歌詞あり/なしを判定し、歌詞ありならペアから 1 曲、歌詞なしなら 2 clip 両方を採用する。`never` で整理をスキップ |
| `pair_selection.min_song_sec` / `.max_song_sec` | `45` / `300` | 極端に短い曲 / 長い曲を master 対象から除外する duration guard。`null` で片側だけ無効化 |
| `pair_selection.out_of_range_action` | `stock` | 尺フィルタで除外した音源の扱い。`stock` で `assets/stock/music/b-side/` へ退避、`delete` で削除 |
| `pair_selection.strategy` / `.random_seed` | `random` / `null` | 歌詞ありペアの winner 選定。`null` seed は実行時生成し `01-master/.selection.log` へ記録 |
| `stock.dir` | `assets/stock/music/b-side` | 歌詞ありペアの loser と尺フィルタ除外曲の保管先 |
| `stock.filename_template` | `{collection_slug}__{song_id}__{title_slug}.{ext}` | stock 退避時のファイル名。使用可能 placeholder は `collection_slug` / `song_id` / `title_slug` / `ext` のみ。生成結果は basename のみ許可し、`/` / `\` / `..` / 絶対パスは失敗 |
| `stock.on_duplicate` | `skip` | stock 先に同名ファイルがある場合の挙動。`skip` は既存 stock を残して入力音源を削除、`overwrite` は既存 stock を置換、`fail` は入力音源を触らず非 0 終了 |

マスター音源生成は `uv run yt-generate-master` CLI がチャンネル側 `audio.crossfade_duration` override を読み、未指定時の組み込み default は同梱 `config.default.yaml` と同期テストで固定する。そのため実音声のクロスフェードと `domains.metadata.service.BAHMetadataGenerator` のタイムスタンプ計算は同じ既定値・同じチャンネル上書き値を使う。

## When to Use

- `/music --generate` で楽曲生成・ダウンロードが完了し、マスター音源を生成したいとき
- `02-Individual-music/` に MP3 / M4A / WAV ファイルが揃っている状態でマスター結合を実行したいとき
- `/music --generate` のダウンロードが使えない場合のフォールバックとして、プレイリスト URL 経由で DL + マスター生成を一貫実行したいとき

Lyria で音源を生成するチャンネルでは `/music --generate` が `01-master/master.mp3` を直接出力するため本スキルは不要。

## Quick Reference

| コマンド | 説明 | 例 |
|---------|------|-----|
| `/music --master` | DL 済み音源（`02-Individual-music/`）からマスター生成。URL 省略可（ローカルファイル名の突合は Step 1.6） | `/music --master` |
| `/music --master <playlist-url>` | プレイリスト内の全曲をDL + マスター生成 | `/music --master https://suno.com/playlist/xxx` |
| `uv run yt-generate-master --loop N` | マスター生成時に全トラックを N 回繰り返して結合 | `uv run yt-generate-master --loop 3` |
| `uv run yt-generate-master --target-duration MIN` | 目標尺 (分) 以上になる最小ループ回数を自動算出 | `uv run yt-generate-master --target-duration 150` |
| `uv run yt-generate-master --no-loop` | skill-config の目標尺を無視して 1 パスで生成 | `uv run yt-generate-master --no-loop` |
| `uv run yt-generate-master --shuffle` | 連結前に MP3 リストをシャッフル（OS entropy で seed 自動生成、stdout に `[Shuffle] seed=<N>` を出力） | `uv run yt-generate-master --shuffle` |
| `uv run yt-generate-master --shuffle-seed N` | シャッフル順を固定（`--shuffle` を暗黙有効化、再現性検証用） | `uv run yt-generate-master --shuffle-seed 42` |
| `uv run yt-generate-master --pin-first <files...>` | 先頭固定する MP3 ファイル名を順番指定（`--shuffle` 併用時も pin の順序は保持） | `uv run yt-generate-master --pin-first 00-hook.mp3 --shuffle` |
| `uv run yt-generate-master --pin-first-count N` | ソート済み先頭 N 件を固定（`--shuffle` 併用時は残り N+1〜末尾のみシャッフル） | `uv run yt-generate-master --pin-first-count 1 --shuffle` |
| `uv run yt-suno-audio-cleanup plan/apply` | Suno 個別音源の後処理を plan / apply。apply は元ファイルを backup して同名置換 | `uv run yt-suno-audio-cleanup plan <collection>` |
| `uv run yt-suno-verify-playlist` | ローカル音声ファイル名または playlist 曲名の突合（混入 / 生成漏れ / clip 不足を fail-loud 検出） | `uv run yt-suno-verify-playlist <collection> --music-dir 02-Individual-music` |
| (skill-config) `pair_selection.mode` | 歌詞-aware 採用整理。歌詞ありならペア片方、歌詞なしなら両方採用 | `mode: auto` |
| (skill-config) `pair_selection.min_song_sec` / `.max_song_sec` | 短すぎる / 長すぎる Suno 失敗生成を master から除外 | `min_song_sec: 45`, `max_song_sec: 300` |
| (skill-config) `audio.target_duration_min` | 旧 channel override。`config/channel/audio.json` が未設定のときだけ、CLI フラグ未指定時の互換 fallback として使用 | `target_duration_min: 120` |
| (skill-config) `audio.shuffle` | CLI フラグ未指定時のデフォルトシャッフル設定 | `shuffle: true` |
| (skill-config) `audio.shuffle_seed` | `audio.shuffle: true` 時のデフォルト seed（整数） | `shuffle_seed: 42` |
| (skill-config) `audio.pin_first_count` | CLI フラグ未指定時のデフォルト先頭固定数（`0` = 固定なし） | `pin_first_count: 1` |

出力 MP3 のビットレートとクロスフェード秒数は CLI 引数ではなく、`config/skills/masterup.json`（優先）または `config/skills/masterup.yaml` の `audio.bitrate` / `audio.crossfade_duration` で設定する。未設定時は組み込み default を使い、その値は同梱 `config.default.yaml` と同期テストで固定される。目標尺は CLI フラグ > `config/channel/audio.json` > skill-config の順で、skill-config の `audio.target_duration_min` は channel 側未設定時だけの互換 fallback。その他の CLI 対応オプションは `uv run yt-generate-master --help` を正本とする。

## Suno fallback 経路

suno-helper の一括ダウンロードが完了していれば、この経路は通らない。DL が途中で壊れた場合
（プレイリスト HTML が読めない / CDN が 403・404 を返す）だけ [suno-fallback.md](suno-fallback.md)
を読む。同ファイルに Step 2 / Step 3 の手動代替と、手動 DL からの復旧手順がある。

**silent な続行は禁止**。不完全な master.mp3 を作らず、Suno 経路が壊れた可能性を報告して停止する。

## Instructions

あなたは SunoAI 楽曲ダウンロード & マスターアップマネージャーです。

### 引数の解釈

```
$ARGUMENTS
```

- 第1引数: SunoAI プレイリストURL（省略可）。`02-Individual-music/` に音源が揃っていれば URL なしで完走できる（Step 2-3 はスキップ）。**URL 未指定を理由に「raw master 生成には playlist URL が必要です。URL を教えてください」と案内して停止するのは誤り** — Step 1.6 でローカルファイル名を突合する

### 前提条件

- アクティブなコレクションの `02-Individual-music/` ディレクトリが存在
- WebFetch ツールが利用可能であること（Step 2-3 を実行する場合のみ）

### Step 1: コレクションの特定

1. `collections/planning/` の `workflow-state.json` を検索
2. `assets.music_prompts = true` かつ `assets.raw_master = null` のコレクションを対象
3. 複数ある場合はユーザーに選択を促す

#### Step 1.4: raw_master 実ファイル突合チェック（不整合検知 / #1668）

対象コレクションを確定したら、生成に進む前に `assets.raw_master` と `01-master/` の実ファイルを突合する。フォールバック運用（`yt-generate-master` 直接実行）では `01-master/master.mp3` が生成済みでも `assets.raw_master` が `null` のまま残ることがあり、放置すると後続スキルが古い状態を前提に進行する:

```bash
uv run yt-raw-master-check <コレクションディレクトリ>
```

- **exit 0（整合）**: そのまま Step 1.5 へ進む
- **exit 2（不整合検知）**: CLI が出力した警告（例:「assets.raw_master が実ファイルと一致しません。更新しますか」）をユーザーに提示し、AskUserQuestion で更新可否を確認する
  - **承認** → `uv run yt-raw-master-check <dir> --apply` を実行し、`assets.raw_master` / `updated_at` が更新されたことを確認してから Step 1.5 へ進む。raw master が既に揃っている場合は Step 2〜5 の再生成は不要（Step 6 / 完了時の更新のみ確認）
  - **非承認** → `workflow-state.json` は変更しない。**警告を無視して silent に続行するのは禁止** — 不整合が残ったままである旨を明示してから、ユーザーの指示（再生成 or 中断）を仰ぐ。次回起動時も同じ警告が再表示される
- **exit 1（エラー）**: `workflow-state.json` の破損等。内容を報告して停止する

### Step 1.5: DL 完全性チェック（部分ダウンロード検知）

`02-Individual-music/` の実ファイル数を期待曲数と突合する。**`assets.music_downloaded` が `true` でも本チェックはスキップしない**（フラグと実ファイル数が食い違う部分ダウンロード — 例: 10 曲中 5 曲失敗 — を見逃さないため）。

期待曲数・実ファイル数は `/music --generate` の DL 完了判定・collection server の `status` 判定と同じロジック（既存ユーティリティ）で算出し、算式を二重管理しない。server lifecycle が必要な fallback 経路では `.claude/skills/extension/references/serve.md` を直接読み、起動・再利用・停止を本 skill に複製しない:

```bash
python3 -c "
from pathlib import Path
from youtube_automation.domains.suno.downloaded.workflow import read_pattern_count, expected_download_count
from youtube_automation.domains.suno.downloaded.archive import count_audio_files
from youtube_automation.domains.suno.prompts import read_suno_prompt_entries
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths

coll_dir = Path('.')  # アクティブなコレクションディレクトリで実行
pattern_count = read_pattern_count(coll_dir, prompt_entries_reader=read_suno_prompt_entries)
expected = expected_download_count(pattern_count)
actual = count_audio_files(CollectionPaths(coll_dir).music_dir)
print(f'pattern_count={pattern_count} expected={expected} actual={actual}')
"
```

- `pattern_count`: `20-documentation/suno-prompts.json` の entry 数
- `expected`（期待曲数）: `pattern_count × 2`。Suno は 1 Generate = 2 clip を生成するため、インスト / ボーカルいずれのモードでも共通の算式（ボーカルモードの 1 曲 1 winner 採用は Step 4.5 の後段処理であり、ダウンロード完了判定には影響しない）
- `actual`（実ファイル数）: `02-Individual-music/` 内の `.mp3` / `.m4a` / `.wav` ファイル数

判定:
- **`actual == 0`**: `/music --generate` 未実行として「`/music --generate` を実行してダウンロードを完了してください」を案内して停止
- **`0 < actual < expected`**: 部分ダウンロードとして扱う。`assets.music_downloaded` が `true` であっても揃っているとはみなさない。不足曲数（`expected - actual`）を提示し、「`/music --generate` を再実行して不足分を DL するか、Suno UI から手動で不足曲をダウンロードして `02-Individual-music/` に配置してください」を案内して既定では停止する。ユーザーが欠落込みの続行を明示指示した場合だけ、Step 4.5 の `--allow-incomplete-download` 手順へ進む
- 定期実行の extension state が `checkpoint` / `manual-intervention` / `running` の場合も、実ファイル数・`planning.music.suno_playlist_url`・`assets.music_downloaded` が揃うまでは停止する。extension state の `completed` は補助情報であり、この実ファイル突合を代替しない
- **`actual >= expected`**: チェック OK として Step 1.6 へ進む

`pattern_count` が `None`（`suno-prompts.json` が存在しない）の場合は期待曲数が算出不能なため本チェックをスキップし、以降の既存フローに委ねる。

### Step 1.6: playlist × suno-prompts.json 突合ゲート（必須・混入検出）

> **Step 5 前の共通ゲート**: この突合は Step 2 fallback 専用ではない。`02-Individual-music/` に音源があり Step 2-3 をスキップする primary path でも、Step 5 に進む前に必ず完了させる。

primary path では `02-Individual-music/` のローカルファイル名を第一手段とし、下記 CLI を実行する。`--music-dir` の相対パスは `<collection-path>` 基準で解決する。外部の title list 解決や対話確認は行わない。非正準形ファイル（Suno UI 手動 DL 由来の `Title.mp3` / `Title (1).mp3` / `Title_1.mp3` 等）は CLI が suno-prompts.json と照合して正準形 `NN{a|b}-Title.ext` へ自動リネームしてから突合する。照合できないファイルはリネームされず unknown として報告される。**playlist URL の記録有無に依らず本ゲートは完走できる** — 「Suno playlist URL がないため suno-prompts.json との突合ができません」型の停止は誤り。title list 提示 / 混入込み続行の 2 択分岐は `02-Individual-music/` に音声ファイルが 1 件も無い場合の最終 fallback に限る。

```bash
# primary path: 02-Individual-music/ の <2桁以上のentry index>{a|b}-<title>.<ext> を直接突合
uv run yt-suno-verify-playlist <collection-path> --music-dir 02-Individual-music
```

fallback path（Step 2-3 で DL する場合）は従来どおり Step 2 の WebFetch 結果から title list を作り、`--titles` または `--titles-file` で突合する。

判定:
- **unknown（どの entry にも一致しない曲）**: 別コレクション由来の混入。playlist から除外するまで Step 5 に進まない
- **missing（playlist に存在しない entry）**: 生成漏れ。`/music --generate` で追補生成するまで Step 5 に進まない
- **underfilled（clip 数が期待未満の entry）**: 生成が途中で止まった疑い。既定は 2 clip/entry（`--expected-clips-per-entry` で調整、`0` で無効化）。既定では停止し、Step 1.5 で欠落込みの続行が明示承認済みの場合だけ Step 4.5 の `--allow-incomplete-download` 手順へ進める
- 非 0 終了時はレポートをそのままユーザーへ提示して既定では停止する。unknown は、ユーザーが混入込みでの続行を明示指示した場合のみ、混入内容と影響（世界観不整合・メタデータずれ）を報告した上で続行できる。underfilled だけの非 0 は前項の明示承認時のみ例外とし、clip が 0 件の missing entry は引き続き停止する

> **背景**: playlist には「最新セットの生成が未完のまま、前後コレクションの曲が混入する」事故が繰り返し起きている（実例: 深夜コレクションに昼テーマ 2 ペアが混入 + 深夜 2 entry 未生成のまま master 化）。曲名は `/music --generate` が Song Title 欄へ注入する `entry.title ?? entry.name` で一意なため、機械突合で確実に検出できる。silent な続行は禁止。

### Step 2-3: MP3 の取得（suno-helper 済みなら不要）

`02-Individual-music/` に MP3 が揃っていれば Step 4 へ進む。揃っていない場合は
[suno-fallback.md](suno-fallback.md) の fallback 手順を使う。

### Step 4: 結果レポート

以下の表形式で全トラックの状態を一覧表示する:

```
| # | Filename                      | Size (MB) | Duration (s) | Status |
|---|-------------------------------|-----------|--------------|--------|
| 1 | 01-pattern-a-arrival.mp3      |      2.8  |       120.3  | OK     |
| 2 | 02-pattern-a-departure.mp3    |      3.1  |       135.7  | OK     |
| 3 | 03-pattern-b-drift.mp3        |      0.0  |          -   | FAIL: size < 10KB |
```

表の後にサマリー行を出す:
- **Total**: N files, XX.X MB
- **OK**: N / **FAIL**: N / **MISSING**: N
- 検証失敗または欠落がある場合は明示的に `Step 5 をブロック中 — 上記の FAIL / MISSING を解消してください` と表示

### Step 4.5: Suno clip 採用整理（歌詞-aware + 尺フィルタ）

`uv run yt-generate-master` の直前に `uv run yt-suno-select-tracks` を実行し、`02-Individual-music/` を master 入力として安全な状態に整理する。

本実行でファイル移動・削除が発生する前に、必ず dry-run で `pair_selection.min_song_sec` 未満の候補を確認する:

```bash
uv run yt-suno-select-tracks --dry-run <collection-path>
```

dry-run stdout の `[dropped_under_min]` セクションに 1 件以上ある場合は、各行の `source=<filename>` / `duration=<sec>s` / `min_song_sec=<sec>s` をユーザーへ提示し、続行可否を確認する。Claude Code では AskUserQuestion で「続行する」「続行しない」の 2 択を出す。AskUserQuestion 非対応環境（Codex 等）では、同じ情報をテキストで提示し、ユーザーの明示的な承認発言を待つ。

- **続行する**: 下記の本実行へ進み、既存の `pair_selection.out_of_range_action` に従って除外する。その後 Step 5 へ進む
- **続行しない**: 本実行を行わず、`/music --generate` での追補生成または該当曲の手動確認を案内して停止する。Step 5 へ進まない
- `[dropped_under_min]` に候補が無い場合: 確認プロンプトを出さず、下記の本実行へ進む。`pair_selection.max_song_sec` 超過だけの候補では、この確認プロンプトを出さない

```bash
uv run yt-suno-select-tracks <collection-path>
```

この CLI は `20-documentation/suno-prompts.json` と `02-Individual-music/` の音源を読み、`pair_selection.*` / `stock.*` 設定に従って以下を実行する:

1. **尺フィルタを先に適用**:
   - `pair_selection.min_song_sec` 未満の極端に短い曲を除外
   - `pair_selection.max_song_sec` 超過の極端に長い曲を除外
   - 既定は `45 <= duration <= 300` 秒
   - `max_song_sec: 300` は 5 分超の崩れた Suno 生成を混ぜないための既定値。チャンネル側の `config/skills/masterup.json` 優先、既存 `masterup.yaml` fallback で `pair_selection.max_song_sec` を明示的に上書きできる
   - 除外曲は `pair_selection.out_of_range_action` に従い、既定では `assets/stock/music/b-side/` へ退避する
   - 除外後にある prompt の採用候補が 0 件になった場合は fail-loud。基本は `/music --generate` で追補生成してから再実行する
2. **歌詞あり（vocal / lyrics あり）**:
   - `suno-prompts.json` の `lyrics` に実歌詞がある entry は、同じ prompt から生成された clip 群のうち 1 曲だけを winner として採用
   - winner は `02-Individual-music/<NN>-<title>.<ext>` に rename
   - loser は `assets/stock/music/b-side/` へ退避
   - winner 選定は `pair_selection.strategy: random`。seed は `pair_selection.random_seed`、未指定なら自動生成して `01-master/.selection.log` に記録する
3. **歌詞なし（instrumental / lyrics なし）**:
   - 同じ prompt から生成された 2 clip は両方採用する
   - 尺フィルタで落ちた clip だけ除外し、残った clip は `01a-...` / `01b-...` のまま `uv run yt-generate-master` に渡す

`lyrics` が `[Instrumental]` / `[Extended Outro]` などタグだけの場合は歌詞なしとして扱う。選別ログは `pair_selection.selection_log_path`（既定 `01-master/.selection.log`）に残す。

**2 clip 未満の prompt を含む場合の例外続行**:

既定では prompt ごとに 2 clip が必要であり、不足分の追補生成を優先する。各 prompt に少なくとも 1 clip は存在するものの、Suno の一部生成失敗などで追補せず続行することをユーザーが明示承認した場合だけ、不足 prompt と `実数/2`、instrumental の収録曲数が減る影響、vocal の代替候補がない影響を提示し、次の順で実行する。

```bash
uv run yt-suno-select-tracks --dry-run <collection-path> --allow-incomplete-download
uv run yt-suno-select-tracks <collection-path> --allow-incomplete-download
```

このフラグが無効化するのは初期の 2 clip 完了検査だけである。`pair_selection.min_song_sec` / `max_song_sec` の尺フィルタ、命名・duration probe、尺フィルタ後に候補 0 件となる prompt の停止は維持する。dry-run で `[dropped_under_min]` が出た場合は、通常どおり本実行前に別途続行確認を取る。

**max_song_sec 超過だけで全落ちした場合の復旧**:

この復旧は例外採用の承認を必要とし、非 dry-run の CLI が `workflow-state.json::music_pair_selection` と `updated_at` を更新する。subagent へは委譲せず、対象 prompt・候補・duration を提示して承認を得た後、メインエージェントが次のコマンドを実行する。

```bash
uv run yt-suno-select-tracks <collection-path> --allow-best-effort-over-max
```

このフラグは、ある prompt の全候補が `pair_selection.max_song_sec` 超過だけで落ちた場合に限り、最短の候補を 1 曲だけ警告付きで例外採用する。短すぎる音源（`min_song_sec` 未満）や probe 失敗は壊れた生成として引き続き fail-loud。例外採用した候補は `01-master/.selection.log` の `[exceptions_over_limit]` と `workflow-state.json::music_pair_selection.exceptions_over_limit` に、対象ファイル・duration・理由付きで記録される。

安全契約:

- `pair_selection.selection_log_path` は collection dir 配下の相対パスのみ許可する。絶対パスや `..` は fail-loud
- `stock.dir` はチャンネルルートの `assets/stock/` 配下の相対パスのみ許可する。既定は `assets/stock/music/b-side/`
- `stock.filename_template` の placeholder は `collection_slug` / `song_id` / `title_slug` / `ext` のみ。生成ファイル名は basename のみ許可する
- `stock.on_duplicate` は `skip` / `overwrite` / `fail` のみ。`fail` と不正設定はファイル移動・削除・rename・log 書き込み前に停止する
- 対応音声拡張子（`.mp3` / `.m4a` / `.wav`）で命名規則に合わないファイルが `02-Individual-music/` にある場合は、後段 `uv run yt-generate-master` への混入防止のため fail-loud
- 全検証が通るまでファイル移動・削除・rename・log 書き込みは行わない。非 0 終了時は入力音源を再実行可能な状態に残す

**dry-run**:

```bash
uv run yt-suno-select-tracks <collection-path> --dry-run
```

ファイル移動なしで winner / loser / 尺外除外の plan を stdout に出す。`[dropped_under_min]` には `pair_selection.min_song_sec` 未満で除外される候補だけが、ファイル名・duration・設定中の `min_song_sec` 付きで表示される。

### Step 5: マスター音源生成（CLI）

**前提条件（検証ゲート）**: Step 3〜4.5 の検証が **全件 OK** である場合にのみ本ステップを実行する。以下のいずれかに該当する場合は **Step 5 を実行してはならない**（不完全な master.mp3 の生成を防止）:
- Step 3 の検証で `failed` 配列が空でない（サイズ異常・再生時間異常・Content-Type 不正）
- 期待ファイル突合チェックで `missing` 配列が空でない
- Step 2 の件数突合で不一致が検出されている
- Step 1.6 の `uv run yt-suno-verify-playlist` が未実行、検証不能、または非 0 終了している（混入 / 生成漏れ / clip 不足。ユーザーが混入込み続行を明示指示した場合を除く）
- Step 4.5 の `uv run yt-suno-select-tracks` が非 0 終了している（尺フィルタ後の採用候補 0 件、stock 移動失敗など）

検証失敗時は Step 4 / 4.5 のレポートを提示し、ユーザーに手動修正（再ダウンロード / Suno UI からの手動取得 / `/music --generate` 追補生成）を促してから再実行する。

#### Step 5.0: Suno 個別音源の音質補正（既定 ON / config opt-out）

マスター結合前に `02-Individual-music/` の各 Suno 音源へ ffmpeg 後処理を適用する:

```bash
uv run yt-suno-audio-cleanup plan <collection-path>   # まず対象と ffmpeg filter を確認
uv run yt-suno-audio-cleanup apply <collection-path>  # 元ファイルを originals-pre-cleanup/ に退避して同名置換
uv run yt-suno-audio-cleanup apply <collection-path> --jobs 1  # 明示的な直列実行
```

`apply` は曲単位で最大2件を並列処理する。最大並列数は `--jobs` → `post_processing.suno_audio_cleanup.max_workers` → `2` の順で解決し、安全上限は8とする。失敗時は新しい曲を投入せず、開始済み処理を回収してファイル名順にエラーを報告する。`--jobs 1` は worker thread を作らず、従来どおり各曲の進捗と例外を直ちに呼び出し元へ渡す。`plan` はファイル名順に ffprobe で長さを調べてコマンドを表示するが、ffmpeg encode は起動しない。

適用内容:

- 冒頭無音カット (`silenceremove`)
- 350Hz 付近のもやつき / 8kHz 付近のシャリつきを軽く抑える EQ
- 曲中の音量ムラを `dynaudnorm` で緩和
- `alimiter` による瞬間ピーク抑制
- 既定 `-14 LUFS` の `loudnorm`
- 後半崩れの被害を抑える末尾 fade-out guard

同梱既定は `enabled: true`。従来どおり cleanup せず結合するチャンネルは、`config/skills/masterup.json`（JSON が無ければ互換 `masterup.yaml`）で次のように明示 opt-out する:

```json
{
  "post_processing": {
    "suno_audio_cleanup": {
      "enabled": false
    }
  }
}
```

`enabled: false` の場合は何もしない。単発で明示実行する場合は `--force` を付けて `plan/apply` できる。既に backup があるファイルは二重処理を避けるため skip される（再処理する場合も `--force`）。

#### Step 5.1: 曲間ラウドネス偏差ゲート

cleanup の有効・無効にかかわらず、マスター結合前に次の単一スクリプトを1回だけ実行する。計測・閾値判定・逸脱曲の特定はスクリプトを正とし、本文で再計算しない。receipt は対象 collection、全入力ファイルの basename / size / SHA-256、実測 LUFS、適用閾値、判定、全曲走査回数を保持する。

```bash
LOUDNESS_SCRIPT="$(git rev-parse --show-toplevel 2>/dev/null)/.claude/skills/music/references/check_loudness_deviation.py"; if [ ! -f "$LOUDNESS_SCRIPT" ]; then printf 'ERROR: loudness gate script not found: %s\n' "$LOUDNESS_SCRIPT" >&2; exit 1; fi; uv run python3 "$LOUDNESS_SCRIPT" <collection-path> --receipt <collection-path>/01-master/.loudness-receipt.json
```

`git rev-parse` は同期済み skill が置かれた workspace root だけを解決し、実行 CWD は変更しない。したがって `channels/<channel>` を CWD にするマルチチャンネル workspace でも、そのチャンネルの `config/channel/` を読みながら同梱スクリプトを起動できる。

- exit 0: PASS と全曲の実測 LUFS を表示し、atomic write 済み receipt とともに Step 5 本体へ進む
- exit 1: スクリプト不在などの起動失敗、計測または設定エラー。表示された原因を解消して再実行し、Step 5 本体へ進まない
- exit 2: FAIL。逸脱曲、実測 LUFS、目標範囲を表示し、state を変更せず停止する。`uv run yt-suno-audio-cleanup plan <collection-path> --force` で対象を確認し、`apply --force` 後に本ゲートを再実行する

receipt が欠落・JSON破損・別 collection・入力ファイル不一致・現在の設定閾値と不一致・FAIL のいずれかなら fail closed とする。古い receipt や閾値違反を承認だけで通過させず、現在の全入力に対する PASS receipt を作り直す。

#### Step 5 本体: マスター結合の実行

ダウンロード完了後、`uv run yt-generate-master` CLI でマスター音源を自動生成:

```bash
uv run yt-generate-master                          # CWD がコレクションディレクトリのとき
uv run yt-generate-master <collection-path>        # 明示指定
uv run yt-generate-master --loop 3                 # 全トラックを 3 回繰り返して結合
uv run yt-generate-master --target-duration 150    # 150 分以上になる最小ループ回数を自動算出
uv run yt-generate-master --shuffle                # ループ展開前にトラック順をランダム化
uv run yt-generate-master --shuffle-seed 42        # 再現性 seed 指定（--shuffle を暗黙有効化）
uv run yt-generate-master --pin-first 00-hook.mp3 --shuffle           # 指定 1 曲を先頭固定 + 残りシャッフル
uv run yt-generate-master --pin-first-count 1 --shuffle               # ソート済み先頭 1 件を固定 + 残りシャッフル
```

`02-Individual-music/` のオーディオファイル（MP3 / M4A / WAV）を自動検出し、skill-config の `audio.crossfade_duration` / `audio.bitrate` でクロスフェード結合します。チャンネルごとに変更する場合は `config/skills/masterup.json`、または JSON が存在しない既存チャンネルでは `config/skills/masterup.yaml` の `audio` section を更新してから、フラグなしで本 CLI を実行します。`domains.metadata.service.BAHMetadataGenerator` のタイムスタンプ計算と同じ設定値を参照するため、実音声と description のタイムスタンプが常に一致します。suno-helper の DL フォーマット設定（`sunoDownloadFormat`）により入力形式が MP3 以外になる場合があるため、拡張子で判別する。
**この処理は常にダウンロード後（または suno-helper DL 済み確認後）に自動実行する。**

生成成功後、メインは次のコマンドで receipt と現在の入力・閾値を再検証し、PASS の場合だけ `assets.raw_master` / `updated_at` を原子的に更新する。receipt 検証は SHA-256 と保存済み測定値の再計算だけを行い、FFmpeg の全曲走査を繰り返さない。

```bash
uv run yt-raw-master-check <collection-path> --apply \
  --loudness-receipt <collection-path>/01-master/.loudness-receipt.json
```

このコマンドが非 0 なら state を変更せず停止する。`workflow-state.json` を手編集して検証を迂回しない。

**ループ時の注意**: `--loop` / `--target-duration` は Suno/Lyria のトラック数が少ないコレクションで raw master の尺を target に届かせるためのオプション。`--loop` / `--target-duration` / `--no-loop` は同時指定不可。実行前にトラック総尺・目標尺・ループ回数・見込み尺の preview が表示される。目標尺の SSOT は `config/channel/audio.json::audio.target_duration_min/max`。1 pass が min 未満かつ整数ループが max を超える場合は生成を停止し、`--no-loop`、部分ループ素材、target 変更、または operator 判断の `--allow-duration-outside-target` を選ぶ。upload plan も同じ範囲を検証し、例外時は同 flag の明示が必要。全ループ分の YouTube チャプターが必要な場合は、preview の loop count と同じ `N` を `domains.metadata.service.BAHMetadataGenerator.generate_timestamps(loops=N)` / `format_timestamps_text(loops=N)` に渡して展開する。1 ループ分のみ載せる従来運用は `loops=1` のままで変更なし。

**シャッフル時の注意**: `--shuffle` はループ展開の**前**に 1 回だけ実行され、シャッフルされた順序がループごとに同じ並びで N 回繰り返される（ループごとに独立してシャッフルし直すわけではない）。再現性が必要な場合は `--shuffle-seed N` を指定するか、`--shuffle` 単独実行時に stdout に出る `[Shuffle] seed=<N>` の値を控えておけば後で同じ並びを再現できる。再現性ログは `--quiet` 指定時も常に出力される。

**先頭固定時の注意**: `--pin-first <files...>` は引数順を保持して先頭に固定する。`--pin-first-count N` は `02-Individual-music/` のソート済み先頭 N 件を固定する。両者は mutually exclusive（同時指定で argparse エラー）。`--shuffle` 併用時は pin された曲は順序固定のまま、残りのみシャッフルされる（要件: retention に強いフック曲を冒頭に置きつつ後半の類似イントロクラスタ化を回避）。`--target-duration` / `--loop` 併用時もループ展開の前段で先頭固定処理が適用される。`--pin-first` 指定ファイルが `02-Individual-music/` に存在しない場合は fail-loud で停止する。スキル設定 `audio.pin_first_count` を `1` 以上にしておけば、CLI フラグなしでもチャンネル単位のデフォルトとして自動適用される。

### Step 5.5: ambient レイヤー整音（オプション）

`branding/<dirname>/<glob>` 配下に該当ファイルを持つチャンネルでは、マスター生成後に環境音 (雨音など) をレイヤーする:

```bash
uv run yt-finalize-master                       # CWD がコレクションディレクトリ
uv run yt-finalize-master <collection-path>     # 明示指定
```

既定では `branding/rain_layers/rain_*.wav` を探索（既存 v5.5.0 互換）。`branding/rain_layers/` ディレクトリが無い／`rain_*.wav` が 0 件のチャンネルでは何もせず exit 0（pass-through）。`master.mp3` は `master.tmp.mp3` 経由 atomic rename で in-place 上書きされる（pass2 失敗時は元 master が保護される）。

#### skill-config 設定マトリクス (`audio.finalize.*`)

`uv run yt-finalize-master` の音響パイプラインは全項目を skill-config から注入できる（#512）。
すべて任意キーで、未指定時は組み込みデフォルトが既存 v5.5.0 と同じ挙動を再現する。

| キー | 既定 | 説明 |
|---|---|---|
| `audio.finalize.bitrate` | `audio.bitrate` を流用 (`"192k"`) | 出力ビットレート（ffmpeg `-b:a`） |
| `audio.finalize.codec` | `"libmp3lame"` | 出力コーデック（ffmpeg `-c:a`） |
| `audio.finalize.sample_rate` | (未指定) | 出力サンプリングレート（ffmpeg `-ar`）。未指定なら master 由来 |
| `audio.finalize.ambient_layers.dirname` | `"rain_layers"` | `branding/<dirname>/` 探索ディレクトリ名 |
| `audio.finalize.ambient_layers.glob` | `"rain_*.wav"` | `<dirname>/` 配下の対象 glob |
| `audio.finalize.ambient_layers.volume_db` | `-19` | 全レイヤー共通の音量 dB |
| `audio.finalize.ambient_layers.fadein_s` | `0.5` | 頭の不連続抑制 (`afade`) 秒数 |
| `audio.finalize.ambient_layers.fadein_curve` | `"tri"` | `afade` の curve (`tri`/`exp`/`log`/`qsin`/`hsin`/`esin`/`cub`/`squ`/`par` …) |
| `audio.finalize.ambient_layers.layers.<filename>` | (未指定) | per-file 上書き（`volume_db` / `fadein_s` / `fadein_curve`） |
| `audio.finalize.loudnorm.enabled` | `true` | `false` で pass1/pass2 を skip し `amix` 単発で encode |
| `audio.finalize.loudnorm.mode` | `"linear"` | `"linear"` のみサポート。`"dynamic"` 指定時は `NotImplementedError` |
| `audio.finalize.loudnorm.I` | `-14` | integrated loudness 目標（LUFS） |
| `audio.finalize.loudnorm.LRA` | `11` | loudness range 目標 |
| `audio.finalize.loudnorm.TP` | `-1.5` | true peak 目標（dBTP） |
| `audio.finalize.mix.duration` | `"first"` | ffmpeg `amix duration`（`first`/`shortest`/`longest`） |
| `audio.finalize.mix.normalize` | `0` | ffmpeg `amix normalize`（`0`/`1`、`true`/`false` も可） |

**Fail-loud ルール**:
- `loudnorm.mode: dynamic` → `NotImplementedError`（two-pass linear 専用設計の明示）
- `loudnorm.mode` がその他不正値 / `mix.duration` 不正値 / `mix.normalize` 範囲外 / `layers` が dict 以外 → `ConfigError`
- `layer_overrides` 長と layer 数の不一致（内部契約） → `ValidationError`

#### per-file 上書き設定例

```yaml
audio:
  finalize:
    ambient_layers:
      volume_db: -19            # 全 layer 共通
      fadein_s: 0.5
      layers:
        rain_001.wav:
          volume_db: -22         # この 1 ファイルだけ -22dB で被せる
        rain_002.wav:
          fadein_s: 1.5          # フェードインだけ長くしたい
          fadein_curve: "exp"    # 指数カーブで自然に立ち上げる
    loudnorm:
      enabled: true
      I: -14
      LRA: 11
      TP: -1.5
    mix:
      duration: "first"          # master の長さで切る (環境音は aloop 展開済み)
      normalize: 0               # amix の自動 0.5x スケーリングを無効化
```

#### `loudnorm.enabled: false`（1-pass モード）

整音不要・amix 結果をそのまま出したい場合は `loudnorm.enabled: false` で `ffmpeg` の呼び出し回数を 1 回（amix → encode 直行）に短縮できる。pass1 の measure を行わないため処理時間も半分以下になる。

```yaml
audio:
  finalize:
    loudnorm:
      enabled: false             # pass1/pass2 を skip
```

### Step 5.6: 雨レイヤー後処理（config 駆動 / opt-in）

`uv run yt-finalize-master` が master.mp3 を **loudnorm 二段で in-place 上書き**するのに対し、`uv run yt-apply-rain-layers` は raw master と `branding/rain_layers/*.wav` を **amix のみ**で合成し**別ファイル**（既定 `01-master/master-rain.wav`）に書き出す軽い後処理 CLI。後段で外部 DAW のミキシング+マスタリングを挟む運用（raw master を保持したまま雨レイヤー付きバージョンを並行管理したい場合）向け。

この CLI は出力成功時に `workflow-state.json::assets.raw_master` を owner 経由で更新し、成果物生成だけを行うオプションを持たない。subagent 実行時はこの Step を実行せず、subagent の成果物をメインエージェントが検証して `yt-workflow-state` を実行した後、メインエージェントが次のコマンドを実行する。

```bash
uv run yt-apply-rain-layers                       # CWD がコレクションディレクトリ
uv run yt-apply-rain-layers <collection-path>     # 明示指定
uv run yt-apply-rain-layers --dry-run             # ffmpeg コマンドを表示するだけで実行しない
```

挙動:

- `post_processing.rain_layers.enabled: false`（既定）→ 何もせず exit 0
- `enabled: true` だが `branding/rain_layers/*.wav` が 0 件 → **fail-loud**（rc=1。レイヤー WAV を配置するか `enabled: false` にする）
- `enabled: true` + WAV が在る → ffmpeg で各レイヤーを `-stream_loop -1` で master 尺までループ → `volume={volume_db}dB` で減衰 → `amix=duration=first:normalize=0` で master と合成 → `pcm_s16le` / `44100Hz` / stereo の WAV を出力
- 出力成功時に `workflow-state.json::assets.raw_master` を `output_name` で上書き（後段の `/wf-next` などが新出力を参照するため）

`uv run yt-finalize-master`（`audio.finalize:` namespace）と `uv run yt-apply-rain-layers`（`post_processing.rain_layers:` namespace）は**独立した opt-in**。両方有効化すると master.mp3 への loudnorm 上書きと master-rain.wav の別ファイル出力が両方走るので、片方だけ使う運用を推奨する。

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

**`--delete` を付けない理由**: メイン側で `/thumbnail` や `/thumbnail --loop` 等によって先行生成された素材（例: `10-assets/main.png`, `10-assets/loop.mp4`）が worktree 側に存在しないことがあり、`--delete` を付けるとそれらが消えてしまう。worktree 側で新規追加されたファイルだけメインに上書き反映する片方向追加同期で十分。

**この処理は常にマスター生成後に自動実行する（ワークツリー実行時のみ）。**

### 完了時の更新

生成したマスターファイル名（例: `master.mp3`）を JSON string として `uv run yt-workflow-state --collection <collection-path> set-asset raw_master <json-value>` へ渡す。owner CLI が同じ lock 内で `updated_at` も更新する。

`phase` は `"prepared"` のまま変更しない。`raw_master` → `master_audio` 確定後の `"mastered"` フェーズ遷移は `/wf-next` の責務（本スキルはユーザーのミキシング+マスタリング前の raw master 生成までを担う）。

## CDN URL パターン (DEPRECATED -- fallback only)

> suno-helper の一括ダウンロード機能が primary path。CDN curl は suno-helper が使えない場合のフォールバックとしてのみ利用する。

| 形式 | URL | 認証 |
|------|-----|------|
| MP3 | `https://cdn1.suno.ai/{song_id}.mp3` | 不要 |

## 所要時間と完了報告

`uv run yt-generate-master`（ffmpeg クロスフェード結合）は **30 秒〜2 分**。Step 3 の `curl` による MP3 一括ダウンロードも曲数が多いと数十秒〜分単位かかる。

ログを `/tmp/music-master-$(date +%s).log` へ redirect し、完了後は末尾から `master.mp3` のパスとダウンロード成功曲数を報告する。background 実行フラグを持たない環境（Codex 等）では `nohup ... > <log> 2>&1 &` を使い、完了はログ末尾で確認する。

## オーディオビジュアライザー / オーバーレイ

`/music --master` は**音源（mp3 / wav）を作る工程**で、映像オーバーレイ（ビジュアライザー・波形・購読ボタンポップアップ等）は扱わない。
ユーザーから「ビジュアライザー付きで」「波形を出して」等の指示があっても、`/music --master` 段階では何も合成できない。

ビジュアライザー周りの現行仕様は `/video --generate` の「オーディオビジュアライザー / オーバーレイについて」節を参照。必要な場合は `/video --generate` 実行前に `config/channel/youtube.json::overlays.enabled: true` と overlay 詳細設定を用意する。
誤指示の事故防止のため、`/music --master` 着手前に動画にオーバーレイが必要かをユーザーへ確認すること（#646 feedback）。

## Next Step

- `/video --generate` で動画生成を実行
