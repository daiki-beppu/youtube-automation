# コレクション企画文書の保存・読込契約

## 共通Web review lifecycle

企画候補は全件 `selection_status: proposed` の draft JSON として先に owner CLI へ渡し、永続 `plan_proposals.json` + `.html` pair を公開する。この draft 公開では `planning.generated` を更新しない。候補ごとに `music_direction` / `video_direction` / `thumbnail_direction` を保存し、previewがある場合はcollection内の `10-assets/plan-preview-<proposal_id>.<ext>` へ安全にコピーして、そのrelative pathを `preview_assets` に記録する。

企画候補の手動選択は、永続 `plan_proposals.html` と選択cardを開く製品非依存の
`uv run yt-collection-plan-select --collection <collection-path>` で行う。
共通brokerが返したmanifest内 `proposal_id`、企画JSON digest、全preview digestを再検証してから、同じownerが選択済みpairを公開し、既存どおりその成功後だけstateを投影する。選択candidateには `selection_source: web` を監査情報として保存する。
HTMLやbroker応答をJSON正本・任意path・command・state patchとして扱わない。renderer、browser、timeout、digest不一致は未選択のままfail-closedで停止し、会話選択へ黙って切り替えない。
browserのないterminal環境だけは `--transport terminal` を明示し、表示されたallowlistを通常のユーザー確認へ渡した後、同じCLIへ `--candidate-id <proposal_id>` を付けて再実行する。この経路も同じdigest検証・確定ownerを通し、`selection_source: terminal` を保存する。
自動選択経路は `uv run yt-collection-plan-select --collection <collection-path> --automatic` を使う。推奨順1位を同じID検証・確定ownerへ渡すが、HTML生成・browser表示・broker待機は行わず、`selection_source: automatic` を保存する。Codex / Claude固有のsession message APIは使用しない。

`20-documentation/plan_proposals.json` を唯一の正本とし、同 basename の HTML を企画承認 gate の正規表示に使う。schema は `collection-plan.schema.json` を正とする。

通常企画と batch record 投影は `plan_id`, `collection_name`, `theme_slug`, `track_count`, `music_engine`, `final_title`, `target_persona`, `viewing_scene` の意味と命名を共有する。企画生成・ranking 規則は変更しない。

候補 JSON はまず全件 `proposed` で作り、次の owner CLI でdraft pairを保存する。manual / terminal / automaticの選択確定後も同じCLI内部のwriterが更新pairに使われる。

```bash
uv run yt-document-migrate <candidate.json> \
  --target <collection>/20-documentation/plan_proposals.json \
  --schema collection-plan.schema.json \
  --workflow-state <collection>/workflow-state.json
```

既存 `plan_proposals.md` だけがある場合は移行可否を明示確認し、Yes だけ `--migration-decision yes`、No は `--migration-decision no` を付ける。No では Markdown と workflow state を変更しない。JSON+HTML pair の更新では移行 flag を付けない。

owner はdraftでは全件 `proposed`、確定時はcandidate 1件だけの `selected|auto_selected`、plan/evidence ID、HTML対応を検証する。確定pairを再読込できた後だけ `planning.generated`, `planning.final_title`, `planning.target_persona` を workflow-state owner API で更新する。schema/HTML/pair、proposal ID、JSON/preview digest、replayの検証失敗時は state を更新せず、既存 JSON/HTML/Markdown を保持する。

後工程、freshness、batch resume は `read_published_json_document(..., RepositorySchema.COLLECTION_PLAN)` 相当で pair を fail-closed に検証し、JSON だけを入力にする。HTML や旧 Markdown を parse しない。
