---
name: lyria
description: Use when Vertex AI Lyria 3 でマスター音源を自動生成したいとき。composition.json を設計し DJ フェーズ展開で WAV を直接出力する（人手介入なし、/masterup 不要、次工程は /videoup）。API 自動音源生成・DJ フェーズ展開・composition.json 設計の場面で使用すること。Suno で人手生成するチャンネルでは /suno を使う
---

## Overview

Vertex AI Lyria 3 REST API (`interactions` エンドポイント) を使い、`composition.json` に定義されたフェーズタイムラインに沿って Complete Collection 用マスター音源（WAV）を生成する。

Lyria 3 Pro は **1 リクエストあたり最大約 184 秒（~3 分）** まで生成できる。長尺コレクション（30 分〜数時間）は phase 境界＋サブ分割で複数セグメントに割り、それぞれを個別 API コールで生成してクロスフェード結合する。

## 前提

以下が揃っていること:

1. `config/channel/` が存在する（`config/channel/audio.json` の `audio.target_duration_min` を参照）
2. skill-config の `_disabled` が **false** であること（`config/skills/lyria.yaml` で上書きしない限り、配布された `config.default.yaml` の default `false` が使われる）
3. `.env` に `GOOGLE_CLOUD_PROJECT` が設定されており `gcloud auth application-default login` 済み（Vertex AI interactions エンドポイントは ADC で呼ぶ）

`config/skills/lyria.yaml` はオプション。`yt-skills sync` で配布される `config.default.yaml` がそのまま使われるため、default 動作で問題なければ作成不要。カスタマイズしたい場合のみ `config.default.yaml` をコピーして `config/skills/lyria.yaml` に置き、必要な値だけ上書きする（deep-merge される）。

不足する場合、ユーザーに確認:
- **`config/channel/` が無い新規チャンネル** → `/channel-new` を案内
- **`config/channel/` が無い既存チャンネル** → `/channel-import` を案内
- **`_disabled: true` のチャンネル** → `/suno` を案内して終了する（Lyria を使わない方針）

## When to Use

- 新コレクションのテーマが確定し、音楽を生成するとき
- `/suno` + `/masterup` の代替として、API 完全自動の音楽生成を行いたいとき
- フェーズ展開（DJ 型）のマスター音源を直接生成したいとき

### 選択タイミング（どこで lyria が選ばれるか）

1. **チャンネルのデフォルト** — `/channel-direction` で suno/lyria を検討 → `/channel-setup` が `config/channel/youtube.json` の `music_engine` に書き込む
2. **コレクション単位の上書き** — `/wf-new` の `yt-init-collection --music-engine lyria` でコレクション毎に上書き可能（省略時はチャンネル設定を継承）
3. **このスキルが呼ばれるとき** — `/wf-new` が `workflow-state.json` の `music_engine = "lyria"` を判定して `/lyria` を自動実行する。手動で `/lyria <theme>` を叩いた場合もこのスキルに入る

## Quick Reference

| コマンド | 説明 | 例 |
|---------|------|-----|
| `/lyria <theme>` | composition 生成 + DJ 生成実行 | `/lyria rain-against-glass` |

### 引数の解釈

```
$ARGUMENTS
```

$ARGUMENTS → コレクションのテーマ指定

## Channel Adaptation

実行前に `config/skills/lyria.yaml` から base 設定を読み取り、テーマに最適化された composition.json を設計する。

| skill-config キー | 用途 |
|------------|------|
| `_disabled` | true なら /suno を案内して終了 |
| `model` | 本生成モデル (`lyria-3-pro-preview`)。プレビュー時は `lyria-3-clip-preview` が自動選択される |
| `prompt_prefix` | `base.prompt_prefix`（共通ジャンル句） |
| `style_hints` | `base.style_hints`（補足スタイル句、optional） |
| `crossfade_sec` | マスタリング時のセグメント結合クロスフェード秒数 |
| `ng_words` | プロンプトに使用禁止の語（Claude が composition.json 設計時にチェック） |
| `duration_padding_min` | `total_duration_min = audio.target_duration_min + duration_padding_min` の余剰分（推奨 3）|

