---
name: lyria
description: Use when Vertex AI Lyria 3 でマスター音源を自動生成したいとき。skill-config と Lyria 3 `interactions` REST API を組み合わせ、1 リクエスト = 最大 ~184 秒の WAV セグメントを 1 つ以上出力する（人手介入なし、/masterup 不要、次工程は /videoup）。Suno で人手生成するチャンネルでは /suno を使う
---

## Overview

Vertex AI Lyria 3 REST API (`interactions` エンドポイント) を使い、`config/skills/lyria.yaml` のスタイル定義とユーザー指定テーマからプロンプトを組み立て、Lyria 3 API を呼んでマスター音源（WAV セグメント）を生成する。

Lyria 3 Pro は **1 リクエストあたり最大約 184 秒（~3 分）** までのオーディオを返す。本スキルはこの API リクエストを 1 つ以上発行してセグメントを取得するところまでを担当する。複数セグメントをクロスフェード結合してコレクション尺（30 分〜数時間）に整える自動パイプラインは現状未実装で、結合手順そのものは別 issue 待ち（複数セグメントを得て手作業で結合する運用は可能）。

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
- Lyria 3 API（最大 ~184 秒/リクエスト）でセグメントを 1 つ以上取得したいとき

### 選択タイミング（どこで lyria が選ばれるか）

1. **チャンネルのデフォルト** — `/channel-direction` で suno/lyria を検討 → `/channel-setup` が `config/channel/youtube.json` の `music_engine` に書き込む
2. **コレクション単位の上書き** — `/wf-new` の `yt-init-collection --music-engine lyria` でコレクション毎に上書き可能（省略時はチャンネル設定を継承）
3. **このスキルが呼ばれるとき** — `/wf-new` が `workflow-state.json` の `music_engine = "lyria"` を判定して `/lyria` を自動実行する。手動で `/lyria <theme>` を叩いた場合もこのスキルに入る

## Quick Reference

| コマンド | 説明 | 例 |
|---------|------|-----|
| `/lyria <theme>` | プロンプト設計 + Lyria 3 API 呼び出し（1 つ以上のセグメント生成） | `/lyria rain-against-glass` |

### 引数の解釈

```
$ARGUMENTS
```

$ARGUMENTS → コレクションのテーマ指定

## Channel Adaptation

実行前に `config/skills/lyria.yaml` から base 設定を読み取り、テーマに最適化されたプロンプトを設計する。

| skill-config キー | 用途 |
|------------|------|
| `_disabled` | true なら /suno を案内して終了 |
| `model` | 本生成モデル (`lyria-3-pro-preview`)。プレビュー時は `lyria-3-clip-preview` が自動選択される |
| `prompt_prefix` | プロンプト先頭の共通ジャンル句 |
| `style_hints` | 補足スタイル句（optional） |
| `ng_words` | プロンプトに使用禁止の語（Claude がプロンプト設計時にチェック） |
| `default_bpm` | チャンネル共通 BPM（generate_music() の `bpm` 引数に流用、個別上書き可） |
| `default_intensity` | チャンネル共通 intensity（generate_music() の `intensity` に流用、個別上書き可） |
| `default_mode` | チャンネル共通 mode（generate_music() の `mode` に流用、個別上書き可） |
| `default_reference_image` | チャンネル共通参照画像パス（generate_music() の `reference_image` に流用、個別上書き可） |

読み込み確認:

```bash
uv run python -c "from youtube_automation.utils.skill_config import load_skill_config; import json; print(json.dumps(load_skill_config('lyria'), indent=2, ensure_ascii=False))"
```

`config/channel/audio.json` からは `audio.target_duration_min`（コレクション全体の基準長）のみ参照する。1 リクエストあたり ~184 秒の制約があるため、`target_duration_min × 60 > 184` の場合は API を複数回呼んでセグメントを揃える必要がある（後述の制約参照）。

## Advanced Parameters（Lyria 3 API 入力）

`lyria_client.generate_music()` は以下の構造化パラメータを受け取れる（1 リクエスト 1 セグメント返り）。

