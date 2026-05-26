---
name: suno
description: Use when Suno UI に投入する音楽プロンプト (Style + Lyrics) を生成したいとき。SunoAI V5 向けのパターン YAML と suno-prompts.md を作成する（楽曲生成は人手で Suno UI、DL + マスター化は次工程 /masterup）。プロンプト作成・Style 文・Lyrics テンプレートなど Suno 手動生成の前段で使用すること。Lyria チャンネルでは /lyria を使う
---

## Overview

コレクション用の SunoAI v5 音楽プロンプトのパターン定義（YAML）を作成し、スクリプトで最終プロンプトを生成する。**インストゥルメンタル / ボーカル（歌詞あり）両モード対応**。

## いつ使うか（選択タイミング）

音楽エンジンの選択は以下の階層で決まる:

1. **チャンネルのデフォルト** — `/channel-direction` で suno/lyria を検討 → `/channel-setup` が `config/channel/youtube.json` の `music_engine` に書き込む
2. **コレクション単位の上書き** — `/wf-new` の `yt-init-collection --music-engine suno` でコレクション毎に上書き可能（省略時はチャンネル設定を継承）
3. **このスキルが呼ばれるとき** — `/wf-new` が `workflow-state.json` の `music_engine = "suno"` を判定して `/suno` を自動実行する。手動で `/suno <theme>` を叩いた場合もこのスキルに入る

AI の役割は **情景フレーズ（scenes）+ テンポ（tempo）+ 歌詞（lyrics、ボーカルモード時）の設計** に集中すること。`genre_line` や共通設定はスクリプトが `config/skills/suno.yaml` から自動付加する。

### モード判定

`config/skills/suno.yaml` の `genre_line` を読み取り、**ボーカル要素**（`vocals`, `vocal`, `singing`, `rap`, `male/female vocals` 等）が含まれていれば**ボーカルモード**、なければ**インストゥルメンタルモード**として処理する。

| モード | 情景フレーズ | 歌詞 | Suno 設定 |
|---|---|---|---|
| インストゥルメンタル | 必須 | 不要 | Custom Mode + **Instrumental ON** |
| ボーカル（歌詞あり） | 必須（楽曲の世界観として歌詞と整合） | 必須（パターンごと） | Custom Mode + **Instrumental OFF** + Lyrics 欄に投入 |

### スタイルバリアント（A/B テスト対応）

`config/skills/suno.yaml` に `style_variants` が定義されている場合、パターンごとに `style` キーで variant を指定できる。variant が指定されたパターンは、デフォルトの `genre_line` の代わりに variant 固有の `genre_line` が使われる。

**戦略選択**（`style_strategy` を参照）:

| 戦略 | 説明 | YAML での指定方法 |
|------|------|------------------|
| `mixed` | 1 コレクション内で複数の variant をランダム混合 | 各パターンに異なる `style: A`〜`E` を割り当て |
| `single` | 1 コレクション = 1 variant で統一 | 全パターンに同じ `style: X` を割り当て |

## Instructions

### ベンチマーク BGM 構造の参照

パターン設計に入る前に、`config/channel/analytics.json` の `benchmark.channels[].slug` を列挙し、
各 slug について `data/video_analysis/<slug>/*.json`（`/video-analyze` の出力）が存在するか確認する。

- **存在する場合**: `bgm_arc.intro` / `bgm_arc.peak` / `bgm_arc.outro` / `bgm_arc.energy_curve` を
  読み込み、slug ごとに intro 秒・peak 秒・outro 開始秒の平均と代表的な `energy_curve` パターンを
  抽出する。これを 4 パターンの起伏配置（パターン 1 を intro 寄り、パターン 3 を peak 寄りなど）の
  参考にする。`scene_timeline[].summary` からは「視覚的に強い瞬間」のフレーズ候補を抽出し、
  情景フレーズ設計（後述）の素材として使う。
- **`data/video_analysis/<slug>/*.json` 不在 + `data/benchmark_*.json` も不在**: ユーザーに
  「`/benchmark` を先行実行してください」と案内し、本サブセクションはスキップして警告のみで続行。
- **`data/benchmark_*.json` は存在するが分析未実行**: `AskUserQuestion` で
  `uv run yt-video-analyze --source benchmark --channel <slug> --top 5` の自動実行を提案。承認時のみ
  実行、拒否時は警告のみで続行。
- **鮮度警告**: 各 `.json` の `analyzed_at` が最新 `data/benchmark_*.json` のファイル名日付より古い場合は
  警告のみ（中断しない）。

サマリー出力フォーマット:

```
**ベンチマーク BGM 構造（video-analyze 平均）**

| slug | intro (avg) | peak (avg) | outro 開始 (avg) | energy 代表 |
|---|---|---|---|---|
| <slug> | 12s | 1:45 | 8:20 | 「徐々に上昇 → 中盤ピーク → ゆるやかなフェード」 |
```

ベンチマーク構造を参考にするが**完全模倣しない**。差別化方針（`/channel-direction` の決定事項）と
矛盾する場合は意図的に外す。

