---
name: suno
description: "Use when Suno UI に投入する音楽プロンプト (Style + Lyrics) を生成したいとき。SunoAI V5 向けの YAML 定義（インストは `tracks_per_collection` で曲数指定の独立 entry 並列、ボーカルは pattern × tracks_per_pattern 設計）から suno-prompts.md / suno-prompts.json を作成する（次工程 `/suno-helper` でブラウザ自動生成 + playlist 一括追加、その後 `/masterup` で DL + マスター化）。プロンプト作成・Style 文・Lyrics テンプレートなど Suno 連続生成の前段で使用すること。Lyria チャンネルでは /lyria を使う"
---

## Overview

コレクション用の SunoAI v5 音楽プロンプトを YAML で定義し、スクリプトで最終プロンプトを生成する。**インストゥルメンタル / ボーカル（歌詞あり）両モード対応**。

- **インストモード**: 曲数 (`tracks_per_collection`) を指定し、ceil(N/2) 個の独立 entry をフラットに並べる（pattern 概念は廃止）。`/suno-helper` が各 entry を Suno に順次投入し、Suno 仕様で 1 Generate = 2 clip 生成されるため両 clip 採用で N clip となる
- **ボーカルモード**: 従来どおりパターン (`pattern_strategy: mixed/single`) × 再生成 (`tracks_per_pattern`) で構成し、ベスト曲を選曲する運用（歌唱の発音・ピッチ精度のため）

## いつ使うか（選択タイミング）

音楽エンジンの選択は以下の階層で決まる:

1. **チャンネルのデフォルト** — `/channel-direction` で suno/lyria を検討 → `/channel-setup` が `config/channel/youtube.json` の `music_engine` に書き込む
2. **コレクション単位の上書き** — `/wf-new` の `yt-init-collection --music-engine suno` でコレクション毎に上書き可能（省略時はチャンネル設定を継承）
3. **このスキルが呼ばれるとき** — `/wf-new` が `workflow-state.json` の `music_engine = "suno"` を判定して `/suno` を自動実行する。手動で `/suno <theme>` を叩いた場合もこのスキルに入る

AI の役割は **情景フレーズ（scenes）+ テンポ（tempo）+ 歌詞（lyrics、ボーカルモード時）の設計** に集中すること。`genre_line` や共通設定はスクリプトが `config/skills/suno.yaml` から自動付加する。

### モード判定

`config/skills/suno.yaml` の `genre_line` を読み取り、**ボーカル要素**（`vocals`, `vocal`, `singing`, `rap`, `male/female vocals` 等）が含まれていれば**ボーカルモード**、なければ**インストゥルメンタルモード**として処理する。

| モード | YAML 構造 | 歌詞 | Suno 設定 |
|---|---|---|---|
| インストゥルメンタル | `tracks_per_collection` 由来の `ceil(N/2)` 個の独立 entry（各 entry = 1 scene = 1 Generate = 2 clip 両採用） | 不要 | Custom Mode + **Instrumental ON** |
| ボーカル（歌詞あり） | `pattern_strategy` × `tracks_per_pattern` の旧パターン設計（情景フレーズ + 歌詞をパターン単位） | 必須（パターンごと） | Custom Mode + **Instrumental OFF** + Lyrics 欄に投入 |

### スタイルバリアント（A/B テスト対応）

`config/skills/suno.yaml` に `style_variants` が定義されている場合、各 entry（インスト）またはパターン（ボーカル）に `style` キーで variant を指定できる。variant が指定されているときはデフォルトの `genre_line` の代わりに variant 固有の `genre_line` が使われる。

**戦略選択**（`style_strategy` を参照）:

| 戦略 | 説明 | YAML での指定方法 |
|------|------|------------------|
| `mixed` | 1 コレクション内で複数の variant を混合 | 各 entry / パターンに異なる `style: A`〜`E` を割り当て |
| `single` | 1 コレクション = 1 variant で統一 | 全 entry / パターンに同じ `style: X` を割り当て |

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