| キー | 型 | 説明 |
|------|-----|------|
| `prompt` | string | プロンプト本文。skill-config の `prompt_prefix` ＋ `style_hints` ＋ テーマに合わせた主役楽器・演奏指示で組み立てる |
| `model` | string | `lyria-3-pro-preview`（本生成）/ `lyria-3-clip-preview`（30 秒固定、通常は使わない） |
| `reference_image` | Path | 参照画像パス。サムネイル `10-assets/main.png` を指せば音源の雰囲気が画像に寄る。対応形式: `.png`/`.jpg`/`.jpeg`/`.webp` |
| `bpm` | int | BPM。プロンプトに `", {bpm} BPM"` として自動合成される。目安 60-180 |
| `intensity` | `"low"` / `"medium"` / `"high"` | それぞれ `"mellow, low-energy"` / `"balanced, moderate energy"` / `"driving, high-energy"` に展開される |
| `mode` | `"instrumental"` / `"vocal"` | `instrumental` は末尾に `". Instrumental."` を付加、`vocal` は lyrics 未指定時のみ `". With vocals."` を付加 |
| `lyrics` | string | 歌詞。末尾に `". Lyrics: ..."` として合成される。`[Verse]` `[Chorus]` の section tag 使用可 |

**API 仕様上の注意**: Lyria 3 `interactions` で真の構造化入力は `reference_image` のみ。`bpm`/`intensity`/`mode`/`lyrics` は独立フィールドではなく、プロンプトテキストへの自然言語埋め込みとして送信される。

**duration の制約**: Lyria 3 Pro は 1 リクエスト ~184 秒が上限。長さはプロンプトのヒント扱いでぴったり一致せず、レスポンスを取得してから尺をトリミングする運用になる。複数セグメントを結合して長尺マスター音源を作る自動パスは現状未実装。

## Instructions

あなたは Lyria 3 音源生成のオーケストレーターです。
`config/skills/lyria.yaml` の値からプロンプトと API 入力パラメータを組み立て、`lyria_client.generate_music()` を 1 回以上呼んで音源セグメントを取得します。

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

## Step 2: プロンプト設計

### 設計原則

1. **prompt_prefix は最小限に**: `config/skills/lyria.yaml` の `prompt_prefix` をそのまま使用。楽器名・ムード語を追加しない
2. **プロンプトは「動作指示」で書く**: 状態描写ではなく、メロディの動き（wandering freely, phrases rising and falling）を指示する
3. **簡潔な修飾**: 形容詞は 1-2 個で十分
4. **禁止形容詞チェック**: `config/skills/lyria.yaml` の `ng_words` と `/suno` 側 `references/suno-examples.md` の禁止形容詞リストに準拠

詳しい推奨値・NG パターンは `references/lyria-tuning-guide.md` を参照。

### プロンプト組み立て

最終的に `generate_music(prompt=..., ...)` に渡す文字列は以下のような構造で組み立てる:

```
{prompt_prefix}, {style_hints}, {主役楽器の演奏指示}, {テーマに沿った最小限の情景描写}
```

例（テーマ: `rain-against-glass`、skill-config の `prompt_prefix = "celtic folk only, clean dry recording, no pads"`）:

```
celtic folk only, clean dry recording, no pads, gentle melodic phrases rising and falling, solo fingerpicked acoustic guitar
```

### API 入力パラメータの確定

`skill-config` のチャンネル共通値（`default_bpm` / `default_intensity` / `default_mode` / `default_reference_image`）を初期値とし、テーマに応じて個別調整してから `generate_music()` の引数に渡す。

- `reference_image`: コレクションの `10-assets/main.png`（存在すれば）
- `bpm`: テーマに沿った値（`default_bpm` を出発点）
- `intensity`: テーマに沿った値（`default_intensity` を出発点）
- `mode`: 通常 `instrumental`

## Step 3: 設定の書き出しとユーザー確認

1. 設計したプロンプトと API 入力パラメータを `20-documentation/lyria-prompt.md` に書き出す:
   - ヘッダー（Engine, Channel, Model）
   - 最終プロンプト本文
   - API 入力パラメータ（`reference_image` / `bpm` / `intensity` / `mode`）
   - 設計上の意図（主役楽器、雰囲気、テーマとの関係）
   - 品質チェックリスト

2. ユーザーにプロンプト・パラメータの確認を求める
3. 修正があれば `lyria-prompt.md` を編集して再確認

## Step 4: 音楽生成