### Suno プリセット推奨（suno_preset fallback）

`data/video_analysis/<slug>/*.json` の `suno_preset.genre_line` / `suno_preset.exclude_styles` を
`yt-generate-suno` が fallback として参照する。`config/skills/suno.yaml` の対応キーが空のとき、
全 slug 横断で集約した推奨値を採用する:

- `genre_line`: 各 JSON のスタイル句を多数決し上位 8 句を `, ` 結合
- `exclude_styles`: 全 JSON の和集合（重複排除、出現順保持）

ユーザーが `config/skills/suno.yaml` に override を書いた瞬間にそちらが優先される（後方互換）。
新規チャンネルでも `/video-analyze --source benchmark` を先に回しておけば 1 回目の `/suno` から
近い雰囲気で開始でき、`genre_line` / `exclude_styles` の手調整回数が減らせる。

### 対象テーマ

```
$ARGUMENTS
```

## パターンベース設計

4 パターンで感情・エネルギーの起伏を設計し、各パターンに 1 つの情景フレーズを用意する:

1. **ベンチマーク `bgm_arc` 平均から起伏配置の参考にする**（Instructions 冒頭のサマリーを利用。
   intro / peak / outro の尺配分を 4 パターンに割り当てる初期値として使う）
2. テーマの感情の流れを設計（例: 静寂 → 開放 → 親密 → 動き）
3. 各パターンで 1 つの統合された情景フレーズを用意（複数シーンの要素をマージ）
4. 各パターンに style variant を割り当て

### 生成計画

4 パターン × 3 回生成（1 回 2 曲）= **24 トラック** → ベスト曲を選定。
プロンプト変更は **4 回のみ**（パターン切替時のみ）。

### 曲の長さ（V5）

Suno V5 では Styles 経由で実楽曲長を制御できない（2026-05 時点）。Styles 末尾に長さ指定文字列を入れてもトークンを浪費するだけで効かないため、リポジトリ側ではこの指定を持たない。望む長さに満たない場合は **Suno UI の Extend** で延長する。

- **Style Influence**: `style_influence` で指定（デフォルト 85 推奨）
- **Model**: V5 を使用

> 注意: 構造タグ（`[Intro]`, `[Verse]`, `[Chorus]`, `[Bridge]`, `[Outro]`）は**インストゥルメンタルでは効果なし**だが、
> **ボーカルモードでは Lyrics 欄に必須**（楽曲構成を Suno に伝える）。

## ボーカルモード（歌詞あり楽曲）

`music_engine: suno` かつ `genre_line` にボーカル要素が含まれる場合に適用。

### 歌詞設計ルール

1. **構造タグ必須**: 各歌詞ブロックの先頭に `[Intro]` / `[Verse]` / `[Chorus]` / `[Bridge]` / `[Outro]` のいずれかを置く（Suno が認識）
2. **言語**: `config/skills/suno.yaml` の `lyrics_guidelines.language` に従う
3. **長さ目安**: 4-5 分曲なら **120-180 単語** 程度（Verse 2 + Chorus 2 + Bridge 1 + Outro）
4. **テーマ整合**: 情景フレーズ（scenes）と歌詞の世界観を一致させる
5. **トーン**: `lyrics_guidelines.tone`（例: conversational, narrative, poetic）に従う
6. **韻・リズム**: `lyrics_guidelines.rhyme_style`（loose / strict / natural）に従う
7. **NG**: `lyrics_guidelines.forbidden_topics` に指定された語・テーマは避ける。固有人名もジェネリックな "you / I / we" に置換
8. **gender 整合（サムネ連動）**: サムネ（`10-assets/main.png` / `thumbnail.jpg`）のキャラクター性別と、歌詞の語り手 gender、`genre_line` のボーカル性別（`male vocals` / `female vocals`）の **3 点を一致させる**。サムネで先に決まったキャラ性別に歌詞を従わせる。
   - サムネが**男性モチーフ** → 男性視点の歌詞（男性の語り手・代名詞）+ `genre_line` は `male vocals`
   - サムネが**女性モチーフ** → 女性視点の歌詞（女性の語り手・代名詞）+ `genre_line` は `female vocals`
   - `lyrics_guidelines.vocal_gender` が `male` / `female` なら従う。`""` / `auto` の場合はサムネ（`main.png`）のキャラ性別を確認して決定する
   - 狙い: サムネと歌唱の性別不一致による違和感（没入崩れ・AI 生成バレ）を防ぐ

### 歌詞テンプレ

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

ジャンル別の具体的な歌詞例は `references/lyrics-examples.md` を参照。`lyrics_guidelines.template_reference` で指定した識別子に対応する例を起点にし、チャンネルの `catchphrase` を織り込む。

## 情景フレーズ設計ルール

