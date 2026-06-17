---
name: suno
description: "Use when Suno UI に投入する音楽プロンプト (Style + Lyrics) を生成したいとき。SunoAI V5 向けの YAML 定義（インストは `tracks_per_collection` で曲数指定の独立 entry 並列、ボーカルは pattern × tracks_per_pattern 設計）から suno-prompts.md / suno-prompts.json を作成する（次工程 `/suno-helper` でブラウザ自動生成 + playlist 一括追加、その後 `/masterup` で DL + マスター化）。プロンプト作成・Style 文・Lyrics テンプレートなど Suno 連続生成の前段で使用すること。Lyria チャンネルでは /lyria を使う"
---

## Overview

コレクション用の SunoAI v5 音楽プロンプトを YAML で定義し、スクリプトで最終プロンプトを生成する。**インストゥルメンタル / ボーカル（歌詞あり）両モード対応**。

- **インストモード**: 曲数 (`tracks_per_collection`) を指定し、ceil(N/2) 個の独立 entry をフラットに並べる（pattern 概念は廃止）。`/suno-helper` が各 entry を Suno に順次投入し、Suno 仕様で 1 Generate = 2 clip 生成されるため両 clip 採用で N clip となる
- **ボーカルモード**: 従来どおりパターン (`pattern_strategy: mixed/single`) × 再生成 (`tracks_per_pattern`) で構成し、ベスト曲を選曲する運用（歌唱の発音・ピッチ精度のため）

### モード判定

`config/skills/suno.yaml` の `genre_line` を読み取り、**ボーカル要素**（`vocals`, `vocal`, `singing`, `rap`, `male/female vocals` 等）が含まれていれば**ボーカルモード**、なければ**インストゥルメンタルモード**として処理する。

| モード | YAML 構造 | 歌詞 | Suno 設定 |
|---|---|---|---|
| インストゥルメンタル | `tracks_per_collection` 由来の `ceil(N/2)` 個の独立 entry | 不要 | Custom Mode + **Instrumental ON** |
| ボーカル | `pattern_strategy` × `tracks_per_pattern` のパターン設計 | 必須 | Custom Mode + **Instrumental OFF** + Lyrics 投入 |

### スタイルバリアント（A/B テスト対応）

`config/skills/suno.yaml` に `style_variants` が定義されている場合、各 entry / パターンに `style` キーで variant を指定できる。`style_strategy: mixed` なら 1 コレクション内で複数 variant を混合、`single` なら全 entry 同一 variant で統一。

## Instructions

### 前提条件チェック（hard gate）

**AI は `genre_line` を手書きしてはならない。** 方向性は必ずスクリプト（`yt-video-analyze` の `suno_preset` 出力）由来とする。`/suno` 実行に入る最初のステップとして以下を機械的に判定し、要件を満たさない場合はパターン設計に進まず中断する:

1. `config/skills/suno.yaml` の `genre_line` を読む
2. `config/channel/analytics.json` の `benchmark.channels[].slug` を列挙
3. 各 slug について `data/video_analysis/<slug>/*.json` の存在を確認

| 状態 | 判定 | アクション |
|---|---|---|
| `genre_line` 非空 | OK | パターン設計に進む（既存 `suno_preset` fallback は引き続き有効） |
| `genre_line` 空 + 少なくとも 1 slug で `data/video_analysis/<slug>/*.json` 存在 | OK | `suno_preset.genre_line` を fallback として採用しパターン設計に進む |
| `genre_line` 空 + 全 slug で `data/video_analysis/<slug>/*.json` 不在 | **NG（中断）** | パターン設計に進まず、ユーザーに以下を案内して停止する |

NG 時の案内テンプレ:

```
`/suno` を進められません: `genre_line` が空で、benchmark の video-analyze 結果も未取得です。
AI が方向性を手書きすると意図しないジャンルに流れるため、以下のいずれかを先に実行してください。

1. `data/benchmark_*.json` が無ければ: `/benchmark` を先行実行
2. `data/benchmark_*.json` 取得済みなら: `uv run yt-video-analyze --source benchmark --channel <slug> --top 5`
   を全 benchmark slug で実行
3. 終わったら `/suno <theme>` を再実行

どうしても手書きで続行する場合のみ、明示的に `config/skills/suno.yaml::genre_line` を埋めてから再実行してください。
```