ユーザー承認後、Lyria 3 API を呼び出してセグメントを取得する。コレクション尺に応じて 1 回〜複数回呼び出す:

```python
from pathlib import Path
from youtube_automation.utils.lyria_client import generate_music

audio_bytes = generate_music(
    prompt="<Step 2 で設計したプロンプト>",
    model="lyria-3-pro-preview",
    reference_image=Path("10-assets/main.png"),
    bpm=72,
    intensity="low",
    mode="instrumental",
)
if audio_bytes is None:
    raise RuntimeError("Lyria 生成に失敗しました")
Path("01-master/seg_001.wav").write_bytes(audio_bytes)
```

複数セグメントが必要な場合は、フェーズや展開ごとにプロンプトを変えながら `generate_music()` を繰り返し呼び、`02-Individual-music/<NN>_<name>.wav` のように番号付きで保存する。

> **`.env` は自動ロード**: `lyria_client` 内で `dotenv` により自動読み込みされる。

**注意点**:
- 1 リクエストあたり ~184 秒が上限。`audio.target_duration_min × 60` がこれを超える場合は複数回 API を呼んでセグメントを揃える。**得られたセグメントをクロスフェード結合してマスター音源化する自動パスは本スキルに存在しない**（旧 `yt-generate-music-dj` 廃止に伴い、結合パイプラインは別 issue 待ち）
- Vertex AI の Lyria クォータ（プロジェクト単位）は有限。他チャンネルと同時に大量生成すると 429 エラーが発生する
- 失敗時は `generate_music()` が `None` を返すため、リトライは呼び出し側で行う

## Step 4.1: ワークツリーからメインへのコピー

生成完了後、コレクションディレクトリから `worktree_sync.sh` を実行する。
ワークツリー検出・パス算出・コピーをすべて自動で行う（メインリポジトリで実行時は自動スキップ）。

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/lyria/references/worktree_sync.sh"
```

**コピー対象**:
- `01-master/master.wav` → メインの `01-master/`
- `10-assets/main.png` → メインの `10-assets/`

事前確認には `--dry-run` を付ける。

## Step 5: 完了時の更新

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
| `mood` | `intensity` + `style_hints` + プロンプトから蒸留 | 感情語 1-3 個（例: `["meditative", "warm"]`）|
| `atmosphere` | プロンプトの世界観 1 文（`prompt_prefix` の意図 + 主役楽器の集約） | 個別 prompt をそのまま貼らず、コレクション全体を 1 文で言い切る |
| `tempo` | `bpm` から自然言語化 | `<60` → `very slow` / `60-79` → `slow` / `80-99` → `gentle` / `100-119` → `moderate` / `≥120` → `lively`。bpm 未指定なら `intensity` から（`low` → `slow` / `medium` → `moderate` / `high` → `lively`）|
| `instruments` | プロンプトの楽器名を集約（重複排除） | "solo fingerpicked guitar" → `fingerpicked guitar` のように楽器名のみ抽出。主役 3-5 個に絞る |
| `exclude` (optional) | `config/skills/lyria.yaml` の `ng_words` から**楽器系のみ** | `orchestral` / `synthesizer` / `ambient pads` 等。環境音系は対象外 |

**冪等性**: 既存値があっても `planning.music` 全体を上書きする（merge しない）。スキル再実行 = プロンプト設計やり直しと見なす。

---

## 品質チェック

プロンプトと API 入力パラメータの品質チェック:

- [ ] `prompt_prefix` が `config/skills/lyria.yaml` の `prompt_prefix` に基づいていること
- [ ] プロンプトに主役楽器の演奏指示が含まれていること
- [ ] `ng_words` に含まれる語がプロンプトに使われていないこと
- [ ] 環境音系の語（`rain beginning to tap` 等）が使用されていないこと
- [ ] `reference_image` を使う場合、コレクションの `10-assets/main.png` を指していること
- [ ] `bpm` を指定する場合は 60-180 の整数で、チャンネル audio config と整合していること
- [ ] `intensity` は `"low"` / `"medium"` / `"high"` のいずれかであること
- [ ] `mode` は `"instrumental"` / `"vocal"` のいずれかであること

## Next Step

→ `/videoup` で動画生成を実行（WAV → MP4 変換は既存の generate_videos.sh を使用）
