---
name: lyria
description: Use when コレクションのテーマが確定し、Lyria RealTime API で音楽を生成したいとき。DJ型のフェーズ展開でマスター音源を自動生成。音楽制作、Lyria、DJ生成、マスター音源、フェーズ展開など、Lyria による音楽生成に関わる場面で必ず使用すること
---

## Overview

Lyria RealTime API を使い、composition.json に定義されたフェーズタイムラインに沿って Complete Collection 用マスター音源（WAV）を生成します。API のセッション制限（約10分）を回避するため、phase 境界でセグメント分割し、各セグメントを個別セッションで生成→クロスフェード結合します。

## When to Use

- 新コレクションのテーマが確定し、音楽を生成するとき
- `/suno` + `/masterup` の代替として、API 完全自動の音楽生成を行いたいとき
- フェーズ展開（DJ型）のマスター音源を直接生成したいとき

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

実行前に `channel_config.json` の以下を読み取り、チャンネルに適応する:

| config キー | 用途 | 例 |
|------------|------|-----|
| `audio.target_duration_min` | `total_duration_min` の基準値 | `120` |
| `lyria.prompt_prefix` | `base.prompt_prefix`（**優先**） | `channel_config.json で設定` |
| `lyria.bpm` | ベース BPM | `110` |
| `lyria.brightness` | ベース brightness | `0.4` |
| `lyria.guidance` | プロンプト忠実度 | `3.0` |
| `lyria.temperature` | ランダム性 | `0.9` |
| `lyria.scale` | 音階 | `C_MAJOR_A_MINOR` |
| `lyria.mute_drums` | ドラムミュート | `true` |
| `lyria.transition_sec` | トランジション秒数 | `30` |
| `lyria.ng_words` | プロンプトに使用禁止の語 | `ambient pads, ethereal choir...` |
| `suno.genre_line` | `prompt_prefix` のフォールバック（`lyria` 未定義時） | — |

## Instructions

あなたは Lyria DJ Engine のオーケストレーターです。
`channel_config.json` の `lyria` セクションから base 設定を読み取り、テーマに最適化された composition.json を設計し、DJ エンジンで音楽を生成します。

**base 構築ルール**: `channel_config.json` の `lyria` セクションの値を `composition.json` の `base` にそのままマッピングする（`prompt_prefix`, `bpm`, `brightness`, `guidance`, `temperature`, `scale`, `mute_drums`）。`lyria` セクションがない場合は `suno.genre_line` を `prompt_prefix` のフォールバックとし、他のパラメータはスキルの推奨値を使う。

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

**リファレンス**: チャンネルのリファレンス楽曲を設定し、サウンドの基準とする

1. **楽器切り替え式**: 全楽器を同時に鳴らさず、フェーズごとに主役楽器を変える
2. **prompt_prefix は最小限に**: ジャンル + `acoustic instruments only` + `clean dry recording` + `no pads` 程度。楽器名・ムード語（intimate, gentle, bittersweet 等）は入れない — 全フェーズに付加されソロフェーズでもバック楽器が鳴る原因になる。ネガティブ指示も大量に入れると逆効果（概念を活性化する）
3. **プロンプトは「動作指示」で書く**: 状態描写（sparse, intimate, unhurried）ではなく、メロディの動き（wandering freely, phrases rising and falling, exploring different ideas）を指示する。状態描写だと Lyria が同じパターンをループする
4. **簡潔な修飾**: 形容詞は1-2個で十分
5. **禁止形容詞チェック**: `/suno` スキルの禁止形容詞リストに準拠

### フェーズ設計

| 項目 | 推奨値 |
|------|--------|
| フェーズ数 | `target_duration_min` に応じて調整（120分なら**30前後、各3.5-4.5分**推奨。16-24だとセグメントが長くノイズ蓄積+動きなし） |
| **各フェーズの最大長** | **10分以内**（API セッション制限） |
| transition_sec | 30（推奨） |
| total_duration_min | `channel_config.json` の `audio.target_duration_min` + 3分 |

