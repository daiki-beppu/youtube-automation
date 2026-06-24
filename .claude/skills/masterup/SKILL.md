---
name: masterup
description: "Use when /suno で生成したプロンプトを Suno UI で曲にしたあと、そのプレイリストを DL + クロスフェードマスター化したいとき。前工程: /suno（プロンプト生成 → Suno UI で人手楽曲生成）。プレイリスト URL を指定して mp3/m4a/wav 一括 DL + マスター音源を自動生成（次工程: /videoup）。Lyria チャンネルでは /lyria が自動で音源を出力するため本スキルは不要"
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
| `audio.pin_first_count` | `0` | `yt-generate-master` で CLI `--pin-first` / `--pin-first-count` 未指定時に `--pin-first-count N` 相当のデフォルトとして採用される。ソート済み先頭 N 件を順序固定する（`audio.shuffle: true` と併用時は残りだけシャッフル）。`0` = 固定なし。retention に強い 1 曲を冒頭に置きたいときに `1` 以上を設定する |
| `suno_download.cdn_url_template` | `https://cdn1.suno.ai/{song_id}.mp3` | Suno CDN URL テンプレート |
| `post_processing.rain_layers.enabled` | `false` | `yt-apply-rain-layers` の opt-in スイッチ。`true` で `branding/rain_layers/*.wav` を raw master に amix する後処理を有効化する |
| `post_processing.rain_layers.volume_db` | `-19` | 各レイヤーに当てる減衰 dB（10^(-19/20) ≈ 0.112）。`yt-apply-rain-layers` が ffmpeg `volume={dB}` でレイヤー毎に適用 |
| `post_processing.rain_layers.output_name` | `master-rain.wav` | 後処理出力ファイル名（`01-master/` 配下）。成功時に `workflow-state.json::assets.raw_master` がこの名前へ書き換わる |
| `post_processing.rain_layers.output_codec` / `.output_sample_rate` | `pcm_s16le` / `44100` | 出力 WAV の ffmpeg コーデックとサンプリングレート（ステレオ固定）。後段の外部 DAW でミキシング+マスタリングする運用想定 |

マスター音源生成は `yt-generate-master` CLI が同じ skill-config を読み込むため、`audio.crossfade_duration` は実音声のクロスフェードと metadata_generator のタイムスタンプ計算で常に一致する。

## When to Use

**前工程:** `/suno`（プロンプト生成 → Suno UI で人手楽曲生成）

- `/suno` のプロンプトで生成した楽曲のプレイリストを作成したとき
- SunoAI の楽曲をダウンロードしたいとき（mp3/m4a/wav 対応）
- マスター音源（Complete Collection 用）を生成したいとき

Lyria で音源を生成するチャンネルでは `/lyria` が master.wav を直接出力するため本スキルは不要。

## Quick Reference

| コマンド | 説明 | 例 |
|---------|------|-----|
| `/masterup <playlist-url>` | プレイリスト内の全曲をDL + マスター生成 | `/masterup https://suno.com/playlist/xxx` |
| `yt-generate-master --loop N` | マスター生成時に全トラックを N 回繰り返して結合 | `yt-generate-master --loop 3` |
| `yt-generate-master --target-duration MIN` | 目標尺 (分) 以上になる最小ループ回数を自動算出 | `yt-generate-master --target-duration 150` |
| `yt-generate-master --shuffle` | 連結前に音声ファイルリストをシャッフル（OS entropy で seed 自動生成、stdout に `[Shuffle] seed=<N>` を出力） | `yt-generate-master --shuffle` |
| `yt-generate-master --shuffle-seed N` | シャッフル順を固定（`--shuffle` を暗黙有効化、再現性検証用） | `yt-generate-master --shuffle-seed 42` |
| `yt-generate-master --pin-first <files...>` | 先頭固定する音声ファイル名を順番指定（`--shuffle` 併用時も pin の順序は保持） | `yt-generate-master --pin-first 00-hook.mp3 --shuffle` |
| `yt-generate-master --pin-first-count N` | ソート済み先頭 N 件を固定（`--shuffle` 併用時は残り N+1〜末尾のみシャッフル） | `yt-generate-master --pin-first-count 1 --shuffle` |
| (skill-config) `audio.target_duration_min` | CLI フラグ未指定時のデフォルト目標尺（分）。`config/skills/masterup.yaml` で設定 | `target_duration_min: 120` |
| (skill-config) `audio.shuffle` | CLI フラグ未指定時のデフォルトシャッフル設定 | `shuffle: true` |
| (skill-config) `audio.shuffle_seed` | `audio.shuffle: true` 時のデフォルト seed（整数） | `shuffle_seed: 42` |
| (skill-config) `audio.pin_first_count` | CLI フラグ未指定時のデフォルト先頭固定数（`0` = 固定なし） | `pin_first_count: 1` |

