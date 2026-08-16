## Overview

`/music --lyric` は Suno / MiniMax ボーカル曲の **Lyrics 専任**。`/music --prompt` は orchestration + Style / title / scene / JSON merge を担当し、本 skill は歌詞本文だけを作る。

```
/music --lyric  ->  20-documentation/suno-lyrics.{md,json}
                       |
/music --prompt        ->  20-documentation/suno-prompts.{md,json}
                       |
/music --generate ->  Suno UI / MiniMax Music API
```

## Subagent Contract

- **入力**: 対象コレクション、`20-documentation/suno-patterns.yaml`、必要な設定ファイル
- **成果物**: `20-documentation/suno-lyrics.md`、`20-documentation/suno-lyrics.json`、機械検証と semantic review の結果
- **委譲しない処理**: 引用候補と歌詞方針の選択。メインが確定してから起動する
- **例外**: 入力確認に必要な `workflow-state.json::planning.music` を読み取ってよい（書き込みは不可）

subagent は `workflow-state.json` へ書き込まず `AskUserQuestion` を実行しない。承認が要る処理は、メインが承認を得るまで委譲しない。完了報告は `status: success | failure`、成果物の絶対パス一覧、エラー。成果物の存在検証と owner CLI 実行はメインが行う。

## Responsibilities

- 曲ごとの title / scene / mood を読み、1 曲 1 歌詞を作る
- 必要に応じて名言やテーマのエッセンスを抽出し、原文を直接コピーせず歌詞へ再構築する
- Suno V5.5 が読みやすい section tag 付き Lyrics を出力する
- レビュー用 Markdown と `/music --prompt` が機械的にマージできる JSON を出力する

この skill は Style、genre_line、Exclude Styles、Suno More Options、Suno UI 操作を扱わない。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/music/config.default.yaml::lyric`
2. `config/skills/music.yaml::lyric`（存在する場合）

合成規則は `youtube_automation.configuration.skills.load_skill_config("music.lyric")` と同じで、チャンネル上書きが優先される。存在しない override は未設定として扱い、勝手に作成しない。このスキルが `/music --prompt` の skill-config を直接参照する段階では、`suno` 側の `config.default.yaml` と `config/skills/music.yaml::prompt` も同じ手順で読む。

## 前提

以下を確認し、満たさなければ前工程を案内して停止する（機械的な停止条件は後述の Hard Gates が正）:

- チャンネルの `music_engine` が `suno` または `minimax` で、`genre_line` または `suno-patterns.yaml::mode` がボーカルを示すこと。`lyria` とインストゥルメンタルのみのチャンネル / コレクションでは歌詞生成不要として停止する
- 対象コレクションの `20-documentation/suno-patterns.yaml` が存在すること。無ければ先に `/music --prompt` の pattern draft 作成を案内して停止する
- persona reference として `docs/channel/personas/persona-definition.md` を読む。無い場合のみ旧 `docs/audience-persona.md` を legacy fallback として参照する

## Inputs

対象 collection は `$ARGUMENTS`、または現在の collection directory とする。

読むもの:

- `20-documentation/suno-patterns.yaml`: 曲名、scene、mood tag
- `workflow-state.json::planning.music`: mood / atmosphere / tempo / instruments
- `config/skills/music.yaml::prompt.genre_line`: ボーカルモード判定
- `config/skills/music.yaml::lyric`: 任意のチャンネル上書き
- `docs/channel/personas/persona-definition.md`: persona vocabulary と避ける語彙。無い場合のみ旧 `docs/audience-persona.md` を legacy fallback として参照可

## Quote Source Safety

名言取得元は `https://iyashitour.com` に限定する。`config/skills/music.yaml::lyric.source.base_url` を上書きする場合も、scheme は `https`、host は `iyashitour.com` のみ許可する。

許可する path は次の 2 種のみ:

- `/meigen/` 配下（偉人別・カテゴリ別のインデックスページ）
- `/meigen/` 配下のページからリンクで辿った `/archives/<ID>`（`<ID>` は数字。英語名言の原文ページ）への 1 ホップ限定。`/archives/<ID>` を起点にさらに別ページへ辿ることはしない

以下はすべて停止する: `localhost`、private / link-local IP、IP literal、別 host、`..` を含む path、上記の許可 path 以外へのアクセス。別サイトを使う場合は自動取得せず、人間が取得済み引用メモを渡してから続行する。

## Hiragana Lyrics Guide

`config/skills/music.yaml::lyric.lyric.language: ja` の場合、歌詞は**ひらがなで書く**。Suno は漢字の読みを頻繁に誤るため、ひらがな表記で発音精度を確保する。カタカナは外来語にのみ使用可。

## Hard Gates

1. `music_engine` が `suno` / `minimax` のどちらでもない場合は停止する
2. `genre_line` または `suno-patterns.yaml::mode` がボーカルを示さない場合は、歌詞生成不要として停止する
3. `20-documentation/suno-patterns.yaml` が無い場合は停止し、先に `/music --prompt` の pattern draft を作るよう案内する
4. `workflow-state.json::planning.music` が空でも完全停止はしないが、曲ごとの scene と persona reference を優先して進める

## 完了条件

`20-documentation/suno-lyrics.md` / `suno-lyrics.json` が出力され、`check_lyric_duplication.py` と `uv run yt-suno-verify` がともに exit 0、かつ reviewer の semantic review で全 entry が `PASS` になっていること（詳細は Validation セクションが正）。

## Generator-Reviewer Quality Gate

歌詞本文の作成は generator に委譲し、品質検証は生成とは別コンテキストの reviewer が行う。Claude Code では subagent 起動として扱い、Codex では同等の別エージェント / 別コンテキスト実行に読み替える。