設計に入る前に、`config/channel/analytics.json` の `benchmark.channels[].slug` を列挙し、
各 slug について `data/video_analysis/<slug>/*.json`（`/video-analyze` の出力）が存在するか確認する。

- **存在する場合**: `bgm_arc.intro` / `bgm_arc.peak` / `bgm_arc.outro` / `bgm_arc.energy_curve` を
  読み込み、slug ごとに intro 秒・peak 秒・outro 開始秒の平均と代表的な `energy_curve` パターンを
  抽出する。
  - **インストモード**: `ceil(tracks_per_collection / 2)` 個の entry をテーマ世界の中で散らす際の
    バリエーション設計（朝寄り / 夕方寄り / 雨上がり / 室内など）の素材として使う。entry 間で似た
    情景に寄りすぎないよう、benchmark の `scene_timeline[].summary` から多様な視覚モチーフを引く。
  - **ボーカルモード**: 従来どおり `patterns_per_collection` 個の起伏配置（例: 4 パターン運用なら
    パターン 1 を intro 寄り、パターン 3 を peak 寄り。1 パターン運用なら intro→peak→outro を 1 つの
    情景フレーズに内包させる）の参考にする。`scene_timeline[].summary` は情景フレーズ設計（後述）の
    素材として使う。
- **`data/video_analysis/<slug>/*.json` 不在 + `data/benchmark_*.json` も不在**: ユーザーに
  「`/benchmark` を先行実行してください」と案内し、本サブセクションはスキップして警告のみで続行。
- **`data/benchmark_*.json` は存在するが分析未実行**: `AskUserQuestion` で
  `uv run yt-video-analyze --source benchmark --channel <slug> --top 5` の自動実行を提案。承認時のみ実行。
  `genre_line` が**空のとき**は拒否すると「前提条件チェック（hard gate）」を満たせないため中断する
  （AI が手書き fallback で続行することは禁止）。`genre_line` が埋まっているときに限り、拒否時は
  起伏配置の参考情報が無い旨を警告して続行できる。
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

> **方向性は必ずスクリプト由来とする（AI 手書き禁止）**: `genre_line` 空 + `suno_preset` fallback も
> 取れない状態（= `data/video_analysis/<slug>/*.json` が全 slug で不在）で本 skill が AI 推定の
> `genre_line` を本文中・YAML・suno-prompts.md のいずれにも書き起こすことは禁止する。前提条件
> チェック（hard gate）で中断し、`yt-video-analyze` を回してもらってから再実行する。

### 対象テーマ

```
$ARGUMENTS
```

## 曲数ベース設計（インストモード）

**インストモードは pattern 概念を廃止し、`tracks_per_collection` で指定した曲数から
`ceil(N/2)` 個の独立 entry をフラットに並べる**。Suno は 1 Generate = 2 clip 生成するため、
両 clip を採用すれば最終 clip 数が `tracks_per_collection` になる（選曲しない）。各 entry は
他 entry と独立した情景・スタイルで設計し、A〜D の感情起伏や同一プロンプトの再生成は使わない。

参照すべきキー:

| キー | 役割 | 既定 |
|---|---|---|
| `tracks_per_collection` (config) | 1 コレクションあたりの最終 clip 数 | `20` |
| `tracks` (yaml top-level) | コレクション単位の上書き（省略時は config の値） | （省略） |
| `style_strategy` | `mixed` (entry ごとに variant 混合) / `single` (全 entry 共通) | `single` |
| `style_variants` | variant 名と genre_line の対応辞書 | `{}` |

### 手順

1. **ベンチマーク `bgm_arc` 平均と `scene_timeline[].summary` から多様な情景の素材を集める**（同じテーマ
   世界の中で entry 間に色味の差を付ける材料）
2. **曲数を確定する**: `config/skills/suno.yaml::tracks_per_collection` を読み、コレクション単位で
   変えたい場合のみ `suno-patterns.yaml` の top-level `tracks:` キーで上書きする
