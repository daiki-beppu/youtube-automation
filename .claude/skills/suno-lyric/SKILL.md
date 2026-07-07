---
name: suno-lyric
description: "Use when Suno ボーカル曲の歌詞を生成するとき。「歌詞生成」「vocal」「rap」「suno-lyric」で発動。/suno の前工程。Style / UI 投入は /suno と /suno-helper の責務"
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

## 設定読み込みゲート

Inputs の確認に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/suno-lyric/config.default.yaml`
2. `config/skills/suno-lyric.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("suno-lyric")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。このスキルが `/suno` の skill-config を直接参照する段階では、`suno` 側の `config.default.yaml` と `config/skills/suno.yaml` も同じ手順で読む。

## Inputs

対象 collection は `$ARGUMENTS`、または現在の collection directory とする。

読むもの:

- `20-documentation/suno-patterns.yaml`: 曲名、scene、mood tag
- `workflow-state.json::planning.music`: mood / atmosphere / tempo / instruments
- `config/skills/suno.yaml::genre_line`: ボーカルモード判定
- `config/skills/suno-lyric.yaml`: 任意のチャンネル上書き
- `docs/channel/personas/persona-definition.md`: persona vocabulary と避ける語彙。無い場合のみ旧 `docs/audience-persona.md` を legacy fallback として参照可

## Quote Source Safety

名言取得元は `https://iyashitour.com` に限定する。`config/skills/suno-lyric.yaml::source.base_url` を上書きする場合も、scheme は `https`、host は `iyashitour.com` のみ許可する。`localhost`、private / link-local IP、IP literal、別 host、`..` を含む path、`/meigen/` 以外の path は停止する。別サイトを使う場合は自動取得せず、人間が取得済み引用メモを渡してから続行する。

## Hiragana Lyrics Guide

`config/skills/suno-lyric.yaml::lyric.language: ja` の場合、歌詞は**ひらがなで書く**。Suno は漢字の読みを頻繁に誤るため、ひらがな表記で発音精度を確保する。カタカナは外来語にのみ使用可。

## Hard Gates

1. `music_engine` が `suno` でない場合は停止する
2. `genre_line` または `suno-patterns.yaml::mode` がボーカルを示さない場合は、歌詞生成不要として停止する
3. `20-documentation/suno-patterns.yaml` が無い場合は停止し、先に `/suno` の pattern draft を作るよう案内する
4. `workflow-state.json::planning.music` が空でも完全停止はしないが、曲ごとの scene と persona reference を優先して進める

## Generator-Reviewer Quality Gate

歌詞本文の作成は generator に委譲し、品質検証は生成とは別コンテキストの reviewer が行う。Claude Code では subagent 起動として扱い、Codex では同等の別エージェント / 別コンテキスト実行に読み替える。

generator は `suno-patterns.yaml`、persona reference、設定、必要な References を読んで `20-documentation/suno-lyrics.md` と `20-documentation/suno-lyrics.json` を作る。reviewer は生成時のメモや会話を読まず、成果物 `20-documentation/suno-lyrics.json` と `references/review-rubric.md` のみを読んで検証する。

`suno-lyrics.json` は reviewer が JSON だけでテーマ適合性を判定できるよう、各 entry に reviewer-only の `review_context` を必ず含める。`review_context` が欠落している entry は reviewer が外部資料で補わず `FAIL` とし、generator に再生成させる。

検証順序は必ず直列にする:

1. `yt-suno-verify <collection>` を実行し、曲数・entry name・section tag・文字数などの機械的検証が exit 0 で通過したことを確認する
2. その後に reviewer が `references/review-rubric.md` に従って LLM semantic review を実行する
3. reviewer は entry ごとに `PASS` / `FAIL` と理由を出す
4. `FAIL` entry のみ generator に再生成させ、`yt-suno-verify` → LLM semantic review を再実行する
5. 再生成ループは最大 2 周。2 周後も `FAIL` が残る場合は完了扱いにせず、残課題（entry name、FAIL 理由、次に直す観点）をユーザーに提示して引き継ぐ

## References

必要になった時だけ読む:

- 詳細な section 構造と例: `references/lyric-templates.md`
- 名言カテゴリと persona affinity: `references/persona-quote-affinity.md`
- 曲間セクション重複の機械チェック: `references/check_lyric_duplication.py`
- generator-reviewer 分離の意味的品質検証ルーブリック: `references/review-rubric.md`

