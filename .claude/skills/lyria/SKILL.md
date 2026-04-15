---
name: lyria
description: Use when コレクションのテーマが確定し、Lyria RealTime API で音楽を生成したいとき。DJ型のフェーズ展開でマスター音源を自動生成。音楽制作、Lyria、DJ生成、マスター音源、フェーズ展開など、Lyria による音楽生成に関わる場面で必ず使用すること
---

## Overview

Lyria RealTime API を使い、`composition.json` に定義されたフェーズタイムラインに沿って Complete Collection 用マスター音源（WAV）を生成する。API のセッション制限（約 10 分）を回避するため、phase 境界でセグメント分割し、各セグメントを個別セッションで生成 → クロスフェード結合する。

## 前提

以下が揃っていること:

1. `config/channel_config.json` が存在する（`audio.target_duration_min` を参照）
2. `config/skills/lyria.yaml` が存在する（配布された `config.default.yaml` をベースにカスタマイズ）
3. `config/skills/lyria.yaml` の `_disabled` が **false** であること

いずれか不足する場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル** → `/channel-import` を案内
- **`_disabled: true` のチャンネル** → `/suno` を案内して終了する（Lyria を使わない方針）

## When to Use

- 新コレクションのテーマが確定し、音楽を生成するとき
- `/suno` + `/masterup` の代替として、API 完全自動の音楽生成を行いたいとき
- フェーズ展開（DJ 型）のマスター音源を直接生成したいとき

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
| `prompt_prefix` | `base.prompt_prefix`（共通ジャンル句） |
| `bpm` | ベース BPM |
| `brightness` | ベース brightness |
| `guidance` | プロンプト忠実度 |
| `temperature` | ランダム性 |
| `scale` | 音階 |
| `mute_drums` | ドラムミュート |
| `transition_sec` | トランジション秒数 |
| `ng_words` | プロンプトに使用禁止の語 |
| `duration_padding_min` | `total_duration_min = audio.target_duration_min + duration_padding_min` の余剰分（推奨 3）|

読み込み確認:

```bash
uv run python -c "from youtube_automation.utils.skill_config import load_skill_config; import json; print(json.dumps(load_skill_config('lyria'), indent=2, ensure_ascii=False))"
```

`channel_config.json` からは `audio.target_duration_min`（コレクション全体の基準長）のみ参照する。

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
| **各フェーズの最大長** | **10 分以内**（API セッション制限）|
| transition_sec | `config/skills/lyria.yaml` の `transition_sec`（推奨 30）|
| total_duration_min | `audio.target_duration_min` + `lyria.duration_padding_min` |

**セグメント分割の制約**: セグメント分割生成（デフォルト有効）では、各 phase が 1 つのセグメントになる。API のセッション制限が約 10 分のため、**各 phase の長さは必ず 10 分以内** にすること。10 分を超える phase がある場合はサブフェーズに分割する（例: 「シーの子守唄」→「シーの子守唄 — 歌声」+「シーの子守唄 — 残響」）。

フェーズの設計手順:
1. コレクションのテーマ・雰囲気を分析
2. **感情・エネルギーの流れ（起伏）** を設計する（4-6 の大きなアーク）
3. 各アークを 10 分以内のサブフェーズに分割（「— サブテーマ」形式で命名）
4. **楽器切り替え式で主役楽器を割り当てる**: フェーズごとに主役楽器を変える
5. 各フェーズに **主役楽器 + メロディの動作指示** を prompt として記述（動作指示の詳細は references/lyria-tuning-guide.md 参照）
6. `brightness`, `density`, `bpm` をフェーズごとにオーバーライド（起伏を表現）
7. `ng_words` に含まれる語がプロンプトに使われていないか確認

**duration の +α ルール**: Lyria のリアルタイム生成はタイミングが正確に終わらないため、`total_duration_min` は `audio.target_duration_min` より **+duration_padding_min** 分（デフォルト 3）に設定する。余剰分は後工程でトリミングできるが、不足分は再生成が必要になるため、常に余裕を持たせる。

### composition.json 形式

```json
{
  "title": "<コレクション名>",
  "total_duration_min": "<audio.target_duration_min + lyria.duration_padding_min>",
  "base": {
    "prompt_prefix": "<config/skills/lyria.yaml の prompt_prefix>",
    "bpm": 110,
    "brightness": 0.4,
    "guidance": 3.0,
    "temperature": 0.9,
    "scale": "C_MAJOR_A_MINOR",
    "mute_drums": true,
    "mode": "QUALITY"
  },
  "phases": [
    {
      "at_min": 0,
      "name": "<フェーズ名（日本語）>",
      "name_en": "<Phase Name in English>",
      "prompt": "<主役楽器の演奏指示 + 最小限の情景（英語）>",
      "brightness": 0.3,
      "density": 0.2
    }
  ],
  "transition_sec": 30
}
```

**フィールド説明:**

