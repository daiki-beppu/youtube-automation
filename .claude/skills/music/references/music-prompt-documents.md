# Music prompt structured documents

- `書き込む`: `collections/<id>/20-documentation/minimax-prompt.json`, `collections/<id>/20-documentation/minimax-prompt.html`

`/music` の prompt 正本は `references/music-prompt.schema.json` に準拠する JSON と、同 basename の HTML pair とする。

HTML生成直後、親 orchestrator は生成されたHTMLの絶対pathをユーザーが開けるMarkdown linkで提示し、曲数、engine、各cardで確認するstyle / lyrics / optionsを要約する。手動承認ではこの提示後にだけ選択CLIを開始し、approve完了まで `assets.music_prompts` を更新しない。自動承認でもbrowserとbroker待機だけを省略し、HTML linkと採用内容の要約を完了報告へ必ず含める。

手動承認では永続HTMLを `uv run yt-music-prompt-select --collection <collection-path>` で同 basename に再生成して表示し、product-neutralなsingle-use loopback brokerから `approve` / `reject` の候補IDだけを受け取る。
返却後もartifact digestと検証済みJSONを再確認し、HTML・brokerから任意path、command、state patchを受け取らない。
Web失敗は未承認のまま停止し、会話選択へ黙ってfallbackしない。browserなしは `--transport terminal` を明示する。
`skip_generation_approval: true` など既存の自動承認経路では `uv run yt-music-prompt-select --collection <collection-path> --automatic` を使い、HTML表示とbroker待機を省略する。
Codex / Claudeとも同じCLI契約を使い、製品固有session APIへmessageを注入しない。

| engine | JSON 正本 | 承認表示 |
|---|---|---|
| Suno | `20-documentation/suno-prompts.json` | `20-documentation/suno-prompts.html` |
| Lyria | `20-documentation/lyria-prompt.json` | `20-documentation/lyria-prompt.html` |
| MiniMax | `20-documentation/minimax-prompt.json` | `20-documentation/minimax-prompt.html` |

inventory上の正準pathは `collections/<id>/20-documentation/minimax-prompt.json` とし、他engineと同じmusic ownerが公開する。

各 entry は `name`、`style`（Lyria / MiniMax は最終 prompt）、`lyrics`、`options`、`track_role`、`review` を持つ。任意の `title`、`sections`、`quality` も同じcardに表示する。Suno の More Options と Lyria / MiniMax の model / bpm / intensity / mode / reference image / duration は `options` に保存する。生成根拠は root `provenance.source_paths` と必要に応じて `insight_ids` に固定する。album flowとcard内表示順は schema の `x-view` が正本で、HTMLを手編集しない。

## fail-closed publication

1. generator は未公開 candidate JSON を作る。既存の品質基準・prompt本文・options値は変更しない。
2. Suno は既存 `uv run yt-suno-verify <collection-path>`、Lyria は `references/generate.md` の禁止語・parameter checkを先に完走する。各 entry の `review.verify_status` は成功時だけ `pass` にする。
3. 別コンテキストの semantic review をファイル全体に実行する。各 entry の `review.semantic_status` は成功時だけ `pass` にし、理由を `notes` に保存する。
4. 全 entry が両方 `pass` の candidate だけを共通CLIで公開する。

```bash
uv run yt-document-migrate <candidate.json> \
  --target <collection>/20-documentation/<suno-prompts|lyria-prompt|minimax-prompt>.json \
  --schema music-prompt.schema.json \
  --workflow-state <collection>/workflow-state.json
```

既存 `suno-prompts.md` + legacy `suno-prompts.json` または `lyria-prompt.md` がある場合、先に利用者へ移行の Yes / No を確認する。Yes の場合だけ `--migration-decision yes` を追加する。No の場合は `--migration-decision no` を指定して既存成果物とstateを保持する。pair公開・schema検証・JSON/HTML再読込の後もstateは未承認のまま保持し、`yt-music-prompt-select` が返却IDとJSON digestを再検証した後だけ owner API で `assets.music_prompts = true` にする。browser/renderer失敗、stale pair、digest mismatch、replay、`reject` はstateを変更しない。browserなしの明示fallbackは `--transport terminal` で候補を得て、会話確認後に `--candidate-id approve|reject` を指定する。

downstream（Suno helper配信、playlist照合、選曲、master、alignment/planning入力）は `read_suno_prompt_entries` または共通 `read_published_json_document` を通し、対応HTMLを持つ検証済みJSONだけを読む。MarkdownやHTMLの直接parseをfallbackにしない。

## 再開時の承認照合

承認 finalizer は `assets.music_prompts = true` と `music_prompt_approved_digest` を同時に記録する。chain の prompt 判定は既存 reader で JSON/HTML pair・schema を検証し、現在の JSON digest と承認 digest が一致するときだけ skip する。同じ成果物の再開で機械検証や AI semantic review を再実行しない。

JSON 未作成は run、不正 JSON・空 entries・HTML 欠落・pair 不一致・未承認・承認後の変更は blocked として `/music --prompt` の修復経路を示す。digest 未記録の旧承認も再承認が必要。pair が正常で既存 review が pass なら再生成せず `yt-music-prompt-select` で現在の成果物を再承認する。JSON を変えた場合は変更内容を検証・review してから公開・承認する。
