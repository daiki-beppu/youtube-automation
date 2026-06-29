---
name: suno-lyric
description: "Use when Suno のボーカル曲向けに歌詞を生成したいとき。`/suno` の前工程として、コレクション内の曲ごとに名言やテーマのエッセンスをもとに Suno V5.5 用 Lyrics を作成し、`20-documentation/suno-lyrics.md` と `20-documentation/suno-lyrics.json` を出力する。歌詞あり、vocal、singing、rap、male/female vocals、suno-lyric、歌詞生成、名言ベース歌詞、曲ごとの歌詞作成に関わる場面で使用すること。Style / genre_line / Suno UI 投入は `/suno` と `/suno-helper` の責務"
---

## Overview

`/suno-lyric` は Suno ボーカル曲の **Lyrics 専任**。`/suno` は orchestration + Style / title / scene / JSON merge を担当し、本 skill は歌詞本文だけを作る。

```
/suno-lyric  ->  20-documentation/suno-lyrics.{md,json}
                       |
/suno        ->  20-documentation/suno-prompts.{md,json}
                       |
/suno-helper ->  Suno UI
```

## Responsibilities

- 曲ごとの title / scene / mood を読み、1 曲 1 歌詞を作る
- 必要に応じて名言やテーマのエッセンスを抽出し、原文を直接コピーせず歌詞へ再構築する
- Suno V5.5 が読みやすい section tag 付き Lyrics を出力する
- レビュー用 Markdown と `/suno` が機械的にマージできる JSON を出力する

この skill は Style、genre_line、Exclude Styles、Suno More Options、Suno UI 操作を扱わない。

## Inputs

対象 collection は `$ARGUMENTS`、または現在の collection directory とする。

読むもの:

- `20-documentation/suno-patterns.yaml`: 曲名、scene、mood tag
- `workflow-state.json::planning.music`: mood / atmosphere / tempo / instruments
- `config/skills/suno.yaml::genre_line`: ボーカルモード判定
- `config/skills/suno-lyric.yaml`: 任意のチャンネル上書き
- `docs/audience-persona.md`: あれば persona vocabulary と避ける語彙

## Quote Source Safety

名言取得元は `https://iyashitour.com` に限定する。`config/skills/suno-lyric.yaml::source.base_url` を上書きする場合も、scheme は `https`、host は `iyashitour.com` のみ許可する。`localhost`、private / link-local IP、IP literal、別 host、`..` を含む path、`/meigen/` 以外の path は停止する。別サイトを使う場合は自動取得せず、人間が取得済み引用メモを渡してから続行する。

## Hiragana Lyrics Guide

`config/skills/suno-lyric.yaml::lyric.language: ja` の場合、歌詞は**ひらがなで書く**。Suno は漢字の読みを頻繁に誤るため、ひらがな表記で発音精度を確保する。カタカナは外来語にのみ使用可。

## Hard Gates

1. `music_engine` が `suno` でない場合は停止する
2. `genre_line` または `suno-patterns.yaml::mode` がボーカルを示さない場合は、歌詞生成不要として停止する
3. `20-documentation/suno-patterns.yaml` が無い場合は停止し、先に `/suno` の pattern draft を作るよう案内する
4. `workflow-state.json::planning.music` が空でも完全停止はしないが、曲ごとの scene と persona reference を優先して進める

## References

必要になった時だけ読む:

- 詳細な section 構造と例: `references/lyric-templates.md`
- 名言カテゴリと persona affinity: `references/persona-quote-affinity.md`

## Workflow

1. `suno-patterns.yaml` から最終 entry name を作る。`/suno` と同じく `{name_jp} — {name_en}`、複数 scene の場合は ` (Variation N)` を付ける
2. 各 entry に mood tag を割り当てる。明示 `mood` が無ければ scene / title / planning.music から推定する
3. `config/skills/suno-lyric.yaml::affinity_weights` と persona reference から、曲ごとに名言カテゴリまたは偉人候補を選ぶ
4. 名言を使う場合は、英語原文をそのまま歌詞にしない。中核メッセージを 1 文の essence に抽出してから、曲の scene と persona vocabulary に合わせて再構築する
5. Lyrics は V5.5 向けに section tags を明示する。基本形は `[Intro]`, `[Verse 1]`, `[Pre-Chorus]`, `[Chorus]`, `[Verse 2]`, `[Instrumental]`, `[Bridge]`, `[Final Chorus]`, `[Extended Outro]`
6. `suno-lyrics.md` と `suno-lyrics.json` を `20-documentation/` に出力する。`preserve_existing: true` の場合、既存 entry は上書きしない
7. 出力後、`/suno` に戻って Style と Lyrics をマージする

## Output Contract

### `20-documentation/suno-lyrics.json`

JSON root は配列。各 entry は `/suno` が `name` でマージできる形にする:

```json
[
  {
    "name": "夜明けの記憶 — Dawn Memory",
    "lyrics": "[Intro]\n...\n\n[Verse 1]\n...",
    "style": null
  }
]
```

- `name` は `/suno` の最終 prompt entry name と完全一致させる
- `lyrics` は Suno Lyrics 欄へ入れる歌詞。言語は `config/skills/suno-lyric.yaml::lyric.language` に従う
- `style` は `null` のままにする。Style は `/suno` が埋める

### `20-documentation/suno-lyrics.md`

人間レビュー用。各曲ごとに以下を残す:

- entry name
- mood / persona target
- 使用した名言または essence
- Lyrics (`config/skills/suno-lyric.yaml::lyric.language` に従う)
- Lyrics (Japanese / 意訳) は任意。ただし生成した場合は Suno UI には投入しない

## Validation

生成後に確認する:

- `suno-lyrics.json` の各 `name` が `suno-patterns.yaml` 由来の entry name と一致する
- 歌詞に Style 指示、genre_line、Suno UI 操作説明を混ぜない
- 名言原文と連続 5 語以上一致させない
- `config.lyric.vocab_constraints.avoid` の語を避ける
- section tag が欠けていない
- CTA を入れる場合は `config.cta.positions` の対象曲だけに入れる

## Next Step

完了後は `/suno` を実行する。`/suno` は `suno-lyrics.json` を優先して読み、Style と Lyrics を `suno-prompts.json` にマージする。