generator は `suno-patterns.yaml`、persona reference、設定、必要な References を読んで `20-documentation/suno-lyrics.md` と `20-documentation/suno-lyrics.json` を作る。reviewer は生成時のメモや会話を読まず、成果物 `20-documentation/suno-lyrics.json` と `references/review-rubric.md` のみを読んで検証する。

`suno-lyrics.json` は reviewer が JSON だけでテーマ適合性を判定できるよう、各 entry に reviewer-only の `review_context` を必ず含める。`review_context` が欠落している entry は reviewer が外部資料で補わず `FAIL` とし、generator に再生成させる。

検証順序は必ず直列にする:

1. `uv run yt-suno-verify <collection-path>` を実行し、曲数・entry name・section tag・文字数などの機械的検証が exit 0 で通過したことを確認する
2. その後に reviewer が `references/review-rubric.md` に従って LLM semantic review を実行する
3. reviewer は entry ごとに `PASS` / `FAIL` と理由を出す
4. `FAIL` entry のみ generator に再生成させ、`uv run yt-suno-verify` → LLM semantic review を再実行する
5. 再生成ループは最大 2 周。2 周後も `FAIL` が残る場合は完了扱いにせず、残課題（entry name、FAIL 理由、次に直す観点）をユーザーに提示して引き継ぐ

## References

必要になった時だけ読む:

- 詳細な section 構造と例: `references/lyric-templates.md`
- 名言カテゴリと persona affinity: `references/persona-quote-affinity.md`
- 曲間セクション重複の機械チェック: `references/check_lyric_duplication.py`
- generator-reviewer 分離の意味的品質検証ルーブリック: `references/review-rubric.md`

## Workflow

1. 歌詞生成を generator subagent（Codex では別コンテキスト実行）に委譲する
2. `suno-patterns.yaml` から最終 entry name を作る。`/music --prompt` と同じく `{name_jp} — {name_en}`、複数 scene の場合は ` (Variation N)` を付ける
3. 各 entry に mood tag を割り当てる。明示 `mood` が無ければ scene / title / planning.music から推定する
4. `config/skills/music.yaml::lyric.affinity_weights` と persona reference から、曲ごとに名言カテゴリまたは偉人候補を選ぶ
5. 名言を使う場合は、英語原文をそのまま歌詞にしない。中核メッセージを 1 文の essence に抽出してから、曲の scene と persona vocabulary に合わせて再構築する
6. Lyrics は V5.5 向けに section tags を明示する。基本形は `[Intro]`, `[Verse 1]`, `[Pre-Chorus]`, `[Chorus]`, `[Verse 2]`, `[Instrumental]`, `[Bridge]`, `[Final Chorus]`, `[Extended Outro]`, `[Outro]`。`[Verse]` / `[Chorus]` だけでなく `[Intro]` `[Pre-Chorus]` `[Bridge]` `[Extended Outro]` `[Outro]` も曲ごとの scene / persona に合わせて書き分け、他の曲から本文を流用しない（Suno は歌詞テキストに強く追従するため、これらが同一だと全曲の入り・終わりが似通う）
7. `suno-lyrics.md` と `suno-lyrics.json` を `20-documentation/` に出力する。`preserve_existing: true` の場合、既存 entry は上書きしない
8. `uv run yt-suno-verify <collection-path>` 通過後、別コンテキスト reviewer が `suno-lyrics.json` のみを読み、entry ごとに `PASS` / `FAIL` + 理由を出す。`FAIL` entry のみ最大 2 周まで再生成し、上限到達時は残課題をユーザーに提示する
9. 出力後、Suno は `/music --prompt` に戻って Style と Lyrics をマージし、MiniMax は `/music --generate` が検証済み `suno-lyrics.json` を直接消費する

## Output Contract

### `20-documentation/suno-lyrics.json`

JSON root は配列。各 entry は `/music --prompt` が `name` でマージできる形にする:

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

- `name` は `/music --prompt` の最終 prompt entry name と完全一致させる
- `lyrics` は Suno Lyrics 欄へ入れる歌詞。言語は `config/skills/music.yaml::lyric.lyric.language` に従う
- `style` は `null` のままにする。Style は `/music --prompt` が埋める
- `review_context` は reviewer 専用の補助情報。`collection_theme`, `scene`, `mood`, `persona_target`, `persona_vocabulary`, `quote_essence` を含め、`references/review-rubric.md` の判定観点を JSON だけで検証できるようにする。`/music --prompt` の merge loader は `name` / `lyrics` だけを使用し、この補助フィールドを無視してよい

### `20-documentation/suno-lyrics.md`

人間レビュー用。各曲ごとに以下を残す:

- entry name
- mood / persona target
- 使用した名言または essence
- Lyrics (`config/skills/music.yaml::lyric.lyric.language` に従う)
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
- 機械チェックを実行して exit 0 を確認する: `python .claude/skills/music/references/check_lyric_duplication.py <collection>/20-documentation/suno-lyrics.json`
- 成果物チェックを実行して exit 0 を確認する: `uv run yt-suno-verify <collection-path>`
- 曲間重複が検出された場合は出力を完了扱いにせず、該当 section を曲ごとの scene / persona に合わせて書き分け直してから再チェックする（Suno 生成後に発覚すると手戻りできず、クレジットと生成時間が無駄になる）

## Next Step

完了後、Suno は `/music --prompt` を実行し、`suno-lyrics.json` を優先して Style と Lyrics を `suno-prompts.json` にマージする。MiniMax は `/music --generate` を実行し、同じ `suno-lyrics.json` を `yt-generate-minimax-master --lyrics` へ渡す。