3. **`ceil(tracks / 2)` 個の entry を設計する**: 各 entry は固有の `name_jp` / `name_en` / `scenes` (1 行)
   / `tempo` を持つ。**`name_jp` / `name_en` の組（= Suno UI Song Title 欄に注入される `entry.name`）は
   全 entry でユニーク必須** (重複すると Library / playlist / `/masterup` のリネーム時に衝突する)。
   entry 間で情景が被らないよう、視点・時刻・場所・季節などを散らす
4. **style variant を割り当てる**: `style_strategy: single` なら全 entry 同じ variant、`mixed` なら
   entry ごとに variant を切り替える（例: A:lo-fi / B:ambient / C:piano / D:nature）
5. **`yt-generate-suno` 実行で検証**: 以下のいずれかに違反すると fail-loud で停止する。
   - entry 数が `ceil(tracks / 2)` と一致しない
   - `entry.name`（= `{name_jp} — {name_en}`）が他 entry と重複している

### 生成計画（インストモード）

| `tracks_per_collection` | 必要 entry 数 (= ceil(N/2)) | 最終 clip 数 | プロンプト切替回数 |
|---|---|---|---|
| 20（既定） | 10 | 20 | 10 |
| 16 | 8 | 16 | 8 |
| 24 | 12 | 24 | 12 |

`/suno-helper` が各 entry を順次注入し、各 entry の `(Generate) → 2 clip 生成完了 → 次 entry` を
自動的に回す。完了後は 2 clip を選曲せず両方 playlist へ加わる。

## パターンベース設計（ボーカルモード）

**ボーカルモードのみ、従来どおりパターン × 再生成回数で設計する**（歌唱の発音・ピッチが不安定な
ため、1 prompt から 2 clip 生成してベスト曲を選曲する運用を維持）。

参照すべきキー:

| キー | 役割 | 既定 |
|---|---|---|
| `pattern_strategy` | パターン運用の戦略名 (`mixed` / `single`) | `mixed` |
| `tracks_per_pattern` | 1 パターンあたりの Suno 再生成回数 (1 回 = 2 曲) | `3` |
| `pattern_strategy_note` | AI への運用補足 (任意の自由記述) | `""` |

### 共通手順

1. **ベンチマーク `bgm_arc` 平均から起伏配置の参考にする**（Instructions 冒頭のサマリーを利用）
2. テーマの感情の流れを設計し、パターン数（典型 4）に分割する
3. 各パターンで 1 つの統合された情景フレーズと歌詞を用意（複数シーンの要素をマージ）
4. 各パターンに style variant を割り当て

### `pattern_strategy: single` の場合

複数シーンに分けず **1 つの統合された情景フレーズ** にまとめ、同一プロンプトを
`tracks_per_pattern` 回（既定 3 回、1 回 2 曲）生成する運用に切り替える。

- パターン分割（A 〜 D の感情の起伏）は行わない。代わりにテーマ全体を 1 つの世界観に蒸留する
- `suno-patterns.yaml` には **パターン 1 件だけ** を書き出し、style variant も全曲共通にする
- `pattern_strategy_note` に補足が書かれていればそれを情景フレーズ設計に反映する
- 生成計画: **1 パターン × `tracks_per_pattern` 回 × 2 曲 = `tracks_per_pattern * 2` トラック**

### `pattern_strategy: mixed` の場合

従来の起伏設計（感情・エネルギーの推移）を N 個のパターンに分割する運用。デフォルトの
`N=4`（静寂 → 開放 → 親密 → 動き）が典型例。`tracks_per_pattern` 回ずつ生成しベスト曲を選定する。

### 生成計画（ボーカルモード）

総トラック数 = `パターン数 × tracks_per_pattern × 2`（Suno は 1 リクエスト = 2 曲）。
プロンプト変更は **パターン数回のみ**（パターン切替時のみ）。

| パターン数 | `tracks_per_pattern` | 総トラック | プロンプト切替回数 |
|---|---|---|---|
| 1 (single) | 3 | 6 | 1 |
| 4 (mixed, 典型) | 3 | 24 | 4 |

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