読み込み確認:

```bash
uv run python -c "from youtube_automation.utils.skill_config import load_skill_config; import json; print(json.dumps(load_skill_config('lyria'), indent=2, ensure_ascii=False))"
```

`config/channel/audio.json` からは `audio.target_duration_min`（コレクション全体の基準長）のみ参照する。

## Advanced Parameters（Lyria 3 追加入力）

`lyria_client.generate_music()` は以下の構造化パラメータを受け取れる。composition.json の `base.*` と `phases[].*` の両方で指定可能で、**phase > base > 未指定** の優先順位でマージされる。

| キー | 型 | 説明 |
|------|-----|------|
| `reference_image` | string (path) | 参照画像パス。composition.json のある**ディレクトリからの相対**、または絶対パス。サムネイル `10-assets/main.png` を指せば音源の雰囲気が画像に寄る。対応形式: `.png`/`.jpg`/`.jpeg`/`.webp` |
| `bpm` | integer | BPM。プロンプトに `", {bpm} BPM"` として自動合成される。目安 60-180 |
| `intensity` | string enum | `"low"` / `"medium"` / `"high"`。それぞれ `"mellow, low-energy"` / `"balanced, moderate energy"` / `"driving, high-energy"` に展開される |
| `mode` | string enum | `"instrumental"` / `"vocal"`。`instrumental` は末尾に `". Instrumental."` を付加、`vocal` は lyrics 未指定時のみ `". With vocals."` を付加 |
| `lyrics` | string | 歌詞。末尾に `". Lyrics: ..."` として合成される。`[Verse]` `[Chorus]` の section tag 使用可。phase 固有（通常は `phases[].lyrics` で指定） |

**API 仕様上の注意**: Lyria 3 `interactions` で真の構造化入力は `reference_image` のみ。`bpm`/`intensity`/`mode`/`lyrics` は独立フィールドではなく、プロンプトテキストへの自然言語埋め込みとして送信される。

## Instructions

あなたは Lyria DJ Engine のオーケストレーターです。
`config/skills/lyria.yaml` の値を `composition.json` の `base` にそのままマッピングし、DJ エンジンで音楽を生成します。

`_disabled: true` の場合、以下を出力して終了:
> Lyria はこのチャンネルで無効化されています (`config/skills/lyria.yaml` の `_disabled: true`)。音楽生成は `/suno <theme>` を使用してください。

### 対象テーマ

```
$ARGUMENTS
```

---

## Step 1: コレクションの特定

1. `collections/planning/` の `workflow-state.json` を検索
2. 該当テーマのコレクション、または `thumbnail-approved` フェーズのコレクションを対象
3. 複数ある場合はユーザーに選択を促す

## Step 2: composition.json の設計

### 設計原則

1. **楽器切り替え式**: 全楽器を同時に鳴らさず、フェーズごとに主役楽器を変える
2. **prompt_prefix は最小限に**: `config/skills/lyria.yaml` の `prompt_prefix` をそのまま使用。楽器名・ムード語を追加しない
3. **プロンプトは「動作指示」で書く**: 状態描写ではなく、メロディの動き（wandering freely, phrases rising and falling）を指示する
4. **簡潔な修飾**: 形容詞は 1-2 個で十分
5. **禁止形容詞チェック**: `config/skills/lyria.yaml` の `ng_words` と `/suno` 側 references/suno-examples.md の禁止形容詞リストに準拠

詳しい推奨値・NG パターンは `references/lyria-tuning-guide.md` を参照。

### フェーズ設計

| 項目 | 推奨値 |
|------|--------|
| フェーズ数 | `target_duration_min` に応じて調整（120 分なら **30 前後、各 3.5-4.5 分**推奨）|
| **各フェーズの上限** | **実質なし**（実装が自動で 2 分サブセグメントに分割する）|
| total_duration_min | `audio.target_duration_min` + `lyria.duration_padding_min` |

