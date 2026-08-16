# Music prompt structured documents

`/music` の prompt 正本は `references/music-prompt.schema.json` に準拠する JSON と、同 basename の HTML pair とする。

| engine | JSON 正本 | 承認表示 |
|---|---|---|
| Suno | `20-documentation/suno-prompts.json` | `20-documentation/suno-prompts.html` |
| Lyria | `20-documentation/lyria-prompt.json` | `20-documentation/lyria-prompt.html` |

各 entry は `name`、`style`（Lyria は最終 prompt）、`lyrics`、`options`、`track_role`、`review` を持つ。Suno の More Options と Lyria の model / bpm / intensity / mode / reference image / duration は `options` に保存する。生成根拠は root `provenance.source_paths` と必要に応じて `insight_ids` に固定する。表示順と表形式は schema の `x-view` が正本で、HTMLを手編集しない。

## fail-closed publication

1. generator は未公開 candidate JSON を作る。既存の品質基準・prompt本文・options値は変更しない。
2. Suno は既存 `uv run yt-suno-verify <collection-path>`、Lyria は `references/generate.md` の禁止語・parameter checkを先に完走する。各 entry の `review.verify_status` は成功時だけ `pass` にする。
3. 別コンテキストの semantic review をファイル全体に実行する。各 entry の `review.semantic_status` は成功時だけ `pass` にし、理由を `notes` に保存する。
4. 全 entry が両方 `pass` の candidate だけを共通CLIで公開する。

```bash
uv run yt-document-migrate <candidate.json> \
  --target <collection>/20-documentation/<suno-prompts|lyria-prompt>.json \
  --schema music-prompt.schema.json \
  --workflow-state <collection>/workflow-state.json
```

既存 `suno-prompts.md` + legacy `suno-prompts.json` または `lyria-prompt.md` がある場合、先に利用者へ移行の Yes / No を確認する。Yes の場合だけ `--migration-decision yes` を追加する。No の場合は `--migration-decision no` を指定して既存成果物とstateを保持する。pair公開・schema検証・JSON/HTML再読込がすべて成功した後だけ Markdown を削除し、workflow-state owner経由で `assets.music_prompts = true` にする。失敗時は旧成果物、pair、stateをrollbackする。

downstream（Suno helper配信、playlist照合、選曲、master、alignment/planning入力）は `read_suno_prompt_entries` または共通 `read_published_json_document` を通し、対応HTMLを持つ検証済みJSONだけを読む。MarkdownやHTMLの直接parseをfallbackにしない。