| フィールド | 必須 | 説明 |
|-----------|------|------|
| `title` | Yes | コレクション名 |
| `total_duration_min` | Yes | 総再生時間（分） |
| `base.prompt_prefix` | Yes | 全フェーズ共通のジャンル句（skill-config から）|
| `base.bpm` | Yes | ベース BPM（60-200）|
| `base.brightness` | Yes | ベース明るさ（0.0-1.0）|
| `base.guidance` | Yes | プロンプト忠実度（0.0-6.0）|
| `base.temperature` | Yes | ランダム性 |
| `base.scale` | No | 音階（enum 値: `C_MAJOR_A_MINOR` 等）|
| `base.mute_drums` | No | ドラムミュート |
| `base.mode` | No | QUALITY / DIVERSITY |
| `phases[].at_min` | Yes | フェーズ開始時刻（分） |
| `phases[].name` | Yes | フェーズ名（日本語、進捗表示用） |
| `phases[].name_en` | Yes | フェーズ名（英語、ファイル名に使用） |
| `phases[].prompt` | Yes | 主役楽器の演奏指示 + 最小限の情景（英語） |
| `phases[].brightness` | No | brightness オーバーライド |
| `phases[].density` | No | density オーバーライド（0.0-1.0）|
| `phases[].bpm` | No | BPM オーバーライド |
| `phases[].scale` | No | scale オーバーライド（転調用）|
| `phases[].mute_drums` | No | フェーズ単位のドラムミュート |
| `phases[].mute_bass` | No | フェーズ単位のベースミュート |
| `transition_sec` | No | トランジション秒数（default: 30）|

**LiveMusicGenerationConfig 全パラメータ**: bpm, brightness, density, guidance, temperature, scale, top_k, seed, mute_bass, mute_drums, only_bass_and_drums, music_generation_mode

- `scale` は enum 値のみ: `C_MAJOR_A_MINOR`, `D_MAJOR_B_MINOR`, `G_MAJOR_E_MINOR` 等（Dorian/Mixolydian 等のモード指定不可）
- `negative_prompt` は Live API に存在しない（プロンプト本文で `no X` 形式で指示）

## Step 3: 設定の書き出しとユーザー確認

1. composition.json を `20-documentation/composition.json` に保存
2. `20-documentation/lyria-composition.md` に設定を書き出す:
   - ヘッダー（Engine, Channel, Duration）
   - 感情アーク（フェーズの流れを可視化）
   - Timeline Summary（dry-run 出力形式のサマリー）
   - Base Settings テーブル
   - 各フェーズの詳細（日本語解説 + prompt + パラメータ）
   - 品質チェックリスト

**Timeline Summary の形式**（dry-run 出力を転記）:

```
=== <title> (<total_duration_min>min) ===
  Base: bpm=<bpm>  brightness=<brightness>  mode=<mode>
  Transition: <transition_sec>s crossfade

  <HH:MM>  <phase_name>    brightness=<x>   bpm=<x>
  ...
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

- 始め・中盤・終盤の 3 フェーズから各 30 秒サンプルを並列生成（約 30 秒で完了）
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

**セグメント分割生成**（デフォルト有効）:
- 各 phase を独立した API セッションで生成（API の 10 分制限を回避）
- `--workers N` で並列生成数を指定（推奨: `--workers 10`、全セグメント並列）
- 生成中に `seg_001.wav`, `seg_002.wav`, ... が作成される
- 全セグメント完了後にクロスフェード結合して master.wav を出力
- 途中失敗時は自動リトライ（`--max-retries` 回）
- 再実行時は成功済みセグメントをスキップして続行
- `--no-segmented` で従来の 1 セッション生成に戻す

**生成時間の目安**:
- `--workers 10`（並列）: 123 分のコレクション ≈ **約 10 分**（最長セグメントのリアルタイム長に依存）
- `--workers 0`（逐次）: 123 分のコレクション ≈ 123 分

**注意**: 並列生成時、他チャンネルで同時に Lyria セッションを実行すると quota エラーが発生する場合がある。並列生成中は他の Lyria 生成を停止すること。

**セグメントファイルの扱い**:
- デフォルトでセグメントファイル（`seg_*.wav`）は **保持** される（個別楽曲として利用可能）
- `--cleanup` を指定すると生成後に削除

## Step 5.1: ワークツリーからメインへのコピー

生成完了後、コレクションディレクトリから `worktree_sync.sh` を実行する。
ワークツリー検出・パス算出・コピーをすべて自動で行う（メインリポジトリで実行時は自動スキップ）。

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/lyria/references/worktree_sync.sh"
```

**コピー対象**:
- `01-master/master.wav` → メインの `01-master/`
- `01-master/seg_*.wav` → メインの `02-Individual-music/`
- `10-assets/main.png` → メインの `10-assets/`

事前確認には `--dry-run` を付ける。

## Step 6: 完了時の更新

- `workflow-state.json` の `music.generated = true`, `music.approved = true` に更新
- `music.master_audio` にマスター音源ファイル名を記録
- `music.engine` に `"lyria"` を記録
- `phase` を `"music-approved"` に更新

---

## 品質チェック

composition.json の品質チェック:

- [ ] `prompt_prefix` が `config/skills/lyria.yaml` の `prompt_prefix` に基づいていること
- [ ] `guidance`, `temperature`, `mute_drums` が skill-config の値に準拠していること
- [ ] 各 phase の `prompt` に主役楽器の演奏指示が含まれていること（楽器切り替え式）
- [ ] `ng_words` に含まれる語が使用されていないこと
- [ ] 環境音系の語（`rain beginning to tap` 等）が使用されていないこと
- [ ] 最初の phase が `at_min: 0` であること
- [ ] **各 phase の長さが 10 分以内であること**（API セッション制限）
- [ ] フェーズ間に `transition_sec` 以上の間隔があること
- [ ] `total_duration_min` が最後のフェーズ以降に十分な再生時間を確保していること
- [ ] `--preview` でプレビュー生成し、音楽の方向性を確認済み

## Next Step

→ `/videoup` で動画生成を実行（WAV → MP4 変換は既存の generate_videos.sh を使用）