### 英語歌詞のネイティブ感ガード

`lyrics_guidelines.language: en` の場合は、文法の正しさよりも「自然な話し言葉の積み上げ」を優先する。

- 観察日記のように、目の前の小さな動作・光・温度から始める
- ABCB などの loose rhyme を使い、語尾を揃えすぎない
- Chorus は説明文ではなく、短い mantra として繰り返せる言葉にする
- 意味が反転しやすい語を使わない。例: `downfall` は「美しい終わり」ではなく失墜・転落を連想させるため避ける
- 抽象語だけで感情を説明せず、生活の細部から感情を出す

### style_reference

`config/skills/suno.yaml` の `lyrics_guidelines.style_reference` に参考歌詞を登録できる。これは文体参照専用で、歌詞本文・固有表現・印象的なフレーズを copy / verbatim / そのままコピペしてはいけない。

```yaml
lyrics_guidelines:
  style_reference:
    - |
      [Verse]
      <参考にしたい英語歌詞>
```

使うときは、参照歌詞から以下だけを抽出して新規歌詞へ反映する:

- 1 行あたりの長さ
- 視点（一人称 / 二人称 / 観察者）
- loose rhyme の密度
- Chorus の mantra 感
- 情景描写から感情へ移る順序

### Codex 経由の歌詞初稿生成

`config/skills/suno.yaml` の `lyrics_generation.provider` で歌詞初稿の生成経路を切り替えられる。

| provider | 生成経路 |
|---|---|
| `claude` | 通常の `/suno` skill 実行内で歌詞を作る |
| `codex` | `.claude/skills/suno/references/codex-lyrics.sh` で Codex CLI に歌詞下書きを委譲する |

`codex` を使う場合は ChatGPT API を直叩きしない。追加 API key を持たず、ChatGPT ログイン済みの Codex CLI を使う。事前に以下でログイン状態を確認する:

```bash
codex login status
```

プロンプトファイルを用意し、出力先を wrapper の第 2 引数として明示して直接実行する:

```bash
bash .claude/skills/suno/references/codex-lyrics.sh \
  20-documentation/codex-lyrics-prompt.md \
  20-documentation/codex-lyrics.md
```

プロンプトにはテーマ、各 pattern の `scenes`、`lyrics_guidelines`、`lyrics_guidelines.style_reference` を含める。Codex から返った `codex-lyrics.md` を確認し、意味反転語（例: `downfall`）が混入していないこと、観察日記風・loose rhyme・mantra 的 Chorus が成立していることを確認してから `suno-patterns.yaml` の `lyrics` に貼り込む。

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

### Step 1: 定義を YAML で保存

`20-documentation/suno-patterns.yaml` に保存。**scenes + tempo（インスト時）** または **scenes + lyrics（ボーカル時）** を記述する。`style_variants` がある場合は `style` キーで variant を指定可能。

#### インストゥルメンタルモード

`tracks` (省略時は config の `tracks_per_collection`) から導出した `ceil(N/2)` 個の独立 entry を
`patterns:` 配列に並べる。各 entry は 1 scene = 1 Generate = 2 clip 採用。

