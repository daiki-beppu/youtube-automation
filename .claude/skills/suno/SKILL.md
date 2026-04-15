---
name: suno
description: Use when コレクションのテーマが確定し、SunoAI用の音楽プロンプト生成が必要なとき。音楽制作、プロンプト作成、SunoAI、曲を作る、BGM制作など、音楽プロンプト生成に関わる場面で必ず使用すること
---

## Overview

コレクション用の SunoAI v5 音楽プロンプトのパターン定義（YAML）を作成し、スクリプトで最終プロンプトを生成する。**インストゥルメンタル / ボーカル（歌詞あり）両モード対応**。

AI の役割は **情景フレーズ（scenes）+ テンポ（tempo）+ 歌詞（lyrics、ボーカルモード時）の設計** に集中すること。genre_line や共通設定はスクリプトが `channel_config.json` から自動付加する。

### モード判定

`channel_config.json` の `music_engine` および `suno.genre_line` を読み取り、**ボーカル要素**（`vocals`, `vocal`, `singing`, `rap`, `male/female vocals` 等）が含まれていれば**ボーカルモード**、なければ**インストゥルメンタルモード**として処理する。

| モード | 情景フレーズ | 歌詞 | Suno 設定 |
|---|---|---|---|
| インストゥルメンタル | 必須 | 不要 | Custom Mode + **Instrumental ON** |
| ボーカル（歌詞あり） | 必須（楽曲の世界観として歌詞と整合） | 必須（パターンごと） | Custom Mode + **Instrumental OFF** + Lyrics 欄に投入 |

### スタイルバリアント（A/B テスト対応）

`channel_config.json` に `suno.style_variants` が定義されている場合、パターンごとに `style` キーで variant を指定できる。variant が指定されたパターンは、デフォルトの `genre_line` の代わりに variant 固有の `genre_line` が使われる。

**戦略選択**（`suno.style_strategy` を参照）:

| 戦略 | 説明 | YAML での指定方法 |
|------|------|------------------|
| `mixed` | 1コレクション内で複数の variant をランダム混合 | 各パターンに異なる `style: A`〜`E` を割り当て |
| `single` | 1コレクション = 1 variant で統一 | 全パターンに同じ `style: X` を割り当て |

テスト期間中は両戦略をランダムに回し、Analytics 結果に基づいて最適化する。

## Instructions

### 対象テーマ

```
$ARGUMENTS
```

## パターンベース設計

4パターンで感情・エネルギーの起伏を設計し、各パターンに1つの情景フレーズを用意する:

1. テーマの感情の流れを設計（例: 静寂 → 開放 → 親密 → 動き）
2. 各パターンで1つの統合された情景フレーズを用意（複数シーンの要素をマージ）
3. 各パターンに style variant を割り当て

### 生成計画

4パターン × 3回生成（1回2曲）= **24トラック** → ベスト曲を選定。
プロンプト変更は **4回のみ**（パターン切替時のみ）。

### 曲の長さ制御（V5）

V5 では Styles に時間指定プロンプトが反映されるようになった。`channel_config.json` の `suno.duration_prompt` で一元管理:

- **Styles に追加**: `long-form performance, over 4 minutes, 4 to 5 minutes`
- **Style Influence**: 85%（高めにすると時間指定がより反映される）
- **Model**: V5 を使用

スクリプトが `duration_prompt` を全パターンの Styles 末尾に自動付加する。

> 注意: 構造タグ（[Intro], [Verse], [Chorus], [Bridge], [Outro]）は**インストゥルメンタルでは効果なし**だが、
> **ボーカルモードでは Lyrics 欄に必須**（楽曲構成を Suno に伝える）。
> Extend は最終手段として使えるが、Styles での時間指定を優先する。

## ボーカルモード（歌詞あり楽曲）

`music_engine: suno` かつ `suno.genre_line` にボーカル要素が含まれる場合に適用。

### 歌詞設計ルール

1. **構造タグ必須**: 各歌詞ブロックの先頭に `[Intro]` / `[Verse]` / `[Chorus]` / `[Bridge]` / `[Outro]` のいずれかを置く（Suno が認識）
2. **言語**: `channel_config.json` の `youtube.language` に従う（bobble の場合は `en`）
3. **長さ目安**: 4-5 分曲なら **120-180 単語** 程度（Verse 2 + Chorus 2 + Bridge 1 + Outro）
4. **テーマ整合**: 情景フレーズ（scenes）と歌詞の世界観を一致させる。例: scene が "late night drive" なら歌詞も夜・移動・解放を扱う
5. **ジャンル整合**: bobble は laid-back rap + intimate vocals。**conversational tone（会話的な語り）**で。叫ばない、誇張しない
6. **韻・リズム**: jazzhop の lazy flow に乗るよう、行末の韻を緩く揃える。完璧な韻より**ナチュラルな会話感**優先
7. **NG**: explicit 表現、攻撃的な語、政治・宗教、商品名、固有人名（ジェネリックな "you / I / we" を使う）