## Workflow

1. 歌詞生成を generator subagent（Codex では別コンテキスト実行）に委譲する
2. `suno-patterns.yaml` から最終 entry name を作る。`/suno` と同じく `{name_jp} — {name_en}`、複数 scene の場合は ` (Variation N)` を付ける
3. 各 entry に mood tag を割り当てる。明示 `mood` が無ければ scene / title / planning.music から推定する
4. `config/skills/suno-lyric.yaml::affinity_weights` と persona reference から、曲ごとに名言カテゴリまたは偉人候補を選ぶ
5. 名言を使う場合は、英語原文をそのまま歌詞にしない。中核メッセージを 1 文の essence に抽出してから、曲の scene と persona vocabulary に合わせて再構築する
6. Lyrics は V5.5 向けに section tags を明示する。基本形は `[Intro]`, `[Verse 1]`, `[Pre-Chorus]`, `[Chorus]`, `[Verse 2]`, `[Instrumental]`, `[Bridge]`, `[Final Chorus]`, `[Extended Outro]`, `[Outro]`。`[Verse]` / `[Chorus]` だけでなく `[Intro]` `[Pre-Chorus]` `[Bridge]` `[Extended Outro]` `[Outro]` も曲ごとの scene / persona に合わせて書き分け、他の曲から本文を流用しない（Suno は歌詞テキストに強く追従するため、これらが同一だと全曲の入り・終わりが似通う）
7. `suno-lyrics.md` と `suno-lyrics.json` を `20-documentation/` に出力する。`preserve_existing: true` の場合、既存 entry は上書きしない
8. `yt-suno-verify` 通過後、別コンテキスト reviewer が `suno-lyrics.json` のみを読み、entry ごとに `PASS` / `FAIL` + 理由を出す。`FAIL` entry のみ最大 2 周まで再生成し、上限到達時は残課題をユーザーに提示する
9. 出力後、`/suno` に戻って Style と Lyrics をマージする

## Output Contract

### `20-documentation/suno-lyrics.json`

JSON root は配列。各 entry は `/suno` が `name` でマージできる形にする:

```json
[
  {
    "name": "夜明けの記憶 — Dawn Memory",
    "lyrics": "[Intro]\n...\n\n[Verse 1]\n...",
    "style": null,
    "review_context": {
      "collection_theme": "quiet recovery after a long winter",
      "scene": "first light entering a small kitchen",
      "mood": "warm, restrained, hopeful",
      "persona_target": "sleep-deprived adult listener seeking calm",
      "persona_vocabulary": ["ゆっくり", "あたたかい", "ほどける"],
      "quote_essence": "small daily courage matters more than dramatic change"
    }
  }
]
```

- `name` は `/suno` の最終 prompt entry name と完全一致させる
- `lyrics` は Suno Lyrics 欄へ入れる歌詞。言語は `config/skills/suno-lyric.yaml::lyric.language` に従う
- `style` は `null` のままにする。Style は `/suno` が埋める
- `review_context` は reviewer 専用の補助情報。`collection_theme`, `scene`, `mood`, `persona_target`, `persona_vocabulary`, `quote_essence` を含め、`references/review-rubric.md` の判定観点を JSON だけで検証できるようにする。`/suno` の merge loader は `name` / `lyrics` だけを使用し、この補助フィールドを無視してよい

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
- `[Intro]` `[Pre-Chorus]` `[Bridge]` `[Extended Outro]` `[Outro]` の section 本文が、曲間で一言一句同一になっていない（同一曲内での `[Chorus]` / `[Final Chorus]` の反復は正常な曲構成なので対象外）
- 機械チェックを実行して exit 0 を確認する: `python .claude/skills/suno-lyric/references/check_lyric_duplication.py <collection>/20-documentation/suno-lyrics.json`
- 曲間重複が検出された場合は出力を完了扱いにせず、該当 section を曲ごとの scene / persona に合わせて書き分け直してから再チェックする（Suno 生成後に発覚すると手戻りできず、クレジットと生成時間が無駄になる）

## Next Step

完了後は `/suno` を実行する。`/suno` は `suno-lyrics.json` を優先して読み、Style と Lyrics を `suno-prompts.json` にマージする。
