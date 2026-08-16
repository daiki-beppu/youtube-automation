# チャンネル戦略文書の保存・読込契約

4 文書の JSON 正本は `channel-strategy.schema.json` で検証し、HTML は同じ basename へ生成する。

| mode | `document_type` | JSON 正本 |
|---|---|---|
| `--direction` | `direction` | `docs/channel/channel-direction.json` |
| `--persona` | `persona` | `docs/channel/personas/persona-definition.json` |
| `--scene` | `scene` | `docs/plans/viewing-scene-matrix.json` |
| `--constraints` | `constraints` | `docs/channel/creative-constraints.json` |

保存前に candidate JSON を作り、ユーザーが内容を承認した後だけ次を実行する。

```bash
uv run yt-document-migrate <candidate.json> \
  --target <上表のJSON正本> \
  --schema channel-strategy.schema.json
```

同 basename の Markdown だけが存在する場合は、既存 Markdown の移行可否を明示的に確認する。Yes のときだけ `--migration-decision yes`、No のときは `--migration-decision no` を付ける。No なら Markdown を維持して停止する。JSON+HTML pair がある更新では移行 flag を付けない。

CLI は JSON Schema に加え、scene の `persona_id`、persona/constraints の `scene_ids`、constraint/evidence ID を検証する。参照切れ、片方だけの pair、HTML 不一致では保存しない。失敗時は既存 JSON・HTML・Markdown を rollback する。

writer と downstream consumer は `read_published_json_document(..., RepositorySchema.CHANNEL_STRATEGY)` 相当で JSON+HTML pair を検証し、入力には JSON だけを使う。HTML や旧 Markdown を直接 parse しない。