`AskUserQuestion` で「上記の手順を自動実行するか」を提示することは可能だが、**ユーザーが明示同意するまでパターン設計の本文（情景フレーズ・歌詞含む）の作成に着手しない**。`genre_line` 候補を本文中で口頭提案するのも禁止（手書き相当のため）。

### ベンチマーク BGM 構造の参照

設計に入る前に `data/video_analysis/<slug>/*.json` の `bgm_arc` を読み込み、slug ごとに intro 秒・peak 秒・outro 開始秒の平均と代表的な `energy_curve` パターンを抽出する。インストモードでは entry 間のバリエーション素材として、ボーカルモードでは起伏配置の参考にする。`scene_timeline[].summary` も情景フレーズ設計の素材として活用する。ベンチマーク構造を参考にするが**完全模倣しない** -- 差別化方針と矛盾する場合は意図的に外す。

### Suno プリセット推奨（suno_preset fallback）

`data/video_analysis/<slug>/*.json` の `suno_preset.genre_line` / `suno_preset.exclude_styles` を `yt-generate-suno` が fallback として参照する。`config/skills/suno.yaml` の対応キーが空のとき、全 slug 横断で集約した推奨値を採用する。ユーザーが `config/skills/suno.yaml` に override を書いた瞬間にそちらが優先される（後方互換）。

> **方向性は必ずスクリプト由来とする（AI 手書き禁止）**: `genre_line` 空 + `suno_preset` fallback も取れない状態で本 skill が AI 推定の `genre_line` を書き起こすことは禁止する。

### 対象テーマ

```
$ARGUMENTS
```

## Quality Rules (suno-bgm)

### Style Text 5-Element Order

Style テキストは以下の順序で構成する。順序を守ることで Suno の解釈精度が安定する:

1. **ジャンル名** (e.g. lo-fi hip hop, jazz)
2. **音響特性** (e.g. warm, airy, muffled)
3. **キー楽器** (e.g. felt-damped upright piano, fingerpicked acoustic guitar)
4. **リズム/ベース** (e.g. laid-back boom-bap drums, deep fretless bass)
5. **テンポ** (e.g. slow, moderate)

### 120 Character Limit

Style フィールドは **120 文字以下** でなければならない。`yt-generate-suno` がビルド時に超過を警告する。5-Element Order に従って要素を絞り込み、収まらない修飾語は削る。

### Artist Name Prohibition

**Style テキストにアーティスト名を含めてはならない。** Suno ポリシーにより生成がブロックされるか品質が低下する。禁止リストは `config/skills/suno.yaml::banned_artists` に定義されており、`yt-generate-suno` が検出するとエラーで停止する。

### Instrument Adjective Requirements

楽器名には必ず音響的な形容詞（音色・奏法・素材・時代）を付けること。裸の楽器名は Suno が汎用音色を選択し意図した音像から外れる。具体的な Bad/Good ペアは `references/suno-examples.md` の "Instrument Adjective Pairs" を参照。

### Hiragana Lyrics Guide

`lyrics_guidelines.language: ja` の場合、歌詞は**ひらがなで書く**こと。Suno は漢字の読みを頻繁に誤るため、ひらがな表記で発音精度を確保する。カタカナは外来語にのみ使用可。

### Lyrics Structure Auto-Reinforcement

`auto_lyrics_structure: true`（デフォルト）のとき、`yt-generate-suno` が歌詞構造タグを自動補完する:

- **インストモード**: 歌詞先頭に `[Instrumental]`、末尾に `[Extended Outro]` を自動付加
- **ボーカルモード**: 最終セクションが `[Outro]` または `[Extended Outro]` であることを保証

### Mixing/Instrument Notes in Lyrics Header

インストモードでは、歌詞フィールドの先頭（`[Instrumental]` の前）に Mixing Notes と Instrument Notes を記述して Suno のミキシングを誘導できる:

```
Mixing Notes: warm analog warmth, slight tape saturation
Instrument Notes: lead with felt piano, background with soft pad
[Instrumental]
[Extended Outro]
```

## Track Title Generation (#899)

各 entry には **`name_en`**（2-4 word の英語シーン/ムードタイトル）と **`name_jp`**（5-15 文字の日本語訳）を付ける。Suno UI の Song Title 欄に `{name_jp} — {name_en}` として注入され、Library / playlist / `/masterup` のリネームで識別子となる。