```yaml
title: Collection Title Here
mode: instrumental  # 省略時は genre_line から自動判定
tracks: 20  # 省略時は config/skills/suno.yaml::tracks_per_collection (既定 20) が効く
patterns:  # ceil(tracks/2) = 10 entry を並べる。entry 間で情景は被らせない
  - name_jp: 屋上の静寂
    name_en: Rooftop Silence
    style: C
    tempo: slow
    scenes:
      - a heavy door propped open with a brick, cool night air rising through a dim stairwell, the last stars fading above an antenna array
  - name_jp: 朝のキッチン
    name_en: Morning Kitchen
    style: A
    tempo: gentle
    scenes:
      - steam rising from a kettle by a cracked window, soft sunlight on a wooden cutting board, a single cup waiting on the counter
  # ... 残り 8 entry を同様に並べる
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
- インストモードは各 entry **1 シーン**のみ。1 entry = 1 Generate = 2 clip 採用（選曲しない）
- インストモードで `len(patterns)` が `ceil(tracks / 2)` と一致しないと `yt-generate-suno` が fail-loud で停止する
- **全 entry の `name_jp` / `name_en` の組はユニーク必須**。重複していると `yt-generate-suno` が fail-loud で停止する
  （Suno Library / playlist 識別 / `/masterup` リネーム衝突を防ぐため、両モード共通の制約）
- ボーカルモードでは各パターン **1 セット（scenes + lyrics）**。`tracks_per_pattern` 回生成で
  `tracks_per_pattern * 2` トラック/パターン（既定 3 回 = 6 トラック）。`pattern_strategy: single` の
  場合、`patterns:` 配列は **1 要素だけ** にする（A 〜 D を並べない）

### Step 2: スクリプトで suno-prompts.md を生成

```bash
uv run yt-generate-suno <collection-path>
```

`config/skills/suno.yaml` の `genre_line` + `exclude_styles` + `style_influence` をパターンに自動付加して `suno-prompts.md` を生成する。設定変更時はスクリプト再実行のみで全プロンプトに反映される。

`suno-prompts.md` と同じ `20-documentation/` ディレクトリに、各パターンの `{ name, style, lyrics }` を配列化した **`suno-prompts.json`** も併出される。これは Step 3 の Chrome 拡張（`yt-collection-serve` 経由）が fetch する配信元で、`suno-prompts.md` の Style 行と同一内容から生成されるため両者はドリフトしない。

**ボーカルモードの出力**: 各パターンに **Style 欄**（情景フレーズ + genre_line）+ **Lyrics 欄**（歌詞そのまま）の 2 ブロックが書き出される。Suno 側で Custom Mode に入って **Instrumental トグル OFF** にした状態で両方を投入する（Step 3 の自動投入、または fallback の手コピペ）。

保存後、`workflow-state.json` の `music.generated = true` に更新する。

### Step 3: `/suno-helper` で自動投入（推奨）

`suno-prompts.json` を Chrome 拡張（`extensions/suno-helper/`）が読み取り、Suno Custom Mode の Style/Lyrics 両フィールドへ順次注入 → Generate 押下 → 生成完了検知 → 次パターン、を連続実行する。手コピペ（4 パターン × 3 回 ≒ 12 サイクル）を自動化する経路。

> ヘッドレス／DevTools 経由ではなく **既ログイン状態の本物の Chrome セッション** 上で動かすため、reCAPTCHA を踏みにくく、DOM 操作は固定実装でトークン消費ゼロ、ネイティブイベント発火で React に即時反映される。

**手順**:

1. **拡張をビルドしてロード**（初回のみ）: `extensions/suno-helper/` で `pnpm install && pnpm build` を実行 → Chrome で `chrome://extensions` → デベロッパーモード ON → 「パッケージ化されていない拡張機能を読み込む」で `extensions/suno-helper/.output/chrome-mv3/` を選択。詳細は `extensions/README.md`。
2. **サーバー起動**: ターミナルで `suno-prompts.json` を localhost に配信する。`Ctrl-C` で停止できるフォアグラウンドプロセス。
   ```bash
   uv run yt-collection-serve collections/planning/<theme>
   # → http://localhost:7873/suno/prompts.json で配信（CORS はデフォルトで chrome-extension:// と suno.com 系 web origin を許可。#896）
   ```
   コレクションディレクトリの代わりに `suno-prompts.json` のパスを直接渡してもよい。ポートを変える場合は `--port <PORT>`。