**セグメント分割の制約**: セグメント分割生成（デフォルト有効）では、各 phase が1つのセグメントになる。API のセッション制限が約10分のため、**各 phase の長さは必ず10分以内** にすること。10分を超える phase がある場合はサブフェーズに分割する（例: 「シーの子守唄」→「シーの子守唄 — 歌声」+「シーの子守唄 — 残響」）。

フェーズの設計手順:
1. コレクションのテーマ・雰囲気を分析
2. **感情・エネルギーの流れ（起伏）** を設計する（4-6の大きなアーク）
3. 各アークを10分以内のサブフェーズに分割（「— サブテーマ」形式で命名）
4. **楽器切り替え式で主役楽器を割り当てる**: フェーズごとに主役楽器を変える
   - 例: Guitar solo → Whistle melody → Fiddle melody → Guitar+Whistle duo → Fiddle full → Guitar outro
   - 全楽器を同時に鳴らさない。1-2楽器が主役、他は伴奏
5. 各フェーズに **主役楽器 + メロディの動作指示** を prompt として記述
   - 良い例: `"solo fingerpicked acoustic guitar, melody wandering freely in A minor, phrases rising and falling with varied rhythm"`
   - 良い例: `"medieval fiddle melody climbing higher with each phrase, adding ornaments and turns, guitar shifting beneath"`
   - 悪い例: `"solo fingerpicked acoustic guitar, sparse and intimate, unhurried and reflective"` （状態描写 → ループの原因）
   - 悪い例: `"rain beginning to tap against old glass"` （環境音として解釈される）
   - 悪い例: `"Create a peaceful atmosphere"` （命令文）
6. `brightness`, `density`, `bpm` をフェーズごとにオーバーライド（起伏を表現）
7. `channel_config.json` の `lyria.ng_words` に含まれる語がプロンプトに使われていないか確認

**duration の +α ルール**: Lyria のリアルタイム生成はタイミングが正確に終わらないため、`total_duration_min` は `channel_config.json` の `audio.target_duration_min` より **+3分** に設定する（例: 120分目標 → 123）。余剰分は後工程でトリミングできるが、不足分は再生成が必要になるため、常に余裕を持たせる。

### composition.json 形式