**セグメント分割の仕組み**:
- `generate_music_dj.py` は各 phase を `duration_hint_sec`（デフォルト **180 秒**）単位でサブ分割し、1 サブセグメント＝1 API コール（`lyria-3-pro-preview` の ~184 秒上限内）として生成する
- Pro モデルの上限は約 184 秒/リクエストなので、**`duration_hint_sec` を 180 以内** に収めること（既定値 180 がほぼ上限フィット、長尺コンテンツでは API コール数が最小化される）
- サブセグメント間は `crossfade_sec`（デフォルト 5 秒）でクロスフェード結合される
- `phase.duration_hint_sec` を個別指定すれば phase ごとにサブ分割単位を変えられる

**duration の +α ルール**: Lyria の生成長はプロンプト経由のヒント扱いでぴったり一致しない。`total_duration_min` は `audio.target_duration_min` より **+duration_padding_min** 分（デフォルト 3）に設定する。余剰分は後工程でトリミングできるが、不足分は再生成が必要になるため、常に余裕を持たせる。

### composition.json 形式

```json
{
  "title": "<コレクション名>",
  "total_duration_min": "<audio.target_duration_min + lyria.duration_padding_min>",
  "model": "lyria-3-pro-preview",
  "base": {
    "prompt_prefix": "<config/skills/lyria.yaml の prompt_prefix>",
    "style_hints": "<optional: ジャンル/雰囲気の補足句>"
  },
  "phases": [
    {
      "at_min": 0,
      "name": "<フェーズ名（日本語）>",
      "name_en": "<Phase Name in English>",
      "prompt": "<主役楽器の演奏指示 + 最小限の情景（英語）>"
    }
  ],
  "crossfade_sec": 5
}
```

**フィールド説明:**

| フィールド | 必須 | 説明 |
|-----------|------|------|
| `title` | Yes | コレクション名 |
| `total_duration_min` | Yes | 総再生時間（分） — shuffle モード以外で必要 |
| `model` | No | `lyria-3-pro-preview`（default）/ `lyria-3-clip-preview`（30 秒固定、通常は使わない）|
| `base.prompt_prefix` | Yes | 全フェーズ共通のジャンル句（skill-config から）|
| `base.style_hints` | No | スタイル補足句（全フェーズ共通）|
| `phases[].at_min` | Yes | フェーズ開始時刻（分） |
| `phases[].name` | Yes | フェーズ名（日本語、進捗表示用） |
| `phases[].name_en` | Yes | フェーズ名（英語、ファイル名に使用） |
| `phases[].prompt` | Yes | 主役楽器の演奏指示 + 最小限の情景（英語） |
| `phases[].duration_hint_sec` | No | サブ分割の秒数（default 180。Pro モデル上限 184 を超えないこと） |
| `phases[].section_tag` | No | プロンプト末尾に追加される補足タグ（例: `"intro"`）|
| `crossfade_sec` | No | サブセグメント間クロスフェード秒数（default: 5）|
| `shuffle_passes` | No | N>0 で shuffle モード（各 phase を 1 セグメントとして N 回シャッフル連結）|
| `segment_duration_sec` | No | shuffle モード時のセグメント長（default 180）|
| `shuffle_seed` | No | shuffle 再現用 seed |
| `base.reference_image` / `phases[].reference_image` | No | 参照画像パス（相対は composition.json からの相対） |
| `base.bpm` / `phases[].bpm` | No | BPM（整数、目安 60-180） |
| `base.intensity` / `phases[].intensity` | No | `"low"` / `"medium"` / `"high"` |
| `base.mode` / `phases[].mode` | No | `"instrumental"` / `"vocal"` |
| `phases[].lyrics` | No | 歌詞文字列（section tag 可） |

## Step 3: 設定の書き出しとユーザー確認

