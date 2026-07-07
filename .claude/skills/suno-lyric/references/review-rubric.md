# Suno Generator-Reviewer Review Rubric

このルーブリックは `/suno-lyric` と `/suno` の generator-reviewer 分離で使う意味的品質検証の単一ソース。reviewer は生成時の会話やメモを読まず、対象成果物 JSON とこのファイルだけを読む。

## 対象成果物

- `/suno-lyric`: `20-documentation/suno-lyrics.json`
- `/suno`: `20-documentation/suno-prompts.json`

## JSON-only 入力契約

reviewer は対象成果物 JSON とこのルーブリックだけを読む。生成時の会話、pattern draft、設定ファイル、分析メモ、外部資料を追加で読まない。

`/suno-lyric` の `suno-lyrics.json` は各 entry に `review_context` を持ち、少なくとも `collection_theme`, `scene`, `mood`, `persona_target`, `persona_vocabulary`, `quote_essence` を含む。reviewer は theme / scene / mood / persona vocabulary / 名言 essence の判定をこの `review_context` と `lyrics` だけで行う。`review_context` が欠落している、空、または判定観点に必要なフィールドが足りない `/suno-lyric` entry は、外部資料で補完せず `FAIL` とする。

`/suno` の `suno-prompts.json` は既存 consumer 互換のため、entry の必須 field を `name`, `style`, `lyrics` のまま維持する。reviewer は `name`, `style`, `lyrics` と、存在する場合のみ More Options の補助 field（例: `style_influence`, `weirdness`, `vocal_gender`, `exclude_styles`）だけで判定する。`/suno` entry に `review_context` は要求しない。不足する theme / scene / quote 情報を外部資料で補完してはならず、JSON 内に証拠がない観点は「判定不能な外部文脈」として理由に明記し、`review_context` 欠落だけを理由に `FAIL` しない。

## 判定形式

各 entry について、以下の形式で必ず 1 件ずつ出力する。

```text
entry: <name>
status: PASS | FAIL
reason: <PASS または FAIL の根拠を 1-3 文で記述>
```

`FAIL` の entry が 1 件でもあれば成果物全体は未完了。generator は `FAIL` entry のみを再生成し、`PASS` entry は変更しない。

## 判定観点

### 1. テーマ・名言エッセンスの反映度

- `/suno-lyric` `PASS`: collection theme、scene、mood、persona vocabulary、名言 essence が entry 固有の表現として反映されている
- `/suno` `PASS`: `name`, `style`, `lyrics` に存在する theme / scene / mood / quote evidence が entry 固有の Style 方針として矛盾なく反映されている
- `FAIL`: JSON 内 evidence と無関係な一般論、名言原文の表層コピー、scene と矛盾する語彙、entry name と本文の不一致がある

### 2. 曲間の同質化

- `PASS`: section 構成、語彙、モチーフ、情景、Style の質感が entry 間で識別できる
- `FAIL`: 複数 entry が同じ導入、同じ比喩、同じ chorus motif、同じ texture / rhythm feel に寄りすぎている

### 3. Section tag 構成の妥当性

- `/suno-lyric` `PASS`: Suno V5.5 が解釈しやすい section tags があり、entry の展開に対応している
- `/suno` `PASS`: `lyrics` に section tags がある場合は展開と対応している。インスト entry では `[Instrumental]` と終端 tag があり、Style と Lyrics の責務が混ざっていない
- `FAIL`: tag が不足している、tag だけが並ぶ、section の順序が破綻している、Lyrics と Style の責務が混ざっている

### 4. 不自然な表現・禁止表現

- `PASS`: 日本語 / 英語として自然で、Suno policy や skill config の禁止語を避けている
- `FAIL`: 直訳調、意味不明な抽象語、歌いにくい過密行、禁止形容詞、雨音・環境音 NG ワード、アーティスト名が含まれる

## 再検証ループ

1. `bunx tayk suno-verify <collection-path>` が exit 0 で通過した成果物だけを reviewer が読む
2. reviewer は entry ごとに `PASS` / `FAIL` と理由を出す
3. generator は `FAIL` entry のみを再生成する
4. 再生成後は `bunx tayk suno-verify` からやり直す
5. ループ上限は 2 周。2 周後も `FAIL` が残る場合は、残った entry name、FAIL 理由、次に直す観点をユーザーに提示して停止する