## Suno 依存の脆弱性と復旧手段

本スキルは **Suno の公式 API ではなく**、UI でレンダリングされる HTML（WebFetch）と CDN URL パターン（`https://cdn1.suno.ai/{song_id}.mp3`）への curl アクセスという **非公式・非サポートな経路** に依存している。Suno 側の UI / CDN 仕様は事前告知なく変更されうるため、ある日突然 `/masterup` 全体（あるいは Step 2 / Step 3）が壊れる可能性があることを前提に運用すること。

### どこが壊れうるか

| 経路 | 依存箇所 | 壊れた場合の症状 |
|------|----------|------------------|
| プレイリスト HTML スクレイピング | Step 2 / WebFetch | プレイリストページ DOM や `song_count` 等のメタ表記が変わり曲リスト・総曲数が取れない |
| CDN URL パターン | Step 3 / `https://cdn1.suno.ai/{song_id}.mp3` | URL 構造変更・署名要求化・ホスト変更で 403 / 404 が返る |
| プレイリスト公開可否 | Step 2 全体 | プレイリストの未ログイン公開が廃止され HTML 取得そのものが不能になる |

### 壊れた時の判定フロー

1. **Step 2 で曲リストが取れない** → Suno UI の HTML 構造変更を疑う。WebFetch 結果を生で確認し、プロンプトを更新して回避できるかを試す。回避不可なら下記フォールバックへ。
2. **Step 3 で 403 / 404 が連発** → CDN URL パターン変更を疑う。1 曲を手動で Suno UI からダウンロードして MIME / URL を確認し、`suno_download.cdn_url_template` の更新で吸収できるか判定する。吸収不可なら下記フォールバックへ。
3. いずれの場合も **silent な続行は禁止**（不完全な master.mp3 を生成しない）。ユーザーへ「Suno 経路が壊れた可能性が高い。fallback 運用に切替推奨」と明示報告し、停止する。

### フォールバック運用（手動ダウンロード → `yt-generate-master` 直叩き）

`/masterup` の Step 1 / Step 5 / Step 5.5 / Step 6 / 完了時の更新は mp3 / m4a / wav のいずれかが `02-Individual-music/` に揃っていれば成立するため、Step 2 / Step 3 を **手動で代替**することで運用継続できる:

1. Suno UI から曲を 1 つずつ mp3 / m4a / wav のいずれかでダウンロード（公式に提供されている UI 経路。サブスク権利範囲内）
2. アクティブコレクションの `02-Individual-music/` に配置し、ファイル名を連番 + タイトルで揃える（例: `01-pattern-a-arrival.mp3` / `01-pattern-a-arrival.m4a` / `01-pattern-a-arrival.wav`）
3. `uv run yt-generate-master`（または `--target-duration` / `--shuffle` などのオプション付き）を **直接実行**
4. 必要に応じて `uv run yt-finalize-master`（雨音レイヤー）→ Step 6 の `rsync` 同期を **手動で順番に実行**
5. `workflow-state.json` の `music.approved = true` / `mp3_count` / `master_audio` / `phase = "music-approved"` を手動更新（または `/masterup` の「完了時の更新」を別途呼ぶ）

このフォールバックは **`/masterup` が壊れていても master.mp3 を生成できる最小経路**であり、Suno 公式 API 公開までの暫定運用として機能する。

### Suno 公式 API 公開時の移行プラン

Suno が公式 API（プレイリスト一覧 / 楽曲メタデータ / ダウンロード URL）を公開した場合の移行方針:

1. **新規 `yt-suno-fetch` CLI を追加**（`scripts/` 配下、`yt-*` プレフィックス踏襲、`pyproject.toml::[project.scripts]` 登録）。公式 API クライアントを実装し、認証情報は `auth/suno_token.json` 等の独立ファイル + `utils/secrets.py::_SECRET_REFS` 経由で解決する。
2. **本 SKILL.md の Step 2 / Step 3 を書き換え**、WebFetch + CDN curl の経路を `yt-suno-fetch` 呼び出しに置換する。skill-config の `suno_download.cdn_url_template` は deprecated として `config.default.yaml` に deprecation note を残し、しばらくは「API 障害時の緊急 fallback」として併存させる。
3. **非公式経路は別 skill `/masterup-legacy` へ退避**するか、もしくは本 SKILL.md 内で `mode: "official" | "legacy"` を切替可能にする（移行期間中の保険）。
4. 公式 API が安定し下流チャンネル全てが移行完了したら非公式経路を削除し、`suno_download.cdn_url_template` を skill-config からも除去する（破壊的変更として major version bump）。