1. composition.json を `20-documentation/composition.json` に保存
2. `20-documentation/lyria-composition.md` に設定を書き出す:
   - ヘッダー（Engine, Channel, Duration）
   - 感情アーク（フェーズの流れを可視化）
   - Timeline Summary（dry-run 出力形式のサマリー）
   - 各フェーズの詳細（日本語解説 + prompt）
   - 品質チェックリスト

**Timeline Summary の形式**（dry-run 出力を転記）:

```
=== <title> (<total_duration_min>min) ===
  Model: lyria-3-pro-preview
  Base: <prompt_prefix の冒頭 60 文字>...
  Crossfade: <crossfade_sec>s

  seg_001  <phase_name_en>
  seg_002  <phase_name_en (2/N)>
  ...
  Total segments: <N>
  <HH:MM>  END
```

3. dry-run でタイムラインを表示:

```bash
uv run yt-generate-music-dj -c 20-documentation/composition.json --dry-run
```

4. ユーザーにフェーズ構成・タイミングの確認を求める
5. 修正があれば composition.json と lyria-composition.md を両方編集して再度 dry-run

## Step 4: プレビュー生成

本生成の前に、3 つの代表フェーズから 30 秒のプレビューサンプルを生成して方向性を確認する:

```bash
uv run yt-generate-music-dj \
  -c 20-documentation/composition.json \
  -o 01-master/master.wav \
  --preview
```

- 始め・中盤・終盤の 3 フェーズから各 30 秒サンプルを `lyria-3-clip-preview` で並列生成（約 30 秒で完了）
- `01-master/preview/` に `preview_01_*.wav`, `preview_02_*.wav`, `preview_03_*.wav` が出力
- ユーザーにプレビューの試聴を促し、方向性に問題がないか確認
- 修正が必要な場合は composition.json を編集して再度 `--preview` を実行
- 問題なければ Step 5 の本生成に進む

**注意**: プレビューファイルは本生成後も保持される（手動で削除可能）。

## Step 5: 音楽生成

ユーザー承認後、DJ エンジンを実行:

```bash
uv run yt-generate-music-dj \
  -c 20-documentation/composition.json \
  -o 01-master/master.wav \
  -y --max-retries 3 --workers 10
```

> **`.env` は自動ロード**: スクリプト内で `dotenv` により自動読み込みされる。

**セグメント分割生成**:
- 各 phase を `duration_hint_sec`（default 180s）単位のサブセグメントに分割し、1 サブセグメント＝1 API コール（`lyria-3-pro-preview` の ~184 秒上限内）で生成
- `--workers N` で並列生成数を指定（推奨: `--workers 10`、または `-1` で全セグメント同時）
- 生成中に `seg_001.wav`, `seg_002.wav`, ... が作成される
- 全セグメント完了後にクロスフェード結合して master.wav を出力
- 途中失敗時は自動リトライ（`--max-retries` 回）
- 再実行時は成功済みセグメントをスキップして続行

**生成時間の目安**:
- `--workers 10`（並列）: 123 分のコレクション ≈ **約 10 分**（API レイテンシ + ffmpeg 変換）
- `--workers 0`（逐次）: セグメント数 × 30-60 秒/segment

**注意**: Vertex AI の Lyria クォータ（プロジェクト単位）は有限なので、並列 workers を上げすぎると 429 エラーが発生する。他チャンネルと同時に大量生成しないこと。

**セグメントファイルの扱い**:
- デフォルトでセグメントファイル（`seg_*.wav`）は `02-Individual-music/<NN>_<phase_name>.wav` にリネーム移動される（個別楽曲として利用可能）
- `--cleanup` を指定すると生成後に削除

## Step 5.1: ワークツリーからメインへのコピー

