# Suno ボーカルモード歌詞例（参考資料）

ボーカル楽曲（`music_engine: suno` + `suno.genre_line` にボーカル要素）の歌詞設計の参考例。
**これは例示のみ** — 各チャンネルの `config/skills/suno.yaml` の `lyrics_guidelines` に従って調整すること。

## 共通設計ルール

1. **構造タグ必須**: `[Intro]` / `[Verse]` / `[Chorus]` / `[Bridge]` / `[Outro]`（Suno が認識）
2. **長さ目安**: 4-5 分曲なら **120-180 単語**（Verse 2 + Chorus 2 + Bridge 1 + Outro）
3. **テーマ整合**: 情景フレーズ（scenes）と歌詞の世界観を一致させる
4. **NG**: explicit 表現、攻撃的な語、政治・宗教、商品名、固有人名

## 歌詞テンプレート（汎用）

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

## 例 1: jazzhop / laid-back rap

**トーン**: conversational、叫ばない、誇張しない
**韻**: lazy flow に乗る緩い韻。完璧さよりナチュラル感優先

```
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

**成功要因**:
- 視覚描写（tail lights, wet asphalt）+ 聴覚（bassline）+ 体感（windows down）のバランス
- "Mind off, groove on" などチャンネルキャッチコピーを歌詞に組み込み
- Chorus は短く、繰り返しやすく、覚えやすい

## 例 2: acoustic folk（参考）

**トーン**: storytelling、narrative、温かみ
**韻**: natural な脚韻、完全韻で構わない

```
[Verse 1]
Walking down the old stone road where the willow bends low
Carrying my grandmother's lantern, wherever the wind goes
Fields remember every footstep left behind
Stars remember every wish I've made on borrowed time

[Chorus]
Carry me, carry me, down the winding way
Carry me home before the end of day
```

## 歌詞ガイドライン（config/skills/suno.yaml で定義）

各チャンネルの `lyrics_guidelines` で以下を指定する想定:

```yaml
lyrics_guidelines:
  tone: "conversational, laid-back, intimate"
  perspective: "first-person or second-person"
  rhyme_style: "loose, natural flow"
  language: en
  catchphrase: "Mind off, groove on"
  style_reference:
    - |
      [Verse]
      a kettle hums under the hallway light
      your shoes by the door, still leaning right
      we leave the big words on the shelf
      and let the quiet speak for itself
  forbidden_topics:
    - politics
    - religion
    - explicit
  template_reference: jazzhop
lyrics_generation:
  provider: claude
```

`template_reference` は `references/lyrics-examples.md`（このファイル）内のどの例をベースにするかの識別子。