### 歌詞テンプレ（jazzhop / conversational rap 想定）

```
[Intro]
(short instrumental cue, optional 1-2 line spoken intro)

[Verse 1]
4-8 行。情景描写から始める。一人称 or 二人称の語り。

[Chorus]
2-4 行を繰り返す。コアフレーズ（タイトルや keyword に直結）。

[Verse 2]
4-8 行。Verse 1 の続き or 視点シフト。

[Chorus]
（繰り返し）

[Bridge]
2-4 行。視点を変える、または感情のピーク。

[Chorus]
（最後にもう一度）

[Outro]
1-2 行 or instrumental fade。
```

### 歌詞の品質基準例（bobble 向け）

```
[Verse 1]
Tail lights painting lines across the wet asphalt
Got the windows down, ain't nobody gotta call
Just the late-night radio and the lazy bassline drop
Mind off, groove on, baby, let the city pass us all

[Chorus]
Slow it down, slow it down, ain't no rush to get there
Slow it down, slow it down, breathing in the night air
```

**成功要因**:
- 視覚描写（tail lights, wet asphalt）+ 聴覚（bassline）+ 体感（windows down）のバランス
- "Mind off, groove on" など**チャンネルキャッチコピーを歌詞に組み込み**
- Chorus は短く、繰り返しやすく、覚えやすい

## 情景フレーズ設計ルール

1. **命令文なし**: "Create a..." で始めない。情景を描写する
2. **簡潔な修飾**: 形容詞は1-2個。繰り返し禁止
3. **五感に訴える**: 視覚・触覚・嗅覚など具体的な描写。メロディ・ベース・リズムは書かない
4. **楽器ロール指定**: "Solo Cello" や "Ethereal Choir" でフィーチャー楽器を強調可能（任意）

### 禁止形容詞（情景フレーズ内）

SunoAI をモダン/オーケストラ方向に誘導するため禁止:

> thundering, blazing, crushing, soaring, screaming, devastating, explosive, ferocious, towering, surging, crystalline, shimmering, lush, sweeping, majestic, glorious, echoing

代替: low, sparse, bright, soft, deep, gentle, quiet, warm, airy, rising, driving 等

### 雨音・環境音の制御

**雨音や環境音は楽曲に含めない。** マスタリング時に別レイヤーで追加する。

SunoAI は情景フレーズ中の水・雨関連ワードを SE（効果音）として生成してしまう。以下のルールを守る:

**NG ワード（SE を誘発）:**
> rain, dripping, drops, puddles, splashing, pouring, streaming water, trickling, wet（音を連想する文脈で）

**OK ワード（ムード・視覚のみ）:**
> misty, melancholic, nocturnal, bittersweet, wistful, lonesome, lingering, overcast, hazy, foggy, damp（視覚描写として）, glistening, misted, fogged

**全プロンプトに必ず追加:**
```
no rain sound effects, no white noise, no ambient noise
```

**Exclude Styles にも必ず追加:**
```
rain sounds, vinyl crackle, white noise, ambient noise
```

しっとり感は `misty`, `melancholic`, `nocturnal`, `bittersweet` 等のムード語で表現する。

### 品質基準プロンプト例（C-1 パターン）

以下は品質が高いプロンプトの例。新規プロンプト作成時の基準として参照する:

```
chill jazz hop, dusty piano samples, jazzy guitar licks, deep bass groove,
bass-forward mix, prominent upright bass, lo-fi drum loop, tape saturated,
instrumental, gentle, moody and misty, no rain sound effects, no white noise,
no ambient noise,
glistening cobblestone sidewalk at night, a bookshop awning glowing softly
```

**成功要因:**
- ベースが前面に出ており、BGM としての厚みがある
- `moody and misty` でしっとり感を確保しつつ雨 SE なし
- `tape saturated` でアナログの温かみ（`vinyl crackle` は NG）
- 情景フレーズが視覚的で音を連想しない

### テンポ設計

自然言語テンポ: `very slow` / `slow` / `gentle` / `moderate` / `lively`

