---
name: audit
purpose: 振り返る
description: "Use when 整合性・動画本体・公開後メタデータ・価値ループの監査を一括実行または一段だけ実行するとき。フラグなしは4監査を状態判定付きで進め、音楽ムード × サムネ × タイトルは --alignment、動画解析は --video、ローカルと YouTube のメタデータ整合は --metadata、価値ループは --value-loop を使う。「監査一括実行」「整合性チェック」「価値ループ監査」「動画解析」「メタデータ監査」で発動"
---

## 前後工程

- `前工程`: `/channel-strategy --constraints`, `/thumbnail`, `/music`, `/publish --upload`, `/publish`
- `後工程`: `/wf-new`, `/music --prompt`, `/audit --alignment`, `/analytics --flop`, `/video --describe`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `docs/plans/alignment-audit.{json,html}`, `data/video_analysis/<channel>/<video-id>.json`, `reports/video_analysis/<channel>.{json,html}`
- `読み込む`: `collections/<id>/10-assets/thumbnail.jpg`, 検証済み `collections/<id>/20-documentation/suno-prompts.json` または `lyria-prompt.json`, 検証済み `collections/<id>/20-documentation/descriptions.json` + 同 basename HTML, `collections/<id>/20-documentation/upload_tracking.json`, `collections/<id>/workflow-state.json`, `data/benchmark_*.json`, 検証済み `docs/channel/personas/persona-definition.json`, `docs/plans/viewing-scene-matrix.json`, `docs/channel/creative-constraints.json`, `reports/analysis_*.json`, `data/insights.jsonl`, `config/channel/*.json`, `config/skills/audit.yaml`

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| Vertex AI Gemini（`--video` の `yt-video-analyze`） | 未解析の対象動画数 × 1 call | `--source` / `--top` / 対象動画数 / `--force` / `analysis_window_sec` |
| YouTube Data API v3 videos.list（`--metadata`） | remote 監査で 1 call = 1 unit | `--local` 指定時は 0。`--alignment` と `--value-loop` は外部 API を呼ばない |

- 上限 / 承認: 確認プロンプトは挟まない。`--video` の `--source` と `--top` で対象数を絞り、既存の有効な解析結果は再利用する。

## 設定読み込みゲート

video / metadata mode は次を deep-merge し、チャンネル上書きを優先する。

1. `.claude/skills/audit/config.default.yaml` の mode 名の節
2. `config/skills/audit.yaml` の同名節（存在する場合）

実行経路は `load_skill_config("audit.video")` / `load_skill_config("audit.metadata")` を使う。移行前の `config/skills/video-analyze.yaml` / `config/skills/metadata-audit.yaml` は互換入口 `load_skill_config("video-analyze")` / `load_skill_config("metadata-audit")` として同じ設定に読み込むが、存在しない override を勝手に作成しない。

## モード判定

`$ARGUMENTS` から、下表に登録された mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い alignment → video → metadata → value-loop を状態判定付きで進める
- 現段で実装済みの mode は `--alignment` / `--value-loop` / `--video` / `--metadata`
- mode は最大 5 件とし、判定規則を複製しない

| mode | 読む reference |
|---|---|
| `--alignment` | `references/alignment.md` |
| `--value-loop` | `references/value-loop.md` |
| `--video` | `references/video.md` |
| `--metadata` | `references/metadata.md` |

## 一括実行

`references/audit-chain-manifest.json` と `references/audit-chain-state.py` が存在し、manifest の `chainId`、step 順、step mode、approval gate、状態判定 script が妥当であることを確認する。欠損、未知・重複 step、複数 mode、`approvalGate.skip != true` があれば停止する。全 mode は読み取り専用監査またはローカル監査レポート生成だけを行うため、chain の承認ゲートを省略する。

チャンネルルートで manifest 順に次を実行する。

```bash
uv run python .claude/skills/audit/references/audit-chain-state.py \
  --channel-dir . --step <alignment|video|metadata|value-loop>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 完了済みとして次段へ進む |
| 10 | `run` | step の mode reference を読み、その一段を実行する |
| 20 | `blocked` | `reason` と不足成果物を提示して停止する |
| その他 | `error` | manifest / script / 入力 JSON のエラーとして停止する |

実行後は同じ状態判定を再実行する。alignment / video が exit 0 にならなければ停止する。metadata / value-loop は診断結果を永続化しないため、実行後も exit 10 が正常である。metadata の表示結果は同じ会話内で value-loop の横断診断へ渡す。途中失敗時はその段で止め、再発動時は先頭から状態判定して完了済み段を skip する。

## 完了条件

- フラグなし: alignment と video が `skip` または実行後 `skip`、metadata と value-loop が `run` となり、4 mode の監査結果を表示している
- `--alignment`: `references/alignment.md` の完了条件を満たしている
- `--value-loop`: `references/value-loop.md` の完了条件を満たしている
- `--video`: `references/video.md` の完了条件を満たしている
- `--metadata`: `references/metadata.md` の完了条件を満たし、自身では修正していない
- 未知の mode または排他違反では、reference を読まず停止している

実行 mode、監査対象、判定結果、保存したレポート（ある場合）を短く報告する。
