---
name: audit
purpose: 振り返る
description: "Use when 整合性・価値ループ・動画本体を監査するとき。音楽ムード × サムネ × タイトルは --alignment、シーン定義 → 制約翻訳 → 公開前ゲート → 指標還流は --value-loop、動画のフック構造・シーン・BGM 展開は --video を使う。「整合性チェック」「価値ループ監査」「動画解析」「retention drop」で発動"
---

## 前後工程

- `前工程`: `/channel-strategy --constraints`, `/thumbnail`, `/music`
- `後工程`: `/wf-new`, `/music --prompt`, `/audit --alignment`, `/flop-analysis`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `docs/plans/alignment-audit.md`, `data/video_analysis/<channel>/<video-id>.json`, `reports/video_analysis/<channel>.md`
- `読み込む`: `collections/<id>/10-assets/thumbnail.jpg`, `collections/<id>/20-documentation/suno-prompts.md`, `collections/<id>/20-documentation/upload_tracking.json`, `collections/<id>/workflow-state.json`, `data/benchmark_*.json`, `docs/channel/personas/persona-definition.md`, `docs/plans/viewing-scene-matrix.md`, `docs/channel/creative-constraints.md`, `reports/analysis_*.json`, `data/insights.jsonl`, `config/skills/audit.yaml`

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| Vertex AI Gemini（`--video` の `yt-video-analyze`） | 未解析の対象動画数 × 1 call | `--source` / `--top` / 対象動画数 / `--force` / `analysis_window_sec`。`--alignment` と `--value-loop` は外部 API を呼ばない |

- 上限 / 承認: 確認プロンプトは挟まない。`--video` の `--source` と `--top` で対象数を絞り、既存の有効な解析結果は再利用する。

## 設定読み込みゲート

video mode は次を deep-merge し、チャンネル上書きを優先する。

1. `.claude/skills/audit/config.default.yaml` の `video:` 節
2. `config/skills/audit.yaml` の `video:` 節（存在する場合）

実行経路は `load_skill_config("audit.video")` を使う。移行前の `config/skills/video-analyze.yaml` は互換入口 `load_skill_config("video-analyze")` と同じ設定として読み込むが、存在しない override を勝手に作成しない。

## モード判定

`$ARGUMENTS` から、下表に登録された mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら互換入口として `--alignment` を実行する。chain manifest による状態判定は後続段で追加する
- 現段で実装済みの mode は `--alignment` / `--value-loop` / `--video`。`--metadata` は後続段で追加する予約名であり、現段では未知の mode として停止する
- mode は最大 5 件とし、判定規則を複製しない

| mode | 読む reference |
|---|---|
| `--alignment` | `references/alignment.md` |
| `--value-loop` | `references/value-loop.md` |
| `--video` | `references/video.md` |

## 完了条件

- フラグなし / `--alignment`: `references/alignment.md` の完了条件を満たしている
- `--value-loop`: `references/value-loop.md` の完了条件を満たしている
- `--video`: `references/video.md` の完了条件を満たしている
- 未知の mode または排他違反では、reference を読まず停止している

実行 mode、監査対象、判定結果、保存したレポート（ある場合）を短く報告する。
