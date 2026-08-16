# コレクション企画文書の保存・読込契約

`20-documentation/plan_proposals.json` を唯一の正本とし、同 basename の HTML を企画承認 gate の正規表示に使う。schema は `collection-plan.schema.json` を正とする。

通常企画と batch record 投影は `plan_id`, `collection_name`, `theme_slug`, `track_count`, `music_engine`, `final_title`, `target_persona`, `viewing_scene` の意味と命名を共有する。企画生成・ranking 規則は変更しない。

候補 JSON をユーザー承認後に作り、次の owner CLI で保存する。

```bash
uv run yt-document-migrate <candidate.json> \
  --target <collection>/20-documentation/plan_proposals.json \
  --schema collection-plan.schema.json \
  --workflow-state <collection>/workflow-state.json
```

既存 `plan_proposals.md` だけがある場合は移行可否を明示確認し、Yes だけ `--migration-decision yes`、No は `--migration-decision no` を付ける。No では Markdown と workflow state を変更しない。JSON+HTML pair の更新では移行 flag を付けない。

owner は schema、candidate 1件だけの `selected|auto_selected`、plan/evidence ID、HTML対応を検証し、pair を再読込できた後だけ `planning.generated`, `planning.final_title`, `planning.target_persona` を workflow-state owner API で更新する。schema/HTML/pair 検証失敗時は state を更新せず、既存 JSON/HTML/Markdown を rollback する。

後工程、freshness、batch resume は `read_published_json_document(..., RepositorySchema.COLLECTION_PLAN)` 相当で pair を fail-closed に検証し、JSON だけを入力にする。HTML や旧 Markdown を parse しない。