```json
{
  "title": "Rain Against the Glass",
  "total_duration_min": "<channel_config.json の audio.target_duration_min + 3>",
  "base": {
    "prompt_prefix": "<channel_config.json の lyria.prompt_prefix、なければ suno.genre_line>",
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
      "name": "フェーズ名（日本語）",
      "name_en": "Phase Name in English",
      "prompt": "主役楽器の演奏指示 + 最小限の情景（英語）",
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
| `base.prompt_prefix` | Yes | 全フェーズ共通のジャンル句 |
| `base.bpm` | Yes | ベース BPM（60-200）。推奨:**110** |
| `base.brightness` | Yes | ベース明るさ（0.0-1.0）。推奨: **0.4** |
| `base.guidance` | Yes | プロンプト忠実度（0.0-6.0）。推奨: **3.0**（2.5だとpad音増加、3.5だと音数過多） |
| `base.temperature` | Yes | ランダム性（推奨: **0.9**。0.7だとメロディが単調ループ、0.6以下はノイズ増） |
| `base.scale` | No | 音階（enum値: `C_MAJOR_A_MINOR` 等）。モード指定不可 |
| `base.mute_drums` | No | ドラムミュート。推奨:**true** |
| `base.mode` | No | QUALITY / DIVERSITY。推奨: QUALITY |
| `phases[].at_min` | Yes | フェーズ開始時刻（分） |
| `phases[].name` | Yes | フェーズ名（日本語、進捗表示用） |
| `phases[].name_en` | Yes | フェーズ名（英語、ファイル名に使用） |
| `phases[].prompt` | Yes | 主役楽器の演奏指示 + 最小限の情景（英語） |
| `phases[].brightness` | No | brightness オーバーライド |
| `phases[].density` | No | density オーバーライド（0.0-1.0）。アレンジの疎密制御 |
| `phases[].bpm` | No | BPM オーバーライド |
| `phases[].scale` | No | scale オーバーライド（転調用） |
| `phases[].mute_drums` | No | フェーズ単位のドラムミュート |
| `phases[].mute_bass` | No | フェーズ単位のベースミュート |
| `transition_sec` | No | トランジション秒数（default: 30） |

**LiveMusicGenerationConfig 全パラメータ**: bpm, brightness, density, guidance, temperature, scale, top_k, seed, mute_bass, mute_drums, only_bass_and_drums, music_generation_mode
- `scale` は enum 値のみ: `C_MAJOR_A_MINOR`, `D_MAJOR_B_MINOR`, `G_MAJOR_E_MINOR` 等（Dorian/Mixolydian 等のモード指定不可）
- `negative_prompt` は Live API に存在しない（プロンプト本文で `no X` 形式で指示）

### 具体例

> 例: composition.json のサンプル（楽器切り替え式）:

```json
{
  "title": "Example Theme",
  "total_duration_min": 123,
  "base": {
    "prompt_prefix": "(channel_config.json の lyria.prompt_prefix を参照)",
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
      "name": "ギターの独白 — 旅の記憶",
      "name_en": "Guitar Soliloquy — Journey Memory",
      "prompt": "solo fingerpicked acoustic guitar, melody wandering freely in A minor, phrases rising and falling with varied rhythm",
      "brightness": 0.35,
      "bpm": 105,
      "density": 0.15
    },
    {
      "at_min": 8,
      "name": "ティンホイッスルの歌 — 風の便り",
      "name_en": "Tin Whistle Song — Wind Message",
      "prompt": "tin whistle entering with ascending melody, each phrase exploring a new direction, fingerpicked guitar weaving underneath",
      "brightness": 0.4,
      "bpm": 112,
      "density": 0.3
    },
    {
      "at_min": 16,
      "name": "フィドルの加入 — 仲間の温もり",
      "name_en": "Fiddle Joins — Warmth of Companions",
      "prompt": "medieval fiddle joining with ornamental melody that develops with each phrase, grace notes and turns, guitar shifting between strumming and picking",
      "brightness": 0.5,
      "bpm": 115,
      "density": 0.45
    },
    {
      "at_min": 24,
      "name": "静かな余韻 — 時の流れ",
      "name_en": "Quiet Afterglow — Flow of Time",
      "prompt": "solo fingerpicked acoustic guitar, returning to opening melody but finding new variations and resolutions each phrase",
      "brightness": 0.3,
      "bpm": 100,
      "density": 0.1
    }
  ],
  "transition_sec": 30
}
```

**プロンプト設計のポイント（Test A-F 比較実験結果、2026-03-08）:**

| 設定 | 推奨値 | 根拠 |
|------|--------|------|
| `guidance` | **3.0** | 2.5だとpad音増加（プロンプト忠実度不足）、3.5だと音数過多 |
| `temperature` | **0.9** | 0.7だとメロディが単調ループ、0.6以下はノイズ増 |
| `bpm` | **85-118** | 静かなフェーズ 88-95、活発なフェーズ 115-118。コントラストで動きを出す |
| `scale` | **C_MAJOR_A_MINOR** | ジャンルに合った音階を選択 |
| `mute_drums` | **true** | パーカッションなしの intimate サウンド |
| `prompt_prefix` | **最小限** | ジャンル + `acoustic instruments only` + `clean dry recording, no pads`。楽器名・ムード語は入れない |
| ネガティブ指示 | `no pads` 程度 | 大量の `no X` は逆効果（概念を活性化する）。最小限に留める |
| プロンプトスタイル | **動作指示** | 状態描写（sparse, intimate）→ ループ。動作指示（wandering, exploring, climbing）→ 展開 |
| `ambient pads` | **NG** | Lyria を ambient 方向に引っ張る |
| `ethereal choir` | **NG** | 同上 |
| `cinematic` | **NG** | 同上 |
| 楽器切り替え | フェーズごと | 全楽器同時は NG。Guitar → Whistle → Fiddle → Guitar |

## Step 3: 設定の書き出しとユーザー確認

1. composition.json を `20-documentation/composition.json` に保存
2. `20-documentation/lyria-composition.md` に設定を書き出す（`/suno` の `suno-prompts.md` に相当）:
   - ヘッダー（Engine, Channel, Duration）
   - 感情アーク（フェーズの流れを可視化）
   - Timeline Summary（dry-run 出力形式のサマリー）
   - Base Settings テーブル
   - 各フェーズの詳細（日本語解説 + prompt + パラメータ）
   - Lyria 推奨設定
   - 品質チェックリスト

**Timeline Summary の形式**（dry-run 出力を転記）:

```
=== {title} ({total_duration_min}min) ===
  Base: bpm={bpm}  brightness={brightness}  mode={mode}
  Transition: {transition_sec}s crossfade

  {HH:MM}  {phase_name}    brightness={x}   bpm={x}
  ...
  {HH:MM}  END