移行作業は本 issue とは別 issue で扱う。Suno が公式 API 公開を発表した時点で本セクションのリンクとして issue を起票すること。

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
2. prompt で全曲の情報を抽出するよう指示。**プレイリスト全体の総曲数（メタ表記）も同時に取得する**:
   - プレイリスト総曲数（HTML 内の `song_count` / `songs · NN tracks` / `NN songs` 等のメタ表記。**必須**）
   - 各曲のタイトル
   - 各曲の Song ID（UUID）
   - 各曲の再生時間
3. **件数突合チェック（必須・silent な取りこぼし禁止）**:
   - WebFetch 結果から `len(songs)` を数え、ステップ 2 で取得した「プレイリスト総曲数」と突合する
   - **不一致なら処理を中断**し、ユーザーへ次のメッセージで報告する:
     > ⚠️ プレイリスト総曲数 (N) と取得件数 (M) が一致しません。WebFetch は suno.com のサーバー描画分（50 曲まで）しか見えないため、51 曲目以降は遅延読み込みで取りこぼされます。
     > 対処: (a) プレイリストを 50 曲以下に分割して再実行 / (b) 全件を手動で mp3 / m4a / wav のいずれかとして `02-Individual-music/` に揃えてから `yt-generate-master` を直接実行
   - 総曲数のメタ表記が WebFetch から取得できなかった場合も同様に中断し、ユーザーへ「件数突合不能のため処理を停止」と報告する（silent な続行を禁止）
   - **総曲数 ≤ 50 で件数が一致した場合のみ Step 3 へ進む**
4. WebFetch の結果から曲リストをパースして Step 3 に渡す