1. **命令文なし**: `Create a...` で始めない。情景を描写する
2. **簡潔な修飾**: 形容詞は 1-2 個。繰り返し禁止
3. **五感に訴える**: 視覚・触覚・嗅覚など具体的な描写。メロディ・ベース・リズムは書かない
4. **楽器ロール指定**: `Solo Cello` や `Ethereal Choir` でフィーチャー楽器を強調可能（任意）
5. **ベンチマーク `scene_timeline` の活用**: Instructions の「ベンチマーク BGM 構造の参照」で抽出した
   `scene_timeline[].summary`（視覚的に強い瞬間の傾向）を素材として活用する。**そのままコピペしない** —
   自チャンネルの世界観に翻訳してから使う（語彙・トーン・固有名詞は本 skill の禁止形容詞ルールと整合させる）

### 禁止形容詞（情景フレーズ内）

SunoAI をモダン / オーケストラ方向に誘導するため禁止:

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

（`config/skills/suno.yaml` の `exclude_styles` にあらかじめ含めておくと自動付加される）

しっとり感は `misty`, `melancholic`, `nocturnal`, `bittersweet` 等のムード語で表現する。

#### genre_line と exclude_styles の整合性

`exclude_styles` で除外したワードを `genre_line` 側に残すと相殺される。たとえば `exclude_styles` に `vinyl crackle` を含めつつ `genre_line` に `vinyl crackle warmth` のような表現を入れると、Suno には除外したい SE が結局供給されてしまう。`exclude_styles` を更新するときは `genre_line` 側にも同じワードや派生表現が混ざっていないかをセットで確認する。

### 品質基準プロンプト例

ジャンル別の具体例は `references/suno-examples.md` を参照。新規プロンプト作成時は、該当ジャンルの例を基準として確認する。

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
```

#### ボーカルモード（歌詞あり）

```yaml
title: Collection Title Here
mode: vocal  # 省略時は genre_line から自動判定
patterns:
  - name_jp: <日本語パターン名>
    name_en: <English Pattern Name>
    scenes:
      - <情景フレーズ (英語、1 行)>
    lyrics: |
      [Verse 1]
      <4-8 行の情景描写>

      [Chorus]
      <2-4 行のコアフレーズ>

      [Verse 2]
      <4-8 行、視点シフト or 続き>

      [Chorus]
      （繰り返し）

      [Bridge]
      <2-4 行、感情のピーク>

      [Chorus]
      （最後にもう一度）

      [Outro]
      <1-2 行 or instrumental fade>
```

**注意**:
- `style` 指定時は variant の genre_line にテンポが含まれるため、`tempo` は省略可能
- ボーカルモードでは各パターン **1 セット（scenes + lyrics）**。3 回生成で 6 トラック/パターン
- インストモードは各パターン **1 シーン**のみ。3 回生成で 6 曲/パターン

### Step 2: スクリプトで suno-prompts.md を生成

```bash
uv run yt-generate-suno <collection-path>
```

`config/skills/suno.yaml` の `genre_line` + `exclude_styles` + `style_influence` をパターンに自動付加して `suno-prompts.md` を生成する。設定変更時はスクリプト再実行のみで全プロンプトに反映される。

**ボーカルモードの出力**: 各パターンに **Style 欄**（情景フレーズ + genre_line）+ **Lyrics 欄**（歌詞そのまま）の 2 ブロックが書き出される。Suno 側で Custom Mode に入って **Instrumental トグル OFF** にした状態で両方をコピペする。

保存後、`workflow-state.json` の `music.generated = true` に更新する。

### Step 3: workflow-state.json の planning.music を更新

`/alignment-check` がコレクション横断で音楽 mood × サムネ × タイトルの整合を機械的に判定できるよう、`workflow-state.json` の `planning.music` セクションを populate する。新規制作分は必須。

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

**書き方ガイド**:

| フィールド | ソース | 補足 |
|-----------|--------|------|
| `engine` | 固定値 `"suno"` | — |
| `mood` | パターン全体を貫く感情語 1-3 個 | パターン設計の感情の流れから蒸留（例: 静寂 → 開放 → 親密 → 動き なら `["mellow", "warm"]`）|
| `atmosphere` | 全パターンの `scenes` を集約した世界観 1 文（英語） | 個別シーンを羅列せず、コレクション全体の情景を 1 文で言い切る |
| `tempo` | パターンの代表テンポ | enum: `very slow` / `slow` / `gentle` / `moderate` / `lively`（情景フレーズ設計の「テンポ設計」表と同じ語彙）|
| `instruments` | `config/skills/suno.yaml` の `genre_line` + `mood_descriptors` の楽器 + `scenes` の楽器ロール指定（`Solo Cello` 等）| 重複排除し、主役 3-5 個に絞る |
| `exclude` (optional) | `config/skills/suno.yaml` の `exclude_styles` から**楽器系のみ** | `rain sounds` / `vinyl crackle` / `white noise` 等の環境音系は対象外（楽曲楽器ではないため）|

**冪等性**: 既存値があっても `planning.music` 全体を上書きする（merge しない）。スキル再実行 = パターン設計やり直しと見なす。

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