```

3. dry-run でタイムラインを表示:

```bash
uv run yt-generate-music-dj -c 20-documentation/composition.json --dry-run
```

4. ユーザーにフェーズ構成・タイミングの確認を求める
5. 修正があれば composition.json と lyria-composition.md を両方編集して再度 dry-run

## Step 4: プレビュー生成

本生成の前に、3つの代表フェーズから30秒のプレビューサンプルを生成して方向性を確認する:

```bash
uv run yt-generate-music-dj \
  -c 20-documentation/composition.json \
  -o 01-master/master.wav \
  --preview
```

- 始め・中盤・終盤の3フェーズから各30秒サンプルを並列生成（約30秒で完了）
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

> **`.env` は自動ロード**: スクリプト内で `dotenv` により自動読み込みされるため、`source .env` は不要。

**セグメント分割生成**（デフォルト有効）:
- 各 phase を独立した API セッションで生成（API の10分制限を回避）
- `--workers N` で並列生成数を指定（推奨: `--workers 10`、全セグメント並列）
  - `0`: 逐次生成（デフォルト）
  - `N`: N並列（Semaphore で制御）
  - `-1`: 全並列（セグメント数 = 並列数）
- 生成中に `seg_001.wav`, `seg_002.wav`, ... が作成される
- 全セグメント完了後にクロスフェード結合して master.wav を出力
- 途中失敗時は自動リトライ（`--max-retries` 回）
- 再実行時は成功済みセグメントをスキップして続行
- `--no-segmented` で従来の1セッション生成に戻す

**生成時間の目安**:
- `--workers 10`（並列）: 123分のコレクション ≈ **約10分**（最長セグメントのリアルタイム長に依存）
- `--workers 0`（逐次）: 123分のコレクション ≈ 123分

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

- [ ] `prompt_prefix` が `channel_config.json` の `lyria.prompt_prefix` に基づいていること
- [ ] `guidance`, `temperature`, `mute_drums` が `channel_config.json` の `lyria` セクションの値に準拠していること
- [ ] 各 phase の `prompt` に主役楽器の演奏指示が含まれていること（楽器切り替え式）
- [ ] `ambient pads`, `ethereal choir`, `cinematic` が使用されていないこと
- [ ] ネガティブ指示（`no synthesizer, no sound effects` 等）が含まれていること
- [ ] 禁止形容詞（/suno スキル参照）が使用されていないこと
- [ ] 最初の phase が `at_min: 0` であること
- [ ] **各 phase の長さが10分以内であること**（API セッション制限）
- [ ] フェーズ間に `transition_sec` 以上の間隔があること
- [ ] `total_duration_min` が最後のフェーズ以降に十分な再生時間を確保していること
- [ ] `--preview` でプレビュー生成し、音楽の方向性を確認済み

## Next Step

→ `/videoup` で動画生成を実行（WAV → MP4 変換は既存の generate_videos.sh を使用）