**取得手段のフォールバック方針**: WebFetch は suno.com のサーバー描画分（上限 50 件）しか拾えないため、本 skill は「50 曲以下のプレイリスト」を前提運用とする。50 曲超のプレイリストは現状 50 曲単位に分割して個別実行するか、手動で `02-Individual-music/` に mp3 / m4a / wav を揃えてから `yt-generate-master` を直接実行するワークフローへ切り替える（内部 API / 公式 API への移行は別 issue）。

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
yt-generate-master --pin-first 00-hook.mp3 --shuffle           # 指定 1 曲を先頭固定 + 残りシャッフル
yt-generate-master --pin-first-count 1 --shuffle               # ソート済み先頭 1 件を固定 + 残りシャッフル
```

`02-Individual-music/` の mp3 / m4a / wav を自動検出し、skill-config の `audio.crossfade_duration` / `audio.bitrate` でクロスフェード結合して `master.mp3` を生成します。metadata_generator のタイムスタンプ計算と同じ設定値を参照するため、実音声と description のタイムスタンプが常に一致します。
**この処理は常にダウンロード後に自動実行する。**

**ループ時の注意**: `--loop` / `--target-duration` は Suno/Lyria のトラック数が少ないコレクションで raw master の尺を target に届かせるためのオプション。`--loop` と `--target-duration` は同時指定不可。`metadata_generator` が生成する YouTube タイムスタンプは現状 **1 ループ分のみ** なので、動画尺が timestamp 末尾より長くなる（DJ セット動画では許容範囲。複数ループを timestamp に反映したい場合は別途 issue 化）。

**シャッフル時の注意**: `--shuffle` はループ展開の**前**に 1 回だけ実行され、シャッフルされた順序がループごとに同じ並びで N 回繰り返される（ループごとに独立してシャッフルし直すわけではない）。再現性が必要な場合は `--shuffle-seed N` を指定するか、`--shuffle` 単独実行時に stdout に出る `[Shuffle] seed=<N>` の値を控えておけば後で同じ並びを再現できる。再現性ログは `--quiet` 指定時も常に出力される。

**先頭固定時の注意**: `--pin-first <files...>` は引数順を保持して先頭に固定する。`--pin-first-count N` は `02-Individual-music/` のソート済み先頭 N 件を固定する。両者は mutually exclusive（同時指定で argparse エラー）。`--shuffle` 併用時は pin された曲は順序固定のまま、残りのみシャッフルされる（要件: retention に強いフック曲を冒頭に置きつつ後半の類似イントロクラスタ化を回避）。`--target-duration` / `--loop` 併用時もループ展開の前段で先頭固定処理が適用される。`--pin-first` 指定ファイルが `02-Individual-music/` に存在しない場合は fail-loud で停止する。スキル設定 `audio.pin_first_count` を `1` 以上にしておけば、CLI フラグなしでもチャンネル単位のデフォルトとして自動適用される。

### Step 5.5: ambient レイヤー整音（オプション）

`branding/<dirname>/<glob>` 配下に該当ファイルを持つチャンネルでは、マスター生成後に環境音 (雨音など) をレイヤーする:

```bash
yt-finalize-master                       # CWD がコレクションディレクトリ
yt-finalize-master <collection-path>     # 明示指定
```

既定では `branding/rain_layers/rain_*.wav` を探索（既存 v5.5.0 互換）。`branding/rain_layers/` ディレクトリが無い／`rain_*.wav` が 0 件のチャンネルでは何もせず exit 0（pass-through）。`master.mp3` は `master.tmp.mp3` 経由 atomic rename で in-place 上書きされる（pass2 失敗時は元 master が保護される）。

#### skill-config 設定マトリクス (`audio.finalize.*`)

`yt-finalize-master` の音響パイプラインは全項目を skill-config から注入できる（#512）。
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

#### 旧 `rain_layer` namespace（DEPRECATED, #512）

旧 v5.5.0 までの `rain_layer:` namespace は後方互換 alias として読み続けるが、利用するとプロセス起動時に `DeprecationWarning` が出る。新 `audio.finalize.*` namespace へ移行すること。新旧両方を同時に書いた場合は新が勝ち、旧は無視される（warning も出ない）。

### Step 5.6: 雨レイヤー後処理（config 駆動 / opt-in）

`yt-finalize-master` が master.mp3 を **loudnorm 二段で in-place 上書き**するのに対し、`yt-apply-rain-layers` は raw master と `branding/rain_layers/*.wav` を **amix のみ**で合成し**別ファイル**（既定 `01-master/master-rain.wav`）に書き出す軽い後処理 CLI。後段で外部 DAW のミキシング+マスタリングを挟む運用（raw master を保持したまま雨レイヤー付きバージョンを並行管理したい場合）向け。

```bash
yt-apply-rain-layers                       # CWD がコレクションディレクトリ
yt-apply-rain-layers <collection-path>     # 明示指定
yt-apply-rain-layers --dry-run             # ffmpeg コマンドを表示するだけで実行しない
```

挙動:

- `post_processing.rain_layers.enabled: false`（既定）→ 何もせず exit 0
- `enabled: true` だが `branding/rain_layers/*.wav` が 0 件 → **fail-loud**（rc=1。レイヤー WAV を配置するか `enabled: false` にする）
- `enabled: true` + WAV が在る → ffmpeg で各レイヤーを `-stream_loop -1` で master 尺までループ → `volume={volume_db}dB` で減衰 → `amix=duration=first:normalize=0` で master と合成 → `pcm_s16le` / `44100Hz` / stereo の WAV を出力
- 出力成功時に `workflow-state.json::assets.raw_master` を `output_name` で上書き（後段の `/wf-next` などが新出力を参照するため）

`yt-finalize-master`（`rain_layer:` namespace）と `yt-apply-rain-layers`（`post_processing.rain_layers:` namespace）は**独立した opt-in**。両方有効化すると master.mp3 への loudnorm 上書きと master-rain.wav の別ファイル出力が両方走るので、片方だけ使う運用を推奨する。

### Step 5.7: タイムスタンプ整合性

現行の Complete Collection タイムスタンプは `metadata_generator.generate_timestamps()` / `format_timestamps_text()` が生成する。`yt-generate-master` と同じ `masterup.audio.crossfade_duration` を参照するため、mp3 / m4a / wav の入力形式にかかわらず実音声と description のクロスフェード秒数は同じ設定値で揃う。

`yt-fix-timestamps` は 2026-03/04 の固定コレクション向け historical CLI として残す。テーマ単位のみの旧フォーマットと 3 秒固定クロスフェードを再現するためのもので、`/masterup` の通常フローでは実行しない。新規コレクションの timestamp 不整合は `20-documentation/descriptions.md` を再生成して解消する。

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

## オーディオビジュアライザー / オーバーレイ

`/masterup` は**音源（mp3 / m4a / wav）を作る工程**で、映像オーバーレイ（ビジュアライザー・波形・購読ボタンポップアップ等）は扱わない。
ユーザーから「ビジュアライザー付きで」「波形を出して」等の指示があっても、`/masterup` 段階では何も合成できない。

ビジュアライザー周りの現状と制約は `videoup` SKILL.md の「オーディオビジュアライザー / オーバーレイについて」節を参照（#511 で feature 化中・現状未実装）。
誤指示の事故防止のため、masterup 着手前に動画にオーバーレイが必要かをユーザーへ確認すること（#646 feedback）。

## Next Step

→ `/videoup` で動画生成を実行
