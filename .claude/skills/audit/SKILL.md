---
name: audit
purpose: 振り返る
description: "Use when 音楽ムード × サムネ × タイトルの整合性を読み取り専用で監査するとき。「整合性チェック」「タイトル見直し」「CTR改善」で発動。一段だけは排他的な --alignment を使う"
---

## 前後工程

- `前工程`: `/channel-strategy --constraints`, `/thumbnail`, `/music`
- `後工程`: `/flop-analysis`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `docs/plans/alignment-audit.md`
- `読み込む`: `collections/<id>/10-assets/thumbnail.jpg`, `collections/<id>/20-documentation/suno-prompts.md`, `collections/<id>/workflow-state.json`

## モード判定

`$ARGUMENTS` から、下表に登録された mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら現段で唯一実装済みの `--alignment` を実行する。chain manifest による状態判定は後続段で追加する
- 現段で実装済みの mode は `--alignment` のみ。`--value-loop` / `--video` / `--metadata` は後続段で追加する予約名であり、現段では未知の mode として停止する
- mode は最大 5 件とし、判定規則を複製しない

| mode | 読む reference |
|---|---|
| `--alignment` | `references/alignment.md` |

## 完了条件

- フラグなし / `--alignment`: `references/alignment.md` の完了条件を満たしている
- 未知の mode または排他違反では、reference を読まず停止している

実行 mode、監査対象、不整合件数、保存したレポートを短く報告する。