3. **Suno を開く**: Chrome で Suno の **Custom Mode** 画面を開く（ボーカルモードは **Instrumental トグル OFF**）。
4. **取得 → 連続実行**: 拡張ポップアップでサーバー URL（既定 `http://localhost:7873`）を入れて **データ取得** → パターン一覧を確認 → **全パターンを連続実行**。
5. **停止と継続** (#948): captcha challenge は waiting-captcha 表示で解消（多くは自動 verify）を待って自動続行する。entry 単位の一時的な失敗は preset 連動で自動リトライし、上限超過分は **スキップして完走** する。スキップされた entry はポップアップに一覧表示され、**失敗分のみ再実行** ボタンで再投入できる（失敗ゼロで完走したときに playlist 追加が実行される）。run 全体が停止するのは致命的なケース（注入先セレクタ不在 / captcha の手動解決が 10 分超 / 生成キューが 10 分間無変化）のみで、その場合は再開バナーから続きを再開できる。

### Step 3 の fallback: 拡張が使えない／壊れたときの手コピペ

拡張をロードできない、Suno の UI 変更で注入先セレクタが外れた（`extensions/shared/dom.ts` の `SELECTORS` 保守が必要）、その他自動投入が機能しない場合は、従来どおり **`suno-prompts.md` を見ながら手コピペ** に切り替える:

1. `suno-prompts.md` を開く。
2. Suno の Custom Mode に入り、ボーカルモードは **Instrumental トグル OFF**。
3. パターンごとに **Style 欄** と **Lyrics 欄** を貼り付け、**Generate** を押す。これを全パターン分繰り返す。

自動・手動どちらの経路でも投入内容は同一（`suno-prompts.md` と `suno-prompts.json` は同一の中間表現から生成）。

### Step 4: workflow-state.json の planning.music を更新

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
| `mood` | コレクション全体を貫く感情語 1-3 個 | インストは全 entry の `scenes` を、ボーカルは全パターンの感情の流れを蒸留（例: `["mellow", "warm"]`）|
| `atmosphere` | 全 entry / パターンの `scenes` を集約した世界観 1 文（英語） | 個別シーンを羅列せず、コレクション全体の情景を 1 文で言い切る |
| `tempo` | 代表テンポ | enum: `very slow` / `slow` / `gentle` / `moderate` / `lively`（情景フレーズ設計の「テンポ設計」表と同じ語彙）|
| `instruments` | `config/skills/suno.yaml` の `genre_line` + `mood_descriptors` の楽器 + `scenes` の楽器ロール指定（`Solo Cello` 等）| 重複排除し、主役 3-5 個に絞る |
| `exclude` (optional) | `config/skills/suno.yaml` の `exclude_styles` から**楽器系のみ** | `rain sounds` / `vinyl crackle` / `white noise` 等の環境音系は対象外（楽曲楽器ではないため）|

**冪等性**: 既存値があっても `planning.music` 全体を上書きする（merge しない）。スキル再実行 = 設計やり直しと見なす。

## オーディオビジュアライザー / オーバーレイ

`/suno` は**Suno UI に投入するプロンプト（Style + Lyrics）を生成する工程**で、映像オーバーレイ（ビジュアライザー・波形・購読ボタンポップアップ等）は扱わない。
ユーザーから「ビジュアライザー付きで」「波形を出して」等の指示があっても、`/suno` 段階・`/masterup` 段階のいずれでも何も合成できない。

ビジュアライザー周りの現状と制約は `videoup` SKILL.md の「オーディオビジュアライザー / オーバーレイについて」節を参照（#511 で feature 化中・現状未実装）。
誤指示の事故防止のため、suno 着手前に動画にオーバーレイが必要かをユーザーへ確認すること（#646 feedback）。

## 障害時ガイダンス

本スキル自体は外部 API を呼ばない（生成プロンプトを作るだけ）。実際の楽曲生成は `/suno-helper` で自動投入、またはその fallback として手コピペで行う。

| 状況 | 兆候 | 対処 |
|---|---|---|
| Suno UI / CDN 障害 | Suno 側でエラー・生成が進まない | 本スキルの責務外（楽曲生成は `/suno-helper`）。[Suno 公式サイト](https://suno.com)・公式 SNS で障害情報を確認し、時間を置いて UI で再試行。DL/マスター化は `/masterup` 側の障害ガイダンスに従う |

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
- サーバー CLI: `src/youtube_automation/scripts/collection_serve.py`