### 命名ルール

- pattern scene + persona vocabulary をベースに、情景・質感・場所を凝縮した自然なフレーズにする
- Amber Music Playlist TTP スタイルの例:
  - "Midnight Funk Groove" / "深夜のファンクグルーヴ"
  - "Velvet Vinyl Spin" / "ベルベットレコード"
  - "Smoky Jazz Lane" / "スモーキージャズ通り"

### バリデーション

- **全タイトルユニーク**: コレクション内で `name_en` / `name_jp` の重複は `yt-generate-suno` が fail-loud で停止
- **自然なフレーズ**: AI っぽい抽象語の羅列（word salad）は禁止。具体的な情景が浮かぶタイトルにする
- **他コレクションとの差別化**: 他コレクションのタイトルと 3 単語以上の連続一致がないこと

## 曲数ベース設計（インストモード）

**pattern 概念を廃止し、`tracks_per_collection` から `ceil(N/2)` 個の独立 entry をフラットに並べる**。各 entry = 1 Generate = 2 clip 両採用。

| キー | 役割 | 既定 |
|---|---|---|
| `tracks_per_collection` | 最終 clip 数 | `20` |
| `tracks` (yaml) | コレクション単位の上書き | 省略 |
| `style_strategy` | `mixed` / `single` | `single` |

### 1 pattern = 1 scene 原則（必須）

**各 pattern の `scenes` は必ず 1 行のみとする。** 1 pattern に複数 scenes を入れると、コードが `(Variation 1)` `(Variation 2)` ... の機械的接尾辞でタイトルを生成し、曲ごとの固有性が失われる。
代わりに `ceil(N/2)` 個の pattern をフラットに並べ、それぞれに固有の `name_jp` / `name_en` と 1 行の scene を持たせること。

**NG（複数 scenes → Variation N で機械的ユニーク化）:**
```yaml
patterns:
  - name_jp: 不屈の持久
    name_en: Unbreakable Endurance
    scenes:
      - scene A text...
      - scene B text...
      - scene C text...
```

**OK（1 pattern = 1 scene、各曲が固有タイトル）:**
```yaml
patterns:
  - name_jp: 鋼の意志
    name_en: Iron Will
    scenes:
      - scene A text...
  - name_jp: 揺るがぬ決意
    name_en: Unwavering Resolve
    scenes:
      - scene B text...
  - name_jp: 不屈の持久
    name_en: Unbreakable Endurance
    scenes:
      - scene C text...
```

### 手順

1. ベンチマーク `bgm_arc` と `scene_timeline[].summary` から多様な情景素材を集める
2. `config/skills/suno.yaml::tracks_per_collection` を読み曲数を確定（上書き時は yaml の `tracks:` キー）
3. `ceil(tracks / 2)` 個の entry を設計。**各 entry は固有の `name_jp` / `name_en` を持ち、`scenes` は 1 行のみ**
4. style variant を割り当て（`single` なら全 entry 同一、`mixed` なら entry ごとに切替）
5. `yt-generate-suno` 実行で検証（entry 数不一致・name 重複は fail-loud）

## パターンベース設計（ボーカルモード）

**ボーカルモードのみ、パターン × 再生成回数で設計する**（歌唱の不安定さのためベスト曲選曲運用を維持）。

| キー | 役割 | 既定 |
|---|---|---|
| `pattern_strategy` | `mixed` / `single` | `mixed` |
| `tracks_per_pattern` | パターンあたりの再生成回数 | `3` |

- `single`: 1 つの統合情景フレーズにまとめ、同一プロンプトを `tracks_per_pattern` 回生成
- `mixed`: 感情の起伏を N 個のパターンに分割（典型 4: 静寂 → 開放 → 親密 → 動き）

### 曲の長さ（V5）

Suno V5 では Styles 経由で実楽曲長を制御できない。望む長さに満たない場合は **Suno UI の Extend** で延長する。

### ボーカル歌詞設計

1. 構造タグ必須: `[Intro]` / `[Verse]` / `[Chorus]` / `[Bridge]` / `[Outro]`
2. 言語: `lyrics_guidelines.language` に従う
3. 長さ: 4-5 分曲で 120-180 単語程度
4. gender 整合: サムネのキャラ性別・歌詞の語り手・`genre_line` のボーカル性別を一致させる

#### style_reference

