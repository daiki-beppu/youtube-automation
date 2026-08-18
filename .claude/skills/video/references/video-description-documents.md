# 動画説明の構造化文書契約

`/video --describe` の正本は `video-description.schema.json` 準拠の
`20-documentation/descriptions.json` と、同 basename の `descriptions.html` pair とする。
JSON は title、最終 description、表示順の section、track list、tags、localizations、provenance、
quality check を保持する。HTML は人間確認専用で、upload / metadata consumer は parse しない。

生成内容は公開先とは別の candidate JSON に保存し、全 quality check を `pass` にしてから次を実行する。

```bash
uv run yt-document-migrate <candidate.json> \
  --target <collection-path>/20-documentation/descriptions.json \
  --schema video-description.schema.json \
  --workflow-state <collection-path>/workflow-state.json
```

既存 `descriptions.md` がある場合は、利用者へ移行の Yes / No を確認する。Yes の場合だけ
`--migration-decision yes`、No の場合は `--migration-decision no` を指定する。pair の schema 検証、
HTML 再生成照合、JSON/HTML 再読込が成功した後だけ Markdown を削除し、workflow-state owner 経由で
`assets.description = true` にする。失敗時は旧 Markdown、pair、state を rollback する。

localizations が非空なら、その値を upload 時の最終翻訳として使う。localizations が空 object の場合は
「文書側に最終翻訳なし」と扱い、workflow-state.json の scene_phrases から metadata generator が生成した
翻訳を維持する。空 object で生成済み翻訳を消してはならない。

localization の必須値、title 上限、quality status / 各 check のいずれかが不正なら公開しない。
公開済み pair の片方欠損・改変も state / preflight / upload を成功扱いにしない。
