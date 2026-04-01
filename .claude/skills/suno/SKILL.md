---
name: suno
description: Use when コレクションのテーマが確定し、SunoAI用の音楽プロンプト生成が必要なとき。音楽制作、プロンプト作成、SunoAI、曲を作る、BGM制作など、音楽プロンプト生成に関わる場面で必ず使用すること
---

## Overview

コレクション用の SunoAI v5 インストゥルメンタル音楽プロンプトのパターン定義（YAML）を作成し、スクリプトで最終プロンプトを生成する。

AI の役割は **情景フレーズ（scenes）とテンポ（tempo）の設計** に集中すること。genre_line や共通設定はスクリプトが `channel_config.json` から自動付加する。

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

> 注意: 構造タグ（[Intro], [Verse] 等）はインストゥルメンタルでは効果なし。
> Extend は最終手段として使えるが、Styles での時間指定を優先する。

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

`20-documentation/suno-patterns.yaml` に保存。**scenes と tempo** を記述する。`style_variants` がある場合は `style` キーで variant を指定可能:

```yaml
title: Collection Title Here
patterns:
  # 4パターン、各1シーン（複数要素をマージした統合フレーズ）
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

**注意**: `style` 指定時は variant の genre_line にテンポが含まれるため、`tempo` は省略可能。各パターン1シーンのみ。3回生成で6曲/パターン。

### Step 2: スクリプトで suno-prompts.md を生成

```bash
python3 automation/generate_suno_prompts.py <collection-path>
```

`channel_config.json` の `suno.genre_line` + `suno.mood_descriptors` をパターンに自動付加して `suno-prompts.md` を生成。設定変更時はスクリプト再実行のみで全プロンプトに反映される。

保存後、`workflow-state.json` の `music.generated = true` に更新する。

## Next Step

→ SunoAI にプロンプトを手動投入して楽曲生成
→ ダウンロード対象のプレイリストを作成
→ `/masterup <playlist-url>` でダウンロード + マスター音源生成