`config/skills/suno.yaml` の `lyrics_guidelines.style_reference` に参考歌詞を登録できる。文体参照専用で、歌詞本文・固有表現を copy / verbatim / そのままコピペしてはいけない。抽出するのは: 1 行の長さ、視点、loose rhyme の密度、Chorus の mantra 感、情景から感情への順序のみ。

#### 英語歌詞のネイティブ感ガード

`lyrics_guidelines.language: en` の場合:

- 観察日記のように、目の前の小さな動作・光・温度から始める
- ABCB などの loose rhyme を使い、語尾を揃えすぎない
- Chorus は説明文ではなく、短い mantra として繰り返せる言葉にする
- 意味反転語を避ける。例: `downfall` は「美しい終わり」ではなく失墜・転落を連想させるため禁止
- 抽象語だけで感情を説明せず、生活の細部から感情を出す

歌詞テンプレとジャンル別例は `references/lyrics-examples.md` を参照。

#### Codex 経由の歌詞初稿生成

`config/skills/suno.yaml` の `lyrics_generation.provider` で歌詞初稿の生成経路を切り替えられる。

| provider | 生成経路 |
|---|---|
| `claude` | 通常の `/suno` skill 実行内で歌詞を作る |
| `codex` | `.claude/skills/suno/references/codex-lyrics.sh` で Codex CLI に歌詞下書きを委譲する |

`codex` を使う場合は ChatGPT API を直叩き・直接呼び出ししない。追加 API key を持たず、ChatGPT ログイン済みの Codex CLI を使う。事前に `codex login status` でログイン状態を確認する。

## 情景フレーズ設計ルール

1. **命令文なし**: `Create a...` で始めない。情景を描写する
2. **簡潔な修飾**: 形容詞は 1-2 個。繰り返し禁止
3. **五感に訴える**: 視覚・触覚・嗅覚など具体的な描写。メロディ・ベース・リズムは書かない
4. **楽器ロール指定**: `Solo Cello` や `Ethereal Choir` でフィーチャー楽器を強調可能（任意）
5. **ベンチマーク活用**: `scene_timeline[].summary` を素材にするが**そのままコピペしない**

### 禁止形容詞

> thundering, blazing, crushing, soaring, screaming, devastating, explosive, ferocious, towering, surging, crystalline, shimmering, lush, sweeping, majestic, glorious, echoing

代替: low, sparse, bright, soft, deep, gentle, quiet, warm, airy, rising, driving 等

### 雨音・環境音の制御

**雨音や環境音は楽曲に含めない。** NG ワード: rain, dripping, drops, puddles, splashing, pouring 等。OK ワード: misty, melancholic, nocturnal, bittersweet, foggy 等。全プロンプトに `no rain sound effects, no white noise, no ambient noise` を追加。`exclude_styles` にも `rain sounds, vinyl crackle, white noise, ambient noise` を含める。

#### genre_line と exclude_styles の整合性

`exclude_styles` で除外したワードを `genre_line` 側に残すと相殺される。たとえば `exclude_styles` に `vinyl crackle` を含めつつ `genre_line` に `vinyl crackle warmth` を入れると除外が無効化される。`exclude_styles` を更新するときは `genre_line` 側にも同じワードや派生表現が混ざっていないかをセットで確認する。

### テンポ設計

自然言語テンポ: `very slow` / `slow` / `gentle` / `moderate` / `lively`

| テーマ | テンポ | 情景フレーズ例 |
|--------|--------|--------------|
| Study / Reading | slow | fingers turning pages slowly |
| Sleep / Dream | very slow | embers fading in a stone hearth |
| Forest / Nature | gentle / moderate | morning mist between ancient oaks |
| Festival / Dance | lively | fiddles rising in a torchlit hall |

## 出力

### Step 1: 定義を YAML で保存

`20-documentation/suno-patterns.yaml` に保存。インストモードは `ceil(N/2)` 個の独立 entry を `patterns:` 配列に並べる。ボーカルモードはパターン単位で scenes + lyrics を記述。