生成完了後、コレクションディレクトリから `worktree_sync.sh` を実行する。
ワークツリー検出・パス算出・コピーをすべて自動で行う（メインリポジトリで実行時は自動スキップ）。

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/lyria/references/worktree_sync.sh"
```

**コピー対象**:
- `01-master/master.wav` → メインの `01-master/`
- `02-Individual-music/*.wav` → メインの `02-Individual-music/`
- `10-assets/main.png` → メインの `10-assets/`

事前確認には `--dry-run` を付ける。

## Step 6: 完了時の更新

- `workflow-state.json` の `planning.music` セクションを populate（下記参照）
- `workflow-state.json` の `music.generated = true`, `music.approved = true` に更新
- `music.master_audio` にマスター音源ファイル名を記録
- `music.engine` に `"lyria"` を記録
- `phase` を `"music-approved"` に更新

### planning.music スキーマ

`/alignment-check` がコレクション横断で音楽 mood × サムネ × タイトルの整合を機械的に判定できるよう、`workflow-state.json` の `planning.music` セクションを populate する。新規制作分は必須。

```json
{
  "planning": {
    "music": {
      "engine": "lyria",
      "mood": ["meditative", "warm"],
      "atmosphere": "slow fingerpicked guitar in a quiet hall",
      "tempo": "slow",
      "instruments": ["fingerpicked guitar", "soft piano"],
      "exclude": ["orchestral", "synthesizer"]
    }
  }
}
```

**書き方ガイド**:

| フィールド | ソース | 補足 |
|-----------|--------|------|
| `engine` | 固定値 `"lyria"` | — |
| `mood` | `composition.json` の `base.intensity` + `base.style_hints` + 全 phase prompt から蒸留 | 感情語 1-3 個（例: `["meditative", "warm"]`）|
| `atmosphere` | composition の世界観 1 文（`base.prompt_prefix` の意図 + 主要 phase の集約） | 個別 phase prompt をそのまま貼らず、コレクション全体を 1 文で言い切る |
| `tempo` | `base.bpm` から自然言語化 | `<60` → `very slow` / `60-79` → `slow` / `80-99` → `gentle` / `100-119` → `moderate` / `≥120` → `lively`。bpm 未指定なら `intensity` から（`low` → `slow` / `medium` → `moderate` / `high` → `lively`）|
| `instruments` | 全 phase `prompt` の楽器名を集約（重複排除） | "solo fingerpicked guitar" → `fingerpicked guitar` のように楽器名のみ抽出。主役 3-5 個に絞る |
| `exclude` (optional) | `config/skills/lyria.yaml` の `ng_words` から**楽器系のみ** | `orchestral` / `synthesizer` / `ambient pads` 等。環境音系は対象外 |

**冪等性**: 既存値があっても `planning.music` 全体を上書きする（merge しない）。スキル再実行 = composition 設計やり直しと見なす。

---

## 品質チェック

composition.json の品質チェック:

- [ ] `base.prompt_prefix` が `config/skills/lyria.yaml` の `prompt_prefix` に基づいていること
- [ ] 各 phase の `prompt` に主役楽器の演奏指示が含まれていること（楽器切り替え式）
- [ ] `ng_words` に含まれる語がプロンプトに使われていないこと
- [ ] 環境音系の語（`rain beginning to tap` 等）が使用されていないこと
- [ ] 最初の phase が `at_min: 0` であること
- [ ] `duration_hint_sec`（省略時 180）が 184 を超えていないこと（Pro モデル API 上限）
- [ ] `total_duration_min` が最後のフェーズ以降に十分な再生時間を確保していること
- [ ] `base.reference_image` を使う場合、コレクションの `10-assets/main.png` を `../10-assets/main.png` として指定していること
- [ ] `bpm` を指定する場合は 60-180 の整数で、チャンネル audio config と整合していること
- [ ] `intensity` は `"low"` / `"medium"` / `"high"` のいずれかであること
- [ ] `mode` は `"instrumental"` / `"vocal"` のいずれかであること
- [ ] `--preview` でプレビュー生成し、音楽の方向性を確認済み

## Next Step

→ `/videoup` で動画生成を実行（WAV → MP4 変換は既存の generate_videos.sh を使用）