| テーマ | テンポ | 情景フレーズ例 |
|--------|--------|--------------|
| Study / Reading | slow | fingers turning pages slowly |
| Mystical / Magic | slow / gentle | a glass orb glowing soft blue |
| Sleep / Dream | very slow | embers fading in a stone hearth |
| Village / Town | moderate | bread cooling on a windowsill |
| Forest / Nature | gentle / moderate | morning mist between ancient oaks |
| Tavern / Inn | moderate | ale mugs and low firelight |
| Journey / Travel | moderate | boots on a winding road at dusk |
| Festival / Dance | lively | fiddles rising in a torchlit hall |

## 出力

### Step 1: パターン定義を YAML で保存

`20-documentation/suno-patterns.yaml` に保存。**scenes + tempo（インスト時）** または **scenes + lyrics（ボーカル時）** を記述する。`style_variants` がある場合は `style` キーで variant を指定可能。

#### インストゥルメンタルモード

```yaml
title: Collection Title Here
mode: instrumental  # 省略時は genre_line から自動判定
patterns:
  - name_jp: 屋上の静寂
    name_en: Rooftop Silence
    style: C
    scenes:
      - a heavy door propped open with a brick, cool night air rising through a dim stairwell, the last stars fading above an antenna array

  - name_jp: 最初の夜景
    name_en: First Glimpse of the Skyline
    style: A
    scenes:
      - a folding chair facing a wide skyline, distant office windows still lit at midnight, warm air rising from rooftop vents
```

#### ボーカルモード（歌詞あり）

```yaml
title: Late Night Drive
mode: vocal  # 省略時は genre_line から自動判定
patterns:
  - name_jp: 夜の高速、ひとり
    name_en: Highway Alone
    scenes:
      - tail lights painting lines across wet asphalt, the radio humming low, an empty interstate stretching past sleeping suburbs
    lyrics: |
      [Verse 1]
      Tail lights painting lines across the wet asphalt
      Got the windows down, ain't nobody gotta call
      Just the late-night radio and the lazy bassline drop
      Mind off, groove on, baby, let the city pass us all

      [Chorus]
      Slow it down, slow it down, ain't no rush to get there
      Slow it down, slow it down, breathing in the night air

      [Verse 2]
      Streetlights flicker like they got a story too
      Half-lit gas stations and the moon is shining through
      Ain't no destination, just the rhythm and the road
      Mind off, groove on, baby, let the engine carry slow

      [Chorus]
      Slow it down, slow it down, ain't no rush to get there
      Slow it down, slow it down, breathing in the night air

      [Bridge]
      Sometimes the only therapy is keeping the wheels turning
      No conversation needed when the speakers keep on burning

      [Chorus]
      Slow it down, slow it down, ain't no rush to get there
      Slow it down, slow it down, breathing in the night air

      [Outro]
      (Hum it out, hum it out…)
```

**注意**:
- `style` 指定時は variant の genre_line にテンポが含まれるため、`tempo` は省略可能
- ボーカルモードでは各パターン**1 セット（scenes + lyrics）**。3回生成で 6 トラック/パターン
- インストモードは各パターン**1 シーン**のみ。3回生成で 6 曲/パターン

### Step 2: スクリプトで suno-prompts.md を生成

```bash
uv run yt-generate-suno <collection-path>
```

`channel_config.json` の `suno.genre_line` + `suno.mood_descriptors` をパターンに自動付加して `suno-prompts.md` を生成。設定変更時はスクリプト再実行のみで全プロンプトに反映される。

**ボーカルモードの出力**: 各パターンに **Style 欄**（情景フレーズ + genre_line）+ **Lyrics 欄**（歌詞そのまま）の 2 ブロックが書き出される。Suno 側で Custom Mode に入って **Instrumental トグル OFF** にした状態で両方をコピペする。

保存後、`workflow-state.json` の `music.generated = true` に更新する。

## Next Step

### インストゥルメンタル
→ SunoAI Custom Mode（**Instrumental ON**）にプロンプトを手動投入して楽曲生成
→ ダウンロード対象のプレイリストを作成
→ `/masterup <playlist-url>` でダウンロード + マスター音源生成

### ボーカル（歌詞あり）
→ SunoAI Custom Mode（**Instrumental OFF**）に Style + Lyrics を投入して楽曲生成
→ 歌唱の発音・ピッチが破綻していないか必ず試聴チェック
→ ダウンロード対象のプレイリストを作成
→ `/masterup <playlist-url>` でダウンロード + マスター音源生成