```yaml
title: Collection Title Here
mode: instrumental  # 省略時は genre_line から自動判定
tracks: 10  # 省略時は config の tracks_per_collection
patterns:
  # 1 pattern = 1 scene = 固有タイトル。ceil(10/2) = 5 個の entry
  - name_jp: 屋上の静寂
    name_en: Rooftop Silence
    tempo: slow
    scenes:
      - a heavy door propped open with a brick, cool night air rising through a dim stairwell
  - name_jp: 煙突の向こう
    name_en: Beyond the Chimney
    tempo: slow
    scenes:
      - grey smoke trailing upward from a rooftop chimney, the skyline a blurred edge of warm windows
  - name_jp: 路地裏の灯り
    name_en: Alley Lantern Glow
    tempo: gentle
    scenes:
      - a single paper lantern swaying above a narrow alley, puddles catching the soft amber light
  - name_jp: 港の霧笛
    name_en: Harbor Foghorn
    tempo: slow
    scenes:
      - a distant foghorn rolling across a still harbor, ships resting dark against a grey dawn
  - name_jp: 窓辺の雨だれ
    name_en: Windowsill Drip
    tempo: gentle
    scenes:
      - condensation tracing slow lines down a warm kitchen window, a kettle just finished steaming
```

### Step 2: スクリプトで suno-prompts.md を生成

```bash
uv run yt-generate-suno <collection-path>
```

`config/skills/suno.yaml` の `genre_line` + `exclude_styles` + `style_influence` をパターンに自動付加して `suno-prompts.md` と `suno-prompts.json` を生成する。保存後、`workflow-state.json` の `music.generated = true` に更新する。

### Step 3: `/suno-helper` で自動投入（推奨）

`suno-prompts.json` を Chrome 拡張（`extensions/suno-helper/`）が読み取り、連続実行する。

1. **拡張をビルドしてロード**（初回のみ）: `pnpm install && pnpm build` → Chrome で `chrome://extensions` → `.output/chrome-mv3/` を選択
2. **サーバー起動**: `tayk collection-serve collections/planning/<theme>` → `http://localhost:7873/suno/prompts.json` で配信
3. **Suno を開く**: Chrome で Custom Mode 画面（ボーカルは **Instrumental OFF**）
4. **取得 → 連続実行**: 拡張ポップアップでデータ取得 → 全パターンを連続実行。スキップされた entry は再実行ボタンで再投入可能

UI 変更で注入先セレクタが外れた場合は `extensions/shared/dom.ts` の `SELECTORS` を保守する。

### Step 3 の fallback: 拡張が使えない／壊れたときの手コピペ

拡張をロードできない場合は `suno-prompts.md` を見ながら手コピペに切り替える: Suno の Custom Mode に入り、パターンごとに Style 欄と Lyrics 欄を貼り付けて Generate。自動・手動どちらでも投入内容は同一。

### Step 4: workflow-state.json の planning.music を更新

`/alignment-check` が音楽 mood × サムネ × タイトルの整合を判定できるよう、`workflow-state.json` の `planning.music` を populate する。

```json
{
  "planning": {
    "music": {
      "engine": "suno",
      "mood": ["mellow", "introspective"],
      "atmosphere": "rainy harbor at night, mellow jazz by the docks",
      "tempo": "slow",
      "instruments": ["soft piano", "saxophone", "upright bass"],
      "exclude": ["electric guitar", "heavy drums"]
    }
  }
}
```

## オーディオビジュアライザー / オーバーレイ

`/suno` は Suno UI に投入するプロンプト生成工程であり、映像オーバーレイは扱わない。詳細は `videoup` SKILL.md の該当節を参照。

## Next Step

### インストゥルメンタル
→ `/suno-helper` で SunoAI Custom Mode（**Instrumental ON**）に自動投入して連続生成 + playlist 一括追加
→ `/masterup <playlist-url>` でダウンロード + マスター音源生成

### ボーカル（歌詞あり）
→ `/suno-helper` で SunoAI Custom Mode（**Instrumental OFF**）に Style + Lyrics を自動投入して連続生成 + playlist 一括追加
→ 歌唱の発音・ピッチが破綻していないか必ず試聴チェック
→ `/masterup <playlist-url>` でダウンロード + マスター音源生成

## Cross References

- 前工程（テーマ確定 + 制作開始）: `/wf-new`
- 次工程（ブラウザ自動生成 + playlist 一括追加）: `/suno-helper`
- 後工程（DL + マスター化）: `/masterup`
- 拡張本体のコード: `extensions/suno-helper/` / `extensions/shared/`
- サーバー CLI: `packages/cli/src/commands/collection-serve/cli.ts`
